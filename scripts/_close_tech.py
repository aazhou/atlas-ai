"""收盘技术指标计算 - 7/20"""
import json, sys
import numpy as np

TICKERS = {
    "002475": "002475.SZ",   # 立讯精密
    "300236": "300236.SZ",   # 上海新阳
    "002472": "002472.SZ",   # 双环传动
    "688099": "688099.SS",   # 晶晨股份
    "000963": "000963.SZ",   # 华东医药
}

def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    # Use Wilder's smoothing for remaining points
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_val = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_val = 100 - (100 / (1 + rs))
    return round(rsi_val, 1) if 'rsi_val' in dir() else round(rsi, 1)

def compute_macd(closes):
    if len(closes) < 26:
        return None, None
    ema12 = closes[-1]
    ema26 = closes[-1]
    multiplier12 = 2 / 13
    multiplier26 = 2 / 27
    ema12_vals = [closes[0]]
    ema26_vals = [closes[0]]
    for price in closes[1:]:
        ema12_vals.append(price * multiplier12 + ema12_vals[-1] * (1 - multiplier12))
        ema26_vals.append(price * multiplier26 + ema26_vals[-1] * (1 - multiplier26))
    dif = np.array(ema12_vals) - np.array(ema26_vals)
    dea = [dif[0]]
    multiplier_dea = 2 / 10
    for d in dif[1:]:
        dea.append(d * multiplier_dea + dea[-1] * (1 - multiplier_dea))
    dea = np.array(dea)
    macd_bar = 2 * (dif - dea)
    # Determine gold/dead cross
    if len(dif) >= 3:
        if dif[-1] > dea[-1] and dif[-2] <= dea[-2]:
            status = "金叉"
        elif dif[-1] < dea[-1] and dif[-2] >= dea[-2]:
            status = "死叉"
        elif dif[-1] > dea[-1]:
            status = "金叉持续"
        else:
            status = "死叉扩大"
    else:
        status = "数据不足"
    return round(float(macd_bar[-1]), 4), status

def compute_ma(closes, period):
    if len(closes) < period:
        return None
    return round(float(np.mean(closes[-period:])), 2)

def compute_bollinger(closes, period=20, std_mult=2):
    if len(closes) < period:
        return None, None, None, None
    ma = np.mean(closes[-period:])
    std = np.std(closes[-period:])
    upper = ma + std_mult * std
    lower = ma - std_mult * std
    current = closes[-1]
    if current >= upper:
        pos = "突破上轨"
    elif current <= lower:
        pos = "跌破下轨"
    elif current > ma:
        pos = "上半区"
    else:
        pos = "下半区"
    return round(float(upper), 2), round(float(ma), 2), round(float(lower), 2), pos

def compute_pos_20d(closes):
    if len(closes) < 20:
        return None
    high20 = max(closes[-20:])
    low20 = min(closes[-20:])
    current = closes[-1]
    if high20 == low20:
        return 50.0
    return round(float((current - low20) / (high20 - low20) * 100), 1)

def compute_vol_ratio(volumes):
    """量比 = 今日量 / 5日均量"""
    if len(volumes) < 6:
        return None
    today_vol = volumes[-1]
    avg5 = np.mean(volumes[-6:-1])
    if avg5 == 0:
        return 1.0
    return round(float(today_vol / avg5), 2)

try:
    import yfinance as yf
except ImportError:
    print(json.dumps({"error": "yfinance not installed"}, ensure_ascii=False))
    sys.exit(1)

results = {}

for code, ticker in TICKERS.items():
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="60d", auto_adjust=False)
        if df.empty:
            results[code] = {"error": "empty data"}
            continue
        
        closes = df['Close'].values.astype(float)
        volumes = df['Volume'].values.astype(float)
        
        # Filter NaN
        closes = closes[~np.isnan(closes)]
        volumes = volumes[~np.isnan(volumes)]
        
        if len(closes) < 20:
            results[code] = {"error": f"only {len(closes)} bars"}
            continue
        
        rsi = compute_rsi(closes)
        macd_bar, macd_status = compute_macd(closes)
        ma5 = compute_ma(closes, 5)
        ma10 = compute_ma(closes, 10)
        ma20 = compute_ma(closes, 20)
        ma60 = compute_ma(closes, 60) if len(closes) >= 60 else None
        bb_upper, bb_mid, bb_lower, bb_pos = compute_bollinger(closes)
        pos20 = compute_pos_20d(closes)
        vol_ratio = compute_vol_ratio(volumes)
        
        # Determine trend from MA structure
        if ma5 and ma10 and ma20 and ma60:
            if ma5 > ma10 > ma20 > ma60:
                trend = "多头排列"
            elif ma5 < ma10 < ma20 < ma60:
                trend = "空头排列"
            elif ma5 > ma10:
                trend = "短期偏多"
            elif ma5 < ma10:
                trend = "短期偏空"
            else:
                trend = "交织"
        else:
            trend = "数据不足"
        
        results[code] = {
            "rsi": rsi,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "ma60": ma60,
            "macd_bar": macd_bar,
            "macd": macd_status,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "bb_mid": bb_mid,
            "bb_pos": bb_pos,
            "pos_20d": pos20,
            "vol_ratio": vol_ratio,
            "trend": trend,
            "close_yf": round(float(closes[-1]), 2),
        }
        print(f"[{code}] RSI={rsi} MA20={ma20} MA60={ma60} MACD={macd_status} BB={bb_pos} Pos20={pos20}% Vol={vol_ratio}", flush=True)
        
    except Exception as e:
        results[code] = {"error": str(e)[:100]}
        print(f"[{code}] ERROR: {e}", flush=True)

print("\n=== JSON ===", flush=True)
print(json.dumps(results, ensure_ascii=False, indent=2))
