"""
Multi-Factor Scoring Strategy (V11 validated)
多因子评分策略 — 已验证的最优策略

四因子：K线形态(0.2) + 量价关系(0.4) + 价格行为(0.3) + 趋势(0.1)
评分 > 0.18 → LONG，移动止盈+5%，48h超时
"""
from typing import List, Tuple, Dict
from quant.strategies.base import BaseStrategy, Signal, BacktestResult
from quant.data.features import (
    multifactor_score, candle_score, volume_score, pa_score, trend_score,
    funding_extreme_score, get_funding_at_time,
    btc_filter
)
from quant.backtest.engine import run_simple_backtest, compute_metrics


class MultiFactorStrategy(BaseStrategy):
    """多因子评分策略"""
    
    name = 'multifactor'
    description = 'K线+量价+价格行为+趋势四因子评分>0.18做多，移动止盈'
    version = '1.0'
    
    DEFAULT_PARAMS = {
        'weights': {'candle': 0.2, 'vol': 0.4, 'pa': 0.3, 'trend': 0.1},
        'threshold': 0.18,
        'sl_pct': -0.10,
        'tp_pct': 0.05,
        'max_hold_hours': 48,
        'trailing_activation': 0.05,
        'use_funding_filter': True,
        'funding_boost_threshold': 0.5,  # 费率因子>0.5时调整权重
    }
    
    def __init__(self, params: dict = None):
        super().__init__(params or self.DEFAULT_PARAMS)
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}
    
    def compute_score(self, klines: List[Tuple], i: int,
                      funding_rates: List[Tuple] = None,
                      oi_data: List[Tuple] = None) -> Tuple[float, dict]:
        """计算多因子评分"""
        return multifactor_score(klines, i, funding_rates, oi_data, 
                                 self.params['weights'])
    
    def generate_signals(self, klines: List[Tuple],
                         funding_rates: List[Tuple] = None,
                         oi_data: List[Tuple] = None) -> List[Signal]:
        signals = []
        p = self.params
        
        if len(klines) < 50:
            return signals
        
        for i in range(50, len(klines)):
            ts = klines[i][0]
            close = klines[i][4]
            
            # 计算多因子评分
            score, details = self.compute_score(klines, i, funding_rates, oi_data)
            
            if score < p['threshold']:
                continue
            
            # 费率过滤器（可选，避免在资金费率正常时入场）
            if p['use_funding_filter'] and funding_rates:
                fr = get_funding_at_time(funding_rates, ts)
                if fr > 0:  # 正费率不做多
                    continue
            
            signals.append(Signal(
                symbol='',
                direction='LONG',
                score=round(score, 2),
                entry_price=close,
                stop_loss=close * (1 + p['sl_pct']),
                take_profit=close * (1 + p['tp_pct']),
                timestamp=ts,
                strategy=self.name,
                reason=str(details),
                confidence='HIGH' if score > 0.5 else 'MED',
            ))
        
        return signals
    
    def backtest(self, klines: List[Tuple],
                 funding_rates: List[Tuple] = None,
                 oi_data: List[Tuple] = None) -> BacktestResult:
        p = self.params
        
        def signal_func(kl, fr, oi, i):
            if len(kl) < 50:
                return False, 0, ''
            
            score, details = self.compute_score(kl, i, fr, oi)
            if score < p['threshold']:
                return False, 0, ''
            
            if p['use_funding_filter'] and fr:
                fr_val = get_funding_at_time(fr, kl[i][0])
                if fr_val > 0:
                    return False, 0, ''
            
            return True, score, str(details)
        
        trades, equity = run_simple_backtest(
            klines, signal_func,
            sl_pct=p['sl_pct'], tp_pct=p['tp_pct'],
            max_hold_hours=p['max_hold_hours'],
            trailing_activation=p['trailing_activation'],
            funding_rates=funding_rates,
            oi_data=oi_data,
        )
        
        metrics = compute_metrics(trades)
        
        return BacktestResult(
            strategy_name=self.name,
            symbol='',
            **metrics,
            trades=trades,
            equity_curve=equity,
        )


class EnsembleStrategy(BaseStrategy):
    """策略集成：多策略投票"""
    
    name = 'ensemble'
    description = '多策略投票制：至少2/3策略一致才触发'
    version = '1.0'
    
    DEFAULT_PARAMS = {
        'vote_threshold': 2,          # 最少投票数
        'sl_pct': -0.10,
        'tp_pct': 0.05,
        'max_hold_hours': 48,
        'trailing_activation': 0.05,
    }
    
    def __init__(self, strategies: List[BaseStrategy] = None, params: dict = None):
        super().__init__(params or self.DEFAULT_PARAMS)
        self.strategies = strategies or []
    
    def add_strategy(self, strategy: BaseStrategy):
        self.strategies.append(strategy)
    
    def generate_signals(self, klines: List[Tuple],
                         funding_rates: List[Tuple] = None,
                         oi_data: List[Tuple] = None) -> List[Signal]:
        if len(self.strategies) < 2:
            return []
        
        p = self.params
        signals = []
        
        for i in range(50, len(klines)):
            votes = 0
            max_score = 0
            reasons = []
            
            for strat in self.strategies:
                sigs = strat.generate_signals(
                    [(klines[i],)],  # 单根K线
                    funding_rates, oi_data
                )
                if sigs:
                    votes += 1
                    max_score = max(max_score, sigs[0].score)
                    reasons.append(f'{strat.name}:{sigs[0].score:.2f}')
            
            if votes >= p['vote_threshold']:
                ts = klines[i][0]
                close = klines[i][4]
                signals.append(Signal(
                    symbol='',
                    direction='LONG',
                    score=max_score,
                    entry_price=close,
                    stop_loss=close * (1 + p['sl_pct']),
                    take_profit=close * (1 + p['tp_pct']),
                    timestamp=ts,
                    strategy='ensemble',
                    reason=' | '.join(reasons),
                ))
        
        return signals
