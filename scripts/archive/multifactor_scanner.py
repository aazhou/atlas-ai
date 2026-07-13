"""多因子策略扫描器 — funding + candle + volume + price action + trend"""
import duckdb, json, urllib.request, os, sys
from datetime import datetime, timezone, timedelta

DATA = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto'
DB = os.path.join(DATA, 'market.duckdb')
PORTFOLIO = os.path.join(DATA, 'portfolio.json')
SIGNALS = os.path.join(DATA, 'signals.json')

# Best params from multi-factor search: TP=5%, SL=-10%, hold=48h, thr=0.18
W = {'candle': 0.4, 'vol': 0.2, 'pa': 0.3, 'rsi': 0.1, 'trend': 0}
THR = 0.18
TP = 0.05
SL = -0.10
HOLD_BARS = 192  # 48h in 15m bars

con = duckdb.connect(DB, read_only=True)
SIGNS = []
now = datetime.now(timezone(timedelta(hours=8)))

# Load portfolio
pf = {'positions': [], 'closed': [], 'updated': now.strftime('%Y-%m-%d %H:%M:%S')}
if os.path.exists(PORTFOLIO):
    with open(PORTFOLIO) as f: pf = json.load(f)
    if 'closed' not in pf: pf['closed'] = []

existing_positions = {p['symbol'] for p in pf['positions']}

syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM funding ORDER BY symbol").fetchall()]

for sym in syms:
    if sym in existing_positions: continue
    
    # Get klines
    klines = con.execute(f"SELECT open_time/1000,open,high,low,close,volume FROM kline WHERE symbol='{sym}' AND interval='15m' ORDER BY open_time DESC LIMIT 200").fetchall()
    if len(klines) < 60: continue
    klines.reverse()
    
    # Get funding
    frates = con.execute(f"SELECT funding_time,funding_rate FROM funding WHERE symbol='{sym}' ORDER BY funding_time").fetchall()
    if len(frates) < 10: continue
    p5 = sorted([v for _, v in frates])[int(len(frates) * 0.05)]
    
    # Compute factors for last bar
    n = len(klines)
    i = n - 1  # latest bar
    o, hi, lo, c, v = klines[i][1:6]
    po, pc = klines[i-1][1], klines[i-1][4]
    
    # Funding at current time
    t_ms = int(klines[i][0]) * 1000
    fi = len(frates) - 1
    while fi > 0 and frates[fi][0] > t_ms: fi -= 1
    fr = frates[fi][1]
    
    if fr >= p5: continue  # Funding not extreme
    
    body = abs(c - o); wl = min(o, c) - lo; wh = hi - max(o, c); tot = max(hi - lo, 1e-8)
    hammer = 1 if wl > body * 1.5 and wl > wh * 1.5 else 0
    engulf = 1 if pc < po and c > o and o < po and c > pc else 0
    doji = 1 if body / tot < 0.3 and lo <= min(klines[j][3] for j in range(max(i-10,0), i)) else 0
    candle = round((hammer + engulf + doji) / 3, 2)
    
    avg_vol = sum(klines[j][5] for j in range(max(i-20,0), i)) / min(20, i)
    vol_score = round(min(v / avg_vol / 3, 1) if c > o else 0, 2)
    
    sma20 = sum(klines[j][4] for j in range(max(i-20,0), i)) / min(20, i)
    lo20 = min(klines[j][3] for j in range(max(i-20,0), i))
    pb = (max(klines[j][2] for j in range(max(i-20,0), i)) - c) / max(max(klines[j][2] for j in range(max(i-20,0), i)), 1e-8)
    pa_score = round(((1 if (c - lo20) / max(lo20, 1e-8) < 0.01 else 0) + (1 if c > sma20 else 0) + (1 if 0.03 < pb < 0.20 else 0)) / 3, 2)
    
    gains = sum(max(klines[j][4] - klines[j-1][4], 0) for j in range(max(i-13,0), i+1)) / 14
    losses = sum(max(klines[j-1][4] - klines[j][4], 0) for j in range(max(i-13,0), i+1)) / 14
    rsi = 100 - 100 / (1 + gains / losses) if losses > 0 else 100
    rsi_score = round(max(0, (35 - rsi) / 20), 2) if rsi < 35 else 0
    
    sma50 = sum(klines[j][4] for j in range(max(i-50,0), i)) / min(50, i) if i >= 50 else sma20
    trend = 1 if c > sma50 else (0.3 if c > sma20 else 0)
    
    score = W['candle'] * candle + W['vol'] * vol_score + W['pa'] * pa_score + W['rsi'] * rsi_score + W['trend'] * trend
    if score < THR: continue
    
    # Get entry price from real-time ticker
    try:
        ticker = json.loads(urllib.request.urlopen(f'https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}', timeout=5).read())
        entry_px = float(ticker['price'])
    except: continue
    
    short = sym.replace('USDT', '')
    SIGNS.append({'symbol': short, 'direction': 'LONG', 'funding_rate': round(fr*100,4), 'p5_threshold': round(p5*100,4),
                  'entry_price': round(entry_px, 6), 'trend_up': trend > 0.5,
                  'confidence': 'HIGH', 'stop_loss': round(entry_px*(1+SL), 6), 'take_profit': round(entry_px*(1+TP), 6),
                  'reason': f'多因子:形态{candle}/量{vol_score}/价{pa_score}/RSI{rsi_score}/趋势{trend}' if score > 0.25 else f'费率{fr*100:.3f}%<P5{p5*100:.3f}%',
                  'strategy': 'multifactor', 'time': now.strftime('%Y-%m-%d %H:%M:%S'),
                  'entry_time': now.strftime('%Y-%m-%d %H:%M:%S'), 'unrealized_pnl': 0, 'current_price': entry_px})

con.close()

# Update portfolio.json with new positions
tx = json.loads(urllib.request.urlopen('https://fapi.binance.com/fapi/v1/ticker/24hr').read())
pmap = {t['symbol']: float(t['lastPrice']) for t in tx}

# Update existing
for p in pf['positions']:
    try:
        sym = p['symbol'] if p['symbol'].endswith('USDT') else p['symbol'] + 'USDT'
        if sym in pmap:
            p['current_price'] = pmap[sym]
            p['unrealized_pnl'] = round((pmap[sym] / p['entry_price'] - 1) * 100, 2)
            # Check exit
            if pmap[sym] >= p['entry_price'] * (1 + TP):
                pf['closed'].append({'symbol': p['symbol'], 'entry_price': p['entry_price'], 'exit_price': pmap[sym],
                    'exit_pnl': round((pmap[sym] / p['entry_price'] - 1) * 100, 2), 'exit_reason': '止盈+10%', 'exit_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                    'strategy': p.get('strategy', 'funding_extreme'), 'direction': 'LONG'})
                p['_remove'] = True
            elif pmap[sym] <= p['entry_price'] * (1 + SL):
                pf['closed'].append({'symbol': p['symbol'], 'entry_price': p['entry_price'], 'exit_price': pmap[sym],
                    'exit_pnl': round((pmap[sym] / p['entry_price'] - 1) * 100, 2), 'exit_reason': '止损-10%', 'exit_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                    'strategy': p.get('strategy', 'funding_extreme'), 'direction': 'LONG'})
                p['_remove'] = True
    except: pass

pf['positions'] = [p for p in pf['positions'] if not p.get('_remove')]

# Add new multifactor positions
for sig in SIGNS:
    if sig['strategy'] == 'multifactor' and sig['symbol'] not in {p.get('symbol','').replace('USDT','') for p in pf['positions']}:
        pf['positions'].append({'symbol': sig['symbol'] + 'USDT', 'symbol_short': sig['symbol'],
            'entry_price': sig['entry_price'], 'current_price': sig['current_price'], 'unrealized_pnl': sig['unrealized_pnl'],
            'entry_time': sig['entry_time'], 'strategy': 'multifactor', 'funding_at_entry': sig['funding_rate'],
            'direction': 'LONG'})

pf['updated'] = now.strftime('%Y-%m-%d %H:%M:%S')
json.dump(pf, open(PORTFOLIO, 'w'), indent=2, ensure_ascii=False, default=str)

# Update signals.json (merge with existing)
sigs = {'updated': now.strftime('%Y-%m-%d %H:%M:%S'), 'strategy': 'funding_extreme + multifactor',
        'signal_count': len(SIGNS), 'signals': SIGNS, 'generated': now.strftime('%Y-%m-%d %H:%M:%S')}
json.dump(sigs, open(SIGNALS, 'w'), indent=2, ensure_ascii=False, default=str)

print(f'Multifactor scan: {len(SIGNS)} signals | Positions: {len(pf["positions"])} open | Closed: {len(pf["closed"])}')
for s in SIGNS: print(f'  {s["symbol"]:6s} score=... reason={s["reason"][:60]}')
