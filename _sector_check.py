"""拉板块资金流 - 备选方案"""
import json, urllib.request, os

# 读取今日fund_flows
DATA = r"C:\Users\admin\aazhous-projects\atlas-ai\data\stock"
today = "2026-07-14"

ff = os.path.join(DATA, f"fund_flows-{today}.json")
if os.path.exists(ff):
    with open(ff) as f:
        data = json.load(f)
    print(f"记录时间: {data.get('timestamp','?')}")
    sectors = data.get("sectors", [])
    # 按主力净流入排序
    sectors.sort(key=lambda x: x.get("flow", 0), reverse=True)
    print("\n=== TOP10 主力净流入 ===")
    for s in sectors[:10]:
        print(f"  {s['name']}: {s['flow']:+.1f}亿 | {s.get('chg_pct',0):+.2f}%")
    print("\n=== BOTTOM10 主力净流出 ===")
    for s in sectors[-10:]:
        print(f"  {s['name']}: {s['flow']:+.1f}亿 | {s.get('chg_pct',0):+.2f}%")
else:
    print("fund_flows文件不存在")

# 也读sectors
sf = os.path.join(DATA, f"sectors-{today}.json")
if os.path.exists(sf):
    with open(sf) as f:
        etf_data = json.load(f)
    print(f"\n=== ETF板块 (记录时间: {etf_data.get('timestamp','?')}) ===")
    etfs = etf_data.get("sectors", [])
    etfs.sort(key=lambda x: x.get("chg_pct", 0), reverse=True)
    for e in etfs[:5]:
        print(f"  🟢 {e['name']}: {e['chg_pct']:+.2f}%")
    print("  ...")
    for e in etfs[-5:]:
        print(f"  🔴 {e['name']}: {e['chg_pct']:+.2f}%")
