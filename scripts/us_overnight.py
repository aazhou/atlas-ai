import yfinance as yf
import pandas as pd

results = {}
for sym, label in [('SPY','S&P500'), ('QQQ','Nasdaq'), ('DIA','Dow'), ('NVDA','NVDA'), ('AVGO','AVGO'), ('TSLA','TSLA'), ('MSFT','MSFT'), ('GOOGL','GOOGL')]:
    try:
        df = yf.download(sym, period='3d', progress=False)
        if df.empty:
            continue
        # Handle MultiIndex
        if isinstance(df.columns, pd.MultiIndex):
            close_col = ('Close', sym)
        else:
            close_col = 'Close'
        
        closes = df[close_col].dropna()
        if len(closes) >= 2:
            c0 = float(closes.iloc[-2])
            c1 = float(closes.iloc[-1])
            chg = (c1/c0 - 1)*100
            results[label] = {'prev': c0, 'last': c1, 'chg': chg}
    except Exception as e:
        print(f"{sym}: Error - {e}")

for label, d in results.items():
    arrow = "🔺" if d['chg'] > 0 else "🔻" if d['chg'] < 0 else "➡️"
    print(f"{arrow} {label}: {d['last']:.2f} ({d['chg']:+.2f}%)")
