#!/usr/bin/env python3
"""
DuckDB 增量更新 — 每5分钟拉最新数据追加到 market.duckdb

拉取范围：
  - K线: 每个周期最新 5 根，仅追加 open_time > 已有最大的
  - 费率: 最新 10 条 funding rate
  - OI: 最新 5m OI 快照
  - Ticker: 全量 24h ticker（覆盖写入）

用法: python scripts/incremental_update.py
"""
import duckdb
import json
import time
import os
import sys
import requests
from datetime import datetime

# ═══════════════════ Config ═══════════════════

BASE_URL = "https://fapi.binance.com"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "crypto")
DB_PATH = os.path.join(DATA_DIR, "market.duckdb")
os.makedirs(DATA_DIR, exist_ok=True)

TIMEOUT = 10
SLEEP = 0.12          # Reduced from 0.25 — only applied after actual API calls
RETRIES = 2

MIN_VOLUME_USDT = 1_000_000    # $1M — 扫描候选门槛
TICKER_VOL_USDT = 10_000_000   # $10M — 持久化到 DB 的门槛

INTERVALS = ["5m", "15m", "1h", "4h", "1d"]
KLINE_LOOKBACK = 5             # 每个周期拉最新 5 根
FUNDING_LIMIT = 10
OI_LIMIT = 5

# ═══════════════════ API ═══════════════════

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
            if r.status_code == 429:
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


# ═══════════════════ DuckDB Schema ═══════════════════

def init_schema(con):
    """Ensure all tables exist."""
    con.execute("""
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
    con.execute("""
        CREATE TABLE IF NOT EXISTS funding_rate (
            symbol       VARCHAR NOT NULL,
            funding_time BIGINT  NOT NULL,
            rate         DOUBLE,
            fetched_at   DOUBLE,
            PRIMARY KEY (symbol, funding_time)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS oi_snapshot (
            symbol        VARCHAR NOT NULL,
            period        VARCHAR NOT NULL,
            timestamp     BIGINT  NOT NULL,
            open_interest DOUBLE,
            fetched_at    DOUBLE,
            PRIMARY KEY (symbol, period, timestamp)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS ticker (
            symbol           VARCHAR PRIMARY KEY,
            last_price       DOUBLE,
            high_price       DOUBLE,
            low_price        DOUBLE,
            quote_volume     DOUBLE,
            price_change_pct DOUBLE,
            trade_count      BIGINT,
            updated_at       DOUBLE
        )
    """)
    # Indexes
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_kline_sym_int_time
        ON kline(symbol, interval, open_time)
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_funding_sym_time
        ON funding_rate(symbol, funding_time)
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_oi_sym_period_time
        ON oi_snapshot(symbol, period, timestamp)
    """)
    con.commit()


# ═══════════════════ Incremental Updates ═══════════════════

def update_tickers(con):
    """Pull all 24h tickers, store those with vol > $10M. Full replace."""
    data = fetch_json(f"{BASE_URL}/fapi/v1/ticker/24hr")
    if not data:
        print("  [TICKER] API 失败，跳过", file=sys.stderr)
        return 0

    now = time.time()
    con.execute("DELETE FROM ticker")

    rows = []
    count = 0
    for t in data:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        try:
            vol = float(t["quoteVolume"])
            if vol < TICKER_VOL_USDT:
                continue
            rows.append((
                sym,
                float(t["lastPrice"]),
                float(t["highPrice"]),
                float(t["lowPrice"]),
                vol,
                float(t["priceChangePercent"]),
                int(t["count"]),
                now,
            ))
            count += 1
        except (KeyError, ValueError):
            continue

    if rows:
        con.executemany("""
            INSERT INTO ticker VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
    con.commit()

    print(f"  [TICKER] {count} 币种 (vol>$10M) | {len(data)} 全市场", file=sys.stderr)
    return count


def update_klines(con):
    """For each interval + each symbol in ticker, pull latest 5 klines.
       Only pull if the last candle is older than the interval period.
       Only sleep after actual API calls (not on skips)."""
    syms = [r[0] for r in con.execute(
        "SELECT symbol FROM ticker ORDER BY quote_volume DESC"
    ).fetchall()]

    # Interval staleness threshold: pull if last candle older than this (ms)
    INTERVAL_MS = {
        "5m": 5 * 60 * 1000,
        "15m": 15 * 60 * 1000,
        "1h": 60 * 60 * 1000,
        "4h": 4 * 60 * 60 * 1000,
        "1d": 24 * 60 * 60 * 1000,
    }
    STALENESS_MULTIPLIER = 2.0  # Only pull if >2x interval behind

    # Pre-fetch all max open_times in one query
    max_times_raw = con.execute("""
        SELECT symbol, interval, MAX(open_time) as max_ot
        FROM kline
        GROUP BY symbol, interval
    """).fetchall()
    max_times = {}
    for r in max_times_raw:
        max_times[(r[0], r[1])] = r[2]

    total_new = 0
    total_skipped = 0
    now = time.time()
    now_ms = int(now * 1000)

    for interval in INTERVALS:
        threshold_ms = int(INTERVAL_MS[interval] * STALENESS_MULTIPLIER)

        for sym in syms:
            last_ts = max_times.get((sym, interval), 0)

            # Skip if data is fresh enough
            if last_ts > 0 and (now_ms - last_ts) < threshold_ms:
                total_skipped += 1
                continue

            # Fetch latest klines
            try:
                raw = fetch_json(f"{BASE_URL}/fapi/v1/klines", params={
                    "symbol": sym, "interval": interval, "limit": KLINE_LOOKBACK
                })
                if not raw:
                    total_skipped += 1
                    continue

                values_parts = []
                for k in raw:
                    ot = k[0]
                    if ot <= last_ts:
                        continue
                    values_parts.append(
                        f"('{sym}', '{interval}', {ot}, "
                        f"{float(k[1])}, {float(k[2])}, {float(k[3])}, {float(k[4])}, "
                        f"{float(k[5])}, {float(k[7])}, {float(k[9])}, "
                        f"{int(k[8])}, {now})"
                    )

                if values_parts:
                    sql = f"""
                        INSERT OR REPLACE INTO kline
                        (symbol, interval, open_time, open, high, low, close,
                         volume, quote_volume, taker_volume, num_trades, fetched_at)
                        VALUES {', '.join(values_parts)}
                    """
                    con.execute(sql)
                    total_new += len(values_parts)

                time.sleep(SLEEP)  # Only sleep after real API call
            except Exception:
                total_skipped += 1

        con.commit()

    print(f"  [KLINE] 新增 {total_new} 根 | 跳过 {total_skipped} (数据新鲜)",
          file=sys.stderr)
    return total_new


def update_funding(con):
    """Pull latest funding rates — only if last record is older than 4h."""
    syms = [r[0] for r in con.execute(
        "SELECT symbol FROM ticker ORDER BY quote_volume DESC"
    ).fetchall()]

    # Pre-fetch max funding_times
    max_ft_raw = con.execute("""
        SELECT symbol, MAX(funding_time) as max_ft
        FROM funding_rate GROUP BY symbol
    """).fetchall()
    max_ft = {r[0]: r[1] for r in max_ft_raw}

    total_new = 0
    total_skipped = 0
    now = time.time()
    now_ms = int(now * 1000)
    FOUR_HOURS_MS = 4 * 3600 * 1000

    for sym in syms:
        last_ft = max_ft.get(sym, 0)
        if last_ft > 0 and (now_ms - last_ft) < FOUR_HOURS_MS:
            total_skipped += 1
            continue

        try:
            data = fetch_json(f"{BASE_URL}/fapi/v1/fundingRate", params={
                "symbol": sym, "limit": FUNDING_LIMIT
            })
            if not data:
                total_skipped += 1
                continue

            values_parts = []
            for item in data:
                ft = int(item["fundingTime"])
                rate = float(item["fundingRate"])
                values_parts.append(f"('{sym}', {ft}, {rate}, {now})")

            if values_parts:
                sql = f"""
                    INSERT OR REPLACE INTO funding_rate
                    (symbol, funding_time, rate, fetched_at)
                    VALUES {', '.join(values_parts)}
                """
                con.execute(sql)
                total_new += len(values_parts)

            time.sleep(SLEEP * 0.5)
        except Exception:
            total_skipped += 1

    con.commit()
    print(f"  [FUNDING] 新增 {total_new} 条 | 跳过 {total_skipped} (<4h内)",
          file=sys.stderr)
    return total_new


def update_oi(con):
    """Pull latest 5m OI snapshots — only if last record older than 5min."""
    syms = [r[0] for r in con.execute(
        "SELECT symbol FROM ticker ORDER BY quote_volume DESC"
    ).fetchall()]

    # Pre-fetch max OI timestamps
    max_oi_raw = con.execute("""
        SELECT symbol, MAX(timestamp) as max_ts
        FROM oi_snapshot WHERE period = '5m'
        GROUP BY symbol
    """).fetchall()
    max_oi = {r[0]: r[1] for r in max_oi_raw}

    total_new = 0
    total_skipped = 0
    now = time.time()
    now_ms = int(now * 1000)
    FIVE_MIN_MS = 5 * 60 * 1000

    for sym in syms:
        last_ts = max_oi.get(sym, 0)
        if last_ts > 0 and (now_ms - last_ts) < FIVE_MIN_MS:
            total_skipped += 1
            continue

        try:
            data = fetch_json(
                f"{BASE_URL}/futures/data/openInterestHist",
                params={"symbol": sym, "period": "5m", "limit": OI_LIMIT}
            )
            if not data:
                total_skipped += 1
                continue

            values_parts = []
            for item in data:
                ts = int(item["timestamp"])
                oi = float(item["sumOpenInterest"])
                values_parts.append(f"('{sym}', '5m', {ts}, {oi}, {now})")

            if values_parts:
                sql = f"""
                    INSERT OR REPLACE INTO oi_snapshot
                    (symbol, period, timestamp, open_interest, fetched_at)
                    VALUES {', '.join(values_parts)}
                """
                con.execute(sql)
                total_new += len(values_parts)

            time.sleep(SLEEP * 0.5)
        except Exception:
            total_skipped += 1

    con.commit()
    print(f"  [OI] 新增 {total_new} 条 | 跳过 {total_skipped} (<5min内)",
          file=sys.stderr)
    return total_new


# ═══════════════════ Main ═══════════════════

def run():
    start = time.time()

    if not os.path.exists(DB_PATH):
        print("[ERR] DuckDB 不存在，请先运行 kline_duckdb.py build", file=sys.stderr)
        sys.exit(1)

    con = duckdb.connect(DB_PATH)
    init_schema(con)

    print(f"[INCR] {datetime.now().strftime('%H:%M:%S')} 开始增量更新...", file=sys.stderr)

    n_ticker = update_tickers(con)
    n_kline = update_klines(con)
    n_funding = update_funding(con)
    n_oi = update_oi(con)

    con.close()

    duration = round(time.time() - start, 1)
    print(f"[INCR] 完成 {duration:.1f}s | "
          f"T:{n_ticker} K:{n_kline} F:{n_funding} O:{n_oi}",
          file=sys.stderr)

    # Output JSON for cron
    result = {
        "ts": datetime.now().isoformat(),
        "duration_sec": duration,
        "tickers": n_ticker,
        "klines_new": n_kline,
        "funding_new": n_funding,
        "oi_new": n_oi,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    run()
