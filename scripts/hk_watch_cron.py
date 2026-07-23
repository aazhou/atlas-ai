"""港股盯盘脚本 - cron 版"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import json
import yfinance as yf
import numpy as np
from datetime import datetime, date

# 实时价（已从 qt.gtimg.cn 获取）
realtime = {
    "0700": {"name": "腾讯", "price": 447.0, "prev_close": 440.6, "chg": 1.45},
    "9988": {"name": "阿里", "price": 113.7, "prev_close": 113.6, "chg": 0.09},
    "3032": {"name": "恒生科技ETF", "price": 4.666, "prev_close": 4.666, "chg": 0.00},
}

def compute_rsi(closes, period=14):
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:]) if len(gains) >= period else np.mean(gains)
    avg_loss = np.mean(losses[-period:]) if len(losses) >= period else np.mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - 100 / (1 + rs))

def compute_macd(closes):
    ema12 = np.array(closes)
    ema26 = np.array(closes)
    # Simple EMA
    alpha12 = 2/13
    alpha26 = 2/27
    for i in range(1, len(ema12)):
        ema12[i] = closes[i] * alpha12 + ema12[i-1] * (1-alpha12)
    for i in range(1, len(ema26)):
        ema26[i] = closes[i] * alpha26 + ema26[i-1] * (1-alpha26)
    dif = ema12 - ema26
    dea = np.zeros_like(dif)
    for i in range(1, len(dif)):
        dea[i] = dif[i] * (2/10) + dea[i-1] * (1 - 2/10)
    macd_bar = 2 * (dif - dea)
    return dif[-1], dea[-1], macd_bar[-1], dif[-2] if len(dif) > 1 else 0, dea[-2] if len(dea) > 1 else 0

def compute_ma(closes, period):
    if len(closes) < period:
        return None
    return float(np.mean(closes[-period:]))

def compute_bollinger(closes, period=20):
    if len(closes) < period:
        return None, None, None
    ma = np.mean(closes[-period:])
    std = np.std(closes[-period:])
    return float(ma), float(ma + 2*std), float(ma - 2*std)

# Ticker mapping
tickers = {
    "0700": "0700.HK",
    "9988": "9988.HK",
    "3032": "3032.HK",
}

results = {}
all_outputs = []

# 恒指
try:
    hsi = yf.Ticker("^HSI")
    hsi_hist = hsi.history(period="60d", auto_adjust=False)
    if len(hsi_hist) >= 1:
        hsi_last = hsi_hist['Close'].dropna().iloc[-1]
        hsi_prev = hsi_hist['Close'].dropna().iloc[-2] if len(hsi_hist) >= 2 else hsi_last
        hsi_chg = float((hsi_last / hsi_prev - 1) * 100)
        hsi_close = float(hsi_last)
        # 20日位置
        hsi_high20 = float(hsi_hist['High'].dropna().iloc[-20:].max())
        hsi_low20 = float(hsi_hist['Low'].dropna().iloc[-20:].min())
        hsi_pos20 = float((hsi_close - hsi_low20) / (hsi_high20 - hsi_low20) * 100) if hsi_high20 != hsi_low20 else 50
        results['hsi'] = f"恒指 {hsi_close:.0f}（昨收 {hsi_chg:+.1f}%），20日位置 {hsi_pos20:.0f}%"
        all_outputs.append(f"**大势：** 恒指昨收 {hsi_close:.0f}（{hsi_chg:+.1f}%），20日区间 {hsi_pos20:.0f}% 分位")
except Exception as e:
    all_outputs.append(f"**大势：** 恒指数据获取失败 ({e})")

# 逐只分析
for code, yf_code in tickers.items():
    info = realtime[code]
    try:
        tk = yf.Ticker(yf_code)
        hist = tk.history(period="60d", auto_adjust=False)
        if len(hist) < 20:
            all_outputs.append(f"**{info['name']} {info['price']}（{info['chg']:+.1f}%）：** K线数据不足")
            continue

        closes = hist['Close'].dropna().values
        volumes = hist['Volume'].dropna().values
        highs = hist['High'].dropna().values
        lows = hist['Low'].dropna().values

        if len(closes) < 20:
            all_outputs.append(f"**{info['name']} {info['price']}（{info['chg']:+.1f}%）：** K线数据不足")
            continue

        # RSI
        rsi = compute_rsi(closes, 14)
        # MACD
        dif, dea, bar, dif_p, dea_p = compute_macd(closes)
        # MA
        ma5 = compute_ma(closes, 5)
        ma10 = compute_ma(closes, 10)
        ma20 = compute_ma(closes, 20)
        ma60 = compute_ma(closes, 60) if len(closes) >= 60 else None
        # Bollinger
        bb_mid, bb_upper, bb_lower = compute_bollinger(closes, 20)
        # 20日位置
        high20 = float(np.max(highs[-20:]))
        low20 = float(np.min(lows[-20:]))
        pos20 = float((info['price'] - low20) / (high20 - low20) * 100) if high20 != low20 else 50
        # 量比（最近5日均量）
        avg_vol5 = float(np.mean(volumes[-6:-1])) if len(volumes) >= 6 else float(np.mean(volumes[-5:]))
        latest_vol = float(volumes[-1])
        vol_ratio = float(latest_vol / avg_vol5) if avg_vol5 > 0 else 1.0

        # K线形态分析（最近3根）
        signals = []
        
        # 最近3根K线
        latest_open = float(hist['Open'].dropna().iloc[-1])
        latest_close = closes[-1]
        latest_high = float(highs[-1])
        latest_low = float(lows[-1])
        
        body = abs(latest_close - latest_open)
        upper_shadow = latest_high - max(latest_open, latest_close)
        lower_shadow = min(latest_open, latest_close) - latest_low
        total_range = latest_high - latest_low

        # 射击之星：上影线 >= 实体2倍，在上涨趋势高位
        if upper_shadow >= body * 2 and body > 0 and pos20 > 70:
            signals.append("🔴 射击之星顶部信号")
        # 锤子线：下影线 >= 实体2倍，在下跌趋势低位
        if lower_shadow >= body * 2 and body > 0 and pos20 < 30:
            signals.append("🟢 锤子线底部信号")
        # 十字星
        if body < total_range * 0.1 and total_range > 0:
            signals.append("⚪ 十字星变盘前兆")
        # 乌云盖顶
        if len(closes) >= 2:
            prev_open = float(hist['Open'].dropna().iloc[-2])
            prev_close = closes[-2]
            if prev_close > prev_open and latest_open > prev_close and latest_close < prev_close and latest_close > prev_open:
                signals.append("🔴 乌云盖顶")
        # 吞没
        if len(closes) >= 2:
            prev_open = float(hist['Open'].dropna().iloc[-2])
            prev_close = closes[-2]
            prev_body = abs(prev_close - prev_open)
            if prev_close < prev_open and latest_close > latest_open and latest_open < prev_close and latest_close > prev_open:
                signals.append("🟢 看涨吞没")

        # 量价关系
        if latest_close > closes[-2] and vol_ratio > 1.3:
            signals.append("📈 价涨量增（健康）")
        elif latest_close > closes[-2] and vol_ratio < 0.7:
            signals.append("⚠️ 价涨量缩（乏力）")
        elif latest_close < closes[-2] and vol_ratio > 1.3:
            signals.append("🚨 价跌量增（出货）")

        # MA结构
        if ma5 and ma10 and ma20:
            if ma5 > ma10 > ma20:
                signals.append("✅ MA多头排列")
            elif ma5 < ma10 < ma20:
                signals.append("🔴 MA空头排列")

        # MACD信号
        if dif > dea and dif_p <= dea_p:
            signals.append("🟢 MACD金叉")
        elif dif < dea and dif_p >= dea_p:
            signals.append("🔴 MACD死叉")

        # BB位置
        if bb_upper and bb_lower:
            if info['price'] > bb_upper:
                signals.append("⚠️ 突破布林上轨（超买）")
            elif info['price'] < bb_lower:
                signals.append("🟢 跌破布林下轨（超卖）")

        # 组装输出
        signal_str = " | ".join(signals) if signals else "无明显信号"
        
        msg = f"**{info['name']} {info['price']}（{info['chg']:+.1f}%）：** {signal_str}"
        msg += f"\n  RSI {rsi:.0f} | MACD bar {bar:+.2f} | 量比 {vol_ratio:.1f} | 20日位置 {pos20:.0f}%"
        if ma20:
            msg += f" | MA20 {ma20:.1f}"
        
        all_outputs.append(msg)

    except Exception as e:
        all_outputs.append(f"**{info['name']} {info['price']}（{info['chg']:+.1f}%）：** 数据异常 ({e})")

# 只输出有信号的
has_signal = False
for line in all_outputs:
    if any(s in line for s in ["🔴", "🟢", "🚨", "⚠️", "⚪"]):
        has_signal = True
        break

# 大涨大跌检查
for code, info in realtime.items():
    if abs(info['chg']) >= 3:
        has_signal = True

if has_signal or True:  # 初次盯盘总输出
    print("## 🇭🇰 港股盯盘 " + datetime.now().strftime("%H:%M"))
    for line in all_outputs:
        print(line)
else:
    print("[SILENT]")
