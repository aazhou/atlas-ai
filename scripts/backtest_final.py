"""费率极值回测 — 只做ALL，加交易详情，过滤垃圾"""
import duckdb, json, math
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
con = duckdb.connect(DB, read_only=True)
syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM funding ORDER BY symbol").fetchall()]
bj = lambda ts: datetime.fromtimestamp(ts/1000).strftime('%m/%d %H:%M')

results = []
for sym in syms:
    mid_t = con.execute(f"SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY funding_time) FROM funding WHERE symbol='{sym}'").fetchone()[0]
    if not mid_t: continue
    p5 = con.execute(f"SELECT PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY funding_rate) FROM funding WHERE symbol='{sym}' AND funding_time < {mid_t}").fetchone()[0]
    if not p5: continue

    trades = con.execute(f"""
    WITH s AS (
        SELECT f.symbol, f.funding_time, f.funding_rate,
            (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time ORDER BY k.open_time LIMIT 1) entry,
            (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000 ORDER BY k.open_time DESC LIMIT 1) exit_px,
            (SELECT MIN(k.low) FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000) worst
        FROM funding f WHERE f.symbol='{sym}' AND f.funding_time >= {mid_t} AND f.funding_rate < {p5}
    )
    SELECT funding_time, funding_rate, entry, exit_px, worst,
        (exit_px-entry)/entry*100, (worst-entry)/entry*100
    FROM s WHERE entry IS NOT NULL AND exit_px IS NOT NULL ORDER BY funding_time
    """).fetchall()

    if len(trades) < 5: continue  # 至少5笔

    returns = [t[5] for t in trades]
    wins = sum(1 for r in returns if r > 0)
    avg_r = sum(returns)/len(returns)
    total_win = sum(r for r in returns if r > 0)
    total_loss = abs(sum(r for r in returns if r < 0))

    # Max DD
    eq, peak, max_dd = 100, 100, 0
    for r in returns:
        eq *= (1+r/100)
        if eq>peak: peak=eq
        dd=(peak-eq)/peak*100
        if dd>max_dd: max_dd=dd

    # Sharpe (log returns)
    log_rets=[math.log(1+r/100) for r in returns]
    mean_log=sum(log_rets)/len(log_rets)
    std_log=math.sqrt(sum((x-mean_log)**2 for x in log_rets)/len(log_rets))
    sharpe=mean_log/std_log*math.sqrt(len(log_rets)) if std_log>0 else 0

    # Filter junk
    if max_dd>50 or sharpe<0: continue

    trade_records=[]
    for t in trades:
        trade_records.append({
            'time': t[0], 'fr': round(t[1]*100,4),
            'entry': round(t[2],6), 'exit': round(t[3],6),
            'pnl': round(t[5],2), 'dd': round(t[6],2)
        })

    results.append({
        'symbol': sym.replace('USDT',''),
        'p5': round(p5*100,4),
        'trades': len(trades),
        'win_rate': round(wins/len(trades)*100,1),
        'avg_pnl': round(avg_r,2),
        'max_dd': round(max_dd,1),
        'sharpe': round(sharpe,2),
        'profit_factor': round(total_win/total_loss,2) if total_loss>0 else 999,
        'equity': round(eq,1),
        'date_range': f"{bj(trades[0][0])}~{bj(trades[-1][0])}",
        'trades_detail': trade_records,
        'avg_pnl_pct': round(avg_r,2),
        'max_drawdown_pct': round(max_dd,1),
        'final_equity': round(eq,1)
    })

con.close()
results.sort(key=lambda x: x['sharpe'], reverse=True)
with open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/backtest_detailed.json','w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f'Saved {len(results)} coins')
for r in results:
    print(f"  {r['symbol']:8s} T={r['trades']} WR={r['win_rate']}% avg={r['avg_pnl']:+.1f}% DD={r['max_dd']:.1f}% PF={r['profit_factor']}")
