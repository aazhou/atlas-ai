"""
Data Layer - DuckDB Manager
统一数据访问层，管理 DuckDB 连接和数据查询
"""
import duckdb
import os
from quant.config import DUCKDB_PATH

class DuckDBManager:
    """DuckDB 数据库管理器"""
    
    def __init__(self, path=None, read_only=False):
        self.path = path or DUCKDB_PATH
        self.read_only = read_only
        self._con = None
    
    @property
    def con(self):
        if self._con is None:
            self._con = duckdb.connect(self.path, read_only=self.read_only)
        return self._con
    
    def close(self):
        if self._con:
            self._con.close()
            self._con = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
    
    # === Schema ===
    
    def get_tables(self):
        return [r[0] for r in self.con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()]
    
    def get_columns(self, table):
        return self.con.execute(
            f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='{table}'"
        ).fetchall()
    
    def get_row_count(self, table):
        return self.con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    
    def get_coins(self, interval='5m', min_rows=500):
        """获取有足够数据的币种列表"""
        return [r[0] for r in self.con.execute(f"""
            SELECT symbol FROM kline 
            WHERE interval='{interval}'
            GROUP BY symbol HAVING COUNT(*) >= {min_rows}
            ORDER BY COUNT(*) DESC
        """).fetchall()]
    
    # === K-line Queries ===
    
    def get_klines(self, symbol, interval='5m', limit=500, offset=0):
        """获取K线数据，返回 list of tuples"""
        rows = self.con.execute(f"""
            SELECT open_time, open, high, low, close, volume, num_trades, taker_buy_volume
            FROM kline
            WHERE symbol='{symbol}' AND interval='{interval}'
            ORDER BY open_time ASC
            LIMIT {limit} OFFSET {offset}
        """).fetchall()
        return rows
    
    def get_klines_range(self, symbol, interval='5m', start_ms=None, end_ms=None):
        """按时间范围获取K线"""
        where = f"symbol='{symbol}' AND interval='{interval}'"
        if start_ms:
            where += f" AND open_time >= {start_ms}"
        if end_ms:
            where += f" AND open_time <= {end_ms}"
        return self.con.execute(f"""
            SELECT open_time, open, high, low, close, volume, taker_buy_volume
            FROM kline WHERE {where}
            ORDER BY open_time ASC
        """).fetchall()
    
    def get_multi_tf_klines(self, symbol, intervals=('5m', '15m', '1h', '4h'), limit=500):
        """获取多周期K线"""
        result = {}
        for tf in intervals:
            rows = self.get_klines(symbol, tf, limit)
            if rows:
                result[tf] = rows
        return result
    
    # === Funding Rate ===
    
    def get_funding_rates(self, symbol, limit=500):
        """获取资金费率历史"""
        return self.con.execute(f"""
            SELECT funding_time, funding_rate 
            FROM funding
            WHERE symbol='{symbol}'
            ORDER BY funding_time DESC
            LIMIT {limit}
        """).fetchall()
    
    def get_latest_funding(self, symbol):
        """最新费率"""
        r = self.con.execute(f"""
            SELECT funding_rate FROM funding
            WHERE symbol='{symbol}'
            ORDER BY funding_time DESC LIMIT 1
        """).fetchone()
        return r[0] if r else None
    
    def get_funding_map(self, symbols=None):
        """获取所有币种最新费率映射"""
        if symbols:
            placeholders = ','.join([f"'{s}'" for s in symbols])
            where = f"WHERE symbol IN ({placeholders})"
        else:
            where = ""
        rows = self.con.execute(f"""
            SELECT symbol, funding_rate FROM (
                SELECT symbol, funding_rate,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY funding_time DESC) as rn
                FROM funding {where}
            ) WHERE rn=1
        """).fetchall()
        return {r[0]: r[1] for r in rows}
    
    # === OI Data ===
    
    def get_oi_history(self, symbol, limit=500):
        """获取持仓量历史"""
        return self.con.execute(f"""
            SELECT timestamp, open_interest 
            FROM oi_snapshot
            WHERE symbol='{symbol}'
            ORDER BY timestamp DESC
            LIMIT {limit}
        """).fetchall()
    
    # === Ticker ===
    
    def get_tickers(self, symbols=None):
        """获取最新ticker"""
        if symbols:
            placeholders = ','.join([f"'{s}'" for s in symbols])
            where = f"WHERE symbol IN ({placeholders})"
        else:
            where = ""
        rows = self.con.execute(f"""
            SELECT symbol, last_price, high_price, low_price, 
                   quote_volume, price_change_pct
            FROM ticker {where}
        """).fetchall()
        return rows
    
    # === Bulk Operations ===
    
    def get_all_coins_data(self, interval='5m', limit=500, min_rows=500):
        """批量获取所有币种K线（用于回测扫描）"""
        coins = self.get_coins(interval, min_rows)
        data = {}
        for coin in coins:
            rows = self.get_klines(coin, interval, limit)
            if len(rows) >= 100:
                data[coin] = rows
        return data
    
    def get_stats(self):
        """数据库统计信息"""
        return {
            'path': self.path,
            'size_mb': round(os.path.getsize(self.path) / (1024*1024), 2),
            'tables': self.get_tables(),
            'kline_rows': self.get_row_count('kline'),
            'funding_rows': self.get_row_count('funding'),
            'oi_rows': self.get_row_count('oi_snapshot'),
            'ticker_rows': self.get_row_count('ticker'),
            'coins_5m': len(self.get_coins('5m')),
            'coins_1h': len(self.get_coins('1h')),
            'coins_1d': len(self.get_coins('1d')),
        }
