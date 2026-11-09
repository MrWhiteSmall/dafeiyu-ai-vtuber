"""网页助手：给我一个能点网页的地方。
用法：写 out/web_cmd.json，它读、执行、写 out/web_result.json。
指令格式：
  {"seq":"001","url":"https://...","wait":3000,"shot":"web1.png"}
  {"seq":"002","click_text":"主播中心","wait":2500,"shot":"web2.png"}
  {"seq":"003","click_sel":"text=品类主播认证","wait":2500,"shot":"web3.png"}
  {"seq":"004","type_sel":"input","text":"你好","wait":800}
  {"seq":"005","shot":"web5.png"}          # 只截图
  {"seq":"006","eval":"document.title"}     # 取页面信息
"""
import asyncio
import json
import os

from playwright.async_api import async_playwright

DIR = r'D:\dafeiyu-ai-vtuber\out'
CMD = os.path.join(DIR, 'web_cmd.json')
RES = os.path.join(DIR, 'web_result.json')
PROFILE = os.path.join(DIR, '_webprofile')
LOG = os.path.join(DIR, 'web_agent.log')


def log(msg):
    line = f'{__import__("time").strftime("%H:%M:%S")} {msg}'
    print(line, flush=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


async def snapshot(page, shot):
    info = {
        'url': page.url,
        'title': await page.title(),
    }
    if shot:
        await page.screenshot(path=os.path.join(DIR, shot))
        info['shot'] = shot
    try:
        info['texts'] = await page.evaluate("""() => {
            const out = [];
            document.querySelectorAll('a,button,div[role=button],span,li').forEach(el => {
                const t = (el.innerText || '').trim();
                if (t && t.length <= 14 && el.offsetParent !== null) out.push(t);
            });
            return Array.from(new Set(out)).slice(0, 80);
        }""")
    except Exception as e:
        info['texts_err'] = str(e)
    return info


async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            PROFILE, channel='chrome', headless=False,
            viewport={'width': 1440, 'height': 900},
            args=['--start-maximized', '--disable-blink-features=AutomationControlled',
                  '--no-proxy-server'])
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto('https://creator.douyin.com/', wait_until='domcontentloaded')
        await page.wait_for_timeout(4000)
        await page.screenshot(path=os.path.join(DIR, 'web0.png'))
        log('browser ready: ' + page.url)

        while True:
            await asyncio.sleep(0.8)
            if not os.path.exists(CMD):
                continue
            try:
                with open(CMD, encoding='utf-8-sig') as f:
                    cmd = json.load(f)
                os.remove(CMD)
            except Exception as e:
                log(f'cmd parse error: {e}')
                continue

            seq = str(cmd.get('seq', ''))
            ok, err = True, ''
            try:
                # 换到最新的可见页（用户可能自己开了新标签）
                page = ctx.pages[-1]
                if cmd.get('url'):
                    await page.goto(cmd['url'], wait_until='domcontentloaded')
                if cmd.get('click_text'):
                    await page.get_by_text(cmd['click_text'], exact=False).first.click(timeout=8000)
                if cmd.get('click_sel'):
                    await page.locator(cmd['click_sel']).first.click(timeout=8000)
                if cmd.get('type_sel'):
                    await page.locator(cmd['type_sel']).first.fill(cmd.get('text', ''), timeout=8000)
                if cmd.get('set_files'):
                    files = cmd.get('files') or []
                    if isinstance(files, str):
                        files = [files]
                    await page.locator(cmd['set_files']).first.set_input_files(files, timeout=20000)
                    log(f'set files -> {files}')
                if cmd.get('press'):
                    await page.keyboard.press(cmd['press'])
                if cmd.get('eval'):
                    val = await page.evaluate(cmd['eval'])
                    log(f'eval -> {val}')
                await page.wait_for_timeout(int(cmd.get('wait', 1500)))
                info = await snapshot(page, cmd.get('shot'))
            except Exception as e:
                ok, err, info = False, str(e), {}
                log(f'[{seq}] ERROR {e}')

            info.update({'ok': ok, 'error': err, 'seq': seq})
            with open(RES, 'w', encoding='utf-8') as f:
                json.dump(info, f, ensure_ascii=False, indent=1)
            log(f'[{seq}] ok={ok} url={info.get("url")}')

        await ctx.close()


asyncio.run(main())
