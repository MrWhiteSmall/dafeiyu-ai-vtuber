# 直播观察哨：每 3 分钟扫一次日志，统计指标 + 异常告警
import json, os, re, time, io, sys

ROOT = r"D:\dafeiyu-ai-vtuber"
LOG = os.path.join(ROOT, "log")
OUT = os.path.join(ROOT, "out")
WATCH_LOG = os.path.join(OUT, "live_watch.log")
STATE = os.path.join(OUT, "live_watch_state.json")
INTERVAL = 180

PAT = {
    "danmaku": re.compile(r"直播间弹幕消息|📧"),
    "enter": re.compile(r"直播间成员加入消息|进入直播间"),
    "gift": re.compile(r"礼物消息|赠送"),
    "llm": re.compile(r"调用大模型|使用流式推理LLM|流式推理"),
    "song": re.compile(r"\[点歌\]|网易云音乐|正在为你播放"),
    "filter": re.compile(r"违禁|badwords|过滤"),
    "error": re.compile(r"ERROR|Traceback|Exception|失败"),
}


def today_file(prefix):
    return os.path.join(LOG, f"{prefix}-{time.strftime('%Y-%m-%d')}.txt")


def count_lines(path):
    """返回 (总行数, 读取过的偏移)"""
    st = load_state()
    off = st.get(path, 0)
    if not os.path.exists(path):
        return {}, off
    size = os.path.getsize(path)
    if size < off:
        off = 0
    with io.open(path, encoding="utf-8", errors="replace") as f:
        f.seek(off)
        chunk = f.read()
        new_off = f.tell()
    cnt = {k: 0 for k in PAT}
    for line in chunk.splitlines():
        for k, rx in PAT.items():
            if rx.search(line):
                cnt[k] += 1
    st[path] = new_off
    save_state(st)
    return cnt, new_off


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def save_state(st):
    try:
        json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def http_json(url, timeout=6):
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"_err": str(e)[:80]}


def ports():
    import socket
    res = {}
    for p in (8082, 12345, 5500, 8787, 8888, 4455):
        s = socket.socket()
        s.settimeout(0.6)
        res[p] = s.connect_ex(("127.0.0.1", p)) == 0
        s.close()
    return res


def main():
    io.open(WATCH_LOG, "a", encoding="utf-8").write(
        f"\n===== watcher started {time.strftime('%m-%d %H:%M:%S')} =====\n"
    )
    prev = None
    while True:
        t0 = time.time()
        cmt, _ = count_lines(today_file("comment"))
        for _k in ("danmaku", "enter", "gift", "llm", "song", "filter", "error"):
            cmt.setdefault(_k, 0)
        app, _ = count_lines(today_file("log"))
        for _k in ("danmaku", "enter", "gift", "llm", "song", "filter", "error"):
            app.setdefault(_k, 0)
        stats = http_json("http://127.0.0.1:8787/stats")
        cap = http_json("http://127.0.0.1:5500/state")
        up = ports()
        down = [str(p) for p, v in up.items() if not v]

        total_dm = cmt["danmaku"] + app["danmaku"]
        line = (f"[{time.strftime('%m-%d %H:%M:%S')}] "
                f"弹幕{total_dm} 进场{cmt['enter'] + app['enter']} 礼物{cmt['gift'] + app['gift']} "
                f"LLM{app['llm']} 点歌{app['song']} 过滤{app['filter']} 报错{app['error']} "
                f"| token {(stats.get('total_tokens') if isinstance(stats, dict) else '?')} "
                f"calls {(stats.get('calls') if isinstance(stats, dict) else '?')} "
                f"| 字幕 {(cap.get('text') or '')[:24]} ")
        if down:
            line += f"| ⚠️ 端口挂了 {','.join(down)}"
        if prev is not None:
            if total_dm == prev and app["llm"] == 0 and app["error"] == 0:
                line += "| 静默（无弹幕、无报错）"
        prev = total_dm
        print(line, flush=True)
        io.open(WATCH_LOG, "a", encoding="utf-8").write(line + "\n")
        json.dump({
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "danmaku": total_dm, "enter": cmt["enter"] + app["enter"],
            "gift": cmt["gift"] + app["gift"], "llm": app["llm"],
            "song": app["song"], "filter": app["filter"], "error": app["error"],
            "token": stats.get("total_tokens"), "calls": stats.get("calls"),
            "caption": cap.get("text"), "ports_down": down,
        }, open(os.path.join(OUT, "live_watch_state_snapshot.json"), "w", encoding="utf-8"),
            ensure_ascii=False, indent=2)
        time.sleep(max(10, INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    main()
