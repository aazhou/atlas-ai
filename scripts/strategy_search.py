#!/usr/bin/env python3
"""
strategy_search.py — DuckDB暴力搜索5种加密交易策略
=====================================================
在market.duckdb上回测多个策略组合，评估性能指标，
输出Top 3到 data/crypto/strategies.json

策略:
  A. 费率均值回归 — funding偏离均值做反向
  B. 量价突破 — 放量+价格突破N日区间
  C. OI异动 — OI暴增+价格滞涨=反转
  D. 多时间框架EMA金叉死叉
  E. BTC引领效应 — BTC突破→山寨补涨

使用方式: python scripts/strategy_search.py [--top N]
"""

import duckdb
import json
import math
import sys
import os
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / 'data' / 'crypto' / 'market.duckdb'
OUTPUT_PATH = PROJECT_ROOT / 'data' / 'crypto' / 'strategies.json'
TOP_N = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == '--top' else 3

# ============================================================
# Utilities
# ============================================================

def connect():
    return duckdb.connect(str(DB_PATH), read_only=True)

def load_klines(con, interval='1h', symbols=None):
    """Load klines into a dict of symbol -> DataFrame."""
    if symbols:
        syms = "','".join(symbols)
        where = f"WHERE symbol IN ('{syms}')"
    else:
        where = ""
    df = con.execute(f"""
        SELECT symbol, open_time, open, high, low, close, volume
        FROM kline
        WHERE interval = '{interval}' {where}
        ORDER BY symbol, open_time
    """).df()
    return df

def load_funding(con, symbols=None):
    if symbols:
        syms = "','".join(symbols)
        where = f"WHERE symbol IN ('{syms}')"
    else:
        where = ""
    df = con.execute(f"""
        SELECT symbol, funding_time, funding_rate
        FROM funding {where}
        ORDER BY symbol, funding_time
    """).df()
    return df

def load_oi(con, period='5m', symbols=None):
    if symbols:
        syms = "','".join(symbols)
        where = f"WHERE period = '{period}' AND symbol IN ('{syms}')"
    else:
        where = f"WHERE period = '{period}'"
    df = con.execute(f"""
        SELECT symbol, timestamp, open_interest
        FROM oi_snapshot {where}
        ORDER BY symbol, timestamp
    """).df()
    return df

def load_tickers(con, symbols=None):
    if symbols:
        syms = "','".join(symbols)
        where = f"WHERE symbol IN ('{syms}')"
    else:
        where = ""
    df = con.execute(f"SELECT symbol, last_price, high_price, low_price, quote_volume, price_change_pct FROM ticker {where}").df()
    return df

def get_all_symbols(con):
    rows = con.execute("SELECT DISTINCT symbol FROM kline ORDER BY symbol").fetchall()
    return [r[0] for r in rows]

def compute_metrics(trades):
    """
    trades: list of dicts with {pnl_pct, entry_time, exit_time, symbol}
    Returns dict of {sharpe, win_rate, profit_factor, max_drawdown, total_return, monthly_returns, trades}
    """
    if not trades:
        return {'sharpe': 0, 'win_rate': 0, 'profit_factor': 0, 'max_drawdown': 0,
                'total_return': 0, 'monthly_returns': [], 'trades': 0}

    returns = [t['pnl_pct'] / 100.0 for t in trades]  # convert % to decimal
    n = len(returns)
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    win_rate = len(wins) / n * 100 if n > 0 else 0

    avg_ret = sum(returns) / n if n > 0 else 0
    std_ret = math.sqrt(sum((r - avg_ret)**2 for r in returns) / (n - 1)) if n > 1 else 0.01
    sharpe = (avg_ret / std_ret * math.sqrt(365 * 24)) if std_ret > 0 else 0  # hourly → annualized

    total_wins = sum(abs(r) for r in wins) if wins else 0
    total_losses = sum(abs(r) for r in losses) if losses else 0
    profit_factor = total_wins / total_losses if total_losses > 0 else (999 if total_wins > 0 else 0)

    # Max drawdown (cumulative)
    cumulative = 0
    peak = 0
    max_dd = 0
    for r in returns:
        cumulative += r
        peak = max(peak, cumulative)
        dd = peak - cumulative
        max_dd = max(max_dd, dd)

    total_return = (cumulative * 100) if returns else 0

    # Monthly returns
    monthly = defaultdict(float)
    for t in trades:
        key = t['entry_time'][:7] if isinstance(t['entry_time'], str) else str(t['entry_time'])[:7]
        monthly[key] += t['pnl_pct']
    monthly_returns = [{'month': k, 'return': round(v, 2)} for k, v in sorted(monthly.items())]

    return {
        'sharpe': round(sharpe, 2),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'max_drawdown': round(max_dd * 100, 1),
        'total_return': round(total_return, 2),
        'monthly_returns': monthly_returns,
        'trades': n
    }

# ============================================================
# Strategy A: Funding Mean Reversion
# ============================================================

def backtest_funding_mean_reversion(con):
    """
    费率偏离均值 > 2σ → 反向入场
    费率极端负 → LONG; 费率极端正 → SHORT
    费率回归均值附近 → 平仓
    """
    df = load_funding(con)
    if df.empty:
        return {'name': 'funding_mean_reversion', 'description': '费率均值回归', 'trades': []}

    symbols = df['symbol'].unique()
    all_trades = []

    for sym in symbols:
        sdf = df[df['symbol'] == sym].sort_values('funding_time')
        rates = sdf['funding_rate'].values
        if len(rates) < 50:
            continue

        window = 48  # ~48 funding intervals = 8h history
        rolling_mean = []
        rolling_std = []
        for i in range(len(rates)):
            start = max(0, i - window)
            segment = rates[start:i+1]
            rolling_mean.append(sum(segment) / len(segment))
            rolling_std.append(math.sqrt(sum((x - rolling_mean[-1])**2 for x in segment) / len(segment)) if len(segment) > 1 else 0)

        position = None  # None, {'type':'long'/'short', 'entry_rate', 'entry_time'}
        for i in range(window, len(rates)):
            rate = rates[i]
            mu = rolling_mean[i]
            sigma = rolling_std[i] if rolling_std[i] > 0 else 0.0001  # avoid div by zero

            if position is None:
                z = (rate - mu) / sigma if sigma > 0 else 0
                if z < -2.0:  # extremely negative → go LONG
                    position = {'type': 'long', 'entry_rate': rate, 'entry_idx': i, 'entry_time': int(sdf.iloc[i]['funding_time'])}
                elif z > 2.0:  # extremely positive → go SHORT
                    position = {'type': 'short', 'entry_rate': rate, 'entry_idx': i, 'entry_time': int(sdf.iloc[i]['funding_time'])}
            else:
                z = (rate - mu) / sigma if sigma > 0 else 0
                exit_condition = abs(z) < 0.3  # back near mean
                max_hold = (i - position['entry_idx'] > 72)  # max 12h hold

                if exit_condition or max_hold:
                    # Simplified PnL: if LONG, positive rate change = loss; if SHORT, positive = gain
                    rate_diff = rate - position['entry_rate']
                    if position['type'] == 'long':
                        pnl = -rate_diff * 10000  # scale for readability
                    else:
                        pnl = rate_diff * 10000

                    all_trades.append({
                        'symbol': sym,
                        'type': position['type'],
                        'pnl_pct': round(pnl, 2),
                        'entry_time': datetime.fromtimestamp(position['entry_time'] / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                        'exit_time': datetime.fromtimestamp(int(sdf.iloc[i]['funding_time']) / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                        'entry_rate': position['entry_rate'],
                        'exit_rate': rate
                    })
                    position = None

    metrics = compute_metrics(all_trades)
    return {
        'name': 'funding_mean_reversion',
        'description': '费率偏离均值2σ时反向入场，回归均值平仓。极端负→LONG，极端正→SHORT',
        'parameters': {'window': window, 'entry_z': 2.0, 'exit_z': 0.3, 'max_hold_intervals': 72},
        **metrics,
        'sample_trades': all_trades[:10]
    }

# ============================================================
# Strategy B: Volume Breakout
# ============================================================

def backtest_volume_breakout(con):
    """
    放量(volume > 3x 20-period avg) + 价格突破N-period最高价 → LONG
    止损: -5%, 止盈: +10%
    """
    df = load_klines(con, interval='1h')
    if df.empty:
        return {'name': 'volume_breakout', 'description': '量价突破', 'trades': []}

    symbols = df['symbol'].unique()
    all_trades = []
    vol_window = 20
    price_window = 20
    vol_mult = 3.0
    sl = -5.0
    tp = 10.0

    for sym in symbols:
        sdf = df[df['symbol'] == sym].sort_values('open_time')
        closes = sdf['close'].values
        highs = sdf['high'].values
        volumes = sdf['volume'].values
        times = sdf['open_time'].values
        if len(closes) < vol_window + 10:
            continue

        position = None
        for i in range(vol_window, len(closes)):
            avg_vol = sum(volumes[i-vol_window:i]) / vol_window
            highest_high = max(highs[i-price_window:i])

            if position is None:
                if volumes[i] > avg_vol * vol_mult and closes[i] > highest_high:
                    position = {'entry': closes[i], 'entry_time': int(times[i]), 'entry_idx': i}
            else:
                pnl = (closes[i] - position['entry']) / position['entry'] * 100
                if pnl <= sl or pnl >= tp or (i - position['entry_idx']) > 48:  # max 48h hold
                    all_trades.append({
                        'symbol': sym,
                        'type': 'long',
                        'pnl_pct': round(pnl, 2),
                        'entry_time': datetime.fromtimestamp(int(position['entry_time']) / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                        'exit_time': datetime.fromtimestamp(int(times[i]) / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                        'entry_price': position['entry'],
                        'exit_price': closes[i]
                    })
                    position = None

    metrics = compute_metrics(all_trades)
    return {
        'name': 'volume_breakout',
        'description': '放量(>3x均量)+价格突破20周期最高价→LONG。SL:-5%, TP:+10%',
        'parameters': {'vol_window': vol_window, 'price_window': price_window, 'vol_mult': vol_mult, 'sl': sl, 'tp': tp, 'max_hold_hours': 48},
        **metrics,
        'sample_trades': all_trades[:10]
    }

# ============================================================
# Strategy C: OI Divergence
# ============================================================

def backtest_oi_divergence(con):
    """
    OI 1h内增加 > 20% + 价格变动 < 1% → 反转信号 SHORT
    止损: +5%, 止盈: -10%
    """
    oi_df = load_oi(con, period='5m')
    kline_df = load_klines(con, interval='15m')
    if oi_df.empty or kline_df.empty:
        return {'name': 'oi_divergence', 'description': 'OI背离', 'trades': []}

    symbols = set(oi_df['symbol'].unique()) & set(kline_df['symbol'].unique())
    all_trades = []
    oi_threshold = 20  # % increase over 1h
    price_threshold = 1.0  # % price move
    sl = -5.0   # SHORT: stop if price goes up 5%
    tp = 10.0   # SHORT: take profit if price drops 10%

    for sym in symbols:
        oi_sym = oi_df[oi_df['symbol'] == sym].sort_values('timestamp')
        kl_sym = kline_df[kline_df['symbol'] == sym].sort_values('open_time')
        if len(oi_sym) < 24 or len(kl_sym) < 50:
            continue

        # Align OI timestamps to 5min buckets
        oi_times = oi_sym['timestamp'].values
        oi_values = oi_sym['open_interest'].values
        kl_times = kl_sym['open_time'].values
        kl_closes = kl_sym['close'].values

        position = None
        for i in range(12, len(oi_times)):  # 12 * 5min = 1h
            # OI change over last 1h
            oi_1h_ago_idx = max(0, i - 12)
            oi_change = (oi_values[i] - oi_values[oi_1h_ago_idx]) / oi_values[oi_1h_ago_idx] * 100 if oi_values[oi_1h_ago_idx] > 0 else 0

            # Price change over same period
            oi_time = oi_times[i]
            # Find nearest kline
            kl_idx = None
            for j in range(len(kl_times)):
                if kl_times[j] >= oi_time - 300000:  # within 5min
                    kl_idx = j
                    break
            if kl_idx is None or kl_idx < 12:
                continue

            prev_kl_idx = max(0, kl_idx - 12)
            price_change = (kl_closes[kl_idx] - kl_closes[prev_kl_idx]) / kl_closes[prev_kl_idx] * 100

            if position is None:
                if oi_change > oi_threshold and abs(price_change) < price_threshold:
                    # OI spiked but price barely moved → SHORT
                    position = {'entry': kl_closes[kl_idx], 'entry_time': int(kl_times[kl_idx]), 'entry_idx': kl_idx}
            else:
                pnl = (position['entry'] - kl_closes[kl_idx]) / position['entry'] * 100  # SHORT: profit when price drops
                max_hold = (kl_idx - position['entry_idx']) > 192  # max 48h in 15m candles
                if pnl <= sl or pnl >= tp or max_hold:
                    all_trades.append({
                        'symbol': sym,
                        'type': 'short',
                        'pnl_pct': round(pnl, 2),
                        'entry_time': datetime.fromtimestamp(int(position['entry_time']) / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                        'exit_time': datetime.fromtimestamp(int(kl_times[kl_idx]) / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                        'entry_price': position['entry'],
                        'exit_price': kl_closes[kl_idx]
                    })
                    position = None

    metrics = compute_metrics(all_trades)
    return {
        'name': 'oi_divergence',
        'description': 'OI 1h增加>20% + 价格变动<1% → 反转SHORT。SL:-5%, TP:+10%',
        'parameters': {'oi_threshold_pct': oi_threshold, 'price_threshold_pct': price_threshold, 'sl': sl, 'tp': tp},
        **metrics,
        'sample_trades': all_trades[:10]
    }

# ============================================================
# Strategy D: Multi-Timeframe EMA Crossover
# ============================================================

def backtest_ema_crossover(con):
    """
    EMA(9,21,50) 在 1h K线上:
    - EMA9 > EMA21 > EMA50 → LONG
    - EMA9 < EMA21 < EMA50 → SHORT
    - 交叉反向 → 平仓
    """
    df = load_klines(con, interval='1h')
    if df.empty:
        return {'name': 'ema_crossover', 'description': 'EMA金叉死叉', 'trades': []}

    def ema(values, period):
        alpha = 2.0 / (period + 1)
        result = [values[0]]
        for v in values[1:]:
            result.append(alpha * v + (1 - alpha) * result[-1])
        return result

    symbols = df['symbol'].unique()
    all_trades = []

    for sym in symbols:
        sdf = df[df['symbol'] == sym].sort_values('open_time')
        closes = sdf['close'].values
        times = sdf['open_time'].values
        if len(closes) < 55:
            continue

        ema9 = ema(closes, 9)
        ema21 = ema(closes, 21)
        ema50 = ema(closes, 50)

        position = None
        for i in range(50, len(closes)):
            bullish = ema9[i] > ema21[i] > ema50[i]
            bearish = ema9[i] < ema21[i] < ema50[i]

            if position is None:
                if bullish:
                    position = {'type': 'long', 'entry': closes[i], 'entry_time': int(times[i]), 'entry_idx': i}
                elif bearish:
                    position = {'type': 'short', 'entry': closes[i], 'entry_time': int(times[i]), 'entry_idx': i}
            else:
                exit_signal = False
                if position['type'] == 'long' and not bullish:
                    exit_signal = True
                elif position['type'] == 'short' and not bearish:
                    exit_signal = True
                elif (i - position['entry_idx']) > 240:  # max 10 days hold
                    exit_signal = True

                if exit_signal:
                    if position['type'] == 'long':
                        pnl = (closes[i] - position['entry']) / position['entry'] * 100
                    else:
                        pnl = (position['entry'] - closes[i]) / position['entry'] * 100

                    all_trades.append({
                        'symbol': sym,
                        'type': position['type'],
                        'pnl_pct': round(pnl, 2),
                        'entry_time': datetime.fromtimestamp(int(position['entry_time']) / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                        'exit_time': datetime.fromtimestamp(int(times[i]) / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                        'entry_price': position['entry'],
                        'exit_price': closes[i]
                    })
                    position = None

    metrics = compute_metrics(all_trades)
    return {
        'name': 'ema_crossover',
        'description': 'EMA(9/21/50)金叉做多，死叉做空。1h K线，交叉反向平仓',
        'parameters': {'ema_fast': 9, 'ema_mid': 21, 'ema_slow': 50, 'timeframe': '1h', 'max_hold_hours': 240},
        **metrics,
        'sample_trades': all_trades[:10]
    }

# ============================================================
# Strategy E: BTC Lead Effect
# ============================================================

def backtest_btc_lead(con):
    """
    BTC突破N周期最高价 → 扫描山寨币补涨
    入场: 山寨币价格尚未突破但近高点
    平仓: BTC回撤或山寨追涨到位
    """
    df = load_klines(con, interval='1h')
    if df.empty:
        return {'name': 'btc_lead', 'description': 'BTC引领效应', 'trades': []}

    symbols = df['symbol'].unique()
    if 'BTCUSDT' not in symbols:
        return {'name': 'btc_lead', 'description': 'BTC引领效应 (无BTC数据)', 'trades': []}

    btc_df = df[df['symbol'] == 'BTCUSDT'].sort_values('open_time')
    btc_highs = btc_df['high'].values
    btc_closes = btc_df['close'].values
    btc_times = btc_df['open_time'].values

    all_trades = []
    lookback = 24  # 24h lookback
    btc_breakout_threshold = 0.02  # 2%

    # Precompute BTC breakouts
    btc_breakout_times = set()
    for i in range(lookback, len(btc_closes)):
        prev_high = max(btc_highs[i-lookback:i])
        if btc_closes[i] > prev_high * (1 + btc_breakout_threshold / 100):
            btc_breakout_times.add(int(btc_times[i]))

    if not btc_breakout_times:
        return {'name': 'btc_lead', 'description': 'BTC引领效应 (无突破信号)', 'trades': []}

    # Scan altcoins
    ALTS = [s for s in symbols if s != 'BTCUSDT' and s.endswith('USDT')]
    max_alt_time_diff_hours = 4

    for sym in ALTS:
        sdf = df[df['symbol'] == sym].sort_values('open_time')
        if len(sdf) < lookback + 10:
            continue
        closes = sdf['close'].values
        highs = sdf['high'].values
        times = sdf['open_time'].values

        position = None
        for i in range(lookback, len(closes)):
            t = int(times[i])
            current_price = closes[i]

            # Check if BTC had a breakout within last 4 hours
            btc_lead_recent = False
            for bt in btc_breakout_times:
                if 0 < (t - bt) / 3600000 <= max_alt_time_diff_hours:
                    btc_lead_recent = True
                    break

            if position is None:
                if btc_lead_recent:
                    prev_high = max(highs[i-lookback:i])
                    alt_near_high = current_price > prev_high * 0.95 and current_price < prev_high * 1.02
                    if alt_near_high:
                        position = {'entry': current_price, 'entry_time': t, 'entry_idx': i}
            else:
                pnl = (current_price - position['entry']) / position['entry'] * 100
                btc_idx = None
                for j in range(len(btc_times)):
                    if btc_times[j] >= t:
                        btc_idx = j
                        break
                btc_pulled_back = False
                if btc_idx and btc_idx >= lookback:
                    btc_pullback = (max(btc_highs[btc_idx-lookback:btc_idx]) - btc_closes[btc_idx]) / max(btc_highs[btc_idx-lookback:btc_idx]) * 100
                    if btc_pullback > 3:
                        btc_pulled_back = True

                max_hold = (i - position['entry_idx']) > 48
                if pnl >= 8 or pnl <= -5 or btc_pulled_back or max_hold:
                    all_trades.append({
                        'symbol': sym,
                        'type': 'long',
                        'pnl_pct': round(pnl, 2),
                        'entry_time': datetime.fromtimestamp(position['entry_time'] / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                        'exit_time': datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                        'entry_price': position['entry'],
                        'exit_price': current_price
                    })
                    position = None

    metrics = compute_metrics(all_trades)
    return {
        'name': 'btc_lead',
        'description': 'BTC突破24h新高→4h内山寨补涨追入。SL:-5%, TP:+8%, BTC回撤>3%平仓',
        'parameters': {'lookback_hours': lookback, 'btc_breakout_pct': btc_breakout_threshold, 'alt_max_diff_hours': max_alt_time_diff_hours, 'sl': -5, 'tp': 8},
        **metrics,
        'sample_trades': all_trades[:10]
    }

# ============================================================
# Main
# ============================================================

def main():
    print(f"[策略搜索] 连接 DuckDB: {DB_PATH}")
    con = connect()

    strategies = [
        ('A', '费率均值回归', backtest_funding_mean_reversion),
        ('B', '量价突破', backtest_volume_breakout),
        ('C', 'OI背离', backtest_oi_divergence),
        ('D', 'EMA金叉死叉', backtest_ema_crossover),
        ('E', 'BTC引领效应', backtest_btc_lead),
    ]

    results = []
    for code, name, fn in strategies:
        print(f"\n{'='*60}")
        print(f"[策略 {code}] {name}")
        print(f"{'='*60}")
        try:
            result = fn(con)
            trades = result.get('trades', 0)
            sample = result.pop('sample_trades', [])
            result['sample_trades'] = sample

            print(f"  交易笔数: {trades}")
            print(f"  胜率: {result.get('win_rate', 0)}%")
            print(f"  夏普: {result.get('sharpe', 0)}")
            print(f"  盈亏比: {result.get('profit_factor', 0)}")
            print(f"  最大回撤: {result.get('max_drawdown', 0)}%")
            print(f"  累计收益: {result.get('total_return', 0)}%")

            monthly = result.get('monthly_returns', [])
            if monthly:
                print(f"  月收益: {monthly[-3:] if len(monthly) > 3 else monthly}")

            results.append(result)
        except Exception as e:
            print(f"  ❌ 失败: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                'name': name,
                'description': f'执行失败: {str(e)}',
                'sharpe': 0, 'win_rate': 0, 'profit_factor': 0,
                'max_drawdown': 0, 'total_return': 0, 'monthly_returns': [], 'trades': 0,
                'error': str(e)
            })

    con.close()

    # Convert numpy types to native Python
    def to_native(obj):
        if isinstance(obj, dict):
            return {k: to_native(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [to_native(v) for v in obj]
        elif hasattr(obj, 'item'):  # numpy scalar
            return obj.item()
        return obj

    results = [to_native(r) for r in results]

    # Sort by composite score: sharpe + win_rate/10 + profit_factor
    # 0-trade strategies are excluded from top ranking
    def composite(r):
        if r.get('trades', 0) < 3:
            return -9999
        s = r.get('sharpe', 0)
        w = r.get('win_rate', 0) / 10
        p = min(r.get('profit_factor', 0), 5)
        return s + w + p - abs(r.get('max_drawdown', 50)) / 20

    results.sort(key=composite, reverse=True)

    # Top N
    top = results[:TOP_N]
    output = {
        'generated': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
        'top_n': TOP_N,
        'strategies': top,
        'all_results': results,
        'ranking_metric': 'composite = sharpe + win_rate/10 + profit_factor - max_dd/20'
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"[完成] Top {TOP_N} 策略已保存到: {OUTPUT_PATH}")
    print(f"{'='*60}")
    for i, s in enumerate(top):
        print(f"  #{i+1} {s['name']}: 夏普={s.get('sharpe',0)}, 胜率={s.get('win_rate',0)}%, 回撤={s.get('max_drawdown',0)}%, 收益={s.get('total_return',0)}%")

if __name__ == '__main__':
    main()
