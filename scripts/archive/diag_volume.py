"""Diagnostic: understand volume breakout conditions"""
import sys
sys.path = [p for p in sys.path if 'venv' not in p.lower() and 'hermes-agent' not in p.lower()]

import duckdb, pandas as pd, numpy as np

DB_PATH = r'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'

def diagnose(symbol, interval='15m', vol_mult=[1.5, 2.0, 2.5, 3.0, 5.0], lookback=20):
    con = duckdb.connect(DB_PATH)
    df = con.execute(f"""
        SELECT open_time, open, high, low, close, volume
        FROM kline WHERE symbol='{symbol}' AND interval='{interval}'
        ORDER BY open_time ASC
    """).fetchdf()
    con.close()

    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df = df.set_index('open_time')

    # Compute indicators
    vol_ma = df['volume'].rolling(lookback).mean()
    high_20 = df['high'].rolling(lookback).max()
    bullish = df['close'] > df['open']

    print(f"\n## {symbol} {interval} | {len(df)} bars | {df.index[0]} -> {df.index[-1]}")
    print(f"Vol range: {df['volume'].min():.0f} - {df['volume'].max():.0f}")
    print(f"Price range: {df['close'].min():.2f} - {df['close'].max():.2f}")
    print(f"Avg vol: {df['volume'].mean():.0f}")
    print(f"Avg vol MA(20): {vol_ma.mean():.0f}")

    for mult in vol_mult:
        # Condition: vol > mult * vol_ma
        vol_cond = df['volume'] > mult * vol_ma
        # Condition: close >= high_20
        high_cond = df['close'] >= high_20
        # Condition: bullish
        bull_cond = bullish

        all_cond = vol_cond & high_cond & bull_cond
        # After first 20 bars (warmup)
        valid_idx = all_cond.index[lookback:]
        valid = all_cond[lookback:]

        signals = valid.sum()
        print(f"  Vol>{mult}xMA: vol_sig={vol_cond[lookback:].sum()}, "
              f"high_sig={high_cond[lookback:].sum()}, "
              f"bull_sig={bull_cond[lookback:].sum()}, "
              f"ALL={signals}")

        if signals > 0:
            # Show first few signals
            sig_times = valid[valid].index[:3]
            for t in sig_times:
                row = df.loc[t]
                print(f"    [{t}] Close={row['close']:.2f} High20={high_20.loc[t]:.2f} "
                      f"Vol={row['volume']:.0f} VolMA={vol_ma.loc[t]:.0f} "
                      f"Ratio={row['volume']/vol_ma.loc[t]:.1f}x")

# Diagnose major symbols
for sym in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT', 'DOGEUSDT', 'SUIUSDT', 'AVAXUSDT']:
    diagnose(sym)
