"""Get US overnight + A-share pre-market data for pre-market prediction."""
import yfinance as yf
import pandas as pd
import json, sys

# US ETFs proxy for indices
us_tickers = ["SPY", "QQQ", "DIA"]
# US holdings
us_holdings = ["NVDA", "AVGO", "TSLA", "MSFT", "GOOGL"]
# HK holdings
hk_tickers = ["0700.HK", "9988.HK", "3032.HK"]

all_us = us_tickers + us_holdings

try:
    data = yf.download(all_us, period="5d", progress=False)
except Exception as e:
    print(f"ERROR: yfinance download failed: {e}")
    sys.exit(1)

results = {}

for tkr in all_us:
    if isinstance(data.columns, pd.MultiIndex):
        try:
            close_col = ('Close', tkr)
            if close_col not in data.columns:
                results[tkr] = {"error": "no close col", "available_cols": [str(c) for c in data.columns]}
                continue
            closes = data[close_col].dropna()
        except Exception as e:
            results[tkr] = {"error": str(e)}
            continue
    else:
        closes = data['Close'].dropna()
    
    if len(closes) < 2:
        results[tkr] = {"error": f"only {len(closes)} data points"}
        continue
    
    prev_close = float(closes.iloc[-2])
    latest_close = float(closes.iloc[-1])
    chg_pct = round((latest_close / prev_close - 1) * 100, 2)
    
    results[tkr] = {
        "prev_close": round(prev_close, 2),
        "latest_close": round(latest_close, 2),
        "chg_pct": chg_pct
    }

# Also get HK data
try:
    hk_data = yf.download(hk_tickers, period="5d", progress=False)
    for tkr in hk_tickers:
        if isinstance(hk_data.columns, pd.MultiIndex):
            close_col = ('Close', tkr)
            if close_col not in hk_data.columns:
                results[tkr] = {"error": "no close col"}
                continue
            closes = hk_data[close_col].dropna()
        else:
            closes = hk_data['Close'].dropna()
        
        if len(closes) >= 2:
            results[tkr] = {
                "prev_close": round(float(closes.iloc[-2]), 2),
                "latest_close": round(float(closes.iloc[-1]), 2),
                "chg_pct": round((float(closes.iloc[-1]) / float(closes.iloc[-2]) - 1) * 100, 2)
            }
except Exception as e:
    results["hk_error"] = str(e)

print(json.dumps(results, indent=2))
