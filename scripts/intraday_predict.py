#!/usr/bin/env python3
"""A股盘中前瞻预判 — cron 执行"""
import requests, re, json, sys, os
from datetime import datetime

today = datetime.now().strftime('%Y-%m-%d')
DATA_DIR = r'C:\Users\admin\aazhous-projects\atlas-ai\data\stock'

# ===== Step 0: 实时行情 =====
codes = 'sz300236,sh688099,sz002475,sz000963,sz300034'
try:
    r = requests.get(f'https://hq.sinajs.cn/list={codes}',
                     headers={'Referer':'https://finance.sina.com.cn/'}, timeout=10)
    r.encoding = 'gbk'
    raw = r.text
except Exception as e:
    print(f"[ERROR] 新浪实时行情获取失败: {e}")
    sys.exit(1)

results = {}
for line in raw.strip().split('\n'):
    if not line.strip():
        continue
    match = re.search(r'var hq_str_\w+="([^"]*)"', line)
    if not match:
        continue
    data = match.group(1).split(',')
    if len(data) < 9:
        continue
    name = data[0]
    try:
        cur = float(data[3])
        yest = float(data[2])
        chg_pct = round((cur - yest) / yest * 100, 2) if yest > 0 else 0
        high = float(data[4])
        low = float(data[5])
        vol = float(data[8])
    except (ValueError, IndexError):
        continue
    
    results[name] = {
        'code': data[0],
        'cur': cur, 'yest': yest, 'chg_pct': chg_pct,
        'high': high, 'low': low, 'vol': vol
    }

print(f"=== 实时行情 {today} ===")
for k, v in results.items():
    print(f"  {k}: {v['cur']:.2f} ({v['chg_pct']:+.2f}%) 昨收:{v['yest']:.2f} 高:{v['high']:.2f} 低:{v['low']:.2f}")

# ===== Step 1: 动量数据 =====
momentum_file = os.path.join(DATA_DIR, f'sector_momentum-{today}.json')
momentum = None
if os.path.exists(momentum_file):
    with open(momentum_file, 'r', encoding='utf-8') as f:
        momentum = json.load(f)
    print(f"\n=== 板块动量 ({today}) ===")
    if 'accel_up' in momentum:
        print(f"  加速流入: {momentum['accel_up']}")
    if 'accel_down' in momentum:
        print(f"  加速流出: {momentum['accel_down']}")
    if 'rotation' in momentum:
        print(f"  轮动信号: {momentum['rotation']}")
    if 'sectors' in momentum:
        for s in momentum['sectors']:
            print(f"  {s.get('name','?')}: 涨跌幅={s.get('chg_pct',0):+.2f}% 动量={s.get('momentum','?')}")
    print(f"\n  完整JSON keys: {list(momentum.keys())}")
else:
    print(f"\n[WARN] 动量文件不存在: {momentum_file}")

# ===== Step 2: 板块原始数据 =====
sector_file = os.path.join(DATA_DIR, f'sectors-{today}.json')
sectors = None
if os.path.exists(sector_file):
    with open(sector_file, 'r', encoding='utf-8') as f:
        sectors = json.load(f)
    print(f"\n=== 板块数据 ({today}) ===")
    if isinstance(sectors, list):
        # Sort by chg_pct
        sorted_s = sorted(sectors, key=lambda x: x.get('chg_pct', 0), reverse=True)
        print("  TOP 5 领涨:")
        for s in sorted_s[:5]:
            print(f"    {s.get('name','?')}: {s.get('chg_pct',0):+.2f}%")
        print("  BOTTOM 5 领跌:")
        for s in sorted_s[-5:]:
            print(f"    {s.get('name','?')}: {s.get('chg_pct',0):+.2f}%")
    elif isinstance(sectors, dict):
        print(f"  JSON keys: {list(sectors.keys())}")
        if 'data' in sectors:
            d = sorted(sectors['data'], key=lambda x: x.get('chg_pct',0), reverse=True)
            print("  TOP 5:", [(s.get('name'), s.get('chg_pct')) for s in d[:5]])
else:
    print(f"\n[WARN] 板块文件不存在: {sector_file}")

# ===== 持仓板块映射 =====
STOCK_SECTORS = {
    '上海新阳': '半导体',
    '晶晨股份': '半导体/SoC',
    '立讯精密': '消费电子',
    '华东医药': '医药',
    '钢研高纳': '军工',
}

print("\n=== 持仓 vs 板块动量 ===")
for name, sector in STOCK_SECTORS.items():
    d = results.get(name, {})
    if not d:
        continue
    # Find matching sector in momentum
    mom_info = "无数据"
    if momentum and 'sectors' in momentum:
        for s in momentum['sectors']:
            if sector in s.get('name', ''):
                mom_info = f"动量={s.get('momentum','?')} 涨跌={s.get('chg_pct',0):+.2f}%"
                break
    print(f"  {name}({sector}): {d['chg_pct']:+.2f}% | 板块: {mom_info}")

# ===== 风险检测 =====
print("\n=== ⚠️ 风险信号 ===")
alerts = []
for name, d in results.items():
    chg = d['chg_pct']
    sector = STOCK_SECTORS.get(name, '')
    
    # 跌幅预警
    if chg <= -5:
        alerts.append(f"🚨 {name}: 暴跌 {chg:.1f}%! 现价{d['cur']:.2f}")
    elif chg <= -3:
        alerts.append(f"🔶 {name}: 跌 {abs(chg):.1f}% 现价{d['cur']:.2f}")
    
    # 板块背离检测
    if momentum and 'sectors' in momentum:
        for s in momentum['sectors']:
            if sector in s.get('name', ''):
                s_chg = s.get('chg_pct', 0)
                if chg < -1 and s_chg > 1:
                    alerts.append(f"⚠️ {name}: 个股{chg:+.1f}% vs 板块{s_chg:+.1f}% — 显著弱于板块!")
                if chg > 1 and s_chg < -1:
                    alerts.append(f"⚠️ {name}: 个股{chg:+.1f}% vs 板块{s_chg:+.1f}% — 逆板块走强，关注")

if not alerts:
    print("  无明显风险信号")
else:
    for a in alerts:
        print(f"  {a}")

print("\n[DONE]")
