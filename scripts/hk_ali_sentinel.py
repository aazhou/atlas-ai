#!/usr/bin/env python3
"""港股哨兵 — 阿里9988 盯盘。触发才推送。"""
import urllib.request, re, sys, os, json
from datetime import datetime

# 仅港股交易时段（9:30-12:00, 13:00-16:00）周一至周五
now = datetime.now()
if now.weekday() >= 5:
    sys.exit(0)
hm = now.hour * 60 + now.minute
if not ((570 <= hm <= 720) or (780 <= hm <= 960)):
    sys.exit(0)

STATE_FILE = r"C:\Users\admin\aazhous-projects\atlas-ai\data\hk_alibaba_sentinel.json"
triggered = {}
if os.path.exists(STATE_FILE):
    try:
        with open(STATE_FILE) as f:
            triggered = json.load(f)
    except: pass

code = "09988"
url = f"https://hq.sinajs.cn/list=hk{code}"
req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
raw = urllib.request.urlopen(req, timeout=10).read().decode("gbk")
m = re.search(r'hq_str_hk(\w+)="(.+)"', raw)
if not m:
    sys.exit(0)
d = m.group(2).split(",")
price = float(d[6])

ALERTS = [
    (119.0, "above", "🔔 阿里 {:.2f} 碰MA60(119)！缩量减1/3，放量突破则持有"),
    (102.0, "below", "🚨 阿里 {:.2f} 跌破MA20(102)！止损信号，立即评估"),
]

now_str = now.strftime("%H:%M")
output = []
for threshold, direction, msg_tpl in ALERTS:
    hit = (direction == "above" and price >= threshold) or (direction == "below" and price <= threshold)
    key = f"{direction}_{threshold}"
    if hit and key not in triggered:
        output.append(msg_tpl.format(price))
        triggered[key] = now_str

with open(STATE_FILE, "w") as f:
    json.dump(triggered, f)

if output:
    print(f"🕐 {now_str} 阿里9988 现价{price:.2f}")
    for o in output:
        print(o)
# silent otherwise
