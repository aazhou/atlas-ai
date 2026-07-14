"""
Strategy Base Class
所有策略的基类，定义统一接口
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import json


@dataclass
class Signal:
    """交易信号"""
    symbol: str
    direction: str           # 'LONG' | 'SHORT'
    score: float             # 策略评分 0-1
    entry_price: float       # 建议入场价
    stop_loss: float         # 止损价
    take_profit: float       # 止盈价
    timestamp: int           # Unix ms
    strategy: str            # 策略名称
    reason: str = ''         # 触发原因
    confidence: str = 'MED'  # 'HIGH'|'MED'|'LOW'


@dataclass
class Trade:
    """已完成的交易"""
    symbol: str
    direction: str
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    pnl_pct: float
    max_favorable: float     # 最大浮盈%
    max_adverse: float       # 最大浮亏%
    exit_reason: str         # 'TP'|'SL'|'TIMEOUT'|'MANUAL'
    strategy: str


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str
    symbol: str
    total_trades: int
    win_trades: int
    win_rate: float
    avg_return: float        # 平均收益率
    total_return: float      # 总收益率
    max_drawdown: float      # 最大回撤
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    profit_factor: float     # 盈亏比 (总盈利/总亏损)
    avg_hold_hours: float
    trades: List[Dict] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    
    @property
    def score(self) -> float:
        """综合评分 0-100"""
        s = 0
        s += min(25, self.sharpe_ratio * 25) if self.sharpe_ratio > 0 else 0
        s += self.win_rate * 20 if self.win_rate else 0
        s += max(0, 20 - self.max_drawdown * 60) if self.max_drawdown else 0
        s += min(15, self.profit_factor * 10) if self.profit_factor else 0
        s += min(10, self.total_trades * 2)  # 5笔以上满分
        s += min(10, self.avg_return * 100) if self.avg_return > 0 else 0
        return round(s, 1)
    
    @property
    def grade(self) -> str:
        """评级"""
        if self.score >= 75 and self.sharpe_ratio >= 1.0 and self.max_drawdown < 0.35:
            return 'A'
        elif self.score >= 60:
            return 'B'
        else:
            return 'C'
    
    def to_dict(self) -> dict:
        return {
            'strategy': self.strategy_name,
            'symbol': self.symbol,
            'total_trades': self.total_trades,
            'win_rate': round(self.win_rate, 3),
            'avg_return': round(self.avg_return, 4),
            'total_return': round(self.total_return, 4),
            'max_drawdown': round(self.max_drawdown, 4),
            'sharpe_ratio': round(self.sharpe_ratio, 2),
            'sortino_ratio': round(self.sortino_ratio, 2),
            'calmar_ratio': round(self.calmar_ratio, 2),
            'profit_factor': round(self.profit_factor, 2),
            'avg_hold_hours': round(self.avg_hold_hours, 1),
            'score': self.score,
            'grade': self.grade,
            'trades_count': self.total_trades,
            'trades': self.trades,
            'equity_curve': self.equity_curve,
        }


class BaseStrategy(ABC):
    """策略基类"""
    
    name: str = 'base'
    description: str = ''
    version: str = '1.0'
    
    def __init__(self, params: dict = None):
        self.params = params or {}
    
    @abstractmethod
    def generate_signals(self, klines: List[Tuple], funding_rates: List[Tuple] = None,
                         oi_data: List[Tuple] = None) -> List[Signal]:
        """
        生成交易信号
        
        Args:
            klines: [(open_time, open, high, low, close, volume, ...), ...]
            funding_rates: [(time, rate), ...]
            oi_data: [(time, oi), ...]
        
        Returns:
            List of Signal objects
        """
        pass
    
    @abstractmethod
    def backtest(self, klines: List[Tuple], funding_rates: List[Tuple] = None,
                 oi_data: List[Tuple] = None) -> BacktestResult:
        """回测策略"""
        pass
    
    def get_params(self) -> dict:
        return self.params
    
    def __repr__(self):
        return f"{self.name} v{self.version}"
