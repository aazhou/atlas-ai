import duckdb, urllib.request, json, time
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
con = duckdb.connect(DB)

TARGETS = ['TUSDT','ETHUSDT','BTCUSDT','ZECUSDT','SKLUSDT','DOGEUSDT']
INTERVALS = ['1h','4h']
START_MS = 1735689600000

total = 0
for sym in TARGETS:
    for intv in INTERVALS:
        earliest = con.execute(f"SELECT COALESCE(MIN(open_time), 99999999999999) FROM kline WHERE symbol='{sym}' AND interval='{intv}'").fetchone()[0]
        existing = (int(datetime.now().timestamp()*1000) - earliest)/86400000 if earliest < 99999999999998 else 0
        
        if existing > 180:
            print(f'  {sym} {intv}: {existing:.0f}d skip')
            continue
        
        start = START_MS
        sym_new = 0; batches = 0
        while batches < 500:
            try:
                url = f'https://api.binance.com/api/v3/klines?symbol={sym}&interval={intv}&limit=1000&startTime={start}'
                r = urllib.request.urlopen(url, timeout=15)
                data = json.loads(r.read())
                time.sleep(0.08)
            except: break
            
            if not data or len(data) < 2: break
            inserted = 0
            for k in data:
                ot = k[0]
                if ot >= earliest: continue
                con.execute(f"INSERT INTO kline VALUES ('{sym}','{intv}',{ot},{k[1]},{k[2]},{k[3]},{k[4]},{k[5]},{k[7]},{k[8]},{k[9]},{k[10]})")
                inserted += 1
            if inserted == 0: break
            sym_new += inserted
            start = data[-1][0] + (3600000 if intv=='1h' else 14400000)
            batches += 1
        
        if sym_new:
            total += sym_new
            print(f'  {sym} {intv}: +{sym_new} candles')
        # else silent - stay quiet if no new data

con.close()
print(f'\nTotal: {total}')
