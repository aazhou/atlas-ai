"""
PA-V3 完整版: LONG+SHORT, 三周期(4h/1h/15m), EMA14/55/144
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

SYMS = ['TUSDT','ETHUSDT','BTCUSDT','ZECUSDT','SKLUSDT','DOGEUSDT']

for sym in SYMS:
    kl_4h = con.execute(f"SELECT open_time/1000, close FROM kline WHERE symbol='{sym}' AND interval='4h' ORDER BY open_time").fetchall()
    kl_1h = con.execute(f"SELECT open_time/1000, open, high, low, close FROM kline WHERE symbol='{sym}' AND interval='1h' ORDER BY open_time").fetchall()
    kl_15m = con.execute(f"SELECT open_time/1000, open, high, low, close, volume FROM kline WHERE symbol='{sym}' AND interval='15m' ORDER BY open_time").fetchall()
    
    if len(kl_4h) < 200 or len(kl_1h) < 200 or len(kl_15m) < 500:
        continue
    
    # 4h EMA144
    c4 = [k[1] for k in kl_4h]; t4 = [k[0] for k in kl_4h]
    e144_4h = ema(c4, 144)
    
    def get_4h_state(t):
        """Return: (above_EMA144, below_EMA144)"""
        for i in range(len(t4)-1, -1, -1):
            if t4[i] <= t:
                if i < 144: return False, False
                return c4[i] > e144_4h[i], c4[i] < e144_4h[i]
        return False, False
    
    # 1h EMA14/55
    c1 = [k[4] for k in kl_1h]; t1 = [k[0] for k in kl_1h]
    e14_1h = ema(c1, 14); e55_1h = ema(c1, 55)
    
    def get_1h_state(t, price):
        """Return: (bullish_momentum, bearish_momentum, dist_to_ema55_pct)"""
        for i in range(len(t1)-1, -1, -1):
            if t1[i] <= t:
                if i < 55: return False, False, 0
                bull = e14_1h[i] > e55_1h[i]
                bear = e14_1h[i] < e55_1h[i]
                dist = (price - e55_1h[i]) / e55_1h[i] * 100
                return bull, bear, dist
        return False, False, 0
    
    # === SIMULATE ===
    trades = []
    pos = None
    
    for i in range(500, len(kl_15m)):
        o, h, l, c, v = kl_15m[i][1:6]
        t = kl_15m[i][0]
        
        # Exit
        if pos:
            pnl = (c / pos['ep'] - 1) * 100
            if pos['dir'] == 'SHORT':
                pnl = -pnl
            
            if l <= pos['sl'] and pos['dir'] == 'LONG':
                pos['px'] = pos['sl']; pos['pnl'] = round((pos['sl']/pos['ep']-1)*100, 2)
                pos['reason'] = '止损'; trades.append(pos); pos = None
            elif h >= pos['sl'] and pos['dir'] == 'SHORT':
                pos['px'] = pos['sl']; pos['pnl'] = round((1-pos['sl']/pos['ep'])*100, 2)
                pos['reason'] = '止损'; trades.append(pos); pos = None
            elif h >= pos['tp'] and pos['dir'] == 'LONG':
                pos['px'] = pos['tp']; pos['pnl'] = round((pos['tp']/pos['ep']-1)*100, 2)
                pos['reason'] = '止盈'; trades.append(pos); pos = None
            elif l <= pos['tp'] and pos['dir'] == 'SHORT':
                pos['px'] = pos['tp']; pos['pnl'] = round((1-pos['tp']/pos['ep'])*100, 2)
                pos['reason'] = '止盈'; trades.append(pos); pos = None
            elif (t - pos['et']) / 3600 > 120:
                pos['px'] = c; pos['pnl'] = round((c/pos['ep']-1)*100, 2)
                if pos['dir'] == 'SHORT': pos['pnl'] = -pos['pnl']
                pos['reason'] = '超时'; trades.append(pos); pos = None
            elif i == len(kl_15m)-1:
                pos['px'] = c; pos['pnl'] = round((c/pos['ep']-1)*100, 2)
                if pos['dir'] == 'SHORT': pos['pnl'] = -pos['pnl']
                pos['reason'] = '收盘'; trades.append(pos); pos = None
            continue
        
        # === ENTRY ===
        above_144, below_144 = get_4h_state(t)
        bull_mom, bear_mom, dist = get_1h_state(t, c)
        
        # PA signal
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        avg_v = sum(kl_15m[j][5] for j in range(max(0,i-10), i)) / min(10, i)
        
        # LONG conditions
        if above_144 and bull_mom:
            # Pullback near 1h EMA55 (within -1% to +2%)
            if -1 < dist < 2:
                # Bullish PA: hammer/reversal at support
                pa_ok = lower_wick > body * 0.5 and c > o and v > avg_v
                if pa_ok:
                    atrs = []
                    for j in range(max(0,i-13), i):
                        tr = max(kl_15m[j][2]-kl_15m[j][3], abs(kl_15m[j][2]-kl_15m[max(0,j-1)][4]), abs(kl_15m[j][3]-kl_15m[max(0,j-1)][4]))
                        atrs.append(tr)
                    atr = sum(atrs)/len(atrs) if atrs else c*0.005
                    pos = {'et': t, 'ep': c, 'dir': 'LONG', 'atr': atr, 'sl': c - atr*1.5, 'tp': c + atr*3.0}
        
        # SHORT conditions
        elif below_144 and bear_mom:
            # Rally near 1h EMA55 (within -2% to +1%)
            if -2 < dist < 1:
                # Bearish PA: shooting star/reversal at resistance
                pa_ok = upper_wick > body * 0.5 and c < o and v > avg_v
                if pa_ok:
                    atrs = []
                    for j in range(max(0,i-13), i):
                        tr = max(kl_15m[j][2]-kl_15m[j][3], abs(kl_15m[j][2]-kl_15m[max(0,j-1)][4]), abs(kl_15m[j][3]-kl_15m[max(0,j-1)][4]))
                        atrs.append(tr)
                    atr = sum(atrs)/len(atrs) if atrs else c*0.005
                    pos = {'et': t, 'ep': c, 'dir': 'SHORT', 'atr': atr, 'sl': c + atr*1.5, 'tp': c - atr*3.0}
    
    if len(trades) < 5:
        continue
    
    # Separate by direction
    for direction in ['LONG', 'SHORT']:
        dir_trades = [t for t in trades if t['dir'] == direction]
        if len(dir_trades) < 5: continue
        
        wins = sum(1 for t in dir_trades if t['pnl'] > 0)
        wr = wins / len(dir_trades) * 100
        avg = sum(t['pnl'] for t in dir_trades) / len(dir_trades)
        total = sum(t['pnl'] for t in dir_trades)
        
        eq=0; peak=0; dd=0
        for t in dir_trades:
            eq+=t['pnl']
            if eq>peak: peak=eq
            if peak-eq>dd: dd=peak-eq
        
        days = (kl_15m[-1][0] - kl_15m[0][0]) / 86400
        freq = len(dir_trades) / max(days/30, 0.5)
        
        reasons = {}
        for t in dir_trades:
            r = t.get('reason','?')
            reasons[r] = reasons.get(r,0)+1
        
        flag = '🔥' if wr>=45 and total>0 and dd<20 else ('✅' if total>0 else '❌')
        
        print(f'{flag} {sym:12s} {direction:5s} | {len(dir_trades)}T WR={wr:.0f}% avg={avg:+.2f}% total={total:+.2f}% DD={dd:.1f}% | {freq:.1f}/月 | {reasons}')

con.close()
