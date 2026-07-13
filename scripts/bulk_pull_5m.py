"""
并发拉取50币种5m历史K线
- 3线程并发
- 每币种自动跳过已有数据
- 目标: 补全到2025年1月
"""
import duckdb, json, urllib.request, time, threading, os
from datetime import datetime
from queue import Queue

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
START_MS = 1735689600000  # Jan 1 2025
INTERVAL = '5m'
BATCH = 1000
MAX_BATCHES = 55  # ~6 months of 5m
WORKERS = 3
RATE_LIMIT = 0.05  # seconds between API calls per thread

lock = threading.Lock()
total_inserted = 0
total_coins_done = 0
total_coins = 0

def fetch_batch(symbol, start_ms):
    try:
        url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={INTERVAL}&limit={BATCH}&startTime={start_ms}'
        r = urllib.request.urlopen(url, timeout=20)
        return json.loads(r.read())
    except Exception as e:
        return None

def pull_coin(sym):
    global total_inserted, total_coins_done
    con = duckdb.connect(DB)
    
    earliest = con.execute(f"SELECT COALESCE(MIN(open_time), 99999999999999) FROM kline WHERE symbol='{sym}' AND interval='{INTERVAL}'").fetchone()[0]
    
    # Calculate days of data already in DB
    if earliest and earliest < 99999999999998:
        existing_days = (int(datetime.now().timestamp()*1000) - earliest) / 86400000
        if existing_days > 180:  # >6 months
            con.close()
            with lock:
                total_coins_done += 1
            return
        if earliest <= START_MS + 86400000:  # already has Jan data
            con.close()
            with lock:
                total_coins_done += 1
            return
    
    start = START_MS
    sym_new = 0
    batches = 0
    
    while batches < MAX_BATCHES:
        data = fetch_batch(sym, start)
        time.sleep(RATE_LIMIT)
        
        if not data or len(data) < 2:
            break
        
        inserted = 0
        for k in data:
            ot = k[0]
            if earliest and ot >= earliest:
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
    
    con.close()
    
    with lock:
        total_coins_done += 1
        total_inserted += sym_new
        d = datetime.fromtimestamp(earliest/1000).strftime('%m/%d') if earliest and earliest<99999999999998 else 'new'
        existing = f'(had from {d})' if sym_new<1000 else ''
        print(f'[{total_coins_done}/{total_coins}] {sym:20s} +{sym_new:>6} candles {existing}')

def worker(queue):
    while True:
        sym = queue.get()
        if sym is None:
            break
        try:
            pull_coin(sym)
        except Exception as e:
            with lock:
                print(f'  ERR {sym}: {e}')
        queue.task_done()

# === Main ===
con = duckdb.connect(DB, read_only=True)
# Get all symbols sorted by volume (most liquid first)
syms = [s[0] for s in con.execute("""
    SELECT symbol FROM (
        SELECT symbol, AVG(volume*close) as avg_vol
        FROM kline WHERE interval='5m'
        GROUP BY symbol ORDER BY avg_vol DESC
    )
""").fetchall()]
con.close()

total_coins = len(syms)
print(f'Starting pull for {total_coins} coins, {WORKERS} workers')
print(f'Target: 5m data from {datetime.fromtimestamp(START_MS/1000).strftime("%Y-%m-%d")}')
print()

# Create work queue
queue = Queue()
for s in syms:
    queue.put(s)
for _ in range(WORKERS):
    queue.put(None)

threads = []
for _ in range(WORKERS):
    t = threading.Thread(target=worker, args=(queue,))
    t.start()
    threads.append(t)

for t in threads:
    t.join()

print(f'\nDone. Total inserted: {total_inserted} candles across {total_coins} coins')
