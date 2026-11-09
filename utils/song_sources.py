#  -*- coding: utf-8 -*-
"""多音源点歌：本地没有时，同时问网易云 + QQ 音乐，挑最像的那首下载。

为什么要有这个：单靠网易云，很多歌它没有版权（或者只给 104KB 的假文件），
而这些歌在 QQ 音乐是免费的。反过来也有 QQ 拿不到的。

打分逻辑（谁分高先用谁）：
  1. 标题相似度（去掉括号里的 Live/伴奏/翻唱 等修饰再比）
  2. 关键词里的歌手名是否出现在候选歌手里
  3. 时长是否像一首完整的歌（90~420 秒）
  4. 命中 伴奏/纯音乐/铃声/片段/试听/remix/翻唱/live 等降权
"""
from __future__ import annotations

LAST_REASON = ""  # 最近一次 fetch_best 失败的原因：
#   'vip' = 歌手对得上但拿不到音频（会员曲/无版权）
#   'io'  = 写盘失败（磁盘/路径问题，跟版权无关）
#   'net' = 网络异常
#   ''    = 三个音源都没搜到合适的

import os
import re
import sys
import difflib

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils import netease_music as nm
from utils import qq_music as qm
from utils import openverse_music as ov

# 音源优先级：QQ 音乐主力 → 网易云兜底 → Openverse（CC 授权的免费音频，最后的手段）
# 2026-11-08 用户口径：qq音乐作为主力搜索，找不到 fallback 到网易云，最后才是 openverse
SOURCE_ORDER = ("qq", "netease", "openverse")
ENABLED_SOURCES = SOURCE_ORDER

BAD_WORDS = (
    "伴奏", "纯音乐", "铃声", "片段", "试听", "dj版", "dj", "remix", "cover",
    "翻唱", "live", "现场", "演唱会", "instrumental", "karaoke", "demo",
    "0.8x", "1.2x", "加速版", "慢速版", "钢琴版", "吉他版", "八音盒",
    # 「原唱 XXX」「女声版」这类都是别人翻的，标题里带这些词一律降权，
    # 否则"晴天 (原唱 周杰伦)"会因为标题完全匹配而盖过真原唱
    "原唱", "女声版", "男声版", "童声版", "温柔版", "慢摇", "合唱版",
    # 各种换皮版本：线上已发生「点歌 稻香」下回来「稻香(治愈版)」，
    # 治愈版只有 120 秒、唱歌的还是别人的采样
    "治愈版", "治愈", "助眠", "睡前", "3d环绕", "环绕版", "重低音", "车载",
    "网红版", "女声", "男声", "翻自", "改编版", "慢速", "加速",
)

_BRACKETS = re.compile(r"[\(（\[【].*?[\)）\]】]")


def _norm(text: str) -> str:
    if not text:
        return ""
    s = _BRACKETS.sub(" ", str(text))
    s = re.sub(r"[\s·・\-—_/\\|,，。.、!！?？'\"“”‘’]+", "", s)
    return s.lower()


def _has_bad(text: str) -> bool:
    low = (text or "").lower()
    return any(w in low for w in BAD_WORDS)


def _split_query(keyword: str):
    """把「晴天 周杰伦」拆成 (标题, 可能的歌手)"""
    parts = [p for p in re.split(r"[\s\-—/]+", (keyword or "").strip()) if p]
    if len(parts) <= 1:
        return (keyword or "").strip(), ""
    return parts[0], " ".join(parts[1:])


def _score(q_title: str, q_artist: str, title: str, artist: str, duration_s: float, source: str):
    nt, nc = _norm(q_title), _norm(title)
    sim = difflib.SequenceMatcher(None, nt, nc).ratio() if nt and nc else 0.0
    score = sim * 100.0

    if nt and nt == nc:
        score += 25.0
    elif nt and (nt in nc or nc in nt):
        score += 12.0

    if q_artist:
        na = _norm(q_artist)
        nca = _norm(artist)
        for token in re.split(r"[\s]+", q_artist):
            t = _norm(token)
            if t and t in nca:
                score += 18.0
                break
        else:
            if na and (na in nca or nca in na):
                score += 10.0

    if 90 <= (duration_s or 0) <= 420:
        score += 8.0
    elif duration_s:
        score -= 12.0

    if _has_bad(title) or _has_bad(artist):
        score -= 45.0

    # 「旧版」「新版」这类不是翻唱，但也不是大家点的那一版，轻一点罚。
    if any(w in (title or "") for w in ("旧版", "新版", "重制", "重置版", "2023版", "2024版")):
        score -= 10.0

    # QQ 是主力音源，同分时优先（Openverse 只作最后兜底，不参与抢分）
    score += 2.0 if source == "qq" else (1.0 if source == "netease" else 0.0)
    return score


def _raw_candidates(source: str, keyword: str, per_source: int = 6) -> list[dict]:
    """只问一个音源，返回未打分的候选。"""
    cands: list[dict] = []
    if source == "netease":
        try:
            for s in nm.search_netease_songs(keyword, per_source) or []:
                artists = "、".join([a.get("name", "") for a in (s.get("artists") or [])])
                dur = float(s.get("duration") or 0) / 1000.0
                cands.append({
                    "source": "netease",
                    "title": s.get("name") or "",
                    "artist": artists,
                    "album": (s.get("album") or {}).get("name") or "",
                    "duration": dur,
                    "raw": s,
                    "key": f"{s.get('name')} - {artists}",
                })
        except Exception as e:
            print(f"[多音源] 网易云搜索异常: {e}")
    elif source == "qq":
        try:
            for s in qm.search(keyword, per_source) or []:
                cands.append({
                    "source": "qq",
                    "title": s.get("name") or "",
                    "artist": s.get("singer") or "",
                    "album": s.get("album") or "",
                    "duration": float(s.get("interval") or 0),
                    "raw": s,
                    "key": s.get("key") or "",
                })
        except Exception as e:
            print(f"[多音源] QQ音乐搜索异常: {e}")
    elif source == "openverse":
        try:
            for s in ov.search(keyword, per_source) or []:
                cands.append({
                    "source": "openverse",
                    "title": s.get("title") or "",
                    "artist": s.get("creator") or "",
                    "album": s.get("provider") or "",
                    "duration": float(s.get("duration") or 0),
                    "raw": s,
                    "key": f"{s.get('title')} - {s.get('creator')}",
                })
        except Exception as e:
            print(f"[多音源] Openverse 搜索异常: {e}")
    return cands


def _rank(cands: list[dict], keyword: str) -> list[dict]:
    """打分 + 歌手校验 + 降序。"""
    q_title, q_artist = _split_query(keyword)

    # 用户只发歌名时（"点歌 晴天"），不能凭"标题完全一样"就选——翻唱们标题也完全一样。
    # 这里从候选标题里的「(原唱 周杰伦)」「(原唱: 陈奕迅)」这类标注反推原唱，再用它重新打分，
    # 于是"晴天 - 周杰伦"能靠歌手命中压过"晴天 - 梦里啥都有"。
    if not q_artist:
        for c in cands:
            m = re.search(r"原唱[:：\s]*([^\)）\]】]+)", c["title"] or "")
            if m:
                guess = m.group(1).strip()
                if guess:
                    q_artist = guess
                    break

    for c in cands:
        c["score"] = _score(q_title, q_artist, c["title"], c["artist"], c["duration"], c["source"])
        # 歌手对得上优先：防止"点了周杰伦，结果下回来一个翻唱"
        c["artist_match"] = bool(q_artist) and any(
            t and t in _norm(c["artist"]) for t in re.split(r"\s+", q_artist)
        )
    # 注：试过"同名歌跨音源一律优先 QQ"来防网易云的翻唱顶替（周杰伦这类网易云没版权），
    # 但那会把「起风了 - 周深（翻唱）」顶到「起风了 - 买辣椒也用券（原唱）」前面，
    # 分不出来，已撤掉。现在靠：① 带歌手时只认 artist_match；② BAD_WORDS 降权「原唱 XXX」这类标题。
    cands.sort(key=lambda x: x["score"], reverse=True)
    return cands


def search_all(keyword: str, per_source: int = 6) -> list[dict]:
    """所有音源都搜一遍（仅用于调试/看排序），实际点歌走 fetch_best 的分级兜底。"""
    cands: list[dict] = []
    for s in ENABLED_SOURCES:
        cands.extend(_raw_candidates(s, keyword, per_source))
    return _rank(cands, keyword)


def _download(cand: dict, save_dir: str, log) -> tuple[str | None, str | None]:
    # 先自己建目录：各音源的 download 都把 IO 异常吞成 None 了，
    # 在这儿抛 OSError 才能让上层知道「是机器/路径的问题，不是没版权」。
    os.makedirs(save_dir, exist_ok=True)
    if cand["source"] == "netease":
        path, info = nm.download_netease_candidate(cand["raw"], save_dir)
        if not path:
            # 网易云内部把异常吞了，只留下 LAST_ERROR_KIND：写盘/网络要照实上报，
            # 不能一律当成「会员曲」（线上真踩过：路径不存在 -> 说成没版权）。
            kind = getattr(nm, "LAST_ERROR_KIND", "") or "vip"
            if kind in ("io", "net"):
                raise OSError(f"网易云 {kind} 错误") if kind == "io" else RuntimeError("网易云网络异常")
        return path, info
    if cand["source"] == "openverse":
        path = ov.download(cand["raw"], save_dir, log=log)
        return (path, cand["key"]) if path else (None, None)
    path = qm.download(cand["raw"], save_dir, log=log)
    return (path, cand["key"]) if path else (None, None)


def _ensure_named(path: str, title: str, artist: str, log=print) -> str:
    """把下载下来的文件改名成「歌名 - 歌手.ext」，保证文件自带歌手信息。

    网易云下回来的常见是「1901371647_孤勇者.mp3」，只有歌名没有歌手，
    下次「点歌 孤勇者」就会随机挑到某个翻唱版本。
    """
    import os
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    t = (title or "").strip()
    a = (artist or "").strip()
    if not t:
        return path
    if a and _norm(a) and _norm(a) in _norm(stem):
        return path  # 已经带歌手了
    want = f"{t} - {a}" if a else t
    want = re.sub(r'[\\/:*?"<>|]', " ", want).strip()
    target = os.path.join(os.path.dirname(path), f"{want}{ext}")
    if os.path.abspath(target) == os.path.abspath(path):
        return path
    if os.path.exists(target):
        try:
            os.remove(target)
        except Exception:
            pass
    try:
        os.replace(path, target)
        log(f"[多音源] 已重命名：{base} -> {os.path.basename(target)}")
        return target
    except Exception as e:
        log(f"[多音源] 重命名失败：{e}")
        return path


def fetch_best(keyword: str, save_dir: str = "song", log=print, max_try: int = 4):
    """按音源优先级逐级兜底下载，返回 (路径, 展示名, 音源)

    顺序：QQ 音乐（主力）→ 网易云（兜底）→ Openverse（CC 授权，最后手段）。
    关键词里带歌手时，只在"歌手对得上"的候选里挑：宁可回一句"这首要会员"，
    也不要把翻唱当成原唱放出去（线上踩过：点了周杰伦，下回来 RyaVocal 的翻唱）。
    """
    global LAST_REASON
    LAST_REASON = ""

    # 目录不存在会让写 .part 直接抛 FileNotFoundError，被误判成“会员曲”
    # （线上真踩过：测试目录没建，反方向的钟明明能下却说没版权）。
    try:
        os.makedirs(save_dir, exist_ok=True)
    except Exception as _e:
        log(f"[多音源] 建目录失败 {save_dir}：{_e}")

    any_artist_matched = False
    tried_total = 0
    fail_kinds = {"vip": 0, "io": 0, "net": 0}

    # 没给歌手时，同一首歌的多个版本会打平（起风了：周深／买辣椒也用券／吴青峰 都是 135 分，
    # QQ 搜索把周深排在前面）。网易云对"多版本同名歌"的原唱排序更靠谱，所以拿它的顺序做平手参考。
    tie_rank = {}
    if not _split_query(keyword)[1]:
        try:
            for c in _rank(_raw_candidates("netease", keyword), keyword):
                # 用原始歌手串（不是 _norm，_norm 会把「冯沁苑(买辣椒也用券)」的括号内容去掉，
                # 导致和 QQ 的「买辣椒也用券」对不上）
                a = str(c.get("artist", "")).strip().lower()
                if a and a not in tie_rank:
                    tie_rank[a] = len(tie_rank)
        except Exception as _e:
            log(f"[多音源] 取网易云排序失败（不影响主流程）：{_e}")

    def _order(pool):
        def key_fn(item):
            i, c = item
            a = str(c.get("artist", "")).strip().lower()
            r = 99
            for k, v in tie_rank.items():
                if k and (k == a or k in a or a in k):
                    r = min(r, v)
            return (-c["score"], r, i)
        return [c for _, c in sorted(enumerate(pool), key=key_fn)]

    for source in SOURCE_ORDER:
        cands = _rank(_raw_candidates(source, keyword), keyword)
        if not cands:
            log(f"[多音源] {source} 没搜到，换下一个")
            continue

        matched = [c for c in cands if c.get("artist_match")]
        if matched:
            any_artist_matched = True
        pool = matched if matched else cands
        pool = _order(pool)

        tried = 0
        for cand in pool:
            if cand["score"] < 30:
                break
            kind = None
            try:
                path, info = _download(cand, save_dir, log)
                if not path:
                    kind = "vip"      # 接口没给音频地址：会员曲 / 无版权
            except OSError as e:
                kind = "io"
                log(f"[多音源] {cand['source']} 下载 {cand['key']} 写盘失败: {e}")
                path, info = None, None
            except Exception as e:
                kind = "net"
                log(f"[多音源] {cand['source']} 下载 {cand['key']} 异常: {e}")
                path, info = None, None
            if path:
                log(f"[多音源] 选中 {cand['source']}：{cand['key']}（{cand['duration']:.0f}s，得分 {cand['score']:.0f}）")
                # 文件名必须同时带歌名和歌手，否则后面「点歌 晴天」只会被"晴天"二字迷惑，
                # 分不清是周杰伦原唱还是某个翻唱。
                try:
                    path = _ensure_named(path, cand["title"], cand["artist"], log)
                except Exception as _e:
                    log(f"[多音源] 重命名失败（不影响播放）：{_e}")
                return path, info or cand["key"], cand["source"]
            tried += 1
            tried_total += 1
            if kind:
                fail_kinds[kind] = fail_kinds.get(kind, 0) + 1
            if tried >= max_try:
                break
        log(f"[多音源] {source} 试了 {tried} 个候选都不行，换下一个音源")

    # 失败原因要分清：真有版权问题才说“会员曲”，写盘/网络故障要照实说，
    # 否则用户会以为整首歌唱不了（线上踩过：目录不存在被报成“要开会员”）。
    if any_artist_matched and fail_kinds["vip"]:
        LAST_REASON = "vip"
        log(f"[多音源] 歌手对得上的候选都拿不到音频（多半是会员曲）：{keyword}")
    elif fail_kinds["io"]:
        LAST_REASON = "io"
        log(f"[多音源] 下载写盘失败（磁盘/路径问题，不是版权）：{keyword}")
    elif fail_kinds["net"]:
        LAST_REASON = "net"
        log(f"[多音源] 下载网络异常：{keyword}")
    else:
        log(f"[多音源] 三个音源共试 {tried_total} 个候选都下不下来：{keyword}")
    return None, None, None


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    kw = sys.argv[1] if len(sys.argv) > 1 else "晴天 周杰伦"
    for c in search_all(kw)[:8]:
        flag = "★" if _has_bad(c["title"]) else " "
        print(f"{c['score']:6.1f} {flag} [{c['source']:7s}] {c['title']} - {c['artist']} ({c['duration']:.0f}s)")
