"""
Atlas Quant → V11 Bridge
桥接新 quant 系统到现有 v11_trading_cron.py 基础设施

用法（cron 调用）:
  /c/Python314/python quant/bridge.py

替代 v11_sim_trading.py，使用新 quant 系统的 Scanner + PortfolioManager
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.config import DUCKDB_PATH, SIGNALS_PATH, PORTFOLIO_PATH, PRIORITY_COINS
from quant.data.db import DuckDBManager
from quant.execution.scanner import Scanner, PortfolioManager
from quant.strategies.multifactor import MultiFactorStrategy
from quant.strategies.funding_extreme import FundingExtremeStrategy


def load_best_params():
    """加载每币种最优参数"""
    params_path = os.path.join(os.path.dirname(DUCKDB_PATH), 'best_params.json')
    if not os.path.exists(params_path):
        return {}
    with open(params_path) as f:
        data = json.load(f)
    return {r['coin']: r['params'] for r in data.get('results', [])}


def main():
    has_change = False
    best_params = load_best_params()
    
    # 初始化
    scanner = Scanner()
    portfolio = PortfolioManager()
    
    # 扫描信号
    signals = scanner.scan_all(PRIORITY_COINS[:20])  # 前20流动性币种
    
    # 按策略分组，取Top 3信号
    top_signals = signals[:3]
    
    for sig in top_signals:
        # 检查已有持仓
        existing = [p for p in portfolio.positions if p['symbol'] == sig.symbol]
        if existing:
            continue
        
        # 开仓
        pos = portfolio.open_position(sig)
        if pos:
            has_change = True
            print(f'OPEN {sig.symbol} {sig.strategy} @{sig.entry_price:.4f} score={sig.score}')
    
    # 更新价格
    from quant.config import PRIORITY_COINS
    # get prices from Binance
    import urllib.request
    price_map = {}
    for sym in {p['symbol'] for p in portfolio.positions}:
        try:
            url = f'https://api.binance.com/api/v3/ticker/price?symbol={sym}'
            r = urllib.request.urlopen(url, timeout=5)
            d = json.loads(r.read())
            price_map[sym] = float(d['price'])
        except:
            pass
    
    portfolio.update_prices(price_map)
    
    # 检查出场
    exits = portfolio.check_exits()
    for trade in exits:
        has_change = True
        sym = trade['symbol']
        ep = trade['exit_price']
        pnl = trade['pnl_pct']
        reason = trade['exit_reason']
        print(f'CLOSE {sym} @{ep:.4f} pnl={pnl:.2%} [{reason}]')
    
    # Export signals
    scanner.export_signals(signals)
    
    # Stats
    stats = portfolio.get_stats()
    if has_change:
        n_open = stats['open_positions']
        n_closed = stats['closed_trades']
        pnl_pct = stats['total_pnl_pct']
        wr = stats['win_rate']
        print(f'STATS: {n_open} open, {n_closed} closed, PnL={pnl_pct:.2%}, WR={wr:.0%}')
    
    return has_change


if __name__ == '__main__':
    has_change = main()
    if not has_change:
        # Silent exit — no stdout = cron doesn't deliver
        pass
