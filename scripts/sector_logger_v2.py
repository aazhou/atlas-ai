"""
板块数据采集 v2 — DuckDB存储 + JSON导出
每5分钟: 拉ETF涨跌 + 东财资金流 → DuckDB → 导出JSON供网站
"""
import requests, re, json, os, sys, urllib.request
import duckdb
from datetime import datetime, time

try:
    from trading_calendar import is_a_stock_trading_day, is_a_stock_trading_time
    if not is_a_stock_trading_day(): sys.exit(0)
    if not is_a_stock_trading_time(): sys.exit(0)
except ImportError:
    now = datetime.now()
    if now.weekday() >= 5: sys.exit(0)
    t = now.time()
    if not (time(9,30) <= t <= time(11,30) or time(13,0) <= t <= time(15,0)): sys.exit(0)

ETFS = {
    'sh512480':'半导体','sz159995':'芯片','sh515050':'5G/AI','sh512720':'计算机','sh515880':'通信',
    'sh512980':'传媒','sz159869':'游戏','sz159997':'电子','sz159732':'消费电子',
    'sh562500':'机器人','sh516110':'汽车','sh515030':'新能源车','sh512660':'军工','sh515790':'光伏',
    'sh516780':'稀土','sh516020':'化工','sh516750':'建材',
    'sh512010':'医药','sz159647':'中药','sh515170':'食品饮料','sz159996':'家电','sz159825':'农业',
    'sh512800':'银行','sh512880':'证券','sh512200':'房地产','sh515220':'煤炭','sh515210':'钢铁',
    'sh512400':'有色','sh516950':'基建','sz159611':'电力',
}

now = datetime.now()
today = now.strftime('%Y-%m-%d')
time_str = now.strftime('%H:%M')
DATA_DIR = r'C:\Users\admin\aazhous-projects\atlas-ai\data\stock'
DB_PATH = r'C:\Users\admin\aazhous-projects\atlas-ai\data\atlas.duckdb'

# 1. 拉ETF涨跌
codes = ','.join(ETFS.keys())
r = requests.get(f'https://hq.sinajs.cn/list={codes}', headers={'Referer':'https://finance.sina.com.cn/'}, timeout=10)
r.encoding = 'gbk'

sectors = {}
for line in r.text.strip().split('\n'):
    m = re.search(r'hq_str_(\w+)="(.+)"', line)
    if not m: continue
    code = m.group(1); d = m.group(2).split(',')
    cur = float(d[3]); yest = float(d[2])
    name = ETFS.get(code, code)
    sectors[name] = round((cur/yest-1)*100, 2)

# 2. 拉东财资金流 — 全量9页，覆盖450+板块
fund_flows = {}
total_flow = {'in': 0, 'out': 0, 'up': 0, 'down': 0}
for pn in range(1, 10):
    try:
        em_url = f'https://push2.eastmoney.com/api/qt/clist/get?pn={pn}&pz=50&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:2&fields=f14,f62,f184,f3'
        em_r = urllib.request.urlopen(em_url, timeout=10)
        em_data = json.loads(em_r.read())
        items = em_data.get('data',{}).get('diff',[])
        if not items:
            break
        for item in items:
            name = item.get('f14','')
            flow = item.get('f62',0) or 0
            chg = item.get('f184',0) or 0
            if name and name not in fund_flows:
                fval = round(flow/1e8, 2)
                fund_flows[name] = {'flow': fval, 'chg': round(chg, 2)}
                if fval > 0: total_flow['in'] += fval
                else: total_flow['out'] += fval
                if chg > 0: total_flow['up'] += 1
                elif chg < 0: total_flow['down'] += 1
    except Exception as e:
        if pn == 1:
            print(f'[WARN] 资金流API失败: {e}')
        break

if fund_flows:
    print(f'📊 板块资金: {total_flow["in"]:+.0f}/{total_flow["out"]:+.0f}亿 涨{total_flow["up"]}/跌{total_flow["down"]}/{len(fund_flows)}板块')

# 3. 写入 DuckDB
con = duckdb.connect(DB_PATH)
for name, chg in sectors.items():
    con.execute("INSERT OR IGNORE INTO stock_sectors VALUES (?, ?, ?, ?)", [today, time_str, name, chg])
for name, f in fund_flows.items():
    con.execute("INSERT OR IGNORE INTO stock_fund_flows VALUES (?, ?, ?, ?, ?)", [today, time_str, name, f['flow'], f['chg']])
con.close()

# 4. 导出 JSON 供网站
# sectors JSON (兼容旧版)
sector_data = {'date': today, 'updated': time_str, 'sectors': {}}
con = duckdb.connect(DB_PATH)
rows = con.execute("SELECT sector, time, chg FROM stock_sectors WHERE date=? ORDER BY time", [today]).fetchall()
for sector, t, chg in rows:
    if sector not in sector_data['sectors']:
        sector_data['sectors'][sector] = {'current': chg, 'history': []}
    sector_data['sectors'][sector]['current'] = chg
    sector_data['sectors'][sector]['history'].append({'time': t, 'chg': chg})

with open(f'{DATA_DIR}/sectors-{today}.json', 'w') as f:
    json.dump(sector_data, f, ensure_ascii=False)

# fund_flows JSON
ff_data = {'date': today, 'updated': time_str, 'sectors': {}}
rows = con.execute("SELECT sector, time, fund_flow, chg FROM stock_fund_flows WHERE date=? ORDER BY time", [today]).fetchall()
for sector, t, flow, chg in rows:
    if sector not in ff_data['sectors']:
        ff_data['sectors'][sector] = {'current': chg, 'fund_flow': flow, 'history': []}
    ff_data['sectors'][sector]['current'] = chg
    ff_data['sectors'][sector]['fund_flow'] = flow
    ff_data['sectors'][sector]['history'].append({'time': t, 'chg': chg, 'flow': flow})

with open(f'{DATA_DIR}/fund_flows-{today}.json', 'w') as f:
    json.dump(ff_data, f, ensure_ascii=False)

con.close()

# 5. 异动检测
up = [f'{n} +{c:.1f}%' for n,c in sorted(sectors.items(), key=lambda x:-x[1])[:3] if c>0]
down = [f'{n} {c:.1f}%' for n,c in sorted(sectors.items(), key=lambda x:x[1])[:3] if c<0]
if up or down:
    print(f'📊 {time_str}')
    if up: print('🟢', ' | '.join(up))
    if down: print('🔴', ' | '.join(down))
