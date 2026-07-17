
import json
from pathlib import Path
from collections import defaultdict

data_dir = Path("C:/Users/admin/aazhous-projects/atlas-ai/data/stock")

# Load 4 days of sector data
days = {}
for date in ["2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16"]:
    f = data_dir / f"sectors-{date}.json"
    if f.exists():
        with open(f, encoding='utf-8') as fh:
            days[date] = json.load(fh)

# Extract closing chg for each sector across days
sectors = {}
for date, data in days.items():
    for sector_name, sdata in data["sectors"].items():
        if sector_name not in sectors:
            sectors[sector_name] = {}
        sectors[sector_name][date] = sdata["current"]

# Calculate multi-day changes
print("=== 板块4日累计涨跌幅 (7/13 → 7/16) ===")
print(f"{'板块':<10} {'7/13':>7} {'7/14':>7} {'7/15':>7} {'7/16':>7} {'4日累计':>8} {'趋势':>10}")
print("-" * 75)

results = []
for name, data in sorted(sectors.items()):
    d13 = data.get("2026-07-13", None)
    d14 = data.get("2026-07-14", None)
    d15 = data.get("2026-07-15", None)
    d16 = data.get("2026-07-16", None)
    
    if all(v is not None for v in [d13, d14, d15, d16]):
        cum = round(d13 + d14 + d15 + d16, 2)
        if d16 > 0 and cum > 0:
            trend = "🟢偏强"
        elif d16 < -1 and cum < -3:
            trend = "🔴偏弱"
        elif d16 > 0 and cum < 0:
            trend = "🟡反弹中"
        elif d16 < 0 and cum > 0:
            trend = "🟠回调中"
        else:
            trend = "⚪横盘/弱"
        
        results.append((name, d13, d14, d15, d16, cum, trend))
        print(f"{name:<10} {d13:>+6.1f}% {d14:>+6.1f}% {d15:>+6.1f}% {d16:>+6.1f}% {cum:>+7.1f}% {trend}")

# Now check fund_flows for multi-day patterns
print("\n\n=== 东财板块资金流 4日趋势分析 ===")

all_flows = defaultdict(lambda: {"flows": [], "chgs": []})
for date in ["2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16"]:
    ff_file = data_dir / f"fund_flows-{date}.json"
    if ff_file.exists():
        with open(ff_file, encoding='utf-8') as fh:
            fdata = json.load(fh)
        for name, sdata in fdata["sectors"].items():
            all_flows[name]["flows"].append(sdata.get("fund_flow", 0))
            all_flows[name]["chgs"].append(sdata.get("current", 0))

# Find sectors with consistent inflow over 4 days
print("\n=== 连续4天主力净流入的板块 (稳定吸金) ===")
for name, data in sorted(all_flows.items()):
    if len(data["flows"]) >= 4:
        total_flow = sum(data["flows"])
        avg_flow = total_flow / len(data["flows"])
        all_positive = all(f > 0 for f in data["flows"])
        if all_positive:
            today_chg = data["chgs"][-1] if data["chgs"] else 0
            print(f"  {name:<12} 4日总流入{total_flow:+.2f}亿 日均{avg_flow:+.2f}亿 今日涨幅{today_chg:+.2f}%")

print("\n=== 连续3天以上主力净流入的板块 ===")
for name, data in sorted(all_flows.items()):
    if len(data["flows"]) >= 3:
        flows_3d = data["flows"][-3:]
        if all(f > 0 for f in flows_3d):
            total_3d = sum(flows_3d)
            today_chg = data["chgs"][-1] if data["chgs"] else 0
            print(f"  {name:<12} 近3日流入{total_3d:+.2f}亿 今日涨幅{today_chg:+.2f}%")

print("\n=== 关键发现：资金在吸但价格未大涨的板块 (背离信号) ===")
for name, data in sorted(all_flows.items()):
    if len(data["flows"]) >= 3:
        flows_3d = data["flows"][-3:]
        total_3d = sum(flows_3d)
        today_chg = data["chgs"][-1] if data["chgs"] else 0
        # Criteria: 3-day total inflow > 3 billion, but today's gain < 2% (not overtly hot)
        if total_3d > 3 and today_chg < 2 and today_chg > -2:
            print(f"  ⚡ {name:<12} 3日净流入{total_3d:+.2f}亿 | 今日涨幅仅{today_chg:+.2f}% → 资金潜伏信号")

print("\n=== 今日热门/冷门板块 Top/Bottom 10 (涨幅排序) ===")
today_flows = []
ff_file = data_dir / "fund_flows-2026-07-16.json"
if ff_file.exists():
    with open(ff_file, encoding='utf-8') as fh:
        fdata = json.load(fh)
    today_flows = [(n, d["fund_flow"], d["current"]) for n, d in fdata["sectors"].items()]
    today_flows.sort(key=lambda x: x[2], reverse=True)
    
    print("\nTOP 10 (今日涨幅):")
    for name, flow, chg in today_flows[:10]:
        hot = "🔥热门" if chg > 3 else ""
        print(f"  {name:<12} {chg:>+7.2f}% 主力{flow:>+8.2f}亿 {hot}")
    
    print("\nBOTTOM 10 (今日跌幅):")
    for name, flow, chg in today_flows[-10:]:
        print(f"  {name:<12} {chg:>+7.2f}% 主力{flow:>+8.2f}亿")
