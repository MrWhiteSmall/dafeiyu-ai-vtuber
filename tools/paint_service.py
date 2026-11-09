"""礼物祝福画服务：每攒够 20 个礼物，让大章鱼现场"画"一幅祝福画。

对外接口（给 Live2D 舞台页调用）：
  GET  /health
  GET  /paint?user=昵称        生成一张祝福画，返回 {ok, file, url, title, seconds}
  GET  /last                   返回最近一张画

生图用阿里百炼 wan2.2-t2i-flash（实测 8 秒左右），存到 Live2D/assets/paint/，
舞台页按 60% 屏占比居中展示 3 秒。同时通过主程序的 /say 让大章鱼念一句感谢。
"""

import asyncio
import json
import os
import random
import sys
import time
import urllib.parse
import urllib.request
import uuid

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAINT_DIR = os.path.join(ROOT, "Live2D", "assets", "paint")
DOODLE_DIR = os.path.join(ROOT, "Live2D", "assets", "doodle")
os.makedirs(PAINT_DIR, exist_ok=True)
os.makedirs(DOODLE_DIR, exist_ok=True)

DASHSCOPE_KEY = os.environ.get("DASHSCOPE_KEY", "")
BASE = "https://dashscope.aliyuncs.com/api/v1"
MODEL = "wan2.2-t2i-flash"
MAIN_SAY = "http://127.0.0.1:8082/say"

NEG = "文字,汉字,字母,数字,水印,签名,logo,低质量,模糊,畸变,多余的手指,恐怖"
STYLE = ("中国风新年画与国画结合的高清插画，暖色宣纸质感，金色描边，画面饱满喜庆，"
         "构图干净，主体居中，无任何文字。")

# 每条：主题 + 画面描述
BLESSINGS = [
    ("身体健康", "一位鹤发童颜的老寿星手持仙桃，身旁是青松、仙鹤与飘逸的云气，背景是淡青色山峦"),
    ("家和万事兴", "一座温暖的中式庭院，屋檐下挂红灯笼，一家人围坐圆桌，桌上是热气腾腾的饭菜，院中花开满枝"),
    ("事业顺利", "一尾金色鲤鱼跃过龙门，水花与祥云翻卷，远山与朝阳相映，气势昂扬"),
    ("财源广进", "聚宝盆中金元宝与铜钱堆积如山，周围是盛开的白菜与牡丹，红绸与祥云环绕"),
    ("平安喜乐", "一只安静的青花瓷瓶插着梅花，窗前明月与竹影，案上摆着橘子与年糕，氛围温润"),
    ("步步高升", "层叠的青山与云海之间有一条向上的石阶，阶旁竹林摇曳，顶端是朝阳与飞鸟"),
]

DOODLE_STYLE = (
    "儿童简笔画（line drawing）：白纸上用黑色水笔画出来的简笔画，"
    "只有轮廓线条，内部全部留白、绝对不要涂黑、不要填色，"
    "线条简单、歪歪扭扭、常常断开或不闭合，造型稚拙、比例故意不对，"
    "像小学生随手在本子上画的，画面大面积留白，不画阴影、不上色、不写实；"
    "画面里不能出现任何文字、汉字、字母、数字、签名或水印。画的是："
)
DOODLE_NEG = ("涂黑,剪影,黑色块,实心,阴影,渐变,彩色,写实,细节,照片,3d,"
              "文字,汉字,字母,数字,水印,签名")


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
STATE = {"last": None, "busy": False, "count": 0}

# 你画我猜的题目重复率很高，同一个词画过一次就存下来，下次直接给图（省时间也省钱）
DOODLE_CACHE_FILE = os.path.join(DOODLE_DIR, ".cache.json")


def _load_doodle_cache():
    try:
        with open(DOODLE_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_doodle_cache(cache):
    try:
        tmp = DOODLE_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, DOODLE_CACHE_FILE)
    except Exception as e:
        print("[doodle] 缓存写入失败:", e, flush=True)


def _post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def _get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def submit(prompt, neg=None):
    return _post(BASE + "/services/aigc/text2image/image-synthesis",
                 {"model": MODEL,
                  "input": {"prompt": prompt, "negative_prompt": neg or NEG},
                  "parameters": {"size": "1280*1280", "n": 1}},
                 {"Authorization": "Bearer " + DASHSCOPE_KEY,
                  "Content-Type": "application/json",
                  "X-DashScope-Async": "enable"})


def wait_task(task_id, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = _get(BASE + "/tasks/" + task_id, {"Authorization": "Bearer " + DASHSCOPE_KEY})
        out = d.get("output", {})
        st = out.get("task_status")
        if st == "SUCCEEDED":
            results = out.get("results") or []
            if results:
                return results[0].get("url")
            return None
        if st in ("FAILED", "CANCELED"):
            print("[paint] 任务失败:", json.dumps(out, ensure_ascii=False)[:300], flush=True)
            return None
        time.sleep(1.0)
    return None


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return os.path.getsize(dest)


def say(text):
    try:
        body = json.dumps({"content": text, "username": "大章鱼"},
                          ensure_ascii=False).encode()
        req = urllib.request.Request(MAIN_SAY, data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8).read()
        return True
    except Exception as e:
        print("[paint] 播报失败:", e, flush=True)
        return False


def generate(user=""):
    theme, desc = random.choice(BLESSINGS)
    prompt = "%s 主题是「%s」：%s。" % (STYLE, theme, desc)
    t0 = time.time()
    r = submit(prompt)
    task_id = r.get("output", {}).get("task_id")
    if not task_id:
        return None, theme, prompt, 0, "提交失败：" + json.dumps(r, ensure_ascii=False)[:200]
    url = wait_task(task_id)
    if not url:
        return None, theme, prompt, time.time() - t0, "生成失败"
    name = "paint-%s-%s.png" % (time.strftime("%H%M%S"), uuid.uuid4().hex[:6])
    dest = os.path.join(PAINT_DIR, name)
    size = download(url, dest)
    secs = time.time() - t0
    print("[paint] 完成 %s %.1fs %.0fKB 主题=%s 用户=%s" % (name, secs, size / 1024, theme, user),
          flush=True)
    return name, theme, prompt, secs, None


@app.get("/health")
async def health():
    return {"service": "paint-service", "model": MODEL, "dir": PAINT_DIR,
            "has_key": bool(DASHSCOPE_KEY), "count": STATE["count"]}


@app.get("/last")
async def last():
    return {"ok": bool(STATE["last"]), "data": STATE["last"]}


@app.get("/paint")
async def paint(user: str = "", announce: int = 1):
    if STATE["busy"]:
        return JSONResponse({"ok": False, "error": "busy"}, status_code=429)
    STATE["busy"] = True
    try:
        if announce:
            why = random.choice([
                "谢谢%s的礼物，本大章鱼给你们画一幅画送祝福，稍等哈。",
                "%s送的礼物收到啦，那我现场画一幅，图个吉利。",
                "礼物攒够了，%s，看好了，我这就画。",
            ]) % (user or "大家")
            say(why)
        name, theme, prompt, secs, err = await asyncio.to_thread(generate, user)
        if not name:
            return JSONResponse({"ok": False, "error": err, "seconds": round(secs, 1)}, status_code=500)
        STATE["count"] += 1
        data = {"file": name, "url": "./assets/paint/" + urllib.parse.quote(name),
                "theme": theme, "seconds": round(secs, 1), "at": time.time()}
        STATE["last"] = data
        return {"ok": True, "data": data}
    finally:
        STATE["busy"] = False


@app.get("/doodle")
async def doodle(subject: str = "", announce: int = 1):
    """观众点题，大章鱼随手画个抽象草稿。"""
    subject = (subject or "").strip()[:20] or "小猫"
    cache = _load_doodle_cache()
    hit = cache.get(subject)
    if hit and os.path.exists(os.path.join(DOODLE_DIR, hit)):
        print("[doodle] 命中缓存 %s 主题=%s" % (hit, subject), flush=True)
        return {"ok": True, "data": {"file": hit, "subject": subject,
                                     "url": "./assets/doodle/" + urllib.parse.quote(hit),
                                     "seconds": 0, "cached": True, "at": time.time()}}
    if STATE["busy"]:
        return JSONResponse({"ok": False, "error": "busy"}, status_code=429)
    STATE["busy"] = True
    try:
        if announce:
            say(random.choice([
                "%s 说要画%s，行，我随手画个草图啊，不一定像。",
                "好，%s 点的%s，我拿笔勾两下。",
                "%s 想看%s？那我随便涂一个。",
            ]) % ("大家", subject))
        t0 = time.time()
        prompt = DOODLE_STYLE + subject + "。"
        r = await asyncio.to_thread(submit, prompt, DOODLE_NEG)
        task_id = r.get("output", {}).get("task_id")
        if not task_id:
            return JSONResponse({"ok": False, "error": "提交失败"}, status_code=500)
        url = await asyncio.to_thread(wait_task, task_id)
        if not url:
            return JSONResponse({"ok": False, "error": "生成失败"}, status_code=500)
        name = "doodle-%s-%s.png" % (time.strftime("%H%M%S"), uuid.uuid4().hex[:6])
        dest = os.path.join(DOODLE_DIR, name)
        size = await asyncio.to_thread(download, url, dest)
        secs = round(time.time() - t0, 1)
        print("[doodle] %s %.1fs %.0fKB 主题=%s" % (name, secs, size / 1024, subject), flush=True)
        cache[subject] = name
        if len(cache) > 120:  # 只留最近 120 个词
            for k in list(cache)[:len(cache) - 120]:
                cache.pop(k, None)
        _save_doodle_cache(cache)
        return {"ok": True, "data": {"file": name, "subject": subject,
                                     "url": "./assets/doodle/" + urllib.parse.quote(name),
                                     "seconds": secs, "at": time.time()}}
    finally:
        STATE["busy"] = False


if __name__ == "__main__":
    port = 8899
    print("[paint] 服务启动 http://127.0.0.1:%d  key=%s  model=%s"
          % (port, "yes" if DASHSCOPE_KEY else "NO", MODEL), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
