# -*- coding: utf-8 -*-
"""Openverse 音源（CC 授权的免费音频），点歌兜底的最后一档。

QQ 音乐、网易云都拿不到时才用它：能下到的是 CC0/CC-BY 的纯音乐、古典、环境音，
不是流行歌的原唱，但"这首歌我这儿真没有"的时候，至少还能放点像样的东西。

接口：https://api.openverse.org/v1/audio/   （匿名可用，有限流，失败就静默跳过）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse
import urllib.request

API = "https://api.openverse.org/v1/audio/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) dafeiyu-vtuber/1.0"
MIN_BYTES = 300_000
MIN_SECONDS = 30.0
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFPROBE = os.path.join(ROOT, "tools", "ffmpeg", "bin", "ffprobe.exe")


def _get_json(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def search(keyword: str, limit: int = 6) -> list[dict]:
    """返回 [{title, creator, duration(秒), url, license, provider, foreign_landing_url}]"""
    if not keyword:
        return []
    params = {
        "q": keyword,
        "page_size": str(max(1, min(limit, 20))),
    }
    url = API + "?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url)
    except Exception as e:
        print(f"[Openverse] 搜索失败: {e}")
        return []

    out = []
    for r in data.get("results") or []:
        u = r.get("url") or ""
        if not u.startswith("http"):
            continue
        dur = float(r.get("duration") or 0) / 1000.0
        out.append({
            "title": (r.get("title") or "").strip(),
            "creator": (r.get("creator") or "").strip(),
            "duration": dur,
            "url": u,
            "license": r.get("license") or "",
            "provider": r.get("provider") or "openverse",
            "foreign_landing_url": r.get("foreign_landing_url") or "",
        })
    return out


def probe_seconds(path: str) -> float:
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=25,
        )
        return float((out.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def download(cand: dict, out_dir: str = "song", log=print) -> str | None:
    """下载到 out_dir，返回本地路径；校验不过返回 None。"""
    url = cand.get("url")
    if not url:
        return None
    title = re.sub(r'[\\/:*?"<>|]', " ", cand.get("title") or "openverse").strip() or "openverse"
    creator = re.sub(r'[\\/:*?"<>|]', " ", cand.get("creator") or "").strip()
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if ext not in (".mp3", ".ogg", ".oga", ".flac", ".m4a", ".wav"):
        ext = ".mp3"
    os.makedirs(out_dir, exist_ok=True)
    name = f"{title} - {creator}{ext}" if creator else f"{title}{ext}"
    path = os.path.join(out_dir, name)
    part = path + ".part"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
        size = os.path.getsize(part)
        if size < MIN_BYTES:
            log(f"[Openverse] 文件太小（{size} 字节），丢弃")
            os.remove(part)
            return None
        secs = probe_seconds(part)
        if secs and secs < MIN_SECONDS:
            log(f"[Openverse] 时长只有 {secs:.0f}s，太短，丢弃")
            os.remove(part)
            return None
        os.replace(part, path)
        log(f"[Openverse] 下载成功 {os.path.basename(path)}（{secs:.0f}s，{size // 1024}KB，"
            f"授权 {cand.get('license', '?')}）")
        return path
    except Exception as e:
        log(f"[Openverse] 下载失败: {e}")
        try:
            if os.path.exists(part):
                os.remove(part)
        except Exception:
            pass
        return None


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kw = sys.argv[1] if len(sys.argv) > 1 else "piano"
    for s in search(kw):
        print(f"{s['duration']:6.0f}s  {s['title']} - {s['creator']} [{s['license']}]")
