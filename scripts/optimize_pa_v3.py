"""
PA-V3 参数优化: 网格搜索最优ATR倍数、TP/SL比例、入场区间
在所有有完整三周期数据的币种上测试
"""
import duckdb, json, math
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
con = duckdb.connect(DB, read_only=True)

def ema(data, period):
    k = 2/(period+1)
    vals = [data[0]]
    for v in data[1:]:
        vals.append(v*k + vals[-1]*(1-k))
    return vals

def run_backtest(sym, atr_sl, atr_tp, entry_zone_lo, entry_zone_hi, min_trend_bars):
    kl_4h = con.execute(f"SELECT open_time/1000, close FROM kline WHERE symbol='{sym}' AND interval='4h' ORDER BY open_time").fetchall()
    kl_1h = con.execute(f"SELECT open_time/1000, open, high, low, close FROM kline WHERE symbol='{sym}' AND interval='1h' ORDER BY open_time").fetchall()
    kl_15m = con.execute(f"SELECT open_time/1000, open, high, low, close, volume FROM kline WHERE symbol='{sym}' AND interval='15m' ORDER BY open_time").fetchall()
    
    if len(kl_4h) < 200 or len(kl_1h) < 200 or len(kl_15m) < 500:
        return None
    
    c4 = [k[1] for k in kl_4h]; t4 = [k[0] for k in kl_4h]
    e144_4h = ema(c4, 144)
    
    def get_4h_state(t):
        for i in range(len(t4)-1, -1, -1):
            if t4[i] <= t:
                if i < 144: return False, False
                return c4[i] > e144_4h[i], c4[i] < e144_4h[i]
        return False, False
    
    c1 = [k[4] for k in kl_1h]; t1 = [k[0] for k in kl_1h]
    e14_1h = ema(c1, 14); e55_1h = ema(c1, 55)
    
    def get_1h_state(t, price):
        for i in range(len(t1)-1, -1, -1):
            if t1[i] <= t:
                if i < 55: return False, False, 0, False
                bull = e14_1h[i] > e55_1h[i]
                bear = e14_1h[i] < e55_1h[i]
                dist = (price - e55_1h[i]) / e55_1h[i] * 100
                # Check trend duration
                dur = 0
                for j in range(i, max(0,i-20), -1):
                    if e14_1h[j] > e55_1h[j]: dur += 1
                    else: break
                trend_ok = dur >= min_trend_bars
                return bull, bear, dist, trend_ok
        return False, False, 0, False
    
    trades = []
    pos = None
    
    for i in range(500, len(kl_15m)):
        o, h, l, c, v = kl_15m[i][1:6]
        t = kl_15m[i][0]
        
        if pos:
            if pos['dir'] == 'LONG':
                pnl = (c / pos['ep'] - 1) * 100
                if l <= pos['sl']:
                    pos['pnl'] = round((pos['sl']/pos['ep']-1)*100, 2); pos['reason'] = '止损'
                    trades.append(pos); pos = None
                elif h >= pos['tp']:
                    pos['pnl'] = round((pos['tp']/pos['ep']-1)*100, 2); pos['reason'] = '止盈'
                    trades.append(pos); pos = None
                elif (t - pos['et']) / 3600 > 120:
                    pos['pnl'] = round((c/pos['ep']-1)*100, 2); pos['reason'] = '超时'
                    trades.append(pos); pos = None
            else:  # SHORT
                pnl = (1 - c/pos['ep']) * 100
                if h >= pos['sl']:
                    pos['pnl'] = round((1-pos['sl']/pos['ep'])*100, 2); pos['reason'] = '止损'
                    trades.append(pos); pos = None
                elif l <= pos['tp']:
                    pos['pnl'] = round((1-pos['tp']/pos['ep'])*100, 2); pos['reason'] = '止盈'
                    trades.append(pos); pos = None
                elif (t - pos['et']) / 3600 > 120:
                    pos['pnl'] = round((1-c/pos['ep'])*100, 2); pos['reason'] = '超时'
                    trades.append(pos); pos = None
            continue
        
        above_144, below_144 = get_4h_state(t)
        bull_mom, bear_mom, dist, trend_ok = get_1h_state(t, c)
        
        body = abs(c - o)
        upper_wick = h - max(o, c); lower_wick = min(o, c) - l
        avg_v = sum(kl_15m[j][5] for j in range(max(0,i-10), i)) / max(1, min(10, i))
        
        if above_144 and bull_mom and trend_ok:
            if entry_zone_lo < dist < entry_zone_hi:
                pa_ok = lower_wick > body * 0.5 and c > o and v > avg_v * 1.3
                if pa_ok:
                    atrs = [max(kl_15m[j][2]-kl_15m[j][3], abs(kl_15m[j][2]-kl_15m[max(0,j-1)][4]), abs(kl_15m[j][3]-kl_15m[max(0,j-1)][4])) for j in range(max(0,i-13), i)]
                    atr = sum(atrs)/len(atrs) if atrs else c*0.005
                    pos = {'et': t, 'ep': c, 'dir': 'LONG', 'sl': c - atr*atr_sl, 'tp': c + atr*atr_tp}
        
        elif below_144 and bear_mom and trend_ok:
            if entry_zone_lo < dist < entry_zone_hi:
                pa_ok = upper_wick > body * 0.5 and c < o and v > avg_v * 1.3
                if pa_ok:
                    atrs = [max(kl_15m[j][2]-kl_15m[j][3], abs(kl_15m[j][2]-kl_15m[max(0,j-1)][4]), abs(kl_15m[j][3]-kl_15m[max(0,j-1)][4])) for j in range(max(0,i-13), i)]
                    atr = sum(atrs)/len(atrs) if atrs else c*0.005
                    pos = {'et': t, 'ep': c, 'dir': 'SHORT', 'sl': c + atr*atr_sl, 'tp': c - atr*atr_tp}
    
    if len(trades) < 5:
        return None
    
    wins = sum(1 for t in trades if t['pnl'] > 0)
    wr = wins / len(trades) * 100
    avg = sum(t['pnl'] for t in trades) / len(trades)
    total = sum(t['pnl'] for t in trades)
    
    eq=0; peak=0; dd=0
    for t in trades:
        eq+=t['pnl']
        if eq>peak: peak=eq
        if peak-eq>dd: dd=peak-eq
    
    days = (kl_15m[-1][0] - kl_15m[0][0]) / 86400
    freq = len(trades) / max(days/30, 0.5)
    
    return {'trades': len(trades), 'wr': wr, 'avg': avg, 'total': total, 'dd': dd, 'freq': freq}

# Grid search
SYMS = ['SKLUSDT','ETHUSDT','TUSDT','ZECUSDT','DOGEUSDT','BTCUSDT']
atr_sl_options = [1.0, 1.5, 2.0]
atr_tp_options = [2.0, 3.0, 4.0, 5.0]
zone_options = [(-3, 1), (-2, 1), (-1, 2), (-1, 1)]  # (entry_zone_lo, entry_zone_hi)
trend_options = [1, 3, 6]  # min trend bars

best = {}

for sl in atr_sl_options:
    for tp in atr_tp_options:
        if tp <= sl: continue
        for z_lo, z_hi in zone_options:
            for tb in trend_options:
                combined_score = 0
                tested = 0
                detail = []
                for sym in SYMS:
                    r = run_backtest(sym, sl, tp, z_lo, z_hi, tb)
                    if r:
                        tested += 1
                        # Score: reward consistent profitability
                        s = 0
                        if r['total'] > 0: s += 30
                        if r['wr'] >= 45: s += 25
                        elif r['wr'] >= 40: s += 15
                        if r['dd'] < 10: s += 20
                        elif r['dd'] < 20: s += 10
                        if 3 < r['freq'] < 20: s += 15  # 3-20 per month = ideal
                        elif r['freq'] <= 3: s += 5
                        combined_score += s
                        detail.append(f"{sym}:{r['trades']}T WR{r['wr']:.0f}% PnL{r['total']:+.1f}%")
                
                if tested >= 3:
                    params = f'SL={sl} TP={tp} zone=({z_lo},{z_hi}) trend={tb}h'
                    key_score = combined_score / tested
                    if key_score > 40:
                        print(f'🔥 {params} | avg_score={key_score:.0f} | {" | ".join(detail)}')

con.close()
