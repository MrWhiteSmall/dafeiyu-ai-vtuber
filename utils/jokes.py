# -*- coding: utf-8 -*-
"""冷笑话库：读 data/冷笑话.txt，随机取一条（尽量不连续重复）。"""
from __future__ import annotations

import io
import os
import random
import threading

_JOKE_FILE = os.path.join("data", "冷笑话.txt")
_lock = threading.Lock()
_cache: list[str] = []
_recent: list[str] = []

# 兜底：文件缺失时也能说两句
_FALLBACK = [
    "为什么章鱼从来不怕考试？因为它有八只手，可以同时写八张卷子。",
    "为什么海水是咸的？因为鱼在里面哭了一整个下午。",
    "我问冰箱你冷不冷，它说：你先把门关上再问我。",
]


def _load() -> list[str]:
    global _cache
    with _lock:
        if _cache:
            return _cache
        try:
            with io.open(_JOKE_FILE, encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            _cache = lines or list(_FALLBACK)
        except Exception:  # noqa: BLE001
            _cache = list(_FALLBACK)
        return _cache


def pick_joke() -> str:
    """随机取一条，最近 12 条不重复。"""
    pool = _load()
    with _lock:
        cand = [j for j in pool if j not in _recent] or pool
        j = random.choice(cand)
        _recent.append(j)
        if len(_recent) > 12:
            del _recent[:-12]          # 就地裁剪，别重新绑定（否则 _recent 会变成局部变量）
        return j


def count() -> int:
    return len(_load())


# 观众触发用的口令
TRIGGERS = ("讲个笑话", "来个笑话", "讲笑话", "说个笑话", "来个冷笑话", "讲个冷笑话", "冷笑话")

# 说出来时前面加的开场白
LEADS = (
    "行，给你讲一个：",
    "来，冷笑话时间：",
    "这个有点冷啊，听好了：",
    "我讲一个，笑不笑随你：",
    "海底冷笑话库存充足，抽一条：",
)


def joke_line() -> str:
    return random.choice(LEADS) + pick_joke()


def is_joke_cmd(content: str) -> bool:
    if not content:
        return False
    t = content.strip()
    # 「讲个笑话」这种短口令；太长的话交给大模型正常对话
    if len(t) > 14:
        return False
    return any(k in t for k in TRIGGERS)
