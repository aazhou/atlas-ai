"""
补全15m K线数据 — 关键币种
用 startTime 分页正向拉取，每批1000根
"""
import duckdb, json, urllib.request, time
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
INTERVAL = '15m'
BATCH = 1000
START_MS = 1735689600000  # Jan 1 2025

# 优先币种: PA-V3验证通过的 + V11持仓币种
TARGETS = [
    'SNDKUSDT', 'SOXLUSDT', 'KORUUSDT', 'ZECUSDT',  # PA-V3高分
    'ETHUSDT', 'DOGEUSDT', 'CLUSDT',                   # PA-V3中等
    'TUSDT', 'LABUSDT', 'SKLUSDT', 'EVAAUSDT',         # V11持仓
    'BTCUSDT',                                          # 基准
]

con = duckdb.connect(DB)
total_new = 0

for sym in TARGETS:
    earliest = con.execute(f"SELECT COALESCE(MIN(open_time), 99999999999999) FROM kline WHERE symbol='{sym}' AND interval='{INTERVAL}'").fetchone()[0]
    
    existing_days = (int(datetime.now().timestamp()*1000) - earliest) / 86400000 if earliest < 99999999999998 else 0
    
    if existing_days > 60:
        print(f'  {sym:18s} has {existing_days:.0f}d, skip')
        continue
    
    start = START_MS
    sym_new = 0
    batches = 0
    
    while batches < 200:  # max 200 batches = ~200 days of 15m
        try:
            url = f'https://api.binance.com/api/v3/klines?symbol={sym}&interval={INTERVAL}&limit={BATCH}&startTime={start}'
            r = urllib.request.urlopen(url, timeout=15)
            data = json.loads(r.read())
            time.sleep(0.08)
        except Exception as e:
            print(f'  {sym} ERR: {e}')
            break
        
        if not data or len(data) < 2:
            break
        
        inserted = 0
        for k in data:
            ot = k[0]
            if ot >= earliest:
                continue
            con.execute(f"INSERT INTO kline VALUES ('{sym}','{INTERVAL}',{ot},{k[1]},{k[2]},{k[3]},{k[4]},{k[5]},{k[7]},{k[8]},{k[9]},{k[10]})")
            inserted += 1
        
        if inserted == 0:
            break
        
        sym_new += inserted
        start = data[-1][0] + 900000  # 15 min after last candle
        batches += 1
        
        if batches % 20 == 0:
            dt = datetime.fromtimestamp(data[0][0]/1000).strftime('%m/%d')
            print(f'  {sym:18s} batch {batches}: +{sym_new} total, at {dt}')
    
    if sym_new > 0:
        total_new += sym_new
        new_from = datetime.fromtimestamp(START_MS/1000).strftime('%m/%d')
        new_days = sym_new * 15 / 1440  # 15m bars to days
        print(f'  {sym:18s} DONE: +{sym_new} candles (~{new_days:.0f}d)')
    else:
        print(f'  {sym:18s} 0 new')

con.close()
print(f'\nTotal new 15m candles: {total_new}')
