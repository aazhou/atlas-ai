"""
Generate K-line chart data for ALL coins in backtest_detailed.json.
One file per coin+interval with prices + markers tagged by strategy.
Output: data/crypto/chart_{symbol}_{interval}.json
"""
import json
import duckdb
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(r"C:\Users\admin\aazhous-projects\atlas-ai\data\crypto")
DB_PATH = DATA_DIR / "market.duckdb"
BACKTEST_PATH = DATA_DIR / "backtest_detailed.json"
OUT_DIR = DATA_DIR

INTERVALS = ["5m", "15m", "1h"]
INTERVAL_SECONDS = {"5m": 300, "15m": 900, "1h": 3600}


def load_klines(db_path, duck_symbol, interval):
    """Load klines from DuckDB, convert to {t, o, h, l, c} format."""
    conn = duckdb.connect(str(db_path), read_only=True)
    rows = conn.execute("""
        SELECT open_time, open, high, low, close
        FROM kline
        WHERE symbol = ? AND interval = ?
        ORDER BY open_time ASC
    """, [duck_symbol, interval]).fetchall()
    conn.close()

    klines = []
    for row in rows:
        klines.append({
            "t": row[0] // 1000,  # ms -> seconds for lightweight-charts
            "o": round(row[1], 8),
            "h": round(row[2], 8),
            "l": round(row[3], 8),
            "c": round(row[4], 8),
        })
    return klines


def parse_time(time_str):
    """Parse trade entry/exit time string to UTC timestamp.
    Handles '2026-07-04 16:30:00' and '2026-07-04 16:30'."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(time_str, fmt)
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    return None


def find_kline_time(trade_ts, klines, interval_sec):
    """Find the kline whose time window contains the trade timestamp."""
    for k in klines:
        if k["t"] <= trade_ts < k["t"] + interval_sec:
            return k["t"]
    # Fallback: nearest kline before trade
    best = None
    for k in klines:
        if k["t"] <= trade_ts:
            best = k["t"]
    return best


def build_markers(trades, klines, interval_sec, strategy):
    """Convert trades to markers aligned with kline times."""
    markers = []
    for trade in trades:
        # Parse entry time
        entry_ts = parse_time(trade.get("entry_time", ""))
        exit_ts = parse_time(trade.get("exit_time", ""))
        if entry_ts is None or exit_ts is None:
            continue

        entry_kline_t = find_kline_time(entry_ts, klines, interval_sec)
        exit_kline_t = find_kline_time(exit_ts, klines, interval_sec)

        pnl = trade.get("pnl", 0)
        entry_price = trade.get("entry", 0)
        exit_price = trade.get("exit", 0)

        # Entry marker
        if entry_kline_t is not None:
            markers.append({
                "time": datetime.fromtimestamp(entry_kline_t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "type": "entry",
                "price": entry_price,
                "text": "开多",
                "strategy": strategy,
            })

        # Exit marker
        if exit_kline_t is not None:
            markers.append({
                "time": datetime.fromtimestamp(exit_kline_t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "type": "exit",
                "price": exit_price,
                "text": "止盈" if pnl >= 0 else "止损",
                "pnl": pnl,
                "strategy": strategy,
            })

    return markers


def main():
    # Load backtest data
    with open(BACKTEST_PATH, "r") as f:
        backtest_data = json.load(f)

    # Build: {display_symbol: [(strategy, trades_detail), ...]}
    coin_data = {}
    for item in backtest_data:
        sym = item.get("symbol", "?")
        strategy = item.get("strategy", "?")
        trades = item.get("trades_detail", [])
        if sym not in coin_data:
            coin_data[sym] = []
        coin_data[sym].append((strategy, trades))

    # Deduce DuckDB symbol: append USDT if not already
    def to_duck_sym(display):
        if display.endswith("USDT"):
            return display
        return display + "USDT"

    total_generated = 0

    for display_sym, strategy_trades_list in coin_data.items():
        duck_sym = to_duck_sym(display_sym)

        # Process each interval
        for interval in INTERVALS:
            klines = load_klines(DB_PATH, duck_sym, interval)
            if not klines:
                print(f"  WARNING: No {interval} klines for {duck_sym}, skipping")
                continue

            # Build all markers tagged by strategy
            all_markers = []
            interval_sec = INTERVAL_SECONDS[interval]
            for strategy, trades in strategy_trades_list:
                markers = build_markers(trades, klines, interval_sec, strategy)
                all_markers.extend(markers)

            output = {
                "prices": klines,
                "markers": all_markers,
            }

            out_name = f"chart_{display_sym}_{interval}.json"
            out_path = OUT_DIR / out_name

            with open(out_path, "w") as f:
                json.dump(output, f, ensure_ascii=False)

            strategies = [s for s, _ in strategy_trades_list]
            print(f"{display_sym} ({', '.join(strategies)}) {interval}: "
                  f"{len(klines)} klines, {len(all_markers)} markers -> {out_path}")
            total_generated += 1

    print(f"\nDone. Generated {total_generated} chart data files.")


if __name__ == "__main__":
    main()
