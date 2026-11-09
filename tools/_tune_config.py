import json

p = 'config.json'
c = json.load(open(p, encoding='utf-8'))
c['schedule'][1]['enable'] = False
c['schedule'][0]['copy'] = ['现在是{time}，本鱼继续营业。', '报时：{time}，别熬夜。']
json.dump(c, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=4)
print('schedule =', [(s['enable'], s['copy'][0]) for s in c['schedule']])
print('read_comment =', c['read_comment']['enable'])
print('local_qa =', c['local_qa']['text']['enable'])
print('integral =', c['integral']['enable'])
