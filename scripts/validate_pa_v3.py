"""
PA-V3 策略验证: EMA14/55/144 + 价格行为
对Top20每币种回测最近30天的15m数据
"""
import duckdb, json, math
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
con = duckdb.connect(DB, read_only=True)

top20 = [s[0] for s in con.execute("""
    SELECT symbol FROM (
        SELECT symbol, AVG(volume*close) as avg_vol FROM kline WHERE interval='15m'
        GROUP BY symbol ORDER BY avg_vol DESC LIMIT 20
    )
""").fetchall()]

def ema(data, period):
    k = 2 / (period + 1)
    result = []
    val = data[0]
    for v in data:
        val = v * k + val * (1 - k)
        result.append(val)
    return result

def compute_emas(closes):
    e14 = ema(closes, 14)
    e55 = ema(closes, 55)
    e144 = ema(closes, 144)
    return e14, e55, e144

for sym in top20:
    kl = con.execute(f"SELECT open_time/1000, open, high, low, close, volume FROM kline WHERE symbol='{sym}' AND interval='15m' ORDER BY open_time").fetchall()
    if len(kl) < 500: continue
    
    closes = [k[4] for k in kl]
    volumes = [k[5] for k in kl]
    highs = [k[2] for k in kl]
    lows = [k[3] for k in kl]
    
    e14, e55, e144 = compute_emas(closes)
    
    # Count bullish/bearish bars
    bullish = 0; bearish = 0; total = 0
    for i in range(200, len(kl)):  # skip warmup
        total += 1
        if e14[i] > e55[i] > e144[i]: bullish += 1
        elif e14[i] < e55[i] < e144[i]: bearish += 1
    
    # Find long entries: pullback to EMA55/144 while EMA14>EMA55>EMA144
    trades_long = []
    pos = None
    for i in range(200, len(kl)):
        is_bullish = e14[i] > e55[i] and e55[i] > e144[i]
        c = closes[i]; h = highs[i]; l = lows[i]; v = volumes[i]
        avg_v = sum(volumes[max(0,i-10):i]) / 10 if i >= 10 else v
        
        if pos:
            pnl = (c / pos['ep'] - 1) * 100
            atr = pos['atr']
            # Exit: hit SL or TP1 or TP2
            if l <= pos['sl']:
                pos['px'] = pos['sl']; pos['pnl'] = round((pos['sl']/pos['ep']-1)*100,2)
                pos['reason'] = '止损'; trades_long.append(pos); pos = None
            elif h >= pos['tp1']:
                pos['px'] = pos['tp1']; pos['pnl'] = round((pos['tp1']/pos['ep']-1)*100,2)
                pos['reason'] = '止盈TP1'; trades_long.append(pos); pos = None
        
        elif is_bullish:
            # Pullback to EMA55 zone
            dist_to_55 = (c - e55[i]) / e55[i] * 100
            if 0 < dist_to_55 < 1.5 and v > avg_v * 1.3:
                # PA: check for bullish candle
                o = kl[i][1]
                body = abs(c - o)
                lower_wick = min(o, c) - l
                upper_wick = h - max(o, c)
                is_bullish_pa = c > o and lower_wick > body * 0.5  # bullish with support wick
                
                if is_bullish_pa:
                    atr_val = sum(highs[max(0,i-14):i+1])/min(14,i+1) - sum(lows[max(0,i-14):i+1])/min(14,i+1)
                    if atr_val <= 0: atr_val = c * 0.005
                    pos = {
                        'ep': c, 'atr': atr_val,
                        'sl': c - atr_val * 1.5,
                        'tp1': c + atr_val * 2.0,
                    }
    
    # Count trades
    wins = sum(1 for t in trades_long if t['pnl'] > 0)
    wr = (wins / len(trades_long) * 100) if trades_long else 0
    avg_pnl = sum(t['pnl'] for t in trades_long) / len(trades_long) if trades_long else 0
    total_pnl = sum(t['pnl'] for t in trades_long)
    
    # Score
    score = 0
    if len(trades_long) >= 5: score += 20
    elif len(trades_long) >= 3: score += 10
    if wr >= 60: score += 30
    elif wr >= 45: score += 15
    if avg_pnl > 0: score += 20
    if total_pnl > 0: score += 20
    if len(trades_long) > 0 and max(t['pnl'] for t in trades_long) > 5: score += 10
    
    flag = '🔥' if score >= 70 else ('✅' if score >= 50 else ('🟡' if score >= 30 else '❌'))
    
    print(f'{flag} {sym:16s} MA方向: 多{bullish}({bullish*100//max(total,1)}%) 空{bearish}({bearish*100//max(total,1)}%) | 交易:{len(trades_long)}T WR:{wr:.0f}% 均PnL:{avg_pnl:+.1f}% 总PnL:{total_pnl:+.1f}% 评分:{score}')

con.close()
