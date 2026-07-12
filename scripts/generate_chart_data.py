"""
Generate K-line chart data for crypto backtest visualization.
Takes 4h klines from DuckDB + trade entries/exits from backtest_detailed.json,
merges into {klines, markers} JSON files per coin.
"""
import json
import duckdb
from pathlib import Path

DATA_DIR = Path(r"C:\Users\admin\aazhous-projects\atlas-ai\data\crypto")
DB_PATH = DATA_DIR / "market.duckdb"
BACKTEST_PATH = DATA_DIR / "backtest_detailed.json"

# Symbol mapping: backtest key -> DuckDB symbol
SYMBOL_MAP = {
    "T": "TUSDT",
    "VANRY": "VANRYUSDT",
    "SKLUSDT": "SKLUSDT",
}


def load_klines(db_path, symbol, interval="4h"):
    """Load klines from DuckDB, return as list of dicts."""
    conn = duckdb.connect(str(db_path))
    rows = conn.execute("""
        SELECT open_time, open, high, low, close
        FROM kline
        WHERE symbol = ? AND interval = ?
        ORDER BY open_time ASC
    """, [symbol, interval]).fetchall()
    conn.close()

    klines = []
    for row in rows:
        klines.append({
            "time": row[0] // 1000,  # ms -> Unix seconds for lightweight-charts
            "open": round(row[1], 8),
            "high": round(row[2], 8),
            "low": round(row[3], 8),
            "close": round(row[4], 8),
        })
    return klines


def load_trades(backtest_path):
    """Load trades from backtest_detailed.json, return dict symbol->trades."""
    with open(backtest_path, "r") as f:
        data = json.load(f)

    trades_map = {}
    for item in data:
        symbol = item.get("symbol", "?")
        duck_symbol = SYMBOL_MAP.get(symbol, symbol)
        trades = item.get("trades_detail", [])
        if trades:
            trades_map[duck_symbol] = trades
    return trades_map


def find_nearest_kline_time(trade_time_str, klines):
    """Find the kline whose open_time contains the trade time (4h candle window)."""
    from datetime import datetime, timezone

    dt = datetime.strptime(trade_time_str, "%Y-%m-%d %H:%M:%S")
    ts = int(dt.replace(tzinfo=timezone.utc).timestamp())

    for k in klines:
        if k["time"] <= ts < k["time"] + 14400:
            return k["time"]

    # Fallback: nearest kline before
    best = None
    for k in klines:
        if k["time"] <= ts:
            best = k["time"]
    return best


def build_markers(trades, klines):
    """Convert trades to lightweight-charts markers."""
    markers = []
    for trade in trades:
        candle_time = find_nearest_kline_time(trade["time"], klines)
        if candle_time is None:
            continue

        pnl = trade.get("pnl", 0)

        # Entry: green arrow below bar
        markers.append({
            "time": candle_time,
            "position": "belowBar",
            "color": "#22c55e",
            "shape": "arrowUp",
            "text": "ENTRY",
        })

        # Exit: colored arrow above bar
        exit_color = "#22c55e" if pnl >= 0 else "#ef4444"
        markers.append({
            "time": candle_time,
            "position": "aboveBar",
            "color": exit_color,
            "shape": "arrowDown",
            "text": f"{'W' if pnl >= 0 else 'L'}{pnl:+.1f}%",
        })

    return markers


def main():
    trades_map = load_trades(BACKTEST_PATH)

    all_symbols = set(list(trades_map.keys()) + ["SKLUSDT"])

    for duck_symbol in sorted(all_symbols):
        print(f"Processing {duck_symbol}...")
        klines = load_klines(DB_PATH, duck_symbol)
        if not klines:
            print(f"  WARNING: No klines found for {duck_symbol}, skipping")
            continue

        trades = trades_map.get(duck_symbol, [])
        markers = build_markers(trades, klines)

        # Display symbol for output filename
        display = duck_symbol.replace("USDT", "USDT")
        out_name = f"backtest_chart_{duck_symbol}.json"
        out_path = DATA_DIR / out_name

        output = {
            "symbol": duck_symbol,
            "klines": klines,
            "markers": markers,
            "trade_count": len(trades),
            "marker_count": len(markers),
        }

        with open(out_path, "w") as f:
            json.dump(output, f)

        print(f"  -> {out_path} ({len(klines)} klines, {len(markers)} markers)")

    print("Done.")


if __name__ == "__main__":
    main()
