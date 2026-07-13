#!/usr/bin/env python3
"""加密Alpha雷达 — 回测引擎 v3（4H回调买入策略）
策略核心：
  1. 趋势: EMA21 > EMA50（仅做多）
  2. 回调: 前一根K线最低价触及EMA21±2%区域
  3. 缩量: 当前K线成交量 < 均量50%（缩量回调=健康）
  4. 确认: 当前K线收盘 > EMA21（回调企稳）
  5. 排除前10大盘币
扫描Binance全量USDT合约4H K线(近14天)，检测回调信号并模拟交易。
输出: 胜率/盈亏比/夏普比率/最大回撤 + v2对比
"""

import json
import sys
import time
import math
import os
from datetime import datetime
from collections import defaultdict

import requests

# ── Config ──
BASE_URL = "https://fapi.binance.com"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "crypto")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "backtest.json")
OLD_FILE = os.path.join(OUTPUT_DIR, "backtest_old.json")
INTERVAL = "4h"
LOOKBACK_DAYS = 14
LIMIT = 200  # ~33 days of 4H candles (enough for EMA50 warmup + 14d lookback)
SLEEP = 0.15

# Trade params (v3)
SL_PCT = -0.08          # -8% stop loss
TP1_PCT = 0.12          # +12% first target
TP2_PCT = 0.25          # +25% second target
TP1_WEIGHT = 0.50       # 50% at TP1, 50% runners
MAX_HOLD_CANDLES = 42   # 7 days of 4H candles

# ── Strategy Params ──
EMA_FAST = 21
EMA_SLOW = 50
EMA_ZONE_PCT = 0.02      # ±2% from EMA21
VOL_CONTRACTION_RATIO = 0.50  # volume < 50% of average
VOL_LOOKBACK = 20         # SMA period for average volume

# 排除前10大盘币
EXCLUDE_LARGE_CAP = {
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "DOTUSDT", "LTCUSDT", "LINKUSDT",
    "AVAXUSDT", "MATICUSDT", "UNIUSDT", "ATOMUSDT",
}


# ── Helpers ──
def fetch_json(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries - 1:
                print(f"  [ERR] {url}: {e}", file=sys.stderr)
                return None
            time.sleep(1 * (attempt + 1))
    return None


def get_all_symbols():
    """Get all USDT-margined perpetual symbols, excluding large caps."""
    data = fetch_json(f"{BASE_URL}/fapi/v1/exchangeInfo")
    if not data:
        return []
    symbols = []
    for s in data.get("symbols", []):
        if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING":
            sym = s["symbol"]
            if sym not in EXCLUDE_LARGE_CAP:
                symbols.append(sym)
    return sorted(symbols)


def get_klines(symbol, interval=INTERVAL, limit=LIMIT):
    data = fetch_json(f"{BASE_URL}/fapi/v1/klines", params={
        "symbol": symbol, "interval": interval, "limit": limit
    })
    if not data:
        return None
    candles = []
    for k in data:
        candles.append({
            "t": k[0],
            "o": float(k[1]),
            "h": float(k[2]),
            "l": float(k[3]),
            "c": float(k[4]),
            "v": float(k[5]),
            "qv": float(k[7]),
        })
    return candles


def compute_ema(prices, period):
    if len(prices) < period:
        return [None] * len(prices)
    ema = [None] * len(prices)
    sma = sum(prices[:period]) / period
    ema[period - 1] = sma
    alpha = 2.0 / (period + 1)
    for i in range(period, len(prices)):
        ema[i] = alpha * prices[i] + (1 - alpha) * ema[i - 1]
    return ema


# ── Signal Detection (v3: pullback-buy) ──
def detect_signals_v3(candles):
    """Detect pullback-buy signals:
    Conditions:
      1. EMA21 > EMA50 at signal candle (bullish trend)
      2. Previous candle's low touched EMA21 ±2% zone
      3. Current candle volume < 50% of 20-period average volume (contraction)
      4. Current candle close > EMA21 (pullback holds)
    Returns list of (candle_index, entry_price).
    """
    min_warmup = max(VOL_LOOKBACK, EMA_SLOW) + 1
    if len(candles) < min_warmup + 2:
        return []

    closes = [c["c"] for c in candles]
    ema_fast = compute_ema(closes, EMA_FAST)
    ema_slow = compute_ema(closes, EMA_SLOW)

    signals = []
    for i in range(min_warmup, len(candles) - 1):
        # Must have EMAs
        if ema_fast[i] is None or ema_slow[i] is None:
            continue
        if ema_fast[i - 1] is None:
            continue

        c = candles[i]
        prev = candles[i - 1]

        # ── Filter 1: Trend — EMA21 > EMA50
        if ema_fast[i] <= ema_slow[i]:
            continue

        # ── Filter 2: Pullback — prev candle low touched EMA21 ±2%
        ema21_val = ema_fast[i - 1]
        zone_low = ema21_val * (1 - EMA_ZONE_PCT)
        zone_high = ema21_val * (1 + EMA_ZONE_PCT)
        if prev["l"] > zone_high or prev["l"] < zone_low:
            continue  # Did NOT pull back to EMA21 zone

        # ── Filter 3: Volume contraction — current vol < 50% of avg
        if i < VOL_LOOKBACK:
            continue
        avg_vol = sum(candles[j]["v"] for j in range(i - VOL_LOOKBACK, i)) / VOL_LOOKBACK
        if avg_vol <= 0:
            continue
        if c["v"] >= avg_vol * VOL_CONTRACTION_RATIO:
            continue  # Volume not contracted enough

        # ── Filter 4: Confirmation — close > EMA21 (pullback holds)
        if c["c"] <= ema_fast[i]:
            continue

        entry = c["c"]
        signals.append((i, entry))

    return signals


# ── Trade Simulation ──
def simulate_trade(candles, entry_idx, entry_price):
    """Simulate a trade with 4H candles.
    SL: -8%, TP1: +12%, TP2: +25%
    TP1_WEIGHT = 0.5 (50% exits at TP1, 50% runs to TP2)
    """
    sl_price = entry_price * (1 + SL_PCT)
    tp1_price = entry_price * (1 + TP1_PCT)
    tp2_price = entry_price * (1 + TP2_PCT)
    tp1_hit = False

    end_idx = min(entry_idx + MAX_HOLD_CANDLES + 1, len(candles))

    for i in range(entry_idx + 1, end_idx):
        low = candles[i]["l"]
        high = candles[i]["h"]

        if low <= sl_price:
            sl_exit = sl_price
            if tp1_hit:
                pnl = TP1_WEIGHT * TP1_PCT + (1 - TP1_WEIGHT) * SL_PCT
                return (sl_exit, "TP1+SL", pnl, i - entry_idx)
            else:
                return (sl_exit, "SL", SL_PCT, i - entry_idx)

        if not tp1_hit and high >= tp1_price:
            tp1_hit = True

        if high >= tp2_price:
            if tp1_hit:
                pnl = TP1_WEIGHT * TP1_PCT + (1 - TP1_WEIGHT) * TP2_PCT
                return (tp2_price, "TP2", pnl, i - entry_idx)
            else:
                return (tp2_price, "TP2", TP2_PCT, i - entry_idx)

        if tp1_hit and i == end_idx - 1:
            exit_price = candles[i]["c"]
            pnl = TP1_WEIGHT * TP1_PCT + (1 - TP1_WEIGHT) * (exit_price / entry_price - 1)
            return (exit_price, "TP1+EOD", pnl, i - entry_idx)

    exit_price = candles[end_idx - 1]["c"]
    pnl = exit_price / entry_price - 1
    if tp1_hit:
        pnl = TP1_WEIGHT * TP1_PCT + (1 - TP1_WEIGHT) * pnl
        return (exit_price, "TP1+MAX", pnl, end_idx - 1 - entry_idx)
    return (exit_price, "MAX_HOLD", pnl, end_idx - 1 - entry_idx)


# ── Statistics ──
def compute_sharpe(pnls, risk_free=0.02):
    if len(pnls) < 2:
        return 0.0
    mean = sum(pnls) / len(pnls)
    std = math.sqrt(sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)) if len(pnls) > 1 else 0.01
    if std == 0:
        return 0.0
    return (mean - risk_free / 365) * math.sqrt(365) / std


def compute_max_drawdown(equity_curve):
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for e in equity_curve:
        if e > peak:
            peak = e
        dd = (peak - e) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd


def build_equity_curve(trades):
    curve = [1.0]
    for t in trades:
        curve.append(curve[-1] * (1 + t["pnl"]))
    return curve


def compute_statistics(trades, symbols, signal_count, version="v3"):
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / len(trades) if trades else 0
    pnls = [t["pnl"] for t in trades]
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0
    total_win = sum(t["pnl"] for t in wins)
    total_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = total_win / total_loss if total_loss > 0 else 0
    sharpe = compute_sharpe(pnls)
    equity = build_equity_curve(trades)
    max_dd = compute_max_drawdown(equity)

    best = max(trades, key=lambda t: t["pnl"]) if trades else None
    worst = min(trades, key=lambda t: t["pnl"]) if trades else None

    # By symbol
    by_symbol = defaultdict(lambda: {"trades": 0, "wins": 0, "pnls": [], "avg_pnl": 0, "win_rate": 0})
    for t in trades:
        sym = t["symbol"]
        by_symbol[sym]["trades"] += 1
        by_symbol[sym]["pnls"].append(t["pnl"])
        if t["pnl"] > 0:
            by_symbol[sym]["wins"] += 1
    for sym, v in by_symbol.items():
        v["avg_pnl"] = sum(v["pnls"]) / len(v["pnls"]) if v["pnls"] else 0
        v["win_rate"] = v["wins"] / v["trades"] if v["trades"] else 0
        v["pnls"] = [round(p, 6) for p in v["pnls"]]

    # By exit type
    by_exit = defaultdict(lambda: {"count": 0, "pnls": [], "avg_pnl": 0})
    for t in trades:
        et = t["exit_type"]
        by_exit[et]["count"] += 1
        by_exit[et]["pnls"].append(t["pnl"])
    for et, v in by_exit.items():
        v["avg_pnl"] = sum(v["pnls"]) / len(v["pnls"]) if v["pnls"] else 0
        v["pnls"] = [round(p, 6) for p in v["pnls"]]

    # Load old comparison (v2)
    comparison = None
    if os.path.exists(OLD_FILE):
        try:
            with open(OLD_FILE, "r", encoding="utf-8") as f:
                old = json.load(f)
            old_summary = old.get("summary", {})
            comparison = {
                "old": {
                    "version": old.get("meta", {}).get("version", "v2"),
                    "interval": old.get("meta", {}).get("interval", "15m"),
                    "total_trades": old_summary.get("total_trades", 0),
                    "win_rate": old_summary.get("win_rate", 0),
                    "avg_pnl": old_summary.get("avg_pnl", 0),
                    "profit_factor": old_summary.get("profit_factor", 0),
                    "sharpe_ratio": old_summary.get("sharpe_ratio", 0),
                    "max_drawdown": old_summary.get("max_drawdown", 0),
                },
                "new": {
                    "version": version,
                    "interval": INTERVAL,
                    "total_trades": len(trades),
                    "win_rate": round(win_rate, 4),
                    "avg_pnl": round(avg_pnl, 4),
                    "profit_factor": round(profit_factor, 2),
                    "sharpe_ratio": round(sharpe, 2),
                    "max_drawdown": round(max_dd, 4),
                },
                "delta": {
                    "total_trades": len(trades) - old_summary.get("total_trades", 0),
                    "win_rate": round(round(win_rate, 4) - old_summary.get("win_rate", 0), 4),
                    "avg_pnl": round(round(avg_pnl, 4) - old_summary.get("avg_pnl", 0), 4),
                    "profit_factor": round(round(profit_factor, 2) - old_summary.get("profit_factor", 0), 2),
                    "sharpe_ratio": round(round(sharpe, 2) - old_summary.get("sharpe_ratio", 0), 2),
                    "max_drawdown": round(round(max_dd, 4) - old_summary.get("max_drawdown", 0), 4),
                }
            }
        except Exception as e:
            print(f"  [WARN] Failed to load old backtest: {e}")

    return {
        "meta": {
            "generated": datetime.now().isoformat(),
            "lookback_days": LOOKBACK_DAYS,
            "interval": INTERVAL,
            "sl_pct": SL_PCT,
            "tp1_pct": TP1_PCT,
            "tp2_pct": TP2_PCT,
            "version": version,
            "strategy": "pullback_buy",
            "filters": {
                "ema_fast": EMA_FAST,
                "ema_slow": EMA_SLOW,
                "ema_zone_pct": EMA_ZONE_PCT,
                "vol_contraction_ratio": VOL_CONTRACTION_RATIO,
                "vol_lookback": VOL_LOOKBACK,
                "exclude_large_cap": len(EXCLUDE_LARGE_CAP),
            }
        },
        "summary": {
            "total_symbols": len(symbols),
            "symbols_with_signals": sum(1 for v in signal_count.values() if v > 0),
            "total_signals": sum(signal_count.values()),
            "total_trades": len(trades),
            "win_rate": round(win_rate, 4),
            "avg_pnl": round(avg_pnl, 4),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd, 4),
            "best_trade": {"symbol": best["symbol"], "pnl": best["pnl"], "type": best["exit_type"]} if best else None,
            "worst_trade": {"symbol": worst["symbol"], "pnl": worst["pnl"], "type": worst["exit_type"]} if worst else None,
        },
        "by_symbol": {k: dict(v) for k, v in sorted(by_symbol.items(), key=lambda x: x[1]["avg_pnl"], reverse=True)},
        "by_exit_type": dict(by_exit),
        "trades": trades if len(trades) <= 500 else trades[:500],
        "signal_distribution": {sym: signal_count.get(sym, 0) for sym in symbols if signal_count.get(sym, 0) > 0},
        "comparison": comparison,
    }


def print_summary(result):
    s = result["summary"]
    print(f"\n{'─' * 55}")
    print(f"  📊 回测统计 (v3 4H回调买入策略)")
    print(f"  {'─' * 55}")
    print(f"  扫描币种: {s['total_symbols']} | 有信号: {s['symbols_with_signals']} | 总信号: {s['total_signals']}")
    print(f"  模拟交易: {s['total_trades']} 笔")
    print(f"  胜率:     {s['win_rate']:.1%}")
    print(f"  均收益:   {s['avg_pnl']:.2%}")
    print(f"  盈亏比:   {s['profit_factor']:.1f}")
    print(f"  夏普:     {s['sharpe_ratio']:.2f}")
    print(f"  最大回撤: {s['max_drawdown']:.1%}")
    if s["best_trade"]:
        print(f"  最佳:     {s['best_trade']['symbol']} {s['best_trade']['pnl']:.1%} ({s['best_trade']['type']})")
    if s["worst_trade"]:
        print(f"  最差:     {s['worst_trade']['symbol']} {s['worst_trade']['pnl']:.1%} ({s['worst_trade']['type']})")

    # Comparison
    comp = result.get("comparison")
    if comp:
        old = comp["old"]
        new = comp["new"]
        d = comp["delta"]
        print(f"\n  📈 v2(15m突破) → v3(4H回调) 对比")
        print(f"  {'指标':<14} {'v2 15m突破':>14} {'v3 4H回调':>14} {'变化':>12}")
        print(f"  {'─' * 56}")
        print(f"  {'交易笔数':<14} {old['total_trades']:>14} {new['total_trades']:>14} {d['total_trades']:>+12}")
        print(f"  {'胜率':<14} {old['win_rate']:>13.1%} {new['win_rate']:>13.1%} {d['win_rate']:>+12.1%}")
        print(f"  {'均收益':<14} {old['avg_pnl']:>13.2%} {new['avg_pnl']:>13.2%} {d['avg_pnl']:>+12.2%}")
        print(f"  {'盈亏比':<14} {old['profit_factor']:>13.1f} {new['profit_factor']:>13.1f} {d['profit_factor']:>+12.1f}")
        print(f"  {'夏普':<14} {old['sharpe_ratio']:>13.2f} {new['sharpe_ratio']:>13.2f} {d['sharpe_ratio']:>+12.2f}")
        print(f"  {'最大回撤':<14} {old['max_drawdown']:>13.1%} {new['max_drawdown']:>13.1%} {d['max_drawdown']:>+12.1%}")

    # Top 5 symbols
    by_sym = result.get("by_symbol", {})
    top5 = sorted(by_sym.items(), key=lambda x: x[1]["avg_pnl"], reverse=True)[:5]
    if top5:
        print(f"\n  🏆 Top 5 币种 (按均收益):")
        for sym, v in top5:
            print(f"    {sym:12s}  {v['trades']:2d}笔  胜率{v['win_rate']:.0%}  均{v['avg_pnl']:.2%}")


# ── Main ──
def main():
    print("=" * 60)
    print("  加密Alpha雷达 — 回测引擎 v3（4H回调买入策略）")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  策略: 回调EMA{EMA_FAST}±{EMA_ZONE_PCT:.0%} | 缩量<{VOL_CONTRACTION_RATIO:.0%}均量 | EMA{EMA_FAST}>EMA{EMA_SLOW}")
    print(f"  风控: SL{SL_PCT:.0%} | TP1{TP1_PCT:.0%} | TP2{TP2_PCT:.0%}")
    print(f"  排除: {len(EXCLUDE_LARGE_CAP)}大盘币 (BTC/ETH/BNB/...)")
    print("=" * 60)

    # 1. Get symbols
    print("\n[1/4] 获取合约列表（排除大盘币）...")
    symbols = get_all_symbols()
    print(f"  共 {len(symbols)} 个USDT永续合约 (已排除 {len(EXCLUDE_LARGE_CAP)} 个大盘币)")
    if not symbols:
        print("[FAIL] 无法获取合约列表，退出")
        sys.exit(1)

    # 2. Fetch 4H klines
    print(f"\n[2/4] 拉取4H K线 (每币 {LIMIT} 根)...")
    all_klines = {}
    failed = 0
    for idx, sym in enumerate(symbols):
        if idx % 50 == 0:
            print(f"  进度: {idx}/{len(symbols)} ...")
        candles = get_klines(sym, interval="4h", limit=LIMIT)
        if candles and len(candles) >= 70:
            all_klines[sym] = candles
        else:
            failed += 1
        time.sleep(SLEEP)
    print(f"  成功: {len(all_klines)} | K线失败/不足: {failed}")

    if not all_klines:
        print("[FAIL] 无可用K线数据")
        sys.exit(1)

    # 3. Detect signals + simulate
    print(f"\n[3/4] 扫描回调买入信号 + 模拟交易...")
    all_trades = []
    signal_count = {}
    trades = []

    for sym, candles in all_klines.items():
        signals = detect_signals_v3(candles)
        signal_count[sym] = len(signals)
        for entry_idx, entry_price in signals:
            exit_price, exit_type, pnl, hold = simulate_trade(candles, entry_idx, entry_price)
            trades.append({
                "symbol": sym,
                "entry_idx": entry_idx,
                "entry_price": round(entry_price, 8),
                "entry_time": datetime.fromtimestamp(candles[entry_idx]["t"] / 1000).isoformat(),
                "exit_price": round(exit_price, 8),
                "exit_type": exit_type,
                "pnl": round(pnl, 6),
                "hold_candles": hold,
                "hold_hours": round(hold * 4, 1),
            })

    total_signals = sum(signal_count.values())
    syms_with_signals = sum(1 for v in signal_count.values() if v > 0)
    print(f"  总信号: {total_signals} | 有信号的币种: {syms_with_signals} | 模拟交易: {len(trades)}")

    # 4. Statistics + Save
    print(f"\n[4/4] 统计与保存...")
    result = compute_statistics(trades, symbols, signal_count, version="v3")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[DONE] 结果已保存: {OUTPUT_FILE}")

    print_summary(result)
    return result


if __name__ == "__main__":
    main()
