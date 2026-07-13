import json

pf = json.load(open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/portfolio.json'))

# Fix closed trades: EVAA was a valid V11 signal, update its strategy
for c in pf['closed']:
    if c['symbol'] == 'EVAAUSDT':
        c['strategy'] = 'V11_multifactor'  # EVAA is in V11 signals
    # MU stays as funding_extreme - not in V11

json.dump(pf, open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/portfolio.json', 'w'), ensure_ascii=False, indent=2)

print("Fixed:")
for c in pf['closed']:
    print(f"  {c['symbol']} -> strategy={c['strategy']} | PnL={c.get('exit_pnl',0):+.2f}%")
print(f"Open: {len(pf['positions'])} | Closed: {len(pf['closed'])}")
