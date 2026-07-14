"""
Parameter Grid Search & Optimizer
参数网格搜索 — 每币种独立最优参数
"""
import sys
import os
import json
import time
from datetime import datetime
from itertools import product
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.config import DUCKDB_PATH
from quant.data.db import DuckDBManager
from quant.strategies.funding_extreme import FundingExtremeStrategy
from quant.strategies.multifactor import MultiFactorStrategy
from quant.backtest.engine import compute_metrics, run_simple_backtest


# === 参数网格 ===

MULTIFACTOR_GRID = {
    'threshold': [0.10, 0.15, 0.18, 0.22, 0.25],
    'sl_pct': [-0.05, -0.08, -0.10, -0.12],
    'tp_pct': [0.03, 0.05, 0.08, 0.10],
    'max_hold_hours': [12, 24, 48],
    'trailing_activation': [0.03, 0.05],
}

FUNDING_EXTREME_GRID = {
    'funding_threshold': [-0.0003, -0.0005, -0.0010],
    'confirm_score': [0.05, 0.10, 0.15],
    'sl_pct': [-0.05, -0.08, -0.10, -0.12],
    'max_hold_hours': [24, 48],
    'trailing_activation': [0.03, 0.05],
}


def search_coin_params(strategy_class, param_grid: Dict, coin: str,
                       klines: List, funding_rates: List = None,
                       min_trades: int = 5, top_n: int = 5) -> List[dict]:
    """对单个币种搜索最优参数"""
    results = []
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    total_combos = 1
    for v in values:
        total_combos *= len(v)
    
    for combo in product(*values):
        params = dict(zip(keys, combo))
        
        # 过滤无意义的组合（TP > abs(SL) 但我们需要盈利空间）
        
        try:
            strategy = strategy_class(params)
            result = strategy.backtest(klines, funding_rates)
            
            if result.total_trades >= min_trades:
                results.append({
                    'params': params,
                    'total_trades': result.total_trades,
                    'win_rate': result.win_rate,
                    'avg_return': result.avg_return,
                    'total_return': result.total_return,
                    'max_drawdown': result.max_drawdown,
                    'sharpe_ratio': result.sharpe_ratio,
                    'sortino_ratio': result.sortino_ratio,
                    'profit_factor': result.profit_factor,
                    'score': result.score,
                    'grade': result.grade,
                })
        except Exception as e:
            continue
    
    # 综合排序：夏普 > 0 优先，然后按 score 排序
    results.sort(key=lambda r: (
        1 if r['sharpe_ratio'] > 0 else 0,
        r['score']
    ), reverse=True)
    
    return results[:top_n]


def main():
    print('=' * 60)
    print('Atlas Quant - Parameter Grid Search')
    print('=' * 60)
    
    db = DuckDBManager(DUCKDB_PATH, read_only=True)
    
    # 深度数据币种
    deep_coins = db.get_coins('5m', min_rows=5000)
    print(f'Deep coins: {deep_coins}')
    
    # 加载费率
    funding_map = db.get_funding_map(deep_coins)
    
    all_best = {}
    
    for coin in deep_coins:
        print(f'\n--- {coin} ---')
        klines = db.get_klines(coin, '5m', limit=10000)
        if len(klines) < 500:
            continue
        
        fr = funding_map.get(coin)
        funding_rates = [(int(time.time()*1000), fr)] if fr else []
        
        # 搜索多因子策略参数
        print(f'  Grid: multifactor ({len(list(product(*MULTIFACTOR_GRID.values())))} combos)...')
        mf_best = search_coin_params(
            MultiFactorStrategy, MULTIFACTOR_GRID, coin, 
            klines, funding_rates, min_trades=5
        )
        
        if mf_best:
            best = mf_best[0]
            print(f'  ✅ Best: thr={best["params"]["threshold"]} '
                  f'SL={best["params"]["sl_pct"]} TP={best["params"]["tp_pct"]} '
                  f'H={best["params"]["max_hold_hours"]}h'
                  f' | {best["total_trades"]}t WR={best["win_rate"]:.0%} '
                  f'Sharpe={best["sharpe_ratio"]:.2f} DD={best["max_drawdown"]:.1%} '
                  f'Score={best["score"]} {best["grade"]}')
            
            all_best[f'{coin}_multifactor'] = {
                'coin': coin,
                'strategy': 'multifactor',
                **best,
            }
        
        # 搜索费率策略参数
        if fr is not None and abs(fr) > 0.0001:
            fe_grid = FUNDING_EXTREME_GRID
            fe_combos = len(list(product(*fe_grid.values())))
            print(f'  Grid: funding_extreme ({fe_combos} combos)...')
            fe_best = search_coin_params(
                FundingExtremeStrategy, fe_grid, coin,
                klines, funding_rates, min_trades=3
            )
            if fe_best:
                best = fe_best[0]
                print(f'  ✅ Best: fr_thr={best["params"]["funding_threshold"]} '
                      f'SL={best["params"]["sl_pct"]} '
                      f'| {best["total_trades"]}t WR={best["win_rate"]:.0%} '
                      f'Sharpe={best["sharpe_ratio"]:.2f}')
                all_best[f'{coin}_funding_extreme'] = {
                    'coin': coin,
                    'strategy': 'funding_extreme',
                    **best,
                }
    
    db.close()
    
    # 输出最优参数表
    print('\n' + '=' * 60)
    print('BEST PARAMS PER COIN')
    print('=' * 60)
    
    sorted_best = sorted(all_best.values(), key=lambda r: r['score'], reverse=True)
    for r in sorted_best:
        emoji = '🟢' if r['grade'] == 'A' else ('🟡' if r['grade'] == 'B' else '🔴')
        p = r['params']
        print(f"\n{emoji} [{r['grade']}] {r['coin']} {r['strategy']} | Score:{r['score']}")
        print(f"  Params: {json.dumps(p)}")
        print(f"  Stats: {r['total_trades']}t WR={r['win_rate']:.0%} "
              f"AvgRet={r['avg_return']:.2%} DD={r['max_drawdown']:.1%} "
              f"Sharpe={r['sharpe_ratio']:.2f}")
    
    # 保存
    output_path = os.path.join(os.path.dirname(DUCKDB_PATH), 'best_params.json')
    with open(output_path, 'w') as f:
        json.dump({
            'run_at': datetime.now().isoformat(),
            'results': sorted_best,
        }, f, indent=2)
    print(f'\n✅ Saved to {output_path}')


if __name__ == '__main__':
    main()
