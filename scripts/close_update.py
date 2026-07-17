#!/usr/bin/env python3
"""收盘持仓分析 — 拉 yfinance 技术指标 + 生成 portfolio.json"""
import json, sys, re
from datetime import datetime

# --- Sina 数据解析 ---
sina_raw = '''
var hq_str_sz002475="立讯精密,61.000,61.580,58.050,61.500,57.090,58.040,58.050,143301667,8437769036.370,28700,58.040,27345,58.030,14200,58.020,43800,58.010,241000,58.000,145961,58.050,18700,58.060,7100,58.070,15700,58.080,3800,58.090,2026-07-17,15:35:00,00,D|54824|3182533.200";
var hq_str_sz300236="上海新阳,94.870,93.700,88.960,95.900,88.890,88.960,88.970,15492373,1438141129.760,100,88.960,400,88.950,700,88.940,100,88.930,100,88.910,1100,88.970,3900,88.980,4700,88.990,38800,89.000,2600,89.010,2026-07-17,15:34:45,00,D|5400|480384.000";
var hq_str_sz002472="双环传动,41.310,41.570,37.790,41.660,37.580,37.790,37.800,50091200,1958539795.270,56100,37.790,10900,37.780,4300,37.770,4400,37.760,7800,37.750,128800,37.800,68700,37.810,30200,37.820,3600,37.830,6300,37.840,2026-07-17,15:34:30,00,D|16500|623700.000";
var hq_str_sh688099="晶晨股份,97.970,97.990,87.390,100.480,85.420,87.390,87.400,25157293,2316933303.000,500,87.390,500,87.300,500,87.290,200,87.280,200,87.260,12243,87.400,760,87.460,300,87.470,6875,87.480,11866,87.490,2026-07-17,15:34:59,00,D|2800|244720.00";
var hq_str_sz000963="华东医药,31.640,31.960,30.100,31.900,29.930,30.100,30.110,37298500,1140556203.790,25200,30.100,9300,30.090,5800,30.080,15900,30.070,17400,30.060,28400,30.110,9100,30.120,5900,30.130,3500,30.140,18900,30.150,2026-07-17,15:34:45,00,D|18100|544810.000";
'''

sina_prices = {}
for line in sina_raw.strip().split('\n'):
    line = line.strip()
    if not line:
        continue
    m = re.search(r'var hq_str_(\w+)="(.*?)";', line)
    if not m:
        continue
    code_raw = m.group(1)  # sz002475 or sh688099
    code = code_raw[2:]  # 002475
    parts = m.group(2).split(',')
    try:
        name = parts[0]
        open_p = float(parts[1])
        prev_close = float(parts[2])
        price = float(parts[3])
        high = float(parts[4])
        low = float(parts[5])
        volume = int(parts[8])
        amount = float(parts[9])
        chg = round((price - prev_close) / prev_close * 100, 2)
        
        sina_prices[code] = {
            'name': name, 'code': code, 'price': price,
            'prev_close': prev_close, 'open': open_p,
            'high': high, 'low': low, 'chg': chg,
            'volume': volume, 'amount': amount
        }
    except Exception as e:
        print(f"Parse error for {code_raw}: {e}", file=sys.stderr)

print("=== Sina prices ===")
for code, d in sina_prices.items():
    print(f"{d['name']}({code}): 昨收{d['prev_close']} 现价{d['price']} 涨跌{d['chg']}% 高{d['high']} 低{d['low']}")

# --- yfinance 技术指标 ---
import pandas as pd
import numpy as np
try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed, skipping technical indicators", file=sys.stderr)
    sys.exit(0)

def compute_indicators(df):
    """从日线 DataFrame 计算技术指标"""
    if df is None or len(df) < 20:
        return None
    
    close = df['Close']
    high = df['High']
    low = df['Low']
    volume = df['Volume']
    
    # MA
    ma5 = close.rolling(5).mean().iloc[-1]
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else None
    
    # RSI-14
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(14).mean().iloc[-1]
    avg_loss = loss.rolling(14).mean().iloc[-1]
    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    
    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9).mean()
    macd_bar = (macd_line - signal_line).iloc[-1]
    macd_bar_prev = (macd_line - signal_line).iloc[-2]
    
    if macd_line.iloc[-1] > signal_line.iloc[-1]:
        macd_status = "金叉"
        if macd_bar > macd_bar_prev:
            macd_status += "扩大"
        else:
            macd_status += "收敛"
    else:
        macd_status = "死叉"
        if macd_bar < macd_bar_prev:
            macd_status += "扩大"
        else:
            macd_status += "收敛"
    
    # Bollinger Bands
    bb_mid = ma20
    bb_std = close.rolling(20).std().iloc[-1]
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    
    price_now = close.iloc[-1]
    if price_now >= bb_upper:
        bb_pos = "突破上轨"
    elif price_now <= bb_lower:
        bb_pos = "跌破下轨"
    elif price_now > bb_mid:
        bb_pos = "上半区"
    else:
        bb_pos = "下半区"
    
    # Volume ratio (vs 5-day avg)
    vol_avg5 = volume.rolling(5).mean().iloc[-1]
    vol_ratio = volume.iloc[-1] / vol_avg5 if vol_avg5 > 0 else 1.0
    
    # 20-day position
    low20 = low.rolling(20).min().iloc[-1]
    high20 = high.rolling(20).max().iloc[-1]
    pos_20d = (price_now - low20) / (high20 - low20) * 100 if high20 > low20 else 50
    
    # K-line patterns
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else None
    prev2 = df.iloc[-3] if len(df) >= 3 else None
    
    body = abs(last['Close'] - last['Open'])
    upper_shadow = last['High'] - max(last['Close'], last['Open'])
    lower_shadow = min(last['Close'], last['Open']) - last['Low']
    
    patterns = []
    
    # Hammer / Inverted hammer
    if body > 0 and lower_shadow >= body * 2 and pos_20d < 30:
        patterns.append("锤子线(底部)")
    if body > 0 and upper_shadow >= body * 2 and pos_20d > 70:
        patterns.append("射击之星(顶部)")
    
    return {
        'rsi': round(rsi, 1),
        'ma5': round(float(ma5), 2),
        'ma10': round(float(ma10), 2),
        'ma20': round(float(ma20), 2),
        'ma60': round(float(ma60), 2) if ma60 is not None else None,
        'macd': macd_status,
        'macd_bar': round(float(macd_bar), 3),
        'bb': bb_pos,
        'bb_upper': round(float(bb_upper), 2),
        'bb_lower': round(float(bb_lower), 2),
        'vol_ratio': round(float(vol_ratio), 2),
        'pos_20d': round(float(pos_20d), 1),
        'patterns': patterns,
    }

# 拉 yfinance 数据
tickers = {
    '002475.SZ': '立讯精密',
    '300236.SZ': '上海新阳',
    '002472.SZ': '双环传动',
    '688099.SS': '晶晨股份',
    '000963.SZ': '华东医药',
}

print("\n=== yfinance indicators ===")
for ticker, name in tickers.items():
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period='90d', auto_adjust=False)
        if hist is None or len(hist) < 20:
            print(f"{name}({ticker}): insufficient data ({len(hist) if hist is not None else 0} rows)")
            continue
        
        indic = compute_indicators(hist)
        if indic is None:
            print(f"{name}({ticker}): indicator computation failed")
            continue
        
        print(f"\n{name}({ticker}):")
        for k, v in indic.items():
            print(f"  {k}: {v}")
    except Exception as e:
        print(f"{name}({ticker}): ERROR - {e}", file=sys.stderr)

print("\nDone. Now write portfolio.json")
