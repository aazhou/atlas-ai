#!/usr/bin/env python3
"""
加密市场数据持久化层 — SQLite
缓存K线/OI/费率/ticker，支持增量更新。
首次全量拉取 → 后续扫描只拉增量 → 目标<30s
"""

import sqlite3
import json
import time
import os
import sys
from datetime import datetime
from contextlib import contextmanager

import requests

# ═══════════════════ Config ═══════════════════

BASE_URL = "https://fapi.binance.com"
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "crypto", "market.db"
)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

TIMEOUT = 10
SLEEP = 0.08  # fast sleep for bulk operations
RETRIES = 2

# Cache TTLs (seconds)
TICKER_TTL = 300        # 5min — ticker refreshes every scan
KLINE_TTL = 3600        # 1h — but we also incremental pull
FUNDING_TTL = 28800     # 8h — funding settles every 8h
OI_TTL = 300            # 5min — OI changes fast
CONTRACT_TTL = 86400    # 24h — contract list rarely changes

# ═══════════════════ Database ═══════════════════

def get_schema_version(conn):
    """Check if DB has our schema."""
    try:
        r = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return int(r[0]) if r else 0
    except Exception:
        return 0


def init_db(conn):
    """Initialize database schema."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS contracts (
            symbol TEXT PRIMARY KEY,
            base_asset TEXT,
            quote_asset TEXT,
            status TEXT,
            updated_at REAL
        );

        CREATE TABLE IF NOT EXISTS klines (
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            open_time INTEGER NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            quote_volume REAL,
            trades INTEGER,
            fetched_at REAL,
            PRIMARY KEY (symbol, interval, open_time)
        );

        CREATE TABLE IF NOT EXISTS funding_history (
            symbol TEXT NOT NULL,
            funding_time INTEGER NOT NULL,
            rate REAL,
            fetched_at REAL,
            PRIMARY KEY (symbol, funding_time)
        );

        CREATE TABLE IF NOT EXISTS oi_history (
            symbol TEXT NOT NULL,
            period TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            open_interest REAL,
            fetched_at REAL,
            PRIMARY KEY (symbol, period, timestamp)
        );

        CREATE TABLE IF NOT EXISTS tickers (
            symbol TEXT PRIMARY KEY,
            data TEXT,       -- JSON blob
            updated_at REAL
        );

        -- Indexes for fast lookups
        CREATE INDEX IF NOT EXISTS idx_klines_sym_int ON klines(symbol, interval);
        CREATE INDEX IF NOT EXISTS idx_funding_sym ON funding_history(symbol);
        CREATE INDEX IF NOT EXISTS idx_oi_sym_period ON oi_history(symbol, period);
    """)
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version','1')")
    conn.commit()


@contextmanager
def get_conn():
    """Get a database connection with WAL mode."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        conn.close()


def _ensure_db():
    with get_conn() as conn:
        if get_schema_version(conn) < 1:
            init_db(conn)


# ═══════════════════ API Helpers ═══════════════════

def fetch_json(url, params=None, retries=RETRIES):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(0.5 * (attempt + 1))
    return None


# ═══════════════════ Contract Cache ═══════════════════

def get_all_symbols(force_refresh=False):
    """Get all USDT perpetual symbols, cached in DB."""
    _ensure_db()
    with get_conn() as conn:
        now = time.time()
        if not force_refresh:
            row = conn.execute(
                "SELECT updated_at FROM contracts LIMIT 1"
            ).fetchone()
            if row and now - row[0] < CONTRACT_TTL:
                symbols = conn.execute(
                    "SELECT symbol FROM contracts ORDER BY symbol"
                ).fetchall()
                return [s[0] for s in symbols]

        # Fetch from API
        data = fetch_json(f"{BASE_URL}/fapi/v1/exchangeInfo")
        if not data:
            # Fallback to cached even if stale
            symbols = conn.execute(
                "SELECT symbol FROM contracts ORDER BY symbol"
            ).fetchall()
            return [s[0] for s in symbols]

        symbols = []
        rows = []
        for s in data.get("symbols", []):
            if (s.get("contractType") == "PERPETUAL"
                    and s.get("quoteAsset") == "USDT"
                    and s.get("status") == "TRADING"):
                sym = s["symbol"]
                symbols.append(sym)
                rows.append((sym, s.get("baseAsset", ""),
                            s.get("quoteAsset", ""), s.get("status", ""), now))

        symbols.sort()
        rows.sort(key=lambda r: r[0])

        conn.execute("DELETE FROM contracts")
        conn.executemany(
            "INSERT INTO contracts(symbol,base_asset,quote_asset,status,updated_at) "
            "VALUES(?,?,?,?,?)", rows
        )
        conn.commit()
        return symbols


# ═══════════════════ Ticker Cache ═══════════════════

def get_all_tickers(force_refresh=False):
    """Get all 24h tickers, cached in DB with 5min TTL.
    Returns {symbol: ticker_dict}.
    """
    _ensure_db()
    with get_conn() as conn:
        now = time.time()

        if not force_refresh:
            row = conn.execute(
                "SELECT updated_at FROM tickers LIMIT 1"
            ).fetchone()
            if row and now - row[0] < TICKER_TTL:
                rows = conn.execute("SELECT symbol, data FROM tickers").fetchall()
                return {sym: json.loads(data) for sym, data in rows}

        # Fetch from API
        data = fetch_json(f"{BASE_URL}/fapi/v1/ticker/24hr")
        if not data:
            # Fallback to stale cache
            rows = conn.execute("SELECT symbol, data FROM tickers").fetchall()
            return {sym: json.loads(data) for sym, data in rows}

        tickers = {}
        conn.execute("DELETE FROM tickers")
        for t in data:
            sym = t.get("symbol", "")
            if sym.endswith("USDT"):
                tickers[sym] = t
                conn.execute(
                    "INSERT INTO tickers(symbol,data,updated_at) VALUES(?,?,?)",
                    (sym, json.dumps(t), now)
                )
        conn.commit()
        return tickers


# ═══════════════════ Kline Cache ═══════════════════

def get_cached_klines(symbol, interval="1h", limit=50):
    """Get klines from cache. Returns list of candle dicts or None if insufficient."""
    _ensure_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT open_time, open, high, low, close, volume, quote_volume, trades "
            "FROM klines WHERE symbol=? AND interval=? "
            "ORDER BY open_time DESC LIMIT ?",
            (symbol, interval, limit)
        ).fetchall()

        if len(rows) < limit:
            return None  # Not enough cached data

        candles = []
        for r in reversed(rows):  # chron order
            candles.append({
                "t": r[0], "o": r[1], "h": r[2], "l": r[3],
                "c": r[4], "v": r[5], "qv": r[6], "trades": r[7]
            })
        return candles


def fetch_and_cache_klines(symbol, interval="1h", limit=50):
    """Fetch klines from API and store in DB. Returns candle list."""
    data = fetch_json(f"{BASE_URL}/fapi/v1/klines", params={
        "symbol": symbol, "interval": interval, "limit": limit
    })
    if not data:
        return get_cached_klines(symbol, interval, limit)  # fallback to cache

    _ensure_db()
    now = time.time()
    with get_conn() as conn:
        for k in data:
            conn.execute("""
                INSERT OR REPLACE INTO klines
                (symbol, interval, open_time, open, high, low, close, volume, quote_volume, trades, fetched_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (
                symbol, interval, k[0],
                float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                float(k[5]), float(k[7]),
                int(k[8]),
                now
            ))
        conn.commit()

    candles = []
    for k in data:
        candles.append({
            "t": k[0], "o": float(k[1]), "h": float(k[2]), "l": float(k[3]),
            "c": float(k[4]), "v": float(k[5]), "qv": float(k[7]), "trades": int(k[8])
        })
    return candles


def incremental_update_klines(symbol, interval="1h", lookback=5):
    """Fetch only new klines since last cached candle. Returns full merged dataset.
    Returns (candles, is_fresh) where is_fresh=True if new data was pulled.
    """
    _ensure_db()
    with get_conn() as conn:
        last_row = conn.execute(
            "SELECT open_time FROM klines WHERE symbol=? AND interval=? ORDER BY open_time DESC LIMIT 1",
            (symbol, interval)
        ).fetchone()

        if not last_row:
            # No cache at all, do full pull
            candles = fetch_and_cache_klines(symbol, interval)
            return candles, True

        last_time = last_row[0]
        now_ms = int(time.time() * 1000)

        # Fetch only new candles (limit=lookback is small, fast)
        new_data = fetch_json(f"{BASE_URL}/fapi/v1/klines", params={
            "symbol": symbol, "interval": interval, "limit": lookback
        })

        if not new_data:
            # API failed, return cached
            return get_cached_klines(symbol, interval), False

        new_candles = []
        now = time.time()
        for k in new_data:
            if k[0] > last_time:  # Only store genuinely new candles
                conn.execute("""
                    INSERT OR REPLACE INTO klines
                    (symbol, interval, open_time, open, high, low, close, volume, quote_volume, trades, fetched_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    symbol, interval, k[0],
                    float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                    float(k[5]), float(k[7]),
                    int(k[8]),
                    now
                ))
                new_candles.append({
                    "t": k[0], "o": float(k[1]), "h": float(k[2]),
                    "l": float(k[3]), "c": float(k[4]), "v": float(k[5]),
                    "qv": float(k[7]), "trades": int(k[8])
                })

        is_fresh = len(new_candles) > 0
        if new_candles:
            conn.commit()

        # Return merged: cached + new
        return get_cached_klines(symbol, interval), is_fresh


# ═══════════════════ Funding Cache ═══════════════════

def get_cached_funding(symbol, limit=5):
    """Get funding history from cache."""
    _ensure_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT funding_time, rate FROM funding_history "
            "WHERE symbol=? ORDER BY funding_time DESC LIMIT ?",
            (symbol, limit)
        ).fetchall()
        if not rows:
            return None
        return [{"time": r[0], "rate": r[1]} for r in reversed(rows)]


def fetch_and_cache_funding(symbol, limit=10):
    """Fetch funding history from API and cache."""
    data = fetch_json(f"{BASE_URL}/fapi/v1/fundingRate", params={
        "symbol": symbol, "limit": limit
    })
    if not data:
        return get_cached_funding(symbol, limit)

    _ensure_db()
    now = time.time()
    with get_conn() as conn:
        for item in data:
            conn.execute("""
                INSERT OR REPLACE INTO funding_history
                (symbol, funding_time, rate, fetched_at)
                VALUES(?,?,?,?)
            """, (symbol, int(item["fundingTime"]), float(item["fundingRate"]), now))
        conn.commit()

    result = sorted(
        [{"time": int(item["fundingTime"]), "rate": float(item["fundingRate"])}
         for item in data],
        key=lambda x: x["time"]
    )
    return result


# ═══════════════════ OI Cache ═══════════════════

def get_cached_oi(symbol, period="5m", limit=5):
    """Get OI history from cache."""
    _ensure_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT timestamp, open_interest FROM oi_history "
            "WHERE symbol=? AND period=? ORDER BY timestamp DESC LIMIT ?",
            (symbol, period, limit)
        ).fetchall()
        if not rows:
            return None
        return [{"time": r[0], "oi": r[1]} for r in reversed(rows)]


def fetch_and_cache_oi(symbol, period="5m", limit=5):
    """Fetch OI history from API and cache."""
    data = fetch_json(f"{BASE_URL}/futures/data/openInterestHist", params={
        "symbol": symbol, "period": period, "limit": limit
    })
    if not data:
        return get_cached_oi(symbol, period, limit)

    _ensure_db()
    now = time.time()
    with get_conn() as conn:
        for item in data:
            conn.execute("""
                INSERT OR REPLACE INTO oi_history
                (symbol, period, timestamp, open_interest, fetched_at)
                VALUES(?,?,?,?,?)
            """, (symbol, period, int(item["timestamp"]),
                 float(item["sumOpenInterest"]), now))
        conn.commit()

    return [{"time": int(item["timestamp"]),
             "oi": float(item["sumOpenInterest"])}
            for item in sorted(data, key=lambda x: int(x["timestamp"]))]


# ═══════════════════ Bulk Operations ═══════════════════

def bulk_prime_all(max_symbols=None):
    """
    First-time bulk load: fetch klines + funding + OI for all contracts.
    This runs once to populate the cache. Takes ~5-8 minutes for 530 coins.
    Set max_symbols to limit (e.g., 100) for testing.

    Returns dict with stats.
    """
    symbols = get_all_symbols(force_refresh=True)
    if max_symbols:
        symbols = symbols[:max_symbols]

    tickers = get_all_tickers(force_refresh=True)

    stats = {"total": len(symbols), "klines_ok": 0, "funding_ok": 0, "oi_ok": 0, "failed": 0}

    print(f"  [PRIME] Starting bulk load for {len(symbols)} contracts...", file=sys.stderr)

    for idx, sym in enumerate(symbols):
        ok = True

        # 1h klines (50 candles)
        candles = fetch_and_cache_klines(sym, "1h", 50)
        time.sleep(SLEEP)
        if candles and len(candles) >= 20:
            stats["klines_ok"] += 1
        else:
            ok = False

        # 15m klines (12 candles for LONG_D)
        fetch_and_cache_klines(sym, "15m", 12)
        time.sleep(SLEEP * 0.5)

        # Funding history
        fr = fetch_and_cache_funding(sym, 10)
        time.sleep(SLEEP * 0.3)
        if fr and len(fr) >= 2:
            stats["funding_ok"] += 1
        else:
            ok = False

        # OI history (5m for LONG_B, 1h for LONG_C)
        oi5 = fetch_and_cache_oi(sym, "5m", 5)
        time.sleep(SLEEP * 0.3)
        oi1h = fetch_and_cache_oi(sym, "1h", 3)
        time.sleep(SLEEP * 0.3)
        if oi5 and len(oi5) >= 2:
            stats["oi_ok"] += 1
        else:
            ok = False

        if not ok:
            stats["failed"] += 1

        if (idx + 1) % 50 == 0:
            print(f"  [PRIME] {idx+1}/{len(symbols)} "
                  f"K:{stats['klines_ok']} F:{stats['funding_ok']} "
                  f"O:{stats['oi_ok']} X:{stats['failed']}",
                  file=sys.stderr)

    print(f"  [PRIME] Done. K:{stats['klines_ok']} F:{stats['funding_ok']} "
          f"O:{stats['oi_ok']} Failed:{stats['failed']}",
          file=sys.stderr)
    return stats


def incremental_scan_update(symbols, tickers):
    """
    Incremental update for a scan: for each symbol, pull only new candles,
    latest funding, latest OI. This is the fast path for recurring scans.

    Returns updated caches that the scanner can query.
    """
    _ensure_db()
    stats = {"klines_new": 0, "funding_new": 0, "oi_new": 0, "errors": 0}
    now = time.time()

    for idx, sym in enumerate(symbols):
        try:
            # Only update klines if we have a ticker (trading)
            if sym in tickers:
                # Quick incremental kline pull
                candles, fresh = incremental_update_klines(sym, "1h", lookback=3)
                if fresh:
                    stats["klines_new"] += 1

                # Quick incremental funding check
                cached_fr = get_cached_funding(sym, 2)
                if cached_fr:
                    last_fr_time = cached_fr[-1]["time"]
                    # Funding settles every 8h — check if we need update
                    if now * 1000 - last_fr_time > 8 * 3600 * 1000:
                        fetch_and_cache_funding(sym, 2)
                        stats["funding_new"] += 1
                else:
                    fetch_and_cache_funding(sym, 2)
                    stats["funding_new"] += 1

                # Quick incremental OI (5m)
                cached_oi = get_cached_oi(sym, "5m", 2)
                if not cached_oi:
                    fetch_and_cache_oi(sym, "5m", 3)
                    stats["oi_new"] += 1

                time.sleep(SLEEP * 0.3)  # ~0.024s per coin

        except Exception:
            stats["errors"] += 1

        if (idx + 1) % 200 == 0:
            print(f"  [INCR] {idx+1}/{len(symbols)} "
                  f"new_k:{stats['klines_new']} new_f:{stats['funding_new']} "
                  f"new_o:{stats['oi_new']}",
                  file=sys.stderr)

    return stats


def get_db_stats():
    """Get database statistics for diagnostics."""
    _ensure_db()
    with get_conn() as conn:
        stats = {}
        for table in ["klines", "funding_history", "oi_history", "tickers", "contracts"]:
            r = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            stats[table] = r[0]
        stats["db_size_mb"] = round(os.path.getsize(DB_PATH) / (1024 * 1024), 2) if os.path.exists(DB_PATH) else 0
        return stats


# ═══════════════════ CLI ═══════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Market DB — crypto data cache")
    parser.add_argument("action", choices=["prime", "stats", "init", "incr"],
                       help="prime=full load, stats=db info, init=schema only, incr=incremental update")
    parser.add_argument("--max", type=int, default=None, help="Max symbols for prime")
    args = parser.parse_args()

    if args.action == "init":
        _ensure_db()
        print("[OK] Database initialized")

    elif args.action == "stats":
        s = get_db_stats()
        print(f"DB: {DB_PATH}")
        print(f"Size: {s['db_size_mb']}MB")
        for k, v in s.items():
            if k != "db_size_mb":
                print(f"  {k}: {v} rows")

    elif args.action == "prime":
        bulk_prime_all(max_symbols=args.max)

    elif args.action == "incr":
        symbols = get_all_symbols()
        tickers = get_all_tickers(force_refresh=True)
        stats = incremental_scan_update(symbols, tickers)
        print(f"[INCR] Done: {stats}")
