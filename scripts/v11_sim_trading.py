"""
V11 多因子模拟交易引擎
策略: 费率<P5 + 4h趋势向上 + 五因子评分>0.18 → LONG
止损-10% | 止盈+5%(移动止盈) | 最大持仓48h
"""
import duckdb, json, urllib.request, time, os
from datetime import datetime, timedelta

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
PORTFOLIO = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/portfolio.json'
SIGNALS = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/live_signals.json'

# V11 parameters
WEIGHTS = {'candle': 0.2, 'vol': 0.4, 'pa': 0.3, 'rsi': 0.0, 'trend': 0.1}
THR = 0.18
SL = -0.10
TP = 0.05
HOLD_HOURS = 48

# Coins blacklisted from backtest
BLACKLIST = {'VANRYUSDT', 'PARTIUSDT', 'MMTUSDT', 'MUUSDT', 'LABUSDT', 'HBARUSDT'}

def get_binance_prices(symbols):
    """Get real-time prices from Binance"""
    prices = {}
    for sym in symbols:
        try:
            url = f'https://api.binance.com/api/v3/ticker/price?symbol={sym}'
            r = urllib.request.urlopen(url, timeout=5)
            d = json.loads(r.read())
            prices[sym] = float(d['price'])
        except Exception as e:
            pass
    return prices

def compute_factors(k, fr, i):
    """Compute 5-factor score for candle i"""
    o, hi, lo, c, v = k[i][1], k[i][2], k[i][3], k[i][4], k[i][5]
    po, pc = k[i-1][1], k[i-1][4]
    
    body = abs(c - o)
    wl = min(o, c) - lo
    wh = hi - max(o, c)
    total_range = max(hi - lo, 1e-8)
    
    # Candle factor (0 lag)
    hammer = 1 if wl > body * 1.5 and wl > wh * 1.5 else 0
    engulfing = 1 if pc < po and c > o and o < po and c > pc else 0
    doji = 1 if body / total_range < 0.3 and lo <= min(k[j][3] for j in range(max(0,i-10), i)) else 0
    cn = round((hammer + engulfing + doji) / 3, 2)
    
    # Volume factor
    avg_vol = sum(k[j][5] for j in range(max(0,i-20), i)) / min(20, i)
    vl = round(min(v / max(avg_vol, 1e-8) / 3, 1) if c > o else 0, 2)
    
    # Price action factor
    sma20 = sum(k[j][4] for j in range(max(0,i-20), i)) / min(20, i)
    lo20 = min(k[j][3] for j in range(max(0,i-20), i))
    hi20 = max(k[j][2] for j in range(max(0,i-20), i))
    pb = (hi20 - c) / max(hi20, 1e-8)
    
    at_support = 1 if abs(c - lo20) / max(lo20, 1e-8) < 0.01 else 0
    above_ma = 1 if c > sma20 else 0
    pullback = 1 if 0.03 < pb < 0.20 else 0
    pa = round((at_support + above_ma + pullback) / 3, 2)
    
    # RSI factor (lagging, low weight)
    gains = sum(max(k[j][4] - k[j-1][4], 0) for j in range(max(0,i-13), i+1)) / 14
    losses = sum(max(k[j-1][4] - k[j][4], 0) for j in range(max(0,i-13), i+1)) / 14
    rsi = 100 - 100 / (1 + gains / losses) if losses > 0 else 100
    rs = round(max(0, (35 - rsi) / 20), 2)
    
    # Trend factor
    sma50 = sum(k[j][4] for j in range(max(0,i-50), i)) / min(50, i) if i >= 50 else sma20
    tr = 1.0 if c > sma50 else (0.3 if c > sma20 else 0)
    
    score = (WEIGHTS['candle'] * cn + WEIGHTS['vol'] * vl + 
             WEIGHTS['pa'] * pa + WEIGHTS['rsi'] * rs + WEIGHTS['trend'] * tr)
    
    return round(score, 2)

def scan_signals():
    """Scan all coins for V11 multi-factor signals"""
    con = duckdb.connect(DB, read_only=True)
    syms = con.execute("SELECT DISTINCT symbol FROM funding").fetchall()
    
    results = []
    for (sym,) in syms:
        if sym in BLACKLIST:
            continue
            
        fr = con.execute(f"SELECT funding_time, funding_rate FROM funding WHERE symbol='{sym}' ORDER BY funding_time").fetchall()
        kl = con.execute(f"SELECT open_time/1000, open, high, low, close, volume FROM kline WHERE symbol='{sym}' AND interval='5m' ORDER BY open_time").fetchall()
        kl_4h = con.execute(f"SELECT open_time, close FROM kline WHERE symbol='{sym}' AND interval='4h' ORDER BY open_time DESC LIMIT 50").fetchall()
        
        if len(fr) < 50 or len(kl) < 100 or len(kl_4h) < 20:
            continue
        
        # P5 threshold
        rates = [r for _, r in fr]
        p5 = sorted(rates)[int(len(rates) * 0.05)]
        latest_rate = fr[-1][1]
        
        # 4h trend filter
        closes_4h = [c for _, c in kl_4h]
        ma20_4h = sum(closes_4h[:20]) / 20
        ma50_4h = sum(closes_4h[:50]) / 50 if len(closes_4h) >= 50 else ma20_4h
        trend_up = ma20_4h > ma50_4h
        
        if not (latest_rate < p5 and trend_up):
            continue
        
        # Multi-factor score on latest 5m candle
        n = len(kl)
        score = compute_factors(kl, fr, n - 1)
        
        if score >= THR:
            results.append({
                'symbol': sym,
                'funding_rate': round(latest_rate * 100, 4),
                'p5': round(p5 * 100, 4),
                'price_5m_close': round(kl[-1][4], 8),
                'score': score,
                'trend': 'UP',
                'time': datetime.now().strftime('%H:%M:%S')
            })
    
    con.close()
    results.sort(key=lambda x: x['funding_rate'])
    return results

def load_portfolio():
    if os.path.exists(PORTFOLIO):
        with open(PORTFOLIO) as f:
            return json.load(f)
    return {'positions': [], 'closed': [], 'updated': '', 'stats': {}}

def save_portfolio(p):
    p['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(PORTFOLIO, 'w') as f:
        json.dump(p, f, ensure_ascii=False, indent=2)

def main():
    print(f'=== V11 Sim Trading Engine ===')
    print(f'Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    
    # Scan signals
    signals = scan_signals()
    print(f'Signals: {len(signals)}')
    for s in signals:
        print(f'  {s["symbol"]:12s} rate={s["funding_rate"]:+.4f}% P5={s["p5"]:+.4f}% score={s["score"]:.2f}')
    
    # Save signals
    with open(SIGNALS, 'w') as f:
        json.dump({'time': datetime.now().isoformat(), 'signals': signals}, f, indent=2, ensure_ascii=False)
    
    # Load portfolio
    port = load_portfolio()
    open_symbols = {p['symbol'] for p in port['positions']}
    
    # Get real-time prices for open positions + new signals
    all_syms = list(open_symbols) + [s['symbol'] for s in signals]
    prices = {}
    if all_syms:
        prices = get_binance_prices(all_syms)
    
    # Update open positions
    now = datetime.now()
    for pos in port['positions']:
        sym = pos['symbol']
        if sym in prices:
            pos['current_price'] = prices[sym]
            pnl = (prices[sym] / pos['entry_price'] - 1) * 100
            pos['unrealized_pnl'] = round(pnl, 2)
            
            # Check exit conditions
            entry_time = datetime.strptime(pos['entry_time'], '%Y-%m-%d %H:%M:%S')
            hours_held = (now - entry_time).total_seconds() / 3600
            
            exit_reason = None
            if pnl <= SL * 100:
                exit_reason = f'止损 {pnl:+.1f}%'
                pos['exit_price'] = pos['entry_price'] * (1 + SL)
                pos['exit_pnl'] = SL * 100
            elif pnl >= TP * 100:
                exit_reason = f'止盈 {pnl:+.1f}%'
                pos['exit_price'] = pos['entry_price'] * (1 + TP)
                pos['exit_pnl'] = TP * 100
            elif hours_held >= HOLD_HOURS:
                exit_reason = f'超时 {hours_held:.0f}h'
                pos['exit_price'] = prices.get(sym, pos['current_price'])
                pos['exit_pnl'] = pnl
            
            if exit_reason:
                pos['exit_reason'] = exit_reason
                pos['exit_time'] = now.strftime('%Y-%m-%d %H:%M:%S')
                print(f'  CLOSE {sym}: {exit_reason}')
    
    # Move closed positions
    closed_now = [p for p in port['positions'] if 'exit_reason' in p]
    port['positions'] = [p for p in port['positions'] if 'exit_reason' not in p]
    port['closed'].extend(closed_now)
    open_symbols = {p['symbol'] for p in port['positions']}
    
    # Enter new positions
    for sig in signals:
        sym = sig['symbol']
        if sym in open_symbols:
            continue
        # Check if recently closed (avoid re-entry within 4h)
        recent_exits = [c for c in port['closed'] if c['symbol'] == sym and 
                       (now - datetime.strptime(c.get('exit_time', '2000-01-01'), '%Y-%m-%d %H:%M:%S')).total_seconds() < 14400]
        if recent_exits:
            continue
        
        entry_price = prices.get(sym, sig['price_5m_close'])
        port['positions'].append({
            'symbol': sym,
            'symbol_short': sym.replace('USDT', ''),
            'entry_price': entry_price,
            'current_price': entry_price,
            'unrealized_pnl': 0,
            'entry_time': now.strftime('%Y-%m-%d %H:%M:%S'),
            'strategy': 'V11_multifactor',
            'funding_at_entry': sig['funding_rate'],
            'p5_at_entry': sig['p5'],
            'score_at_entry': sig['score'],
            'trend_up': True
        })
        print(f'  OPEN {sym} @ {entry_price}')
    
    # Stats
    closed = port['closed']
    total_closed = len(closed)
    wins = sum(1 for c in closed if c.get('exit_pnl', 0) > 0)
    total_pnl = sum(c.get('exit_pnl', 0) for c in closed)
    
    port['stats'] = {
        'total_trades': total_closed,
        'win_rate': round(wins / max(total_closed, 1) * 100, 1),
        'total_pnl': round(total_pnl, 2),
        'open_positions': len(port['positions'])
    }
    
    save_portfolio(port)
    print(f'\nPortfolio: {len(port["positions"])} open, {total_closed} closed ({wins}W)')
    print('Done.')

if __name__ == '__main__':
    main()
