import requests, json, os, re, sys
from datetime import datetime

today = datetime.now().strftime('%Y-%m-%d')
now = datetime.now().strftime('%H:%M')
print(f"{'='*60}")
print(f"MIDDAY PREJUDGE @ {now} | DATE: {today}")
print(f"{'='*60}")

# ── Step 0: Sina Real-time ──
print("\n── SINA REAL-TIME ──")
codes = 'sz300236,sh688099,sz002475,sz000963,sz300034'
try:
    r = requests.get(f'https://hq.sinajs.cn/list={codes}', 
                     headers={'Referer':'https://finance.sina.com.cn/'}, timeout=10)
    r.encoding = 'gbk'
    lines = r.text.strip().split('\n')
    holdings = {}
    for line in lines:
        if not line.strip():
            continue
        # var hq_str_sz300236="name, open, yest, cur, high, low, ..."
        m = re.match(r'var hq_str_(\w+)="(.+)"', line)
        if m:
            code = m.group(1)
            fields = m.group(2).split(',')
            if len(fields) >= 4:
                name = fields[0]
                open_p = float(fields[1]) if fields[1] else 0
                yest = float(fields[2]) if fields[2] else 0
                cur = float(fields[3]) if fields[3] else 0
                chg_pct = ((cur - yest) / yest * 100) if yest > 0 else 0
                holdings[code] = {
                    'name': name, 'open': open_p, 'yest': yest, 'cur': cur,
                    'chg_pct': round(chg_pct, 2)
                }
                print(f"  {code} {name}: 昨收{yest} 现价{cur} 涨跌{chg_pct:+.2f}% 开{open_p}")
except Exception as e:
    print(f"  SINA ERROR: {e}")

# ── Step 1: Momentum Data ──
print("\n── SECTOR MOMENTUM ──")
momentum_path = f'C:/Users/admin/aazhous-projects/atlas-ai/data/stock/sector_momentum-{today}.json'
try:
    with open(momentum_path, 'r', encoding='utf-8') as f:
        momentum = json.load(f)
    print(f"  updated: {momentum.get('updated','N/A')}")
    
    accel_up = momentum.get('accel_up', [])
    accel_down = momentum.get('accel_down', [])
    rotation = momentum.get('rotation', [])
    
    if accel_up:
        print(f"  🔥 加速流入({len(accel_up)}):")
        for s in accel_up[:5]:
            print(f"    {s.get('name','?')}: chg={s.get('change_pct',0)}% flow={s.get('main_flow',0)}")
    if accel_down:
        print(f"  🔻 加速流出({len(accel_down)}):")
        for s in accel_down[:5]:
            print(f"    {s.get('name','?')}: chg={s.get('change_pct',0)}% flow={s.get('main_flow',0)}")
    if rotation:
        print(f"  🔄 轮动信号:")
        for r in rotation[:3]:
            print(f"    {r}")
    
    # Check sectors matching holdings
    holdings_sector_map = {
        '300236': ['半导体', '电子'],
        '688099': ['半导体', 'SoC', '芯片'],
        '002475': ['消费电子', '电子'],
        '000963': ['医药'],
        '300034': ['军工', '航天航空'],
    }
    all_sectors = momentum.get('sectors', [])
    for code, keywords in holdings_sector_map.items():
        if code in holdings:
            for s in all_sectors:
                s_name = s.get('name', '')
                for kw in keywords:
                    if kw in s_name:
                        flow = s.get('main_flow', 0)
                        chg = s.get('change_pct', 0)
                        direction = s.get('direction', '?')
                        print(f"  [{code}] {holdings[code]['name']} → 板块{s_name}: flow={flow} chg={chg}% dir={direction}")
                        break
except FileNotFoundError:
    print(f"  FILE NOT FOUND: {momentum_path}")
except Exception as e:
    print(f"  ERROR: {e}")

# ── Step 2: Sectors raw data ──
print("\n── SECTOR RAW ──")
sectors_path = f'C:/Users/admin/aazhous-projects/atlas-ai/data/stock/sectors-{today}.json'
try:
    with open(sectors_path, 'r', encoding='utf-8') as f:
        sectors = json.load(f)
    print(f"  updated: {sectors.get('updated','N/A')}")
    alerts = sectors.get('alerts', [])
    if alerts:
        print(f"  最近异动({len(alerts)}条):")
        for a in alerts[-5:]:
            print(f"    {a}")
    
    cur = sectors.get('current', [])
    if cur:
        # Sort by change_pct
        sorted_by_chg = sorted(cur, key=lambda x: float(x.get('change_pct', 0) or 0) if x.get('change_pct') else 0, reverse=True)
        print(f"\n  TOP5 涨幅:")
        for s in sorted_by_chg[:5]:
            chg = float(s.get('change_pct', 0) or 0)
            flow = float(s.get('main_flow', 0) or 0)
            print(f"    {s.get('name','?')}: {chg:+.2f}% flow={flow:.1f}亿")
        print(f"  BOTTOM5 跌幅:")
        for s in sorted_by_chg[-5:]:
            chg = float(s.get('change_pct', 0) or 0)
            flow = float(s.get('main_flow', 0) or 0)
            print(f"    {s.get('name','?')}: {chg:+.2f}% flow={flow:.1f}亿")
except FileNotFoundError:
    print(f"  FILE NOT FOUND: {sectors_path}")
except Exception as e:
    print(f"  ERROR: {e}")

# ── Summary ──
print("\n── HOLDINGS SUMMARY ──")
for code, h in holdings.items():
    status = '🟢' if h['chg_pct'] > 0 else ('🔴' if h['chg_pct'] < 0 else '⚪')
    print(f"  {status} {code} {h['name']}: {h['cur']} ({h['chg_pct']:+.2f}%)")

print(f"\n{'='*60}")
print("DONE")
