"""
Backtest Engine
向量化回测引擎 — 支持多策略、多币种、参数网格搜索
"""
import math
from typing import List, Dict, Tuple, Optional, Callable
from dataclasses import dataclass
from collections import defaultdict

from quant.strategies.base import BacktestResult, Signal
from quant.config import (
    INITIAL_CAPITAL, RISK_PER_TRADE, SLIPPAGE_BPS, COMMISSION_BPS,
    BACKTEST_MIN_TRADES, BACKTEST_MIN_SHARPE, BACKTEST_MAX_DRAWDOWN
)


def compute_metrics(trades: List[dict], initial_capital: float = INITIAL_CAPITAL) -> dict:
    """从交易列表计算所有性能指标"""
    n = len(trades)
    if n == 0:
        return {
            'total_trades': 0, 'win_trades': 0, 'win_rate': 0,
            'avg_return': 0, 'total_return': 0, 'max_drawdown': 0,
            'sharpe_ratio': 0, 'sortino_ratio': 0, 'calmar_ratio': 0,
            'profit_factor': 0, 'avg_hold_hours': 0,
        }
    
    pnls = [t['pnl_pct'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    
    win_rate = len(wins) / n
    avg_return = sum(pnls) / n
    
    # 总收益率（复利）
    total_return = 1.0
    for p in pnls:
        total_return *= (1 + p)
    total_return -= 1
    
    # 最大回撤（从净值曲线）
    equity = [1.0]
    for p in pnls:
        equity.append(equity[-1] * (1 + p))
    peak = equity[0]
    max_dd = 0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak
        if dd > max_dd:
            max_dd = dd
    
    # 夏普比率
    if len(pnls) > 1:
        avg = sum(pnls) / len(pnls)
        var = sum((x - avg) ** 2 for x in pnls) / (len(pnls) - 1)
        std = math.sqrt(var) if var > 0 else 0
        sharpe = (avg / std * math.sqrt(n)) if std > 0 else 0
        sharpe = min(sharpe, 99.99)  # 防止溢出
    else:
        sharpe = 0
    
    # Sortino（只用下行标准差）
    if len(pnls) > 1:
        neg = [p for p in pnls if p < 0]
        if neg:
            down_var = sum(x**2 for x in neg) / len(pnls)
            down_std = math.sqrt(down_var)
            sortino = (avg / down_std * math.sqrt(n)) if down_std > 0 else 0
            sortino = min(sortino, 99.99)
        else:
            sortino = 99.99
    else:
        sortino = 0
    
    # Calmar
    calmar = (total_return / max_dd) if max_dd > 0 else 0
    
    # Profit Factor
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 99
    
    # 平均持仓时间
    avg_hold = 0
    if n > 0:
        holds = [(t.get('exit_time', 0) - t.get('entry_time', 0)) / 3600000 for t in trades]
        avg_hold = sum(holds) / n
    
    return {
        'total_trades': n,
        'win_trades': len(wins),
        'win_rate': win_rate,
        'avg_return': avg_return,
        'total_return': total_return,
        'max_drawdown': max_dd,
        'sharpe_ratio': sharpe,
        'sortino_ratio': sortino,
        'calmar_ratio': calmar,
        'profit_factor': profit_factor,
        'avg_hold_hours': avg_hold,
    }


def _segment_klines(klines: List[Tuple], max_gap_minutes: int = 30) -> List[List[Tuple]]:
    """按数据连续性分段，断层处强制平仓"""
    if not klines:
        return []
    segments = []
    start = 0
    for i in range(1, len(klines)):
        gap = (klines[i][0] - klines[i-1][0]) / 60000
        if gap > max_gap_minutes:
            segments.append(klines[start:i])
            start = i
    if start < len(klines):
        segments.append(klines[start:])
    return segments


def run_simple_backtest(
    klines: List[Tuple],
    signal_func: Callable,
    sl_pct: float = -0.10,
    tp_pct: float = 0.05,
    max_hold_hours: int = 48,
    use_trailing_stop: bool = True,
    trailing_activation: float = 0.05,
    funding_rates: List[Tuple] = None,
    oi_data: List[Tuple] = None,
) -> Tuple[List[dict], List[float]]:
    """
    简化回测引擎 — 自动处理数据断层
    
    Args:
        klines: K线数据 [(open_time, open, high, low, close, volume, ...), ...]
        signal_func: (klines, funding_rates, oi_data, index) -> (is_signal, score, reason)
        sl_pct: 止损百分比（负数）
        tp_pct: 固定止盈百分比
        max_hold_hours: 最大持仓时间
        use_trailing_stop: 是否使用移动止盈
        trailing_activation: 移动止盈激活阈值
        funding_rates: [(time_ms, rate), ...]
        oi_data: [(time_ms, oi_value), ...]
    
    Returns:
        (trades_list, equity_curve)
    """
    segments = _segment_klines(klines)
    all_trades = []
    equity = [1.0]
    
    for seg_idx, seg in enumerate(segments):
        if len(seg) < 50:
            continue
        
        in_position = False
        position = None
        
        for i in range(50, len(seg)):
            current_k = seg[i]
            close = current_k[4]
            ts = current_k[0]
        
            if not in_position:
                is_signal, score, reason = signal_func(seg, funding_rates, oi_data, i)
                if is_signal:
                    entry_price = close * (1 + SLIPPAGE_BPS / 10000)
                    position = {
                        'entry_idx': i, 'entry_price': entry_price, 'entry_time': ts,
                        'score': score, 'reason': reason,
                        'max_price': close, 'highest_price': close,
                        'trailing_activated': False,
                    }
                    in_position = True
            else:
                if close > position['highest_price']:
                    position['highest_price'] = close
                
                pnl_from_entry = (close - position['entry_price']) / position['entry_price']
                if use_trailing_stop and pnl_from_entry >= trailing_activation:
                    position['trailing_activated'] = True
                
                exit_price = None
                exit_reason = None
                
                if pnl_from_entry <= sl_pct:
                    exit_price = close * (1 - SLIPPAGE_BPS / 10000)
                    exit_reason = 'SL'
                elif not position['trailing_activated'] and pnl_from_entry >= tp_pct:
                    exit_price = close * (1 - SLIPPAGE_BPS / 10000)
                    exit_reason = 'TP'
                elif position['trailing_activated']:
                    dd = (position['highest_price'] - close) / position['highest_price']
                    if dd >= 0.03:
                        exit_price = close * (1 - SLIPPAGE_BPS / 10000)
                        exit_reason = 'TRAILING'
                
                if not exit_reason:
                    hold_hours = (ts - position['entry_time']) / 3600000
                    if hold_hours >= max_hold_hours:
                        exit_price = close * (1 - SLIPPAGE_BPS / 10000)
                        exit_reason = 'TIMEOUT'
                
                if exit_price:
                    pnl = (exit_price - position['entry_price']) / position['entry_price']
                    pnl -= COMMISSION_BPS * 2 / 10000
                    all_trades.append({
                        'entry_time': position['entry_time'], 'exit_time': ts,
                        'entry_price': position['entry_price'], 'exit_price': exit_price,
                        'pnl_pct': round(pnl, 6),
                        'max_favorable': round((position['highest_price'] - position['entry_price']) / position['entry_price'], 4),
                        'max_adverse': round(min(0, pnl), 4),
                        'exit_reason': exit_reason, 'score': position['score'],
                    })
                    equity.append(equity[-1] * (1 + pnl))
                    in_position = False
                    position = None
        
        # End of segment → force close
        if in_position and position and seg:
            last_close = seg[-1][4]
            pnl = (last_close - position['entry_price']) / position['entry_price']
            pnl -= COMMISSION_BPS * 2 / 10000
            all_trades.append({
                'entry_time': position['entry_time'], 'exit_time': seg[-1][0],
                'entry_price': position['entry_price'], 'exit_price': last_close,
                'pnl_pct': round(pnl, 6),
                'max_favorable': round((position['highest_price'] - position['entry_price']) / position['entry_price'], 4),
                'max_adverse': round(min(0, pnl), 4),
                'exit_reason': 'GAP', 'score': position['score'],
            })
    
    return all_trades, equity


class GridSearch:
    """参数网格搜索"""
    
    def __init__(self, strategy_class, param_grid: Dict[str, List]):
        self.strategy_class = strategy_class
        self.param_grid = param_grid
        self.results = []
    
    def run(self, klines_data: Dict[str, List], funding_data: Dict[str, List] = None,
            min_trades: int = BACKTEST_MIN_TRADES) -> List[dict]:
        """遍历所有参数组合，返回最优结果"""
        from itertools import product
        
        keys = list(self.param_grid.keys())
        values = list(self.param_grid.values())
        
        for combo in product(*values):
            params = dict(zip(keys, combo))
            
            all_results = []
            for symbol, klines in klines_data.items():
                fr = funding_data.get(symbol) if funding_data else None
                
                strategy = self.strategy_class(params)
                result = strategy.backtest(klines, fr)
                if result and result.total_trades >= min_trades:
                    all_results.append(result)
            
            if all_results:
                # 聚合所有币种结果
                total_trades = sum(r.total_trades for r in all_results)
                avg_sharpe = sum(r.sharpe_ratio for r in all_results) / len(all_results)
                avg_wr = sum(r.win_rate for r in all_results) / len(all_results)
                
                self.results.append({
                    'params': params,
                    'coins_tested': len(klines_data),
                    'coins_with_trades': len(all_results),
                    'total_trades': total_trades,
                    'avg_sharpe': round(avg_sharpe, 2),
                    'avg_win_rate': round(avg_wr, 3),
                    'best_coin': max(all_results, key=lambda r: r.sharpe_ratio).symbol if all_results else None,
                    'results': [r.to_dict() for r in all_results],
                })
        
        # 按夏普排序
        self.results.sort(key=lambda x: x['avg_sharpe'], reverse=True)
        return self.results
