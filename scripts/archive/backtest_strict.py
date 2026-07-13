"""严格回测: rolling P5 + 样本外验证"""
import duckdb, json

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
con = duckdb.connect(DB, read_only=True)

syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM funding ORDER BY symbol").fetchall()]
results = []

for sym in syms:
    # Find median time to split in-sample vs out-of-sample
    mid_t = con.execute(f"SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY funding_time) FROM funding WHERE symbol='{sym}'").fetchone()[0]
    if not mid_t: continue
    
    # P5 calculated ONLY from first half (in-sample)
    p5 = con.execute(f"SELECT PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY funding_rate) FROM funding WHERE symbol='{sym}' AND funding_time < {mid_t}").fetchone()[0]
    if not p5: continue
    
    # Trades ONLY from second half (out-of-sample)
    trades = con.execute(f"""
    WITH s AS (
        SELECT f.symbol, f.funding_time, f.funding_rate,
            (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time ORDER BY k.open_time LIMIT 1) entry,
            (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000 ORDER BY k.open_time DESC LIMIT 1) exit_px,
            (SELECT MIN(k.low) FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000) worst
        FROM funding f WHERE f.symbol='{sym}' AND f.funding_rate < {p5} AND f.funding_time >= {mid_t}
    )
    SELECT funding_time, funding_rate, entry, exit_px, worst,
        (exit_px-entry)/entry*100 as pnl, (worst-entry)/entry*100 as max_dd
    FROM s WHERE entry IS NOT NULL AND exit_px IS NOT NULL
    ORDER BY funding_time
    """).fetchall()
    
    if len(trades) < 3: continue
    
    pnls = [t[5] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    avg_pnl = sum(pnls) / len(pnls)
    
    # Max DD
    eq, peak, max_dd = 100, 100, 0
    for pnl in pnls:
        eq *= (1 + pnl/100)
        if eq > peak: peak = eq
        dd = (peak-eq)/peak*100
        if dd > max_dd: max_dd = dd
    
    mean_r = avg_pnl/100
    std_r = (sum((p/100-mean_r)**2 for p in pnls)/len(pnls))**0.5
    sharpe = mean_r/std_r*(len(pnls)**0.5) if std_r > 0 else 0
    
    from datetime import datetime
    bj = lambda ts: datetime.fromtimestamp(ts/1000).strftime('%m/%d')
    
    trade_records = [{'time': t[0], 'fr': round(t[1]*100,4), 'entry': round(t[2],6),
                      'exit': round(t[3],6), 'pnl': round(t[5],2), 'dd': round(t[6],2)} for t in trades]
    
    results.append({
        'symbol': sym, 'p5_pct': round(p5*100,4), 'trades': len(trades),
        'wins': wins, 'win_rate': round(wins/len(trades)*100,1),
        'avg_pnl': round(avg_pnl,2), 'max_dd': round(max_dd,1),
        'sharpe': round(sharpe,2), 'equity': round(eq,1),
        'date_range': f"{bj(trades[0][0])}~{bj(trades[-1][0])}",
        'trades_detail': trade_records
    })

con.close()

results.sort(key=lambda x: x['sharpe'], reverse=True)

print(f"{'Sym':10s} {'T':>4s} {'WR':>5s} {'Avg%':>7s} {'DD%':>6s} {'Sh':>6s} {'Eq':>6s} {'Date':>15s}")
print("-"*70)
for r in results:
    print(f"{r['symbol']:10s} {r['trades']:>4d} {r['win_rate']:>4.1f}% {r['avg_pnl']:>+6.2f}% {r['max_dd']:>5.1f}% {r['sharpe']:>+5.2f} {r['equity']:>5.0f} {r['date_range']:>15s}")

with open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/backtest_detailed.json','w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\nSaved {len(results)} coins (sample外验证)")
