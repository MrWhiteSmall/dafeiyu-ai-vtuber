#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""切换大肥鱼主程序用的大模型服务商（OpenAI 兼容接口）。

用法：
    python tools\\switch_llm.py --provider deepseek --key sk-xxxx
    python tools\\switch_llm.py --provider glm                 # key 从 GLM_API_KEY 读
    python tools\\switch_llm.py --provider dashscope --key sk-xxxx
    python tools\\switch_llm.py --show                         # 只看当前配置
    python tools\\switch_llm.py --test                         # 用当前配置发一次真实请求

原理：主程序 chat_type=chatgpt 走的是通用 OpenAI 兼容客户端，
只认 config.json 里这三项：openai.api（base_url）、openai.api_key、chatgpt.model。
所以换服务商 = 改这三项，代码一行都不用动。
"""
import argparse
import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.json"

PROVIDERS = {
    "proxy": {
        "api": "http://127.0.0.1:8787/v1",
        "model": "deepseek-chat",
        "env": "LOCAL_PROXY_KEY",
        "default_key": "local-fallback-proxy",
        "note": "本地兜底代理：DeepSeek 优先，超时/报错自动换 qwen-flash。要保证 tools\\llm_fallback.py 在跑",
    },
    "deepseek": {
        "api": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "env": "DEEPSEEK_API_KEY",
        "note": "deepseek-chat 是 V3 非思考模式；deepseek-reasoner 会先思考几十秒，直播不能用",
    },
    "glm": {
        "api": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "env": "GLM_API_KEY",
        "note": "glm-4-flash 免费且实测 1 秒内回，最省钱",
    },
    "dashscope": {
        "api": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-flash",
        "env": "DASHSCOPE_KEY",
        "note": "阿里云百炼兼容模式，qwen-flash 有免费额度",
    },
}


def port_listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def load():
    with CONFIG.open("r", encoding="utf-8") as f:
        return json.load(f)


def save(cfg):
    with CONFIG.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)


def show():
    cfg = load()
    keys = cfg["openai"]["api_key"]
    print(f"接口地址 : {cfg['openai']['api']}")
    print(f"模型     : {cfg['chatgpt']['model']}")
    print(f"API Key  : {len(keys)} 个，长度 {[len(k) for k in keys]}，头 {[k[:6] for k in keys]}")
    print(f"语音合成 : {cfg.get('audio_synthesis_type')}")
    for name, p in PROVIDERS.items():
        if cfg["openai"]["api"].startswith(p["api"].rsplit("/v", 1)[0]):
            print(f"^- 看起来是 {name}（{p['note']}）")
            break


def test_call(cfg):
    from openai import OpenAI
    client = OpenAI(base_url=cfg["openai"]["api"], api_key=cfg["openai"]["api_key"][0], timeout=60)
    t = time.time()
    resp = client.chat.completions.create(
        model=cfg["chatgpt"]["model"],
        messages=[
            {"role": "system", "content": "你是海底直播间的AI虚拟主播大肥鱼，只用一两句口语回答，20-50字，不要markdown。"},
            {"role": "user", "content": "大肥鱼你好，你是真人吗？"},
        ],
        temperature=0.9,
        max_tokens=120,
    )
    cost = time.time() - t
    print(f"耗时 {cost:.2f}s")
    print("回复：" + resp.choices[0].message.content.strip())
    if cost > 5:
        print("!! 超过 5 秒，直播回弹幕会明显卡顿，建议换更快的模型")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=sorted(PROVIDERS))
    ap.add_argument("--key", help="不给就从对应环境变量读")
    ap.add_argument("--model", help="覆盖默认模型名")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()

    if args.show:
        show()
        return

    if args.test:
        test_call(load())
        return

    if not args.provider:
        ap.print_help()
        return

    p = PROVIDERS[args.provider]
    key = args.key or os.environ.get(p["env"], "").strip() or p.get("default_key", "")
    if not key:
        print(f"没有 key：请用 --key 传入，或先设置环境变量 {p['env']}")
        sys.exit(1)

    if port_listening(8082):
        print("主程序正在运行（8082 在监听），改配置会被它覆盖。请先关掉主程序/一键启动窗口再执行。")
        sys.exit(1)

    cfg = load()
    backup = CONFIG.with_suffix(f".json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(CONFIG, backup)

    cfg["openai"]["api"] = p["api"]
    cfg["openai"]["api_key"] = [key]
    cfg["chatgpt"]["model"] = args.model or p["model"]
    save(cfg)

    print(f"已切到 {args.provider}")
    print(f"  接口 {p['api']}")
    print(f"  模型 {args.model or p['model']}")
    print(f"  备份 {backup.name}")
    print(f"  提示 {p['note']}")
    print("\n现在可以重跑 启动大肥鱼（先跑弹幕程序）.bat 了。")


if __name__ == "__main__":
    main()
