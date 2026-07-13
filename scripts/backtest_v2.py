"""
全量回测引擎 v2
- 两个策略: funding_extreme (费率绝对值) + multifactor (V11多因子)
- LONG + SHORT 双向测试
- 收盘价进出（真实可执行）
- 每笔交易明细
- 策略+币种双维度报告
"""
import duckdb, json, math, os
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
OUT_DIR = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto'

con = duckdb.connect(DB, read_only=True)
syms = [s[0] for s in con.execute("SELECT DISTINCT symbol FROM kline").fetchall()]

# ===== Strategy 1: Funding Extreme =====
def backtest_funding_extreme(sym, direction='LONG'):
    """费率绝对值策略: rate < threshold → entry, SL/TP timeout exit"""
    THRESHOLD = -0.0005  # -0.05% absolute
    
    kl = con.execute(f"""SELECT open_time/1000, open, high, low, close, volume 
        FROM kline WHERE symbol='{sym}' AND interval='5m' ORDER BY open_time""").fetchall()
    fr = con.execute(f"SELECT funding_time, funding_rate FROM funding WHERE symbol='{sym}' ORDER BY funding_time").fetchall()
    
    if len(kl) < 200 or len(fr) < 50:
        return None
    
    trades = []
    fi = 0
    in_position = False
    entry = None
    
    for i in range(50, len(kl)):
        t_sec = int(kl[i][0])
        t_ms = t_sec * 1000
        close = kl[i][4]
        
        # Update funding rate pointer
        while fi + 1 < len(fr) and fr[fi+1][0] <= t_ms:
            fi += 1
        
        current_rate = fr[fi][1] if fi < len(fr) else 0
        
        if not in_position:
            if direction == 'LONG' and current_rate < THRESHOLD:
                in_position = True
                entry = {'time': t_sec, 'price': close, 'rate': current_rate, 'idx': i}
            elif direction == 'SHORT' and current_rate > abs(THRESHOLD):
                in_position = True
                entry = {'time': t_sec, 'price': close, 'rate': current_rate, 'idx': i}
        else:
            pnl_pct = (close / entry['price'] - 1) * 100
            if direction == 'SHORT':
                pnl_pct = -pnl_pct
            
            hours = (t_sec - entry['time']) / 3600
            exit_reason = None
            
            if pnl_pct <= -10:
                exit_reason = '止损'
            elif pnl_pct >= 10:
                exit_reason = '止盈'
            elif hours >= 48:
                exit_reason = '超时'
            
            if exit_reason or i == len(kl) - 1:
                if not exit_reason:
                    exit_reason = '收盘'
                
                # Calculate max favorable/adverse excursion
                max_profit = 0
                max_loss = 0
                for j in range(entry['idx'] + 1, i + 1):
                    p = (kl[j][4] / entry['price'] - 1) * 100
                    if direction == 'SHORT': p = -p
                    max_profit = max(max_profit, p)
                    max_loss = min(max_loss, p)
                
                trades.append({
                    'entry_time': datetime.fromtimestamp(entry['time']).strftime('%Y-%m-%d %H:%M:%S'),
                    'exit_time': datetime.fromtimestamp(t_sec).strftime('%Y-%m-%d %H:%M:%S'),
                    'entry_price': round(entry['price'], 8),
                    'exit_price': round(close, 8),
                    'pnl_pct': round(pnl_pct, 2),
                    'direction': direction,
                    'exit_reason': exit_reason,
                    'max_profit': round(max_profit, 2),
                    'max_loss': round(max_loss, 2),
                    'entry_rate': round(entry['rate'] * 100, 4)
                })
                in_position = False
                entry = None
    
    return trades

# ===== Strategy 2: V11 Multifactor =====
WEIGHTS = {'candle': 0.2, 'vol': 0.4, 'pa': 0.3, 'trend': 0.1}
THR = 0.18

def compute_multifactor_score(k, i):
    o, hi, lo, c, v = k[i][1], k[i][2], k[i][3], k[i][4], k[i][5]
    if i < 20: return 0
    po, pc = k[i-1][1], k[i-1][4]
    
    body = abs(c - o)
    wl = min(o, c) - lo
    wh = hi - max(o, c)
    total_range = max(hi - lo, 1e-8)
    
    hammer = 1 if wl > body * 1.5 and wl > wh * 1.5 else 0
    engulfing = 1 if pc < po and c > o and o < po and c > pc else 0
    doji = 1 if body / total_range < 0.3 and lo <= min(k[j][3] for j in range(i-10, i)) else 0
    cn = (hammer + engulfing + doji) / 3
    
    avg_vol = sum(k[j][5] for j in range(i-20, i)) / 20
    vl = min(v / max(avg_vol, 1e-8) / 3, 1) if c > o else 0
    
    sma20 = sum(k[j][4] for j in range(i-20, i)) / 20
    lo20 = min(k[j][3] for j in range(i-20, i))
    hi20 = max(k[j][2] for j in range(i-20, i))
    pb = (hi20 - c) / max(hi20, 1e-8)
    at_support = 1 if abs(c - lo20) / max(lo20, 1e-8) < 0.01 else 0
    above_ma = 1 if c > sma20 else 0
    pullback = 1 if 0.03 < pb < 0.20 else 0
    pa = (at_support + above_ma + pullback) / 3
    
    sma50 = sum(k[j][4] for j in range(i-50, i)) / 50 if i >= 50 else sma20
    tr = 1.0 if c > sma50 else (0.3 if c > sma20 else 0)
    
    score = WEIGHTS['candle'] * cn + WEIGHTS['vol'] * vl + WEIGHTS['pa'] * pa + WEIGHTS['trend'] * tr
    return round(score, 2)

def backtest_multifactor(sym, direction='LONG'):
    """V11多因子: 费率<P5 + 4h趋势 + 因子评分>0.18"""
    kl = con.execute(f"""SELECT open_time/1000, open, high, low, close, volume 
        FROM kline WHERE symbol='{sym}' AND interval='5m' ORDER BY open_time""").fetchall()
    fr = con.execute(f"SELECT funding_time, funding_rate FROM funding WHERE symbol='{sym}' ORDER BY funding_time").fetchall()
    kl_4h = con.execute(f"SELECT open_time/1000, close FROM kline WHERE symbol='{sym}' AND interval='4h' ORDER BY open_time DESC LIMIT 50").fetchall()
    
    if len(kl) < 200 or len(fr) < 50 or len(kl_4h) < 20:
        return None
    
    rates = [r for _, r in fr]
    p5 = sorted(rates)[int(len(rates) * 0.05)]
    p95 = sorted(rates)[int(len(rates) * 0.95)]
    
    trades = []
    fi = 0
    in_position = False
    entry = None
    
    for i in range(100, len(kl)):
        t_sec = int(kl[i][0])
        t_ms = t_sec * 1000
        close = kl[i][4]
        
        while fi + 1 < len(fr) and fr[fi+1][0] <= t_ms:
            fi += 1
        current_rate = fr[fi][1] if fi < len(fr) else 0
        
        # 4h trend check
        closes_4h = [c for _, c in kl_4h]
        if len(closes_4h) >= 50:
            ma20_4h = sum(closes_4h[:20]) / 20
            ma50_4h = sum(closes_4h[:50]) / 50
            trend_up = ma20_4h > ma50_4h
        else:
            trend_up = True  # insufficient data, default to allow
        
        # Compute factor score
        score = compute_multifactor_score(kl, i)
        
        if not in_position:
            signal = False
            if direction == 'LONG':
                signal = current_rate < p5 and trend_up and score >= THR
            else:  # SHORT
                signal = current_rate > p95 and not trend_up and score >= THR
            
            if signal:
                in_position = True
                entry = {'time': t_sec, 'price': close, 'rate': current_rate, 'score': score, 'idx': i}
        else:
            pnl_pct = (close / entry['price'] - 1) * 100
            if direction == 'SHORT':
                pnl_pct = -pnl_pct
            
            hours = (t_sec - entry['time']) / 3600
            
            # Trailing stop for LONG
            exit_reason = None
            if direction == 'LONG':
                if pnl_pct <= -10:
                    exit_reason = '止损'
                elif pnl_pct >= 5:
                    exit_reason = '止盈'
                elif hours >= 48:
                    exit_reason = '超时'
            else:  # SHORT
                if pnl_pct <= -10:
                    exit_reason = '止损'
                elif pnl_pct >= 5:
                    exit_reason = '止盈'
                elif hours >= 48:
                    exit_reason = '超时'
            
            if exit_reason or i == len(kl) - 1:
                if not exit_reason:
                    exit_reason = '收盘'
                
                max_profit = 0
                max_loss = 0
                for j in range(entry['idx'] + 1, i + 1):
                    p = (kl[j][4] / entry['price'] - 1) * 100
                    if direction == 'SHORT': p = -p
                    max_profit = max(max_profit, p)
                    max_loss = min(max_loss, p)
                
                trades.append({
                    'entry_time': datetime.fromtimestamp(entry['time']).strftime('%Y-%m-%d %H:%M:%S'),
                    'exit_time': datetime.fromtimestamp(t_sec).strftime('%Y-%m-%d %H:%M:%S'),
                    'entry_price': round(entry['price'], 8),
                    'exit_price': round(close, 8),
                    'pnl_pct': round(pnl_pct, 2),
                    'direction': direction,
                    'exit_reason': exit_reason,
                    'max_profit': round(max_profit, 2),
                    'max_loss': round(max_loss, 2),
                    'entry_rate': round(entry['rate'] * 100, 4),
                    'entry_score': entry['score']
                })
                in_position = False
                entry = None
    
    return trades

def compute_stats(trades):
    if not trades or len(trades) < 3:
        return None
    
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    wr = len(wins) / len(trades) * 100
    
    returns = [t['pnl_pct'] for t in trades]
    avg_ret = sum(returns) / len(returns)
    total_ret = sum(returns)
    
    std = math.sqrt(sum((r - avg_ret)**2 for r in returns) / len(returns)) if len(returns) > 1 else 1
    sharpe = (avg_ret / max(std, 0.01)) * math.sqrt(len(trades))
    sharpe = min(sharpe, 99.99)
    
    # Max drawdown
    peak = 0; eq = 0; max_dd = 0
    for r in returns:
        eq += r
        if eq > peak: peak = eq
        dd = peak - eq
        if dd > max_dd: max_dd = dd
    
    # Profit factor
    gross_profit = sum(t['pnl_pct'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl_pct'] for t in losses)) if losses else 1
    pf = gross_profit / max(gross_loss, 0.01)
    
    return {
        'trades': len(trades),
        'win_rate': round(wr, 1),
        'avg_pnl': round(avg_ret, 2),
        'total_return': round(total_ret, 2),
        'max_dd': round(max_dd, 1),
        'sharpe': round(sharpe, 2),
        'profit_factor': round(pf, 2),
        'avg_win': round(sum(t['pnl_pct'] for t in wins) / max(len(wins), 1), 2),
        'avg_loss': round(sum(t['pnl_pct'] for t in losses) / max(len(losses), 1), 2),
    }

# ===== Run all =====
STRATEGIES = [
    ('funding_extreme', backtest_funding_extreme),
    ('multifactor', backtest_multifactor),
]
DIRECTIONS = ['LONG', 'SHORT']

results = {}

for sname, sfunc in STRATEGIES:
    results[sname] = {'LONG': [], 'SHORT': []}
    for direction in DIRECTIONS:
        print(f'\n=== {sname} {direction} ===')
        for sym in syms:
            trades = sfunc(sym, direction)
            if not trades or len(trades) < 3:
                continue
            
            stats = compute_stats(trades)
            if not stats or stats['sharpe'] < 0 or stats['max_dd'] > 80 or stats['trades'] < 3:
                continue
            
            # Keep only top results
            short_sym = sym.replace('USDT', '')
            
            # Export chart data for top coins
            chart_path = f'{OUT_DIR}/chart_{short_sym}_5m.json'
            if not os.path.exists(chart_path):
                # Generate chart on the fly
                kl = con.execute(f"""SELECT open_time/1000, open, high, low, close 
                    FROM kline WHERE symbol='{sym}' AND interval='5m' ORDER BY open_time""").fetchall()
                if len(kl) >= 50:
                    klines = [{'time': int(r[0]), 'open': r[1], 'high': r[2], 'low': r[3], 'close': r[4]} for r in kl]
                    markers = []
                    for t in trades:
                        ts = int(datetime.strptime(t['entry_time'], '%Y-%m-%d %H:%M:%S').timestamp())
                        markers.append({'time': ts, 'type': 'entry', 'text': '开多' if direction=='LONG' else '开空', 
                                       'strategy': sname, 'pnl': t['pnl_pct']})
                    with open(chart_path, 'w') as f:
                        json.dump({'klines': klines, 'markers': markers}, f, default=str)
            
            result = {
                'symbol': short_sym,
                'strategy': sname,
                'direction': direction,
                'date_range': f"{trades[0]['entry_time'][5:10]}~{trades[-1]['exit_time'][5:10]}",
                **stats,
                'trades_detail': trades
            }
            results[sname][direction].append(result)
            
            verdict = '✅' if stats['sharpe'] > 1 and stats['win_rate'] > 50 else ('⚠️' if stats['sharpe'] > 0 else '❌')
            print(f'  {verdict} {short_sym:10s} T={stats["trades"]:3d} WR={stats["win_rate"]:5.1f}% avg={stats["avg_pnl"]:+6.2f}% DD={stats["max_dd"]:5.1f}% Sh={stats["sharpe"]:6.2f}')

con.close()

# Save results
for sname in ['funding_extreme', 'multifactor']:
    for d in ['LONG', 'SHORT']:
        # Sort by sharpe
        results[sname][d].sort(key=lambda x: x['sharpe'], reverse=True)
        fname = f'backtest_{sname}_{d.lower()}.json'
        with open(f'{OUT_DIR}/{fname}', 'w') as f:
            json.dump(results[sname][d], f, ensure_ascii=False, indent=2, default=str)
        print(f'\nSaved {fname}: {len(results[sname][d])} coins')

# Merge for page consumption
all_results = []
for sname in ['funding_extreme', 'multifactor']:
    for d in ['LONG', 'SHORT']:
        all_results.extend(results[sname][d])

# Filter: only sharpe > 0.5 AND wr > 40%
filtered = [r for r in all_results if r['sharpe'] > 0.5 and r['win_rate'] > 40]
filtered.sort(key=lambda x: x['sharpe'], reverse=True)

with open(f'{OUT_DIR}/backtest_all.json', 'w') as f:
    json.dump(filtered, f, ensure_ascii=False, indent=2, default=str)

print(f'\nFinal: {len(filtered)} tradable results saved to backtest_all.json')
print('Done.')
