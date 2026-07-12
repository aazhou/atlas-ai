"""
Extreme Event Sniper Backtest
=============================
Tests 3 signal types on historical data to find high-conviction setups.

Signal 1: Panic Rebound — 15m candle drop >threshold%, track 1h recovery
Signal 2: Short Squeeze — funding < -0.3% x3 cycles then flips positive
Signal 3: Independent Launch — BTC flat, coin vol >5x avg, price tight <3%
"""
import json, os, sys, time
from datetime import datetime
from collections import defaultdict
import duckdb

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                       'data', 'crypto', 'market.duckdb')
FUNDING_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                            'data', 'crypto', 'funding_history.json')
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                           'data', 'crypto', 'sniper_strategy.json')

con = duckdb.connect(DB_PATH, read_only=True)

def load_15m_klines():
    """Load all 15m kline data as dict of symbol -> sorted list of candles."""
    rows = con.execute('''
        SELECT symbol, open_time, open, high, low, close, volume, quote_volume
        FROM kline WHERE interval='15m'
        ORDER BY symbol, open_time
    ''').fetchall()
    
    data = defaultdict(list)
    for r in rows:
        data[r[0]].append({
            'ts': r[1],
            'o': float(r[2]), 'h': float(r[3]), 'l': float(r[4]),
            'c': float(r[5]), 'v': float(r[6]), 'qv': float(r[7])
        })
    
    # Sort each list by timestamp
    for sym in data:
        data[sym].sort(key=lambda x: x['ts'])
    
    return data

def load_1h_klines():
    """Load 1h klines for Signal 2 validation."""
    rows = con.execute('''
        SELECT symbol, open_time, open, high, low, close
        FROM kline WHERE interval='1h'
        ORDER BY symbol, open_time
    ''').fetchall()
    
    data = defaultdict(list)
    for r in rows:
        data[r[0]].append({
            'ts': r[1],
            'o': float(r[2]), 'h': float(r[3]), 'l': float(r[4]), 'c': float(r[5])
        })
    
    for sym in data:
        data[sym].sort(key=lambda x: x['ts'])
    
    return data

def load_4h_klines():
    """Load 4h klines."""
    rows = con.execute('''
        SELECT symbol, open_time, open, high, low, close
        FROM kline WHERE interval='4h'
        ORDER BY symbol, open_time
    ''').fetchall()
    
    data = defaultdict(list)
    for r in rows:
        data[r[0]].append({
            'ts': r[1],
            'o': float(r[2]), 'h': float(r[3]), 'l': float(r[4]), 'c': float(r[5])
        })
    
    for sym in data:
        data[sym].sort(key=lambda x: x['ts'])
    
    return data

# ============================================================
# SIGNAL 1: Panic Rebound
# 15m candle where (low - open)/open < -threshold_pct → then track 1h max gain
# ============================================================
def backtest_panic_rebound(k15, drop_thresholds=[8, 10, 12, 15], 
                            tp_levels=[10, 15, 20, 25, 30],
                            sl_levels=[3, 5, 7, 8]):
    """
    For each 15m candle where intra-candle drop exceeds threshold:
    - Entry: close of that candle (assuming you catch it at candle close)
    - Track: next 4 candles (1h)
    - Check: does price hit TP or SL first? what's max favorable excursion?
    """
    results = []
    
    for sym, candles in k15.items():
        for i, c in enumerate(candles):
            if i < 5:  # Need 5 previous candles for context
                continue
            if i + 4 >= len(candles):  # Need 4 future candles (1h)
                continue
            
            # Calculate intra-candle drop
            intra_drop_pct = (c['l'] - c['o']) / c['o'] * 100
            
            # CRITICAL: Only consider candles that RECOVERED from the panic
            # A candle that closes near its low = continuation (worse)
            # A candle with long lower wick (close >> low) = reversal signal
            candle_range = c['h'] - c['l']
            if candle_range > 0:
                close_position = (c['c'] - c['l']) / candle_range  # 0=closed at low, 1=closed at high
            else:
                close_position = 0.5
            
            # Must close above 40% of the candle range (recovery signal)
            if close_position < 0.35:
                continue
            
            for dt in drop_thresholds:
                if intra_drop_pct > -dt:
                    continue
                if intra_drop_pct < -50:  # Filter obvious data errors
                    continue
                
                entry_price = c['c']  # Enter at close of panic candle
                if entry_price <= 0:
                    continue
                
                # Track next 4 candles (1h forward)
                future = candles[i+1:i+5]
                
                # Find max high and min low in the forward window
                max_high = max(f['h'] for f in future)
                min_low = min(f['l'] for f in future)
                final_close = future[-1]['c']
                
                max_gain_pct = (max_high - entry_price) / entry_price * 100
                max_loss_pct = (min_low - entry_price) / entry_price * 100
                final_pnl = (final_close - entry_price) / entry_price * 100
                
                for tp in tp_levels:
                    for sl in sl_levels:
                        # Determine which hits first
                        tp_hit = max_gain_pct >= tp
                        sl_hit = max_loss_pct <= -sl
                        
                        if tp_hit and sl_hit:
                            # Both hit: check which happened first candle-by-candle
                            tp_candle = None
                            sl_candle = None
                            for j, fc in enumerate(future):
                                if tp_candle is None and (fc['h'] - entry_price) / entry_price * 100 >= tp:
                                    tp_candle = j
                                if sl_candle is None and (fc['l'] - entry_price) / entry_price * 100 <= -sl:
                                    sl_candle = j
                                if tp_candle is not None and sl_candle is not None:
                                    break
                            winner = tp_candle < sl_candle if (tp_candle is not None and sl_candle is not None) else False
                            outcome = 'win' if winner else 'loss'
                            realized_pnl = tp if winner else -sl
                        elif tp_hit:
                            outcome = 'win'
                            realized_pnl = tp
                        elif sl_hit:
                            outcome = 'loss'
                            realized_pnl = -sl
                        else:
                            outcome = 'draw'
                            realized_pnl = round(final_pnl, 2)
                        
                        results.append({
                            'signal': 'panic_rebound',
                            'symbol': sym,
                            'ts': c['ts'],
                            'drop_threshold': dt,
                            'intra_drop_pct': round(intra_drop_pct, 2),
                            'close_position': round(close_position, 2),
                            'entry': round(entry_price, 4),
                            'tp': tp,
                            'sl': sl,
                            'outcome': outcome,
                            'realized_pnl': realized_pnl,
                            'max_gain': round(max_gain_pct, 2),
                            'max_loss': round(max_loss_pct, 2),
                            'final_pnl': round(final_pnl, 2)
                        })
    
    return results

# ============================================================
# SIGNAL 2: Short Squeeze
# funding < -0.3% for 3 consecutive 8h cycles → flips positive → track 4h gain
# ============================================================
def backtest_short_squeeze(funding_data, k4h, threshold=-0.003, cycles=3):
    """
    Find sequences where funding rate < threshold for N consecutive periods,
    then the next period turns positive. Track 4h price movement.
    
    funding_data: list of {symbol, funding_time, rate}
    k4h: dict of symbol -> list of 4h candles
    """
    if not funding_data:
        print("  No funding data available, skipping Signal 2")
        return []
    
    # Group funding by symbol
    fund_by_symbol = defaultdict(list)
    for f in funding_data:
        fund_by_symbol[f['symbol']].append(f)
    
    for sym in fund_by_symbol:
        fund_by_symbol[sym].sort(key=lambda x: x['funding_time'])
    
    results = []
    tp_levels = [15, 20, 25, 30, 40]
    sl_levels = [5, 8, 10, 12]
    
    for sym, fund_rates in fund_by_symbol.items():
        if sym not in k4h or len(fund_rates) < cycles + 1:
            continue
        
        candles = k4h[sym]
        # Build time index for quick lookup
        candle_map = {c['ts']: c for c in candles}
        
        for i in range(len(fund_rates) - cycles):
            # Check N consecutive negative funding periods
            period_rates = fund_rates[i:i+cycles]
            if len(period_rates) < cycles:
                continue
            
            all_negative = all(r['rate'] < threshold for r in period_rates)
            if not all_negative:
                continue
            
            # Check if next period flips positive
            if i + cycles >= len(fund_rates):
                continue
            
            next_rate = fund_rates[i+cycles]
            if next_rate['rate'] <= 0:
                continue
            
            # Signal triggered at the time of positive flip
            signal_ts = next_rate['funding_time']
            
            # Find the corresponding 4h candle and its successors
            # Find closest 4h candle after signal
            entry_candle = None
            entry_idx = None
            for j, c in enumerate(candles):
                if c['ts'] >= signal_ts:
                    entry_candle = c
                    entry_idx = j
                    break
            
            if entry_candle is None or entry_idx is None:
                continue
            if entry_idx + 1 >= len(candles):  # Need at least 1 future candle (4h)
                continue
            
            entry_price = entry_candle['o']  # Enter at open of the candle at signal time
            if entry_price <= 0:
                continue
            
            # Track next candle (4h forward)
            future_c = candles[entry_idx + 1]
            max_high = future_c['h']
            min_low = future_c['l']
            final_close = future_c['c']
            
            max_gain_pct = (max_high - entry_price) / entry_price * 100
            max_loss_pct = (min_low - entry_price) / entry_price * 100
            final_pnl = (final_close - entry_price) / entry_price * 100
            
            for tp in tp_levels:
                for sl in sl_levels:
                    tp_hit = max_gain_pct >= tp
                    sl_hit = max_loss_pct <= -sl
                    
                    if tp_hit and sl_hit:
                        # Simple: check high first or low first based on candle shape
                        # If high triggers before low, it's a win
                        high_reached_at = tp / max_gain_pct if max_gain_pct > 0 else 1
                        low_reached_at = sl / abs(max_loss_pct) if max_loss_pct < 0 else 1
                        winner = high_reached_at < low_reached_at
                        outcome = 'win' if winner else 'loss'
                        realized_pnl = tp if winner else -sl
                    elif tp_hit:
                        outcome = 'win'
                        realized_pnl = tp
                    elif sl_hit:
                        outcome = 'loss'
                        realized_pnl = -sl
                    else:
                        outcome = 'draw'
                        realized_pnl = round(final_pnl, 2)
                    
                    results.append({
                        'signal': 'short_squeeze',
                        'symbol': sym,
                        'ts': signal_ts,
                        'funding_min': round(min(r['rate']*100 for r in period_rates), 4),
                        'funding_next': round(next_rate['rate']*100, 4),
                        'entry': round(entry_price, 4),
                        'tp': tp,
                        'sl': sl,
                        'outcome': outcome,
                        'realized_pnl': realized_pnl,
                        'max_gain': round(max_gain_pct, 2),
                        'max_loss': round(max_loss_pct, 2),
                        'final_pnl': round(final_pnl, 2)
                    })
    
    return results

# ============================================================
# SIGNAL 3: Independent Launch
# BTC ±1% for 1h, coin vol >5x avg, coin price range <3% → track 6h gain
# ============================================================
def backtest_independent_launch(k15, btc_threshold=1.0, vol_mult=5, price_range=3.0):
    """
    When BTC is flat (±btc_threshold% in the current 1h window) AND
    a coin has volume >vol_mult * its 20-bar average volume AND
    price range (high-low)/open < price_range%
    → track next 24 candles (6h)
    """
    if 'BTCUSDT' not in k15:
        print("  No BTCUSDT data, skipping Signal 3")
        return []
    
    btc_candles = k15['BTCUSDT']
    results = []
    tp_levels = [10, 15, 20, 25, 30]
    sl_levels = [3, 5, 7, 8]
    
    # Build BTC 1h rolling window (4 x 15m candles)
    for sym, candles in k15.items():
        if sym == 'BTCUSDT' or len(candles) < 50:
            continue
        
        for i in range(20, len(candles) - 24):  # Need 20 for avg + 24 for 6h forward
            c = candles[i]
            
            # Find closest BTC candle by timestamp
            btc_c = None
            btc_idx = None
            for j, bc in enumerate(btc_candles):
                if bc['ts'] >= c['ts'] - 900000 and bc['ts'] <= c['ts'] + 900000:
                    btc_c = bc
                    btc_idx = j
                    break
            
            if btc_c is None:
                continue
            
            # Check BTC flatness over past 1h (4 candles)
            if btc_idx < 4:
                continue
            btc_past = btc_candles[btc_idx-3:btc_idx+1]  # 4 candles = 1h
            btc_range_pct = (max(bc['h'] for bc in btc_past) - min(bc['l'] for bc in btc_past)) / btc_past[0]['o'] * 100
            if btc_range_pct > btc_threshold:
                continue
            
            # Check coin volume > 5x average
            past_vol = [candles[k]['v'] for k in range(i-20, i) if candles[k]['v'] > 0]
            if len(past_vol) < 15:
                continue
            avg_vol = sum(past_vol) / len(past_vol)
            if c['v'] < avg_vol * vol_mult:
                continue
            
            # Check price tightness: (high-low)/open < price_range%
            coin_range = (c['h'] - c['l']) / c['o'] * 100
            if coin_range > price_range:
                continue
            
            entry_price = c['c']
            if entry_price <= 0:
                continue
            
            # Track next 24 candles (6h)
            future = candles[i+1:i+25]
            max_high = max(f['h'] for f in future)
            min_low = min(f['l'] for f in future)
            final_close = future[-1]['c']
            
            max_gain_pct = (max_high - entry_price) / entry_price * 100
            max_loss_pct = (min_low - entry_price) / entry_price * 100
            final_pnl = (final_close - entry_price) / entry_price * 100
            
            for tp in tp_levels:
                for sl in sl_levels:
                    tp_hit = max_gain_pct >= tp
                    sl_hit = max_loss_pct <= -sl
                    
                    if tp_hit and sl_hit:
                        tp_candle = None
                        sl_candle = None
                        for j, fc in enumerate(future):
                            if tp_candle is None and (fc['h'] - entry_price) / entry_price * 100 >= tp:
                                tp_candle = j
                            if sl_candle is None and (fc['l'] - entry_price) / entry_price * 100 <= -sl:
                                sl_candle = j
                            if tp_candle is not None and sl_candle is not None:
                                break
                        winner = tp_candle < sl_candle if (tp_candle is not None and sl_candle is not None) else False
                        outcome = 'win' if winner else 'loss'
                        realized_pnl = tp if winner else -sl
                    elif tp_hit:
                        outcome = 'win'
                        realized_pnl = tp
                    elif sl_hit:
                        outcome = 'loss'
                        realized_pnl = -sl
                    else:
                        outcome = 'draw'
                        realized_pnl = round(final_pnl, 2)
                    
                    results.append({
                        'signal': 'independent_launch',
                        'symbol': sym,
                        'ts': c['ts'],
                        'vol_ratio': round(c['v'] / avg_vol, 2),
                        'coin_range': round(coin_range, 2),
                        'btc_range': round(btc_range_pct, 2),
                        'entry': round(entry_price, 4),
                        'tp': tp,
                        'sl': sl,
                        'outcome': outcome,
                        'realized_pnl': realized_pnl,
                        'max_gain': round(max_gain_pct, 2),
                        'max_loss': round(max_loss_pct, 2),
                        'final_pnl': round(final_pnl, 2)
                    })
    
    return results

# ============================================================
# Analysis & Summary
# ============================================================
def summarize_signal(name, results):
    """Summarize backtest results for a signal type."""
    if not results:
        return {'signal': name, 'total_triggers': 0, 'error': 'No data available'}
    
    total = len(results)
    wins = sum(1 for r in results if r['outcome'] == 'win')
    losses = sum(1 for r in results if r['outcome'] == 'loss')
    draws = sum(1 for r in results if r['outcome'] == 'draw')
    
    win_pnl = [r['realized_pnl'] for r in results if r['outcome'] == 'win']
    loss_pnl = [r['realized_pnl'] for r in results if r['outcome'] == 'loss']
    all_pnl = [r['realized_pnl'] for r in results]
    
    avg_win = sum(win_pnl) / len(win_pnl) if win_pnl else 0
    avg_loss = sum(loss_pnl) / len(loss_pnl) if loss_pnl else 0
    avg_all = sum(all_pnl) / len(all_pnl) if all_pnl else 0
    
    max_win = max(win_pnl) if win_pnl else 0
    max_loss = min(loss_pnl) if loss_pnl else 0
    
    win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
    
    # Group by TP/SL combination to find optimal
    combo_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'draws': 0, 'pnl_sum': 0, 'avg_max_gain': 0, 'count': 0})
    for r in results:
        key = f"TP{r['tp']}/SL{r['sl']}"
        combo_stats[key]['wins'] += 1 if r['outcome'] == 'win' else 0
        combo_stats[key]['losses'] += 1 if r['outcome'] == 'loss' else 0
        combo_stats[key]['draws'] += 1 if r['outcome'] == 'draw' else 0
        combo_stats[key]['pnl_sum'] += r['realized_pnl']
        combo_stats[key]['avg_max_gain'] += r['max_gain']
        combo_stats[key]['count'] += 1
    
    best_combos = []
    for combo, stats in combo_stats.items():
        wr = stats['wins'] / (stats['wins'] + stats['losses']) * 100 if (stats['wins'] + stats['losses']) > 0 else 0
        avg_pnl = stats['pnl_sum'] / stats['count'] if stats['count'] > 0 else 0
        avg_mg = stats['avg_max_gain'] / stats['count'] if stats['count'] > 0 else 0
        # Calculate reward:risk (expected value per trade)
        ev = avg_pnl
        best_combos.append({
            'combo': combo,
            'win_rate': round(wr, 1),
            'avg_pnl': round(avg_pnl, 2),
            'avg_max_gain': round(avg_mg, 2),
            'triggers': stats['count'],
            'wins': stats['wins'],
            'losses': stats['losses'],
            'draws': stats['draws']
        })
    
    best_combos.sort(key=lambda x: (x['win_rate'] * 0.7 + x['avg_pnl'] * 0.3), reverse=True)
    
    # Unique triggers (per event, not per TP/SL combo)
    unique_triggers = len(set((r['symbol'], r['ts']) for r in results))
    unique_symbols = len(set(r['symbol'] for r in results))
    
    # Per-month estimate
    day_range = results[0]['ts'] if results else 0
    # Rough estimate based on data range
    
    return {
        'signal': name,
        'total_triggers_all_combos': total,
        'unique_events': unique_triggers,
        'unique_symbols': unique_symbols,
        'win_rate_all': round(win_rate, 1),
        'avg_pnl_all': round(avg_all, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'max_single_win': round(max_win, 2),
        'max_single_loss': round(max_loss, 2),
        'wins': wins,
        'losses': losses,
        'draws': draws,
        'best_combos': best_combos[:5]
    }

# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print("EXTREME EVENT SNIPER BACKTEST")
    print("=" * 60)
    
    # Load data
    print("\n[1/3] Loading 15m kline data...")
    k15 = load_15m_klines()
    print(f"  Loaded {len(k15)} symbols, {sum(len(v) for v in k15.values())} candles")
    
    print("[2/3] Loading 4h kline data...")
    k4h = load_4h_klines()
    print(f"  Loaded {len(k4h)} symbols")
    
    # Load funding data
    print("[3/3] Loading funding data...")
    funding_data = []
    if os.path.exists(FUNDING_PATH):
        with open(FUNDING_PATH) as f:
            funding_data = json.load(f)
        print(f"  Loaded {len(funding_data)} funding records from JSON")
    else:
        # Fall back to DuckDB
        rows = con.execute('SELECT symbol, funding_time, rate FROM funding_rate ORDER BY symbol, funding_time').fetchall()
        funding_data = [{'symbol': r[0], 'funding_time': r[1], 'rate': r[2]} for r in rows]
        print(f"  Loaded {len(funding_data)} funding records from DuckDB")
    
    # ========================================
    # SIGNAL 1: Panic Rebound
    # ========================================
    print("\n" + "=" * 60)
    print("SIGNAL 1: PANIC REBOUND")
    print("  15m candle drop > threshold → track 1h recovery")
    print("=" * 60)
    
    s1 = backtest_panic_rebound(k15)
    s1_summary = summarize_signal('panic_rebound', s1)
    print(f"  Unique events: {s1_summary['unique_events']}")
    print(f"  Win rate (all combos): {s1_summary['win_rate_all']}%")
    print(f"  Avg PnL (all): {s1_summary['avg_pnl_all']}%")
    print(f"  Max single win: {s1_summary['max_single_win']}%")
    print(f"  Top combos:")
    for c in s1_summary.get('best_combos', [])[:3]:
        print(f"    {c['combo']} | WR={c['win_rate']}% | avgPnL={c['avg_pnl']}% | n={c['triggers']}")
    
    # ========================================
    # SIGNAL 2: Short Squeeze
    # ========================================
    print("\n" + "=" * 60)
    print("SIGNAL 2: SHORT SQUEEZE")
    print("  funding < -0.3% x3 cycles → flips positive → track 4h")
    print("=" * 60)
    
    s2 = backtest_short_squeeze(funding_data, k4h)
    s2_summary = summarize_signal('short_squeeze', s2)
    if 'error' in s2_summary:
        print(f"  ERROR: {s2_summary['error']}")
    else:
        print(f"  Unique events: {s2_summary.get('unique_events', 0)}")
        print(f"  Win rate (all combos): {s2_summary.get('win_rate_all', 0)}%")
        print(f"  Avg PnL (all): {s2_summary.get('avg_pnl_all', 0)}%")
        print(f"  Max single win: {s2_summary.get('max_single_win', 0)}%")
        if s2_summary.get('best_combos'):
            for c in s2_summary['best_combos'][:3]:
                print(f"    {c['combo']} | WR={c['win_rate']}% | avgPnL={c['avg_pnl']}% | n={c['triggers']}")
    
    # ========================================
    # SIGNAL 3: Independent Launch
    # ========================================
    print("\n" + "=" * 60)
    print("SIGNAL 3: INDEPENDENT LAUNCH")
    print("  BTC flat ±1%, coin vol >5x avg, price range <3% → track 6h")
    print("=" * 60)
    
    s3 = backtest_independent_launch(k15)
    s3_summary = summarize_signal('independent_launch', s3)
    if 'error' in s3_summary:
        print(f"  ERROR: {s3_summary['error']}")
    else:
        print(f"  Unique events: {s3_summary.get('unique_events', 0)}")
        print(f"  Win rate (all combos): {s3_summary.get('win_rate_all', 0)}%")
        print(f"  Avg PnL (all): {s3_summary.get('avg_pnl_all', 0)}%")
        print(f"  Max single win: {s3_summary.get('max_single_win', 0)}%")
        if s3_summary.get('best_combos'):
            for c in s3_summary['best_combos'][:3]:
                print(f"    {c['combo']} | WR={c['win_rate']}% | avgPnL={c['avg_pnl']}% | n={c['triggers']}")
    
    # ========================================
    # BUILD FINAL STRATEGY
    # ========================================
    print("\n" + "=" * 60)
    print("BUILDING SNIPER STRATEGY")
    print("=" * 60)
    
    # Score each signal type
    def score_signal(s, name):
        if s.get('error') or s.get('unique_events', 0) == 0:
            return 0, name, None
        
        # Find best combo with enough triggers
        valid_combos = [c for c in s.get('best_combos', []) if c['triggers'] >= 5]
        if not valid_combos:
            valid_combos = s.get('best_combos', [])
        
        if not valid_combos:
            return 0, name, None
        
        best = valid_combos[0]
        wr = best['win_rate']
        avg_pnl = best['avg_pnl']
        triggers = s['unique_events']
        
        # Score: win_rate * avg_pnl * log(triggers) — reward quality over quantity
        import math
        score = wr * max(avg_pnl, 0.1) * math.log(triggers + 1) / 100
        
        return score, name, best
    
    scores = [
        score_signal(s1_summary, 'panic_rebound'),
        score_signal(s2_summary, 'short_squeeze'),
        score_signal(s3_summary, 'independent_launch')
    ]
    scores.sort(key=lambda x: x[0], reverse=True)
    
    strategy = {
        'name': 'Extreme Event Sniper',
        'version': '1.0',
        'generated': datetime.now().isoformat(),
        'philosophy': 'Extreme events only. 1-2 trades/day max. No daily scanning.',
        'data_period': {
            'kline_15m': '10 days (131 symbols)',
            'kline_4h': '83 days (131 symbols)',
            'funding': f'{len(funding_data)} records',
            'note': 'Limited historical data — results are indicative, backtest window narrow'
        },
        'signals': {
            '1_panic_rebound': {
                'description': '15m candle intra-candle drop > threshold% → enter at close → target 1h recovery',
                'summary': s1_summary,
                'rank': next((i+1 for i, s in enumerate(scores) if s[1] == 'panic_rebound'), 'N/A'),
                'score': round(next((s[0] for s in scores if s[1] == 'panic_rebound'), 0), 2)
            },
            '2_short_squeeze': {
                'description': 'Funding < -0.3% for 3 consecutive 8h cycles → flips positive → target 4h gain',
                'summary': s2_summary,
                'rank': next((i+1 for i, s in enumerate(scores) if s[1] == 'short_squeeze'), 'N/A'),
                'score': round(next((s[0] for s in scores if s[1] == 'short_squeeze'), 0), 2)
            },
            '3_independent_launch': {
                'description': 'BTC flat ±1% + coin volume >5x avg + price range <3% → target 6h breakout',
                'summary': s3_summary,
                'rank': next((i+1 for i, s in enumerate(scores) if s[1] == 'independent_launch'), 'N/A'),
                'score': round(next((s[0] for s in scores if s[1] == 'independent_launch'), 0), 2)
            }
        },
        'ranking': [s[1] for s in scores],
        'conclusion': ''
    }
    
    # Write conclusion
    lines = []
    for rank, (score, name, best_combo) in enumerate(scores, 1):
        if best_combo:
            lines.append(f"#{rank} {name}: WR={best_combo['win_rate']}%, avgPnL={best_combo['avg_pnl']}%, combo={best_combo['combo']}, events={best_combo['triggers']}")
        else:
            lines.append(f"#{rank} {name}: NO VALID SIGNALS")
    
    strategy['conclusion'] = '\n'.join(lines)
    print('\n' + strategy['conclusion'])
    
    # Save
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(strategy, f, indent=2, default=str)
    
    print(f"\nSaved to {OUTPUT_PATH}")
    
    # Also dump raw results for inspection
    raw_path = OUTPUT_PATH.replace('.json', '_raw.json')
    with open(raw_path, 'w') as f:
        # Save a subset of raw results (signal summaries, not every combo)
        json.dump({
            'panic_rebound_events': [
                {'symbol': r['symbol'], 'ts': r['ts'], 'drop': r['intra_drop_pct'], 
                 'drop_threshold': r['drop_threshold'], 'max_gain': r['max_gain'],
                 'combo': f"TP{r['tp']}/SL{r['sl']}", 'outcome': r['outcome'], 'pnl': r['realized_pnl']}
                for r in s1[:500]  # Limit to avoid huge file
            ],
            'short_squeeze_events': [
                {'symbol': r['symbol'], 'ts': r['ts'], 'fund_min': r.get('funding_min'),
                 'fund_next': r.get('funding_next'), 'max_gain': r['max_gain'],
                 'combo': f"TP{r['tp']}/SL{r['sl']}", 'outcome': r['outcome'], 'pnl': r['realized_pnl']}
                for r in s2
            ],
            'independent_launch_events': [
                {'symbol': r['symbol'], 'ts': r['ts'], 'vol_ratio': r.get('vol_ratio'),
                 'coin_range': r.get('coin_range'), 'max_gain': r['max_gain'],
                 'combo': f"TP{r['tp']}/SL{r['sl']}", 'outcome': r['outcome'], 'pnl': r['realized_pnl']}
                for r in s3[:500]
            ]
        }, f, indent=2, default=str)
    
    print(f"Raw events saved to {raw_path}")
    
    con.close()

if __name__ == '__main__':
    main()
