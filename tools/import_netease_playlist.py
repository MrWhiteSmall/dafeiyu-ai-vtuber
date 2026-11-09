"""按歌单把网易云歌曲慢慢下载进 song\ 目录（限速、可断点续传）。

用法：
    python tools/import_netease_playlist.py --id 123456789
    python tools/import_netease_playlist.py --url "https://music.163.com/playlist?id=123456789"
    python tools/import_netease_playlist.py --id 123456789 --interval 35 --limit 20

设计要点：
- 只走网易云公开接口，不需要登录 cookie。
- 每首歌之间 sleep `--interval` 秒（默认 30），避免被限流。
- 进度写 `out/song_import_state.json`，中断后重跑会跳过已完成的歌。
- 下载失败（VIP / 无版权 / 403）记入 state 的 failed，不反复重试。
- 文件名用「歌名 - 歌手.mp3」，与点歌的模糊匹配保持一致。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SONG_DIR = os.path.join(ROOT, 'song')
STATE_PATH = os.path.join(ROOT, 'out', 'song_import_state.json')
LOG_PATH = os.path.join(ROOT, 'out', 'song_import.log')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
HEADERS = {'User-Agent': UA, 'Referer': 'https://music.163.com/'}

MIN_BYTES = 1_000_000


try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def log(msg: str) -> None:
    line = time.strftime('%H:%M:%S') + ' ' + msg
    try:
        print(line, flush=True)
    except Exception:
        print(line.encode('utf-8', 'replace').decode('ascii', 'replace'), flush=True)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'done': [], 'failed': {}}


def save_state(st: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_playlist_id(args) -> str:
    if args.id:
        return str(args.id).strip()
    if args.url:
        q = urllib.parse.urlparse(args.url).query
        pid = urllib.parse.parse_qs(q).get('id')
        if pid:
            return pid[0]
        m = re.search(r'(\d{5,})', args.url)
        if m:
            return m.group(1)
    raise SystemExit('需要 --id 或 --url 指定歌单')


def fetch_tracks(pid: str, want: int = 0) -> tuple[str, list[dict]]:
    """返回 (歌单名, [{id, name, artist}])

    「我喜欢的音乐」是私有歌单，只能用 v6 接口拿 trackIds，
    再分批用 song/detail 补齐歌名。顺序与歌单一致（最新在前）。
    """
    url = f'https://music.163.com/api/v6/playlist/detail?id={pid}'
    data = json.loads(http_get(url).decode('utf-8', 'ignore'))
    pl = data.get('playlist') or {}
    name = pl.get('name') or f'playlist-{pid}'
    ids = [str(x['id']) for x in (pl.get('trackIds') or []) if x.get('id')]
    if not ids:
        ids = [str(t['id']) for t in (pl.get('tracks') or []) if t.get('id')]
    if want:
        ids = ids[:want]

    info: dict[str, dict] = {}
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        u = 'https://music.163.com/api/song/detail?ids=[' + ','.join(chunk) + ']'
        try:
            d = json.loads(http_get(u).decode('utf-8', 'ignore'))
        except Exception as e:
            log(f'  取详情失败（第 {i} 批）：{e}')
            continue
        for s in d.get('songs') or []:
            ar = '/'.join(a.get('name', '') for a in (s.get('artists') or []) if a.get('name'))
            info[str(s['id'])] = {'id': s['id'], 'name': s.get('name') or '', 'artist': ar}

    tracks = [info[i] for i in ids if i in info]
    return name, tracks


def safe_name(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:120] or 'unknown'


def norm_title(s: str) -> str:
    """歌名归一化：去空格、去括号里的版本信息、统一大小写，用于严格比对。"""
    s = (s or '').lower()
    s = re.sub(r'[(\[（【].*?[)\]）】]', '', s)
    s = re.sub(r'[\s\-_·.,，、!！?？"\'“”‘’]', '', s)
    return s


def already_have(title: str) -> bool:
    if not os.path.isdir(SONG_DIR):
        return False
    low = title.lower()
    for fn in os.listdir(SONG_DIR):
        if fn.lower().endswith(('.mp3', '.flac', '.wav', '.m4a', '.ogg')):
            if low in fn.lower():
                return True
    return False


def probe_ok(path: str) -> bool:
    """用 ffprobe 校验：能解出时长且 >= 45 秒，才算真歌（VIP 会返回一段坏文件）。"""
    ff = os.path.join(ROOT, 'tools', 'ffmpeg', 'bin', 'ffprobe.exe')
    if not os.path.exists(ff):
        return os.path.getsize(path) >= 1_000_000
    try:
        import subprocess
        out = subprocess.run([ff, '-v', 'error', '-show_entries', 'format=duration',
                              '-of', 'default=noprint_wrappers=1:nokey=1', path],
                             capture_output=True, text=True, timeout=25)
        s = (out.stdout or '').strip()
        if not s or s.upper().startswith('N/A'):
            return False
        return float(s) >= 45.0
    except Exception:
        return False


def download(track: dict) -> str | None:
    tid = track['id']
    title = safe_name(f"{track['name']} - {track['artist']}" if track['artist'] else track['name'])
    path = os.path.join(SONG_DIR, title + '.mp3')
    if os.path.exists(path) and probe_ok(path):
        return path

    # 1) 走项目自带的取音频：先匿名，拿不到自动用 cookie/netease.txt 走登录态（VIP 歌靠这个）
    try:
        sys.path.insert(0, ROOT)
        from utils.netease_music import _fetch_audio_bytes
        headers = {'User-Agent': UA, 'Referer': 'https://music.163.com'}
        blob = _fetch_audio_bytes(tid, headers, timeout=90)
        if blob and len(blob) >= MIN_BYTES:
            with open(path, 'wb') as f:
                f.write(blob)
            if probe_ok(path):
                return path
            os.remove(path)
            log('  文件校验不通过（时长过短/损坏），转搜索兜底')
        else:
            log(f'  拿不到音频流（{len(blob) if blob else 0}B），转搜索兜底')
    except Exception as e:
        log(f'  取音频异常：{e}')

    # 2) 搜索兜底：只接受**歌名完全一致**的候选，绝不下翻唱/同名的别的歌
    try:
        sys.path.insert(0, ROOT)
        from utils.netease_music import search_netease_songs, download_netease_candidate
        want = norm_title(track['name'])
        kw = f"{track['name']} {track['artist']}".strip()
        want_ar = norm_title(track.get('artist', ''))
        cands = search_netease_songs(kw, limit=10) or []
        for c in cands:
            raw_name = c.get('name', '') or ''
            if any(k in raw_name for k in ('伴奏', '纯音乐', '铃声', '片段', '试听', 'DJ版')):
                log(f'  跳过非原版：{raw_name}')
                continue
            if norm_title(raw_name) != want:
                continue
            cand_ar = norm_title('/'.join(a.get('name', '') for a in (c.get('artists') or [])))
            if want_ar and cand_ar and want_ar not in cand_ar and cand_ar not in want_ar:
                log(f"  跳过同名不同歌手：{cand_ar}")
                continue
            got, disp = download_netease_candidate(c, SONG_DIR)
            if got and os.path.exists(got) and probe_ok(got):
                log(f'  搜索兜底命中《{disp}》')
                return got
        log('  没有歌名完全一致的可用候选')
    except Exception as e:
        log(f'  搜索兜底失败：{e}')
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--id', help='歌单 id（我喜欢的音乐 = 你的用户 id）')
    ap.add_argument('--url', help='歌单分享链接')
    ap.add_argument('--interval', type=float, default=30, help='每首之间等待秒数')
    ap.add_argument('--limit', type=int, default=0, help='本次最多下几首（0=不限）')
    args = ap.parse_args()

    pid = parse_playlist_id(args)
    os.makedirs(SONG_DIR, exist_ok=True)
    st = load_state()

    log(f'拉取歌单 {pid} ...')
    try:
        name, tracks = fetch_tracks(pid, want=args.limit or 0)
    except Exception as e:
        log(f'歌单拉取失败: {e}')
        return 2
    log(f'歌单《{name}》取到 {len(tracks)} 首（本次上限 {args.limit or "不限"}）')

    done = set(st.get('done', []))
    failed = st.get('failed', {})
    ok = skip = fail = 0
    started = time.time()

    for i, t in enumerate(tracks, 1):
        tid = str(t['id'])
        if tid in done:
            skip += 1
            continue
        if tid in failed:
            skip += 1
            continue
        if args.limit and (ok + fail) >= args.limit:
            log(f'达到本次上限 {args.limit} 首，收工')
            break
        if already_have(t['name']):
            done.add(tid)
            skip += 1
            continue
        log(f'[{i}/{len(tracks)}] 下载 {t["name"]} - {t["artist"]}')
        p = download(t)
        if p:
            ok += 1
            done.add(tid)
            log(f'  OK {os.path.basename(p)} {os.path.getsize(p) // 1024}KB')
        else:
            fail += 1
            failed[tid] = t['name']
        st['done'] = sorted(done)
        st['failed'] = failed
        save_state(st)
        time.sleep(args.interval)

    log(f'结束：新增 {ok} / 跳过 {skip} / 失败 {fail}，用时 {int(time.time() - started)}s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
