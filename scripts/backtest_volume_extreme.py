#!/usr/bin/env python3
"""
量能极值反转 v4 — 加确认过滤器 (kline-only)
策略: 放量急跌 + 反转确认 → 下一根确认柱入场

确认条件:
  A: 锤子线(下影线>2x实体) + 放量
  B: RSI<30超卖反弹
  C: 双柱确认(急跌柱后跟阳线)

三框架+全参数暴力扫描
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

INTERVALS = ['15m', '1h', '4h']

# Per-interval params
INTERVAL_CONFIG = {
    '15m': {
        'vol_mult': [3.0, 4.0, 6.0],
        'price_drop': [-0.01, -0.02],
        'sl_pct': [-0.03, -0.05, -0.08],
        'tp_pct': [0.08, 0.12, 0.16, 0.20],
        'max_hold': [12, 24],
        'rsi_period': 14,
        'rsi_threshold': 30,
    },
    '1h': {
        'vol_mult': [2.5, 3.0, 4.0],
        'price_drop': [-0.02, -0.03, -0.04],
        'sl_pct': [-0.04, -0.06, -0.10],
        'tp_pct': [0.12, 0.18, 0.25, 0.35],
        'max_hold': [12, 24],
        'rsi_period': 14,
        'rsi_threshold': 35,
    },
    '4h': {
        'vol_mult': [2.0, 2.5, 3.0, 4.0],
        'price_drop': [-0.02, -0.03, -0.05],
        'sl_pct': [-0.05, -0.08, -0.10, -0.12],
        'tp_pct': [0.15, 0.20, 0.25, 0.30, 0.40],
        'max_hold': [12, 18, 24],
        'rsi_period': 14,
        'rsi_threshold': 35,
    },
}

CONFIRMATION_MODES = [
    'none',       # No confirmation (baseline)
    'hammer',     # Hammer candle (lower wick > 2x body)
    'rsi',        # RSI oversold
    'hammer+rsi', # Both
    'two_bar',    # Signal bar + next bar green confirmation
]

MCAP_TIERS = ['all', 'top20', 'small']
MIN_TRADES = 15


def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    gains, losses = gains[-period:], losses[-period:]
    avg_g = sum(gains)/period if period > 0 else 0
    avg_l = sum(losses)/period if period > 0 else 0
    if avg_l == 0:
        return 100.0
    return 100 - 100/(1 + avg_g/avg_l)


def is_hammer(o, h, l, c):
    """Hammer: lower wick >= 2x body, small upper wick."""
    body = abs(c - o)
    if body == 0:
        return False
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    return lower_wick >= 2 * body and upper_wick <= 0.5 * body


def run_backtest(con, interval):
    config = INTERVAL_CONFIG[interval]
    
    # Load klines
    raw = con.execute(f"""
        SELECT symbol, open_time, open, high, low, close, volume
        FROM kline WHERE interval = '{interval}'
        ORDER BY symbol, open_time
    """).fetchall()
    
    candles = {}
    for r in raw:
        sym = r[0]
        if sym not in candles:
            candles[sym] = []
        candles[sym].append({'t': r[1], 'o': r[2], 'h': r[3], 'l': r[4], 'c': r[5], 'v': r[6]})
    
    # Top 20
    top20 = set(r[0] for r in con.execute(
        "SELECT symbol FROM ticker ORDER BY quote_volume DESC LIMIT 20"
    ).fetchall())
    
    grid = list(product(
        config['vol_mult'], config['price_drop'], config['sl_pct'],
        config['tp_pct'], config['max_hold'], CONFIRMATION_MODES, MCAP_TIERS
    ))
    
    all_results = []
    
    for params in grid:
        vol_mult, price_drop, sl_pct, tp_pct, max_hold, conf_mode, mcap = params
        
        if sl_pct > price_drop:  # SL must be wider
            continue
        
        trades = []
        
        for sym, cds in candles.items():
            if sym == 'BTCUSDT':
                continue
            if mcap == 'top20' and sym not in top20:
                continue
            if mcap == 'small' and sym in top20:
                continue
            if len(cds) < config['rsi_period'] + 5:
                continue
            
            # Pre-compute closes for RSI
            closes = [c['c'] for c in cds]
            
            # Pre-compute avg_vol_20
            vol_avgs = []
            for i in range(len(cds)):
                if i >= 20:
                    avg = sum(cds[j]['v'] for j in range(i-20, i)) / 20
                else:
                    avg = 0
                vol_avgs.append(avg)
            
            for i in range(22, len(cds) - 2):  # Need room for entry + exit
                c = cds[i]
                
                # Volume extreme
                if vol_avgs[i] <= 0 or c['v'] < vol_avgs[i] * vol_mult:
                    continue
                
                # Price drop
                chg = (c['c'] - c['o']) / c['o'] if c['o'] > 0 else 0
                if chg > price_drop:
                    continue
                
                # =========== Confirmation Filters ===========
                entry_offset = 1  # Default: enter next bar
                
                if conf_mode == 'hammer':
                    if not is_hammer(c['o'], c['h'], c['l'], c['c']):
                        continue
                
                elif conf_mode == 'rsi':
                    rsi = compute_rsi(closes[:i+1], config['rsi_period'])
                    if rsi is None or rsi > config['rsi_threshold']:
                        continue
                
                elif conf_mode == 'hammer+rsi':
                    if not is_hammer(c['o'], c['h'], c['l'], c['c']):
                        continue
                    rsi = compute_rsi(closes[:i+1], config['rsi_period'])
                    if rsi is None or rsi > config['rsi_threshold']:
                        continue
                
                elif conf_mode == 'two_bar':
                    # Signal bar is bearish; next bar must be bullish
                    if i + 1 >= len(cds) - 2:
                        continue
                    next_bar = cds[i+1]
                    next_chg = (next_bar['c'] - next_bar['o']) / next_bar['o'] if next_bar['o'] > 0 else 0
                    if next_chg <= 0:  # Not bullish confirmation
                        continue
                    entry_offset = 2  # Enter 2 bars after signal
                
                # Entry
                if i + entry_offset >= len(cds) - 1:
                    continue
                entry_price = cds[i + entry_offset]['o']
                sl_price = entry_price * (1 + sl_pct)
                tp_price = entry_price * (1 + tp_pct)
                
                # Forward exit
                exit_price = None
                exit_reason = None
                exit_bar = 0
                end_i = min(i + entry_offset + max_hold, len(cds))
                
                for j in range(i + entry_offset, end_i):
                    bar = cds[j]
                    exit_bar = j - i - entry_offset + 1
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
                    'pnl': pnl, 'win': 1 if pnl > 0 else 0,
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
        total_win_pnl = sum(t['pnl'] for t in wins)
        total_loss_pnl = abs(sum(t['pnl'] for t in losses))
        pf = total_win_pnl / total_loss_pnl if total_loss_pnl > 0 else 0
        
        total_tp = sum(1 for t in trades if t['reason'] == 'TP')
        total_sl = sum(1 for t in trades if t['reason'] == 'SL')
        total_time = sum(1 for t in trades if t['reason'] == 'TIME')
        
        entry_rec = {
            'interval': interval,
            'vol_mult': vol_mult,
            'price_drop': f'{price_drop*100:+.0f}%',
            'sl_pct': f'{sl_pct*100:+.0f}%',
            'tp_pct': f'{tp_pct*100:+.0f}%',
            'max_hold': max_hold,
            'confirmation': conf_mode,
            'mcap': mcap,
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
        }
        
        # Track ALL results for distribution analysis
        all_results.append(entry_rec)
        
        # Print interesting ones
        if wr > 45 or payoff > 2.0 or pf > 0.7:
            print(f"  {'★' if pf > 0.8 else '·'} PF={pf:.2f} WR={wr:.1f}% "
                  f"payoff={payoff:.2f} trades={len(trades)} "
                  f"| [{interval}] vol={vol_mult}x drop={price_drop*100:+.0f}% "
                  f"SL={sl_pct*100:+.0f}% TP={tp_pct*100:+.0f}% "
                  f"{conf_mode} {mcap} TP:{total_tp} SL:{total_sl} T:{total_time}",
                  file=sys.stderr)
    
    return all_results


def main():
    t0 = time.time()
    
    con_disk = duckdb.connect(DB_PATH, read_only=True)
    
    all_results = []
    
    for interval in INTERVALS:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"[{interval}] 回测...", file=sys.stderr)
        t1 = time.time()
        
        # Copy data to in-memory
        con = duckdb.connect(':memory:')
        con.execute(f"ATTACH '{DB_PATH}' AS src (READ_ONLY)")
        con.execute(f"CREATE TABLE kline AS SELECT * FROM src.kline WHERE interval='{interval}'")
        con.execute("CREATE TABLE ticker AS SELECT * FROM src.ticker")
        con.execute("DETACH src")
        
        results = run_backtest(con, interval)
        con.close()
        
        elapsed = time.time() - t1
        print(f"  {len(results)} 组合 | {elapsed:.1f}s", file=sys.stderr)
        all_results.extend(results)
    
    con_disk.close()
    
    # ═══ Analysis ═══
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"═══ 全量分析 ({len(all_results)} 组合) ═══", file=sys.stderr)
    
    # Top by PF
    all_results.sort(key=lambda x: x['profit_factor'], reverse=True)
    
    print(f"\n═══ PF Top 20 ═══", file=sys.stderr)
    for i, r in enumerate(all_results[:20]):
        star = '★★★' if r['profit_factor'] >= 1.0 else ('★★' if r['profit_factor'] >= 0.8 else '★' if r['profit_factor'] >= 0.6 else ' ')
        print(f"  {star} #{i+1} PF={r['profit_factor']:.2f} WR={r['win_rate']:.1f}% "
              f"payoff={r['payoff']:.2f} trades={r['trades']} "
              f"avgW={r['avg_win']} avgL={r['avg_loss']} bars={r['avg_bars']} "
              f"| [{r['interval']}] vol={r['vol_mult']}x drop={r['price_drop']} "
              f"SL={r['sl_pct']} TP={r['tp_pct']} {r['confirmation']} {r['mcap']} "
              f"TP:{r['tp_hits']} SL:{r['sl_hits']} T:{r['time_exits']}",
              file=sys.stderr)
    
    # WR > 50%
    wr50 = [r for r in all_results if r['win_rate'] >= 50]
    wr50.sort(key=lambda x: x['payoff'], reverse=True)
    print(f"\n═══ WR≥50%: {len(wr50)} 组合 (按赔率排序) ═══", file=sys.stderr)
    for i, r in enumerate(wr50[:10]):
        print(f"  #{i+1} WR={r['win_rate']:.1f}% payoff={r['payoff']:.2f} "
              f"PF={r['profit_factor']:.2f} trades={r['trades']} "
              f"| [{r['interval']}] SL={r['sl_pct']} TP={r['tp_pct']} {r['confirmation']}",
              file=sys.stderr)
    
    # PF >= 1.0 (profitable)
    profitable = [r for r in all_results if r['profit_factor'] >= 1.0]
    print(f"\n═══ PF≥1.0 (正期望): {len(profitable)} 组合 ═══", file=sys.stderr)
    for r in profitable[:10]:
        print(f"  PF={r['profit_factor']:.2f} WR={r['win_rate']:.1f}% "
              f"payoff={r['payoff']:.2f} trades={r['trades']} "
              f"| [{r['interval']}] vol={r['vol_mult']}x drop={r['price_drop']} "
              f"SL={r['sl_pct']} TP={r['tp_pct']} {r['confirmation']} {r['mcap']}",
              file=sys.stderr)
    
    # By confirmation mode
    print(f"\n═══ 按确认模式汇总 ═══", file=sys.stderr)
    for cm in CONFIRMATION_MODES:
        subset = [r for r in all_results if r['confirmation'] == cm]
        if subset:
            best = max(subset, key=lambda x: x['profit_factor'])
            avg_pf = sum(r['profit_factor'] for r in subset) / len(subset)
            print(f"  {cm:12s}: {len(subset):4d} combos  avg_PF={avg_pf:.2f}  "
                  f"best_PF={best['profit_factor']:.2f} (WR={best['win_rate']:.1f}%)",
                  file=sys.stderr)
    
    # By interval
    print(f"\n═══ 按时间框架汇总 ═══", file=sys.stderr)
    for iv in INTERVALS:
        subset = [r for r in all_results if r['interval'] == iv]
        if subset:
            best = max(subset, key=lambda x: x['profit_factor'])
            avg_pf = sum(r['profit_factor'] for r in subset) / len(subset)
            profitable_n = sum(1 for r in subset if r['profit_factor'] >= 1.0)
            print(f"  {iv:4s}: {len(subset):4d} combos  avg_PF={avg_pf:.2f}  "
                  f"best_PF={best['profit_factor']:.2f}  PF≥1.0: {profitable_n}",
                  file=sys.stderr)
    
    # Save
    output = {
        'generated': datetime.now().isoformat(),
        'strategy': 'volume_extreme_reversal_v4',
        'total_combos': len(all_results),
        'top_by_pf': all_results[:30],
        'wr50_plus': wr50[:20],
        'profitable': profitable,
        'by_confirmation': {cm: [r for r in all_results if r['confirmation'] == cm] for cm in CONFIRMATION_MODES},
    }
    
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    elapsed = time.time() - t0
    print(f"\n[完成] {elapsed:.0f}s | {OUTPUT}", file=sys.stderr)
    
    return len(all_results)


if __name__ == '__main__':
    main()
