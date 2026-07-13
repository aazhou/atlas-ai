"""多因子评分策略 — 费率 + K线形态 + 量价关系 + 价格行为"""
import duckdb, json, math
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
con = duckdb.connect(DB, read_only=True)

def calc_factors(klines):
    """对每一根15m K线计算6类因子评分(0-1)"""
    n = len(klines)
    if n < 50: return []
    
    # Precompute: 20-period stats
    sma20_list = [0]*20
    for i in range(20, n):
        sma20_list.append(sum(klines[j][4] for j in range(i-20, i))/20)
    
    avg_vol_list = [0]*20
    for i in range(20, n):
        avg_vol_list.append(sum(klines[j][5] for j in range(i-20, i))/20)
    
    # Compute RSI
    rsi_list = [50]*14
    for i in range(14, n):
        gains = sum(max(klines[j][4]-klines[j-1][4], 0) for j in range(i-13, i+1))/14
        losses = sum(max(klines[j-1][4]-klines[j][4], 0) for j in range(i-13, i+1))/14
        rs = gains/losses if losses > 0 else 100
        rsi_list.append(100 - 100/(1+rs))
    
    factors = []
    for i in range(50, n):
        o, h, l, c, v = klines[i][1], klines[i][2], klines[i][3], klines[i][4], klines[i][5]
        prev_o, prev_c = klines[i-1][1], klines[i-1][4]
        
        # === Factor 1: K线形态 (0-1) ===
        body = abs(c-o); wick_low = min(o,c)-l; wick_high = h-max(o,c)
        total = max(h-l, 0.00000001)
        
        # 锤子线: 长下影, 小实体, 在近期低位
        hammer = 1.0 if (wick_low > body*2 and body < h-l and c > o) else 0
        # 吞没形态: 阳线完全吞没前一根阴线
        engulfing = 1.0 if (prev_c < prev_o and c > o and o <= prev_c and c >= prev_o) else 0
        # 早晨之星变体: 前阴 + 十字星 + 阳
        doji = 1.0 if body/total < 0.1 else 0
        morning_star = 1.0 if (prev_c < prev_o and doji > 0.5 and c > o and c > prev_c) else 0
        
        candle_score = (hammer + engulfing + morning_star) / 3
        
        # === Factor 2: 量价关系 (0-1) ===
        avg_vol = avg_vol_list[i]
        vol_ratio = v/max(avg_vol, 1)
        # 放量阳线 = 资金进场
        bull_vol = min(vol_ratio/5, 1.0) if c > o else 0
        # 缩量阴线 = 卖压枯竭
        die_vol = min(1/vol_ratio, 1.0) if c < o and vol_ratio < 1 else 0
        vol_score = max(bull_vol, die_vol)
        
        # === Factor 3: 价格行为 (0-1) ===
        sma20 = sma20_list[i]
        # 价格在均线上方 = 强势
        above_ma = 1.0 if c > sma20 else 0
        # 价格距20期低点 < 3% = 接近支撑
        low20 = min(klines[j][3] for j in range(i-20, i))
        near_support = 1.0 if (c - low20)/max(low20, 0.0001) < 0.03 else 0
        # 回撤幅度合理(>5% <15%) = 不是崩盘
        high20 = max(klines[j][2] for j in range(i-20, i))
        pullback_ratio = (high20-c)/max(high20, 0.0001)
        healthy_pb = 1.0 if 0.05 < pullback_ratio < 0.15 else 0
        
        pa_score = (above_ma + near_support + healthy_pb) / 3
        
        # === Factor 4: RSI (0-1) ===
        rsi = rsi_list[i]
        rsi_score = max(0, min(1, (40 - rsi)/20)) if rsi < 40 else 0  # RSI<40给分
        
        # === Factor 5: 动量 (0-1) ===
        # 3根连续阳线或阴线后的反转
        prev3 = [klines[j][4] for j in range(i-4, i)]
        prev3_up = all(prev3[j] > prev3[j-1] for j in range(1,4)) if len(prev3)>=4 else False
        mom_score = 0.5  # neutral
        
        # === Factor 6: 趋势确认 (0-1) ===
        # 价格在50期均线上
        if i >= 50:
            sma50 = sum(klines[j][4] for j in range(i-50, i))/50
            trend_score = 1.0 if c > sma50 else (0.3 if c > sma20 else 0)
        else:
            trend_score = 0.3
        
        factors.append({
            't': klines[i][0], 'o': o, 'h': h, 'l': l, 'c': c,
            'candle': round(candle_score, 2),
            'volume': round(vol_score, 2),
            'price_action': round(pa_score, 2),
            'rsi': round(rsi_score, 2),
            'momentum': round(mom_score, 2),
            'trend': round(trend_score, 2)
        })
    
    return factors

def backtest_multifactor(factors, funding_map, funding_p5, weights, score_threshold, sl_pct, tp_pct, hold_bars):
    """多因子加权评分策略回测"""
    trades = []
    for i, f in enumerate(factors):
        # 费率必须极端
        fr = funding_map.get(int(f['t']), 0)
        if fr >= funding_p5:
            continue
        
        # 综合评分
        score = (weights['candle'] * f['candle'] + 
                weights['volume'] * f['volume'] +
                weights['price_action'] * f['price_action'] +
                weights['rsi'] * f['rsi'] +
                weights['momentum'] * f['momentum'] +
                weights['trend'] * f['trend'])
        
        if score < score_threshold:
            continue
        
        ep = f['c']
        for j in range(i+1, min(i+hold_bars, len(factors))):
            fut = factors[j]
            if fut['l'] <= ep * (1 + sl_pct/100):
                trades.append(sl_pct)
                break
            elif fut['h'] >= ep * (1 + tp_pct/100):
                trades.append(tp_pct)
                break
            elif j == min(i+hold_bars-1, len(factors)-1):
                trades.append((fut['c']-ep)/ep*100)
    
    if len(trades) < 5:
        return None
    
    wins = sum(1 for t in trades if t > 0)
    wr = wins / len(trades) * 100
    avg = sum(trades) / len(trades)
    std = math.sqrt(sum((x-avg)**2 for x in trades) / len(trades))
    sharpe = avg / max(std, 0.001) * math.sqrt(len(trades))
    
    return {'trades': len(trades), 'wr': round(wr,1), 'avg_pnl': round(avg,2),
            'sharpe': round(sharpe,2), 'score': round(score_threshold,2),
            'sl': sl_pct, 'tp': tp_pct, 'hold': hold_bars}

# Test on TUSDT first
SYMS = ['TUSDT', 'VANRYUSDT', 'SKLUSDT']

for SYM in SYMS:
    klines = con.execute(f"SELECT open_time/1000,open,high,low,close,volume FROM kline WHERE symbol='{SYM}' AND interval='15m' ORDER BY open_time").fetchall()
    funding = con.execute(f"SELECT funding_time,funding_rate FROM funding WHERE symbol='{SYM}' ORDER BY funding_time").fetchall()
    funding_map = {int(f[0]/1000)*1000: f[1] for f in funding}
    p5 = sorted([v for v in funding_map.values()])[int(len(funding_map)*0.05)]
    
    factors = calc_factors(klines)
    if not factors: continue
    
    print(f"\n=== {SYM} === P5={p5*100:.3f}% | {len(factors)} bars with factors")
    
    best = {'sharpe': -99}
    
    # Weight grids: rate dominant, others auxiliary
    weight_grids = [
        {'candle':0.3,'volume':0.3,'price_action':0.2,'rsi':0.1,'momentum':0.0,'trend':0.1},
        {'candle':0.4,'volume':0.2,'price_action':0.3,'rsi':0.1,'momentum':0.0,'trend':0.0},
        {'candle':0.5,'volume':0.3,'price_action':0.2,'rsi':0.0,'momentum':0.0,'trend':0.0},
        {'candle':0.2,'volume':0.4,'price_action':0.3,'rsi':0.1,'momentum':0.0,'trend':0.0},
        {'candle':0.3,'volume':0.2,'price_action':0.4,'rsi':0.0,'momentum':0.0,'trend':0.1},
    ]
    
    for w in weight_grids:
        for threshold in [0.2, 0.25, 0.3, 0.35]:
            for sl in [-5, -8, -10]:
                for tp in [5, 8, 12, 20]:
                    for hold in [48, 96, 192]:
                        r = backtest_multifactor(factors, funding_map, p5, w, threshold, sl, tp, hold)
                        if r and r['sharpe'] > best['sharpe']:
                            best = {**r, 'weights': w, 'symbol': SYM}
                            print(f"  ★ Sh={r['sharpe']:.2f} WR={r['wr']:.0f}% T={r['trades']} avg={r['avg_pnl']:+.1f}% thr={r['score']} SL={sl}% TP={tp}% hold={hold}")

con.close()
if best['sharpe'] > -99:
    print(f"\nBEST: {json.dumps({k:v for k,v in best.items() if k!='weights'}, indent=2)}")
    json.dump(best, open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/best_multifactor.json', 'w'), indent=2, default=str)
