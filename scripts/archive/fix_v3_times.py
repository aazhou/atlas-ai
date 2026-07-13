import json
from datetime import datetime

with open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/backtest_v3.json') as f:
    data = json.load(f)

for r in data:
    for t in r.get('trades_detail', []):
        if isinstance(t.get('entry_time'), (int, float)):
            t['entry_time'] = datetime.fromtimestamp(t['entry_time']).strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(t.get('exit_time'), (int, float)):
            t['exit_time'] = datetime.fromtimestamp(t['exit_time']).strftime('%Y-%m-%d %H:%M:%S')

with open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/backtest_v3.json', 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f'Fixed {len(data)} entries')
for r in data[:3]:
    print(f'  {r["symbol"]} {r["direction"]} score={r["score"]} trades_detail[0]: {r["trades_detail"][0]["entry_time"]}')
