"""Get overnight US market data - working version."""
import yfinance as yf
import json

tickers = [
    ('SPY', '标普500'), ('QQQ', '纳斯达克100'), ('DIA', '道指'),
    ('NVDA', '英伟达'), ('AVGO', '博通'), ('TSLA', '特斯拉'),
    ('MSFT', '微软'), ('GOOGL', '谷歌'), ('META', 'Meta'),
    ('SMH', '半导体ETF'),
]

results = {}
for ticker, name in tickers:
    try:
        df = yf.download(ticker, period='5d', progress=False)
        # squeeze to Series
        close = df['Close'].squeeze()
        close = close.dropna()
        if len(close) >= 2:
            prev = close.iloc[-2]
            curr = close.iloc[-1]
            chg = round((curr / prev - 1) * 100, 2)
            results[ticker] = {'name': name, 'price': round(float(curr), 2), 'chg_pct': chg}
        else:
            results[ticker] = {'name': name, 'error': f'only {len(close)} pts'}
    except Exception as e:
        results[ticker] = {'name': name, 'error': str(e)[:80]}

print(json.dumps(results, indent=2, ensure_ascii=False))
