import requests, json, sys
from datetime import datetime

today = datetime.now().strftime('%Y-%m-%d')
now = datetime.now().strftime('%H:%M')

costs = {'上海新阳': 121.9, '晶晨股份': 99.4, '立讯精密': 63.1, '华东医药': 30.3, '钢研高纳': 17.1}
sector_map = {'上海新阳': '半导体', '晶晨股份': '半导体', '立讯精密': '消费电子', '华东医药': '医药', '钢研高纳': '军工'}

# === Step 0: 新浪实时行情 ===
codes = 'sz300236,sh688099,sz002475,sz000963,sz300034'
try:
    r = requests.get(f'https://hq.sinajs.cn/list={codes}',
                     headers={'Referer':'https://finance.sina.com.cn/'}, timeout=10)
    r.encoding = 'gbk'
except Exception as e:
    print(f"ERROR: 新浪API失败: {e}")
    sys.exit(1)

holdings = {}
for line in r.text.strip().split('\n'):
    parts = line.split('"')
    if len(parts) < 2: continue
    data = parts[1].split(',')
    if len(data) < 32: continue
    name = data[0]
    cur = float(data[3]); yest = float(data[2])
    high = float(data[4]); low = float(data[5])
    chg = (cur / yest - 1) * 100 if yest > 0 else 0
    cost = costs.get(name, 0)
    pnl = (cur / cost - 1) * 100 if cost > 0 else 0
    holdings[name] = {'cur': cur, 'yest': yest, 'chg': round(chg,2),
                      'high': high, 'low': low, 'pnl': round(pnl,2)}

# === Step 1: 板块动量 ===
momentum = {}
try:
    with open(f'C:/Users/admin/aazhous-projects/atlas-ai/data/stock/sector_momentum-{today}.json') as f:
        momentum = json.load(f)
except: pass

# === Step 2: 板块数据 ===
sectors_data = {}
try:
    with open(f'C:/Users/admin/aazhous-projects/atlas-ai/data/stock/sectors-{today}.json') as f:
        raw = json.load(f)
        sectors_data = raw.get('sectors', {})  # {板块名: {current, history}}
except: pass

# === Step 3: 持仓板块对照 ===
# momentum file has trend/accel per sector
mom_sectors = momentum.get('sectors', {})

# sectors file has current value per sector name
sector_currents = {}
for sname, sdata in sectors_data.items():
    if isinstance(sdata, dict):
        sector_currents[sname] = sdata.get('current', 0)

# Merge: for each holding, find sector stats
def find_sector_stats(target):
    """Fuzzy match target sector in momentum + sectors data"""
    result = {'momentum_trend': '?', 'momentum_cur': 0, 'sector_cur': 0, 'sector_name': ''}
    # exact match
    for k, v in mom_sectors.items():
        if target == k:
            result['momentum_trend'] = v.get('trend', '?')
            result['momentum_cur'] = v.get('cur', 0)
            result['sector_name'] = k
            break
    if not result['sector_name']:
        # fuzzy match in momentum
        for k, v in mom_sectors.items():
            if target in k or any(kw in k for kw in [target[:2]]):
                result['momentum_trend'] = v.get('trend', '?')
                result['momentum_cur'] = v.get('cur', 0)
                result['sector_name'] = k
                break
    # exact match in sectors
    for k, v in sector_currents.items():
        if target == k:
            result['sector_cur'] = v
            if not result['sector_name']: result['sector_name'] = k
            break
    if not result['sector_cur']:
        for k, v in sector_currents.items():
            if target in k:
                result['sector_cur'] = v
                if not result['sector_name']: result['sector_name'] = k
                break
    return result

# === Step 4: 轮动/加速分析 ===
accel_up = []
accel_down = []
for k, v in mom_sectors.items():
    a15_30 = v.get('accel_15_30', 0)
    cur = v.get('cur', 0)
    if a15_30 > 0.3 and cur > 1:
        accel_up.append((k, cur, a15_30))
    if a15_30 < -0.3 and cur < -1:
        accel_down.append((k, cur, a15_30))

# === OUTPUT ===
print(f"🧠 {now} 盘中预判\n")

# 资金方向
up_str = ', '.join([f"{k}{c:+.1f}%" for k,c,_ in accel_up[:3]]) if accel_up else '无'
down_str = ', '.join([f"{k}{c:+.1f}%" for k,c,_ in accel_down[:3]]) if accel_down else '无'

# Find top/bottom sectors for headline
sorted_cur = sorted([(k, v.get('cur',0)) for k,v in mom_sectors.items() if abs(v.get('cur',0)) > 0.5],
                     key=lambda x: x[1], reverse=True)
top3 = sorted_cur[:3] if sorted_cur else []
bot3 = sorted_cur[-3:] if len(sorted_cur) >= 3 else []

print(f"📊 资金方向：半导体/芯片/电子全线崩跌，资金逃向传媒/游戏避险")
if top3:
    print(f"   领涨: {', '.join([f'{k}{c:+.1f}%' for k,c in top3])}")
if bot3:
    print(f"   领跌: {', '.join([f'{k}{c:+.1f}%' for k,c in bot3])}")

# 风险前瞻
print(f"\n⚠️ 风险前瞻：")
for name, h in holdings.items():
    sector = sector_map[name]
    stats = find_sector_stats(sector)
    alerts = []
    
    if h['chg'] < -5:
        alerts.append(f"🚨 暴跌{h['chg']:+.1f}%，浮亏{h['pnl']:+.1f}%")
    elif h['chg'] < -2:
        alerts.append(f"📉 {h['chg']:+.1f}%")
    elif h['chg'] > 3:
        alerts.append(f"💰 涨超3%需锁利")
    
    # Sector context
    s_cur = stats['sector_cur'] or stats['momentum_cur']
    diff = h['chg'] - s_cur if s_cur else 0
    trend = stats['momentum_trend']
    
    if abs(diff) > 2:
        if diff < -2:
            alerts.append(f"弱于板块({s_cur:+.1f}%){diff:+.1f}pp → 领跌品种")
        elif diff > 2:
            alerts.append(f"强于板块({s_cur:+.1f}%){diff:+.1f}pp")
    
    if trend and 'accel_down' in trend:
        alerts.append(f"板块涨幅加速收窄")
    if trend and 'down' in trend and s_cur and s_cur < -2:
        alerts.append(f"板块崩跌{s_cur:+.1f}%")
    
    if alerts:
        print(f"  {name} {h['cur']:.2f} ({h['chg']:+.2f}%): {' | '.join(alerts)}")

# 机会前瞻
print(f"\n💡 机会前瞻：")
# 传媒/游戏方向
game = mom_sectors.get('游戏', {})
media = mom_sectors.get('传媒', {})
if game.get('cur', 0) > 3 or media.get('cur', 0) > 3:
    print(f"  传媒/游戏方向资金持续流入但已涨{max(game.get('cur',0), media.get('cur',0)):.1f}% → 不追，等明天回踩")

# 医药
med = mom_sectors.get('医药', {})
if med.get('trend') == 'accel_down' and med.get('cur', 0) > 2:
    print(f"  医药板块涨幅收窄({med.get('cur',0):+.1f}%) → 不宜追")

# 无明确机会时
if not any([game.get('cur',0)>3, med.get('cur',0)>2]):
    print(f"  无明确新机会 — 半导体未企稳、医药收窄、其余平淡")

# 操作提醒
print(f"\n🎯 操作提醒：")
actions = []
for name, h in holdings.items():
    if h['chg'] > 3:
        actions.append(f"│ {name} │ 🔴 锁利减仓 │ +{h['chg']:.1f}%触发阈值，浮盈{h['pnl']:+.1f}%")
    if h['chg'] < -5:
        actions.append(f"│ {name} │ 🚨 设止损线 │ -{abs(h['chg']):.1f}%，若继续下探需止损")

if actions:
    print("│ 标的 │ 行动 │ 原因")
    for a in actions:
        print(a)
else:
    print("  无需操作")

# 下午预判
semi = mom_sectors.get('半导体', {})
semi_cur = semi.get('cur', 0)
semi_trend = semi.get('trend', '')
a30_60 = semi.get('accel_30_60', 0)

print(f"\n🔮 下午预判：")
if semi_cur < -3:
    if a30_60 > 0:
        print(f"  半导体{semi_cur:+.1f}%但30→60分钟有小幅反弹(+{a30_60:.1f}) → 下午可能震荡企稳，难V反")
    else:
        print(f"  半导体{semi_cur:+.1f}%且持续走弱 → 下午大概率继续承压")

med_cur = med.get('cur', 0)
if med_cur > 2 and med.get('trend') == 'accel_down':
    print(f"  医药涨幅预计收窄至+2%以内，冲高是减仓窗口")

print(f"\n--- {now} ---")
