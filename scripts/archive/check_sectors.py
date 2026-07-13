import json, re

with open(r'C:\Users\admin\aazhous-projects\atlas-ai\data\stock\sector_momentum-2026-07-13.json', 'r') as f:
    data = json.load(f)

sectors = data['sectors']

# Find all sectors and their trends
print("=== ALL SECTORS ===")
for name, info in sorted(sectors.items()):
    trend = info.get('trend', '?')
    cur = info.get('cur', 0)
    accel = info.get('accel_15_30', 0)
    print(f"  {name}: {cur:+.2f}% | trend={trend} | accel_15_30={accel:+.2f}")

# Holdings sectors
print("\n=== HOLDINGS SECTOR CHECK ===")
holdings = {
    '上海新阳(300236)': '半导体',
    '晶晨股份(688099)': '半导体',
    '立讯精密(002475)': '消费电子',
    '华东医药(000963)': '医药',
    '钢研高纳(300034)': '军工',
}
for name, sector in holdings.items():
    if sector in sectors:
        s = sectors[sector]
        print(f"  {name} → {sector}: {s['cur']:+.2f}% trend={s['trend']} accel={s.get('accel_15_30',0):+.2f}")
    else:
        print(f"  {name} → {sector}: NOT FOUND in sectors")
        # try partial match
        for k in sectors:
            if sector in k:
                print(f"    ... matched '{k}': {sectors[k]['cur']:+.2f}%")

# Also check for any positive sector
print("\n=== POSITIVE SECTORS ===")
pos = [(n, i['cur']) for n, i in sectors.items() if i['cur'] > 0]
if pos:
    for n, c in sorted(pos, key=lambda x: -x[1]):
        print(f"  {n}: +{c:.2f}%")
else:
    print("  NONE — all sectors negative")

# Check if 医药 has any variants
print("\n=== SECTOR NAMES CONTAINING 药 ===")
for k in sectors:
    if '药' in k:
        print(f"  {k}: {sectors[k]['cur']:+.2f}%")
