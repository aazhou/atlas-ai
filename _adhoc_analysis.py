"""A股午间分析 - 补发龙哥"""
import subprocess, json, sys, os
from datetime import datetime

BASE = r"C:\Users\admin\aazhous-projects\atlas-ai"
DATA = os.path.join(BASE, "data", "stock")

# ===== 1. 拉新浪实时行情（全量持仓+观察） =====
tickers = {
    "上海新阳": "sz300236",
    "嵘泰股份": "sh605133",
    "立讯精密": "sz002475",
    "华东医药": "sz000963",
    "通富微电": "sz002156",
    "纳芯微": "sh688052",
    "柯力传感": "sh603662",
    "扬杰科技": "sz300373",
    "晶晨股份": "sh688099",
}

sina_codes = ",".join(tickers.values())
url = f"https://hq.sinajs.cn/list={sina_codes}"

import urllib.request
req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
resp = urllib.request.urlopen(req, timeout=15)
raw = resp.read().decode("gbk")

results = {}
for line in raw.strip().split("\n"):
    if not line.strip():
        continue
    parts = line.split('="')
    if len(parts) < 2:
        continue
    code = parts[0].split("hq_str_")[-1]
    data = parts[1].strip('";\n').split(",")
    if len(data) < 32:
        continue
    name = data[0]
    price = float(data[3]) if data[3] else 0
    prev_close = float(data[2]) if data[2] else 0
    high = float(data[4]) if data[4] else 0
    low = float(data[5]) if data[5] else 0
    volume = float(data[8]) if data[8] else 0
    amount = float(data[9]) if data[9] else 0
    chg_pct = (price - prev_close) / prev_close * 100 if prev_close else 0
    results[name] = {
        "code": code, "price": price, "prev_close": prev_close,
        "high": high, "low": low, "chg_pct": round(chg_pct, 2),
        "volume": volume, "amount": amount
    }

print("=== 实时行情 ===")
for name, d in results.items():
    arrow = "🔴" if d["chg_pct"] < -2 else ("🟢" if d["chg_pct"] > 2 else "⚪")
    print(f"{arrow} {name} {d['code']}: {d['price']:.2f} ({d['chg_pct']:+.2f}%) 高{d['high']:.2f} 低{d['low']:.2f}")

# ===== 2. 板块资金流 =====
import urllib.parse
try:
    sector_url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=30&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:2&fields=f14,f62,f184"
    req2 = urllib.request.Request(sector_url, headers={"Referer": "https://data.eastmoney.com/"})
    resp2 = urllib.request.urlopen(req2, timeout=10)
    sector_data = json.loads(resp2.read().decode())
    sectors = sector_data.get("data", {}).get("diff", [])
    
    print("\n=== 板块资金流 TOP5 ===")
    for s in sectors[:5]:
        name = s.get("f14", "?")
        flow = float(s.get("f62", 0)) / 1e8
        chg = s.get("f184", 0)
        print(f"  {name}: 主力净流入 {flow:+.1f}亿 | 涨跌幅 {chg:+.2f}%")
    
    print("\n=== 板块资金流 BOTTOM5 ===")
    for s in sectors[-5:]:
        name = s.get("f14", "?")
        flow = float(s.get("f62", 0)) / 1e8
        chg = s.get("f184", 0)
        print(f"  {name}: 主力净流入 {flow:+.1f}亿 | 涨跌幅 {chg:+.2f}%")
except Exception as e:
    print(f"\n[板块数据拉取失败: {e}]")

# ===== 3. 读取今日sector数据（如果有的话）=====
today = datetime.now().strftime("%Y-%m-%d")
sector_file = os.path.join(DATA, f"sectors-{today}.json")
fund_flows_file = os.path.join(DATA, f"fund_flows-{today}.json")

print(f"\n=== 今日数据文件 ===")
print(f"sectors: {'✅' if os.path.exists(sector_file) else '❌'}")
print(f"fund_flows: {'✅' if os.path.exists(fund_flows_file) else '❌'}")

# ===== 4. 读portfolio.json =====
portfolio_file = os.path.join(DATA, "portfolio.json")
if os.path.exists(portfolio_file):
    with open(portfolio_file) as f:
        pf = json.load(f)
    print(f"\n=== 持仓分析 (更新于 {pf.get('updated','?')}) ===")
    for h in pf.get("holdings", []):
        print(f"  {h['name']} {h['code']}: 成本{h['cost']} | 状态{h['status']} | {h.get('action','')}")
    if pf.get("analysis"):
        a = pf["analysis"]
        print(f"\n  市场: {a.get('market','')}")
        print(f"  持仓: {a.get('portfolio','')}")

print("\n=== 数据收集完毕 ===")
