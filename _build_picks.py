import json, os

data_dir = 'data/football'
files = {
    '2026-07-04.json': '世界杯', '2026-07-05.json': '世界杯', '2026-07-06.json': '世界杯',
    '2026-07-07.json': '世界杯', '2026-07-08.json': '世界杯', '2026-07-10.json': '世界杯',
    '2026-07-11.json': '世界杯', '2026-07-12.json': '世界杯',
    'csl-2026-07-10.json': '中超', 'csl-2026-07-11.json': '中超', 'csl-2026-07-12.json': '中超',
}
picks = []
for fn, lg in files.items():
    fp = os.path.join(data_dir, fn)
    if not os.path.exists(fp): continue
    d = json.load(open(fp, 'r', encoding='utf-8'))
    for p in d.get('top_picks', []):
        if 'hit' not in p: continue
        picks.append({
            'date': d.get('date', fn.replace('.json','').replace('csl-','')),
            'league': lg, 'round': d.get('round',''),
            'rank': p.get('rank',''), 'pick': p.get('pick',''),
            'odds': p.get('odds', 0), 'tier': p.get('tier',''),
            'hit': p.get('hit'), 'logic': p.get('logic','')
        })

result = {'updated': '2026-07-12', 'picks': picks}
json.dump(result, open(os.path.join(data_dir, 'picks_history.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

total = len(picks)
h = sum(1 for p in picks if p['hit'] is True)
m = sum(1 for p in picks if p['hit'] is False)
hl = sum(1 for p in picks if p['hit'] == 'half')
v = sum(1 for p in picks if p['hit'] == 'void')
print(f'Total: {total} | Hits: {h} | Miss: {m} | Half: {hl} | Void: {v}')
if h+m > 0: print(f'Hit rate (excl half/void): {h}/{h+m} = {h/(h+m)*100:.1f}%')

wc = [p for p in picks if p['league']=='世界杯']
cs = [p for p in picks if p['league']=='中超']
wh = sum(1 for p in wc if p['hit'] is True); wm = sum(1 for p in wc if p['hit'] is False)
ch = sum(1 for p in cs if p['hit'] is True); cm = sum(1 for p in cs if p['hit'] is False)
print(f'World Cup hit rate: {wh}/{wh+wm} = {wh/(wh+wm)*100:.1f}%' if (wh+wm)>0 else 'World Cup: n/a')
print(f'CSL hit rate: {ch}/{ch+cm} = {ch/(ch+cm)*100:.1f}%' if (ch+cm)>0 else 'CSL: n/a')
