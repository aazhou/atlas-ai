"""补全多因子回测数据——含交易明细、最大回撤、正确日期"""
import duckdb, json, math
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
con = duckdb.connect(DB, read_only=True)

W = {'candle': 0.4, 'vol': 0.2, 'pa': 0.3, 'rsi': 0.1, 'trend': 0}
THR = 0.18
SL = -10
TP = 5
HOLD = 192

# Only include coins that passed multi-factor validation (Sharpe > 2)
VALID_COINS = ['TUSDT', 'LITUSDT', 'HMSTRUSDT', 'ENAUSDT', 'SXTUSDT', 'EVAAUSDT']
# Exclude SOXL/VIRTUAL/SNDK/SPCX (unrealistic Sharpe, no DD data)

all_results = []
for SYM in VALID_COINS:
    klines = con.execute(f"SELECT open_time/1000,open,high,low,close,volume FROM kline WHERE symbol='{SYM}' AND interval='15m' ORDER BY open_time").fetchall()
    frates = con.execute(f"SELECT funding_time,funding_rate FROM funding WHERE symbol='{SYM}' ORDER BY funding_time").fetchall()
    if len(klines) < 100 or len(frates) < 10:
        continue
    
    p5 = sorted([v for _, v in frates])[int(len(frates) * 0.05)]
    n = len(klines)
    factors = []
    fi = 0
    
    for i in range(50, n):
        o, hi, lo, c, v = klines[i][1:6]
        po, pc = klines[i-1][1], klines[i-1][4]
        t_ms = int(klines[i][0]) * 1000
        while fi + 1 < len(frates) and frates[fi+1][0] <= t_ms:
            fi += 1
        fr = frates[fi][1]
        if fr >= p5:
            continue
        
        body = abs(c-o); wl = min(o,c)-lo; wh = hi-max(o,c); tot = max(hi-lo, 1e-8)
        hammer = 1 if wl > body*1.5 and wl > wh*1.5 else 0
        engulf = 1 if pc < po and c > o and o < po and c > pc else 0
        doji = 1 if body/tot < 0.3 and lo <= min(klines[j][3] for j in range(i-10, i)) else 0
        candle = round((hammer + engulf + doji) / 3, 2)
        
        avg_vol = sum(klines[j][5] for j in range(i-20, i)) / 20
        vol_score = round(min(v / avg_vol / 3, 1) if c > o else 0, 2)
        
        sma20 = sum(klines[j][4] for j in range(i-20, i)) / 20
        lo20 = min(klines[j][3] for j in range(i-20, i))
        pb = (max(klines[j][2] for j in range(i-20, i)) - c) / max(max(klines[j][2] for j in range(i-20, i)), 1e-8)
        pa_score = round(((1 if (c-lo20)/max(lo20, 1e-8) < 0.01 else 0) + 
                          (1 if c > sma20 else 0) + 
                          (1 if 0.03 < pb < 0.20 else 0)) / 3, 2)
        
        gains = sum(max(klines[j][4] - klines[j-1][4], 0) for j in range(i-13, i+1)) / 14
        losses = sum(max(klines[j-1][4] - klines[j][4], 0) for j in range(i-13, i+1)) / 14
        rsi = 100 - 100/(1 + gains/losses) if losses > 0 else 100
        
        sma50 = sum(klines[j][4] for j in range(i-50, i)) / 50 if i >= 50 else sma20
        trend_score = 1 if c > sma50 else (0.3 if c > sma20 else 0)
        
        sc = W['candle'] * candle + W['vol'] * vol_score + W['pa'] * pa_score + \
             W['rsi'] * round(max(0, (35-rsi)/20), 2) + W['trend'] * trend_score
        if sc < THR:
            continue
        
        factors.append({
            't': klines[i][0], 'o': o, 'hi': hi, 'lo': lo, 'c': c,
            'entry_time': klines[i][0], 'entry': c
        })
    
    # Simulate trades with proper detail
    trades_detail = []
    equity_curve = [100]
    peak = 100
    max_dd = 0
    
    for i, f in enumerate(factors):
        ep = f['c']
        found_exit = False
        exit_px = ep
        exit_time = f['t']
        
        for j in range(i + 1, min(i + HOLD, len(factors))):
            fut = factors[j]
            if fut['lo'] <= ep * (1 + SL / 100):
                exit_px = ep * (1 + SL / 100)
                exit_time = fut['t']
                found_exit = True
                break
            elif fut['hi'] >= ep * (1 + TP / 100):
                exit_px = ep * (1 + TP / 100)
                exit_time = fut['t']
                found_exit = True
                break
            elif j == min(i + HOLD - 1, len(factors) - 1):
                exit_px = fut['c']
                exit_time = fut['t']
                found_exit = True
        
        if not found_exit:
            continue
        
        pnl = (exit_px - ep) / ep * 100
        duration_sec = exit_time - f['entry_time']
        hours = int(duration_sec / 3600)
        mins = int((duration_sec % 3600) / 60)
        duration_str = f"{hours}h{mins}m" if hours > 0 else f"{mins}m"
        
        trades_detail.append({
            'entry_time': str(datetime.fromtimestamp(f['entry_time']))[:-3],
            'exit_time': str(datetime.fromtimestamp(exit_time))[:-3],
            'duration': duration_str,
            'entry': round(ep, 6),
            'exit': round(exit_px, 6),
            'pnl': round(pnl, 2)
        })
        
        # Track equity for max DD
        equity = equity_curve[-1] * (1 + pnl / 100)
        equity_curve.append(equity)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        if dd > max_dd:
            max_dd = dd
    
    if len(trades_detail) < 5:
        continue
    
    wins = sum(1 for t in trades_detail if t['pnl'] > 0)
    wr = wins / len(trades_detail) * 100
    pnls = [t['pnl'] for t in trades_detail]
    avg = sum(pnls) / len(pnls)
    std = math.sqrt(sum((x - avg) ** 2 for x in pnls) / len(pnls))
    sharpe = avg / max(std, 0.001) * math.sqrt(len(pnls))
    
    from datetime import datetime
    bj = lambda ts: datetime.fromtimestamp(ts).strftime('%m/%d')
    
    all_results.append({
        'symbol': SYM.replace('USDT', ''),
        'strategy': 'multifactor',
        'trades': len(trades_detail),
        'win_rate': round(wr, 1),
        'avg_pnl': round(avg, 2),
        'max_dd': round(max_dd, 1),
        'sharpe': round(sharpe, 2),
        'total_return': round(equity_curve[-1] - 100, 1),
        'date_range': f"{bj(klines[50][0])}~{bj(klines[-1][0])}",
        'trades_detail': trades_detail,
        'avg_pnl_pct': round(avg, 2),
        'max_drawdown_pct': round(max_dd, 1),
        'final_equity': round(equity_curve[-1], 1)
    })
    
    print(f"{SYM}: {len(trades_detail)}T WR={wr:.0f}% avg={avg:+.2f}% DD={max_dd:.1f}% Sh={sharpe:.2f}")

con.close()

# Merge with existing funding_extreme data
orig = json.load(open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/backtest_detailed.json'))
# Keep only funding_extreme
orig = [r for r in orig if r.get('strategy') == 'funding_extreme']
# Add new multifactor data
combined = orig + all_results
json.dump(combined, open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/backtest_detailed.json', 'w'), 
          indent=2, ensure_ascii=False, default=str)

print(f"\nTotal: {len(combined)} records")
for r in combined:
    print(f"  {r['symbol']:8s} {r['strategy']:20s} T={r['trades']} WR={r['win_rate']}% avg={r['avg_pnl']:+.2f}% DD={r['max_dd']:.1f}% Sh={r['sharpe']:.2f}")

# Auto-generate chart data for ALL coins
print("\n--- Generating chart data for all coins ---")
import subprocess, sys
subprocess.run([sys.executable, 'C:/Users/admin/aazhous-projects/atlas-ai/scripts/generate_chart_data.py'], check=False)
