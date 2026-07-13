"""Fetch historical funding rates from Binance API for backtesting."""
import json, time, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
import duckdb

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'crypto', 'market.duckdb')
BASE_URL = 'https://fapi.binance.com/fapi/v1'

def fetch_funding(symbol, start_ms, end_ms, limit=1000):
    """Fetch funding rate history for a symbol."""
    params = {
        'symbol': symbol,
        'startTime': start_ms,
        'endTime': end_ms,
        'limit': limit
    }
    resp = requests.get(f'{BASE_URL}/fundingRate', params=params, timeout=30)
    if resp.status_code != 200:
        return []
    return resp.json()

def main():
    # Get all symbols
    con = duckdb.connect(DB_PATH, read_only=True)
    symbols = [r[0] for r in con.execute('SELECT DISTINCT symbol FROM kline').fetchall()]
    con.close()
    
    print(f'Fetching funding history for {len(symbols)} symbols...')
    
    # Fetch last 60 days of funding (8h intervals: ~180 per symbol per 60 days)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - 60 * 24 * 3600 * 1000  # 60 days
    
    all_data = []
    for i, sym in enumerate(symbols):
        try:
            data = fetch_funding(sym, start_ms, end_ms)
            for d in data:
                all_data.append({
                    'symbol': sym,
                    'funding_time': int(d['fundingTime']),
                    'rate': float(d['fundingRate']),
                    'fetched_at': time.time()
                })
            if (i+1) % 20 == 0:
                print(f'  {i+1}/{len(symbols)} ({sym}: {len(data)} records)')
            time.sleep(0.15)  # Rate limit
        except Exception as e:
            print(f'  Error {sym}: {e}')
            time.sleep(1)
    
    print(f'\nTotal records: {len(all_data)}')
    
    # Save to JSON
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                            'data', 'crypto', 'funding_history.json')
    with open(out_path, 'w') as f:
        json.dump(all_data, f)
    print(f'Saved to {out_path}')

if __name__ == '__main__':
    main()
