# -*- coding: utf-8 -*-
"""观众消息对账日志。

目的：一条观众消息进来，日志里必须能查到它去哪了——回了什么、还是被谁丢了、为什么丢。
以前只有零散的 logger 行，对不上账（收了 36 条、只处理 25 条，差的 11 条没有任何痕迹）。

用法（在 my_handle 里会自动调，不需要业务代码操心）：
    msg_log.trace_in("弹幕", username, content)      # 收到
    msg_log.trace_out(username, "好的，这就放")       # 回了（按用户 FIFO 配给最早那条未处理的）
    msg_log.trace_drop(username, content, "违禁词命中")

落盘：log/messages-YYYY-MM-DD.log，一行一条，字段用 | 分隔，方便 grep 与 tools/msg_audit.py 统计。
"""
import datetime
import threading
import time
from pathlib import Path

_LOCK = threading.RLock()
_SEQ = 0
_DIR = Path(__file__).resolve().parent.parent / "log"

# user -> [msg_id, ...]  已经收到但还没有结论的消息，按到达顺序
_PENDING = {}

# 这些类型的合成结果算“回复了观众”；song / idle_time_task 之类不算
REPLY_TYPES = {
    "comment", "local_qa_text", "local_qa_audio", "talk",
    "entrance", "follow", "gift", "integral", "reread",
}


def _next_id():
    global _SEQ
    with _LOCK:
        _SEQ += 1
        return _SEQ


def _clean(text, limit=200):
    s = str(text or "").replace("\r", " ").replace("\n", " ").strip()
    return s if len(s) <= limit else s[:limit] + "…"


def trace(stage, kind, user, content="", detail="", msg_id=None):
    """写一行。stage 取 IN / OUT / DROP / SKIP。"""
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now()
        path = _DIR / f"messages-{now:%Y-%m-%d}.log"
        mid = "-" if msg_id is None else str(msg_id)
        line = (f"{now:%H:%M:%S}.{now.microsecond // 1000:03d} | #{mid:<4} | {stage:<4} | {kind:<4} | "
                f"用户={_clean(user, 40)} | 内容={_clean(content)}")
        if detail:
            line += f" | {_clean(detail, 300)}"
        with _LOCK:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return msg_id
    except Exception:
        return msg_id


def trace_in(kind, user, content=""):
    """收到一条消息，分配编号并登记为待处理。"""
    with _LOCK:
        mid = _next_id()
        _PENDING.setdefault(str(user), []).append(mid)
    trace("IN", kind, user, content, msg_id=mid)
    _bump(kind, user, content)          # 今日台面数据（人数/互动/礼物）
    note_presence(user)                 # 记一笔"这人刚才还在"
    return mid


# ── 在场观众（最近 N 秒内有动作的人） ──
_PRESENCE = {}


def note_presence(user):
    try:
        u = str(user or "").strip()
        if not u or u in ("None", "观众"):
            return
        with _LOCK:
            _PRESENCE[u] = time.time()
    except Exception:
        pass


def present_users(window=600.0):
    """返回 window 秒内有过动作的观众昵称（按最近活跃排序）。"""
    now = time.time()
    with _LOCK:
        alive = [(t, u) for u, t in _PRESENCE.items() if now - t <= window]
        # 顺手清理过期记录，避免字典无限增长
        for u, t in list(_PRESENCE.items()):
            if now - t > 3600:
                _PRESENCE.pop(u, None)
    alive.sort(reverse=True)
    return [u for _, u in alive]


def _pop_pending(user):
    with _LOCK:
        q = _PENDING.get(str(user)) or []
        return q.pop(0) if q else None


def trace_out(user, content="", kind="回复"):
    """回复了。按用户名 FIFO 配给最早那条尚未结论的消息。"""
    mid = _pop_pending(user)
    trace("OUT", kind, user, content, msg_id=mid)
    if mid is not None:      # 只有真正配到一条观众消息才计入“互动回复”，
        bump_reply()         # 否则闲时文案/一条回复拆多段会把数字刷高
    return mid


def trace_drop(user, content="", reason="未说明", kind="丢弃"):
    mid = _pop_pending(user)
    trace("DROP", kind, user, content, reason, msg_id=mid)
    return mid


def trace_skip(user, content="", reason="不需要回复", kind="跳过"):
    mid = _pop_pending(user)
    trace("SKIP", kind, user, content, reason, msg_id=mid)
    return mid


def pending_count():
    with _LOCK:
        return sum(len(v) for v in _PENDING.values())


# ────────────────────────── 今日台面数据 ──────────────────────────
# 给直播画面用：今天多少人打过招呼 / 多少次互动 / 多少份礼物。
# 落一份 JSON 到 Live2D/ 下（和舞台页同源，浏览器直接读），重启后按日期续算。
import json
import re as _re

_STATS_FILE = Path(__file__).resolve().parent.parent / "Live2D" / "live_stats.json"
_STATS = None


def _today():
    return datetime.date.today().isoformat()


def _load_stats():
    global _STATS
    if _STATS is not None:
        return _STATS
    data = {}
    try:
        data = json.loads(_STATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if data.get("date") != _today():
        data = {"date": _today()}
    for k in ("users", "hellos", "comments", "replies", "gifts", "coins"):
        data.setdefault(k, 0)
    data.setdefault("names", [])
    _STATS = data
    return _STATS


def _save_stats():
    try:
        st = _load_stats()
        st["updated"] = datetime.datetime.now().strftime("%H:%M:%S")
        _STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_STATS_FILE)
    except Exception:
        pass


def _bump(kind, user, content=""):
    """按消息类型累计今日数据。"""
    try:
        st = _load_stats()
        with _LOCK:
            u = str(user or "").strip()
            if u and u not in st["names"]:
                st["names"].append(u)
                if len(st["names"]) > 2000:
                    st["names"] = st["names"][-2000:]
                st["users"] = len(st["names"])
            if kind in ("弹幕",):
                st["comments"] += 1
            elif kind in ("进场", "关注"):
                st["hellos"] += 1
            elif kind == "礼物":
                st["gifts"] += 1
                m = _re.search(r"(\d+)\s*个", str(content or ""))
                if m:
                    st["gifts"] += int(m.group(1)) - 1
                m = _re.search(r"[（(](\d+)\s*抖币", str(content or ""))
                if m:
                    st["coins"] += int(m.group(1))
        _save_stats()
    except Exception:
        pass


def bump_reply(n=1):
    """回了一条（合成音频/字幕成功的次数）。"""
    try:
        st = _load_stats()
        with _LOCK:
            st["replies"] += n
        _save_stats()
    except Exception:
        pass


def current_stats():
    try:
        return dict(_load_stats())
    except Exception:
        return {}

