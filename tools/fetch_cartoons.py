import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
ROOT = r"D:\dafeiyu-ai-vtuber"
RAW = os.path.join(ROOT, "media", "_raw")
OUT = os.path.join(ROOT, "media", "cartoons")
FFMPEG = os.path.join(ROOT, "tools", "ffmpeg", "bin", "ffmpeg.exe")
os.makedirs(RAW, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

# (序号, 显示名, archive item, 文件名关键词)
ITEMS = [
    ("01", "小蝌蚪找妈妈", "20220223_20220223_0138", "小蝌蚪找妈妈"),
    ("02", "牧笛", "buffalo-boy_202202", "牧笛"),
    ("03", "骄傲的将军", "1956_20200812", "骄傲的将军"),
    ("04", "贝蒂布普-看手相", "Betty_Boop_Is_My_Palm_Read_1932", "_512kb.mp4"),
    ("05", "贝蒂布普-雪白", "bb_snow_white", "_512kb.mp4"),
    ("06", "贝蒂布普-别吵了", "bb_stop_that_noise", "_512kb.mp4"),
    ("07", "贝蒂布普-她说他冤", "bb_she_wronged_him_right", "_512kb.mp4"),
    ("08", "贝蒂布普-小吉米", "Betty_Boop_and_Little_Jimmy_1936", "_512kb.mp4"),
]


def get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout)


def pick_file(ident, key):
    d = json.loads(get("https://archive.org/metadata/" + urllib.parse.quote(ident)).read())
    cands = []
    for f in d.get("files", []):
        n = f.get("name", "")
        if n.lower().endswith((".mp4", ".mkv", ".ogv", ".mpeg")) and key in n:
            cands.append((int(f.get("size", 0) or 0), n))
    if not cands:
        return None
    cands.sort()
    return cands[0][1]


def download(ident, name, dest):
    url = "https://archive.org/download/" + urllib.parse.quote(ident) + "/" + urllib.parse.quote(name)
    print("[下载]", ident, "->", name, flush=True)
    with get(url, timeout=180) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length", 0) or 0)
        got = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
    print("   完成 %.1fMB" % (got / 1048576), flush=True)
    return got


def transcode(src, dst):
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", src,
           "-vf", "scale='min(854,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "26", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
           "-movflags", "+faststart", dst]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("   转码失败:", (r.stderr or "")[-300:], flush=True)
        return False
    return True


manifest = []
for idx, title, ident, key in ITEMS:
    safe = title.replace("/", "-")
    raw_path = os.path.join(RAW, idx + "-" + safe + os.path.splitext(key)[-1])
    out_path = os.path.join(OUT, idx + "-" + safe + ".mp4")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1_000_000:
        print("[跳过]", out_path, flush=True)
        manifest.append({"file": os.path.basename(out_path), "title": title})
        continue
    try:
        name = pick_file(ident, key)
        if not name:
            print("[缺文件]", ident, key, flush=True)
            continue
        if not os.path.exists(raw_path) or os.path.getsize(raw_path) < 100_000:
            download(ident, name, raw_path)
        if transcode(raw_path, out_path):
            print("[OK]", out_path, round(os.path.getsize(out_path) / 1048576, 1), "MB", flush=True)
            manifest.append({"file": os.path.basename(out_path), "title": title})
            try:
                os.remove(raw_path)
            except OSError:
                pass
    except Exception as e:
        print("[失败]", ident, type(e).__name__, e, flush=True)

with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print("ALL DONE", len(manifest), "部", flush=True)
