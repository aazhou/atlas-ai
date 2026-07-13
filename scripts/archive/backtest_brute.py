"""DuckDB 全面策略回测 — 暴力搜索最优参数"""
import duckdb, json, os
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
OUT = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/backtest_v5.json'

con = duckdb.connect(DB, read_only=True)

# 拿到所有 15m K线，附带上窗口统计
df = con.execute("""
CREATE TEMP TABLE k15 AS
SELECT symbol, open_time, open, high, low, close, volume,
  AVG(volume) OVER w avg_vol,
  MIN(low) OVER w min_low,
  MAX(high) OVER w max_high,
  (close - open) / NULLIF(high - low, 0.0001) body,
  (CASE WHEN close > open THEN (open - low) ELSE (close - low) END) / NULLIF(high - low, 0.0001) lower_wick,
  (CASE WHEN close < open THEN (high - open) ELSE (high - close) END) / NULLIF(high - low, 0.0001) upper_wick
FROM kline WHERE interval='15m'
WINDOW w AS (PARTITION BY symbol ORDER BY open_time ROWS BETWEEN 19 PRECEDING AND 1 PRECEDING)
""").fetchone()

# 回测参数网格
VOL_RATIOS = [3, 5, 10, 20]
PCT_FROM_LOWS = [0.03, 0.05, 0.08, 0.12]
WICK_MINS = [0, 20, 30]
SL_PCTS = [-0.03, -0.05, -0.08]
TP_PCTS = [0.08, 0.12, 0.20, 0.35]
HOLD_BARS = [4, 8, 16, 32]  # 1h, 2h, 4h, 8h

results = []
total = len(VOL_RATIOS) * len(PCT_FROM_LOWS) * len(WICK_MINS) * len(SL_PCTS) * len(TP_PCTS) * 2
print(f"Testing {len(VOL_RATIOS)}x{len(PCT_FROM_LOWS)}x{len(WICK_MINS)}x{len(SL_PCTS)}x{len(TP_PCTS)}x2 = {total} combos...")

# Build signal table once
signals = con.execute(f"""
CREATE TEMP TABLE signals AS
SELECT *, volume/avg_vol as vol_ratio, (close-min_low)/min_low as pct_low
FROM k15 WHERE volume > 0 AND avg_vol > 0
""").fetchone()

best = {'sharpe': -99}
combo_count = 0

for vol in VOL_RATIOS:
 for pct_low in PCT_FROM_LOWS:
  for wick in WICK_MINS:
   # Count signals for this combo
   count = con.execute(f"""
   SELECT COUNT(*) FROM signals
   WHERE vol_ratio > {vol} AND pct_low < {pct_low} AND lower_wick*100 >= {wick}
   """).fetchone()[0]
   
   if count < 20: continue  # skip too few signals
   
   for sl in SL_PCTS:
    for tp in TP_PCTS:
     for hold in [8, 16]:  # 2h, 4h only to keep reasonable
        combo_count += 1
        
        # Simulate trades in SQL
        trades = con.execute(f"""
        WITH entries AS (
          SELECT s.symbol, s.open_time, s.close as entry_price, s.lower_wick, s.vol_ratio,
            s.rowid as signal_id
          FROM signals s
          WHERE s.vol_ratio > {vol} AND s.pct_low < {pct_low} 
            AND s.lower_wick*100 >= {wick}
          ORDER BY s.open_time
        ),
        exits AS (
          SELECT e.*,
            (SELECT MIN(k.low) FROM k15 k WHERE k.symbol = e.symbol 
             AND k.open_time > e.open_time 
             AND k.open_time <= e.open_time + {hold}*15*60*1000) as future_low,
            (SELECT MAX(k.high) FROM k15 k WHERE k.symbol = e.symbol 
             AND k.open_time > e.open_time 
             AND k.open_time <= e.open_time + {hold}*15*60*1000) as future_high
          FROM entries e
        )
        SELECT 
          COUNT(*) as trades,
          SUM(CASE WHEN future_low IS NULL THEN 0
              WHEN future_low <= entry_price * (1 + {sl}) THEN 1 ELSE 0 END) as stops,
          SUM(CASE WHEN future_low IS NULL OR future_high IS NULL THEN 0
              WHEN future_high >= entry_price * (1 + {tp}) 
               AND (future_low IS NULL OR future_low > entry_price * (1 + {sl})) THEN 1 ELSE 0 END) as wins,
          AVG(CASE 
              WHEN future_low <= entry_price * (1 + {sl}) THEN {sl}
              WHEN future_low IS NULL OR future_high IS NULL THEN 0
              WHEN future_high >= entry_price * (1 + {tp}) THEN {tp}
              ELSE 0 END) as avg_pnl
        FROM exits
        """).fetchone()
        
        t, sl_n, win_n, avg_p = trades
        if t < 10: continue
        
        wr = win_n / t if t > 0 else 0
        # Simple Sharpe approximation
        returns = [sl] * sl_n + [tp] * win_n + [0] * (t - sl_n - win_n)
        mean_r = sum(returns) / t
        std_r = (sum((r - mean_r)**2 for r in returns) / t) ** 0.5
        sharpe = mean_r / std_r if std_r > 0 else 0
        
        if sharpe > best['sharpe']:
            best = {
                'vol': vol, 'pct_low': pct_low, 'wick': wick,
                'sl': sl, 'tp': tp, 'hold': hold,
                'trades': t, 'win_rate': wr, 'avg_pnl': avg_p,
                'sharpe': sharpe
            }
            print(f"  NEW BEST: wr={wr:.1%} sharpe={sharpe:.2f} avg={avg_p*100:+.2f}% trades={t} vol>{vol}x low<{pct_low*100:.0f}% wick>{wick}% sl={sl*100:.0f}% tp={tp*100:.0f}% hold={hold}bars")

con.close()

print(f"\n=== BEST STRATEGY ===")
for k, v in best.items():
    print(f"  {k}: {v}")

with open(OUT, 'w') as f:
    json.dump(best, f, indent=2, default=str)
print(f"\nSaved to {OUT}")
