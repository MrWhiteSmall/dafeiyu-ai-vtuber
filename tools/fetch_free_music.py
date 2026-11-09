# 抓一批公有领域（Public Domain）音乐进 song\ 目录，供 AI 点歌使用。
# 来源：archive.org 的 Musopen 合集（古典乐，公有领域录音）
import json
import os
import re
import time
import urllib.parse
import urllib.request

ROOT = r'D:\dafeiyu-ai-vtuber'
DEST = os.path.join(ROOT, 'song')
os.makedirs(DEST, exist_ok=True)
PROXY = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
OP = urllib.request.build_opener(urllib.request.ProxyHandler({'https': PROXY, 'http': PROXY})) \
    if PROXY else urllib.request.build_opener()
UA = {'User-Agent': 'DaFeiYuBGM/1.0 (personal livestream background music)'}

TARGET = 14          # 想抓多少首
MAX_MB = 14          # 单曲上限，太长的交响乐跳过


def get(url, t=40, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with OP.open(req, timeout=t) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def sanitize(name):
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    return re.sub(r'\s+', ' ', name).strip()[:60]


def main():
    q = urllib.parse.urlencode({
        'q': 'collection:musopen', 'fl[]': ['identifier', 'title'],
        'rows': 40, 'output': 'json',
    }, doseq=True)
    d = json.loads(get('https://archive.org/advancedsearch.php?' + q).decode('utf-8', 'ignore'))
    items = d['response']['docs']
    print(f'[库] 找到 {len(items)} 个 Musopen 条目', flush=True)

    got = 0
    manifest = []
    for it in items:
        if got >= TARGET:
            break
        ident = it['identifier']
        try:
            meta = json.loads(get(f'https://archive.org/metadata/{ident}').decode('utf-8', 'ignore'))
        except Exception as e:
            print(f'[跳过] {ident} metadata 失败 {e}', flush=True)
            continue

        files = meta.get('files') or []
        AUDIO_EXT = ('.mp3', '.ogg', '.oga', '.flac', '.m4a')
        mp3s = [f for f in files
                if str(f.get('name', '')).lower().endswith(AUDIO_EXT)
                and int(f.get('size') or 0) < MAX_MB * 1024 * 1024
                and int(f.get('size') or 0) > 300 * 1024]
        # 优先 mp3，省一次转码
        mp3s.sort(key=lambda x: 0 if str(x.get('name', '')).lower().endswith('.mp3') else 1)
        if not mp3s:
            continue

        f = mp3s[0]
        raw_name = f.get('title') or f.get('name') or ident
        ext = os.path.splitext(str(f.get('name', '')))[1].lower()
        fname = sanitize(os.path.splitext(raw_name)[0]) + '.mp3'
        path = os.path.join(DEST, fname)
        if os.path.exists(path):
            print(f'[已有] {fname}', flush=True)
            got += 1
            continue

        url = f'https://archive.org/download/{ident}/{urllib.parse.quote(f["name"])}'
        try:
            data = get(url, t=180)
        except Exception as e:
            print(f'[失败] {fname}: {e}', flush=True)
            continue
        if len(data) < 300 * 1024:
            print(f'[太小] {fname} {len(data)} 字节，跳过', flush=True)
            continue

        if ext == '.mp3':
            with open(path, 'wb') as fp:
                fp.write(data)
        else:
            # 非 mp3 先用 ffmpeg 转一道，播放器兼容性更稳
            tmp = os.path.join(DEST, '_tmp' + ext)
            with open(tmp, 'wb') as fp:
                fp.write(data)
            rc = os.system(f'"D:\\dafeiyu-ai-vtuber\\tools\\ffmpeg\\bin\\ffmpeg.exe" -y -loglevel error -i "{tmp}" -codec:a libmp3lame -q:a 4 "{path}"')
            try:
                os.remove(tmp)
            except OSError:
                pass
            if rc != 0 or not os.path.exists(path):
                print(f'[转码失败] {fname}', flush=True)
                continue

        got += 1
        manifest.append({'file': fname, 'source': url, 'license': 'Public Domain (Musopen)'})
        print(f'[下载 {got}/{TARGET}] {fname}  {len(data)/1024/1024:.1f}MB', flush=True)
        time.sleep(0.4)

    if manifest:
        md = os.path.join(ROOT, 'song', '曲库来源.md')
        old = ''
        if os.path.exists(md):
            old = open(md, encoding='utf-8').read()
        lines = ['# 本地曲库来源', '',
                 '这些曲子来自 archive.org 的 Musopen 合集，**公有领域（Public Domain）**，',
                 '可自由用于直播、无需署名。', '']
        for m in manifest:
            lines.append(f'- `{m["file"]}` ← {m["source"]}')
        open(md, 'w', encoding='utf-8').write('\n'.join(lines) + '\n' + old)

    print(f'[完成] 本次新增 {len(manifest)} 首，song\\ 现在共 {len([x for x in os.listdir(DEST) if x.lower().endswith((".mp3", ".flac", ".wav", ".m4a"))])} 个音频', flush=True)


if __name__ == '__main__':
    main()
