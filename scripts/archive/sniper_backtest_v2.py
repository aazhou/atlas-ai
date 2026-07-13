"""
Tightened Sniper Backtest v2
- Signal 1: Panic Rebound — stricter hammer + multi-candle variant
- Signal 2: Short Squeeze — DEAD (0 events in 60d), skip
- Signal 3: Independent Launch — vol >10x, range <1.5%, exclude top 20 coins
- Signal 4: Volume Climax — extreme vol spike + price reversal at local low
"""
import json, os, sys, time
from datetime import datetime
from collections import defaultdict
import duckdb

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                       'data', 'crypto', 'market.duckdb')
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                           'data', 'crypto', 'sniper_strategy.json')

con = duckdb.connect(DB_PATH, read_only=True)

def load_15m_klines():
    rows = con.execute('''
        SELECT symbol, open_time, open, high, low, close, volume, quote_volume
        FROM kline WHERE interval='15m'
        ORDER BY symbol, open_time
    ''').fetchall()
    data = defaultdict(list)
    for r in rows:
        data[r[0]].append({
            'ts': r[1], 'o': float(r[2]), 'h': float(r[3]),
            'l': float(r[4]), 'c': float(r[5]), 'v': float(r[6]), 'qv': float(r[7])
        })
    for sym in data:
        data[sym].sort(key=lambda x: x['ts'])
    return data

def get_top20_symbols(k15):
    """Get top 20 by average volume"""
    vols = []
    for sym, candles in k15.items():
        avg_vol = sum(c['qv'] for c in candles[-100:]) / max(len(candles[-100:]), 1)
        vols.append((sym, avg_vol))
    vols.sort(key=lambda x: x[1], reverse=True)
    top20 = set(v[0] for v in vols[:20])
    print(f"  Excluding top 20: {', '.join(sorted(top20)[:8])}...")
    return top20

# ============================================================
# SIGNAL 1: Panic Rebound v2
# Stricter: intra-candle drop >12%, close >50% of range (strong hammer),
# OR multi-candle: 3 red candles cumulatively >10% + last candle is hammer
# ============================================================
def backtest_panic_rebound_v2(k15, tp_levels=[15, 20, 25], sl_levels=[5, 7, 8]):
    results = []
    
    for sym, candles in k15.items():
        for i in range(5, len(candles) - 4):
            c = candles[i]
            if c['o'] <= 0:
                continue
            
            # Variant A: Single candle panic + strong hammer
            intra_drop = (c['l'] - c['o']) / c['o'] * 100
            candle_range = c['h'] - c['l']
            if candle_range > 0:
                close_pos = (c['c'] - c['l']) / candle_range
            else:
                close_pos = 0.5
            
            is_hammer_a = intra_drop <= -12 and close_pos >= 0.50 and -50 < intra_drop
            
            # Variant B: Multi-candle cumulative drop + last is hammer
            if i >= 3:
                prev3 = candles[i-3:i+1]
                cumulative_drop = (prev3[-1]['l'] - prev3[0]['o']) / prev3[0]['o'] * 100
                is_hammer_b = cumulative_drop <= -10 and close_pos >= 0.45 and -40 < cumulative_drop
            else:
                is_hammer_b = False
            
            variant = None
            entry_price = c['c']
            
            if is_hammer_a:
                variant = 'single'
            elif is_hammer_b and not is_hammer_a:
                variant = 'multi'
            else:
                continue
            
            # Track next 4 candles (1h)
            future = candles[i+1:i+5]
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
                        tp_candle = sl_candle = None
                        for j, fc in enumerate(future):
                            if tp_candle is None and (fc['h'] - entry_price) / entry_price * 100 >= tp:
                                tp_candle = j
                            if sl_candle is None and (fc['l'] - entry_price) / entry_price * 100 <= -sl:
                                sl_candle = j
                        winner = tp_candle < sl_candle if (tp_candle is not None and sl_candle is not None) else False
                        outcome = 'win' if winner else 'loss'
                        realized_pnl = tp if winner else -sl
                    elif tp_hit:
                        outcome = 'win'; realized_pnl = tp
                    elif sl_hit:
                        outcome = 'loss'; realized_pnl = -sl
                    else:
                        outcome = 'draw'; realized_pnl = round(final_pnl, 2)
                    
                    results.append({
                        'signal': 'panic_rebound',
                        'variant': variant,
                        'symbol': sym, 'ts': c['ts'],
                        'intra_drop_pct': round(intra_drop, 2),
                        'close_pos': round(close_pos, 2),
                        'entry': round(entry_price, 4),
                        'tp': tp, 'sl': sl,
                        'outcome': outcome, 'realized_pnl': realized_pnl,
                        'max_gain': round(max_gain_pct, 2),
                        'max_loss': round(max_loss_pct, 2),
                        'final_pnl': round(final_pnl, 2)
                    })
    
    return results

# ============================================================
# SIGNAL 3: Independent Launch v2 — TIGHTENED
# BTC ±1%, vol >10x avg, price range <1.5%, exclude top 20 coins
# ============================================================
def backtest_independent_launch_v2(k15, top20, vol_mult=10, price_range_max=1.5, 
                                    tp_levels=[15, 20, 25, 30], sl_levels=[5, 7, 8]):
    if 'BTCUSDT' not in k15:
        return []
    
    btc_candles = k15['BTCUSDT']
    results = []
    
    for sym, candles in k15.items():
        if sym == 'BTCUSDT' or sym in top20 or len(candles) < 50:
            continue
        
        for i in range(20, len(candles) - 24):
            c = candles[i]
            
            # Find BTC alignment
            btc_c = btc_idx = None
            for j, bc in enumerate(btc_candles):
                if abs(bc['ts'] - c['ts']) <= 900000:
                    btc_c = bc; btc_idx = j; break
            if btc_c is None or btc_idx < 4:
                continue
            
            # BTC flat check
            btc_past = btc_candles[btc_idx-3:btc_idx+1]
            btc_high = max(bc['h'] for bc in btc_past)
            btc_low = min(bc['l'] for bc in btc_past)
            btc_range_pct = (btc_high - btc_low) / btc_past[0]['o'] * 100
            if btc_range_pct > 1.0:
                continue
            
            # Volume check
            past_vol = [candles[k]['v'] for k in range(i-20, i) if candles[k]['v'] > 0]
            if len(past_vol) < 15:
                continue
            avg_vol = sum(past_vol) / len(past_vol)
            if c['v'] < avg_vol * vol_mult:
                continue
            
            # Price tightness
            coin_range = (c['h'] - c['l']) / c['o'] * 100
            if coin_range > price_range_max:
                continue
            
            entry_price = c['c']
            if entry_price <= 0:
                continue
            
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
                        tp_candle = sl_candle = None
                        for j, fc in enumerate(future):
                            if tp_candle is None and (fc['h'] - entry_price) / entry_price * 100 >= tp:
                                tp_candle = j
                            if sl_candle is None and (fc['l'] - entry_price) / entry_price * 100 <= -sl:
                                sl_candle = j
                        winner = tp_candle < sl_candle if (tp_candle is not None and sl_candle is not None) else False
                        outcome = 'win' if winner else 'loss'
                        realized_pnl = tp if winner else -sl
                    elif tp_hit:
                        outcome = 'win'; realized_pnl = tp
                    elif sl_hit:
                        outcome = 'loss'; realized_pnl = -sl
                    else:
                        outcome = 'draw'; realized_pnl = round(final_pnl, 2)
                    
                    results.append({
                        'signal': 'independent_launch',
                        'symbol': sym, 'ts': c['ts'],
                        'vol_ratio': round(c['v'] / avg_vol, 1),
                        'coin_range': round(coin_range, 2),
                        'btc_range': round(btc_range_pct, 2),
                        'entry': round(entry_price, 4),
                        'tp': tp, 'sl': sl,
                        'outcome': outcome, 'realized_pnl': realized_pnl,
                        'max_gain': round(max_gain_pct, 2),
                        'max_loss': round(max_loss_pct, 2),
                        'final_pnl': round(final_pnl, 2)
                    })
    
    return results

# ============================================================
# SIGNAL 4: Volume Climax
# Extreme vol spike (>15x avg) + price at 20-candle low (<5% from bottom) + reversal candle
# Track 4h (16 candles) recovery
# ============================================================
def backtest_volume_climax(k15, vol_mult=15, tp_levels=[15, 20, 25, 30], sl_levels=[5, 7, 8]):
    results = []
    
    for sym, candles in k15.items():
        if len(candles) < 50:
            continue
        
        for i in range(30, len(candles) - 16):
            c = candles[i]
            if c['o'] <= 0:
                continue
            
            # Volume >15x 20-bar average
            past_vol = [candles[k]['v'] for k in range(i-20, i) if candles[k]['v'] > 0]
            if len(past_vol) < 15:
                continue
            avg_vol = sum(past_vol) / len(past_vol)
            if c['v'] < avg_vol * vol_mult:
                continue
            
            # Price near 20-candle low: close within 5% of 20-candle low
            past_20_low = min(candles[k]['l'] for k in range(i-20, i))
            near_bottom = (c['c'] - past_20_low) / past_20_low * 100
            if near_bottom > 5:
                continue
            
            # Reversal: close > open (green candle) OR long lower wick
            candle_range = c['h'] - c['l']
            if candle_range > 0:
                low_wick_pct = (min(c['o'], c['c']) - c['l']) / candle_range * 100
            else:
                low_wick_pct = 0
            is_green = c['c'] > c['o']
            has_long_wick = low_wick_pct > 30
            if not (is_green or has_long_wick):
                continue
            
            entry_price = c['c']
            
            # Track 16 candles (4h)
            future = candles[i+1:i+17]
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
                        tp_candle = sl_candle = None
                        for j, fc in enumerate(future):
                            if tp_candle is None and (fc['h'] - entry_price) / entry_price * 100 >= tp:
                                tp_candle = j
                            if sl_candle is None and (fc['l'] - entry_price) / entry_price * 100 <= -sl:
                                sl_candle = j
                        winner = tp_candle < sl_candle if (tp_candle is not None and sl_candle is not None) else False
                        outcome = 'win' if winner else 'loss'
                        realized_pnl = tp if winner else -sl
                    elif tp_hit:
                        outcome = 'win'; realized_pnl = tp
                    elif sl_hit:
                        outcome = 'loss'; realized_pnl = -sl
                    else:
                        outcome = 'draw'; realized_pnl = round(final_pnl, 2)
                    
                    results.append({
                        'signal': 'volume_climax',
                        'symbol': sym, 'ts': c['ts'],
                        'vol_ratio': round(c['v'] / avg_vol, 1),
                        'near_bottom_pct': round(near_bottom, 2),
                        'low_wick_pct': round(low_wick_pct, 1),
                        'is_green': is_green,
                        'entry': round(entry_price, 4),
                        'tp': tp, 'sl': sl,
                        'outcome': outcome, 'realized_pnl': realized_pnl,
                        'max_gain': round(max_gain_pct, 2),
                        'max_loss': round(max_loss_pct, 2),
                        'final_pnl': round(final_pnl, 2)
                    })
    
    return results

# ============================================================
# Summary
# ============================================================
def summarize_signal(name, results):
    if not results:
        return {'signal': name, 'total_triggers': 0, 'error': 'No triggers found'}
    
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
    win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
    
    # Best combo
    combo_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'draws': 0, 'pnl_sum': 0, 'count': 0})
    for r in results:
        key = f"TP{r['tp']}/SL{r['sl']}"
        combo_stats[key]['wins'] += 1 if r['outcome'] == 'win' else 0
        combo_stats[key]['losses'] += 1 if r['outcome'] == 'loss' else 0
        combo_stats[key]['draws'] += 1 if r['outcome'] == 'draw' else 0
        combo_stats[key]['pnl_sum'] += r['realized_pnl']
        combo_stats[key]['count'] += 1
    
    best_combos = []
    for combo, stats in combo_stats.items():
        wr = stats['wins'] / (stats['wins'] + stats['losses']) * 100 if (stats['wins'] + stats['losses']) > 0 else 0
        avg_pnl = stats['pnl_sum'] / stats['count'] if stats['count'] > 0 else 0
        # Score: the combo itself (not all combos mixed)
        if stats['count'] >= 3:  # Only consider combos with meaningful sample
            best_combos.append({
                'combo': combo, 'win_rate': round(wr, 1), 'avg_pnl': round(avg_pnl, 2),
                'triggers': stats['count'], 'wins': stats['wins'], 'losses': stats['losses'],
                'draws': stats['draws'],
                'odds_ratio': round(avg_pnl / abs(avg_pnl) if avg_pnl != 0 else 0, 2) if avg_pnl > 0 else 0
            })
    
    best_combos.sort(key=lambda x: x['win_rate'] * 0.6 + x['avg_pnl'] * 0.4, reverse=True)
    
    unique_events = len(set((r['symbol'], r['ts']) for r in results))
    
    return {
        'signal': name,
        'total_triggers_all_combos': total,
        'unique_events': unique_events,
        'win_rate_all': round(win_rate, 1),
        'avg_pnl_all': round(avg_all, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'max_single_win': round(max(win_pnl) if win_pnl else 0, 2),
        'wins': wins, 'losses': losses, 'draws': draws,
        'best_combos': best_combos[:5]
    }

# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print("EXTREME EVENT SNIPER BACKTEST v2")
    print("=" * 60)
    
    k15 = load_15m_klines()
    print(f"Loaded {len(k15)} symbols, {sum(len(v) for v in k15.values())} candles")
    
    top20 = get_top20_symbols(k15)
    
    # === SIGNAL 1: Panic Rebound v2 ===
    print("\n--- SIGNAL 1: Panic Rebound (hammer filter, 2 variants) ---")
    s1 = backtest_panic_rebound_v2(k15)
    s1s = summarize_signal('panic_rebound', s1)
    print(f"  Unique: {s1s['unique_events']} | WR(all): {s1s['win_rate_all']}% | avgPnL: {s1s['avg_pnl_all']}%")
    for c in s1s.get('best_combos', [])[:3]:
        print(f"    {c['combo']} | WR={c['win_rate']}% | avgPnL={c['avg_pnl']}% | n={c['triggers']}")
    
    # === SIGNAL 3: Independent Launch v2 ===
    print("\n--- SIGNAL 3: Independent Launch (vol>10x, range<1.5%, ex-top20) ---")
    s3 = backtest_independent_launch_v2(k15, top20)
    s3s = summarize_signal('independent_launch', s3)
    print(f"  Unique: {s3s['unique_events']} | WR(all): {s3s['win_rate_all']}% | avgPnL: {s3s['avg_pnl_all']}%")
    for c in s3s.get('best_combos', [])[:3]:
        print(f"    {c['combo']} | WR={c['win_rate']}% | avgPnL={c['avg_pnl']}% | n={c['triggers']}")
    
    # === SIGNAL 4: Volume Climax ===
    print("\n--- SIGNAL 4: Volume Climax (vol>15x, near 20-low, reversal candle, 4h) ---")
    s4 = backtest_volume_climax(k15)
    s4s = summarize_signal('volume_climax', s4)
    print(f"  Unique: {s4s['unique_events']} | WR(all): {s4s['win_rate_all']}% | avgPnL: {s4s['avg_pnl_all']}%")
    for c in s4s.get('best_combos', [])[:3]:
        print(f"    {c['combo']} | WR={c['win_rate']}% | avgPnL={c['avg_pnl']}% | n={c['triggers']}")
    
    # === BUILD STRATEGY ===
    print("\n" + "=" * 60)
    print("FINAL RANKING")
    print("=" * 60)
    
    def score(s):
        if s.get('error') or s.get('unique_events', 0) == 0:
            return 0
        valid = [c for c in s.get('best_combos', []) if c['triggers'] >= 3]
        if not valid:
            return 0
        best = valid[0]
        import math
        events_per_day = s['unique_events'] / 10  # 10 days of 15m data
        # Penalize too-frequent signals (want <5/day for sniper)
        frequency_penalty = min(1.0, 5.0 / max(events_per_day, 0.1))
        return best['win_rate'] * max(best['avg_pnl'], 0.1) * frequency_penalty / 100, events_per_day
    
    signals = [
        ('panic_rebound', s1s),
        ('independent_launch', s3s),
        ('volume_climax', s4s)
    ]
    
    ranked = []
    for name, s in signals:
        sc, epd = score(s)
        ranked.append((sc, name, s, epd))
    ranked.sort(key=lambda x: x[0], reverse=True)
    
    for rank, (sc, name, s, epd) in enumerate(ranked, 1):
        best = s.get('best_combos', [{}])[0] if s.get('best_combos') else {}
        wr = best.get('win_rate', 'N/A')
        avgp = best.get('avg_pnl', 'N/A')
        combo = best.get('combo', 'N/A')
        events = s.get('unique_events', 0)
        print(f"  #{rank} {name}: WR={wr}% avgPnL={avgp}% combo={combo} events={events} (~{epd:.1f}/day)")
    
    # Build final output
    strategy = {
        'name': 'Extreme Event Sniper v2',
        'version': '2.0',
        'generated': datetime.now().isoformat(),
        'philosophy': '1-2 trades/day max. Only extreme dislocations. No daily scanning.',
        'data_period': '10 days 15m klines (131 symbols) + 60 days funding. WARNING: limited data.',
        'signals': {},
        'recommended': {},
        'disqualified': {
            'short_squeeze': '0 triggers in 60 days. funding <-0.3% x3 consecutive + flip>0 never occurred. Only valid in extreme bear markets.'
        }
    }
    
    for sc, name, s, epd in ranked:
        signal_info = {
            'rank': ranked.index((sc, name, s, epd)) + 1,
            'score': round(sc, 2),
            'events_total': s.get('unique_events', 0),
            'events_per_day': round(epd, 1),
            'summary': s,
        }
        
        # Determine if usable
        if sc > 0 and epd <= 5:
            signal_info['verdict'] = 'DEPLOYABLE — meets sniper criteria (<5 trades/day, positive EV)'
        elif sc > 0:
            signal_info['verdict'] = 'NEEDS TIGHTENING — positive EV but too frequent'
        else:
            signal_info['verdict'] = 'NOT VIABLE — negative EV or insufficient triggers'
        
        strategy['signals'][name] = signal_info
        
        if 'DEPLOYABLE' in signal_info.get('verdict', ''):
            best = s.get('best_combos', [{}])[0] if s.get('best_combos') else {}
            strategy['recommended'][name] = {
                'combo': best.get('combo'),
                'win_rate': best.get('win_rate'),
                'avg_pnl': best.get('avg_pnl'),
                'expected_monthly_triggers': round(epd * 30),
                'position_size': '5-10% of portfolio per trade (sniper sizing)',
                'rules': 'Enter at signal candle close. Set limit TP + stop SL immediately. No averaging down.'
            }
    
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(strategy, f, indent=2, default=str)
    print(f"\nSaved to {OUTPUT_PATH}")
    
    con.close()

if __name__ == '__main__':
    main()
