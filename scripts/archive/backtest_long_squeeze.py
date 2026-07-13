#!/usr/bin/env python3
"""
LONG_SQUEEZE 策略回测 — 费率反转+OI下降
这是 crypto_scanner.py 中已验证高胜率的模式
目标: 在保持 WR>50% 的前提下，找到更高赔率的参数
"""

import duckdb
import json
import sys
import os
import time
from datetime import datetime
from itertools import product

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "crypto", "market.duckdb")
OUTPUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "data", "crypto", "backtest_results.json")

# ═══════════════════════════ Strategy Parameters ═══════════════════════════

INTERVALS = ['4h', '1h']

# Funding reversal thresholds
FR_EXTREME_NEG = [-0.001, -0.0015, -0.002, -0.003]    # 前一周期费率
FR_NOW_MIN = [0.0, 0.0005, 0.001]                      # 当前费率必须>=

# OI drop
OI_DROP_THRESHOLDS = [-0.10, -0.15, -0.20, -0.30]      # OI 1h 降幅

# Exit params
SL_PCTS = [-0.05, -0.08, -0.10, -0.12]
TP_PCTS = [0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
MAX_HOLD = {'4h': [12, 18, 24], '1h': [24, 48, 72]}

BTC_FILTERS = ['none', 'no_crash']
MIN_TRADES = 15


def load_and_prepare(con, interval):
    """Get funding history, OI, and klines for all symbols."""
    
    # Funding rate history per symbol
    fr_raw = con.execute("""
        SELECT symbol, funding_time, rate
        FROM funding_rate
        ORDER BY symbol, funding_time
    """).fetchall()
    
    funding = {}
    for r in fr_raw:
        sym = r[0]
        if sym not in funding:
            funding[sym] = []
        funding[sym].append({'t': r[1], 'r': r[2]})
    
    # OI 5m snapshots per symbol
    oi_raw = con.execute("""
        SELECT symbol, period, timestamp, open_interest
        FROM oi_snapshot
        ORDER BY symbol, period, timestamp
    """).fetchall()
    
    oi_data = {}
    for r in oi_raw:
        sym = r[0]
        period = r[1]
        if sym not in oi_data:
            oi_data[sym] = {}
        if period not in oi_data[sym]:
            oi_data[sym][period] = []
        oi_data[sym][period].append({'t': r[2], 'oi': r[3]})
    
    # Klines
    raw = con.execute(f"""
        SELECT symbol, open_time, open, high, low, close
        FROM kline WHERE interval = '{interval}'
        ORDER BY symbol, open_time
    """).fetchall()
    
    candles = {}
    for r in raw:
        sym = r[0]
        if sym not in candles:
            candles[sym] = []
        candles[sym].append({'t': r[1], 'o': r[2], 'h': r[3], 'l': r[4], 'c': r[5]})
    
    # BTC for crash filter
    btc = candles.get('BTCUSDT', [])
    
    return funding, oi_data, candles, btc


def get_fr_at_time(funding, symbol, target_ts, window_ms=8*3600*1000):
    """Get funding rate nearest to target_ts within window."""
    if symbol not in funding:
        return None
    rates = funding[symbol]
    best = None
    best_dist = float('inf')
    for r in rates:
        dist = abs(r['t'] - target_ts)
        if dist < window_ms and dist < best_dist:
            best = r['r']
            best_dist = dist
    return best


def get_prev_fr(funding, symbol, target_ts):
    """Get the funding rate just before target_ts."""
    if symbol not in funding:
        return None
    rates = funding[symbol]
    best = None
    for r in rates:
        if r['t'] < target_ts:
            if best is None or r['t'] > best[0]:
                best = (r['t'], r['r'])
    return best[1] if best else None


def get_oi_change(oi_data, symbol, lookback_ms=3600*1000):
    """Get OI change over lookback period. Returns (pct_change, current_oi)."""
    if symbol not in oi_data:
        return None, None
    
    periods = oi_data[symbol]
    snapshots = []
    for period, snaps in periods.items():
        snapshots.extend(snaps)
    
    if len(snapshots) < 2:
        return None, None
    
    snapshots.sort(key=lambda x: x['t'])
    latest_ts = snapshots[-1]['t']
    
    # Find snapshot closest to (latest_ts - lookback)
    target_ts = latest_ts - lookback_ms
    best = None
    best_dist = float('inf')
    for s in snapshots[:-1]:
        dist = abs(s['t'] - target_ts)
        if dist < best_dist:
            best = s
            best_dist = dist
    
    if best is None or best['oi'] == 0:
        return None, None
    
    chg = (snapshots[-1]['oi'] - best['oi']) / best['oi']
    return chg, snapshots[-1]['oi']


def run_test(interval):
    """Run all parameter combos."""
    
    con = duckdb.connect(DB_PATH, read_only=True)
    funding, oi_data, candles, btc_candles = load_and_prepare(con, interval)
    con.close()
    
    # Build BTC time index
    btc_ts_map = {}
    for i, c in enumerate(btc_candles):
        btc_ts_map[c['t']] = i
    
    hold_values = MAX_HOLD[interval]
    
    grid = list(product(FR_EXTREME_NEG, FR_NOW_MIN, OI_DROP_THRESHOLDS,
                        SL_PCTS, TP_PCTS, hold_values, BTC_FILTERS))
    
    all_results = []
    
    for params in grid:
        fr_ext, fr_min, oi_drop, sl_pct, tp_pct, max_hold, btc_f = params
        
        # Skip: SL tighter than reasonable
        if tp_pct <= abs(sl_pct):
            continue
        
        trades = []
        
        for sym, cds in candles.items():
            if sym == 'BTCUSDT':
                continue
            if len(cds) < 10:
                continue
            
            fr_hist = funding.get(sym, [])
            if not fr_hist:
                continue
            
            for i in range(len(cds) - 1):
                c = cds[i]
                ts = c['t']
                
                # Find funding rate at this time
                fr_now = None
                fr_prev = None
                for j, fr in enumerate(fr_hist):
                    if fr['t'] <= ts:
                        fr_now = fr['r']
                        if j > 0:
                            fr_prev = fr_hist[j-1]['r']
                    else:
                        break
                
                if fr_now is None or fr_prev is None:
                    continue
                
                # LONG_SQUEEZE trigger: prev extreme neg → now >= fr_min
                if not (fr_prev < fr_ext and fr_now >= fr_min):
                    continue
                
                # OI drop check
                oi_chg, _ = get_oi_change(oi_data, sym)
                if oi_chg is None or oi_chg > oi_drop:
                    continue
                
                # BTC crash filter
                if btc_f == 'no_crash':
                    btc_idx = btc_ts_map.get(ts)
                    if btc_idx is not None and btc_idx < len(btc_candles):
                        btc_c = btc_candles[btc_idx]
                        btc_chg = (btc_c['c'] - btc_c['o']) / btc_c['o'] if btc_c['o'] > 0 else 0
                        if btc_chg < -0.03:
                            continue
                
                # Entry: next candle open
                entry_price = cds[i+1]['o']
                sl_price = entry_price * (1 + sl_pct)
                tp_price = entry_price * (1 + tp_pct)
                
                # Forward exit
                exit_price = None
                exit_reason = None
                exit_bar = 0
                end_i = min(i + 1 + max_hold, len(cds))
                
                for j in range(i + 1, end_i):
                    bar = cds[j]
                    exit_bar = j - i
                    if bar['l'] <= sl_price:
                        exit_price = sl_price
                        exit_reason = 'SL'
                        break
                    if bar['h'] >= tp_price:
                        exit_price = tp_price
                        exit_reason = 'TP'
                        break
                
                if exit_price is None:
                    exit_price = cds[end_i - 1]['c']
                    exit_reason = 'TIME'
                
                pnl = (exit_price - entry_price) / entry_price
                trades.append({
                    'sym': sym, 'pnl': pnl, 'win': 1 if pnl > 0 else 0,
                    'reason': exit_reason, 'bars': exit_bar,
                })
        
        if len(trades) < MIN_TRADES:
            continue
        
        wins = [t for t in trades if t['win']]
        losses = [t for t in trades if not t['win']]
        avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
        avg_bars = sum(t['bars'] for t in trades) / len(trades)
        
        wr = len(wins) / len(trades) * 100
        payoff = abs(avg_win / avg_loss) if avg_loss != 0 and abs(avg_loss) > 0.0001 else 0
        
        total_win = sum(t['pnl'] for t in wins)
        total_loss = abs(sum(t['pnl'] for t in losses))
        pf = total_win / total_loss if total_loss > 0 else 0
        
        total_tp = sum(1 for t in trades if t['reason'] == 'TP')
        total_sl = sum(1 for t in trades if t['reason'] == 'SL')
        total_time = sum(1 for t in trades if t['reason'] == 'TIME')
        
        # Report all interesting results
        if wr > 40 or payoff > 1.5:
            entry = {
                'interval': interval,
                'fr_extreme': f'{fr_ext*100:.2f}%',
                'fr_now_min': f'{fr_min*100:.2f}%',
                'oi_drop': f'{oi_drop*100:+.0f}%',
                'sl_pct': f'{sl_pct*100:+.0f}%',
                'tp_pct': f'{tp_pct*100:+.0f}%',
                'max_hold': f'{max_hold * (4 if interval=="4h" else 1)}h',
                'btc_filter': btc_f,
                'trades': len(trades),
                'win_rate': round(wr, 1),
                'payoff': round(payoff, 2),
                'profit_factor': round(pf, 2),
                'avg_win': round(avg_win * 100, 2),
                'avg_loss': round(avg_loss * 100, 2),
                'avg_bars': round(avg_bars, 1),
                'tp_hits': total_tp,
                'sl_hits': total_sl,
                'time_exits': total_time,
                'total_pnl': round(sum(t['pnl'] for t in trades) * 100, 2),
            }
            all_results.append(entry)
    
    return all_results


def main():
    t0 = time.time()
    
    all_by_interval = {}
    
    for interval in INTERVALS:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"[{interval}] LONG_SQUEEZE 回测...", file=sys.stderr)
        t1 = time.time()
        results = run_test(interval)
        elapsed = time.time() - t1
        print(f"  {len(results)} 组合达标 (WR>40% or payoff>1.5) | {elapsed:.1f}s", file=sys.stderr)
        all_by_interval[interval] = results
    
    # Print results
    flat = []
    for interval, results in all_by_interval.items():
        flat.extend(results)
    
    flat.sort(key=lambda x: x['profit_factor'], reverse=True)
    
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"═══ LONG_SQUEEZE PF排序 TOP 20 ═══", file=sys.stderr)
    for i, r in enumerate(flat[:20]):
        print(f"  #{i+1} PF={r['profit_factor']:.2f} WR={r['win_rate']:.1f}% "
              f"payoff={r['payoff']:.2f} trades={r['trades']} "
              f"P&L={r['total_pnl']}% | [{r['interval']}] "
              f"fr_ext={r['fr_extreme']} fr_min={r['fr_now_min']} oi={r['oi_drop']} "
              f"SL={r['sl_pct']} TP={r['tp_pct']} hold={r['max_hold']}",
              file=sys.stderr)
    
    # Top by WR
    wr_sorted = sorted(flat, key=lambda x: (x['win_rate'], x['payoff']), reverse=True)
    print(f"\n═══ 按胜率排序 TOP 10 ═══", file=sys.stderr)
    for i, r in enumerate(wr_sorted[:10]):
        print(f"  #{i+1} WR={r['win_rate']:.1f}% payoff={r['payoff']:.2f} "
              f"PF={r['profit_factor']:.2f} trades={r['trades']} TP:{r['tp_hits']} SL:{r['sl_hits']}",
              file=sys.stderr)
    
    # Target: WR>50% + payoff>3:1
    target = [r for r in flat if r['win_rate'] >= 50 and r['payoff'] >= 3.0]
    print(f"\n═══ WR≥50% & payoff≥3.0: {len(target)} 组合 ═══", file=sys.stderr)
    for r in target[:10]:
        print(f"  PF={r['profit_factor']:.2f} WR={r['win_rate']:.1f}% payoff={r['payoff']:.2f} "
              f"trades={r['trades']} | [{r['interval']}] "
              f"SL={r['sl_pct']} TP={r['tp_pct']} fr_ext={r['fr_extreme']} oi={r['oi_drop']}",
              file=sys.stderr)
    
    # Target relaxed: WR>40% + payoff>2:0
    relaxed = [r for r in flat if r['win_rate'] >= 40 and r['payoff'] >= 2.0]
    relaxed.sort(key=lambda x: x['profit_factor'], reverse=True)
    print(f"\n═══ WR≥40% & payoff≥2.0: {len(relaxed)} 组合 ═══", file=sys.stderr)
    for r in relaxed[:10]:
        print(f"  PF={r['profit_factor']:.2f} WR={r['win_rate']:.1f}% payoff={r['payoff']:.2f} "
              f"trades={r['trades']} P&L={r['total_pnl']}% | [{r['interval']}] "
              f"SL={r['sl_pct']} TP={r['tp_pct']} fr_ext={r['fr_extreme']} oi={r['oi_drop']} "
              f"hold={r['max_hold']}",
              file=sys.stderr)
    
    # Save
    output = {
        'generated': datetime.now().isoformat(),
        'strategy': 'LONG_SQUEEZE',
        'by_interval': {
            interval: {
                'count': len(all_by_interval[interval]),
                'results': all_by_interval[interval],
            }
            for interval in INTERVALS
        },
        'top_overall': flat[:30],
        'target_wr50_payoff3': target,
        'relaxed_wr40_payoff2': relaxed,
    }
    
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    elapsed = time.time() - t0
    print(f"\n[完成] {elapsed:.0f}s | {OUTPUT}", file=sys.stderr)
    
    return len(flat)


if __name__ == '__main__':
    main()
