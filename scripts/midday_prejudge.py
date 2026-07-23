import requests, re, json, os, sys
from datetime import datetime, time

now = datetime.now()
today = now.strftime('%Y-%m-%d')
print(f"🕐 {now.strftime('%H:%M')} 盘中预判 | {today} 周{['一','二','三','四','五','六','日'][now.weekday()]}")

# 交易日检查
t = now.time()
morning = time(9,30) <= t <= time(11,30)
afternoon = time(13,0) <= t <= time(15,0)
if not (morning or afternoon):
    print("[SILENT] 非交易时段")
    sys.exit(0)

# Step 0: 新浪实时行情
codes = 'sz300236,sh688099,sz002475,sz000963,sz300034'
try:
    headers = {'Referer': 'https://finance.sina.com.cn/'}
    r = requests.get(f'https://hq.sinajs.cn/list={codes}', headers=headers, timeout=10)
    r.encoding = 'gbk'
    stocks = {}
    for line in r.text.strip().split('\n'):
        if not line.strip(): continue
        parts = line.split('"')
        if len(parts) < 2: continue
        name = parts[0].split('=')[0].replace('var hq_str_', '')
        fields = parts[1].split(',')
        if len(fields) < 4: continue
        cur = float(fields[3]) if fields[3] else 0
        yest = float(fields[2]) if fields[2] else cur
        chg = round((cur/yest - 1) * 100, 2) if yest else 0
        stocks[name] = {'cur': cur, 'yest': yest, 'chg': chg, 'name': fields[0]}
    print("\n📊 实时行情:")
    for k, v in stocks.items():
        print(f"  {k}: {v['cur']:.2f}  涨跌:{v['chg']:+.2f}%  昨收:{v['yest']:.2f}")
except Exception as e:
    print(f"❌ 新浪行情拉取失败: {e}")
    sys.exit(1)
BASE = r"C:\Users\admin\aazhous-projects\atlas-ai\data\stock"

# Step 1: 动量数据
momentum_file = os.path.join(BASE, f'sector_momentum-{today}.json')
if os.path.exists(momentum_file):
    with open(momentum_file, 'r', encoding='utf-8') as f:
        mom = json.load(f)
    print(f"\n📈 板块动量:")
    accel_up = mom.get('accel_up', [])[:3]
    accel_down = mom.get('accel_down', [])[:3]
    rotation = mom.get('rotation', '')
    if accel_up:
        print(f"  加速流入: {', '.join(accel_up)}")
    if accel_down:
        print(f"  加速流出: {', '.join(accel_down)}")
    if rotation:
        print(f"  轮动信号: {rotation}")
else:
    print(f"\n⚠️ 动量文件缺失: {momentum_file}")
    mom = {}

# Step 2: 板块数据
sectors_file = os.path.join(BASE, f'sectors-{today}.json')
if os.path.exists(sectors_file):
    with open(sectors_file, 'r', encoding='utf-8') as f:
        sec = json.load(f)
    print(f"\n📋 板块数据:")
    top = sec.get('top', [])[:3]
    bottom = sec.get('bottom', [])[:3]
    if top:
        names = [t.get('name','?') for t in top]
        print(f"  TOP3: {', '.join(names)}")
    if bottom:
        names = [b.get('name','?') for b in bottom]
        print(f"  BOTTOM3: {', '.join(names)}")
else:
    print(f"\n⚠️ 板块数据文件缺失: {sectors_file}")
    sec = {}

# 持仓-板块映射
holdings_sector = {
    'sz300236': '半导体材料',
    'sh688099': '半导体/SoC',
    'sz002475': '消费电子',
    'sz000963': '医药',
    'sz300034': '军工/高温合金'
}

# 成本
costs = {
    'sz300236': 121.9,
    'sh688099': 99.4,
    'sz002475': 63.1,
    'sz000963': 30.3,
    'sz300034': 17.1
}

print(f"\n💰 盈亏分析:")
alerts = []
for code, v in stocks.items():
    cost = costs.get(code, 0)
    pnl = round((v['cur']/cost - 1)*100, 1) if cost else 0
    sector = holdings_sector.get(code, '未知')
    tag = ""
    if v['chg'] > 3:
        tag = " 🔴涨超3%建议锁利"
        alerts.append(f"{code}: +{v['chg']}% 建议减半仓锁利")
    elif v['chg'] < -3:
        tag = " 🚨跌超3%"
        alerts.append(f"{code}: {v['chg']}% 关注是否破位")
    print(f"  {code} {v['name']}: {v['cur']:.2f} ({v['chg']:+.1f}%) | 成本{cost} | 盈亏{pnl:+.1f}% | {sector}{tag}")

print(f"\n{'='*50}")
print(f"🎯 预判结论:")
print(f"{'='*50}")
