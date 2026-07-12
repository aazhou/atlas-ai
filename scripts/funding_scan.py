import duckdb
con = duckdb.connect('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb', read_only=True)
top30 = [r[0] for r in con.execute("SELECT symbol FROM (SELECT symbol,MAX(quote_volume)vol FROM kline WHERE interval='1d' GROUP BY symbol ORDER BY vol DESC LIMIT 30)").fetchall()]

results = []
for sym in top30:
    r = con.execute(f"SELECT PERCENTILE_CONT(0.1) WITHIN GROUP (ORDER BY funding_rate)*100, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY funding_rate)*100, PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY funding_rate)*100 FROM funding WHERE symbol='{sym}'").fetchone()
    if r[0] is None: continue
    p10, med, p90 = r
    spread = p90 - p10
    if spread > 0.005:
        r2 = con.execute(f"""
        WITH s AS (
            SELECT symbol, funding_time,
                (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time ORDER BY k.open_time LIMIT 1) entry,
                (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000 ORDER BY k.open_time DESC LIMIT 1) exit_px
            FROM funding f WHERE f.symbol='{sym}' AND f.funding_rate < {p10/100}
        )
        SELECT COUNT(*), AVG((exit_px-entry)/NULLIF(entry,0)), SUM(CASE WHEN exit_px>entry THEN 1 ELSE 0 END)
        FROM s WHERE entry IS NOT NULL AND exit_px IS NOT NULL
        """).fetchone()
        t, avg_r, wins = r2
        if t and t >= 3:
            results.append((sym, t, wins/t*100, avg_r*100 if avg_r else 0, p10, p90))

results.sort(key=lambda x: x[3], reverse=True)
print(f"{'Symbol':12s} {'Trades':>6s} {'WR%':>6s} {'Avg%':>7s} {'P10%':>7s} {'P90%':>7s}")
print("-" * 55)
for r in results[:15]:
    print(f"{r[0]:12s} {r[1]:>6d} {r[2]:>5.0f}% {r[3]:>+6.2f}% {r[4]:>+6.3f}% {r[5]:>+6.3f}%")
con.close()
