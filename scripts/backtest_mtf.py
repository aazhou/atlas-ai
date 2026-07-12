"""多时间框架回测：大周期(4h)定方向 + 费率极值入场"""
import duckdb, json
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
con = duckdb.connect(DB, read_only=True)
syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM funding ORDER BY symbol").fetchall()]
bj = lambda ts: datetime.fromtimestamp(ts/1000).strftime('%m/%d')

all_results = []

for sym in syms:
    mid_t = con.execute(f"SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY funding_time) FROM funding WHERE symbol='{sym}'").fetchone()[0]
    if not mid_t: continue
    
    p5 = con.execute(f"SELECT PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY funding_rate) FROM funding WHERE symbol='{sym}' AND funding_time < {mid_t}").fetchone()[0]
    if not p5: continue

    # With trend filter: 4h EMA21 > EMA50 at signal time
    trades = con.execute(f"""
    WITH trend AS (
        SELECT f.symbol, f.funding_time, f.funding_rate,
            (SELECT CASE WHEN AVG(k.close) FILTER (WHERE k.open_time >= f.funding_time - 84*3600*1000 AND k.open_time < f.funding_time - 42*3600*1000) >
                              AVG(k.close) FILTER (WHERE k.open_time >= f.funding_time - 210*3600*1000 AND k.open_time < f.funding_time - 42*3600*1000)
                         THEN 1 ELSE 0 END
             FROM kline k WHERE k.symbol=f.symbol AND k.interval='4h'
            ) trend_up,
            (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time ORDER BY k.open_time LIMIT 1) entry,
            (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000 ORDER BY k.open_time DESC LIMIT 1) exit_px,
            (SELECT MIN(k.low) FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000) worst,
            (SELECT MAX(k.high) FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m' AND k.open_time>f.funding_time AND k.open_time<=f.funding_time+86400000) best
        FROM funding f WHERE f.symbol='{sym}' AND f.funding_rate < {p5} AND f.funding_time >= {mid_t}
    )
    SELECT funding_time, funding_rate, entry, exit_px, worst, best,
        (exit_px-entry)/entry*100, (worst-entry)/entry*100, (best-entry)/entry*100, trend_up
    FROM trend WHERE entry IS NOT NULL AND exit_px IS NOT NULL
    ORDER BY funding_time
    """).fetchall()

    # Split: with trend vs without trend
    with_trend = [t for t in trades if t[9] == 1]
    all_t = trades

    for label, subset in [('ALL', all_t), ('TREND', with_trend)]:
        if len(subset) < 3: continue
        pnls = [t[6] for t in subset]
        wins = sum(1 for p in pnls if p > 0)
        avg_p = sum(pnls)/len(pnls)
        eq, peak, dd = 100, 100, 0
        for p in pnls:
            eq *= (1+p/100)
            if eq>peak: peak=eq
            if (peak-eq)/peak*100>dd: dd=(peak-eq)/peak*100
        mean_r=avg_p/100
        std=(sum((p/100-mean_r)**2 for p in pnls)/len(pnls))**0.5
        sh=mean_r/std*(len(pnls)**0.5) if std>0 else 0
        all_results.append({
            'symbol': sym, 'filter': label, 'trades': len(subset),
            'win_rate': round(wins/len(subset)*100,1), 'avg_pnl': round(avg_p,2),
            'max_dd': round(dd,1), 'sharpe': round(sh,2), 'equity': round(eq,1),
            'date_range': f"{bj(subset[0][0])}~{bj(subset[-1][0])}"
        })

con.close()

all_results.sort(key=lambda x: x['sharpe'], reverse=True)
trend_only = [r for r in all_results if r['filter']=='TREND']
print(f"{'Sym':10s} {'Filt':5s} {'T':>4s} {'WR%':>6s} {'Avg%':>7s} {'DD%':>6s} {'Sh':>6s} {'Eq':>6s}")
print("-"*65)
for r in all_results[:20]:
    print(f"{r['symbol']:10s} {r['filter']:5s} {r['trades']:>4d} {r['win_rate']:>5.1f}% {r['avg_pnl']:>+6.2f}% {r['max_dd']:>5.1f}% {r['sharpe']:>+5.2f} {r['equity']:>5.0f}")

with open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/backtest_detailed.json','w') as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)
print(f"\nSaved {len(all_results)} results ({len(trend_only)} with trend filter)")
