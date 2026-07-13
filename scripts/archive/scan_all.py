import duckdb
from datetime import datetime

con = duckdb.connect('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb', read_only=True)
syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM funding ORDER BY symbol").fetchall()]
bj = lambda ts: datetime.fromtimestamp(ts/1000).strftime('%m/%d')

results = []
for sym in syms:
    # Count trades where funding < -0.05% and calculate avg 24h return
    r = con.execute(f"""
    SELECT COUNT(*), AVG(pnl)*100 FROM (
        SELECT (e-p)/NULLIF(p,0) as pnl FROM (
            SELECT f.funding_time,
                (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time ORDER BY k.open_time LIMIT 1) p,
                (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000 ORDER BY k.open_time DESC LIMIT 1) e
            FROM funding f WHERE f.symbol='{sym}' AND f.funding_rate < -0.0005
        ) WHERE p IS NOT NULL AND e IS NOT NULL
    )
    """).fetchone()
    
    if not r[0] or r[0] < 3 or not r[1]:
        continue
    
    r2 = con.execute(f"SELECT MIN(funding_time), MAX(funding_time) FROM funding WHERE symbol='{sym}'").fetchone()
    results.append((sym, r[0], r[1], bj(r2[0]), bj(r2[1])))

results.sort(key=lambda x: x[2], reverse=True)
print(f"{'Sym':12s} {'T':>4s} {'Avg%':>7s} {'Span':>17s}")
for r in results[:20]:
    print(f"{r[0]:12s} {r[1]:>4d} {r[2]:>+6.1f}% {r[3]}~{r[4]}")

con.close()
print(f"\n{len(results)} coins with >=3 signals at funding < -0.05%")
