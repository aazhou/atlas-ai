
import yfinance as yf, pandas as pd, numpy as np, json, sys

codes = ['300236.SZ','688099.SS','002475.SZ','000963.SZ',
         '603662.SS','605133.SS','002156.SZ','605111.SS','300373.SZ','002472.SZ']

results = {}
for ticker in codes:
    try:
        df = yf.download(ticker, period='60d', progress=False)
        if df.empty:
            results[ticker] = {'error': 'no data'}
            continue

        # Handle MultiIndex columns
        if isinstance(df.columns, pd.MultiIndex):
            close_col = ('Close', ticker)
            volume_col = ('Volume', ticker)
        else:
            close_col = 'Close'
            volume_col = 'Volume'

        closes = df[close_col].dropna().values
        volumes = df[volume_col].dropna().values

        if len(closes) < 20:
            results[ticker] = {'error': 'not enough data'}
            continue

        # RSI-14
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-14:])
        avg_loss = np.mean(losses[-14:])
        rsi = 100 - (100/(1 + avg_gain/avg_loss)) if avg_loss > 0 else 100

        # MA20, MA60
        ma20 = float(np.mean(closes[-20:]))
        ma60 = float(np.mean(closes[-60:])) if len(closes) >= 60 else float(np.mean(closes))

        # MACD
        ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().values
        ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().values
        dif = ema12 - ema26
        dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
        macd_bar = 2*(dif - dea)
        macd_signal = '金叉' if (len(macd_bar)>=2 and macd_bar[-2] <= 0 and macd_bar[-1] > 0) else \
                      '死叉' if (len(macd_bar)>=2 and macd_bar[-2] >= 0 and macd_bar[-1] < 0) else \
                      '多头' if macd_bar[-1] > 0 else '空头'

        # Bollinger Bands
        bb_mid = float(np.mean(closes[-20:]))
        bb_std = float(np.std(closes[-20:]))
        bb_upper = bb_mid + 2*bb_std
        bb_lower = bb_mid - 2*bb_std
        last_close = float(closes[-1])
        bb_pos = '上轨' if last_close > bb_upper else '下轨' if last_close < bb_lower else '中轨'

        # Volume ratio (last 5 vs 20)
        avg_vol_5 = float(np.mean(volumes[-5:])) if len(volumes)>=5 else 0
        avg_vol_20 = float(np.mean(volumes[-20:])) if len(volumes)>=20 else avg_vol_5
        vol_ratio = round(avg_vol_5/avg_vol_20, 2) if avg_vol_20>0 else 1.0

        # Position in 20-day range
        h20 = float(np.max(closes[-20:]))
        l20 = float(np.min(closes[-20:]))
        pos_20d = round((last_close-l20)/(h20-l20)*100, 1) if (h20-l20)>0 else 50

        # High/low points trend (last 5 days)
        highs = closes[-5:]
        lows = closes[-5:]
        trend = '高点抬高' if all(highs[i] <= highs[i+1] for i in range(len(highs)-1)) else \
                '低点降低' if all(lows[i] >= lows[i+1] for i in range(len(lows)-1)) else '震荡'

        results[ticker] = {
            'rsi': round(float(rsi), 1),
            'ma20': round(ma20,2), 'ma60': round(ma60,2),
            'macd': macd_signal, 'macd_bar': round(float(macd_bar[-1]),4),
            'bb': bb_pos, 'bb_upper': round(bb_upper,2), 'bb_lower': round(bb_lower,2),
            'vol_ratio': vol_ratio, 'pos_20d': pos_20d,
            'trend': trend, 'last_close': last_close,
        }
    except Exception as e:
        results[ticker] = {'error': str(e)}

print("YF_RESULT:" + json.dumps(results, ensure_ascii=False))
