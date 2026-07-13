"""
智能5m数据拉取: 自动探测Binance可用范围
策略: 先无参数请求获取最早可用的1000根K线 → 如果比DB早就拉取
"""
import duckdb, json, urllib.request, time
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
INTERVAL = '5m'
BATCH = 1000

con = duckdb.connect(DB, read_only=True)
syms = [s[0] for s in con.execute("""
    SELECT symbol FROM (
        SELECT symbol, AVG(volume*close) as avg_vol, 
               (MAX(open_time)-MIN(open_time))/86400000.0 as days
        FROM kline WHERE interval='5m'
        GROUP BY symbol HAVING avg_vol > 100000
        ORDER BY avg_vol DESC
    )
""").fetchall()]
con.close()

print(f'Processing {len(syms)} coins (vol > $100K)')

total = 0
for idx, sym in enumerate(syms):
    con = duckdb.connect(DB)
    earliest_db = con.execute(f"SELECT COALESCE(MIN(open_time), 99999999999999) FROM kline WHERE symbol='{sym}' AND interval='5m'").fetchone()[0]
    existing_days = (int(datetime.now().timestamp()*1000) - earliest_db) / 86400000 if earliest_db < 99999999999998 else 0
    
    # Probe Binance for earliest available (no startTime = most recent 1000)
    try:
        url = f'https://api.binance.com/api/v3/klines?symbol={sym}&interval={INTERVAL}&limit={BATCH}'
        r = urllib.request.urlopen(url, timeout=10)
        recent = json.loads(r.read())
        time.sleep(0.05)
    except:
        con.close()
        continue
    
    if not recent or len(recent) < 2:
        con.close()
        continue
    
    recent_start = recent[0][0]
    
    # If DB already has data older than recent_start, we're caught up
    if earliest_db and earliest_db <= recent_start:
        con.close()
        continue
    
    # Probe earliest available (with startTime=0)
    try:
        url = f'https://api.binance.com/api/v3/klines?symbol={sym}&interval={INTERVAL}&limit={BATCH}&startTime=0'
        r = urllib.request.urlopen(url, timeout=10)
        old = json.loads(r.read())
        time.sleep(0.05)
    except:
        con.close()
        continue
    
    if not old or len(old) < 2:
        con.close()
        continue
    
    earliest_available = old[0][0]
    
    # Check if DB already covers this
    if earliest_db and earliest_db <= earliest_available:
        have_from = datetime.fromtimestamp(earliest_db/1000).strftime('%Y-%m-%d')
        con.close()
        continue
    
    # Pull from Binance earliest to DB earliest
    start = earliest_available
    sym_new = 0
    batches = 0
    
    while batches < 100:  # safety limit
        try:
            url = f'https://api.binance.com/api/v3/klines?symbol={sym}&interval={INTERVAL}&limit={BATCH}&startTime={start}'
            r = urllib.request.urlopen(url, timeout=15)
            data = json.loads(r.read())
            time.sleep(0.08)
        except:
            break
        
        if not data or len(data) < 2:
            break
        
        inserted = 0
        for k in data:
            ot = k[0]
            if earliest_db and ot >= earliest_db:
                continue
            try:
                con.execute(f"INSERT INTO kline VALUES ('{sym}','{INTERVAL}',{ot},{k[1]},{k[2]},{k[3]},{k[4]},{k[5]},{k[7]},{k[8]},{k[9]},{k[10]})")
                inserted += 1
            except:
                pass
        
        if inserted == 0:
            break
        
        sym_new += inserted
        start = data[-1][0] + 60000
        batches += 1
        
        if batches >= 20 and inserted < 100:
            break  # sparse data, stop
    
    con.close()
    
    if sym_new:
        total += sym_new
        new_range = f"{datetime.fromtimestamp(earliest_available/1000).strftime('%m/%d')}->{datetime.fromtimestamp(recent[-1][0]/1000).strftime('%m/%d')}"
        print(f'[{idx+1}/{len(syms)}] {sym:20s} +{sym_new:>6} candles ({new_range}, {batches} batches)')
    # else: silent for coins with no new data

print(f'\nTotal new: {total} candles')
