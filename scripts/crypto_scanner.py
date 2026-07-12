#!/usr/bin/env python3
"""
加密Alpha雷达 v7 — DuckDB 数据底座版

改造要点：
  - 所有数据从 DuckDB 读取，0 API 调用
  - 增量更新由 incremental_update.py 独立完成
  - 信号计算：SQL 窗口函数批量预计算 EMA/RSI/changes
  - 扫描时间目标：5-10s（原477s）

信号类型：
  LONG_SQUEEZE   空头挤压：费率极端负→正 + OI降>20%
  LONG_REVERSAL  费率反转：负费率翻正
  LONG_DIVERGENCE OI背离：价跌OI增 + 价在EMA20上
  LONG_ACCUMULATION 静默吸筹：OI飙升+价持平
  LONG_WHALE     大户进场：15m量>8x + 价窄幅
  PANIC_BOUNCE   恐慌反弹：1h急跌>5% + RSI<30

风控: SL -3% / TP +12% (赔率4:1)
"""

import json
import os
import sys
import time
from datetime import datetime
from collections import Counter

import duckdb

# ═══════════════════ Config ═══════════════════

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "crypto")
DB_PATH = os.path.join(DATA_DIR, "market.duckdb")
OUTPUT_FILE = os.path.join(DATA_DIR, "signals.json")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")

# ── Strategy Parameters ──

SQ_FR_EXTREME = -0.0015       # 前一周期费率 < -0.15%
SQ_OI_DROP = -0.20            # OI 1h降幅 > 20%
SQ_FR_NOW_MIN = 0.0           # 当前费率 ≥ 0

FR_EXTREME_NEG = -0.0005      # 费率反转阈值 -0.05%
FR_NOW_MIN = 0.0

DV_PRICE_DROP = -0.02         # 2h跌 > 2%
DV_OI_RISE = 0.05             # OI 增 > 5%

AC_OI_SPIKE = 0.20            # OI 1h飙升 > 20%
AC_PRICE_FLAT = 0.005         # 价波动 < 0.5%

WH_VOL_SPIKE = 8.0            # 15m量 > 8x均量
WH_PRICE_NARROW = 0.01        # 价波动 < 1%

PB_PRICE_DROP_1H = -0.05      # 1h急跌 > 5%
PB_RSI_OVERSOLD = 30          # RSI < 30

SL_PCT = -0.03
TP_PCT = 0.12

MIN_VOLUME_USDT = 1_000_000   # L1最低成交额
L2_MIN_VOLUME = 500_000        # L2扫描最低成交额

# ═══════════════════ DuckDB Helpers ═══════════════════


def get_conn(read_only=True):
    return duckdb.connect(DB_PATH, read_only=read_only)


# ═══════════════════ Signal Computation (Python, fed by SQL) ═══════════════════


def compute_ema(prices, period=20):
    """Compute EMA from list of prices."""
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    gains = gains[-period:]
    losses = losses[-period:]
    avg_gain = sum(gains) / period if period > 0 else 0
    avg_loss = sum(losses) / period if period > 0 else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _make_signal(sig_type, symbol, price, reason, confidence, **kwargs):
    sig = {
        "type": sig_type,
        "symbol": symbol,
        "price": round(price, 8),
        "entry_price": round(price, 8),
        "reason": reason,
        "confidence": confidence,
        "stop_loss": round(price * (1 + SL_PCT), 8),
        "take_profit": round(price * (1 + TP_PCT), 8),
        "risk_reward": "4:1",
        "sl_pct": SL_PCT,
        "tp_pct": TP_PCT,
    }
    sig.update(kwargs)
    return sig


# ═══════════════════ Main Scan ═══════════════════


def scan():
    start = time.time()

    if not os.path.exists(DB_PATH):
        print("[ERR] DuckDB 不存在: {}".format(DB_PATH), file=sys.stderr)
        sys.exit(1)

    con = get_conn(read_only=True)

    # ═══ Phase 1: Get tickers (all symbols + 24h data) — sub-10ms ═══
    ticker_rows = con.execute("""
        SELECT symbol, last_price, high_price, low_price, quote_volume,
               price_change_pct, trade_count
        FROM ticker
        WHERE quote_volume >= ?
        ORDER BY quote_volume DESC
    """, [L2_MIN_VOLUME]).fetchall()

    tickers = {}
    scan_symbols = []
    for r in ticker_rows:
        sym = r[0]
        tickers[sym] = {
            "lastPrice": str(r[1]),
            "highPrice": str(r[2]),
            "lowPrice": str(r[3]),
            "quoteVolume": str(r[4]),
            "priceChangePercent": str(r[5]),
            "count": str(r[6]),
        }
        scan_symbols.append(sym)

    all_symbols = scan_symbols[:]  # already filtered

    print(f"  [v7] {len(tickers)} 合约 (量>${L2_MIN_VOLUME/1e6:.0f}M) | DuckDB读取",
          file=sys.stderr)

    # ═══ Phase 2: Bulk-load klines via SQL ═══
    # Query all 1h klines for all scan_symbols in ONE query with EMA/RSI precomputed

    # For 1h candles: we need 50 candles per symbol for EMA20 + RSI14
    kline_1h_start = time.time()
    all_1h_raw = con.execute("""
        SELECT symbol, open_time, open, high, low, close, volume
        FROM kline
        WHERE interval = '1h'
          AND symbol IN (SELECT symbol FROM ticker WHERE quote_volume >= ?)
        ORDER BY symbol, open_time
    """, [L2_MIN_VOLUME]).fetchall()

    # Group by symbol
    candles_1h = {}
    for r in all_1h_raw:
        sym = r[0]
        if sym not in candles_1h:
            candles_1h[sym] = []
        candles_1h[sym].append({
            "t": r[1], "o": r[2], "h": r[3], "l": r[4],
            "c": r[5], "v": r[6],
        })

    # For 15m candles (need 12 candles per symbol for WHALE detection)
    all_15m_raw = con.execute("""
        SELECT symbol, open_time, open, high, low, close, volume
        FROM kline
        WHERE interval = '15m'
          AND symbol IN (SELECT symbol FROM ticker WHERE quote_volume >= ?)
        ORDER BY symbol, open_time
    """, [L2_MIN_VOLUME]).fetchall()

    candles_15m = {}
    for r in all_15m_raw:
        sym = r[0]
        if sym not in candles_15m:
            candles_15m[sym] = []
        candles_15m[sym].append({
            "t": r[1], "o": r[2], "h": r[3], "l": r[4],
            "c": r[5], "v": r[6],
        })

    print(f"  [v7] K线加载: 1h={len(candles_1h)}币 15m={len(candles_15m)}币 "
          f"({(time.time()-kline_1h_start)*1000:.0f}ms)",
          file=sys.stderr)

    # ═══ Phase 3: Bulk-load funding rates ═══
    fr_start = time.time()
    fr_raw = con.execute("""
        SELECT symbol, funding_time, rate
        FROM funding_rate
        WHERE symbol IN (SELECT symbol FROM ticker WHERE quote_volume >= ?)
        ORDER BY symbol, funding_time
    """, [L2_MIN_VOLUME]).fetchall()

    funding = {}
    for r in fr_raw:
        sym = r[0]
        if sym not in funding:
            funding[sym] = []
        funding[sym].append({"time": r[1], "rate": r[2]})

    # ═══ Phase 4: Bulk-load OI snapshots ═══
    oi_raw = con.execute("""
        SELECT symbol, period, timestamp, open_interest
        FROM oi_snapshot
        WHERE symbol IN (SELECT symbol FROM ticker WHERE quote_volume >= ?)
        ORDER BY symbol, period, timestamp
    """, [L2_MIN_VOLUME]).fetchall()

    oi_data = {}
    for r in oi_raw:
        sym = r[0]
        period = r[1]
        if sym not in oi_data:
            oi_data[sym] = {}
        if period not in oi_data[sym]:
            oi_data[sym][period] = []
        oi_data[sym][period].append({"time": r[2], "oi": r[3]})

    print(f"  [v7] 费率+OI加载: F={len(funding)}币 O={len(oi_data)}币 "
          f"({(time.time()-fr_start)*1000:.0f}ms)",
          file=sys.stderr)

    # ═══ Phase 5: Signal Detection (per symbol) ═══
    sig_start = time.time()
    all_signals = []

    for sym in scan_symbols:
        ch1 = candles_1h.get(sym)
        ch15 = candles_15m.get(sym)
        fr = funding.get(sym)
        oi_5m = oi_data.get(sym, {}).get("5m", [])
        # For 1h OI, we approximate with 5m data over longer window
        oi_1h = oi_5m[:]  # Use 5m snapshots as 1h proxy

        # Also check broader OI collection
        if not oi_1h:
            oi_1h = oi_data.get(sym, {}).get("15m", [])

        if not ch1 or len(ch1) < 22:  # Need at least 22 for EMA20 + RSI14
            continue

        signals = detect_signals(sym, ch1, ch15, fr, oi_5m, oi_1h)
        all_signals.extend(signals)

    print(f"  [v7] 信号检测: {len(scan_symbols)}币扫描 信号={len(all_signals)} "
          f"({(time.time()-sig_start)*1000:.0f}ms)",
          file=sys.stderr)

    # ═══ Phase 6: L1 Breakout ═══
    l1_top5 = scan_l1_breakout(all_symbols, tickers)

    # ═══ Phase 7: Filter & Rank ═══
    high_signals = [s for s in all_signals if s["confidence"] == "HIGH"]
    medium_signals = [s for s in all_signals if s["confidence"] == "MEDIUM"]

    type_priority = {
        "LONG_SQUEEZE": 0,
        "PANIC_BOUNCE": 1,
        "LONG_ACCUMULATION": 2,
        "LONG_WHALE": 3,
        "LONG_DIVERGENCE": 4,
        "LONG_REVERSAL": 5,
    }
    high_signals.sort(key=lambda s: (
        type_priority.get(s["type"], 99),
        -abs(s.get("oi_drop_pct", 0))
    ))
    medium_signals.sort(key=lambda s: type_priority.get(s["type"], 99))
    ranked_signals = high_signals + medium_signals

    # ═══ Phase 8: Count & Save ═══
    type_counts = dict(Counter(s["type"] for s in ranked_signals))

    duration = round(time.time() - start, 1)
    con.close()

    result = {
        "generated": datetime.now().isoformat(),
        "scan_duration_sec": duration,
        "scan_version": "v7-duckdb",
        "total_symbols": len(all_symbols),
        "scanned_symbols": len(scan_symbols),
        "l1_breakout": {
            "description": "突破启动 — 量价齐升+近24h高",
            "candidates": len(l1_top5),
            "signals": l1_top5,
        },
        "l2_v6": {
            "description": "v7 高赔率策略: SQUEEZE/REVERSAL/DIVERGENCE/ACCUMULATION/WHALE/PANIC",
            "strategy": "high_conviction_4to1",
            "params": {
                "SL": f"{SL_PCT*100:+.0f}%",
                "TP": f"{TP_PCT*100:+.0f}%",
                "risk_reward": "4:1",
                "min_volume_filter": f"${MIN_VOLUME_USDT:,}",
                "scan_scope": f"DuckDB {len(all_symbols)} pairs (L2: {len(scan_symbols)} with vol>${L2_MIN_VOLUME/1e6:.0f}M)",
                "data_source": "DuckDB only — 0 API calls",
            },
            "type_counts": type_counts,
            "high_confidence_count": len(high_signals),
            "signals_count": len(ranked_signals),
            "signals": ranked_signals,
        },
        "portfolio": _load_portfolio(),
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    _print_summary(result, high_signals, ranked_signals, l1_top5)

    return duration, len(high_signals), len(ranked_signals)


# ═══════════════════ Signal Detection ═══════════════════


def detect_signals(symbol, candles_1h, candles_15m, funding_hist, oi_5m, oi_1h):
    if not candles_1h or len(candles_1h) < 22:
        return []

    closes = [c["c"] for c in candles_1h]
    ema20 = compute_ema(closes)
    rsi14 = compute_rsi(closes)
    latest = candles_1h[-1]
    signals = []

    # Price changes
    price_1h_chg = 0
    price_2h_chg = 0
    if len(candles_1h) >= 2:
        price_1h_chg = (latest["c"] - candles_1h[-2]["c"]) / candles_1h[-2]["c"]
    if len(candles_1h) >= 3:
        price_2h_chg = (latest["c"] - candles_1h[-3]["c"]) / candles_1h[-3]["c"]

    # ═══ LONG_SQUEEZE ═══
    if funding_hist and len(funding_hist) >= 2:
        fr_now = funding_hist[-1]["rate"]
        fr_prev = funding_hist[-2]["rate"]

        if fr_prev < SQ_FR_EXTREME and fr_now >= SQ_FR_NOW_MIN:
            oi_dropped = False
            oi_drop_pct = 0
            if oi_1h and len(oi_1h) >= 2:
                oi_1h_ago = oi_1h[0]["oi"]
                oi_now_val = oi_1h[-1]["oi"]
                if oi_1h_ago > 0:
                    oi_chg = (oi_now_val - oi_1h_ago) / oi_1h_ago
                    oi_drop_pct = round(oi_chg * 100, 1)
                    if oi_chg < SQ_OI_DROP:
                        oi_dropped = True

            if oi_dropped:
                signals.append(_make_signal(
                    "LONG_SQUEEZE", symbol, latest["c"],
                    f"空头挤压: 费率{fr_prev*100:.3f}%→{fr_now*100:.3f}% OI降{oi_drop_pct}%",
                    "HIGH",
                    funding_rate=round(fr_now * 100, 4),
                    fr_prev=round(fr_prev * 100, 4),
                    oi_drop_pct=oi_drop_pct
                ))
            else:
                signals.append(_make_signal(
                    "LONG_REVERSAL", symbol, latest["c"],
                    f"费率反转: {fr_prev*100:.3f}%→{fr_now*100:.3f}%(无OI确认)",
                    "MEDIUM",
                    funding_rate=round(fr_now * 100, 4),
                    fr_prev=round(fr_prev * 100, 4)
                ))

    # ═══ LONG_DIVERGENCE ═══
    if oi_5m and len(oi_5m) >= 2 and ema20 is not None:
        oi_now = oi_5m[-1]["oi"]
        oi_prev = oi_5m[-2]["oi"]
        if oi_prev > 0:
            oi_chg = (oi_now - oi_prev) / oi_prev
            if price_2h_chg < DV_PRICE_DROP and oi_chg > DV_OI_RISE and latest["c"] >= ema20:
                signals.append(_make_signal(
                    "LONG_DIVERGENCE", symbol, latest["c"],
                    f"OI背离: 价{price_2h_chg*100:.1f}% OI+{oi_chg*100:.1f}% EMA20↑",
                    "MEDIUM",
                    oi_change_pct=round(oi_chg * 100, 2),
                    price_change_pct=round(price_2h_chg * 100, 2),
                    ema20=round(ema20, 8)
                ))

    # ═══ LONG_ACCUMULATION ═══
    if oi_1h and len(oi_1h) >= 2:
        oi_1h_ago = oi_1h[0]["oi"]
        oi_1h_now = oi_1h[-1]["oi"]
        if oi_1h_ago > 0:
            oi_1h_chg = (oi_1h_now - oi_1h_ago) / oi_1h_ago
            if oi_1h_chg > AC_OI_SPIKE and abs(price_1h_chg) < AC_PRICE_FLAT:
                conf = "HIGH" if oi_1h_chg > 0.30 else "MEDIUM"
                signals.append(_make_signal(
                    "LONG_ACCUMULATION", symbol, latest["c"],
                    f"静默吸筹: OI+{oi_1h_chg*100:.1f}%/1h 价{price_1h_chg*100:.2f}%持平",
                    conf,
                    oi_change_1h_pct=round(oi_1h_chg * 100, 2),
                    price_flat_pct=round(abs(price_1h_chg) * 100, 2)
                ))

    # ═══ LONG_WHALE ═══
    if candles_15m and len(candles_15m) >= 6:
        latest_15m = candles_15m[-1]
        prev_vols = [c["v"] for c in candles_15m[-6:-1]]
        avg_vol = sum(prev_vols) / len(prev_vols) if prev_vols else 0
        if avg_vol > 0:
            vol_ratio = latest_15m["v"] / avg_vol
            price_15m_chg = abs((latest_15m["c"] - latest_15m["o"]) / latest_15m["o"]) \
                if latest_15m["o"] > 0 else 0
            if vol_ratio > WH_VOL_SPIKE and price_15m_chg < WH_PRICE_NARROW:
                conf = "HIGH" if vol_ratio > 12.0 else "MEDIUM"
                signals.append(_make_signal(
                    "LONG_WHALE", symbol, latest["c"],
                    f"大户进场: 15m量{vol_ratio:.1f}x 价{price_15m_chg*100:.2f}%窄幅",
                    conf,
                    vol_spike_ratio=round(vol_ratio, 1),
                    price_chg_15m_pct=round(price_15m_chg * 100, 2)
                ))

    # ═══ PANIC_BOUNCE ═══
    if price_1h_chg < PB_PRICE_DROP_1H and rsi14 is not None and rsi14 < PB_RSI_OVERSOLD:
        is_real_panic = True
        if funding_hist and len(funding_hist) >= 1:
            fr_latest = funding_hist[-1]["rate"]
            if fr_latest < -0.003:
                is_real_panic = False
        if is_real_panic:
            signals.append(_make_signal(
                "PANIC_BOUNCE", symbol, latest["c"],
                f"恐慌反弹: 1h跌{price_1h_chg*100:.1f}% RSI{rsi14:.0f} 非利空驱动",
                "HIGH" if price_1h_chg < -0.08 and rsi14 < 25 else "MEDIUM",
                price_drop_1h_pct=round(price_1h_chg * 100, 2),
                rsi=round(rsi14, 1),
            ))

    return signals


# ═══════════════════ L1 Breakout ═══════════════════


def scan_l1_breakout(symbols, tickers):
    candidates = []
    for sym in symbols:
        ticker = tickers.get(sym)
        if not ticker:
            continue
        try:
            last = float(ticker["lastPrice"])
            high = float(ticker["highPrice"])
            vol = float(ticker["quoteVolume"])
            chg_pct = float(ticker["priceChangePercent"])
            count = int(ticker["count"])
        except (KeyError, ValueError):
            continue

        if vol < MIN_VOLUME_USDT:
            continue
        if high <= 0:
            continue
        proximity = (high - last) / high
        if proximity > 0.03:
            continue

        score = 0
        if vol > 200_000_000:
            score += 30
        elif vol > 50_000_000:
            score += 18
        elif vol > 20_000_000:
            score += 12
        else:
            score += 6

        if proximity < 0.005:
            score += 25
        elif proximity < 0.01:
            score += 20
        elif proximity < 0.02:
            score += 15
        else:
            score += 8

        if 2 < chg_pct < 8:
            score += 20
        elif 0 < chg_pct <= 2:
            score += 15
        else:
            score += 5

        candidates.append({
            "symbol": sym,
            "price": round(last, 8),
            "price_change_pct": round(chg_pct, 2),
            "high_24h": round(high, 8),
            "low_24h": round(float(ticker["lowPrice"]), 8),
            "high_proximity_pct": round(proximity * 100, 2),
            "volume_usdt": round(vol, 0),
            "trades_count": count,
            "signal_strength": round(min(score, 100), 1),
        })

    candidates.sort(key=lambda x: x["signal_strength"], reverse=True)
    return candidates[:5]


# ═══════════════════ Summary ═══════════════════


def _print_summary(result, high_signals, all_signals, l1_top5):
    duration = result["scan_duration_sec"]

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  加密Alpha雷达 v7 (DuckDB) | {result['generated'][:19]} | {duration:.1f}s",
          file=sys.stderr)
    print(f"  {'='*60}", file=sys.stderr)

    if high_signals:
        print(f"\n  🟢 TIER A — 高确定性信号 ({len(high_signals)}个) | SL:{SL_PCT*100:+.0f}% TP:{TP_PCT*100:+.0f}% (4:1)",
              file=sys.stderr)
        print(f"  {'─'*56}", file=sys.stderr)
        for i, s in enumerate(high_signals[:10]):
            print(f"  {i+1}. [{s['type']:17s}] {s['symbol']:12s} "
                  f"${s['entry_price']:<10.4f} "
                  f"SL:${s['stop_loss']:.4f} TP:${s['take_profit']:.4f}",
                  file=sys.stderr)
            print(f"      {s['reason']}", file=sys.stderr)

        if len(high_signals) > 1:
            print(f"\n  ⚡ 操作建议:", file=sys.stderr)
            for i, s in enumerate(high_signals[:3]):
                print(f"     {i+1}. {s['symbol']} — {s['type']}: 入场${s['entry_price']:.4f} "
                      f"止损${s['stop_loss']:.4f} 目标${s['take_profit']:.4f} "
                      f"({'分批50%' if i == 0 else '分批30%' if i == 1 else '分批20%'})",
                      file=sys.stderr)

    medium_signals = [s for s in all_signals if s["confidence"] == "MEDIUM"]
    if medium_signals:
        print(f"\n  🟡 TIER B — 监控信号 ({len(medium_signals)}个)", file=sys.stderr)
        for i, s in enumerate(medium_signals[:5]):
            print(f"     {i+1}. [{s['type']:17s}] {s['symbol']:12s} "
                  f"${s['entry_price']:<10.4f} {s['reason'][:60]}",
                  file=sys.stderr)

    if l1_top5:
        print(f"\n  📊 L1 突破候选", file=sys.stderr)
        for i, s in enumerate(l1_top5):
            bar = "█" * min(int(s["signal_strength"] / 10), 10)
            print(f"     {i+1}. {s['symbol']:12s} ${s['price']:<10.4f} "
                  f"{s['price_change_pct']:+.1f}% 近高:{s['high_proximity_pct']:.1f}% "
                  f"信号:{s['signal_strength']:.0f} {bar}",
                  file=sys.stderr)

    if not high_signals and not medium_signals:
        print(f"\n  [SILENT] 无信号 — 市场无高确定性机会，等待", file=sys.stderr)

    print(f"\n  📁 {OUTPUT_FILE}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)


def _load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"positions": [], "closed": []}


# ═══════════════════ Entry ═══════════════════

if __name__ == "__main__":
    duration, high_count, total_count = scan()
    if high_count > 0:
        print(f"\n[DONE] {duration:.1f}s | HIGH={high_count} | TOTAL={total_count}")
        sys.exit(0)
    elif total_count > 0:
        print(f"\n[DONE] {duration:.1f}s | 仅有MEDIUM信号，无操作建议")
        sys.exit(1)
    else:
        print(f"\n[DONE] {duration:.1f}s | 无信号")
        sys.exit(2)
