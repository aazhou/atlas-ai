"""DuckDB 多周期数据拉取 — 直接跑，不依赖 agent"""
import duckdb, json, time, sys, urllib.request

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
INTERVALS = {'5m': 1000, '15m': 1000, '1h': 500, '4h': 500, '1d': 365}
SYM_LIMIT = 200  # 分批拉
VOL_THRESHOLD = 10_000_000  # $10M

def fetch(url, retries=3):
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == retries - 1: raise e
            time.sleep(2)

print("Step 1: 获取 ticker 过滤...")
tickers = fetch("https://fapi.binance.com/fapi/v1/ticker/24hr")
qualified = [(t['symbol'], float(t['quoteVolume']), float(t['lastPrice']))
             for t in tickers if t['symbol'].endswith('USDT') and float(t['quoteVolume']) > VOL_THRESHOLD]
qualified.sort(key=lambda x: x[1], reverse=True)
symbols = [s for s, v, p in qualified[:SYM_LIMIT]]
print(f"  {len(symbols)} 币种过门槛 (24h>$10M)")

con = duckdb.connect(DB)
con.execute("DROP TABLE IF EXISTS kline")
con.execute("""
    CREATE TABLE kline (
        symbol VARCHAR, interval VARCHAR, open_time BIGINT,
        open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
        volume DOUBLE, quote_volume DOUBLE,
        num_trades BIGINT, taker_buy_volume DOUBLE, taker_buy_quote_volume DOUBLE,
        PRIMARY KEY (symbol, interval, open_time)
    )
""")

print(f"  待拉取: {len(symbols)} 币种")

total_candles = 0
for idx, sym in enumerate(symbols):
    for interval, limit in INTERVALS.items():
        try:
            url = f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval={interval}&limit={limit}"
            candles = fetch(url, retries=2)
            if not candles: continue

            values = []
            for c in candles:
                values.append(f"('{sym}','{interval}',{c[0]},{c[1]},{c[2]},{c[3]},{c[4]},{c[5]},{c[7]},{c[8]},{c[9]},{c[10]})")

            # Batch insert
            for chunk_start in range(0, len(values), 500):
                chunk = values[chunk_start:chunk_start+500]
                if chunk:
                    sql = f"""INSERT OR REPLACE INTO kline VALUES {','.join(chunk)}"""
                    con.execute(sql)

            total_candles += len(candles)
            time.sleep(0.2)
        except Exception as e:
            print(f"  ERR {sym} {interval}: {e}", file=sys.stderr)

    if (idx+1) % 10 == 0:
        con.commit()
        cnt = con.execute("SELECT COUNT(*) FROM kline").fetchone()[0]
        syms = con.execute("SELECT COUNT(DISTINCT symbol) FROM kline").fetchone()[0]
        print(f"  [{idx+1}/{len(symbols)}] {cnt:,} candles / {syms} symbols")

con.commit()
final_cnt = con.execute("SELECT COUNT(*) FROM kline").fetchone()[0]
final_syms = con.execute("SELECT COUNT(DISTINCT symbol) FROM kline").fetchone()[0]
print(f"\nDONE: {final_cnt:,} K线 / {final_syms} 币种")
con.close()
