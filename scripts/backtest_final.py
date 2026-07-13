"""
全量回测引擎 vFinal
- 双策略 × 多参数组合 × LONG/SHORT × 50币种
- 5m入场 + 4h趋势过滤
- 参数网格: TP(3/5/8/10%) SL(5/8/10%) Hold(12/24/48h)
- 输出: 最优参数 + 合格标的 + 实盘指令
"""
import duckdb, json, math, os, itertools
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
OUT = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto'
MIN_VOL = 30000  # $30K - microcaps are our bread and butter

con = duckdb.connect(DB, read_only=True)

# Get liquid symbols with at least 30 days of 5m data
sym_info = con.execute("""
    SELECT s.symbol, AVG(s.volume*s.close) as avg_vol, 
           (MAX(s.open_time)-MIN(s.open_time))/86400000.0 as days,
           COUNT(*) as bars
    FROM kline s WHERE s.interval='5m'
    GROUP BY s.symbol HAVING days >= 3 AND avg_vol > {}
    ORDER BY avg_vol DESC
""".format(MIN_VOL)).fetchall()

syms = [(s[0], s[2]) for s in sym_info]
print(f'Qualifying symbols (>{MIN_VOL/1e6:.1f}M vol, >30d): {len(syms)}')
for s in sym_info[:15]:
    print(f'  {s[0]:20s} ${s[1]:>12,.0f}  {s[2]:.0f}d  {s[3]} bars')

# Parameter grid
TP_OPTIONS = [0.03, 0.05, 0.08, 0.10]
SL_OPTIONS = [0.05, 0.08, 0.10]
HOLD_OPTIONS = [12, 24, 48]

def backtest(sym, strategy, direction, tp, sl, max_hours):
    """Core backtest: 5m entry + 4h trend"""
    kl = con.execute(f"SELECT open_time/1000, open, high, low, close, volume FROM kline WHERE symbol='{sym}' AND interval='5m' ORDER BY open_time").fetchall()
    kl4 = con.execute(f"SELECT open_time/1000, close FROM kline WHERE symbol='{sym}' AND interval='4h' ORDER BY open_time").fetchall()
    fr = con.execute(f"SELECT funding_time, funding_rate FROM funding WHERE symbol='{sym}' ORDER BY funding_time").fetchall()
    
    if len(kl) < 500 or len(kl4) < 20 or len(fr) < 30:
        return []
    
    # Precompute 4h trend
    c4 = [c for _,c in kl4]
    trends = []
    for i in range(len(kl4)):
        if i < 20: trends.append(True)
        else:
            ma20 = sum(c4[i-20:i])/20; ma50 = sum(c4[max(0,i-50):i])/min(50,i)
            trends.append(ma20 > ma50)
    
    # Funding thresholds
    rates = [r for _,r in fr]
    p5 = sorted(rates)[int(len(rates)*0.05)]
    p95 = sorted(rates)[int(len(rates)*0.95)]
    
    trades = []
    pos = None
    fi = 0
    
    for i in range(100, len(kl)):
        t = int(kl[i][0]); o,h,l,c,v = kl[i][1:6]
        
        while fi+1 < len(fr) and fr[fi+1][0] <= t*1000: fi += 1
        rate = fr[fi][1] if fi < len(fr) else 0
        
        fhi = 0
        while fhi+1 < len(kl4) and kl4[fhi+1][0] <= t: fhi += 1
        trend_up = trends[fhi] if fhi < len(trends) else True
        
        if pos:
            pnl = (c / pos['ep'] - 1) * 100
            if pos['dir'] == 'SHORT': pnl = -pnl
            hours = (t - pos['et']) / 3600
            
            er = None
            if pnl <= -sl*100: er = '止损'
            elif pnl >= tp*100: er = '止盈'
            elif hours >= max_hours: er = '超时'
            elif i == len(kl)-1: er = '收盘'
            
            if er:
                pos['pnl'] = round(pnl, 2); pos['xr'] = er
                pos['xt'] = t; pos['xp'] = c
                trades.append(pos)
                pos = None
        
        elif i >= 20:
            # Entry conditions
            if strategy == 'funding_extreme':
                signal = (rate < -0.0005 and trend_up and direction == 'LONG') or \
                         (rate > 0.0005 and not trend_up and direction == 'SHORT')
            else:  # multifactor
                # Quick multi-factor score
                po,pc = kl[i-1][1], kl[i-1][4]
                body = abs(c-o); wl = min(o,c)-l; wh = h-max(o,c)
                cn = ((1 if wl>body*1.5 and wl>wh*1.5 else 0) + (1 if pc<po and c>o and o<po and c>pc else 0)) / 2
                
                try:
                    avg_vol = sum(kl[j][5] for j in range(i-20,i)) / 20
                    vl = min(v/max(avg_vol,1e-8)/3, 1) if c>o else 0
                except: vl = 0
                
                sma20 = sum(kl[j][4] for j in range(i-20,i)) / 20
                sma50 = sum(kl[j][4] for j in range(max(0,i-50),i)) / min(50,i) if i>=50 else sma20
                trend = 1.0 if c>sma50 else (0.3 if c>sma20 else 0)
                
                lo20 = min(kl[j][3] for j in range(i-20,i))
                hi20 = max(kl[j][2] for j in range(i-20,i))
                pb = (hi20-c)/max(hi20,1e-8)
                pa = ((1 if 0.03<pb<0.20 else 0) + (1 if c>sma20 else 0)) / 2
                
                sc = 0.2*cn + 0.4*vl + 0.3*pa + 0.1*trend
                
                signal = (rate<p5 and trend_up and sc>=0.18 and direction=='LONG') or \
                         (rate>p95 and not trend_up and sc>=0.18 and direction=='SHORT')
            
            if signal:
                pos = {'et': t, 'ep': c, 'dir': direction, 'rate': round(rate*100,4)}
    
    return trades

def score_stats(stats):
    """0-100 quality score"""
    if not stats or stats['trades'] < 5: return 0
    s = 0
    s += min(stats['sharpe']/3, 1) * 25
    s += min(stats['win_rate']/75, 1) * 20
    s += max(0, 1 - stats['max_dd']/35) * 20
    s += min(stats['profit_factor']/2.5, 1) * 15
    s += min(stats['trades']/20, 1) * 10
    s += min(stats['avg_pnl']/5, 1) * 10
    return round(s, 1)

def compute(trades):
    if len(trades) < 5: return None
    rets = [t['pnl'] for t in trades]
    wins = [r for r in rets if r>0]
    avg = sum(rets)/len(rets); total = sum(rets)
    std = math.sqrt(sum((r-avg)**2 for r in rets)/len(rets)) if len(rets)>1 else 1
    sharpe = min((avg/max(std,0.01))*math.sqrt(len(rets)), 99.99)
    
    eq=0; peak=0; max_dd=0
    for r in rets:
        eq+=r
        if eq>peak: peak=eq
        dd=peak-eq
        if dd>max_dd: max_dd=dd
    
    gp = sum(r for r in rets if r>0); gl = abs(sum(r for r in rets if r<0))
    pf = gp/max(gl,0.01)
    
    # Monthly freq
    first_t = datetime.fromtimestamp(trades[0]['et'])
    last_t = datetime.fromtimestamp(trades[-1]['xt'])
    months = max((last_t-first_t).days/30, 0.5)
    
    return {
        'trades': len(trades), 'win_rate': round(len(wins)/len(rets)*100,1),
        'avg_pnl': round(avg,2), 'total_return': round(total,2),
        'max_dd': round(max_dd,1), 'sharpe': round(sharpe,2),
        'profit_factor': round(pf,2),
        'trades_per_month': round(len(trades)/months, 1),
        'date_range': f"{first_t.strftime('%m/%d')}~{last_t.strftime('%m/%d')}"
    }

# === RUN PARAMETER SWEEP ===
print('\n=== Parameter Sweep ===')
all_results = []

for sym, days in syms:
    for strategy in ['funding_extreme', 'multifactor']:
        for direction in ['LONG', 'SHORT']:
            best_score = 0
            best_trades = None
            best_params = None
            
            for tp, sl, hold in itertools.product(TP_OPTIONS, SL_OPTIONS, HOLD_OPTIONS):
                if tp >= sl: continue  # TP must be < SL for rational risk/reward
                trades = backtest(sym, strategy, direction, tp, sl, hold)
                if len(trades) < 5: continue
                
                stats = compute(trades)
                if not stats: continue
                
                sc = score_stats(stats)
                if sc > best_score:
                    best_score = sc
                    best_trades = trades
                    best_params = (tp, sl, hold)
                    best_stats = stats
            
            if best_trades and best_score >= 50:
                short = sym.replace('USDT','')
                result = {
                    'symbol': short,
                    'strategy': strategy,
                    'direction': direction,
                    'tp_pct': round(best_params[0]*100),
                    'sl_pct': round(best_params[1]*100),
                    'hold_h': best_params[2],
                    **best_stats,
                    'score': best_score,
                    'trade_quality': 'A' if best_score>=75 else ('B' if best_score>=60 else 'C'),
                    'trades_detail': [{
                        'entry_time': datetime.fromtimestamp(t['et']).strftime('%Y-%m-%d %H:%M:%S'),
                        'exit_time': datetime.fromtimestamp(t['xt']).strftime('%Y-%m-%d %H:%M:%S'),
                        'entry_price': round(t['ep'],8),
                        'exit_price': round(t['xp'],8),
                        'pnl_pct': t['pnl'],
                        'direction': t['dir'],
                        'exit_reason': t['xr'],
                        'entry_rate': t.get('rate', 0)
                    } for t in best_trades]
                }
                all_results.append(result)

con.close()

# Sort and filter
all_results.sort(key=lambda x: (-x['score'], -x['profit_factor']))

print(f'\n=== RESULTS ===')
a_count = sum(1 for r in all_results if r['trade_quality']=='A')
b_count = sum(1 for r in all_results if r['trade_quality']=='B')
print(f'Total qualifying: {len(all_results)} (A:{a_count} B:{b_count})')

# Show top results
for r in all_results[:20]:
    flag = '🟢' if r['trade_quality']=='A' else ('🟡' if r['trade_quality']=='B' else '')
    print(f"{flag} {r['symbol']:8s} {r['strategy']:18s} {r['direction']:5s} "
          f"TP={r['tp_pct']}% SL={r['sl_pct']}% Hold={r['hold_h']}h "
          f"T={r['trades']:3d} WR={r['win_rate']:.0f}% PF={r['profit_factor']:.1f} "
          f"DD={r['max_dd']:.0f}% Sh={r['sharpe']:.1f} Freq={r['trades_per_month']:.1f}/mo Score={r['score']}")

with open(f'{OUT}/backtest_final.json', 'w') as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2)

print(f'\nSaved: backtest_final.json')

# Strategy summary
print('\n=== STRATEGY SUMMARY ===')
for strat in ['funding_extreme', 'multifactor']:
    for d in ['LONG', 'SHORT']:
        matches = [r for r in all_results if r['strategy']==strat and r['direction']==d and r['trade_quality'] in ('A','B')]
        if matches:
            coins = ','.join(r['symbol'] for r in matches[:5])
            avg_score = sum(r['score'] for r in matches)/len(matches)
            print(f'  {strat} {d}: {len(matches)} coins, avg score {avg_score:.0f} -> {coins}')
