import duckdb, json
con = duckdb.connect('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb', read_only=True)

# Get all 50 coins with funding data
syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM funding ORDER BY symbol").fetchall()]
print(f"{len(syms)} coins with funding data\n")

results = []
for sym in syms:
    # Get funding percentile thresholds
    r = con.execute(f"SELECT PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY funding_rate)*100, PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY funding_rate)*100, PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY funding_rate)*100 FROM funding WHERE symbol='{sym}'").fetchone()
    if not r[0]: continue
    p5, med, p95 = r
    
    # LONG: funding < P5 → buy, hold 24h
    r2 = con.execute(f"""
    WITH s AS (
        SELECT f.symbol, f.funding_time,
            (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time ORDER BY k.open_time LIMIT 1) entry,
            (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000 ORDER BY k.open_time DESC LIMIT 1) exit_px
        FROM funding f WHERE f.symbol='{sym}' AND f.funding_rate < {p5/100}
    )
    SELECT COUNT(*), AVG((exit_px-entry)/NULLIF(entry,0)), SUM(CASE WHEN exit_px>entry THEN 1 ELSE 0 END)
    FROM s WHERE entry IS NOT NULL AND exit_px IS NOT NULL
    """).fetchone()
    t, avg_r, wins = r2
    
    # SHORT: funding > P95 → sell, hold 24h
    r3 = con.execute(f"""
    WITH s AS (
        SELECT f.symbol, f.funding_time,
            (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time ORDER BY k.open_time LIMIT 1) entry,
            (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000 ORDER BY k.open_time DESC LIMIT 1) exit_px
        FROM funding f WHERE f.symbol='{sym}' AND f.funding_rate > {p95/100}
    )
    SELECT COUNT(*), AVG((entry-exit_px)/NULLIF(entry,0)), SUM(CASE WHEN exit_px<entry THEN 1 ELSE 0 END)
    FROM s WHERE entry IS NOT NULL AND exit_px IS NOT NULL
    """).fetchone()
    t2, avg_r2, wins2 = r3
    
    total = (t or 0) + (t2 or 0)
    if total >= 3:
        results.append((sym, t or 0, wins or 0, avg_r or 0, t2 or 0, wins2 or 0, avg_r2 or 0, p5, p95))

# Sort by total return (long + short)
results.sort(key=lambda x: (x[3]*(x[1]) + x[6]*(x[4]))/max(x[1]+x[4],1), reverse=True)
print(f"{'Symbol':12s} {'LONG':>15s} {'SHORT':>15s} {'Funding%':>20s}")
print(f"{'':12s} {'T':>4s} {'WR':>5s} {'Avg':>7s} {'T':>4s} {'WR':>5s} {'Avg':>7s} {'P5':>7s} {'P95':>7s}")
print("-"*80)
for r in results[:20]:
    print(f"{r[0]:12s} {r[1]:>4d} {r[2]/max(r[1],1)*100:>4.0f}% {r[3]*100:>+6.2f}% {r[4]:>4d} {r[5]/max(r[4],1)*100:>4.0f}% {r[6]*100:>+6.2f}% {r[7]:>+6.3f}% {r[8]:>+6.3f}%")

con.close()
