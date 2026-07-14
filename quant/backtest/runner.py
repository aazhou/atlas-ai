"""
Batch Backtest Runner
批量回测：对所有币种运行所有策略，输出结果
"""
import json
import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.config import DUCKDB_PATH, PRIORITY_COINS
from quant.data.db import DuckDBManager
from quant.strategies.funding_extreme import FundingExtremeStrategy
from quant.strategies.multifactor import MultiFactorStrategy
from quant.backtest.engine import compute_metrics


def run_backtest(strategy, coin, klines, funding_rates, oi_data):
    """运行单个策略+币种的回测"""
    try:
        result = strategy.backtest(klines, funding_rates, oi_data)
        result.symbol = coin
        return result
    except Exception as e:
        print(f'  [{strategy.name}] {coin}: ERROR - {e}')
        return None


def main():
    print('=' * 60)
    print('Atlas Quant System - Batch Backtest')
    print('=' * 60)
    
    db = DuckDBManager(DUCKDB_PATH, read_only=True)
    
    # 获取有足量数据的币种
    coins_5m = db.get_coins('5m', min_rows=1000)
    coins_with_deep = [c for c in PRIORITY_COINS if c in coins_5m]
    
    print(f'\n深度数据币种 (5m ≥1000 rows): {len(coins_with_deep)}')
    print(f'普通数据币种 (5m ≥100 rows): {len(coins_5m)}')
    
    # 优先深度数据币种
    priority = [c for c in PRIORITY_COINS[:6] if c in coins_5m]  # BTC/ETH/SOL/BNB/XRP/ADA
    mid_caps = [c for c in PRIORITY_COINS[6:] if c in coins_with_deep]
    
    print(f'\n深度回测币种: {priority + mid_caps}')
    
    # 初始化策略
    strategies = [
        MultiFactorStrategy(),
        FundingExtremeStrategy(),
    ]
    
    # 预加载费率
    funding_map = db.get_funding_map(coins_5m)
    print(f'预加载费率: {len(funding_map)} coins')
    
    all_results = []
    
    for coin in priority + mid_caps[:10]:  # 限制回测币种数量
        print(f'\n--- {coin} ---')
        
        # 加载多周期K线
        klines_data = db.get_multi_tf_klines(coin, ('5m', '1h', '4h'), limit=2000)
        if '5m' not in klines_data or len(klines_data['5m']) < 500:
            print(f'  SKIP: insufficient 5m data ({len(klines_data.get("5m", []))} rows)')
            continue
        
        klines_5m = klines_data['5m']
        
        # 费率数据
        fr = funding_map.get(coin)
        if fr is not None:
            funding_rates = [(int(time.time() * 1000), fr)]
        else:
            funding_rates = []
        
        # OI数据（如果有）
        oi_rows = db.get_oi_history(coin, limit=500)
        
        for strategy in strategies:
            result = run_backtest(strategy, coin, klines_5m, funding_rates, oi_rows)
            if result and result.total_trades >= 3:
                all_results.append(result.to_dict())
                print(f'  [{result.strategy_name}] {result.total_trades} trades | '
                      f'WR={result.win_rate:.1%} | Sharpe={result.sharpe_ratio:.2f} | '
                      f'DD={result.max_drawdown:.1%} | Score={result.score} {result.grade}')
    
    db.close()
    
    # 按评分排序
    all_results.sort(key=lambda r: r['score'], reverse=True)
    
    # 输出摘要
    print('\n' + '=' * 60)
    print('TOP RESULTS')
    print('=' * 60)
    
    for r in all_results[:10]:
        grade_emoji = '🟢' if r['grade'] == 'A' else ('🟡' if r['grade'] == 'B' else '🔴')
        print(f"\n{grade_emoji} [{r['grade']}] {r['symbol']} - {r['strategy']} | Score: {r['score']}")
        print(f"  Trades: {r['total_trades']} | Win Rate: {r['win_rate']:.1%} | "
              f"Avg Return: {r['avg_return']:.2%} | MaxDD: {r['max_drawdown']:.1%}")
        print(f"  Sharpe: {r['sharpe_ratio']:.2f} | Sortino: {r['sortino_ratio']:.2f} | "
              f"PF: {r['profit_factor']:.2f}")
    
    # 保存结果
    output_path = os.path.join(os.path.dirname(DUCKDB_PATH), 'backtest_batch.json')
    output = {
        'run_at': datetime.now().isoformat(),
        'total_combinations': len(all_results),
        'a_grade': len([r for r in all_results if r['grade'] == 'A']),
        'b_grade': len([r for r in all_results if r['grade'] == 'B']),
        'c_grade': len([r for r in all_results if r['grade'] == 'C']),
        'results': all_results,
    }
    
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f'\n✅ Results saved to: {output_path}')
    print(f'   A: {output["a_grade"]} | B: {output["b_grade"]} | C: {output["c_grade"]}')


if __name__ == '__main__':
    main()
