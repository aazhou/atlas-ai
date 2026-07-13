"""
针对性回测: TUSDT 557天5m数据 + 4h趋势 + 双策略
"""
import duckdb, json, math
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
con = duckdb.connect(DB, read_only=True)

sym = 'TUSDT'
kl_5m = con.execute(f"SELECT open_time/1000, open, high, low, close, volume FROM kline WHERE symbol='{sym}' AND interval='5m' ORDER BY open_time").fetchall()
kl_4h = con.execute(f"SELECT open_time/1000, close FROM kline WHERE symbol='{sym}' AND interval='4h' ORDER BY open_time").fetchall()
fr = con.execute(f"SELECT funding_time, funding_rate FROM funding WHERE symbol='{sym}' ORDER BY funding_time").fetchall()

print(f'5m: {len(kl_5m)} bars ({datetime.fromtimestamp(kl_5m[0][0])} -> {datetime.fromtimestamp(kl_5m[-1][0])})')
print(f'4h: {len(kl_4h)} bars ({datetime.fromtimestamp(kl_4h[0][0])} -> {datetime.fromtimestamp(kl_4h[-1][0])})')
print(f'Funding: {len(fr)} rows')

# 4h trend
c4 = [c for _,c in kl_4h]
trends = []
for i in range(len(kl_4h)):
    if i < 20: trends.append(True)
    else:
        ma20 = sum(c4[i-20:i])/20; ma50 = sum(c4[max(0,i-50):i])/min(50,i)
        trends.append(ma20 > ma50)

def run_strategy(name, entry_condition):
    trades = []
    pos = None
    fi = 0
    for i in range(100, len(kl_5m)):
        t = int(kl_5m[i][0])
        o,h,l,c,v = kl_5m[i][1:6]
        
        while fi+1 < len(fr) and fr[fi+1][0] <= t*1000: fi += 1
        rate = fr[fi][1] if fi < len(fr) else 0
        
        fhi = 0
        while fhi+1 < len(kl_4h) and kl_4h[fhi+1][0] <= t: fhi += 1
        trend_up = trends[fhi] if fhi < len(trends) else True
        
        if pos:
            pnl = (c / pos['ep'] - 1) * 100
            if pos['dir'] == 'SHORT': pnl = -pnl
            hours = (t - pos['et']) / 3600
            
            exit_reason = None
            if pnl <= -10: exit_reason = '止损'
            elif pnl >= (5 if 'multifactor' in name else 10): exit_reason = '止盈'
            elif hours >= 48: exit_reason = '超时'
            elif i == len(kl_5m)-1: exit_reason = '收盘'
            
            if exit_reason:
                pos['xt'] = t; pos['xp'] = c; pos['pnl'] = round(pnl, 2)
                pos['xr'] = exit_reason; pos['dur'] = f'{hours:.0f}h'
                trades.append(pos)
                pos = None
        else:
            sig = entry_condition(rate, trend_up, kl_5m, i)
            if sig:
                pos = {
                    'et': t, 'ep': c, 'dir': sig['dir'],
                    'rate': round(rate*100,4), 'strat': name
                }
                if 'score' in sig: pos['score'] = sig['score']
    
    return trades

def compute_stats(trades):
    if len(trades) < 5: return None
    rets = [t['pnl'] for t in trades]
    wins = [r for r in rets if r>0]
    wr = len(wins)/len(rets)*100
    avg = sum(rets)/len(rets)
    std = math.sqrt(sum((r-avg)**2 for r in rets)/len(rets)) if len(rets)>1 else 1
    sharpe = min((avg/max(std,0.01))*math.sqrt(len(rets)), 99.99)
    eq=0; peak=0; max_dd=0
    for r in rets:
        eq+=r
        if eq>peak: peak=eq
        dd=peak-eq
        if dd>max_dd: max_dd=dd
    gross_profit = sum(r for r in rets if r>0)
    gross_loss = abs(sum(r for r in rets if r<0))
    pf = gross_profit/max(gross_loss,0.01)
    return {'trades':len(trades),'win_rate':round(wr,1),'avg_pnl':round(avg,2),
            'total_return':round(sum(rets),2),'max_dd':round(max_dd,1),
            'sharpe':round(sharpe,2),'profit_factor':round(pf,2)}

def score(s):
    if not s: return 0
    sc = 0
    sc += min(s['sharpe']/3,1)*30
    sc += min(s['win_rate']/80,1)*20
    sc += max(0,1-s['max_dd']/40)*25
    sc += min(s['trades']/30,1)*15
    sc += min(s['profit_factor']/3,1)*10
    return round(sc, 1)

# === Strategy 1: Funding Extreme ===
rates_all = [r for _,r in fr]
t1 = run_strategy('funding_extreme', lambda rate, trend_up, kl, i: 
    {'dir': 'LONG'} if rate < -0.0005 and trend_up else (
    {'dir': 'SHORT'} if rate > 0.0005 and not trend_up else None))

# === Strategy 2: Multifactor ===
p5 = sorted(rates_all)[int(len(rates_all)*0.05)]
p95 = sorted(rates_all)[int(len(rates_all)*0.95)]

def mf_entry(rate, trend_up, kl, i):
    if i < 20: return None
    o,hi,lo,c,v = kl[i][1:6]; po,pc = kl[i-1][1],kl[i-1][4]
    body=abs(c-o); wl=min(o,c)-lo; wh=hi-max(o,c); tr=max(hi-lo,1e-8)
    cn=((1 if wl>body*1.5 and wl>wh*1.5 else 0)+(1 if pc<po and c>o and o<po and c>pc else 0))/2
    avg_vol=sum(kl[j][5] for j in range(i-20,i))/20
    vl=min(v/max(avg_vol,1e-8)/3,1) if c>o else 0
    sma20=sum(kl[j][4] for j in range(i-20,i))/20
    sma50=sum(kl[j][4] for j in range(max(0,i-50),i))/min(50,i) if i>=50 else sma20
    trend=1.0 if c>sma50 else (0.3 if c>sma20 else 0)
    lo20=min(kl[j][3] for j in range(i-20,i)); hi20=max(kl[j][2] for j in range(i-20,i))
    pb=(hi20-c)/max(hi20,1e-8)
    pa=((1 if 0.03<pb<0.20 else 0)+(1 if c>sma20 else 0))/2
    sc = 0.2*cn + 0.4*vl + 0.3*pa + 0.1*trend
    sc = round(sc,2)
    if rate < p5 and trend_up and sc >= 0.18:
        return {'dir': 'LONG', 'score': sc}
    if rate > p95 and not trend_up and sc >= 0.18:
        return {'dir': 'SHORT', 'score': sc}
    return None

t2 = run_strategy('multifactor', mf_entry)

con.close()

# Output
all_trades = []
for trades, name in [(t1, 'funding_extreme'), (t2, 'multifactor')]:
    for direction in ['LONG', 'SHORT']:
        dir_trades = [t for t in trades if t['dir'] == direction]
        if len(dir_trades) < 5: continue
        stats = compute_stats(dir_trades)
        if not stats: continue
        sc = score(stats)
        
        result = {
            'symbol': 'T',
            'strategy': name,
            'direction': direction,
            'date_range': f"{datetime.fromtimestamp(dir_trades[0]['et']).strftime('%m/%d')}~{datetime.fromtimestamp(dir_trades[-1]['xt']).strftime('%m/%d')}",
            **stats,
            'score': sc,
            'trade_quality': 'A' if sc>=70 else ('B' if sc>=50 else 'C'),
            'trades_detail': [{
                'entry_time': datetime.fromtimestamp(t['et']).strftime('%Y-%m-%d %H:%M:%S'),
                'exit_time': datetime.fromtimestamp(t['xt']).strftime('%Y-%m-%d %H:%M:%S'),
                'entry_price': round(t['ep'],8), 'exit_price': round(t['xp'],8),
                'pnl_pct': t['pnl'], 'direction': t['dir'],
                'exit_reason': t['xr'], 'duration': t['dur'],
                'entry_rate': t['rate']
            } for t in dir_trades]
        }
        all_trades.append(result)
        
        flag = '🟢' if sc>=70 else ('🟡' if sc>=50 else '🔴')
        print(f'{flag} {name:20s} {direction:5s} T={stats["trades"]:3d} WR={stats["win_rate"]:.0f}% DD={stats["max_dd"]:.0f}% Sh={stats["sharpe"]:.1f} Score={sc}')

all_trades.sort(key=lambda x: x['score'], reverse=True)
with open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/backtest_T_5m.json', 'w') as f:
    json.dump(all_trades, f, ensure_ascii=False, indent=2)

print(f'\nSaved {len(all_trades)} results')
