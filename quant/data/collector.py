"""
Historical Data Collector
补全6个月5m/15m/1h/4h K线 + 费率历史
智能探测：先查Binance最早可用数据，只拉缺失部分
"""
import json, time, urllib.request, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.config import DUCKDB_PATH, PRIORITY_COINS
from quant.data.db import DuckDBManager

BINANCE_KLINE = 'https://fapi.binance.com/fapi/v1/klines'
BINANCE_FUNDING = 'https://fapi.binance.com/fapi/v1/fundingRate'

def fetch_klines(symbol, interval, start_ms=None, end_ms=None, limit=1000):
    """拉取K线"""
    params = f'symbol={symbol}&interval={interval}&limit={limit}'
    if start_ms:
        params += f'&startTime={start_ms}'
    if end_ms:
        params += f'&endTime={end_ms}'
    url = f'{BINANCE_KLINE}?{params}'
    r = urllib.request.urlopen(url, timeout=30)
    return json.loads(r.read())

def fetch_funding(symbol, start_ms=None, limit=1000):
    """拉取费率历史"""
    params = f'symbol={symbol}&limit={limit}'
    if start_ms:
        params += f'&startTime={start_ms}'
    url = f'{BINANCE_FUNDING}?{params}'
    r = urllib.request.urlopen(url, timeout=30)
    return json.loads(r.read())

def get_earliest_ts(symbol, interval):
    """探测Binance最早可用K线时间戳"""
    klines = fetch_klines(symbol, interval, limit=1)
    if klines:
        return klines[0][0]
    return None

def main(target_coin=None, target_rows=None):
    """拉取历史K线 + 费率
    
    Args:
        target_coin: 单个币种或None(全部30个)
        target_rows: 每个周期目标行数，默认: 5m=50000, 15m=20000, 1h=5000, 4h=1500
    """
    coins = [target_coin] if target_coin else PRIORITY_COINS
    intervals = ['5m', '15m', '1h', '4h']
    
    if target_rows is None:
        target_rows = {'5m': 50000, '15m': 20000, '1h': 5000, '4h': 1500}
    
    print(f'=== Data Collector ===')
    print(f'Coins: {len(coins)}, Target rows: {target_rows}')
    
    with DuckDBManager(DUCKDB_PATH) as db:
        for coin_idx, coin in enumerate(coins):
            print(f'\n[{coin_idx+1}/{len(coins)}] {coin}')
            
            # 1. K线数据
            for interval in intervals:
                target = target_rows.get(interval, 5000)
                
                # 查当前行数 + 最早时间
                existing = db.con.execute(f"""
                    SELECT COUNT(*), MIN(open_time) FROM kline
                    WHERE symbol='{coin}' AND interval='{interval}'
                """).fetchone()
                existing_cnt, earliest_db = existing[0], existing[1]
                
                if existing_cnt >= target:
                    print(f'  {interval}: {existing_cnt} rows ✓ (target={target})')
                    continue
                
                needed = target - existing_cnt
                print(f'  {interval}: {existing_cnt} rows, need {needed} more')
                
                # 从DB最早时间向前分页拉取
                end_ms = earliest_db - 60000 if earliest_db and earliest_db > 1e12 else None
                total_new = 0
                batch_count = 0
                
                while batch_count < 200:  # max 200 batches per interval
                    try:
                        klines = fetch_klines(coin, interval, limit=1000, end_ms=end_ms)
                        batch_count += 1
                    except Exception as e:
                        print(f'    ERROR: {e}')
                        break
                    
                    if not klines:
                        break
                    
                    inserted = 0
                    for k in klines:
                        try:
                            db.con.execute(f"""
                                INSERT OR IGNORE INTO kline VALUES (
                                    '{coin}','{interval}',{k[0]},{k[1]},{k[2]},{k[3]},{k[4]},
                                    {k[5]},{k[7]},{k[8]},{k[9]},{k[10]}
                                )
                            """)
                            inserted += 1
                        except Exception:
                            pass
                    
                    total_new += inserted
                    end_ms = klines[0][0] - 60000
                    
                    if len(klines) < 1000 or total_new >= needed:
                        break
                    time.sleep(0.08)
                
                print(f'    → +{total_new} new rows')
            
            # 2. 费率历史
            fr_existing = db.con.execute(f"""
                SELECT COUNT(*), MIN(funding_time) FROM funding WHERE symbol='{coin}'
            """).fetchone()
            fr_cnt, fr_earliest = fr_existing[0], fr_existing[1]
            
            if fr_cnt < 500:
                fr_start = (fr_earliest - 1) if fr_earliest and fr_earliest > 1e12 else 0
                total_fr = 0
                for _ in range(50):
                    try:
                        rates = fetch_funding(coin, start_ms=fr_start, limit=1000)
                    except Exception as e:
                        print(f'  funding ERROR: {e}')
                        break
                    if not rates:
                        break
                    for r in rates:
                        try:
                            db.con.execute(
                                "INSERT OR IGNORE INTO funding VALUES (?,?,?)",
                                (coin, r['fundingTime'], float(r['fundingRate']))
                            )
                            total_fr += 1
                        except:
                            pass
                    fr_start = rates[0]['fundingTime'] - 1
                    if len(rates) < 1000:
                        break
                    time.sleep(0.08)
                print(f'  funding: {fr_cnt}→{fr_cnt+total_fr} rows')
            
            time.sleep(0.2)

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else None)
