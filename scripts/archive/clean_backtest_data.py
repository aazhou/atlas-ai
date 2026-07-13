import json, os

CHART_DIR = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto'
# Coins with existing chart data (any interval)
chart_coins = set()
for f in os.listdir(CHART_DIR):
    if f.startswith('chart_') and f.endswith('.json'):
        # chart_T_5m.json → T
        parts = f.replace('chart_', '').replace('.json', '').split('_')
        coin = parts[0]
        chart_coins.add(coin)

print(f'Coins with charts: {sorted(chart_coins)}')

# Clean backtest_multifactor.json
mf = json.load(open(f'{CHART_DIR}/backtest_multifactor.json'))
clean = []
removed = []
for r in mf:
    sym = r['symbol']
    if sym in chart_coins:
        clean.append(r)
    else:
        removed.append(sym)

print(f'Removed (no chart): {removed}')
print(f'Kept: {len(clean)}')

json.dump(clean, open(f'{CHART_DIR}/backtest_multifactor.json', 'w'), ensure_ascii=False, indent=2)

# Also clean backtest_detailed.json
det = json.load(open(f'{CHART_DIR}/backtest_detailed.json'))
det_clean = []
for r in det:
    if r['symbol'] in chart_coins:
        det_clean.append(r)
json.dump(det_clean, open(f'{CHART_DIR}/backtest_detailed.json', 'w'), ensure_ascii=False, indent=2)
print(f'Detailed: {len(det_clean)} kept')
