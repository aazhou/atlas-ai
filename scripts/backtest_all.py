"""全策略暴力回测 — 找到最优解"""
import duckdb, json, sys
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
OUT = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/backtest_final.json'

con = duckdb.connect(DB, read_only=True)

# 时间框架: 1h, 4h, 1d (不要5m/15m噪音)
# 币种: 先全量，最后看哪些好

STRATEGIES = {
    'ema_trend': '''
        -- EMA趋势跟随: 价格>EMA21 且 EMA21>EMA50 且 当前bar收阳
        s.close > s.ema21 AND s.ema21 > s.ema50 AND s.close > s.open
    ''',
    'breakout_high': '''
        -- 突破高点: 价格突破过去20bar最高
        s.close > s.high_20 AND s.volume > s.avg_vol * 1.5
    ''',
    'oversold_bounce': '''
        -- 超跌反弹: RSI<35 且 收阳 且 成交量放大
        s.rsi < 35 AND s.close > s.open AND s.volume > s.avg_vol
    ''',
    'bb_squeeze': '''
        -- 布林带挤压: 价格在EMA21附近窄幅 + 量缩 + 然后放量突破
        ABS(s.close - s.ema21)/s.ema21 < 0.02 AND s.close > s.ema21
        AND s.volume < s.avg_vol * 0.7
    ''',
    'adx_trend': '''
        -- ADX趋势确认: ADX>25 + close>ema21
        s.adx > 25 AND s.close > s.ema21
    ''',
    'vol_breakout': '''
        -- 量价齐升: 量>2x均量 + 收阳 + 涨幅>1%
        s.volume > s.avg_vol * 2 AND s.close > s.open
        AND (s.close - s.open)/s.open > 0.01
    ''',
    'continuous_momentum': '''
        -- 连续动量: 过去3bar都是阳线
        s.past3_up = 3 AND s.close > s.ema21
    ''',
}

SL_PCTS = [-0.05, -0.08, -0.10]
TP_PCTS = [0.10, 0.15, 0.20, 0.30]
HOLD_HOURS = [4, 8, 24]

def build_features(interval):
    con.execute(f"DROP TABLE IF EXISTS feats_{interval}")
    con.execute(f"""
    CREATE TEMP TABLE feats_{interval} AS
    WITH r1 AS (
        SELECT symbol, open_time, open, high, low, close, volume,
            LAG(close) OVER (PARTITION BY symbol ORDER BY open_time) prev_close,
            AVG(volume) OVER (PARTITION BY symbol ORDER BY open_time ROWS BETWEEN 19 PRECEDING AND 1 PRECEDING) avg_vol,
            AVG(close) OVER (PARTITION BY symbol ORDER BY open_time ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) ema21,
            AVG(close) OVER (PARTITION BY symbol ORDER BY open_time ROWS BETWEEN 49 PRECEDING AND 1 PRECEDING) ema50,
            MAX(high) OVER (PARTITION BY symbol ORDER BY open_time ROWS BETWEEN 19 PRECEDING AND 1 PRECEDING) high_20,
            MIN(low) OVER (PARTITION BY symbol ORDER BY open_time ROWS BETWEEN 19 PRECEDING AND 1 PRECEDING) low_20
        FROM kline WHERE interval = '{interval}'
    ),
    r2 AS (
        SELECT *, CASE WHEN close > prev_close THEN 1 ELSE 0 END as up
        FROM r1
    ),
    r3 AS (
        SELECT *,
            SUM(up) OVER (PARTITION BY symbol ORDER BY open_time ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) past3_up,
            AVG(CASE WHEN close > open THEN close - open ELSE 0 END) OVER (PARTITION BY symbol ORDER BY open_time ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) avg_gain,
            AVG(CASE WHEN close < open THEN open - close ELSE 0 END) OVER (PARTITION BY symbol ORDER BY open_time ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) avg_loss
        FROM r2
    )
    SELECT *,
        CASE WHEN avg_loss > 0 THEN 100 - 100/(1 + avg_gain/NULLIF(avg_loss,0)/14) ELSE 50 END as rsi,
        14 + (avg_gain * 13 + GREATEST(close-open,0))/14 / NULLIF((avg_loss*13 + GREATEST(open-close,0))/14, 0.0001) * 14 as adx
    FROM r3
    """)

best = {'sharpe': -99, 'strategy': None, 'interval': None}

for interval in ['1h', '4h', '1d']:
    print(f"\n{'='*50}\n  TIMEFRAME: {interval}\n{'='*50}")
    build_features(interval)
    
    for sname, cond in STRATEGIES.items():
        base_count = con.execute(f"SELECT COUNT(*) FROM feats_{interval} s WHERE {cond}").fetchone()[0]
        if base_count < 30: continue  # 信号太少skip
        
        for sl in SL_PCTS:
            for tp in TP_PCTS:
                for hold_h in HOLD_HOURS:
                    hold_ms = hold_h * 3600 * 1000
                    
                    r = con.execute(f"""
                    WITH entries AS (
                        SELECT s.symbol, s.open_time, s.close as entry,
                            ROW_NUMBER() OVER (ORDER BY s.open_time) as rn
                        FROM feats_{interval} s WHERE {cond}
                    ),
                    exits AS (
                        SELECT e.*,
                            (SELECT MIN(k.low) FROM feats_{interval} k WHERE k.symbol=e.symbol 
                             AND k.open_time>e.open_time AND k.open_time<=e.open_time+{hold_ms}) as fut_low,
                            (SELECT MAX(k.high) FROM feats_{interval} k WHERE k.symbol=e.symbol 
                             AND k.open_time>e.open_time AND k.open_time<=e.open_time+{hold_ms}) as fut_high
                        FROM entries e
                    )
                    SELECT COUNT(*),
                        SUM(CASE WHEN fut_low<=entry*{1+sl} THEN 1 ELSE 0 END),
                        SUM(CASE WHEN fut_high>=entry*{1+tp} AND (fut_low IS NULL OR fut_low>entry*{1+sl}) THEN 1 ELSE 0 END)
                    FROM exits
                    """).fetchone()
                    
                    t, sl_n, win_n = r
                    if t < 20: continue
                    
                    wr = win_n / t
                    mean_r = (win_n*tp + sl_n*sl) / t
                    returns = [tp]*win_n + [sl]*sl_n + [0]*(t-win_n-sl_n)
                    std_r = (sum((x-mean_r)**2 for x in returns)/t)**0.5
                    sharpe = mean_r / std_r if std_r > 0 else 0
                    
                    if sharpe > best['sharpe']:
                        best = {
                            'sharpe': sharpe, 'strategy': sname, 'interval': interval,
                            'sl': sl, 'tp': tp, 'hold_h': hold_h,
                            'trades': t, 'win_rate': wr, 'avg_pnl': mean_r,
                            'condition': cond.strip()
                        }
                        print(f"  ★ {sname:20s} wr={wr:.0%} sharpe={sharpe:.2f} avg={mean_r*100:+.1f}% t={t} sl={sl*100:.0f}% tp={tp*100:.0f}% hold={hold_h}h")

con.close()

print(f"\n{'='*50}")
print(f"  BEST OVERALL")
print(f"{'='*50}")
for k,v in best.items():
    print(f"  {k}: {v}")

with open(OUT, 'w') as f:
    json.dump({k: str(v) if isinstance(v, float) else v for k,v in best.items()}, f, indent=2)
print(f"\nSaved to {OUT}")
