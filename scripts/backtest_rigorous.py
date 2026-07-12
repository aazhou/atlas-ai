"""
Rigorous backtesting with backtesting.py for:
  1. Volume Breakout Strategy (15m)
  2. BTC Leading Strategy (1h)

Clean PYTHONPATH, Python 3.14 with backtesting.py 0.6.5
"""

import sys
# Filter out venv paths to avoid numpy cp311 conflict
sys.path = [p for p in sys.path if 'venv' not in p.lower() and 'hermes-agent' not in p.lower()]

import duckdb
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os

from backtesting import Backtest, Strategy
from backtesting.lib import crossover

# ─── Data Extraction ───────────────────────────────────────────────────────
DB_PATH = r'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
OUT_DIR = r'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto'

def load_kline(symbol, interval):
    """Load kline data from DuckDB, return DataFrame suitable for backtesting.py"""
    con = duckdb.connect(DB_PATH)
    df = con.execute(f"""
        SELECT open_time, open, high, low, close, volume
        FROM kline
        WHERE symbol = '{symbol}' AND interval = '{interval}'
        ORDER BY open_time ASC
    """).fetchdf()
    con.close()

    if df.empty:
        return df

    # Convert to datetime and set index
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df = df.set_index('open_time')
    df = df.rename(columns={
        'open': 'Open', 'high': 'High', 'low': 'Low',
        'close': 'Close', 'volume': 'Volume'
    })

    # Remove duplicates
    df = df[~df.index.duplicated(keep='first')]
    return df

# ─── Strategy 1: Volume Breakout ───────────────────────────────────────────
class VolumeBreakoutStrategy(Strategy):
    """
    15m K-line strategy:
    - Entry: Volume > 3x 20-bar avg volume + Close > 20-bar high + Close > Open
    - Exit: Trailing stop: TP +10%, SL -8%, max hold 24h (96 bars)
    """
    vol_mult = 3.0
    lookback = 20
    tp_pct = 0.10
    sl_pct = 0.08
    max_hold = 96  # 24h in 15m bars

    def init(self):
        self.vol_avg = self.I(lambda x: pd.Series(x).rolling(self.lookback).mean(), self.data.Volume)
        self.high_20 = self.I(lambda x: pd.Series(x).rolling(self.lookback).max(), self.data.High)

    def next(self):
        current = len(self.data) - 1
        if current < self.lookback:
            return

        # If already in position, check exit
        if self.position.is_long:
            # Max hold check
            if self.trades:
                last_trade = self.trades[-1]
                if current - last_trade.entry_bar >= self.max_hold:
                    self.position.close()
                    return

            # Trailing stop
            entry_price = last_trade.entry_price
            current_price = self.data.Close[-1]
            pnl_pct = (current_price - entry_price) / entry_price

            if pnl_pct >= self.tp_pct:
                self.position.close()
            elif pnl_pct <= -self.sl_pct:
                self.position.close()
            return

        # Entry signal
        vol_now = self.data.Volume[-1]
        vol_avg_now = self.vol_avg[-1]
        high_20_now = self.high_20[-1]
        close_now = self.data.Close[-1]
        open_now = self.data.Open[-1]

        if vol_avg_now > 0 and vol_now > self.vol_mult * vol_avg_now:
            if close_now >= high_20_now and close_now > open_now:
                self.buy()

# ─── Strategy 2: BTC Leading ────────────────────────────────────────────────
class BTCLeadingStrategy(Strategy):
    """
    BTC 1h breaks EMA50 -> altcoin follows within 1h -> LONG
    For non-BTC pairs (tested individually)
    """
    ema_period = 50
    tp_pct = 0.10
    sl_pct = 0.08
    max_hold = 72  # 72h in 1h bars

    def init(self):
        # EMA is precomputed externally since it depends on BTC data
        pass

    def set_signals(self, btc_ema_cross_up, altcoin_buy_signal):
        """Set precomputed signals from external analysis"""
        self._btc_cross = btc_ema_cross_up
        self._alt_signal = altcoin_buy_signal

    def next(self):
        current = len(self.data) - 1
        if current < self.ema_period:
            return

        if self.position.is_long:
            if self.trades:
                last_trade = self.trades[-1]
                if current - last_trade.entry_bar >= self.max_hold:
                    self.position.close()
                    return

            entry_price = last_trade.entry_price
            current_price = self.data.Close[-1]
            pnl_pct = (current_price - entry_price) / entry_price

            if pnl_pct >= self.tp_pct:
                self.position.close()
            elif pnl_pct <= -self.sl_pct:
                self.position.close()
            return

        # Entry: precomputed signal
        if current < len(self._alt_signal) and self._alt_signal[current]:
            self.buy()

# ─── Metrics Calculation ────────────────────────────────────────────────────
def calc_metrics(stats):
    """Extract key metrics from backtesting.py stats"""
    return {
        'start': str(stats.get('Start', '')),
        'end': str(stats.get('End', '')),
        'duration': str(stats.get('Duration', '')),
        'exposure': round(float(stats.get('Exposure Time [%]', 0)), 2),
        'equity_final': round(float(stats.get('Equity Final [$]', 0)), 2),
        'return_pct': round(float(stats.get('Return [%]', 0)), 2),
        'buy_hold_return_pct': round(float(stats.get('Buy & Hold Return [%]', 0)), 2),
        'sharpe': round(float(stats.get('Sharpe Ratio', 0)), 3),
        'sortino': round(float(stats.get('Sortino Ratio', 0)), 3),
        'max_drawdown_pct': round(float(stats.get('Max. Drawdown [%]', 0)), 2),
        'win_rate_pct': round(float(stats.get('Win Rate [%]', 0)), 2),
        'best_trade_pct': round(float(stats.get('Best Trade [%]', 0)), 2),
        'worst_trade_pct': round(float(stats.get('Worst Trade [%]', 0)), 2),
        'avg_trade_pct': round(float(stats.get('Avg. Trade [%]', 0)), 2),
        'profit_factor': round(float(stats.get('Profit Factor', 0)), 3),
        'num_trades': int(stats.get('# Trades', 0)),
        'avg_hold_hours': round(float(stats.get('Avg. Trade Duration', '0').split(' ')[0]) if isinstance(stats.get('Avg. Trade Duration', ''), str) else 0, 1),
    }

# ─── Run Backtests ──────────────────────────────────────────────────────────
def run_volume_breakout(symbols=['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'DOGEUSDT', 'XRPUSDT']):
    """Run volume breakout strategy on selected symbols"""
    results = {}
    all_metrics = []

    for sym in symbols:
        df = load_kline(sym, '15m')
        if df.empty or len(df) < 50:
            print(f"[SKIP] {sym}: insufficient data ({len(df)} bars)")
            continue

        print(f"\n{'='*60}")
        print(f"[VOLUME BREAKOUT] {sym} 15m | {len(df)} bars | {df.index[0]} -> {df.index[-1]}")
        print(f"{'='*60}")

        bt = Backtest(df, VolumeBreakoutStrategy, cash=100000, commission=.001, exclusive_orders=True)
        stats = bt.run()

        metrics = calc_metrics(stats)
        print(json.dumps(metrics, indent=2))
        results[sym] = metrics
        all_metrics.append(metrics)

    return results, all_metrics

def compute_btc_signals(df_btc, alt_df):
    """Precompute BTC EMA50 crossover and altcoin follow signals"""
    ema50 = df_btc['Close'].ewm(span=50, adjust=False).mean()
    # BTC breaks above EMA50 on 1h
    btc_cross = (df_btc['Close'] > ema50) & (df_btc['Close'].shift(1) <= ema50.shift(1))

    # Align timestamps: for each alt bar, check if BTC crossed up within the last 2 bars
    alt_signal = pd.Series(False, index=alt_df.index)
    btc_cross_times = btc_cross[btc_cross].index

    for i, alt_time in enumerate(alt_df.index):
        # Check if BTC crossed up within the last 2 hours (2 bars in 1h)
        recent_cross = [t for t in btc_cross_times if alt_time - pd.Timedelta(hours=2) <= t <= alt_time]
        if recent_cross:
            alt_signal.iloc[i] = True

    return alt_signal.values

def run_btc_leading(alt_symbols=['ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'DOGEUSDT', 'XRPUSDT', 'ADAUSDT']):
    """Run BTC leading strategy"""
    # Load BTC 1h
    btc_df = load_kline('BTCUSDT', '1h')
    if btc_df.empty:
        print("[FAIL] Cannot load BTC 1h data")
        return {}, []

    print(f"BTC 1h: {len(btc_df)} bars | {btc_df.index[0]} -> {btc_df.index[-1]}")

    results = {}
    all_metrics = []

    for sym in alt_symbols:
        alt_df = load_kline(sym, '1h')
        if alt_df.empty or len(alt_df) < 100:
            print(f"[SKIP] {sym}: insufficient data ({len(alt_df)} bars)")
            continue

        # Align to common index range
        common_start = max(btc_df.index[0], alt_df.index[0])
        common_end = min(btc_df.index[-1], alt_df.index[-1])

        alt_aligned = alt_df[common_start:common_end]
        btc_aligned = btc_df[common_start:common_end]

        if len(alt_aligned) < 100:
            print(f"[SKIP] {sym}: aligned data too short ({len(alt_aligned)} bars)")
            continue

        # Precompute signals
        alt_signals = compute_btc_signals(btc_aligned, alt_aligned)
        signal_count = int(alt_signals.sum())
        print(f"\n{'='*60}")
        print(f"[BTC LEADING] {sym} 1h | {len(alt_aligned)} bars | BTC cross signals: {int(btc_aligned['Close'].gt(btc_aligned['Close'].ewm(50).mean()).diff().gt(0).sum())} | Alt entries: {signal_count}")
        print(f"{'='*60}")

        if signal_count == 0:
            print(f"[SKIP] {sym}: no altcoin entry signals generated")
            continue

        bt = Backtest(alt_aligned, BTCLeadingStrategy, cash=10000, commission=.001)
        # Pass signals via strategy params
        stats = bt.run(
            ema_period=50, tp_pct=0.10, sl_pct=0.08, max_hold=72,
        )

        metrics = calc_metrics(stats)
        # Add signal count
        metrics['btc_crosses'] = signal_count
        print(json.dumps(metrics, indent=2))
        results[sym] = metrics
        all_metrics.append(metrics)

    return results, all_metrics

# ─── BTC-Leading Strategy Class with external signals ───────────────────────
# Need to precompute and inject signals since Strategy can't access external data
class BTCLeadPrecomputed(Strategy):
    tp_pct = 0.10
    sl_pct = 0.08
    max_hold = 72

    def init(self):
        self.signal = self.I(lambda x: x, self.data.Close)  # placeholder

    def next(self):
        current = len(self.data) - 1
        if current < 50:
            return

        # Check if we have a position
        if self.position.is_long:
            if self.trades:
                last_trade = self.trades[-1]
                # Max hold
                if current - last_trade.entry_bar >= self.max_hold:
                    self.position.close()
                    return
                # Trailing stop
                pnl_pct = (self.data.Close[-1] - last_trade.entry_price) / last_trade.entry_price
                if pnl_pct >= self.tp_pct or pnl_pct <= -self.sl_pct:
                    self.position.close()
            return

# ─── Enhanced runner with signal injection ──────────────────────────────────
def run_btc_leading_v2(alt_symbols=['ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'DOGEUSDT', 'XRPUSDT', 'ADAUSDT']):
    """Run BTC leading strategy with precomputed signals injected as a column"""
    btc_df = load_kline('BTCUSDT', '1h')
    if btc_df.empty:
        print("[FAIL] Cannot load BTC 1h data")
        return {}, []

    print(f"\nBTC 1h: {len(btc_df)} bars | {btc_df.index[0]} -> {btc_df.index[-1]}")

    # Compute BTC EMA50 crossover
    btc_ema50 = btc_df['Close'].ewm(span=50, adjust=False).mean()
    btc_cross_up = (btc_df['Close'] > btc_ema50) & (btc_df['Close'].shift(1) <= btc_ema50.shift(1))
    btc_cross_times = btc_cross_up[btc_cross_up].index
    print(f"BTC EMA50 cross-ups: {len(btc_cross_times)} events")

    results = {}
    all_metrics = []

    for sym in alt_symbols:
        alt_df = load_kline(sym, '1h')
        if alt_df.empty or len(alt_df) < 100:
            print(f"[SKIP] {sym}: insufficient data ({len(alt_df)} bars)")
            continue

        # Align
        common_start = max(btc_df.index[0], alt_df.index[0])
        common_end = min(btc_df.index[-1], alt_df.index[-1])
        alt_aligned = alt_df[common_start:common_end].copy()

        if len(alt_aligned) < 100:
            print(f"[SKIP] {sym}: aligned data too short ({len(alt_aligned)} bars)")
            continue

        # Generate signal column: 1 when BTC crossed up within last 2h AND alt also rose
        alt_aligned['Signal'] = 0
        for i, (idx, row) in enumerate(alt_aligned.iterrows()):
            recent_cross = [t for t in btc_cross_times if idx - pd.Timedelta(hours=2) <= t <= idx]
            if recent_cross:
                alt_aligned.loc[idx, 'Signal'] = 1

        signal_count = int(alt_aligned['Signal'].sum())
        print(f"\n{'='*60}")
        print(f"[BTC LEADING] {sym} | Aligned bars: {len(alt_aligned)} | Alt entries: {signal_count}")
        print(f"{'='*60}")

        if signal_count < 2:
            print(f"[SKIP] {sym}: insufficient entry signals (<2)")
            continue

        # Custom strategy that reads Signal column
        class BTCLead(Strategy):
            tp_pct = 0.10
            sl_pct = 0.08
            max_hold = 72

            def init(self):
                self.signal_col = self.I(lambda x: x, self.data.Signal, name='signal')

            def next(self):
                current = len(self.data) - 1
                if current < 60:
                    return

                if self.position.is_long:
                    if self.trades:
                        lt = self.trades[-1]
                        if current - lt.entry_bar >= self.max_hold:
                            self.position.close()
                            return
                        pnl = (self.data.Close[-1] - lt.entry_price) / lt.entry_price
                        if pnl >= self.tp_pct or pnl <= -self.sl_pct:
                            self.position.close()
                    return

                # Entry on signal
                if self.signal_col[-1] > 0:
                    # Also require alt itself to be bullish (close > open)
                    if self.data.Close[-1] > self.data.Close[-2]:
                        self.buy()

        bt = Backtest(alt_aligned, BTCLead, cash=100000, commission=.001, exclusive_orders=True)
        stats = bt.run()

        metrics = calc_metrics(stats)
        metrics['btc_cross_signals'] = len(btc_cross_times)
        metrics['alt_entry_signals'] = signal_count
        print(json.dumps(metrics, indent=2))

        results[sym] = metrics
        all_metrics.append(metrics)

    return results, all_metrics

# ─── Summary & Save ─────────────────────────────────────────────────────────
def save_results(strategy_name, results, all_metrics):
    """Save to JSON with quality assessment"""
    if not all_metrics:
        return None

    # Average metrics
    avg = {}
    for key in ['sharpe', 'win_rate_pct', 'return_pct', 'max_drawdown_pct', 'profit_factor']:
        vals = [m[key] for m in all_metrics if m.get(key) is not None]
        avg[key] = round(np.mean(vals), 3) if vals else None

    summary = {
        'strategy': strategy_name,
        'tested_on': datetime.now().isoformat(),
        'symbols_tested': len(results),
        'total_trades': sum(m.get('num_trades', 0) for m in all_metrics),
        'avg_sharpe': avg['sharpe'],
        'avg_win_rate': avg['win_rate_pct'],
        'avg_return_pct': avg['return_pct'],
        'avg_max_dd_pct': avg['max_drawdown_pct'],
        'avg_profit_factor': avg['profit_factor'],
        'per_symbol': results,
    }

    meets_criteria = (
        avg['sharpe'] is not None and avg['sharpe'] > 1.0 and
        avg['win_rate'] is not None and avg['win_rate'] > 40
    )

    summary['meets_live_criteria'] = meets_criteria

    return summary

# ─── Main ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 70)
    print("RIGOROUS BACKTEST - backtesting.py")
    print(f"Data: {DB_PATH}")
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 70)

    all_summaries = []

    # ─── Strategy 1: Volume Breakout ───
    print("\n\n### STRATEGY 1: Volume Breakout (15m) ###")
    print("Rules: Vol>3x20MA + Price>20bar high + Bull bar → LONG")
    print("Exit: TP+10% / SL-8% / Max 24h")
    vb_results, vb_metrics = run_volume_breakout()
    vb_summary = save_results('volume_breakout_15m', vb_results, vb_metrics)
    if vb_summary:
        all_summaries.append(vb_summary)
        print(f"\n>>> Volume Breakout Summary: Sharpe={vb_summary['avg_sharpe']}, "
              f"WinRate={vb_summary['avg_win_rate']}%, "
              f"Trades={vb_summary['total_trades']}, "
              f"MeetsCriteria={vb_summary['meets_live_criteria']}")

    # ─── Strategy 2: BTC Leading ───
    print("\n\n### STRATEGY 2: BTC Leading (1h) ###")
    print("Rules: BTC 1h breaks EMA50 → Alt follows within 2h → LONG")
    print("Exit: TP+10% / SL-8% / Max 72h")
    bl_results, bl_metrics = run_btc_leading_v2()
    bl_summary = save_results('btc_leading_1h', bl_results, bl_metrics)
    if bl_summary:
        all_summaries.append(bl_summary)
        print(f"\n>>> BTC Leading Summary: Sharpe={bl_summary['avg_sharpe']}, "
              f"WinRate={bl_summary['avg_win_rate']}%, "
              f"Trades={bl_summary['total_trades']}, "
              f"MeetsCriteria={bl_summary['meets_live_criteria']}")

    # ─── Save to strategies.json ───
    output = {
        'generated': datetime.now().isoformat(),
        'engine': 'backtesting.py v0.6.5',
        'strategies': all_summaries
    }

    out_path = os.path.join(OUT_DIR, 'strategies.json')
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n[DONE] Saved to {out_path}")

    # ─── Final verdict ───
    print("\n" + "=" * 70)
    print("FINAL VERDICT")
    print("=" * 70)
    for s in all_summaries:
        status = "🟢 PASS (deployable)" if s['meets_live_criteria'] else "🔴 FAIL (not deployable)"
        print(f"  {s['strategy']}: Sharpe={s['avg_sharpe']} WinRate={s['avg_win_rate']}% Trades={s['total_trades']} → {status}")
