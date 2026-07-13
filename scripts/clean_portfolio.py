import json

pf = json.load(open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/portfolio.json'))

v11_signals = {'TUSDT', 'SXTUSDT', 'SKLUSDT', 'EVAAUSDT'}

for pos in pf['positions']:
    if pos['symbol'] in v11_signals:
        pos['strategy'] = 'V11_multifactor'
        if 'score_at_entry' not in pos:
            pos['score_at_entry'] = 0.2

# Close MU
new_positions = []
for p in pf['positions']:
    if p['symbol'] == 'MUUSDT':
        p['exit_reason'] = '策略淘汰(V11不覆盖)'
        p['exit_price'] = p['current_price']
        p['exit_pnl'] = p['unrealized_pnl']
        p['exit_time'] = '2026-07-13 06:50:00'
        pf['closed'].append(p)
    else:
        new_positions.append(p)
pf['positions'] = new_positions

closed = pf['closed']
total = len(closed)
wins = sum(1 for c in closed if c.get('exit_pnl', 0) > 0)
pf['stats'] = {
    'total_trades': total,
    'win_rate': round(wins / max(total, 1) * 100, 1),
    'total_pnl': round(sum(c.get('exit_pnl', 0) for c in closed), 2),
    'open_positions': len(pf['positions'])
}

json.dump(pf, open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/portfolio.json', 'w'), ensure_ascii=False, indent=2)
print(f'Updated: {len(pf["positions"])} open, {total} closed')
for p in pf['positions']:
    print(f'  {p["symbol"]} | {p["strategy"]} | PnL={p["unrealized_pnl"]:+.1f}%')
