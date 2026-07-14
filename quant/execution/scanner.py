"""
Real-time Signal Scanner
实时信号扫描器 — 从 DuckDB 读取最新数据，生成交易信号
"""
import json
import os
import time
from datetime import datetime
from typing import List, Dict, Optional
from collections import defaultdict

from quant.config import DUCKDB_PATH, SIGNALS_PATH, PORTFOLIO_PATH
from quant.data.db import DuckDBManager
from quant.strategies.funding_extreme import FundingExtremeStrategy
from quant.strategies.multifactor import MultiFactorStrategy
from quant.strategies.base import Signal


class Scanner:
    """实时扫描引擎"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DUCKDB_PATH
        self.strategies = []
        self._init_strategies()
    
    def _init_strategies(self):
        """初始化策略列表"""
        self.strategies = [
            FundingExtremeStrategy(),
            MultiFactorStrategy(),
        ]
    
    def add_strategy(self, strategy):
        self.strategies.append(strategy)
    
    def scan_coin(self, symbol: str, funding_rates: List = None) -> List[Signal]:
        """扫描单个币种"""
        all_signals = []
        
        with DuckDBManager(self.db_path, read_only=True) as db:
            # 获取5m K线（最近500根 ≈ 42小时）
            klines = db.get_klines(symbol, '5m', limit=500)
            if len(klines) < 100:
                return all_signals
            
            # 获取费率
            if not funding_rates:
                funding_rates = db.get_funding_rates(symbol, limit=100)
            
            # OI数据
            oi_data = db.get_oi_history(symbol, limit=100)
            
            # 对每个策略扫描
            for strat in self.strategies:
                try:
                    signals = strat.generate_signals(klines, funding_rates, oi_data)
                    for s in signals:
                        s.symbol = symbol
                    all_signals.extend(signals)
                except Exception as e:
                    print(f'  [{strat.name}] {symbol} scan error: {e}')
        
        return all_signals
    
    def scan_all(self, coins: List[str] = None, min_volume_24h: float = 1e6) -> List[Signal]:
        """全市场扫描"""
        if coins is None:
            from quant.config import PRIORITY_COINS
            coins = PRIORITY_COINS
        
        print(f'Scanning {len(coins)} coins with {len(self.strategies)} strategies...')
        
        # 预加载所有费率
        with DuckDBManager(self.db_path, read_only=True) as db:
            funding_map = db.get_funding_map(coins)
        
        all_signals = []
        
        for symbol in coins:
            # 转换成 funding_rates 格式
            fr = funding_map.get(symbol, 0)
            funding_rates = [(int(time.time() * 1000), fr)] if fr else []
            
            signals = self.scan_coin(symbol, funding_rates)
            if signals:
                all_signals.extend(signals)
            
            time.sleep(0.05)  # 避免数据库锁
        
        # 按评分排序
        all_signals.sort(key=lambda s: s.score, reverse=True)
        
        return all_signals
    
    def export_signals(self, signals: List[Signal], path: str = None):
        """导出信号到 JSON"""
        if path is None:
            path = SIGNALS_PATH
        
        data = {
            'generated_at': datetime.now().isoformat(),
            'timestamp': int(time.time() * 1000),
            'total': len(signals),
            'signals': [
                {
                    'symbol': s.symbol,
                    'direction': s.direction,
                    'score': s.score,
                    'entry_price': s.entry_price,
                    'stop_loss': s.stop_loss,
                    'take_profit': s.take_profit,
                    'strategy': s.strategy,
                    'reason': s.reason,
                    'confidence': s.confidence,
                }
                for s in signals
            ]
        }
        
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f'Exported {len(signals)} signals to {path}')
        return path


class PortfolioManager:
    """持仓管理器"""
    
    def __init__(self, path: str = None):
        self.path = path or PORTFOLIO_PATH
        self.positions = []
        self.closed_trades = []
        self.capital = 100_000
        self._load()
    
    def _load(self):
        """加载持仓"""
        if os.path.exists(self.path) and os.path.getsize(self.path) > 0:
            try:
                with open(self.path) as f:
                    data = json.load(f)
                    self.positions = data.get('positions', [])
                    self.closed_trades = data.get('closed_trades', [])
                    self.capital = data.get('capital', 100_000)
            except (json.JSONDecodeError, ValueError):
                pass
    
    def save(self):
        """保存持仓状态"""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w') as f:
            json.dump({
                'positions': self.positions,
                'closed_trades': self.closed_trades,
                'capital': self.capital,
                'last_updated': datetime.now().isoformat(),
            }, f, indent=2)
    
    def open_position(self, signal: Signal, position_size: float = 0.2):
        """开仓"""
        # 检查是否有重复
        for pos in self.positions:
            if pos['symbol'] == signal.symbol:
                return None
        
        # 检查仓位上限
        if len(self.positions) >= 3:
            return None
        
        position = {
            'symbol': signal.symbol,
            'direction': signal.direction,
            'entry_price': signal.entry_price,
            'stop_loss': signal.stop_loss,
            'take_profit': signal.take_profit,
            'entry_time': signal.timestamp,
            'strategy': signal.strategy,
            'score': signal.score,
            'position_size': position_size,
            'current_price': signal.entry_price,
            'pnl_pct': 0,
            'highest_price': signal.entry_price,
        }
        
        self.positions.append(position)
        self.save()
        return position
    
    def close_position(self, symbol: str, exit_price: float, reason: str = 'MANUAL'):
        """平仓"""
        for i, pos in enumerate(self.positions):
            if pos['symbol'] == symbol:
                pnl = (exit_price - pos['entry_price']) / pos['entry_price']
                if pos['direction'] == 'SHORT':
                    pnl = -pnl
                
                trade = {
                    'symbol': symbol,
                    'direction': pos['direction'],
                    'entry_time': pos['entry_time'],
                    'exit_time': int(time.time() * 1000),
                    'entry_price': pos['entry_price'],
                    'exit_price': exit_price,
                    'pnl_pct': round(pnl, 6),
                    'exit_reason': reason,
                    'strategy': pos['strategy'],
                    'score': pos['score'],
                }
                
                self.closed_trades.append(trade)
                self.positions.pop(i)
                self.save()
                return trade
        
        return None
    
    def update_prices(self, price_map: Dict[str, float]):
        """更新当前价格"""
        for pos in self.positions:
            sym = pos['symbol']
            if sym in price_map:
                pos['current_price'] = price_map[sym]
                pnl = (price_map[sym] - pos['entry_price']) / pos['entry_price']
                if pos['direction'] == 'SHORT':
                    pnl = -pnl
                pos['pnl_pct'] = round(pnl, 6)
                if price_map[sym] > pos['highest_price']:
                    pos['highest_price'] = price_map[sym]
    
    def check_exits(self) -> List[dict]:
        """检查是否需要平仓"""
        exits = []
        now = int(time.time() * 1000)
        
        for pos in self.positions[:]:
            cp = pos['current_price']
            
            # 止损
            if pos['direction'] == 'LONG' and cp <= pos['stop_loss']:
                exits.append(self.close_position(pos['symbol'], cp, 'SL'))
                continue
            
            # 超时
            hold_ms = now - pos['entry_time']
            if hold_ms > 48 * 3600 * 1000:
                exits.append(self.close_position(pos['symbol'], cp, 'TIMEOUT'))
                continue
        
        return exits
    
    def get_stats(self) -> dict:
        """获取组合统计"""
        total_pnl = sum(
            (p['current_price'] - p['entry_price']) / p['entry_price'] * p['position_size']
            for p in self.positions
        )
        closed_pnl = sum(t['pnl_pct'] * 0.2 for t in self.closed_trades)
        
        return {
            'capital': self.capital,
            'open_positions': len(self.positions),
            'closed_trades': len(self.closed_trades),
            'total_pnl_pct': round(total_pnl + closed_pnl, 4),
            'win_rate': round(
                sum(1 for t in self.closed_trades if t['pnl_pct'] > 0) / max(len(self.closed_trades), 1), 3
            ) if self.closed_trades else 0,
        }
