# -*- coding: utf-8 -*-
"""夜间值守体检：一行输出关键状态，少占上下文。

用法：
    .venv\\Scripts\\python.exe -u tools\\night_check.py
"""
import json
import os
import re
import socket
import sys
import time
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

PORTS = {8082: "main", 12345: "web", 5500: "caption", 8787: "llm", 8888: "danmaku", 4455: "obs"}


def port_up(p):
    s = socket.socket()
    s.settimeout(0.6)
    try:
        return s.connect_ex(("127.0.0.1", p)) == 0
    finally:
        s.close()


def get(url, timeout=3):
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def main():
    now = datetime.now().strftime("%H:%M:%S")
    dead = [f"{n}:{p}" for p, n in PORTS.items() if not port_up(p)]
    stats = get("http://127.0.0.1:8787/stats") or {}
    cap = get("http://127.0.0.1:5500/state") or {}
    log = os.path.join(ROOT, "log", f"log-{time.strftime('%Y-%m-%d').replace('-0', '-').replace('-', '-')}.txt")
    if not os.path.exists(log):
        cand = [f for f in os.listdir(os.path.join(ROOT, "log")) if f.startswith("log-")]
        log = os.path.join(ROOT, "log", sorted(cand)[-1]) if cand else ""
    errs, drops, dms = [], [], []
    if log:
        with open(log, encoding="utf-8", errors="replace") as f:
            for line in f.readlines()[-4000:]:
                if "ERROR" in line or "Traceback" in line:
                    errs.append(line.strip()[:150])
                elif "[丢弃]" in line:
                    drops.append(line.strip()[:120])
                elif "直播间弹幕消息" in line:
                    dms.append(line.strip()[:150])
    print(f"[{now}] 端口缺失={dead or '无'} | token={stats.get('total_tokens')} calls={stats.get('calls')}")
    try:
        import shutil
        free = shutil.disk_usage("D:\\").free / 1024 ** 3
        out_mp3 = len([f for f in os.listdir(os.path.join(ROOT, "out")) if f.endswith(".mp3")])
        print(f"  D盘剩余={free:.1f}GB out音频={out_mp3}个")
    except Exception:
        pass
    print(f"  字幕={cap.get('text')!r}")
    if dms:
        print(f"  最近弹幕({len(dms)})：{dms[-1]}")
    if drops:
        print(f"  最近丢弃({len(drops)})：{drops[-1]}")
    if errs:
        print(f"  最近报错({len(errs)})：{errs[-1]}")


if __name__ == "__main__":
    main()
