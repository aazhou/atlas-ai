#!/usr/bin/env python
"""Portfolio update: fetch yfinance tech indicators for holdings + watchlist"""
import yfinance as yf
import numpy as np
import pandas as pd
import json, sys

TICKERS = {
    "300236": "300236.SZ",
    "300019": "300019.SZ",
    "688099": "688099.SS",
    "002475": "002475.SZ",
    "000963": "000963.SZ",
    "601138": "601138.SS",
    "002472": "002472.SZ",
    "605111": "605111.SS",
    "300759": "300759.SZ",
    "605133": "605133.SS",
}

results = {}

for code, ticker in TICKERS.items():
    try:
        df = yf.download(ticker, period='60d', progress=False)
        if df.empty or len(df) < 20:
            results[code] = {"error": f"no data or <20 rows (got {len(df)})"}
            continue
        
        # Handle MultiIndex columns (yfinance single-ticker returns tuple columns)
        if isinstance(df.columns, pd.MultiIndex):
            close_col = [c for c in df.columns if c[0] == 'Close'][0]
            volume_col = [c for c in df.columns if c[0] == 'Volume'][0] if any(c[0] == 'Volume' for c in df.columns) else None
            close = df[close_col].values
            volume = df[volume_col].values if volume_col else None
        else:
            close = df['Close'].values
            volume = df['Volume'].values if 'Volume' in df.columns else None
        
        # Drop NaN
        valid_mask = ~np.isnan(close)
        close = close[valid_mask]
        if volume is not None:
            volume = volume[valid_mask]
        
        if len(close) < 20:
            results[code] = {"error": f"not enough valid rows ({len(close)})"}
            continue
        
        latest_close = float(close[-1])
        
        # RSI-14
        delta = np.diff(close)
        gains = np.where(delta > 0, delta, 0)
        losses = np.where(delta < 0, -delta, 0)
        avg_gain = float(np.mean(gains[-14:]))
        avg_loss = float(np.mean(losses[-14:]))
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = float(100 - 100 / (1 + rs))
        
        # MA20, MA60
        ma20 = float(np.mean(close[-20:]))
        ma60 = float(np.mean(close[-min(60, len(close)):]))
        
        # MACD
        ema12 = pd.Series(close).ewm(span=12, adjust=False).mean()
        ema26 = pd.Series(close).ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - signal_line
        macd_golden = bool(float(macd_line.iloc[-1]) > float(signal_line.iloc[-1]))
        hist_latest = float(macd_hist.iloc[-1])
        
        # Volume ratio
        if volume is not None and len(volume) >= 6:
            avg_vol5 = float(np.mean(volume[-6:-1]))
            vol_ratio = float(volume[-1] / avg_vol5) if avg_vol5 > 0 else 1.0
        else:
            vol_ratio = 1.0
        
        # BB(20,2)
        bb_mid = ma20
        bb_std = float(np.std(close[-20:]))
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_pos = float((latest_close - bb_lower) / (bb_upper - bb_lower)) if (bb_upper - bb_lower) > 0 else 0.5
        
        # 20d position
        low20 = float(np.min(close[-20:]))
        high20 = float(np.max(close[-20:]))
        pos20 = float((latest_close - low20) / (high20 - low20) * 100) if (high20 - low20) > 0 else 50
        
        # PE
        try:
            info = yf.Ticker(ticker).info
            pe = float(info.get('trailingPE', 0) or info.get('forwardPE', 0) or 0)
        except:
            pe = 0
        
        results[code] = {
            "close": latest_close,
            "rsi": round(rsi, 1),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "macd_golden": macd_golden,
            "macd_hist": round(hist_latest, 4),
            "vol_ratio": round(vol_ratio, 2),
            "bb_position": round(bb_pos, 2),
            "pos_20d": round(pos20, 1),
            "pe": round(pe, 1),
            "bb_lower": round(bb_lower, 2),
            "bb_upper": round(bb_upper, 2),
        }
    except Exception as e:
        results[code] = {"error": str(e)}

print(json.dumps(results, ensure_ascii=False, indent=2))
