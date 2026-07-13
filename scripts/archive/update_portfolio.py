import urllib.request, json, math
from datetime import datetime

# 当前持仓
holdings = [
    ('上海新阳', '300236', '半导体材料', 121.9, '20%'),
    ('晶晨股份', '688099', '半导体/SoC', 99.6, '30%'),
    ('立讯精密', '002475', '消费电子', 63.1, '20%'),
    ('华东医药', '000963', '医药', 30.3, '20%'),
    ('钢研高纳', '300034', '军工材料', 17.1, '10%'),
]

# 新浪实时价格
codes = ['sz300236','sh688099','sz002475','sz000963','sz300034']
url = 'https://hq.sinajs.cn/list=' + ','.join(codes)
req = urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
r = urllib.request.urlopen(req, timeout=10)
raw = r.read().decode('gbk')

prices = {}
for line in raw.strip().split('\n'):
    if '=' not in line: continue
    code = line.split('=')[0].replace('var hq_str_','')
    data = line.split('"')[1].split(',')
    if len(data) < 32: continue
    prices[code[2:]] = {
        'price': float(data[3]), 'prev_close': float(data[2]),
        'high': float(data[4]), 'low': float(data[5]),
        'open': float(data[1]), 'volume': float(data[8])
    }

# 读板块数据判断市场方向
import os
d = 'C:/Users/admin/aazhous-projects/atlas-ai/data/stock'
files = sorted([f for f in os.listdir(d) if f.startswith('sectors-')], reverse=True)
sector_data = None
if files:
    with open(f'{d}/{files[0]}') as f:
        sector_data = json.load(f)

market_direction = '震荡'
if sector_data:
    sectors = sector_data.get('sectors', {})
    ups = sum(1 for s in sectors.values() if s.get('current', 0) > 0)
    downs = sum(1 for s in sectors.values() if s.get('current', 0) < 0)
    if ups > downs * 2: market_direction = '偏多'
    elif downs > ups * 2: market_direction = '偏空'
    
    # Top/bottom sectors
    sorted_s = sorted(sectors.items(), key=lambda x: x[1].get('current', 0), reverse=True)
    top3 = [f'{n} {v["current"]:+.1f}%' for n, v in sorted_s[:3]]
    worst3 = [f'{n} {v["current"]:+.1f}%' for n, v in sorted_s[-3:]]

# 构建持仓
portfolio_holdings = []
for name, code, sector, cost, pos in holdings:
    p = prices.get(code)
    if not p: continue
    price = p['price']
    chg = (price/p['prev_close'] - 1) * 100
    pnl = (price/cost - 1) * 100
    
    # 判定状态
    if pnl <= -8: status = 'warn'
    elif chg <= -3: status = 'warn'
    elif chg >= 3: status = 'hold'
    else: status = 'hold'
    
    # 操作建议
    if code == '300034' and pnl <= -6:
        action = f'🔴 距-10%止损仅差4%。设硬止损15.39，跌破砍仓'
    elif code == '002475' and chg <= -2:
        action = '🟡 连跌走弱，消费电子无催化。关注60元支撑'
    elif code == '688099' and chg >= 3:
        action = '🟢 半导体利好兑现，持有不动'
    else:
        action = '持有观察'
    
    portfolio_holdings.append({
        'name': name, 'code': code, 'sector': sector,
        'position': pos, 'cost': cost, 'price': round(price, 2),
        'chg': round(chg, 2), 'pnl': round(pnl, 1),
        'status': status, 'action': action, 'alert': ''
    })

# 构建 portfolio.json
now = datetime.now().strftime('%Y-%m-%d %H:%M')
pf = {
    'updated': now,
    'holdings': portfolio_holdings,
    'market': {
        'direction': market_direction,
        'top_sectors': top3 if sector_data else [],
        'worst_sectors': worst3 if sector_data else []
    },
    'analysis': {
        'verdict': '🔴 偏空震荡 — 半导体独涨，其余普跌',
        'market': f'今日{market_direction}。半导体(+0.7%)一枝独秀，传媒游戏跌超3%。钢研高纳-3.6%领跌持仓，美伊冲突脉冲未兑现。整体赚钱效应差。',
        'portfolio': '晶晨+4%受益半导体涨价利好。钢研-6%逼近止损线。立讯连跌需关注。上海新阳/华东正常回调。',
        'actions': ['钢研高纳：设硬止损15.39(-10%)', '立讯精密：若破60减半仓', '其余：持有不动'],
        'risk': '最大风险：钢研高纳跌破止损+半导体利好消退后科技股回调'
    }
}

with open('C:/Users/admin/aazhous-projects/atlas-ai/data/stock/portfolio.json', 'w') as f:
    json.dump(pf, f, ensure_ascii=False, indent=2)

print(f'Updated portfolio.json @ {now}')
for h in pf['holdings']:
    print(f'  {h["name"]} {h["code"]} | {h["price"]} | {h["chg"]:+.1f}% | PnL {h["pnl"]:+.1f}% | {h["status"]}')
print(f'Market: {market_direction}')
