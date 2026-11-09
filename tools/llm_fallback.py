#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""大模型兜底代理：优先 DeepSeek，出错/超时自动换 qwen-flash。

为什么需要它：
    主程序一次只认一个 OpenAI 兼容接口，没有「A 挂了换 B」的能力。
    所以在本地起一个极小的 OpenAI 兼容网关（默认 127.0.0.1:8787），
    主程序把它当普通接口用，换谁上场由这里决定。

关键设计：
    * 只在「还没有吐出第一个字」时切换服务商。一旦观众已经开始听到回复，
      中途换模型会说出两段不搭的话，所以宁可让它说完。
    * 流式（stream=true）和非流式都支持，SSE 原样透传，主程序无需改动。
    * 每次切换都会写日志，方便事后看是哪家拖了后腿。

用法：
    python tools\\llm_fallback.py            # 前台运行
    python tools\\llm_fallback.py --check    # 只体检各服务商，不常驻

配置：tools\\llm_fallback.json（服务商顺序、模型、首字节超时）
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

ROOT = Path(__file__).resolve().parent.parent
CONF_PATH = Path(os.environ.get("LLM_FALLBACK_CONFIG") or Path(__file__).resolve().with_name("llm_fallback.json"))
if not CONF_PATH.is_absolute():
    CONF_PATH = Path(__file__).resolve().with_name(str(CONF_PATH))

with CONF_PATH.open("r", encoding="utf-8-sig") as f:  # Windows 记事本/PS 写出的文件常带 BOM
    CONF = json.load(f)

PROVIDERS = CONF["providers"]
PORT = int(CONF.get("port", 8787))
FIRST_BYTE_TIMEOUT = float(CONF.get("first_byte_timeout", 8))
LOG_FILE = (CONF_PATH.parent / CONF.get("log_file", "../log/llm_proxy.log")).resolve()

app = FastAPI(title="大肥鱼 LLM 兜底代理")

_client: httpx.AsyncClient | None = None

# ---------------- token 统计 ----------------
STATS_FILE = (CONF_PATH.parent.parent / "out" / "token_stats.json").resolve()
_stats = {"prompt": 0, "completion": 0, "total": 0, "calls": 0, "last": None}


def load_stats():
    global _stats
    try:
        if STATS_FILE.exists():
            _stats.update(json.loads(STATS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass


def save_stats():
    try:
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATS_FILE.write_text(json.dumps(_stats, ensure_ascii=False, indent=2), encoding="utf-8")
        # 给前端页面直接读的一份（跨域友好，静态文件由 12345 服务）
        alt = STATS_FILE.parent.parent / "Live2D" / "token_stats.json"
        alt.write_text(json.dumps(_stats, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def add_usage(prompt: int, completion: int, total: int | None = None, model: str = ""):
    _stats["prompt"] += int(prompt or 0)
    _stats["completion"] += int(completion or 0)
    _stats["total"] += int(total if total is not None else (prompt or 0) + (completion or 0))
    _stats["calls"] += 1
    _stats["last"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "model": model,
                      "prompt": int(prompt or 0), "completion": int(completion or 0)}
    save_stats()


def usage_from_bytes(buf: bytes, model: str = ""):
    """从 SSE 尾巴里捞出最后的 usage 数字。

    DeepSeek 的 usage 里还嵌着 prompt_tokens_details.cached_tokens，
    用整体 JSON 正则容易被嵌套花括号骗过去，所以直接抓三个数字字段。
    """
    try:
        text = buf.decode("utf-8", "ignore")
    except Exception:
        return

    def last_int(name):
        vals = re.findall(r'"%s"\s*:\s*(\d+)' % name, text)
        return int(vals[-1]) if vals else 0

    p = last_int("prompt_tokens")
    c = last_int("completion_tokens")
    t = last_int("total_tokens")
    if p or c or t:
        add_usage(p, c, t, model)


load_stats()


def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d ") + line + "\n")
    except OSError:
        pass


def ready_providers():
    """只有拿到 key 的服务商才参与轮换。"""
    out = []
    for p in PROVIDERS:
        key = os.environ.get(p["env"], "").strip()
        if key:
            out.append((p, key))
        else:
            log(f"跳过 {p['name']}：环境变量 {p['env']} 为空")
    return out


def pick_headers(key: str):
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def build_body(provider, body: dict):
    """用服务商自己的模型名，其余参数（temperature/max_tokens/...）原样带过去。"""
    payload = dict(body)
    payload["model"] = provider["model"]
    # 让服务商在流的最后补一个 usage 块，用来统计 token
    if payload.get("stream"):
        so = dict(payload.get("stream_options") or {})
        so["include_usage"] = True
        payload["stream_options"] = so
    return payload


def env_proxy() -> str | None:
    """手动读代理，不走 httpx 的 trust_env。

    原因：系统里 NO_PROXY 常写成 `localhost,127.0.0.1,::1`，
    httpx 0.28 会把 `::1` 当成 `host:port` 解析，直接抛
    `InvalidURL: Invalid port: ':1]'`，整个请求就地失败。
    """
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        if "://" not in raw:
            raw = "http://" + raw
        try:
            parsed = httpx.URL(raw)
        except Exception:
            continue
        if parsed.host and parsed.port:
            return raw
    return None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        proxy = env_proxy()
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=6.0, read=90.0, write=30.0, pool=6.0),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
            trust_env=False,
            proxy=proxy,
        )
        log(f"HTTP 客户端已就绪，代理：{proxy or '直连'}")
    return _client


@app.get("/health")
async def health():
    return {
        "service": "llm-fallback-proxy",
        "providers": [p["name"] for p, _ in ready_providers()],
        "first_byte_timeout": FIRST_BYTE_TIMEOUT,
    }


@app.get("/v1/models")
async def models():
    return {
        "object": "list",
        "data": [{"id": p["model"], "object": "model", "owned_by": p["name"]} for p, _ in ready_providers()],
    }


async def forward_stream(messages_request: Request, body: dict):
    """逐个服务商尝试，谁先吐出第一个字节就用谁。"""
    providers = ready_providers()
    if not providers:
        return JSONResponse({"error": {"message": "没有可用的 API Key"}}, status_code=503)

    errors = []
    for provider, key in providers:
        url = provider["api"].rstrip("/") + "/chat/completions"
        payload = build_body(provider, body)
        started = time.time()
        try:
            stream_ctx = get_client().stream("POST", url, json=payload, headers=pick_headers(key))
            resp = await asyncio.wait_for(stream_ctx.__aenter__(), timeout=FIRST_BYTE_TIMEOUT)
        except asyncio.TimeoutError:
            errors.append(f"{provider['name']}: 连接超时")
            log(f"{provider['name']} 连接超时（>{FIRST_BYTE_TIMEOUT}s），换下一家")
            continue
        except Exception as e:
            errors.append(f"{provider['name']}: {type(e).__name__} {e}")
            log(f"{provider['name']} 连接失败：{type(e).__name__} {e}，换下一家")
            continue

        if resp.status_code != 200:
            text = (await resp.aread()).decode("utf-8", "replace")[:300]
            await resp.aclose()
            errors.append(f"{provider['name']}: HTTP {resp.status_code} {text}")
            log(f"{provider['name']} 返回 {resp.status_code}，换下一家：{text}")
            continue

        # ---- 拿到 200 了，开始等第一个内容块；等太久也换 ----
        chunks: list[bytes] = []
        committed = False
        try:
            iterator = resp.aiter_bytes()
            deadline = started + FIRST_BYTE_TIMEOUT
            while True:
                remain = deadline - time.time()
                if remain <= 0:
                    raise asyncio.TimeoutError
                try:
                    chunk = await asyncio.wait_for(iterator.__anext__(), timeout=remain)
                except StopAsyncIteration:
                    break
                if chunk:
                    chunks.append(chunk)
                    if b"data:" in chunk and b'"content"' in chunk:
                        committed = True
                        break

            if not committed and not chunks:
                raise asyncio.TimeoutError

            first_delay = time.time() - started
            log(f"{provider['name']} 接管（首字节 {first_delay:.2f}s，模型 {provider['model']}）")

            async def body_iter():
                tail = bytearray()
                try:
                    for c in chunks:
                        tail += c
                        del tail[:-1200]
                        yield c
                    async for c in iterator:
                        tail += c
                        del tail[:-1200]
                        yield c
                finally:
                    usage_from_bytes(bytes(tail), provider["model"])
                    await stream_ctx.__aexit__(None, None, None)

            return StreamingResponse(body_iter(), media_type="text/event-stream")
        except Exception as e:
            await stream_ctx.__aexit__(None, None, None)
            errors.append(f"{provider['name']}: 首字超时/异常 {type(e).__name__}")
            log(f"{provider['name']} 首字超时（>{FIRST_BYTE_TIMEOUT}s）或异常，换下一家：{type(e).__name__}")
            continue

    log("所有服务商都失败：" + " | ".join(errors))
    return JSONResponse(
        {"error": {"message": "所有服务商都失败", "detail": errors}},
        status_code=502,
    )


async def forward_once(body: dict):
    providers = ready_providers()
    if not providers:
        return JSONResponse({"error": {"message": "没有可用的 API Key"}}, status_code=503)

    errors = []
    for provider, key in providers:
        url = provider["api"].rstrip("/") + "/chat/completions"
        try:
            r = await get_client().post(url, json=build_body(provider, body), headers=pick_headers(key))
        except Exception as e:
            errors.append(f"{provider['name']}: {type(e).__name__} {e}")
            log(f"{provider['name']} 失败：{type(e).__name__}，换下一家")
            continue
        if r.status_code == 200:
            log(f"{provider['name']} 接管（非流式，模型 {provider['model']}）")
            try:
                u = (r.json() or {}).get("usage") or {}
                add_usage(u.get("prompt_tokens"), u.get("completion_tokens"),
                          u.get("total_tokens"), provider["model"])
            except Exception:
                pass
            return Response(r.content, media_type="application/json")
        errors.append(f"{provider['name']}: HTTP {r.status_code} {r.text[:200]}")
        log(f"{provider['name']} 返回 {r.status_code}，换下一家")

    log("所有服务商都失败：" + " | ".join(errors))
    return JSONResponse({"error": {"message": "所有服务商都失败", "detail": errors}}, status_code=502)


@app.get("/stats")
async def stats():
    return {
        "service": "llm-fallback-proxy",
        "prompt_tokens": _stats["prompt"],
        "completion_tokens": _stats["completion"],
        "total_tokens": _stats["total"],
        "calls": _stats["calls"],
        "last": _stats["last"],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    if body.get("stream"):
        return await forward_stream(request, body)
    return await forward_once(body)


async def check():
    """体检：逐家发一句话，报首字节和回复。"""
    print(f"配置文件：{CONF_PATH}")
    for provider, key in ready_providers():
        url = provider["api"].rstrip("/") + "/chat/completions"
        payload = {
            "model": provider["model"],
            "messages": [
                {"role": "system", "content": "只用一两句口语回答，20-50字。"},
                {"role": "user", "content": "大肥鱼你好，你是真人吗？"},
            ],
            "temperature": 0.9,
            "max_tokens": 120,
            "stream": True,
        }
        t0 = time.time()
        first = None
        buf = ""
        try:
            async with get_client().stream("POST", url, json=payload, headers=pick_headers(key)) as r:
                if r.status_code != 200:
                    text = (await r.aread()).decode("utf-8", "replace")[:200]
                    print(f"  {provider['name']:9} HTTP {r.status_code}  {text}")
                    continue
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        j = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    d = (j.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
                    if d:
                        first = first or (time.time() - t0)
                        buf += d
            print(f"  {provider['name']:9} 首字 {first or -1:.2f}s  总共 {time.time() - t0:.2f}s  {buf.strip()[:50]}")
        except Exception as e:
            print(f"  {provider['name']:9} ERR {type(e).__name__}: {str(e)[:150]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()

    if args.check:
        asyncio.run(check())
        return

    log(f"启动兜底代理 127.0.0.1:{args.port}，顺序：{' -> '.join(p['name'] for p, _ in ready_providers())}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
