import duckdb, json
DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
con = duckdb.connect(DB, read_only=True)

thresholds = {'BTCUSDT': 0.003, 'ETHUSDT': 0.004}
for sym in ['BTCUSDT', 'ETHUSDT']:
    thr = thresholds[sym] / 100
    print(f"\n=== {sym} 费率极值策略 ===")
    
    max_fr = con.execute(f"SELECT MAX(funding_rate)*100 FROM funding WHERE symbol='{sym}'").fetchone()[0]
    min_fr = con.execute(f"SELECT MIN(funding_rate)*100 FROM funding WHERE symbol='{sym}'").fetchone()[0]
    print(f"Range: {min_fr:.4f}% ~ {max_fr:.4f}%")
    
    # Simple: when funding < -0.005%, go LONG. When > 0.005%, go SHORT.
    # Hold for 24h, entry at next 1h close
    
    for direction, fr_sign, entry_sign in [('LONG', '<', 1), ('SHORT', '>', -1)]:
        threshold = -thr if direction == 'LONG' else thr
        op = '<' if direction == 'LONG' else '>'
        
        r = con.execute(f"""
        WITH sig AS (
            SELECT symbol, funding_time, funding_rate,
                (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m'
                 AND k.open_time > f.funding_time ORDER BY k.open_time LIMIT 1) entry,
                (SELECT k.close FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m'
                 AND k.open_time > f.funding_time AND k.open_time <= f.funding_time + 86400000
                 ORDER BY k.open_time DESC LIMIT 1) exit_24h,
                (SELECT MAX(k.high) FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m'
                 AND k.open_time > f.funding_time AND k.open_time <= f.funding_time + 86400000) best,
                (SELECT MIN(k.low) FROM kline k WHERE k.symbol=f.symbol AND k.interval='15m'
                 AND k.open_time > f.funding_time AND k.open_time <= f.funding_time + 86400000) worst
            FROM funding f WHERE f.symbol='{sym}' AND f.funding_rate {op} {threshold}
        )
        SELECT COUNT(*),
            AVG((exit_24h - entry) / NULLIF(entry, 0) * {entry_sign}),
            AVG((best - entry) / NULLIF(entry, 0) * {entry_sign}),
            AVG((worst - entry) / NULLIF(entry, 0) * {entry_sign}),
            SUM(CASE WHEN (exit_24h - entry) * {entry_sign} > 0 THEN 1 ELSE 0 END)
        FROM sig WHERE entry IS NOT NULL AND exit_24h IS NOT NULL
        """).fetchone()
        
        t, avg_exit, avg_best, avg_worst, wins = r
        if t is None or t == 0:
            print(f"  {direction}(fr{op}{threshold*100:.3f}%): 0笔 — 无信号")
            continue
        wr = wins/t*100 if t else 0
        print(f"  {direction}(fr{op}{threshold*100:.3f}%): {t}笔 | 胜率{wr:.0f}% | 均{avg_exit*100:+.2f}% | 最佳{avg_best*100:+.2f}% | 最差{avg_worst*100:+.2f}%")

con.close()
