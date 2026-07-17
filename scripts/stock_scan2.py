
import yfinance as yf
import pandas as pd
import numpy as np

stocks = {
    "元件/被动元件": ["300408.SZ", "002138.SZ", "000636.SZ"],
    "PCB": ["002463.SZ", "603228.SH", "300476.SZ"],
    "银行": ["600036.SS", "601166.SS", "000001.SZ"],
    "煤炭": ["601088.SS", "600188.SS", "601225.SS"],
    "铜/工业金属": ["603993.SS", "601168.SS", "002155.SZ"],
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
            
            if isinstance(df.columns, pd.MultiIndex):
                close = df[('Close', t)]
                vol = df[('Volume', t)] if ('Volume', t) in df.columns else None
            else:
                close = df['Close']
                vol = df['Volume'] if 'Volume' in df.columns else None
            
            close = close.dropna()
            if len(close) < 20:
                print(f"  {t}: 数据不足")
                continue
            
            latest = close.iloc[-1]
            ma20 = close.rolling(20).mean().iloc[-1]
            ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else None
            
            high20 = close.tail(20).max()
            low20 = close.tail(20).min()
            pos20 = (latest - low20) / (high20 - low20) * 100 if high20 != low20 else 50
            
            high60 = close.tail(60).max() if len(close) >= 60 else high20
            low60 = close.tail(60).min() if len(close) >= 60 else low20
            pos60 = (latest - low60) / (high60 - low60) * 100 if high60 != low60 else 50
            
            rsi = calc_rsi(close).iloc[-1]
            
            ema12 = close.ewm(span=12).mean()
            ema26 = close.ewm(span=26).mean()
            macd_v = ema12 - ema26
            signal = macd_v.ewm(span=9).mean()
            macd_status = "金叉" if macd_v.iloc[-1] > signal.iloc[-1] else "死叉"
            
            chg5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) >= 6 else 0
            chg20d = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) >= 21 else 0
            
            if vol is not None:
                vol = vol.dropna()
                vol_ratio = vol.iloc[-1] / vol.tail(20).mean() if len(vol) >= 20 else 1
            else:
                vol_ratio = 1
            
            above_ma20 = "✓" if latest > ma20 else "✗"
            above_ma60 = "✓" if ma60 and latest > ma60 else ("✗" if ma60 else "N/A")
            
            # 底部确认信号
            signals = []
            if 35 <= rsi <= 55:
                signals.append("RSI底部区")
            if pos20 < 25:
                signals.append("20日低位")
            if macd_status == "金叉" and pos20 < 30:
                signals.append("MACD低位金叉⭐")
            if latest < ma20 and pos20 < 20:
                signals.append("超跌待反弹")
            
            signal_str = " | ".join(signals) if signals else "—"
            
            print(f"  {t}: {latest:.2f} | RSI{rsi:.0f} | {macd_status} | 20日{pos20:.0f}% | 60日{pos60:.0f}%")
            print(f"        MA20={ma20:.2f}({above_ma20}) MA60={ma60:.2f}({above_ma60})" if ma60 else f"        MA20={ma20:.2f}({above_ma20})")
            print(f"        5d{chg5d:+.1f}% 20d{chg20d:+.1f}% 量比{vol_ratio:.1f} → {signal_str}")
            
        except Exception as e:
            print(f"  {t}: 错误 - {e}")

print("\n\nDone.")
