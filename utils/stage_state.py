# -*- coding: utf-8 -*-
"""舞台状态桥：Python 侧写小 JSON，网页侧轮询读取后弹卡片。

目前只做一件事：把「某个观众说了什么」推到画面上的卡片里，
让直播间所有人都看得见这条提问（展示时机 = 大章鱼正在处理它时）。

页面：Live2D/stage-octo-portrait.html 里的 #askcard
文件：Live2D/ask_show.json  {"at": 1699..., "user": "薄荷加冰", "text": "...", "role": "user"}
"""
from __future__ import annotations

import json
import os
import re
import time

_LIVE2D_DIR = "Live2D"
_ASK_FILE = os.path.join(_LIVE2D_DIR, "ask_show.json")

# 卡片上最多显示多少字（超出截断，避免糊住画面）
MAX_TEXT = 62
MAX_USER = 16

_last_spoke = 0.0


def _clean(text: str, limit: int) -> str:
    if not isinstance(text, str):
        text = str(text or "")
    # 去掉换行/多余空白/零宽字符，避免卡片被撑开
    text = text.replace("\u200b", "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s{2,}", " ", text).strip()
    # 表情占位符（[比心] 这种）在卡片里没意义，换成空格
    text = re.sub(r"\[[^\]]{1,8}\]", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def _atomic_write(path: str, payload: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)


def show_ask(user: str, text: str, role: str = "user") -> bool:
    """把一条「提问」推到画面卡片。

    role: "user" = 观众问（卡片显示「XX 问」）；"bot" = 大章鱼问观众。
    返回是否成功写入。
    """
    user = _clean(user, MAX_USER) or "观众"
    text = _clean(text, MAX_TEXT)
    if not text:
        return False
    try:
        os.makedirs(_LIVE2D_DIR, exist_ok=True)
        _atomic_write(
            _ASK_FILE,
            {"at": time.time(), "user": user, "text": text, "role": role},
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def claim_slot(min_gap: float = 45.0) -> bool:
    """主动说话抢麦：多个定时线程（祝福/提问/笑话/放歌）共用，避免同一秒抢着说。"""
    global _last_spoke
    now = time.time()
    if now - _last_spoke < min_gap:
        return False
    _last_spoke = now
    return True


def touch_slot() -> None:
    """外部（例如观众刚发弹幕她在回）刷新一下，避免主动说话撞车。"""
    global _last_spoke
    _last_spoke = time.time()
