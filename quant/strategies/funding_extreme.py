"""
Funding Rate Extreme Reversal Strategy (V10 validated)
费率极端位做多 — 已验证的有效策略

逻辑: funding_rate < -0.05% → 空头拥挤 → 等待5m确认K线 → LONG
"""
from typing import List, Tuple
from quant.strategies.base import BaseStrategy, Signal, BacktestResult
from quant.data.features import (
    get_funding_at_time, funding_extreme_score,
    candle_score, volume_score, pa_score,
    btc_filter
)
from quant.backtest.engine import run_simple_backtest, compute_metrics


class FundingExtremeStrategy(BaseStrategy):
    """费率极端反转策略"""
    
    name = 'funding_extreme'
    description = '费率跌破-0.05%后等5m确认K线做多，移动止盈，48h超时'
    version = '1.0'
    
    DEFAULT_PARAMS = {
        'funding_threshold': -0.0005,  # -0.05%
        'sl_pct': -0.10,
        'tp_pct': 0.05,
        'max_hold_hours': 48,
        'trailing_activation': 0.05,
        'confirm_score': 0.1,           # 确认K线最低评分
    }
    
    def __init__(self, params: dict = None):
        super().__init__(params or self.DEFAULT_PARAMS)
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}
    
    def generate_signals(self, klines: List[Tuple], 
                         funding_rates: List[Tuple] = None,
                         oi_data: List[Tuple] = None) -> List[Signal]:
        signals = []
        if not funding_rates or len(klines) < 50:
            return signals
        
        p = self.params
        for i in range(50, len(klines)):
            ts = klines[i][0]
            close = klines[i][4]
            
            # 费率条件
            fr = get_funding_at_time(funding_rates, ts)
            if fr >= p['funding_threshold']:
                continue
            
            # 确认K线：需要一定看涨形态
            cn = candle_score(klines, i)
            vl = volume_score(klines, i)
            if cn + vl < p['confirm_score']:
                continue
            
            # BTC 过滤器
            # (在实际使用中会传入BTC K线)
            
            score = funding_extreme_score(funding_rates, ts, p['funding_threshold'])
            signals.append(Signal(
                symbol='',
                direction='LONG',
                score=round(score, 2),
                entry_price=close,
                stop_loss=close * (1 + p['sl_pct']),
                take_profit=close * (1 + p['tp_pct']),
                timestamp=ts,
                strategy=self.name,
                reason=f'FR={fr:.5f} candle={cn:.2f} vol={vl:.2f}',
            ))
        
        return signals
    
    def backtest(self, klines: List[Tuple], 
                 funding_rates: List[Tuple] = None,
                 oi_data: List[Tuple] = None) -> BacktestResult:
        p = self.params
        
        def signal_func(kl, fr, oi, i):
            if not fr:
                return False, 0, ''
            ts = kl[i][0]
            fr_val = get_funding_at_time(fr, ts)
            if fr_val >= p['funding_threshold']:
                return False, 0, ''
            
            cn = candle_score(kl, i)
            vl = volume_score(kl, i)
            if cn + vl < p['confirm_score']:
                return False, 0, ''
            
            score = funding_extreme_score(fr, ts, p['funding_threshold'])
            return True, score, f'FR={fr_val:.5f}'
        
        trades, equity = run_simple_backtest(
            klines, signal_func,
            sl_pct=p['sl_pct'], tp_pct=p['tp_pct'],
            max_hold_hours=p['max_hold_hours'],
            use_trailing_stop=True,
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
