"""修复：币种名去后缀 + 夏普用对数收益率重算 + 增加赔率/盈亏比"""
import duckdb, json, math

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
con = duckdb.connect(DB, read_only=True)
syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM funding ORDER BY symbol").fetchall()]

results = []
for sym in syms:
    mid_t = con.execute(f"SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY funding_time) FROM funding WHERE symbol='{sym}'").fetchone()[0]
    if not mid_t: continue
    p5 = con.execute(f"SELECT PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY funding_rate) FROM funding WHERE symbol='{sym}' AND funding_time < {mid_t}").fetchone()[0]
    if not p5: continue

    for label in ['ALL', 'TREND']:
        cond = f"f.funding_rate < {p5}"
        if label == 'TREND':
            cond += """ AND (SELECT AVG(close) FROM (SELECT close FROM kline WHERE symbol=f.symbol AND interval='4h' ORDER BY open_time DESC LIMIT 21)) >
                        (SELECT AVG(close) FROM (SELECT close FROM kline WHERE symbol=f.symbol AND interval='4h' ORDER BY open_time DESC LIMIT 50))"""

        trades = con.execute(f"""
        WITH s AS (
            SELECT f.symbol, f.funding_time, f.funding_rate,
                (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time ORDER BY k.open_time LIMIT 1) entry,
                (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000 ORDER BY k.open_time DESC LIMIT 1) exit_px,
                (SELECT MIN(k.low) FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000) worst
            FROM funding f WHERE f.symbol='{sym}' AND f.funding_time >= {mid_t} AND {cond}
        )
        SELECT funding_time, funding_rate, entry, exit_px, worst,
            (exit_px-entry)/entry*100 as pnl_pct, (worst-entry)/entry*100 as max_dd_pct
        FROM s WHERE entry IS NOT NULL AND exit_px IS NOT NULL ORDER BY funding_time
        """).fetchall()

        if len(trades) < 3: continue

        # Simple returns per trade
        returns = [t[5] for t in trades]  # percentage returns
        wins = sum(1 for r in returns if r > 0)
        avg_r = sum(returns)/len(returns)

        # Max drawdown on compounding equity
        eq, peak, max_dd = 100, 100, 0
        for r in returns:
            eq *= (1 + r/100)
            if eq > peak: peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd: max_dd = dd

        # Sharpe: mean(log_return) / std(log_return) * sqrt(trades)
        log_rets = [math.log(1 + r/100) for r in returns]
        mean_log = sum(log_rets)/len(log_rets)
        var_log = sum((x - mean_log)**2 for x in log_rets)/len(log_rets)
        std_log = math.sqrt(var_log)
        sharpe = mean_log / std_log * math.sqrt(len(log_rets)) if std_log > 0 else 0

        # Profit factor: sum of wins / sum of absolute losses
        total_win = sum(r for r in returns if r > 0)
        total_loss = abs(sum(r for r in returns if r < 0))
        profit_factor = total_win / total_loss if total_loss > 0 else float('inf')

        # Average win / average loss ratio
        avg_win = sum(r for r in returns if r > 0) / max(wins, 1)
        avg_loss = sum(r for r in returns if r < 0) / max(len(returns)-wins, 1)
        payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

        from datetime import datetime
        bj = lambda ts: datetime.fromtimestamp(ts/1000).strftime('%m/%d')
        dr = f"{bj(trades[0][0])}~{bj(trades[-1][0])}"

        results.append({
            'symbol': sym.replace('USDT', ''),
            'filter': label,
            'p5': round(p5*100, 4),
            'trades': len(trades),
            'wins': wins,
            'win_rate': round(wins/len(trades)*100, 1),
            'avg_pnl': round(avg_r, 2),
            'max_dd': round(max_dd, 1),
            'sharpe': round(sharpe, 2),
            'profit_factor': round(profit_factor, 2),
            'payoff_ratio': round(payoff_ratio, 2),
            'equity': round(eq, 1),
            'date_range': dr
        })

con.close()

# Sort by profit_factor descending as primary metric (sharpe misleading with small N)
results.sort(key=lambda x: (x['profit_factor'], x['sharpe']), reverse=True)

with open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/backtest_detailed.json', 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"{'Sym':10s} {'Fltr':5s} {'P5%':>7s} {'T':>4s} {'WR%':>6s} {'Avg%':>7s} {'DD%':>6s} {'PF':>6s} {'PR':>6s} {'Sh':>6s} {'Eq':>6s}")
print("-"*80)
for r in results:
    print(f"{r['symbol']:10s} {r['filter']:5s} {r['p5']:>+6.3f}% {r['trades']:>4d} {r['win_rate']:>5.1f}% {r['avg_pnl']:>+6.2f}% {r['max_dd']:>5.1f}% {r['profit_factor']:>5.2f} {r['payoff_ratio']:>5.2f} {r['sharpe']:>+5.2f} {r['equity']:>5.0f}")
