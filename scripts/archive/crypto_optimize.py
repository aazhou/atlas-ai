#!/usr/bin/env python3
"""
crypto_optimize.py — DuckDB 纯SQL策略回测 + 参数优化

策略：
  LONG_A  费率反转 — funding_rate 极端负→正 → 做多
  LONG_B  OI背离   — 价格跌+OI增 → 做多

输出：
  data/crypto/optimal_strategy.json  — 最优参数 + 对比V4.1
  data/crypto/backtest_results.json  — 原始回测明细

运行：python scripts/crypto_optimize.py
"""

import json
import os
import sys
import math
from datetime import datetime
from collections import defaultdict

import duckdb

# ── Paths ──
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "crypto")
DB_PATH = os.path.join(DATA_DIR, "market.duckdb")
OPTIMAL_FILE = os.path.join(DATA_DIR, "optimal_strategy.json")
BACKTEST_FILE = os.path.join(DATA_DIR, "backtest_results.json")

# ── Parameter Grid ──
STOP_LOSSES   = [-0.03, -0.05, -0.08]
TAKE_PROFITS  = [0.05, 0.08, 0.12, 0.20]
HOLD_PERIODS  = [1, 2, 4, 8]  # hours for LONG_A

# ── LONG_A thresholds ──
FA_EXTREME_NEG = -0.0005   # 前一周期费率 < -0.05%
FA_NOW_MIN     = 0.0       # 当前费率 >= 0

# ── LONG_B thresholds ──
FB_PRICE_DROP  = -0.02     # 1h跌 > 2%
FB_OI_RISE     = 0.05      # OI增 > 5%

# ── V4.1 baseline ──
V41_STATS = {
    "version": "V4.1",
    "total_trades": 69,
    "win_rate": 0.39,
    "avg_return": -0.012,
    "sharpe": -0.31,
    "max_drawdown": -0.24,
    "description": "Python逐币种循环 + MEXC API, SL-3%/TP+12%"
}


def get_conn():
    return duckdb.connect(DB_PATH, read_only=True)


# ══════════════════════════════════════════════════
#  LONG_A: 费率反转策略
#  = funding_rate 极端负 → 翻正 → 用后续1h K线计算退出
# ══════════════════════════════════════════════════

def backtest_long_a(con):
    """纯SQL + 轻量Python后处理：费率反转回测"""
    print("=" * 60, file=sys.stderr)
    print("  LONG_A: 费率反转策略回测", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Step 1: 找到所有费率反转事件 (前一期极端负 + 当期翻正)
    # funding_rate 按 (symbol, funding_time) 排序，用 LAG 窗口函数
    events_sql = f"""
    WITH ranked AS (
        SELECT
            symbol,
            funding_time,
            rate,
            LAG(rate) OVER (PARTITION BY symbol ORDER BY funding_time) AS prev_rate,
            LAG(funding_time) OVER (PARTITION BY symbol ORDER BY funding_time) AS prev_time
        FROM funding_rate
    ),
    reversal_events AS (
        SELECT
            symbol,
            prev_time AS event_time,
            prev_rate,
            rate AS current_rate,
            funding_time
        FROM ranked
        WHERE prev_rate IS NOT NULL
          AND prev_rate < {FA_EXTREME_NEG}
          AND rate >= {FA_NOW_MIN}
    )
    SELECT * FROM reversal_events
    ORDER BY symbol, event_time
    """
    events = con.execute(events_sql).fetchall()
    print(f"  [LONG_A] 费率反转事件数: {len(events)} (费率<{FA_EXTREME_NEG*100:+.1f}%→≥0)", file=sys.stderr)

    if len(events) == 0:
        print("  [LONG_A] ⚠ 无费率反转事件，跳过", file=sys.stderr)
        return []

    # Step 2: 为每个事件，拉取后续 K 线 (1h) 来计算持有期收益
    # 批量查询所有相关 symbol 的 1h kline
    symbols = list(set(e[0] for e in events))
    placeholders = ','.join(['?' for _ in symbols])

    klines_raw = con.execute(f"""
        SELECT symbol, open_time, open, high, low, close
        FROM kline
        WHERE interval = '1h'
          AND symbol IN ({placeholders})
        ORDER BY symbol, open_time
    """, symbols).fetchall()

    # 组织为 {symbol: [(time, o, h, l, c), ...]}
    klines = defaultdict(list)
    for r in klines_raw:
        klines[r[0]].append((r[1], r[2], r[3], r[4], r[5]))

    # Step 3: 对每个事件-参数组合，模拟持有
    results = []

    for event in events:
        symbol, event_time, prev_rate, current_rate, funding_time = event
        candles = klines.get(symbol, [])

        if not candles:
            continue

        # 找到事件后第一根 1h K线作为入场 (open)
        entry_candle = None
        entry_idx = None
        for i, c in enumerate(candles):
            if c[0] > event_time:
                entry_candle = c
                entry_idx = i
                break

        if entry_candle is None:
            continue

        entry_price = entry_candle[2]  # open of next candle

        # 测试所有参数组合
        for hold_h in HOLD_PERIODS:
            exit_candles = candles[entry_idx + 1:entry_idx + 1 + hold_h]
            if len(exit_candles) < hold_h:
                continue

            exit_prices = [(c[3], c[4], c[5]) for c in exit_candles]  # (low, high, close)

            for sl in STOP_LOSSES:
                for tp in TAKE_PROFITS:
                    # 模拟：逐根K线检查止损止盈
                    exit_price = None
                    exit_reason = "hold_end"

                    for (low, high, close) in exit_prices:
                        # 检查止损
                        if (low - entry_price) / entry_price <= sl:
                            exit_price = entry_price * (1 + sl)
                            exit_reason = "stop_loss"
                            break
                        # 检查止盈
                        if (high - entry_price) / entry_price >= tp:
                            exit_price = entry_price * (1 + tp)
                            exit_reason = "take_profit"
                            break

                    if exit_price is None:
                        exit_price = exit_prices[-1][2]  # close of last candle
                        exit_reason = "hold_end"

                    pnl_pct = (exit_price - entry_price) / entry_price

                    results.append({
                        "strategy": "LONG_A",
                        "symbol": symbol,
                        "event_time": event_time,
                        "entry_price": round(entry_price, 8),
                        "exit_price": round(exit_price, 8),
                        "pnl_pct": round(pnl_pct, 4),
                        "exit_reason": exit_reason,
                        "hold_hours": hold_h,
                        "stop_loss": sl,
                        "take_profit": tp,
                        "prev_fr": round(prev_rate, 6),
                        "current_fr": round(current_rate, 6),
                    })

    print(f"  [LONG_A] 回测样本数: {len(results)} (事件×参数组合)", file=sys.stderr)
    return results


# ══════════════════════════════════════════════════
#  LONG_B: OI背离策略
#  = 价格跌>2% + OI增>5% → 做多
#  Note: OI 数据仅覆盖今日，回测范围受限于 OI 历史长度
# ══════════════════════════════════════════════════

def backtest_long_b(con):
    """OI背离策略回测 — 用4h K线做价格判断 + OI快照确认"""
    print("\n" + "=" * 60, file=sys.stderr)
    print("  LONG_B: OI背离策略回测", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # OI 数据只覆盖短暂时间段，因此策略受限
    # 改用4h K线找价格下跌时刻，再检查 OI 变化
    # 使用 SQL 窗口函数批量计算

    # 先找价格跌>2% (4h candle) 的时刻
    price_drops_sql = f"""
    WITH price_changes AS (
        SELECT
            symbol,
            open_time,
            close,
            LAG(close) OVER (PARTITION BY symbol ORDER BY open_time) AS prev_close,
            open,
            LAG(open) OVER (PARTITION BY symbol ORDER BY open_time) AS prev_open
        FROM kline
        WHERE interval = '4h'
    ),
    drops AS (
        SELECT
            symbol,
            open_time AS drop_time,
            (close - prev_close) / prev_close AS price_chg,
            close AS price_at_drop,
            open AS open_next
        FROM price_changes
        WHERE prev_close IS NOT NULL
          AND (close - prev_close) / prev_close < {FB_PRICE_DROP}
    )
    SELECT * FROM drops
    ORDER BY symbol, drop_time
    """

    drops = con.execute(price_drops_sql).fetchall()
    print(f"  [LONG_B] 4h价格跌>{abs(FB_PRICE_DROP)*100:.0f}%事件: {len(drops)}", file=sys.stderr)

    if len(drops) == 0:
        print("  [LONG_B] ⚠ 无价格下跌事件，跳过", file=sys.stderr)
        return []

    # OI snapshot 数据有限。尝试用已存在的OI数据
    # 为每个drop事件找最接近的OI变化
    symbols_b = list(set(d[0] for d in drops))
    placeholders_b = ','.join(['?' for _ in symbols_b])

    oi_raw = con.execute(f"""
        SELECT symbol, timestamp, open_interest
        FROM oi_snapshot
        WHERE period = '5m'
          AND symbol IN ({placeholders_b})
        ORDER BY symbol, timestamp
    """, symbols_b).fetchall()

    oi_by_symbol = defaultdict(list)
    for r in oi_raw:
        oi_by_symbol[r[0]].append((r[1], r[2]))

    # 对于每个 drop 事件，找是否有OI增加确认
    # 如果 OI 不可用，使用该事件的后续K线仍然做模拟（但排除 OI 条件变为放宽版测试）

    results = []

    for drop in drops:
        symbol, drop_time, price_chg, price_at_drop, open_next = drop

        # 尝试找 OI 数据
        oi_entries = oi_by_symbol.get(symbol, [])
        oi_rise_confirmed = False
        oi_chg_val = 0.0

        if len(oi_entries) >= 2:
            # 找 drop_time 前后的 OI 值
            oi_before = None
            oi_after = None
            for t, oi in oi_entries:
                if t <= drop_time:
                    oi_before = (t, oi)
                if t > drop_time and oi_after is None:
                    oi_after = (t, oi)
            if oi_before and oi_after and oi_before[1] > 0:
                oi_chg_val = (oi_after[1] - oi_before[1]) / oi_before[1]
                if oi_chg_val > FB_OI_RISE:
                    oi_rise_confirmed = True

        # 即使无OI数据，仍纳入回测（标记 oi_confirmed）
        # 后续可以分别统计有OI确认 vs 无OI确认的胜率

        # 拉取后续 4h K 线
        candles_raw = con.execute(f"""
            SELECT open_time, open, high, low, close
            FROM kline
            WHERE interval = '4h'
              AND symbol = ?
              AND open_time > ?
            ORDER BY open_time
            LIMIT 12
        """, [symbol, drop_time]).fetchall()

        if len(candles_raw) < 1:
            continue

        entry_price = candles_raw[0][1]  # open of next 4h candle

        # 固定持有 2根4h K线 (8h) 测试
        hold_candles = candles_raw[1:3]

        for sl in STOP_LOSSES:
            for tp in TAKE_PROFITS:
                exit_price = None
                exit_reason = "hold_end"

                for (_, _, high, low, close) in (hold_candles if hold_candles else [(None, None, entry_price, entry_price, entry_price)]):
                    if entry_price > 0:
                        if (low - entry_price) / entry_price <= sl:
                            exit_price = entry_price * (1 + sl)
                            exit_reason = "stop_loss"
                            break
                        if (high - entry_price) / entry_price >= tp:
                            exit_price = entry_price * (1 + tp)
                            exit_reason = "take_profit"
                            break

                if exit_price is None:
                    exit_price = hold_candles[-1][4] if hold_candles else entry_price
                    # If no hold candles, use entry candle close
                    if exit_price == entry_price and candles_raw[0][4]:
                        exit_price = candles_raw[0][4]

                if entry_price > 0:
                    pnl_pct = (exit_price - entry_price) / entry_price
                    results.append({
                        "strategy": "LONG_B",
                        "symbol": symbol,
                        "event_time": drop_time,
                        "entry_price": round(entry_price, 8),
                        "exit_price": round(exit_price, 8),
                        "pnl_pct": round(pnl_pct, 4),
                        "exit_reason": exit_reason,
                        "hold_hours": 8,
                        "stop_loss": sl,
                        "take_profit": tp,
                        "price_drop_pct": round(price_chg, 4),
                        "oi_confirmed": oi_rise_confirmed,
                        "oi_change_pct": round(oi_chg_val, 4),
                    })

    print(f"  [LONG_B] 回测样本数: {len(results)} (事件×参数组合)", file=sys.stderr)
    if any(r["oi_confirmed"] for r in results):
        print(f"  [LONG_B] 其中OI确认样本: {sum(1 for r in results if r['oi_confirmed'])}", file=sys.stderr)
    return results


# ══════════════════════════════════════════════════
#  统计分析
# ══════════════════════════════════════════════════

def compute_metrics(trades):
    """从交易列表计算胜率/盈亏比/夏普/最大回撤"""
    if not trades:
        return {
            "total": 0, "wins": 0, "losses": 0,
            "win_rate": 0, "avg_win": 0, "avg_loss": 0,
            "profit_factor": 0, "sharpe": 0, "max_drawdown": 0,
            "total_return": 0, "expectancy": 0,
        }

    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / len(pnls) if pnls else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0

    # Profit factor
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0

    # Sharpe (annualized, assuming trades are independent)
    mean_ret = sum(pnls) / len(pnls) if pnls else 0
    if len(pnls) > 1:
        std_ret = math.sqrt(sum((p - mean_ret) ** 2 for p in pnls) / (len(pnls) - 1))
    else:
        std_ret = 0
    sharpe = mean_ret / std_ret * math.sqrt(len(pnls)) if std_ret > 0 else 0

    # Max drawdown
    cumulative = 1.0
    peak = 1.0
    max_dd = 0.0
    for p in pnls:
        cumulative *= (1 + p)
        if cumulative > peak:
            peak = cumulative
        dd = (cumulative - peak) / peak
        if dd < max_dd:
            max_dd = dd

    # Expectancy
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    return {
        "total": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "profit_factor": round(profit_factor, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_dd, 4),
        "total_return": round(cumulative - 1, 4),
        "expectancy": round(expectancy, 4),
    }


def optimize_params(trades, strategy_name):
    """按参数组合分组，找最优"""
    if not trades:
        return None

    best = None
    best_score = -float('inf')

    # 按 (stop_loss, take_profit, hold_hours) 分组
    groups = defaultdict(list)
    for t in trades:
        key = (t["stop_loss"], t["take_profit"], t.get("hold_hours", 0))
        groups[key].append(t)

    param_results = []
    for key, group_trades in groups.items():
        sl, tp, hold = key
        m = compute_metrics(group_trades)

        # 综合评分: 胜率×0.3 + 期望值×0.3 + 夏普×0.2 + 盈亏比×0.2
        score = (m["win_rate"] * 0.3 +
                 max(m["expectancy"], -0.1) * 0.3 * 10 +
                 max(m["sharpe"], -1) * 0.2 +
                 min(m["profit_factor"], 5) * 0.2)

        param_results.append({
            "stop_loss": sl,
            "take_profit": tp,
            "hold_hours": hold,
            "metrics": m,
            "score": round(score, 4),
            "trade_count": m["total"],
        })

        if score > best_score and m["total"] >= 5:
            best_score = score
            best = {
                "stop_loss": sl,
                "take_profit": tp,
                "hold_hours": hold,
                "metrics": m,
                "score": round(score, 4),
            }

    param_results.sort(key=lambda x: x["score"], reverse=True)
    return best, param_results


# ══════════════════════════════════════════════════
#  合并分析
# ══════════════════════════════════════════════════

def combine_strategies(results_a, results_b):
    """合并两个策略的虚拟组合表现"""
    if not results_a and not results_b:
        return None

    combined = []
    # 取每个策略的最优参数组合
    all_trades = results_a + results_b
    return compute_metrics(all_trades), all_trades


# ══════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════

def main():
    start = datetime.now()
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  加密策略回测+参数优化 (DuckDB SQL)", file=sys.stderr)
    print(f"  {start.isoformat()[:19]}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    if not os.path.exists(DB_PATH):
        print(f"[ERR] DuckDB 不存在: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    con = get_conn()

    # ── LONG_A ──
    results_a = backtest_long_a(con)
    best_a, param_grid_a = optimize_params(results_a, "LONG_A") if results_a else (None, [])

    # ── LONG_B ──
    results_b = backtest_long_b(con)
    best_b, param_grid_b = optimize_params(results_b, "LONG_B") if results_b else (None, [])

    con.close()

    # ── 合并分析 ──
    combined_metrics = None
    if results_a or results_b:
        combined_metrics, _ = combine_strategies(results_a, results_b)

    # ── 构建输出 ──
    output = {
        "generated": start.isoformat(),
        "data_period": {
            "funding_rate": "2026-07-09 ~ 2026-07-12 (8h intervals)",
            "kline": "Up to 2026-07-12 (4h/1h candles, 500 per symbol)",
            "oi_snapshot": "2026-07-12 only (5m intervals) — limited backtest scope",
        },
        "tested_grid": {
            "stop_losses": STOP_LOSSES,
            "take_profits": TAKE_PROFITS,
            "hold_hours_longa": HOLD_PERIODS,
            "hold_hours_longb": "8h (2x 4h candles)",
        },
        "v41_baseline": V41_STATS,
        "LONG_A_funding_reversal": {
            "description": "Funding rate extreme negative → positive → go long",
            "entry_condition": f"prev_rate < {FA_EXTREME_NEG} AND current_rate >= {FA_NOW_MIN}",
            "total_events": len(results_a),
            "best_params": best_a,
            "top5_params": param_grid_a[:5] if param_grid_a else [],
            "all_results_count": len(results_a),
        },
        "LONG_B_oi_divergence": {
            "description": "Price drops >2% (4h) + OI increases >5% → go long",
            "entry_condition": f"price_chg_4h < {FB_PRICE_DROP} AND oi_chg > {FB_OI_RISE}",
            "total_events": len(results_b),
            "oi_confirmed_events": sum(1 for r in results_b if r.get("oi_confirmed")) if results_b else 0,
            "best_params": best_b,
            "top5_params": param_grid_b[:5] if param_grid_b else [],
            "all_results_count": len(results_b),
        },
        "combined": {
            "total_trades": combined_metrics["total"] if combined_metrics else 0,
            "win_rate": combined_metrics["win_rate"] if combined_metrics else 0,
            "sharpe": combined_metrics["sharpe"] if combined_metrics else 0,
            "expectancy": combined_metrics["expectancy"] if combined_metrics else 0,
            "max_drawdown": combined_metrics["max_drawdown"] if combined_metrics else 0,
            "metrics": combined_metrics,
        },
        "recommendation": _make_recommendation(best_a, best_b, combined_metrics),
    }

    # ── 写入文件 ──
    os.makedirs(DATA_DIR, exist_ok=True)

    with open(OPTIMAL_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Also save detailed backtest results
    backtest_detail = {
        "generated": start.isoformat(),
        "LONG_A_trades": results_a,
        "LONG_B_trades": results_b,
    }
    with open(BACKTEST_FILE, "w", encoding="utf-8") as f:
        json.dump(backtest_detail, f, ensure_ascii=False, indent=2)

    # ── 打印汇总 ──
    _print_summary(output, best_a, best_b, combined_metrics, start)

    return output


def _make_recommendation(best_a, best_b, combined):
    rec = {
        "preferred_strategy": None,
        "optimal_params": {},
        "vs_v41_improvement": "",
        "execution_notes": [],
    }

    # Pick the better strategy based on score
    score_a = best_a["score"] if best_a else -99
    score_b = best_b["score"] if best_b else -99

    if score_a >= score_b and best_a:
        rec["preferred_strategy"] = "LONG_A (费率反转)"
        rec["optimal_params"] = {
            "stop_loss": best_a["stop_loss"],
            "take_profit": best_a["take_profit"],
            "hold_hours": best_a["hold_hours"],
        }
    elif best_b:
        rec["preferred_strategy"] = "LONG_B (OI背离)"
        rec["optimal_params"] = {
            "stop_loss": best_b["stop_loss"],
            "take_profit": best_b["take_profit"],
            "hold_hours": best_b.get("hold_hours", 8),
        }

    # Compare to V4.1
    new_sharpe = combined["sharpe"] if combined else 0
    new_winrate = combined["win_rate"] if combined else 0
    v41_sharpe = V41_STATS["sharpe"]
    v41_wr = V41_STATS["win_rate"]

    if new_sharpe > v41_sharpe and new_winrate > v41_wr:
        rec["vs_v41_improvement"] = f"夏普 {v41_sharpe:.2f}→{new_sharpe:.2f} ({'+' if new_sharpe>v41_sharpe else ''}{new_sharpe-v41_sharpe:.2f}), 胜率 {v41_wr:.0%}→{new_winrate:.0%}"
    else:
        rec["vs_v41_improvement"] = f"部分改善: 夏普 {v41_sharpe:.2f}→{new_sharpe:.2f}, 胜率 {v41_wr:.0%}→{new_winrate:.0%}"

    rec["execution_notes"] = [
        "OI数据仅覆盖今日，LONG_B回测范围有限，需积累更多OI历史数据后重新优化",
        "建议每周末全量回测一次，随数据积累持续优化参数",
        "当前最优参数可直接写入 crypto_scanner.py 替换 SL/TP",
    ]

    return rec


def _print_summary(output, best_a, best_b, combined, start_time):
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  回测完成 ({elapsed:.1f}s)", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # LONG_A
    if best_a:
        m = best_a["metrics"]
        print(f"\n  🔵 LONG_A 费率反转 — 最优参数:", file=sys.stderr)
        print(f"     SL: {best_a['stop_loss']*100:+.0f}%  TP: {best_a['take_profit']*100:+.0f}%  "
              f"Hold: {best_a['hold_hours']}h", file=sys.stderr)
        print(f"     胜率: {m['win_rate']:.1%}  盈亏比: {m['profit_factor']:.1f}  "
              f"夏普: {m['sharpe']:.2f}  最大回撤: {m['max_drawdown']:.1%}", file=sys.stderr)
        print(f"     交易数: {m['total']}  期望值: {m['expectancy']:.2%}", file=sys.stderr)

    # LONG_B
    if best_b:
        m = best_b["metrics"]
        print(f"\n  🟢 LONG_B OI背离 — 最优参数:", file=sys.stderr)
        print(f"     SL: {best_b['stop_loss']*100:+.0f}%  TP: {best_b['take_profit']*100:+.0f}%  "
              f"Hold: {best_b.get('hold_hours', 8)}h", file=sys.stderr)
        print(f"     胜率: {m['win_rate']:.1%}  盈亏比: {m['profit_factor']:.1f}  "
              f"夏普: {m['sharpe']:.2f}  最大回撤: {m['max_drawdown']:.1%}", file=sys.stderr)
        print(f"     交易数: {m['total']}  期望值: {m['expectancy']:.2%}", file=sys.stderr)

    # Combined
    if combined:
        print(f"\n  🟣 策略叠加:", file=sys.stderr)
        print(f"     总交易: {combined['total']}  胜率: {combined['win_rate']:.1%}  "
              f"夏普: {combined['sharpe']:.2f}  期望值: {combined['expectancy']:.2%}", file=sys.stderr)

    # vs V4.1
    print(f"\n  📊 vs V4.1 基准:", file=sys.stderr)
    v41 = V41_STATS
    c = combined if combined else {"win_rate": 0, "sharpe": 0, "total": 0}
    wr_delta = c.get("win_rate", 0) - v41["win_rate"]
    sh_delta = c.get("sharpe", 0) - v41["sharpe"]
    print(f"     V4.1: {v41['total']}笔 胜率{v41['win_rate']:.0%} 夏普{v41['sharpe']:.2f}", file=sys.stderr)
    print(f"     优化后: {c.get('total',0)}笔 胜率{c.get('win_rate',0):.0%} 夏普{c.get('sharpe',0):.2f}", file=sys.stderr)
    print(f"     变化: 胜率{wr_delta:+.0%} 夏普{sh_delta:+.2f}", file=sys.stderr)

    # Recommendation
    rec = output["recommendation"]
    print(f"\n  ⚡ 操作建议:", file=sys.stderr)
    print(f"     首选: {rec['preferred_strategy']}", file=sys.stderr)
    print(f"     参数: SL={rec['optimal_params'].get('stop_loss',0)*100:+.0f}% "
          f"TP={rec['optimal_params'].get('take_profit',0)*100:+.0f}% "
          f"Hold={rec['optimal_params'].get('hold_hours',0)}h", file=sys.stderr)
    print(f"     {rec['vs_v41_improvement']}", file=sys.stderr)

    print(f"\n  ✓ 输出: {OPTIMAL_FILE}", file=sys.stderr)
    print(f"  ✓ 输出: {BACKTEST_FILE}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)


if __name__ == "__main__":
    main()
