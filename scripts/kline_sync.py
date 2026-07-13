"""
K线增量同步：从Binance API拉最新K线，更新DuckDB
用法: python kline_sync.py [--export-charts]
"""
import duckdb, json, urllib.request, time, os, sys
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
CHART_DIR = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto'
INTERVALS = ['5m', '15m', '1h', '4h']

def get_klines(symbol, interval, limit=100):
    """Fetch klines from Binance API"""
    try:
        url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
        r = urllib.request.urlopen(url, timeout=15)
        data = json.loads(r.read())
        return data
    except Exception as e:
        print(f'  API error {symbol} {interval}: {e}')
        return None

def sync_symbol(con, sym):
    """Sync latest klines for one symbol"""
    inserted = 0
    for intv in INTERVALS:
        # Get latest timestamp in DB
        existing = con.execute(f"""
            SELECT MAX(open_time) FROM kline 
            WHERE symbol='{sym}' AND interval='{intv}'
        """).fetchone()[0]
        
        klines = get_klines(sym, intv, limit=100)
        if not klines:
            continue
        
        new_rows = 0
        for k in klines:
            ot = k[0]  # open_time in ms
            if existing and ot <= existing:
                continue
            con.execute(f"""
                INSERT OR IGNORE INTO kline 
                VALUES ('{sym}', '{intv}', {ot}, {k[1]}, {k[2]}, {k[3]}, {k[4]}, {k[5]}, {k[6]}, {k[7]}, {k[8]})
            """)
            new_rows += 1
        
        if new_rows:
            print(f'  {sym} {intv}: +{new_rows} candles')
            inserted += new_rows
    
    return inserted

def export_charts(con, syms):
    """Export chart JSONs for website"""
    for sym in syms:
        short = sym.replace('USDT', '')
        for intv in ['5m', '15m', '1h']:
            rows = con.execute(f"""
                SELECT open_time/1000, open, high, low, close 
                FROM kline WHERE symbol='{sym}' AND interval='{intv}'
                ORDER BY open_time
            """).fetchall()
            
            if len(rows) < 20:
                continue
            
            klines = [{'time': int(r[0]), 'open': r[1], 'high': r[2], 'low': r[3], 'close': r[4]} for r in rows]
            
            fpath = f'{CHART_DIR}/chart_{short}_{intv}.json'
            with open(fpath, 'w') as f:
                json.dump({'klines': klines, 'markers': []}, f, default=str)

def main():
    export_only = '--export-charts' in sys.argv
    
    con = duckdb.connect(DB)
    
    if not export_only:
        syms = [s[0] for s in con.execute("SELECT DISTINCT symbol FROM kline").fetchall()]
        total = 0
        print(f'Syncing {len(syms)} symbols...')
        for sym in syms:
            n = sync_symbol(con, sym)
            total += n
            time.sleep(0.1)  # rate limit
        print(f'Total new candles: {total}')
    
    # Export charts
    if '--export-charts' in sys.argv or not export_only:
        syms = [s[0] for s in con.execute("SELECT DISTINCT symbol FROM kline").fetchall()]
        print(f'Exporting charts for {len(syms)} symbols...')
        export_charts(con, syms)
        print('Charts exported')
    
    con.close()

if __name__ == '__main__':
    main()
