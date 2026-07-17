import json, sys
sys.path.insert(0, '/c/Python314/Lib/site-packages')
import yfinance as yf
import pandas as pd
import numpy as np

tickers = {
    '300236': '300236.SZ',
    '002475': '002475.SZ',
    '002472': '002472.SZ',
    '688099': '688099.SS',
    '000963': '000963.SZ',
}

results = {}
for code, ticker in tickers.items():
    try:
        df = yf.download(ticker, period='60d', progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            close = df[('Close', ticker)]
            high = df[('High', ticker)]
            low = df[('Low', ticker)]
            volume = df[('Volume', ticker)]
        else:
            close = df['Close']
            high = df['High']
            low = df['Low']
            volume = df['Volume']
        
        close = close.dropna()
        if len(close) < 20:
            results[code] = {'error': f'insufficient data: {len(close)}'}
            continue
        
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal = macd_line.ewm(span=9).mean()
        macd_hist = macd_line - signal
        
        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        
        high20 = high.rolling(20).max()
        low20 = low.rolling(20).min()
        pos20 = (close - low20) / (high20 - low20)
        
        vol_ma5 = volume.rolling(5).mean()
        vol_ratio = volume / vol_ma5
        
        # Check last few MACD hist values for crossover detection
        macd_hist_vals = [float(macd_hist.iloc[-i]) for i in range(1, min(8, len(macd_hist))+1)]
        macd_line_vals = [float(macd_line.iloc[-i]) for i in range(1, min(8, len(macd_line))+1)]
        
        # K-line shape analysis
        last_body = float(close.iloc[-1]) - float(close.iloc[-2])  # today body
        last_upper = float(high.iloc[-1]) - max(float(close.iloc[-1]), float(close.iloc[-2]))
        last_lower = min(float(close.iloc[-1]), float(close.iloc[-2])) - float(low.iloc[-1])
        
        last = {
            'close': round(float(close.iloc[-1]), 2),
            'rsi': round(float(rsi.iloc[-1]), 1),
            'macd_line': round(float(macd_line.iloc[-1]), 3),
            'macd_signal': round(float(signal.iloc[-1]), 3),
            'macd_hist': round(float(macd_hist.iloc[-1]), 3),
            'macd_trend': 'green_rising' if macd_hist_vals[0] > macd_hist_vals[1] > 0 else 
                          'green_shrinking' if 0 < macd_hist_vals[0] < macd_hist_vals[1] else
                          'red_shrinking' if macd_hist_vals[0] < 0 and macd_hist_vals[0] > macd_hist_vals[1] else
                          'red_expanding' if macd_hist_vals[0] < 0 and macd_hist_vals[0] < macd_hist_vals[1] else 'mixed',
            'ma5': round(float(ma5.iloc[-1]), 2),
            'ma10': round(float(ma10.iloc[-1]), 2),
            'ma20': round(float(ma20.iloc[-1]), 2),
            'ma60': round(float(ma60.iloc[-1]), 2),
            'bb_upper': round(float(bb_upper.iloc[-1]), 2),
            'bb_mid': round(float(bb_mid.iloc[-1]), 2),
            'bb_lower': round(float(bb_lower.iloc[-1]), 2),
            'pos_20d': round(float(pos20.iloc[-1]) * 100, 1),
            'vol_ratio': round(float(vol_ratio.iloc[-1]), 2),
            'k_body': round(last_body, 2),
            'k_upper_shadow': round(last_upper, 2),
            'k_lower_shadow': round(last_lower, 2),
            'close_prev1': round(float(close.iloc[-2]), 2),
            'close_prev2': round(float(close.iloc[-3]), 2),
            'high_last': round(float(high.iloc[-1]), 2),
            'low_last': round(float(low.iloc[-1]), 2),
            'n_days': len(close),
        }
        
        results[code] = last
    except Exception as e:
        results[code] = {'error': str(e)}

print(json.dumps(results, ensure_ascii=False))
