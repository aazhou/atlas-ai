"""
拉取历史5m K线: 从Binance API分批拉取，补全到6个月
Binance限制: 每请求1000根(≈3.5天), 需~50次请求/币种
策略: 已有一批5m数据(7/9-7/12), 向前补到1月底
"""
import duckdb, json, urllib.request, time, os
from datetime import datetime, timedelta

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
BATCH = 1000  # max per request
INTERVAL = '5m'

def fetch_batch(symbol, end_time_ms, limit=BATCH):
    """Fetch klines ending at end_time_ms"""
    try:
        url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={INTERVAL}&limit={limit}&endTime={end_time_ms}'
        r = urllib.request.urlopen(url, timeout=15)
        return json.loads(r.read())
    except Exception as e:
        print(f'  ERR {symbol}: {e}')
        return None

con = duckdb.connect(DB)

# Target: 6 months = ~182 days
TARGET_START = int((datetime.now() - timedelta(days=182)).timestamp() * 1000)

# Get symbols with existing 5m data
syms = [s[0] for s in con.execute("SELECT DISTINCT symbol FROM kline WHERE interval='5m'").fetchall()]
print(f'Processing {len(syms)} symbols, target 6 months back to {datetime.fromtimestamp(TARGET_START/1000).strftime("%Y-%m-%d")}')

# Focus on top 30 by volume first
top30 = [s[0] for s in con.execute("""
    SELECT symbol, AVG(volume*close) as avg_vol 
    FROM kline WHERE interval='5m' 
    GROUP BY symbol ORDER BY avg_vol DESC LIMIT 30
""").fetchall()]

total_new = 0
for sym in top30:
    # Get earliest timestamp in DB
    earliest = con.execute(f"SELECT MIN(open_time) FROM kline WHERE symbol='{sym}' AND interval='5m'").fetchone()[0]
    
    if earliest and earliest <= TARGET_START:
        print(f'  {sym}: already has data from {datetime.fromtimestamp(earliest/1000).strftime("%Y-%m-%d")}')
        continue
    
    end_time = earliest if earliest else int(datetime.now().timestamp() * 1000)
    batch_count = 0
    sym_new = 0
    
    while end_time > TARGET_START and batch_count < 60:
        data = fetch_batch(sym, end_time, BATCH)
        if not data or len(data) < 2:
            break
        
        inserted = 0
        for k in data:
            ot = k[0]
            # Skip if already exists
            if earliest and ot >= earliest:
                continue
            try:
                con.execute(f"""
                    INSERT OR IGNORE INTO kline VALUES (
                        '{sym}', '{INTERVAL}', {ot}, {k[1]}, {k[2]}, {k[3]}, {k[4]}, {k[5]}, {k[6]}, {k[7]}, {k[8]}
                    )
                """)
                inserted += 1
            except:
                pass
        
        sym_new += inserted
        end_time = data[0][0] - 60000  # step back 1 min before first candle
        batch_count += 1
        
        if batch_count % 10 == 0:
            print(f'  {sym}: {batch_count} batches, {sym_new} new candles, at {datetime.fromtimestamp(end_time/1000).strftime("%m-%d %H:%M")}')
        
        time.sleep(0.15)  # rate limit
    
    if sym_new:
        print(f'  {sym}: DONE {batch_count} batches, {sym_new} new candles')
    total_new += sym_new

con.close()
print(f'\nTotal new candles: {total_new}')
