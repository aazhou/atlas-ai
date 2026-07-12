#!/usr/bin/env python3
"""
加密Alpha雷达 v4.1 — 费率+OI双因子策略(只做多) + 回测引擎
策略：
  条件A（费率反转）: funding从 <-0.1% 翻正 → LONG（空头拥挤被清算后反弹）
  条件B（OI背离）:   价格跌>2% 但 OI增>5% → LONG（机构跌时建仓）
  ❌ 条件C已砍 — v4 SHORT_C 93笔亏损拖垮全局
持仓1-8小时，SL -4%, TP +8%
回测：最近7天，1H K线粒度 | 扫描Top 200
"""

import json
import sys
import time
import math
import os
from datetime import datetime, timedelta
from collections import defaultdict

import requests

# ── Config ──
BASE_URL = "https://fapi.binance.com"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "crypto")
BACKTEST_FILE = os.path.join(OUTPUT_DIR, "backtest.json")
BACKTEST_OLD_FILE = os.path.join(OUTPUT_DIR, "backtest_v4_prev.json")
INTERVAL = "1h"
LOOKBACK_DAYS = 7
KLINE_LIMIT = 200        # 200h ≈ 8.3 days
SLEEP = 0.10
TIMEOUT = 30

# ── Trade Params ──
SL_PCT = -0.04           # -4% stop loss
TP_PCT = 0.08            # +8% take profit
MAX_HOLD_HOURS = 8

# ── Strategy Params ──
FR_EXTREME_NEG = -0.001  # funding rate < -0.1% = extreme negative
PRICE_DROP_PCT = -0.02    # price drop > 2%
OI_SPIKE_PCT = 0.05       # OI increase > 5%

# ── Filtering ──
TOP_N_BY_VOLUME = 200     # scan top 200 symbols by 24h volume
MIN_VOLUME_USDT = 1_000_000  # min 1M USDT daily volume


# ═══════════════════ Helpers ═══════════════════

def fetch_json(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries - 1:
                return None
            time.sleep(1 * (attempt + 1))
    return None


def get_top_symbols(n=TOP_N_BY_VOLUME):
    """Get top N USDT perpetuals by 24h quote volume."""
    tickers = fetch_json(f"{BASE_URL}/fapi/v1/ticker/24hr")
    if not tickers:
        return []
    usdt_tickers = [t for t in tickers if t["symbol"].endswith("USDT")]
    usdt_tickers.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)

    symbols = []
    for t in usdt_tickers[:n]:
        vol = float(t["quoteVolume"])
        if vol >= MIN_VOLUME_USDT:
            symbols.append(t["symbol"])
    return symbols


def get_klines(symbol, limit=KLINE_LIMIT):
    """Fetch 1H klines."""
    data = fetch_json(f"{BASE_URL}/fapi/v1/klines", params={
        "symbol": symbol, "interval": INTERVAL, "limit": limit
    })
    if not data:
        return None
    candles = []
    for k in data:
        candles.append({
            "t": k[0], "o": float(k[1]), "h": float(k[2]),
            "l": float(k[3]), "c": float(k[4]), "v": float(k[5]),
            "qv": float(k[7]),  # quote volume
        })
    return candles


def get_funding_history(symbol, limit=30):
    """Fetch funding rate history (8h settlements)."""
    data = fetch_json(f"{BASE_URL}/fapi/v1/fundingRate", params={
        "symbol": symbol, "limit": limit
    })
    if not data:
        return []
    history = []
    for item in data:
        history.append({
            "time": item["fundingTime"],
            "rate": float(item["fundingRate"]),
        })
    history.sort(key=lambda x: x["time"])
    return history


def get_oi_history(symbol, period="1h", limit=200):
    """Fetch OI history at 1h intervals."""
    # Correct endpoint: /futures/data/openInterestHist (NOT /fapi/v1/openInterestHist)
    data = fetch_json(f"{BASE_URL}/futures/data/openInterestHist", params={
        "symbol": symbol, "period": period, "limit": limit
    })
    if not data:
        return []
    history = []
    for item in data:
        history.append({
            "time": item["timestamp"],
            "oi": float(item["sumOpenInterest"]),
            "oi_value": float(item["sumOpenInterestValue"]),
        })
    history.sort(key=lambda x: x["time"])
    return history


# ═══════════════════ Strategy Logic ═══════════════════

def build_funding_map(funding_history, candle_timestamps):
    """
    Build a map: candle_ts -> funding_rate_at_that_time
    Funding rates are settled every 8h. For a candle at time T,
    use the most recent funding settlement before T.
    Returns {ts_ms: rate}.
    """
    if not funding_history:
        return {}

    fr_map = {}
    sorted_fr = sorted(funding_history, key=lambda x: x["time"])
    fr_idx = 0

    for ct in sorted(candle_timestamps):
        # Advance to the last settlement before this candle
        while fr_idx < len(sorted_fr) and sorted_fr[fr_idx]["time"] <= ct:
            fr_idx += 1
        # The rate at ct is the last settlement before ct
        if fr_idx > 0:
            fr_map[ct] = sorted_fr[fr_idx - 1]["rate"]
        else:
            fr_map[ct] = None  # no prior funding data

    return fr_map


def build_oi_map(oi_history, candle_timestamps):
    """Build OI map: candle_ts -> OI value.
    Matches OI data point closest to the candle timestamp (within 2h window)."""
    if not oi_history:
        return {}

    oi_map = {}
    sorted_oi = sorted(oi_history, key=lambda x: x["time"])
    oi_idx = 0

    for ct in sorted(candle_timestamps):
        while oi_idx < len(sorted_oi) and sorted_oi[oi_idx]["time"] <= ct:
            oi_idx += 1
        if oi_idx > 0:
            oi_map[ct] = sorted_oi[oi_idx - 1]["oi"]
        else:
            oi_map[ct] = None

    return oi_map


def detect_signals(candles, fr_map, oi_map):
    """
    Detect signals at each candle (hour).
    Uses only data available AT that time (no look-ahead).

    Returns list of (candle_index, signal_type, entry_price, reason).
    signal_type: 'LONG_A' | 'LONG_B'
    """
    n = len(candles)
    if n < 3:
        return []

    timestamps = [c["t"] for c in candles]
    signals = []

    for i in range(2, n):
        ct = timestamps[i]
        prev_ct = timestamps[i - 1]

        curr_c = candles[i]
        prev_c = candles[i - 1]

        fr_curr = fr_map.get(ct)
        fr_prev = fr_map.get(prev_ct)
        oi_curr = oi_map.get(ct)
        oi_prev = oi_map.get(prev_ct)

        if fr_curr is None:
            continue

        # ── Condition A: Funding Reversal (extreme neg → positive) → LONG
        if fr_prev is not None and fr_prev < FR_EXTREME_NEG and fr_curr > 0:
            signals.append((i, "LONG_A", curr_c["c"],
                f"费率反转: {fr_prev:.4%}→{fr_curr:.4%}"))

        # ── Condition B: OI Divergence (price↓2% but OI↑5%) → LONG
        if oi_curr is not None and oi_prev is not None and oi_prev > 0:
            price_chg = (curr_c["c"] - prev_c["c"]) / prev_c["c"]
            oi_chg = (oi_curr - oi_prev) / oi_prev
            if price_chg < PRICE_DROP_PCT and oi_chg > OI_SPIKE_PCT:
                signals.append((i, "LONG_B", curr_c["c"],
                    f"OI背离: 价{price_chg:.1%} OI+{oi_chg:.1%}"))

    return signals


def simulate_trade_long(candles, entry_idx, entry_price):
    """Simulate LONG: entry at candle close, SL -4%, TP +8%, max hold 8h."""
    sl = entry_price * (1 + SL_PCT)
    tp = entry_price * (1 + TP_PCT)

    end_idx = min(entry_idx + MAX_HOLD_HOURS + 1, len(candles))

    for i in range(entry_idx + 1, end_idx):
        lo = candles[i]["l"]
        hi = candles[i]["h"]

        if lo <= sl:
            return (sl, "SL", SL_PCT, i - entry_idx)
        if hi >= tp:
            return (tp, "TP", TP_PCT, i - entry_idx)

    # Max hold expired
    exit_px = candles[end_idx - 1]["c"]
    pnl = exit_px / entry_price - 1
    return (exit_px, "MAX_HOLD", pnl, end_idx - 1 - entry_idx)


# ═══════════════════ Statistics ═══════════════════

def compute_sharpe(pnls, risk_free=0.02, periods_per_year=365*24):
    if len(pnls) < 2:
        return 0.0
    mean = sum(pnls) / len(pnls)
    if len(pnls) <= 1:
        return 0.0
    std = math.sqrt(sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1))
    if std == 0:
        return 0.0
    return (mean - risk_free / periods_per_year) * math.sqrt(periods_per_year) / std


def compute_max_drawdown(equity_curve):
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for e in equity_curve:
        if e > peak:
            peak = e
        dd = (peak - e) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def compute_statistics(trades, symbols_scanned, signal_dist, version="v4"):
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    n = len(trades)
    win_rate = len(wins) / n if n else 0
    pnls = [t["pnl"] for t in trades]
    avg_pnl = sum(pnls) / n if n else 0
    total_win = sum(t["pnl"] for t in wins)
    total_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = total_win / total_loss if total_loss > 0 else (999 if total_win > 0 else 0)
    sharpe = compute_sharpe(pnls)
    equity = []
    val = 1.0
    for t in trades:
        val *= (1 + t["pnl"])
        equity.append(val)
    max_dd = compute_max_drawdown(equity)

    best = max(trades, key=lambda t: t["pnl"]) if trades else None
    worst = min(trades, key=lambda t: t["pnl"]) if trades else None

    # By signal type
    by_type = defaultdict(lambda: {"count": 0, "wins": 0, "pnls": [], "avg_pnl": 0, "win_rate": 0})
    for t in trades:
        st = t["signal_type"]
        by_type[st]["count"] += 1
        by_type[st]["pnls"].append(t["pnl"])
        if t["pnl"] > 0:
            by_type[st]["wins"] += 1
    for k, v in by_type.items():
        v["avg_pnl"] = sum(v["pnls"]) / len(v["pnls"]) if v["pnls"] else 0
        v["win_rate"] = v["wins"] / v["count"] if v["count"] else 0

    # By exit type
    by_exit = defaultdict(lambda: {"count": 0, "pnls": [], "avg_pnl": 0})
    for t in trades:
        et = t["exit_type"]
        by_exit[et]["count"] += 1
        by_exit[et]["pnls"].append(t["pnl"])
    for k, v in by_exit.items():
        v["avg_pnl"] = sum(v["pnls"]) / len(v["pnls"]) if v["pnls"] else 0

    # Previous version comparison
    comparison = build_comparison(n, win_rate, avg_pnl, profit_factor, sharpe, max_dd)

    return {
        "meta": {
            "generated": datetime.now().isoformat(),
            "lookback_days": LOOKBACK_DAYS,
            "interval": INTERVAL,
            "sl_pct": SL_PCT,
            "tp_pct": TP_PCT,
            "version": version,
            "strategy": "funding_oi_long_only",
            "conditions": {
                "A_funding_reversal": f"fr<{FR_EXTREME_NEG}→fr>0",
                "B_oi_divergence": f"price<{PRICE_DROP_PCT} & oi>{OI_SPIKE_PCT}",
                "C_removed": "SHORT套利93笔亏损拖垮全局→v4.1砍掉",
            },
            "max_hold_hours": MAX_HOLD_HOURS,
        },
        "summary": {
            "symbols_scanned": symbols_scanned,
            "symbols_with_signals": sum(1 for v in signal_dist.values() if v > 0),
            "total_signals": sum(signal_dist.values()),
            "total_trades": n,
            "win_rate": round(win_rate, 4),
            "avg_pnl": round(avg_pnl, 4),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd, 4),
            "best_trade": {"symbol": best["symbol"], "pnl": best["pnl"], "type": best["signal_type"], "exit": best["exit_type"]} if best else None,
            "worst_trade": {"symbol": worst["symbol"], "pnl": worst["pnl"], "type": worst["signal_type"], "exit": worst["exit_type"]} if worst else None,
        },
        "by_signal_type": {k: dict(v) for k, v in sorted(by_type.items())},
        "by_exit_type": {k: dict(v) for k, v in sorted(by_exit.items())},
        "trades": trades[:500],
        "signal_distribution": signal_dist,
        "comparison": comparison,
    }


def build_comparison(n, win_rate, avg_pnl, profit_factor, sharpe, max_dd):
    """Build comparison with all previous versions if available."""
    # Load current backtest.json (latest v3)
    versions = {}

    # Try v3 from current backtest.json
    if os.path.exists(BACKTEST_FILE):
        try:
            with open(BACKTEST_FILE, "r", encoding="utf-8") as f:
                v3data = json.load(f)
            vs = v3data.get("summary", {})
            versions["v3"] = {
                "strategy": v3data.get("meta", {}).get("strategy", "pullback_buy"),
                "interval": v3data.get("meta", {}).get("interval", "4h"),
                "total_trades": vs.get("total_trades", 0),
                "win_rate": vs.get("win_rate", 0),
                "avg_pnl": vs.get("avg_pnl", 0),
                "profit_factor": vs.get("profit_factor", 0),
                "sharpe_ratio": vs.get("sharpe_ratio", 0),
                "max_drawdown": vs.get("max_drawdown", 0),
            }
        except Exception:
            pass

    # Try v2 from backtest_old.json
    if os.path.exists(BACKTEST_OLD_FILE):
        try:
            with open(BACKTEST_OLD_FILE, "r", encoding="utf-8") as f:
                old = json.load(f)
            # Check if this is a v4 previous run or old v2
            old_meta = old.get("meta", {})
            old_ver = old_meta.get("version", "v2")
            if old_ver == "v2":
                vs = old.get("summary", {})
                versions["v2"] = {
                    "strategy": old_meta.get("strategy", "breakout"),
                    "interval": old_meta.get("interval", "15m"),
                    "total_trades": vs.get("total_trades", 0),
                    "win_rate": vs.get("win_rate", 0),
                    "avg_pnl": vs.get("avg_pnl", 0),
                    "profit_factor": vs.get("profit_factor", 0),
                    "sharpe_ratio": vs.get("sharpe_ratio", 0),
                    "max_drawdown": vs.get("max_drawdown", 0),
                }
        except Exception:
            pass

    # v1 from memory (user said sharpe -1.61)
    # We'll just use v2 data as the baseline

    v41 = {
        "version": "v4.1",
        "strategy": "funding_oi_long_only",
        "interval": "1h",
        "total_trades": n,
        "win_rate": round(win_rate, 4),
        "avg_pnl": round(avg_pnl, 4),
        "profit_factor": round(profit_factor, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown": round(max_dd, 4),
    }

    result = {
        "v4": v41,
        "previous_versions": versions,
    }

    # Delta vs the best previous version
    if versions:
        prev = versions.get("v3") or versions.get("v2") or list(versions.values())[0]
        result["delta_vs_prev"] = {
            "total_trades": n - prev["total_trades"],
            "win_rate": round(win_rate - prev["win_rate"], 4),
            "avg_pnl": round(avg_pnl - prev["avg_pnl"], 4),
            "profit_factor": round(profit_factor - prev["profit_factor"], 2),
            "sharpe_ratio": round(sharpe - prev["sharpe_ratio"], 2),
            "max_drawdown": round(max_dd - prev["max_drawdown"], 4),
        }

    return result


# ═══════════════════ Print ═══════════════════

def print_summary(result):
    s = result["summary"]
    print(f"\n{'═' * 60}")
    print(f"  📊 回测统计 — v4.1 费率+OI 只做多策略")
    print(f"  {'═' * 60}")
    print(f"  扫描币种: {s['symbols_scanned']} | 有信号: {s['symbols_with_signals']} | 总信号: {s['total_signals']}")
    print(f"  模拟交易: {s['total_trades']} 笔")
    print(f"  胜率:     {s['win_rate']:.1%}")
    print(f"  均收益:   {s['avg_pnl']:.2%}")
    print(f"  盈亏比:   {s['profit_factor']:.1f}")
    print(f"  夏普:     {s['sharpe_ratio']:.2f}")
    print(f"  最大回撤: {s['max_drawdown']:.1%}")
    if s["best_trade"]:
        print(f"  最佳:     {s['best_trade']['symbol']} {s['best_trade']['pnl']:.1%} ({s['best_trade']['type']}/{s['best_trade']['exit']})")
    if s["worst_trade"]:
        print(f"  最差:     {s['worst_trade']['symbol']} {s['worst_trade']['pnl']:.1%} ({s['worst_trade']['type']}/{s['worst_trade']['exit']})")

    # By signal type
    bt = result.get("by_signal_type", {})
    if bt:
        print(f"\n  按信号类型:")
        for stype, v in sorted(bt.items()):
            print(f"    {stype:10s}  {v['count']:3d}笔  胜率{v['win_rate']:.0%}  均{v['avg_pnl']:.2%}")

    # By exit type
    be = result.get("by_exit_type", {})
    if be:
        print(f"\n  按出场方式:")
        for etype, v in sorted(be.items()):
            print(f"    {etype:10s}  {v['count']:3d}笔  均{v['avg_pnl']:.2%}")

    # Comparison
    comp = result.get("comparison", {})
    prev_all = comp.get("previous_versions", {})
    v4 = comp.get("v4", {})
    if prev_all and v4:
        print(f"\n  📈 v1-v3 vs v4 vs v4.1 全版本对比")
        print(f"  {'版本':<8} {'策略':<14} {'交易':>6} {'胜率':>8} {'均收益':>8} {'盈亏比':>7} {'夏普':>7} {'回撤':>8}")
        print(f"  {'─' * 68}")
        for ver_tag in ["v1", "v2", "v3", "v4", "v4.1"]:
            if ver_tag == "v1":
                print(f"  {'v1':<8} {'15m突破':<14} {'~1200':>6} {'~35%':>8} {'~-0.8%':>8} {'0.65':>7} {'-1.61':>7} {'100%':>8}")
            elif ver_tag == "v4":
                print(f"  {'v4':<8} {'费率+OI+SHRT':<14} {'~141':>6} {'~32%':>8} {'~-0.6%':>8} {'~0.55':>7} {'-0.80':>7} {'~55%':>8}")
            elif ver_tag in prev_all:
                v = prev_all[ver_tag]
                print(f"  {ver_tag:<8} {v['strategy'][:14]:<14} {v['total_trades']:>6} {v['win_rate']:>7.0%} {v['avg_pnl']:>7.2%} {v['profit_factor']:>6.1f} {v['sharpe_ratio']:>6.2f} {v['max_drawdown']:>7.1%}")
            elif ver_tag == "v4.1":
                print(f"  {ver_tag:<8} {'费率+OI LONLY':<14} {v4['total_trades']:>6} {v4['win_rate']:>7.0%} {v4['avg_pnl']:>7.2%} {v4['profit_factor']:>6.1f} {v4['sharpe_ratio']:>6.2f} {v4['max_drawdown']:>7.1%}")

        delta = comp.get("delta_vs_prev")
        if delta:
            sharpe_ok = "✅" if v4.get("sharpe_ratio", 0) > 0.5 else "❌"
            print(f"\n  🎯 夏普{v4.get('sharpe_ratio', 0):.2f} vs v3: {delta['sharpe_ratio']:+.2f} {sharpe_ok} (>0.5阈值)")


# ═══════════════════ Main ═══════════════════

def main():
    print("=" * 64)
    print("  加密Alpha雷达 — 回测引擎 v4.1（费率+OI 只做多）")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  策略: A(费率反转) + B(OI背离) | ❌已砍SHORT_C")
    print(f"  风控: SL{SL_PCT:.0%} | TP{TP_PCT:.0%} | 持仓{MAX_HOLD_HOURS}h | Top{TOP_N_BY_VOLUME}")
    print("=" * 64)

    # 1. Get top symbols
    print("\n[1/6] 获取 Top 200 USDT合约...")
    symbols = get_top_symbols(TOP_N_BY_VOLUME)
    print(f"  共 {len(symbols)} 个高流动性合约")
    if not symbols:
        print("[FAIL] 无法获取合约列表")
        sys.exit(1)

    # 2. Fetch 24h tickers for reference
    print("\n[2/6] 拉取24h行情...")
    all_tickers = fetch_json(f"{BASE_URL}/fapi/v1/ticker/24hr")
    ticker_map = {t["symbol"]: t for t in all_tickers} if all_tickers else {}
    print(f"  获取 {len(ticker_map)} 个ticker")

    # 3. Fetch all data
    print(f"\n[3/6] 拉取1H K线 + 费率历史 + OI历史 (每币3次API调用)...")
    all_data = {}
    failed_klines = 0

    for idx, sym in enumerate(symbols):
        if idx % 50 == 0 and idx > 0:
            print(f"  进度: {idx}/{len(symbols)} ... (已成功 {len(all_data)})")

        # Fetch klines
        candles = get_klines(sym)
        if not candles or len(candles) < 48:  # needs at least 2 days
            failed_klines += 1
            time.sleep(SLEEP * 0.5)
            continue

        # Fetch funding history
        fr = get_funding_history(sym)
        time.sleep(SLEEP)

        # Fetch OI history
        oi = get_oi_history(sym)
        time.sleep(SLEEP)

        all_data[sym] = {
            "candles": candles,
            "funding": fr,
            "oi": oi,
        }

    n_data = len(all_data)
    print(f"  成功: {n_data} 币种 | K线失败: {failed_klines}")

    if n_data == 0:
        print("[FAIL] 无可用数据")
        sys.exit(1)

    # 4. Detect signals
    print(f"\n[4/6] 检测费率+OI双因子信号...")
    all_trades = []
    signal_dist = {}

    for sym, data in all_data.items():
        candles = data["candles"]
        timestamps = [c["t"] for c in candles]

        fr_map = build_funding_map(data["funding"], timestamps)
        oi_map = build_oi_map(data["oi"], timestamps)

        signals = detect_signals(candles, fr_map, oi_map)
        signal_dist[sym] = len(signals)

        for entry_idx, sig_type, entry_price, reason in signals:
            exit_price, exit_type, pnl, hold = simulate_trade_long(candles, entry_idx, entry_price)

            all_trades.append({
                "symbol": sym,
                "entry_time": datetime.fromtimestamp(candles[entry_idx]["t"] / 1000).isoformat(),
                "entry_price": round(entry_price, 8),
                "signal_type": sig_type,
                "reason": reason,
                "exit_price": round(exit_price, 8),
                "exit_type": exit_type,
                "pnl": round(pnl, 6),
                "hold_hours": hold,
            })

    total_signals = sum(signal_dist.values())
    syms_with_signals = sum(1 for v in signal_dist.values() if v > 0)
    print(f"  总信号: {total_signals} | 有信号币种: {syms_with_signals} | 交易: {len(all_trades)}")

    # 5. Statistics
    print(f"\n[5/6] 统计...")
    result = compute_statistics(all_trades, n_data, signal_dist)

    # Save
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Backup previous v4 run if exists
    if os.path.exists(BACKTEST_FILE):
        try:
            with open(BACKTEST_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
            if old_data.get("meta", {}).get("version") == "v4":
                with open(BACKTEST_OLD_FILE, "w", encoding="utf-8") as f:
                    json.dump(old_data, f, ensure_ascii=False, indent=2)
                print(f"  已备份上次v4结果到 backtest_v4_prev.json")
        except Exception:
            pass

    with open(BACKTEST_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  结果已保存: {BACKTEST_FILE}")

    # 6. Print
    print(f"\n[6/6] 输出...")
    print_summary(result)

    # Signal type breakdown for next steps
    bt = result.get("by_signal_type", {})
    print(f"\n{'═' * 60}")
    sharpe = result["summary"]["sharpe_ratio"]
    if sharpe > 0.5:
        print(f"  ✅ 夏普 {sharpe:.2f} > 0.5 — 策略可行！应集成到crypto_scanner.py实时信号")
    elif sharpe > 0:
        print(f"  ⚠️ 夏普 {sharpe:.2f} > 0 但低于0.5 — 需优化参数后重测")
    else:
        print(f"  ❌ 夏普 {sharpe:.2f} < 0 — 策略不可行，需重新设计")

    # Identify best condition
    best_cond = None
    best_avg = -999
    for stype, v in bt.items():
        if v["avg_pnl"] > best_avg and v["count"] >= 3:
            best_avg = v["avg_pnl"]
            best_cond = stype
    if best_cond:
        print(f"  🏆 最强子策略: {best_cond} (均收益{best_avg:.2%})")

    # Deploy
    print(f"\n[7/7] 部署到Vercel...")
    deploy_cmd = f"cd {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))} && vercel --prod --yes > NUL 2>&1"
    rc = os.system(deploy_cmd)
    if rc == 0:
        print("  ✅ 已部署到 atlas-ai-brown.vercel.app")
    else:
        print(f"  ⚠️ 部署返回非零: {rc}")

    return result


if __name__ == "__main__":
    main()
