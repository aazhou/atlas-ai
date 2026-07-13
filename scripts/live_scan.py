import duckdb, json
from datetime import datetime

con = duckdb.connect('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb', read_only=True)

syms = con.execute("SELECT DISTINCT symbol FROM funding").fetchall()
print(f'Total symbols: {len(syms)}')

results = []
for (sym,) in syms:
    fr = con.execute(f"SELECT funding_time, funding_rate FROM funding WHERE symbol='{sym}' ORDER BY funding_time").fetchall()
    kl = con.execute(f"SELECT open_time, close FROM kline WHERE symbol='{sym}' AND interval='4h' ORDER BY open_time DESC LIMIT 50").fetchall()
    
    if len(fr) < 50 or len(kl) < 20:
        continue
    
    rates = [r for _, r in fr]
    p5 = sorted(rates)[int(len(rates) * 0.05)]
    latest_rate = fr[-1][1]
    
    closes = [c for _, c in kl]
    ma20 = sum(closes[:20]) / 20
    ma50 = sum(closes[:50]) / 50 if len(closes) >= 50 else ma20
    trend_up = ma20 > ma50
    
    if latest_rate < p5 and trend_up:
        results.append({
            'symbol': sym,
            'funding_rate': round(latest_rate * 100, 4),
            'p5': round(p5 * 100, 4),
            'price': round(closes[0], 6),
            'trend': 'UP',
            'time': datetime.now().strftime('%H:%M:%S')
        })

con.close()

results.sort(key=lambda x: x['funding_rate'])

print(f"\n=== LIVE SIGNALS ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")
print(f"Filter: funding < P5 AND 4h trend UP")
print(f"Total signals: {len(results)}\n")

for r in results:
    sl = round(r['price'] * 0.9, 6)
    tp = round(r['price'] * 1.1, 6)
    print(f"{r['symbol']:12s} | rate={r['funding_rate']:+.4f}% | P5={r['p5']:+.4f}% | price=${r['price']} | SL=${sl} | TP=${tp}")

json.dump({'time': datetime.now().isoformat(), 'signals': results}, 
    open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/live_signals.json', 'w'), indent=2, default=str)
print(f"\nSaved {len(results)} signals to live_signals.json")
