
import json

BASE = "C:/Users/admin/aazhous-projects/atlas-ai/data/stock"

with open(f"{BASE}/sector_momentum-2026-07-16.json", 'r') as f:
    momentum = json.load(f)

with open(f"{BASE}/sectors-2026-07-16.json", 'r') as f:
    sectors = json.load(f)

mom_sectors = momentum.get('sectors', {})
sorted_mom = sorted(mom_sectors.items(), key=lambda x: x[1].get('cur', 0), reverse=True)

print("=== 板块动量排序 ===")
for name, data in sorted_mom:
    cur = data.get('cur', 0)
    trend = data.get('trend', '?')
    bar = "RED" if cur < -1 else ("GREEN" if cur > 1 else "FLAT")
    print(f"  {bar} {name:8s} {cur:+.2f}% | {trend}")

print("\n=== 持仓板块日内走势 ===")
key_sectors = ['半导体', '芯片', '消费电子', '医药', '军工']
sec_data = sectors.get('sectors', {})

for ks in key_sectors:
    if ks not in sec_data:
        continue
    data = sec_data[ks]
    hist = data.get('history', [])
    if not hist:
        continue
    times = ['09:30', '10:00', '10:30', '11:00', '11:25', '13:00']
    print(f"\n{ks} 当前: {data['current']:+.2f}%")
    for h in hist:
        if h['time'] in times:
            print(f"  {h['time']}: {h['chg']:+.2f}%")

print("\n=== 异动记录 ===")
alerts = sectors.get('alerts', [])
for a in alerts:
    print(f"  {a}")

up = [(n,d) for n,d in sorted_mom if d.get('cur',0) > 1]
down = [(n,d) for n,d in sorted_mom if d.get('cur',0) < -1]
flat = [(n,d) for n,d in sorted_mom if -1 <= d.get('cur',0) <= 1]

print(f"\n=== 市场全景 ===")
up_str = ', '.join([f"{n}({d['cur']:+.1f}%)" for n,d in up])
dn_str = ', '.join([f"{n}({d['cur']:+.1f}%)" for n,d in down])
print(f"领涨(>1%): {len(up)}个 - {up_str}")
print(f"领跌(<-1%): {len(down)}个 - {dn_str}")
print(f"横盘: {len(flat)}个")

# 半导体
if '半导体' in sec_data:
    hist = sec_data['半导体']['history']
    o = hist[0]['chg']
    m10 = hist[6]['chg']
    m11 = hist[18]['chg']
    mclose = hist[23]['chg']
    pm = hist[24]['chg']
    print(f"\n半导体: {o:.1f}% -> 10:00 {m10:.1f}% -> 11:00 {m11:.1f}% -> 午收 {mclose:.1f}% -> 下午 {pm:.1f}%")

# 消费电子
if '消费电子' in sec_data:
    hist = sec_data['消费电子']['history']
    print(f"消费电子: 开盘{hist[0]['chg']:.1f}% -> 午收{hist[23]['chg']:.1f}% -> 当前{sec_data['消费电子']['current']:.1f}%")

# 医药
if '医药' in sec_data:
    hist = sec_data['医药']['history']
    print(f"医药: 开盘{hist[0]['chg']:.1f}% -> 午收{hist[23]['chg']:.1f}% -> 当前{sec_data['医药']['current']:.1f}%")

# 军工
if '军工' in sec_data:
    hist = sec_data['军工']['history']
    print(f"军工: 开盘{hist[0]['chg']:.1f}% -> 午收{hist[23]['chg']:.1f}% -> 当前{sec_data['军工']['current']:.1f}%")

# 资金流（fund_flows）
print("\n=== 资金流向 ===")
ff_path = f"{BASE}/fund_flows-2026-07-16.json"
try:
    with open(ff_path, 'r') as f:
        flows = json.load(f)
    if isinstance(flows, list):
        sorted_flows = sorted(flows, key=lambda x: x.get('f62', 0) if isinstance(x, dict) else 0, reverse=True)
        print(f"总板块数: {len(sorted_flows)}")
        print("流入TOP5:")
        for s in sorted_flows[:5]:
            if isinstance(s, dict):
                name = s.get('f14', '?')
                flow = s.get('f62', 0) / 1e8
                chg = s.get('f184', 0)
                print(f"  {name:10s} 净流入:{flow:+.1f}亿  涨跌:{chg:+.2f}%")
        print("流出TOP5:")
        for s in sorted_flows[-5:]:
            if isinstance(s, dict):
                name = s.get('f14', '?')
                flow = s.get('f62', 0) / 1e8
                chg = s.get('f184', 0)
                print(f"  {name:10s} 净流入:{flow:+.1f}亿  涨跌:{chg:+.2f}%")
except Exception as e:
    print(f"fund_flows 读取失败: {e}")
