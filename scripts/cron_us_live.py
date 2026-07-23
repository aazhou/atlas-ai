#!/usr/bin/env python3
"""
cron_us_live.py — 美股实时数据采集(交易时段)
北京时间 22:00-05:00，每5分钟
产出: data/us/live.json
"""
import json, os, sys
from datetime import datetime

# 判断美股交易时段
now = datetime.now()
h = now.hour
is_summer = now.month > 3 and now.month < 11  # 夏令时粗略判断
if is_summer:
    if not (21 <= h or h < 5): sys.exit(0)  # 夏令时 21:30-04:00
else:
    if not (22 <= h or h < 6): sys.exit(0)  # 冬令时 22:30-05:00

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

try:
    import yfinance as yf
    import pandas as pd
    
    data = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "indices": [], "sectors": {}, "opportunities": []}
    
    # Indices
    for sym, name in [("SPY","SPY"), ("QQQ","QQQ"), ("DIA","DIA"), ("^VIX","VIX"), ("^TNX","10Y")]:
        try:
            tk = yf.Ticker(sym)
            hist = tk.history(period="1d", interval="5m")
            if len(hist) > 0:
                price = float(hist['Close'].iloc[-1])
                prev = float(hist['Open'].iloc[0])
                chg = round((price/prev - 1)*100, 2)
                data["indices"].append({"symbol": name, "price": round(price,2), "chg_pct": chg})
        except: pass
    
    # Sector ETFs
    sectors_etf = {
        "XLK": "科技", "XLF": "金融", "XLE": "能源", "XLV": "医疗",
        "XLI": "工业", "XLY": "消费", "XLU": "公用事业", "XLB": "材料", "XLRE": "房地产"
    }
    for sym, name in sectors_etf.items():
        try:
            tk = yf.Ticker(sym)
            hist = tk.history(period="1d", interval="5m")
            if len(hist) > 0:
                price = float(hist['Close'].iloc[-1])
                prev = float(hist['Open'].iloc[0])
                chg = round((price/prev - 1)*100, 2)
                data["sectors"][name] = {"price": round(price,2), "chg_pct": chg}
        except: pass
    
    # Opportunities
    # 板块偏离检测
    if "XLK" in data.get("sectors",{}) and "XLE" in data.get("sectors",{}):
        tech = data["sectors"]["XLK"]["chg_pct"]
        energy = data["sectors"]["XLE"]["chg_pct"]
        spread = tech - energy
        if abs(spread) > 1:
            direction = "科技强于能源" if spread > 0 else "能源强于科技"
            data["opportunities"].append({
                "type": "板块轮动",
                "signal": f"{direction} 偏离{abs(spread):.1f}%",
                "action": f"关注{'XLK/QQQ' if spread>0 else 'XLE/能源股'}短线机会"
            })
    
    # 数据保存
    os.makedirs(os.path.join(DATA, "us"), exist_ok=True)
    with open(os.path.join(DATA, "us", "live.json"), "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[us_live] {len(data['indices'])} indices, {len(data['sectors'])} sectors, {len(data['opportunities'])} opps")
    
except ImportError:
    print("[us_live] yfinance not available, skipping")
except Exception as e:
    print(f"[us_live] error: {e}")
