#  -*- coding: utf-8 -*-
"""QQ 音乐音源（免登录 128k，可选 cookie 提权）

用法：
    from utils.qq_music import search, download
    hits = search("晴天 周杰伦", limit=8)
    path = download(hits[0], r"D:\\dafeiyu-ai-vtuber\\song")

cookie（可选，放 cookie/qqmusic.txt，一行）：
    uin=123456; qm_keyst=xxxx; qqmusic_key=xxxx
有 cookie 才能拿 VIP 曲的高音质，没有也能拿大部分歌的 128k。
"""
import os
import re
import json
import random
import subprocess
import urllib.parse
import urllib.request

SEARCH_API = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
VKEY_API = "https://u.y.qq.com/cgi-bin/musicu.fcg"
COOKIE_FILE = os.path.join("cookie", "qqmusic.txt")
FFPROBE = os.path.join("tools", "ffmpeg", "bin", "ffprobe.exe")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MIN_BYTES = 1_000_000


def _headers():
    h = {
        "User-Agent": UA,
        "Referer": "https://y.qq.com/",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://y.qq.com",
    }
    ck = _read_cookie()
    if ck:
        h["Cookie"] = ck
    return h


def _read_cookie():
    try:
        if os.path.exists(COOKIE_FILE):
            txt = open(COOKIE_FILE, encoding="utf-8").read().strip()
            return txt or None
    except Exception:
        pass
    return None


def _uin():
    ck = _read_cookie() or ""
    m = re.search(r"(?:^|;\s*)uin=o?(\d+)", ck)
    return m.group(1) if m else "0"


def _post_json(url, payload, timeout=20):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _get_json(url, timeout=20):
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def search(keyword, limit=8):
    """搜歌，返回 [{songmid, name, singer, album, interval, key}]"""
    params = {
        "w": keyword, "p": "1", "n": str(limit), "cr": "1", "t": "0",
        "aggr": "1", "lossless": "0", "format": "json", "inCharset": "utf8",
        "outCharset": "utf-8", "notice": "0", "platform": "yqq.json",
        "needNewCode": "0", "g_tk": "5381",
    }
    url = SEARCH_API + "?" + urllib.parse.urlencode(params)
    try:
        js = _get_json(url)
    except Exception as e:
        print(f"[QQ音乐] 搜索失败: {e}")
        return []
    songs = (((js or {}).get("data") or {}).get("song") or {}).get("list") or []
    out = []
    for s in songs:
        try:
            singers = "、".join([x.get("name", "") for x in (s.get("singer") or [])])
            out.append({
                "source": "qq",
                "songmid": s.get("songmid"),
                "name": s.get("songname") or s.get("title") or "",
                "singer": singers,
                "album": s.get("albumname") or "",
                "interval": int(s.get("interval") or 0),
                "key": f"{s.get('songname', '')} - {singers}",
            })
        except Exception:
            continue
    return out


def get_play_url(songmid):
    """取直链（免登录多为 128k；带 cookie 可拿更高）"""
    guid = str(random.randint(10 ** 9, 10 ** 10 - 1))
    payload = {
        "req_0": {
            "module": "vkey.GetVkeyServer",
            "method": "CgiGetVkey",
            "param": {
                "guid": guid,
                "songmid": [songmid],
                "songtype": [0],
                "uin": _uin(),
                "loginflag": 1,
                "platform": "20",
            },
        },
        "comm": {"uin": _uin(), "format": "json", "ct": 24, "cv": 0},
    }
    try:
        js = _post_json(VKEY_API, payload)
    except Exception as e:
        print(f"[QQ音乐] 取直链失败: {e}")
        return None
    try:
        d = js["req_0"]["data"]
        info = (d.get("midurlinfo") or [{}])[0]
        purl = info.get("purl") or ""
        if not purl:
            return None
        sip = (d.get("sip") or ["https://dl.stream.qqmusic.qq.com/"])[0]
        if not sip.endswith("/"):
            sip += "/"
        return sip + purl
    except Exception:
        return None


def probe_ok(path, min_seconds=45):
    """用 ffprobe 校验时长，防止把报错页/试听片段当歌"""
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30,
        )
        dur = float((r.stdout or "0").strip() or 0)
        return dur >= min_seconds, dur
    except Exception:
        return False, 0.0


def safe_name(name):
    return re.sub(r'[\\/:*?"<>|]', " ", name).strip()


def download(cand, out_dir, log=print):
    """下载一首，成功返回路径"""
    mid = cand.get("songmid")
    if not mid:
        return None
    url = get_play_url(mid)
    if not url:
        log(f"[QQ音乐] 拿不到直链（可能是 VIP 曲）：{cand.get('key')}")
        return None
    filename = safe_name(f"{cand.get('name')} - {cand.get('singer')}")[:80] + ".mp3"
    dest = os.path.join(out_dir, filename)
    if os.path.exists(dest) and os.path.getsize(dest) >= MIN_BYTES:
        ok, dur = probe_ok(dest)
        if ok:
            log(f"[QQ音乐] 本地已有：{filename}")
            return dest
    tmp = dest + ".part"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://y.qq.com/"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(262144)
                if not chunk:
                    break
                f.write(chunk)
        size = os.path.getsize(tmp)
        if size < MIN_BYTES:
            log(f"[QQ音乐] 文件太小（{size} 字节），丢弃：{filename}")
            os.remove(tmp)
            return None
        ok, dur = probe_ok(tmp)
        if not ok:
            log(f"[QQ音乐] 时长异常（{dur:.1f}s），丢弃：{filename}")
            os.remove(tmp)
            return None
        os.replace(tmp, dest)
        log(f"[QQ音乐] 下载成功 {filename} {size // 1024}KB / {dur:.0f}s")
        return dest
    except Exception as e:
        log(f"[QQ音乐] 下载失败：{e}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return None


def get_lyric(songmid: str) -> str:
    """取某首歌的 LRC 原文（QQ 音乐的歌词接口，带 cookie 时更稳）。"""
    if not songmid:
        return ""
    url = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
    params = {
        "songmid": songmid, "format": "json", "nobase64": "1", "g_tk": "5381",
        "loginUin": "0", "hostUin": "0", "inCharset": "utf8", "outCharset": "utf-8",
        "notice": "0", "platform": "yqq", "needNewCode": "0",
    }
    h = {"User-Agent": UA, "Referer": "https://y.qq.com/portal/player.html"}
    ck = _read_cookie()
    if ck:
        h["Cookie"] = ck
    full = url + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(full, headers=h)
        raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace").strip()
        if raw.startswith("MusicJsonCallback"):
            raw = raw[raw.index("(") + 1: raw.rindex(")")]
        d = json.loads(raw)
        return d.get("lyric") or ""
    except Exception as e:
        print(f"[QQ歌词] 获取失败 {songmid}: {e}")
        return ""

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kw = sys.argv[1] if len(sys.argv) > 1 else "晴天 周杰伦"
    print("搜索:", kw)
    hits = search(kw)
    for i, h in enumerate(hits):
        print(f"  {i}. {h['name']} - {h['singer']}  [{h['album']}] {h['interval']}s  mid={h['songmid']}")
    if hits:
        u = get_play_url(hits[0]["songmid"])
        print("首个直链:", (u or "无")[:110])
