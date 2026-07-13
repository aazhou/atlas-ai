"""费率极端位做多 — 完整回测报告"""
import duckdb, json, os

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
OUT = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/backtest_detailed.json'

con = duckdb.connect(DB, read_only=True)
syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM funding ORDER BY symbol").fetchall()]

all_results = []

for sym in syms:
    # P5 threshold for this coin
    r = con.execute(f"SELECT PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY funding_rate) FROM funding WHERE symbol='{sym}'").fetchone()
    p5 = r[0]
    if p5 is None: continue
    
    # Get ALL trades with full detail
    trades = con.execute(f"""
    WITH s AS (
        SELECT f.symbol, f.funding_time, f.funding_rate,
            (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time ORDER BY k.open_time LIMIT 1) entry,
            (SELECT MIN(k.low) FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000) worst,
            (SELECT MAX(k.high) FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000) best,
            (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000 ORDER BY k.open_time DESC LIMIT 1) exit_px
        FROM funding f WHERE f.symbol='{sym}' AND f.funding_rate < {p5}
    )
    SELECT funding_time, funding_rate, entry, worst, best, exit_px,
        (exit_px-entry)/entry*100 as pnl_pct,
        (best-entry)/entry*100 as max_gain,
        (worst-entry)/entry*100 as max_dd
    FROM s WHERE entry IS NOT NULL AND exit_px IS NOT NULL
    ORDER BY funding_time
    """).fetchall()
    
    if len(trades) < 3: continue
    
    # Calculate metrics
    pnls = [t[6] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    avg_pnl = sum(pnls) / len(pnls)
    
    # Max drawdown on equity curve
    equity = 100
    peak = 100
    max_dd = 0
    eq_curve = []
    for pnl in pnls:
        equity *= (1 + pnl/100)
        eq_curve.append(round(equity, 2))
        if equity > peak: peak = equity
        dd = (peak - equity) / peak * 100
        if dd > max_dd: max_dd = dd
    
    # Sharpe
    mean_r = avg_pnl / 100
    std_r = (sum((p/100 - mean_r)**2 for p in pnls) / len(pnls)) ** 0.5
    sharpe = mean_r / std_r * (len(pnls)**0.5) if std_r > 0 else 0
    
    trade_records = []
    for t in trades:
        trade_records.append({
            'time': t[0],
            'funding': round(t[1]*100, 4),
            'entry': round(t[2], 6),
            'exit': round(t[5], 6),
            'pnl_pct': round(t[6], 2),
            'max_gain': round(t[7], 2),
            'max_dd': round(t[8], 2)
        })
    
    all_results.append({
        'symbol': sym,
        'p5_threshold': round(p5*100, 4),
        'trades': len(trades),
        'wins': wins,
        'win_rate': round(wins/len(trades)*100, 1),
        'avg_pnl_pct': round(avg_pnl, 2),
        'max_drawdown_pct': round(max_dd, 1),
        'sharpe': round(sharpe, 2),
        'final_equity': round(equity, 1),
        'equity_curve': eq_curve,
        'trades_detail': trade_records
    })

# Sort by sharpe
all_results.sort(key=lambda x: x['sharpe'], reverse=True)

con.close()

with open(OUT, 'w') as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)

print(f"Saved {len(all_results)} coins to {OUT}")
print(f"\n{'Symbol':12s} {'Trades':>6s} {'WR%':>6s} {'Avg%':>7s} {'MaxDD%':>7s} {'Sharpe':>7s} {'Equity':>7s}")
print("-" * 60)
for r in all_results[:15]:
    print(f"{r['symbol']:12s} {r['trades']:>6d} {r['win_rate']:>5.1f}% {r['avg_pnl_pct']:>+6.2f}% {r['max_drawdown_pct']:>6.1f}% {r['sharpe']:>+6.2f} {r['final_equity']:>6.0f}")
