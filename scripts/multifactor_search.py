"""多因子组合暴力搜索 — DuckDB SQL"""
import duckdb, json, math, itertools

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
con = duckdb.connect(DB, read_only=True)

# 候选因子
# F1: funding_rate < P5（空头拥挤）
# F2: RSI(14) < threshold（超卖）
# F3: price < BB lower band × multiplier（布林下轨）
# F4: volume > avg_vol × multiplier（放量）
# F5: OI change > threshold（大资金入场）
# F6: 4h EMA trend up（大周期方向一致）

SYM = 'TUSDT'
con.execute(f"CREATE TEMP TABLE k AS SELECT * FROM kline WHERE symbol='{SYM}' AND interval='15m' ORDER BY open_time")
con.execute(f"CREATE TEMP TABLE f AS SELECT * FROM funding WHERE symbol='{SYM}' ORDER BY funding_time")

# Compute all factors in one SQL pass
con.execute("""
DROP TABLE IF EXISTS factors;
CREATE TEMP TABLE factors AS
WITH base AS (
    SELECT open_time, open, high, low, close, volume FROM k
),
rolling AS (
    SELECT *,
        AVG(close) OVER (ORDER BY open_time ROWS 19 PRECEDING) sma20,
        AVG(close) OVER (ORDER BY open_time ROWS 49 PRECEDING) sma50,
        AVG(close) OVER (ORDER BY open_time ROWS 13 PRECEDING) sma14,
        AVG(close) OVER (ORDER BY open_time ROWS 199 PRECEDING) sma200,
        AVG(volume) OVER (ORDER BY open_time ROWS 19 PRECEDING) avg_vol,
        MIN(low) OVER (ORDER BY open_time ROWS 19 PRECEDING) low20,
        MAX(high) OVER (ORDER BY open_time ROWS 19 PRECEDING) high20
    FROM base
),
rsi_comp AS (
    SELECT *,
        close - LAG(close) OVER (ORDER BY open_time) diff
    FROM rolling WHERE sma20 IS NOT NULL
)
SELECT * FROM rsi_comp
""")

# Load into Python for fast factor computation
rows = con.execute("SELECT * FROM factors WHERE sma14 IS NOT NULL AND sma50 IS NOT NULL ORDER BY open_time").fetchall()

# Funding factor
funding_rows = con.execute("SELECT * FROM f ORDER BY funding_time").fetchall()
funding_map = {}
for fr in funding_rows:
    funding_map[fr[1]] = fr[2]  # funding_time -> rate
p5 = sorted([v for v in funding_map.values()])[int(len(funding_map)*0.05)]

best = {'sharpe': -99}
results = []

# Grid search over factor combinations
for use_fr in [True]:  # 费率必须（核心因子）
    for use_rsi in [False, True]:
        for use_bb in [False, True]:
            for use_vol in [False, True]:
                for use_trend in [False, True]:
                    active = sum([use_rsi, use_bb, use_vol, use_trend])
                    # Test different thresholds
                    for rsi_thr in [30, 35, 40]:
                        for bb_mult in [1.5, 2.0, 2.5]:
                            for vol_mult in [2, 3, 5]:
                                for sl_pct in [-5, -8, -10]:
                                    for tp_pct in [5, 8, 12, 20]:
                                        for hold_bars in [48, 96, 192]:
                                            trades = []
                                            for r in rows[50:]:  # skip warmup
                                                t, o, h, l, c, v = r[0], r[1], r[2], r[3], r[4], r[5]
                                                sma14, sma20, sma50, sma200 = r[6] if len(r)>6 else 0, r[7] if len(r)>7 else 0, r[8] if len(r)>8 else 0, r[9] if len(r)>9 else 0
                                                avg_vol, low20, high20 = r[10] if len(r)>10 else v, r[11] if len(r)>11 else l, r[12] if len(r)>12 else h
                                                
                                                # Factor checks
                                                if not sma14 or not sma20 or not sma50: continue
                                                
                                                # F1: funding (always checked)
                                                fr = funding_map.get(t, 0)
                                                if fr >= p5: continue  # must be extreme
                                                
                                                # F2: RSI
                                                if use_rsi:
                                                    # Simple RSI approximation
                                                    gain = max(c - sma14, 0)
                                                    loss = max(sma14 - c, 0)
                                                    rs = gain/max(loss, 0.0001)
                                                    rsi = 100 - 100/(1+rs)
                                                    if rsi > rsi_thr: continue
                                                
                                                # F3: BB
                                                if use_bb:
                                                    std = (sum((c_ - sma20)**2 for c_ in [c])**0.5)  # simplified
                                                    bb_low = sma20 - bb_mult * (abs(c - sma20) or 0.001)
                                                    if c > bb_low: continue
                                                
                                                # F4: volume
                                                if use_vol and v < avg_vol * vol_mult: continue
                                                
                                                # F5: trend
                                                if use_trend and sma20 < sma50: continue
                                                
                                                # Entry confirmed
                                                ep = c
                                                # Simulate exit
                                                for j in range(rows.index(r)+1, min(rows.index(r)+hold_bars, len(rows))):
                                                    fut = rows[j]
                                                    if fut[3] <= ep * (1 + sl_pct/100):
                                                        trades.append(sl_pct)
                                                        break
                                                    elif fut[4] >= ep * (1 + tp_pct/100):
                                                        trades.append(tp_pct)
                                                        break
                                                    elif j == min(rows.index(r)+hold_bars-1, len(rows)-1):
                                                        trades.append((fut[4]-ep)/ep*100)
                                            
                                            if len(trades) < 5: continue
                                            wins = sum(1 for t in trades if t > 0)
                                            wr = wins / len(trades) * 100
                                            avg = sum(trades) / len(trades)
                                            std = math.sqrt(sum((x-avg)**2 for x in trades) / len(trades))
                                            sharpe = avg / max(std, 0.001) * math.sqrt(len(trades))
                                            
                                            combo = f"FR{'+RSI' if use_rsi else ''}{'+BB' if use_bb else ''}{'+VOL' if use_vol else ''}{'+TREND' if use_trend else ''}"
                                            if sharpe > best['sharpe']:
                                                best = {'combo': combo, 'trades': len(trades), 'wr': round(wr,1), 'avg_pnl': round(avg,2), 'sharpe': round(sharpe,2), 'rsi_thr': rsi_thr, 'bb_mult': bb_mult, 'vol_mult': vol_mult, 'sl': sl_pct, 'tp': tp_pct, 'hold': hold_bars}
                                                print(f"★ {combo} Sh={sharpe:.2f} WR={wr:.0f}% T={len(trades)} avg={avg:+.1f}% SL={sl_pct}% TP={tp_pct}% hold={hold_bars}")

con.close()
print(f"\nBEST: {json.dumps(best, indent=2)}")
json.dump(best, open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/best_multifactor.json', 'w'), indent=2)
