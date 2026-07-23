"""Get overnight US market data - v4 debug."""
import yfinance as yf
import json

tickers = [('SPY', '标普500'), ('QQQ', '纳斯达克100'), ('DIA', '道指')]

for ticker, name in tickers:
    try:
        df = yf.download(ticker, period='5d', progress=False)
        c = df['Close']
        print(f"{ticker}: type={type(c)}, shape={c.shape if hasattr(c,'shape') else 'N/A'}, columns={c.columns.tolist() if hasattr(c,'columns') else 'N/A'}")
        print(f"  iloc[-1]={c.iloc[-1]}, type={type(c.iloc[-1])}")
        # Try squeeze
        s = c.squeeze()
        print(f"  squeezed type={type(s)}, val={s.iloc[-1] if hasattr(s,'iloc') else s}")
    except Exception as e:
        print(f"{ticker}: ERROR: {e}")
