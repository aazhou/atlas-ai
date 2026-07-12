#!/usr/bin/env python3
"""
DuckDB 持久化 — 多周期 K 线 + 流动性过滤

表: kline (symbol, interval, open_time, OHLCV, taker_volume, num_trades)
周期: 1m / 5m / 15m / 1h / 4h / 1d
过滤: 24h成交量 > $10M USDT
自适应: 1m/5m→3天, 15m/1h→14天, 4h/1d→90天
索引: (symbol, interval, open_time)
"""

import duckdb
import json
import time
import os
import sys
from datetime import datetime

import requests

# ═══════════════════ Config ═══════════════════

BASE_URL = "https://fapi.binance.com"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "crypto")
DB_PATH = os.path.join(DATA_DIR, "market.duckdb")
os.makedirs(DATA_DIR, exist_ok=True)

TIMEOUT = 10
SLEEP = 0.25          # ~4 calls/sec, safe for weight limits
RETRIES = 1           # single retry to avoid long hangs

MIN_VOLUME_USDT = 10_000_000   # $10M liquidity threshold

# Interval config: (lookback_days, max_limit_per_call)
# NOTE: Binance kline weight: ≤100→1, 101-500→2, 501-1000→5, >1000→10
INTERVAL_CONFIG = {
    "1m":  (1,   1000),   # 1d = 1440 candles → 2 calls (1K+400, weight 5+1)  or use 1 call 1500 weight 10
    "5m":  (3,   864),    # 3d = 864 candles  → 1 call (weight 5)
    "15m": (14,  1000),   # 14d = 1344 candles → 2 calls (1K+344, weight 5+1)  or 1 call 1500 weight 10
    "1h":  (14,  336),    # 14d = 336 candles  → 1 call (weight 2)
    "4h":  (90,  500),    # 90d = 540 candles  → 2 calls (500+40, weight 2+1)
    "1d":  (90,  90),     # 90d = 90 candles   → 1 call (weight 1)
}


# ═══════════════════ API ═══════════════════

# Use a persistent session for connection pooling (major speedup)
_SESSION = None


def _get_session():
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({"User-Agent": "atlas-crypto/1.0"})
    return _SESSION


def fetch_json(url, params=None, retries=RETRIES):
    session = _get_session()
    for attempt in range(retries + 1):
        try:
            r = session.get(url, params=params or {}, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            if r.status_code == 429:  # Rate limited
                time.sleep(2.0 * (attempt + 1))
                continue
            if attempt == retries:
                return None
            time.sleep(0.5 * (attempt + 1))
        except Exception:
            if attempt == retries:
                return None
            time.sleep(0.5 * (attempt + 1))
    return None


def fetch_klines_page(symbol, interval, limit, end_time=None):
    """Fetch one page of klines. Returns raw list or None."""
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_time:
        params["endTime"] = end_time
    return fetch_json(f"{BASE_URL}/fapi/v1/klines", params)


def fetch_klines_multi(symbol, interval, lookback_days, max_limit):
    """
    Fetch enough klines to cover lookback_days, paginating as needed.
    Returns list of parsed candle dicts (deduped, chron order).
    """
    interval_minutes = {
        "1m": 1, "5m": 5, "15m": 15,
        "1h": 60, "4h": 240, "1d": 1440
    }
    mins = interval_minutes.get(interval, 1)
    needed = int(lookback_days * 24 * 60 / mins)

    all_raw = []
    end_time = None

    for page in range(10):  # safety cap
        limit = min(max_limit, needed - len(all_raw)) if needed else max_limit
        if limit <= 0:
            break

        raw = fetch_klines_page(symbol, interval, limit, end_time)
        time.sleep(SLEEP)

        if not raw or len(raw) == 0:
            break

        # Prepend (raw is newest-first when using endTime, but API returns oldest-first)
        # Actually Binance always returns oldest-first. Paginate by setting endTime to
        # the open_time of the earliest candle minus 1ms.
        all_raw = raw + all_raw

        if len(raw) < limit:
            break  # no more data

        # Update end_time to fetch older data
        end_time = raw[0][0] - 1  # 1ms before earliest candle
        if end_time <= 0:
            break

    # Dedupe by open_time (keep first occurrence = oldest)
    seen = set()
    candles = []
    for k in all_raw:
        ot = k[0]
        if ot in seen:
            continue
        seen.add(ot)
        candles.append({
            "open_time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "close_time": k[6],
            "quote_volume": float(k[7]),
            "num_trades": int(k[8]),
            "taker_buy_volume": float(k[9]),
            "taker_buy_quote_volume": float(k[10]),
        })

    candles.sort(key=lambda c: c["open_time"])
    return candles


# ═══════════════════ DuckDB ═══════════════════

def get_conn(read_only=False):
    """Get DuckDB connection."""
    conn = duckdb.connect(DB_PATH, read_only=read_only)
    return conn


def init_db(conn):
    """Create table + indexes."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kline (
            symbol       VARCHAR NOT NULL,
            interval     VARCHAR NOT NULL,
            open_time    BIGINT  NOT NULL,
            open         DOUBLE,
            high         DOUBLE,
            low          DOUBLE,
            close        DOUBLE,
            volume       DOUBLE,
            quote_volume DOUBLE,
            taker_volume DOUBLE,
            num_trades   INTEGER,
            fetched_at   DOUBLE,
            PRIMARY KEY (symbol, interval, open_time)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_kline_sym_int_time
        ON kline(symbol, interval, open_time)
    """)
    conn.commit()


def insert_klines(conn, symbol, interval, candles):
    """Batch insert klines via single SQL — MUCH faster than executemany."""
    if not candles:
        return
    now = time.time()
    
    # Build VALUES clause: (sym, intv, ot, o, h, l, c, v, qv, tv, nt, now), ...
    values_parts = []
    for c in candles:
        values_parts.append(
            f"('{symbol}', '{interval}', {c['open_time']}, "
            f"{c['open']}, {c['high']}, {c['low']}, {c['close']}, "
            f"{c['volume']}, {c['quote_volume']}, {c['taker_buy_volume']}, "
            f"{c['num_trades']}, {now})"
        )
    
    sql = f"""
        INSERT OR REPLACE INTO kline
        (symbol, interval, open_time, open, high, low, close,
         volume, quote_volume, taker_volume, num_trades, fetched_at)
        VALUES {', '.join(values_parts)}
    """
    conn.execute(sql)
    conn.commit()


def read_klines(conn, symbol, interval, limit=50):
    """Read cached klines for a symbol+interval. Returns list of dicts, newest last."""
    rows = conn.execute("""
        SELECT open_time, open, high, low, close, volume,
               taker_volume, num_trades
        FROM kline
        WHERE symbol = ? AND interval = ?
        ORDER BY open_time DESC
        LIMIT ?
    """, [symbol, interval, limit]).fetchall()

    if len(rows) < limit:
        return None

    candles = []
    for r in reversed(rows):
        candles.append({
            "t": r[0], "o": r[1], "h": r[2], "l": r[3],
            "c": r[4], "v": r[5], "tv": r[6], "trades": r[7]
        })
    return candles


def read_klines_cached(symbol, interval, limit=50):
    """Convenience: open DuckDB read-only, read klines, close. For scanner use."""
    if not os.path.exists(DB_PATH):
        return None
    conn = get_conn(read_only=True)
    try:
        return read_klines(conn, symbol, interval, limit)
    finally:
        conn.close()


def get_db_stats(conn):
    """Quick DB stats."""
    total = conn.execute("SELECT COUNT(*) FROM kline").fetchone()[0]
    symbols = conn.execute(
        "SELECT COUNT(DISTINCT symbol) FROM kline"
    ).fetchone()[0]
    intervals = conn.execute("""
        SELECT interval, COUNT(*) as cnt
        FROM kline GROUP BY interval ORDER BY interval
    """).fetchall()

    db_size_mb = round(os.path.getsize(DB_PATH) / (1024 * 1024), 2) if os.path.exists(DB_PATH) else 0
    return total, symbols, intervals, db_size_mb


def get_loaded_symbols(conn):
    """Return set of symbols that have ALL intervals fully loaded in kline table."""
    all_intervals = set(INTERVAL_CONFIG.keys())
    rows = conn.execute("""
        SELECT symbol FROM (
            SELECT symbol, COUNT(DISTINCT interval) as intv_count
            FROM kline
            GROUP BY symbol
        ) WHERE intv_count = ?
    """, [len(all_intervals)]).fetchall()
    return {r[0] for r in rows}


# ═══════════════════ Main Build ═══════════════════

def build():
    """Main entry: pull tickers → filter → pull klines → store."""
    start = time.time()

    # ── Step 1: Get tickers + filter by volume ──
    print("[1/3] 拉取 ticker...", file=sys.stderr)
    tickers_data = fetch_json(f"{BASE_URL}/fapi/v1/ticker/24hr")
    if not tickers_data:
        print("[ERR] ticker API 失败", file=sys.stderr)
        sys.exit(1)

    usdt_pairs = [t for t in tickers_data if t["symbol"].endswith("USDT")]
    qualified = []
    for t in usdt_pairs:
        try:
            vol = float(t["quoteVolume"])
            if vol >= MIN_VOLUME_USDT:
                qualified.append((t["symbol"], vol))
        except (KeyError, ValueError):
            continue

    qualified.sort(key=lambda x: x[1], reverse=True)
    symbols = [s for s, _ in qualified]

    print(f"  USDT合约: {len(usdt_pairs)} | 量>${MIN_VOLUME_USDT/1e6:.0f}M: {len(symbols)}",
          file=sys.stderr)
    print(f"  Top5: {', '.join(symbols[:5])}", file=sys.stderr)

    # ── Step 2: Init DuckDB ──
    print("[2/3] 初始化 DuckDB...", file=sys.stderr)
    conn = get_conn()
    init_db(conn)

    # ── Step 3: Pull klines for all intervals ──
    total_api_calls = 0
    total_candles = 0
    symbol_ok = 0

    for idx, sym in enumerate(symbols):
        sym_ok = True
        for interval, (lookback_days, max_limit) in INTERVAL_CONFIG.items():
            candles = fetch_klines_multi(sym, interval, lookback_days, max_limit)
            total_api_calls += 1  # rough — multi-page counted as 1 here; fine for stats

            if candles and len(candles) >= 10:
                insert_klines(conn, sym, interval, candles)
                total_candles += len(candles)
            else:
                sym_ok = False

        if sym_ok:
            symbol_ok += 1

        # Progress every 5 coins
        if (idx + 1) % 5 == 0 or idx == 0:
            elapsed = time.time() - start
            rate = (idx + 1) / elapsed if elapsed > 0 else 0
            eta = (len(symbols) - idx - 1) / rate if rate > 0 else 0
            print(f"  [{idx+1}/{len(symbols)}] {elapsed:.0f}s | "
                  f"OK:{symbol_ok} candles:{total_candles} | "
                  f"{rate:.1f}币/s ETA:{eta:.0f}s",
                  file=sys.stderr)

    conn.close()

    duration = time.time() - start

    # ── Summary ──
    conn = get_conn(read_only=True)
    total, syms, intervals, size_mb = get_db_stats(conn)
    conn.close()

    print(f"\n{'='*55}", file=sys.stderr)
    print(f"  DuckDB 构建完成 | {duration:.0f}s", file=sys.stderr)
    print(f"  文件: {DB_PATH} ({size_mb}MB)", file=sys.stderr)
    print(f"  总K线: {total:,} | 覆盖{symbol_ok}币 | 间隔:{len(intervals)}", file=sys.stderr)
    for intv, cnt in intervals:
        print(f"    {intv:4s}: {cnt:>10,} candles", file=sys.stderr)
    print(f"  Top5已拉取: {', '.join(symbols[:5])}", file=sys.stderr)
    print(f"{'='*55}\n", file=sys.stderr)

    return {
        "duration_sec": round(duration, 1),
        "symbols_qualified": len(symbols),
        "symbols_ok": symbol_ok,
        "total_candles": total_candles,
        "db_size_mb": size_mb,
    }


def resume():
    """Resume build: skip symbols already in DB, pull only new ones."""
    start = time.time()

    # ── Step 1: Get tickers + filter by volume ──
    print("[1/4] 拉取 ticker...", file=sys.stderr)
    tickers_data = fetch_json(f"{BASE_URL}/fapi/v1/ticker/24hr")
    if not tickers_data:
        print("[ERR] ticker API 失败", file=sys.stderr)
        sys.exit(1)

    usdt_pairs = [t for t in tickers_data if t["symbol"].endswith("USDT")]
    qualified = []
    for t in usdt_pairs:
        try:
            vol = float(t["quoteVolume"])
            if vol >= MIN_VOLUME_USDT:
                qualified.append((t["symbol"], vol))
        except (KeyError, ValueError):
            continue

    qualified.sort(key=lambda x: x[1], reverse=True)
    all_qualified_symbols = [s for s, _ in qualified]
    qualified_map = {s: v for s, v in qualified}

    # ── Step 2: Check what's already in DB ──
    print("[2/4] 检查已加载...", file=sys.stderr)
    conn = get_conn()
    init_db(conn)
    loaded = get_loaded_symbols(conn)

    # Filter: keep symbols NOT already in DB
    todo_symbols = [s for s in all_qualified_symbols if s not in loaded]
    skipped = len(loaded)

    print(f"  USDT合约: {len(usdt_pairs)} | 量>${MIN_VOLUME_USDT/1e6:.0f}M: {len(all_qualified_symbols)}",
          file=sys.stderr)
    print(f"  已加载: {skipped} | 待拉取: {len(todo_symbols)}", file=sys.stderr)

    if not todo_symbols:
        print("[OK] 所有合格币种已加载完毕", file=sys.stderr)
        conn.close()
        return {"duration_sec": 0, "symbols_skipped": skipped, "symbols_new": 0, "total_candles": 0}

    print(f"  已加载 (前10): {', '.join(sorted(loaded)[:10])}", file=sys.stderr)
    print(f"  待拉取 (前10): {', '.join(todo_symbols[:10])}", file=sys.stderr)

    # ── Step 3: Pull klines for remaining symbols ──
    print(f"[3/4] 拉取 K线 ({len(todo_symbols)} 币种)...", file=sys.stderr)
    total_api_calls = 0
    total_candles = 0
    symbol_ok = 0
    symbol_fail = 0

    for idx, sym in enumerate(todo_symbols):
        sym_ok = True
        for interval, (lookback_days, max_limit) in INTERVAL_CONFIG.items():
            candles = fetch_klines_multi(sym, interval, lookback_days, max_limit)
            total_api_calls += 1

            if candles and len(candles) >= 10:
                insert_klines(conn, sym, interval, candles)
                total_candles += len(candles)
            else:
                sym_ok = False

        if sym_ok:
            symbol_ok += 1
        else:
            symbol_fail += 1

        # Progress every 5 coins
        if (idx + 1) % 5 == 0 or idx == 0:
            elapsed = time.time() - start
            rate = (idx + 1) / elapsed if elapsed > 0 else 0
            eta = (len(todo_symbols) - idx - 1) / rate if rate > 0 else 0
            print(f"  [{idx+1}/{len(todo_symbols)}] {elapsed:.0f}s | "
                  f"OK:{symbol_ok} fail:{symbol_fail} candles:{total_candles} | "
                  f"{rate:.1f}币/s ETA:{eta:.0f}s",
                  file=sys.stderr)

    conn.close()

    # ── Step 4: Summary ──
    duration = time.time() - start
    conn_ro = get_conn(read_only=True)
    total, syms, intervals, size_mb = get_db_stats(conn_ro)
    conn_ro.close()

    print(f"\n{'='*55}", file=sys.stderr)
    print(f"  DuckDB Resume 完成 | {duration:.0f}s", file=sys.stderr)
    print(f"  跳过(已加载): {skipped} | 本次新增: {symbol_ok} | 失败: {symbol_fail}", file=sys.stderr)
    print(f"  总币种: {syms} | 总K线: {total:,} | 文件: {size_mb}MB", file=sys.stderr)
    for intv, cnt in intervals:
        print(f"    {intv:4s}: {cnt:>10,} candles", file=sys.stderr)
    print(f"{'='*55}\n", file=sys.stderr)

    return {
        "duration_sec": round(duration, 1),
        "symbols_skipped": skipped,
        "symbols_new": symbol_ok,
        "symbols_failed": symbol_fail,
        "total_candles": total_candles,
        "db_size_mb": size_mb,
    }


# ═══════════════════ CLI ═══════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="DuckDB K线持久化 — 多周期版")
    parser.add_argument("action", nargs="?", default="build",
                       choices=["build", "resume", "stats", "init"],
                       help="build=拉取+存储, resume=续拉跳过已有, stats=统计, init=仅建表")
    args = parser.parse_args()

    if args.action == "init":
        conn = get_conn()
        init_db(conn)
        conn.close()
        print(f"[OK] DuckDB 初始化: {DB_PATH}")

    elif args.action == "stats":
        if not os.path.exists(DB_PATH):
            print("[ERR] DB 不存在，请先运行 build")
            sys.exit(1)
        conn = get_conn(read_only=True)
        total, syms, intervals, size_mb = get_db_stats(conn)
        conn.close()
        print(f"DuckDB: {DB_PATH}")
        print(f"Size: {size_mb}MB | Total candles: {total:,} | Symbols: {syms}")
        for intv, cnt in intervals:
            print(f"  {intv:4s}: {cnt:>10,}")

    elif args.action == "build":
        result = build()
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "resume":
        result = resume()
        print(json.dumps(result, indent=2, ensure_ascii=False))
