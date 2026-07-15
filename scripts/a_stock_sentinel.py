#!/usr/bin/env python3
"""A股持仓哨兵 — 每分钟轮询，触发即推送"""
import urllib.request, re, json, os, sys
from datetime import datetime

# 今日监控条件
ALERTS = {
    "sz300236": ("上海新阳", 117.0, "above", "🔔 触发减仓！高开至117-118区域，按计划减仓1/3"),
    "sz000963": ("华东医药", 30.3, "above", "🔔 到达回本线30.3！20日位置87.6%偏高，果断减仓"),
    "sz002472": ("双环传动", 42.0, "below", "🔔 回踩42到位！机器人利好+站上MA20/60，可介入"),
}

# 已触发记录（防重复推送）
STATE_FILE = r"C:\Users\admin\aazhous-projects\atlas-ai\data\sentinel_state.json"
try:
    with open(STATE_FILE) as f:
        triggered = json.load(f)
except:
    triggered = {}

codes = ",".join(ALERTS.keys())
url = f"https://hq.sinajs.cn/list={codes}"
req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
resp = urllib.request.urlopen(req, timeout=10)
raw = resp.read().decode("gbk")

now = datetime.now().strftime("%H:%M:%S")
output = []
new_triggers = []

for line in raw.strip().split("\n"):
    m = re.search(r'hq_str_(\w+)="(.+)"', line)
    if not m: continue
    code, d = m.group(1), m.group(2).split(",")
    name, threshold, direction, msg = ALERTS.get(code, ("", 0, "", ""))
    price = float(d[3])
    
    hit = (direction == "above" and price >= threshold) or (direction == "below" and price <= threshold)
    
    if hit and code not in triggered:
        new_triggers.append(f"{msg}（现价{price:.2f}，触发价{threshold}）")
        triggered[code] = now
    elif hit:
        output.append(f"[{now}] {name} {price:.2f} 已触发过，不重复推送")
    else:
        output.append(f"[{now}] {name} {price:.2f} 监控中（触发价{threshold}）")

# Save state
os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
with open(STATE_FILE, "w") as f:
    json.dump(triggered, f)

# Output: only print triggers for delivery; silent otherwise
if new_triggers:
    print(f"⚠️ {len(new_triggers)}个条件触发：")
    for t in new_triggers:
        print(t)
else:
    # Silent — no output = no delivery
    pass
