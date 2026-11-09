# 从今天的 log/messages-*.log 重算今日台面数据（人数/互动/礼物），写 Live2D/live_stats.json
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent.parent
day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
log = ROOT / 'log' / f'messages-{day}.log'
out = ROOT / 'Live2D' / 'live_stats.json'

st = {'date': day, 'users': 0, 'hellos': 0, 'comments': 0, 'replies': 0,
      'gifts': 0, 'coins': 0, 'names': []}
names = []
TESTS = ('测试', '统计测试', '对账测试')
if not log.exists():
    print('没有日志：', log)
else:
    for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
        parts = [p.strip() for p in line.split('|')]
        if len(parts) < 5:
            continue
        stage = parts[2]
        kind = parts[3]
        user = parts[4].replace('用户=', '', 1)
        content = parts[5].replace('内容=', '', 1) if len(parts) > 5 else ''
        if stage == 'IN':
            if user and user not in names and not any(t in user for t in TESTS):
                names.append(user)
            if kind == '弹幕':
                st['comments'] += 1
            elif kind in ('进场', '关注'):
                st['hellos'] += 1
            elif kind == '礼物':
                st['gifts'] += 1
                m = re.search(r'(\d+)\s*个', content)
                if m:
                    st['gifts'] += int(m.group(1)) - 1
                m = re.search(r'[（(](\d+)\s*抖币', content)
                if m:
                    st['coins'] += int(m.group(1))
        elif stage == 'OUT':
            if parts[1] not in ('#-', '-'):
                st['replies'] += 1

st['users'] = len(names)
st['names'] = names[-2000:]
out.write_text(json.dumps(st, ensure_ascii=False), encoding='utf-8')
print(json.dumps({k: v for k, v in st.items() if k != 'names'}, ensure_ascii=False))
