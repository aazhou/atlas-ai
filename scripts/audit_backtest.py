import duckdb
from datetime import datetime

con = duckdb.connect('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb', read_only=True)

# 1. Data coverage
r = con.execute("SELECT MIN(open_time), MAX(open_time) FROM kline WHERE interval='5m'").fetchone()
t1 = datetime.fromtimestamp(r[0]/1000)
t2 = datetime.fromtimestamp(r[1]/1000)
days = (r[1]-r[0])/86400000
print(f'5m K线: {t1} -> {t2}  ({days:.1f}天)')

for intv in ['15m','1h','4h','1d']:
    r = con.execute(f"SELECT MIN(open_time), MAX(open_time), COUNT(*) FROM kline WHERE interval='{intv}'").fetchone()
    if r[0]:
        t1 = datetime.fromtimestamp(r[0]/1000)
        t2 = datetime.fromtimestamp(r[1]/1000)
        print(f'{intv}: {t1} -> {t2}  ({r[2]} bars)')

r2 = con.execute("SELECT MIN(funding_time), MAX(funding_time), COUNT(*) FROM funding").fetchone()
print(f'费率: {datetime.fromtimestamp(r2[0]/1000)} -> {datetime.fromtimestamp(r2[1]/1000)}  ({r2[2]} rows)')

# 2. Volume distribution
syms = con.execute("SELECT symbol, AVG(volume*close) as avg_vol FROM kline WHERE interval='5m' GROUP BY symbol ORDER BY avg_vol DESC").fetchall()
vols = [s[1] for s in syms]
import statistics
print(f'\n成交量: median=${statistics.median(vols):,.0f}  mean=${sum(vols)/len(vols):,.0f}')
print(f'<$100K: {len([v for v in vols if v<100000])}个  <$1M: {len([v for v in vols if v<1000000])}个  >$1M: {len([v for v in vols if v>=1000000])}个')

# 3. Backtest coverage check
import json
bt = json.load(open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/backtest_all.json'))
bt_syms = set(r['symbol'] for r in bt)
all_5m = set(s[0].replace('USDT','') for s in syms)
print(f'\n回测覆盖: {len(bt_syms)}/{len(all_5m)} 币种')
print(f'回测币种: {sorted(bt_syms)}')

# Check which backtest coins have low volume
print('\n=== 回测币种成交量 ===')
for r in bt:
    sym_full = r['symbol'] + 'USDT'
    vol = con.execute(f"SELECT AVG(volume*close) FROM kline WHERE symbol='{sym_full}' AND interval='5m'").fetchone()[0]
    vol_k = vol/1000 if vol else 0
    flag = '⚠️ 低流动性' if vol_k < 100 else ('✅' if vol_k > 500 else '')
    print(f'  {r["symbol"]:10s} ${vol:>12,.0f}  {r["trades"]}T {r["direction"]} {flag}')

con.close()
