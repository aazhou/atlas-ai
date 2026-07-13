"""
拉取6个月5m K线历史 - 用 startTime 分页正向拉取
"""
import duckdb, json, urllib.request, time
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
INTERVAL = '5m'
BATCH = 1000

# Start from Jan 1 2025
START_MS = 1735689600000
MAX_BATCHES = 52  # ~6 months of 5m data

def fetch_from(start_ms, symbol):
    try:
        url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={INTERVAL}&limit={BATCH}&startTime={start_ms}'
        r = urllib.request.urlopen(url, timeout=15)
        return json.loads(r.read())
    except Exception as e:
        return None

con = duckdb.connect(DB)

# Focus on top 20 liquid + backtest-relevant coins
syms = [s[0] for s in con.execute("""
    SELECT symbol FROM (
        SELECT symbol, AVG(volume*close) as avg_vol 
        FROM kline WHERE interval='5m' 
        GROUP BY symbol ORDER BY avg_vol DESC LIMIT 20
    )
    UNION
    SELECT 'TUSDT'
    UNION SELECT 'EVAAUSDT'
    UNION SELECT 'SKLUSDT' 
    UNION SELECT 'LABUSDT'
    UNION SELECT 'LITUSDT'
    UNION SELECT 'HMSTRUSDT'
""").fetchall()]

print(f'Pulling history for {len(syms)} symbols from {datetime.fromtimestamp(START_MS/1000)}')

total = 0
for sym in syms:
    earliest = con.execute(f"SELECT COALESCE(MIN(open_time), 99999999999999) FROM kline WHERE symbol='{sym}' AND interval='5m'").fetchone()[0]
    
    if earliest and earliest <= START_MS + 86400000:  # already has Jan data
        have_from = datetime.fromtimestamp(earliest/1000).strftime('%Y-%m-%d')
        print(f'  {sym:20s} has data from {have_from}, skip')
        continue
    
    start = START_MS
    sym_new = 0
    batch_n = 0
    
    while batch_n < MAX_BATCHES:
        data = fetch_from(start, sym)
        if not data or len(data) < 2:
            break
        
        inserted = 0
        for k in data:
            ot = k[0]
            if earliest and ot >= earliest:
                continue
            try:
                con.execute(f"""
                    INSERT OR IGNORE INTO kline VALUES (
                        '{sym}', '{INTERVAL}', {ot}, {k[1]}, {k[2]}, {k[3]}, {k[4]}, {k[5]}, {k[7]}, {k[8]}, {k[9]}, {k[10]}
                    )
                """)
                inserted += 1
            except Exception as e:
                pass
        
        if inserted == 0:
            break  # reached existing data
        
        sym_new += inserted
        start = data[-1][0] + 60000  # next batch starts after last candle
        batch_n += 1
        time.sleep(0.1)
    
    if sym_new:
        print(f'  {sym:20s} +{sym_new} candles ({batch_n} batches)')
    else:
        print(f'  {sym:20s} 0 new')
    total += sym_new

con.close()
print(f'\nTotal new: {total} candles')
