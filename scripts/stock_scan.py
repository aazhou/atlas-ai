
import yfinance as yf
import pandas as pd
import numpy as np
import json

# Stocks to check across 3 directions
stocks = {
    "消费-白酒": ["600519.SS", "000858.SZ", "600809.SS"],
    "消费-食品": ["600887.SS", "603288.SS", "002568.SZ"],
    "周期-工业金属": ["601899.SS", "600362.SS", "000630.SZ"],
    "中药": ["600436.SS", "000538.SZ", "600085.SS"],
    "医药生物": ["300760.SZ", "300015.SZ", "603259.SS"],
}

def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

for sector, tickers in stocks.items():
    print(f"\n{'='*60}")
    print(f"  {sector}")
    print(f"{'='*60}")
    
    for t in tickers:
        try:
            df = yf.download(t, period='60d', progress=False)
            if df.empty:
                print(f"  {t}: 无数据")
                continue
            
            # Handle MultiIndex
            if isinstance(df.columns, pd.MultiIndex):
                close = df[('Close', t)]
            else:
                close = df['Close']
            
            close = close.dropna()
            if len(close) < 20:
                print(f"  {t}: 数据不足")
                continue
            
            latest = close.iloc[-1]
            ma20 = close.rolling(20).mean().iloc[-1]
            ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else None
            
            # Position in 20-day range
            high20 = close.tail(20).max()
            low20 = close.tail(20).min()
            pos20 = (latest - low20) / (high20 - low20) * 100 if high20 != low20 else 50
            
            # Position in 60-day range
            high60 = close.tail(60).max() if len(close) >= 60 else high20
            low60 = close.tail(60).min() if len(close) >= 60 else low20
            pos60 = (latest - low60) / (high60 - low60) * 100 if high60 != low60 else 50
            
            # RSI
            rsi = calc_rsi(close).iloc[-1]
            
            # MACD
            ema12 = close.ewm(span=12).mean()
            ema26 = close.ewm(span=26).mean()
            macd = ema12 - ema26
            signal = macd.ewm(span=9).mean()
            macd_hist = macd.iloc[-1] - signal.iloc[-1]
            macd_status = "金叉" if macd.iloc[-1] > signal.iloc[-1] else "死叉"
            
            # 5-day change
            chg5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) >= 6 else 0
            
            # 20-day change
            chg20d = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) >= 21 else 0
            
            # Volume check (last 5 days vs 20-day avg)
            if 'Volume' in df.columns or isinstance(df.columns, pd.MultiIndex):
                if isinstance(df.columns, pd.MultiIndex):
                    vol = df[('Volume', t)].dropna()
                else:
                    vol = df['Volume'].dropna()
                vol_ratio = vol.iloc[-1] / vol.tail(20).mean() if len(vol) >= 20 else 1
            else:
                vol_ratio = 1
            
            # Check if above MA20/MA60
            above_ma20 = "✓" if latest > ma20 else "✗"
            above_ma60 = "✓" if ma60 and latest > ma60 else ("✗" if ma60 else "N/A")
            
            print(f"  {t}: 现价{latest:.2f} | RSI{rsi:.0f} | {macd_status}")
            print(f"        20日区间{pos20:.0f}% | 60日区间{pos60:.0f}%")
            print(f"        MA20={ma20:.2f}({above_ma20}) | MA60={ma60:.2f}({above_ma60})" if ma60 else f"        MA20={ma20:.2f}({above_ma20})")
            print(f"        5日涨跌{chg5d:+.1f}% | 20日涨跌{chg20d:+.1f}% | 量比{vol_ratio:.1f}")
            
        except Exception as e:
            print(f"  {t}: 错误 - {e}")

print("\n\nDone.")
