"""
回测v3: 多周期 + 流动性过滤 + 策略评分 + 实盘指令
- 信号层: 4h K线(费率+趋势) / 日线确认
- 入场层: 15m K线(收盘价)
- 成交量>$500K过滤
- 输出: 回测报告 + 策略评分 + 实盘指令模板
"""
import duckdb, json, math, os
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
OUT = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto'
MIN_VOL = 500000  # $500K minimum avg volume

con = duckdb.connect(DB, read_only=True)

# === Step 0: Filter symbols by liquidity ===
sym_vols = con.execute("""
    SELECT symbol, AVG(volume*close) as avg_vol
    FROM kline WHERE interval='15m'
    GROUP BY symbol HAVING avg_vol > {}
    ORDER BY avg_vol DESC
""".format(MIN_VOL)).fetchall()

liquid_syms = [s[0] for s in sym_vols]
print(f'Liquid symbols (>{MIN_VOL/1e6:.0f}M): {len(liquid_syms)}')
for s in sym_vols[:10]:
    print(f'  {s[0]:20s} ${s[1]:>12,.0f}')

# === Strategy 1: Funding Extreme (absolute threshold) ===
def backtest_funding_extreme(sym):
    """费率< -0.05% → LONG / > +0.05% → SHORT. 4h trend confirm."""
    kl = con.execute(f"SELECT open_time/1000, close FROM kline WHERE symbol='{sym}' AND interval='15m' ORDER BY open_time").fetchall()
    kl_4h = con.execute(f"SELECT open_time/1000, close FROM kline WHERE symbol='{sym}' AND interval='4h' ORDER BY open_time").fetchall()
    fr = con.execute(f"SELECT funding_time, funding_rate FROM funding WHERE symbol='{sym}' ORDER BY funding_time").fetchall()
    
    if len(kl) < 500 or len(kl_4h) < 30 or len(fr) < 30:
        return []
    
    # Precompute 4h trend
    closes_4h = [c for _, c in kl_4h]
    trend_4h = []
    for i in range(len(kl_4h)):
        if i < 20:
            trend_4h.append(True)
        else:
            ma20 = sum(closes_4h[i-20:i]) / 20
            ma50 = sum(closes_4h[max(0,i-50):i]) / min(50, i)
            trend_4h.append(ma20 > ma50)
    
    trades = []
    positions = []  # track open positions
    
    fi = 0
    for i in range(50, len(kl)):
        t_sec = int(kl[i][0])
        close = kl[i][1]
        t_ms = t_sec * 1000
        
        while fi + 1 < len(fr) and fr[fi+1][0] <= t_ms:
            fi += 1
        rate = fr[fi][1] if fi < len(fr) else 0
        
        # Find nearest 4h candle for trend
        four_h_idx = 0
        while four_h_idx + 1 < len(kl_4h) and kl_4h[four_h_idx+1][0] <= t_sec:
            four_h_idx += 1
        trend_up = trend_4h[four_h_idx] if four_h_idx < len(trend_4h) else True
        
        # Check open positions for exits
        new_positions = []
        for pos in positions:
            pnl = (close / pos['entry_price'] - 1) * 100
            if pos['direction'] == 'SHORT':
                pnl = -pnl
            hours = (t_sec - pos['entry_time']) / 3600
            
            exit_reason = None
            if pnl <= -10: exit_reason = '止损'
            elif pnl >= 10: exit_reason = '止盈'
            elif hours >= 48: exit_reason = '超时'
            elif i == len(kl) - 1: exit_reason = '收盘'
            
            if exit_reason:
                pos['exit_time'] = t_sec
                pos['exit_price'] = close
                pos['pnl_pct'] = round(pnl, 2)
                pos['exit_reason'] = exit_reason
                trades.append(pos)
            else:
                new_positions.append(pos)
        positions = new_positions
        
        # Entry signals (only if not already in position)
        if not positions:
            if rate < -0.0005 and trend_up:
                positions.append({
                    'entry_time': t_sec, 'entry_price': close,
                    'direction': 'LONG', 'entry_rate': round(rate*100, 4),
                    'strategy': 'funding_extreme'
                })
            elif rate > 0.0005 and not trend_up:
                positions.append({
                    'entry_time': t_sec, 'entry_price': close,
                    'direction': 'SHORT', 'entry_rate': round(rate*100, 4),
                    'strategy': 'funding_extreme'
                })
    
    return trades

# === Strategy 2: V11 Multifactor ===
WEIGHTS = {'candle': 0.2, 'vol': 0.4, 'pa': 0.3, 'trend': 0.1}
SCORE_THR = 0.18

def compute_mf_score(kl_15m, i):
    """Multi-factor score on 15m candles"""
    if i < 20: return 0
    o, hi, lo, c = kl_15m[i][1], kl_15m[i][2], kl_15m[i][3], kl_15m[i][4]
    v = kl_15m[i][5] if len(kl_15m[i]) > 5 else 0
    po, pc = kl_15m[i-1][1], kl_15m[i-1][4]
    
    body = abs(c - o)
    wl = min(o, c) - lo
    wh = hi - max(o, c)
    tr = max(hi - lo, 1e-8)
    
    hammer = 1 if wl > body * 1.5 and wl > wh * 1.5 else 0
    engulfing = 1 if pc < po and c > o and o < po and c > pc else 0
    cn = (hammer + engulfing) / 2
    
    if v > 0:
        avg_vol = sum(kl_15m[j][5] for j in range(i-20, i)) / 20 if all(len(k) > 5 for k in kl_15m[i-20:i]) else 1
        vl = min(v / max(avg_vol, 1e-8) / 3, 1) if c > o else 0
    else:
        vl = 0.5
    
    sma20 = sum(kl_15m[j][4] for j in range(i-20, i)) / 20
    sma50 = sum(kl_15m[j][4] for j in range(max(0,i-50), i)) / min(50, i) if i >= 50 else sma20
    trend = 1.0 if c > sma50 else (0.3 if c > sma20 else 0)
    
    lo20 = min(kl_15m[j][3] for j in range(i-20, i))
    hi20 = max(kl_15m[j][2] for j in range(i-20, i))
    pb = (hi20 - c) / max(hi20, 1e-8)
    pa = (1 if 0.03 < pb < 0.20 else 0) + (1 if c > sma20 else 0)
    pa /= 2
    
    score = WEIGHTS['candle'] * cn + WEIGHTS['vol'] * vl + WEIGHTS['pa'] * pa + WEIGHTS['trend'] * trend
    return round(score, 2)

def backtest_multifactor(sym):
    """V11: 费率<P5 + 4h趋势 + 15m因子评分"""
    kl = con.execute(f"SELECT open_time/1000, open, high, low, close, volume FROM kline WHERE symbol='{sym}' AND interval='15m' ORDER BY open_time").fetchall()
    kl_4h = con.execute(f"SELECT open_time/1000, close FROM kline WHERE symbol='{sym}' AND interval='4h' ORDER BY open_time").fetchall()
    fr = con.execute(f"SELECT funding_time, funding_rate FROM funding WHERE symbol='{sym}' ORDER BY funding_time").fetchall()
    
    if len(kl) < 500 or len(kl_4h) < 30 or len(fr) < 30:
        return []
    
    rates = [r for _, r in fr]
    p5 = sorted(rates)[int(len(rates)*0.05)]
    p95 = sorted(rates)[int(len(rates)*0.95)]
    
    closes_4h = [c for _, c in kl_4h]
    trend_4h = []
    for i in range(len(kl_4h)):
        if i < 20:
            trend_4h.append(True)
        else:
            ma20 = sum(closes_4h[i-20:i])/20
            ma50 = sum(closes_4h[max(0,i-50):i])/min(50,i)
            trend_4h.append(ma20 > ma50)
    
    trades = []
    positions = []
    fi = 0
    
    for i in range(100, len(kl)):
        t_sec = int(kl[i][0])
        close = kl[i][4]
        
        while fi+1 < len(fr) and fr[fi+1][0] <= t_sec*1000:
            fi += 1
        rate = fr[fi][1] if fi < len(fr) else 0
        
        four_h_idx = 0
        while four_h_idx+1 < len(kl_4h) and kl_4h[four_h_idx+1][0] <= t_sec:
            four_h_idx += 1
        trend_up = trend_4h[four_h_idx] if four_h_idx < len(trend_4h) else True
        
        score = compute_mf_score(kl, i)
        
        # Check exits
        new_positions = []
        for pos in positions:
            pnl = (close / pos['entry_price'] - 1) * 100
            if pos['direction'] == 'SHORT': pnl = -pnl
            hours = (t_sec - pos['entry_time']) / 3600
            
            exit_reason = None
            if pnl <= -10: exit_reason = '止损'
            elif pnl >= 5: exit_reason = '止盈'
            elif hours >= 48: exit_reason = '超时'
            elif i == len(kl)-1: exit_reason = '收盘'
            
            if exit_reason:
                pos['exit_time'] = t_sec; pos['exit_price'] = close
                pos['pnl_pct'] = round(pnl,2); pos['exit_reason'] = exit_reason
                trades.append(pos)
            else:
                new_positions.append(pos)
        positions = new_positions
        
        # Entry
        if not positions:
            if rate < p5 and trend_up and score >= SCORE_THR:
                positions.append({
                    'entry_time': t_sec, 'entry_price': close,
                    'direction': 'LONG', 'entry_rate': round(rate*100,4),
                    'entry_score': score, 'strategy': 'multifactor'
                })
            elif rate > p95 and not trend_up and score >= SCORE_THR:
                positions.append({
                    'entry_time': t_sec, 'entry_price': close,
                    'direction': 'SHORT', 'entry_rate': round(rate*100,4),
                    'entry_score': score, 'strategy': 'multifactor'
                })
    
    return trades

def compute_stats(trades):
    if len(trades) < 5: return None
    rets = [t['pnl_pct'] for t in trades]
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
    
    return {
        'trades': len(trades), 'win_rate': round(wr,1),
        'avg_pnl': round(avg,2), 'total_return': round(sum(rets),2),
        'max_dd': round(max_dd,1), 'sharpe': round(sharpe,2),
        'profit_factor': round(pf,2)
    }

def score_strategy(stats):
    """0-100 score: sharpe 30% + wr 20% + dd 25% + trades 15% + pf 10%"""
    if not stats: return 0
    s = 0
    s += min(stats['sharpe']/3, 1) * 30
    s += min(stats['win_rate']/80, 1) * 20
    s += max(0, 1 - stats['max_dd']/40) * 25
    s += min(stats['trades']/30, 1) * 15
    s += min(stats['profit_factor']/3, 1) * 10
    return round(s, 1)

def live_order_template(sym, direction, entry_price, capital=100000, risk_pct=2):
    """Generate Binance order instructions"""
    position_size = (capital * risk_pct / 100) / (entry_price * 0.10)  # risk 2% at 10% SL
    sl_price = entry_price * (0.9 if direction=='LONG' else 1.1)
    tp_price = entry_price * (1.05 if direction=='LONG' else 0.95)
    
    return {
        'symbol': sym,
        'direction': direction,
        'entry_price': round(entry_price, 8),
        'quantity': round(position_size, 2),
        'stop_loss': round(sl_price, 8),
        'take_profit': round(tp_price, 8),
        'risk_amount': round(capital * risk_pct / 100, 2),
        'order_type': 'MARKET'
    }

# === RUN ===
all_results = []
strategies = [
    ('funding_extreme', backtest_funding_extreme),
    ('multifactor', backtest_multifactor),
]

for sname, sfunc in strategies:
    print(f'\n=== {sname} ===')
    for sym in liquid_syms:
        trades = sfunc(sym)
        if len(trades) < 5:
            continue
        
        # Split by direction
        for direction in ['LONG', 'SHORT']:
            dir_trades = [t for t in trades if t['direction'] == direction]
            if len(dir_trades) < 5:
                continue
            
            stats = compute_stats(dir_trades)
            if not stats or stats['sharpe'] < 0 or stats['max_dd'] > 50:
                continue
            
            score = score_strategy(stats)
            short = sym.replace('USDT', '')
            
            result = {
                'symbol': short, 'strategy': sname, 'direction': direction,
                'date_range': f"{datetime.fromtimestamp(dir_trades[0]['entry_time']).strftime('%m/%d')}~{datetime.fromtimestamp(dir_trades[-1]['exit_time']).strftime('%m/%d')}",
                **stats,
                'score': score,
                'trade_quality': 'A' if score>=70 else ('B' if score>=50 else 'C'),
                'trades_detail': dir_trades,
                'live_order': live_order_template(short, direction, dir_trades[-1]['exit_price']) if dir_trades else None
            }
            all_results.append(result)
            
            flag = '🟢' if score>=70 else ('🟡' if score>=50 else '🔴')
            print(f'  {flag} {short:10s} {direction:5s} T={stats["trades"]:3d} WR={stats["win_rate"]:.0f}% DD={stats["max_dd"]:.0f}% Sh={stats["sharpe"]:.1f} Score={score}')

con.close()

# Sort and save
all_results.sort(key=lambda x: x['score'], reverse=True)
with open(f'{OUT}/backtest_v3.json', 'w') as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)

# Summary
a_count = len([r for r in all_results if r['score']>=70])
b_count = len([r for r in all_results if 50<=r['score']<70])
print(f'\n=== SUMMARY ===')
print(f'Total viable: {len(all_results)}  (A:{a_count} B:{b_count})')
if a_count > 0:
    print('Ready for small-capital live testing!')
    for r in [r for r in all_results if r['score']>=70]:
        o = r['live_order']
        print(f'  {r["symbol"]} {r["direction"]} {r["strategy"]}: qty={o["quantity"]} SL={o["stop_loss"]} TP={o["take_profit"]}')

print(f'\nSaved: backtest_v3.json ({len(all_results)} entries)')
