"""
Generate chart JSON for coins that passed backtest but lack chart files.
Reads from DuckDB, writes {klines, markers} JSON for 5m/15m/1h intervals.
"""
import duckdb, json, os

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
OUT = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto'

# Coins from backtest that need charts
NEED = ['SOXL', 'VIRTUAL', 'SNDK', 'SPCX', 'ARX', 'ENA', 'HBAR']
INTERVALS = ['5m', '15m', '1h']

con = duckdb.connect(DB, read_only=True)

for sym_full in NEED:
    sym = sym_full + 'USDT'
    for intv in INTERVALS:
        fname = f'chart_{sym_full}_{intv}.json'
        fpath = os.path.join(OUT, fname)
        if os.path.exists(fpath):
            print(f'  SKIP {fname} (exists)')
            continue
        
        rows = con.execute(f"""
            SELECT open_time/1000 as t, open as o, high as h, low as l, close as c, volume as v
            FROM kline WHERE symbol='{sym}' AND interval='{intv}'
            ORDER BY open_time
        """).fetchall()
        
        if len(rows) < 20:
            print(f'  SKIP {fname} ({len(rows)} rows)')
            continue
        
        klines = [{'time': int(r[0]), 'open': r[1], 'high': r[2], 'low': r[3], 'close': r[4]} for r in rows]
        
        data = {
            'symbol': sym_full,
            'interval': intv,
            'klines': klines,
            'markers': []  # no trade markers for these summary entries
        }
        
        with open(fpath, 'w') as f:
            json.dump(data, f, default=str)
        print(f'  WROTE {fname} ({len(rows)} candles)')

con.close()
print('Done')
