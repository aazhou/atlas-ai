"""
Atlas Quant System - Configuration
数字货币AI量化交易系统
"""
import os

# === Paths ===
BASE_DIR = r'C:\Users\admin\aazhous-projects\atlas-ai'
QUANT_DIR = os.path.join(BASE_DIR, 'quant')
DATA_DIR = os.path.join(BASE_DIR, 'data', 'crypto')
DUCKDB_PATH = os.path.join(DATA_DIR, 'market.duckdb')
PORTFOLIO_PATH = os.path.join(DATA_DIR, 'portfolio.json')
SIGNALS_PATH = os.path.join(DATA_DIR, 'signals.json')

# === Risk Management ===
INITIAL_CAPITAL = 100_000          # USD
MAX_POSITIONS = 3                   # 最大同时持仓
RISK_PER_TRADE = 0.02              # 每笔交易风险 2%
MAX_DAILY_LOSS = 0.05              # 日最大亏损 5% → 停摆
MAX_CORRELATION = 0.7              # 仓位间最大相关性
KELLY_FRACTION = 0.5               # Kelly 分数仓位

# === Execution ===
DEFAULT_LEVERAGE = 1               # 默认杠杆（现货）
SLIPPAGE_BPS = 5                   # 滑点假设 5bps
COMMISSION_BPS = 4                 # 手续费 4bps (taker)

# === Strategy Parameters ===
# Funding Extreme Strategy (V10 validated)
FUNDING_THRESHOLD = -0.0005        # 费率 < -0.05% → 触发
FUNDING_HOLD_HOURS = 48
FUNDING_SL = -0.10
FUNDING_TP_TRAILING = 0.05         # 移动止盈激活点

# Multi-Factor Strategy (V11 validated)
MF_WEIGHTS = {'candle': 0.2, 'vol': 0.4, 'pa': 0.3, 'trend': 0.1}
MF_THRESHOLD = 0.18
MF_SL = -0.10
MF_TP = 0.05                       # 移动止盈
MF_HOLD_HOURS = 48

# === Backtest ===
BACKTEST_MIN_TRADES = 5            # 最少交易笔数（统计显著）
BACKTEST_MIN_SHARPE = 1.0          # 最低夏普
BACKTEST_MAX_DRAWDOWN = 0.35       # 最大回撤限制

# === Timeframes ===
TF_5M = '5m'
TF_15M = '15m'
TF_1H = '1h'
TF_4H = '4h'
TF_1D = '1d'

# === Binance API ===
BINANCE_REST_BASE = 'https://fapi.binance.com'
BINANCE_KLINE_LIMIT = 1000
BINANCE_RATE_LIMIT = 0.1           # seconds between requests

# === Top 30 liquidity coins (volume > $10M) ===
PRIORITY_COINS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT',
    'ADAUSDT', 'DOGEUSDT', 'AVAXUSDT', 'LINKUSDT', 'SUIUSDT',
    'NEARUSDT', 'UNIUSDT', 'AAVEUSDT', 'BCHUSDT', 'XLMUSDT',
    'WLDUSDT', 'ARBUSDT', 'ENAUSDT', 'HBARUSDT', 'TAOUSDT',
    'VANRYUSDT', 'SKLUSDT', 'TUSDT', 'ZECUSDT', 'DEXEUSDT',
    'HYPEUSDT', 'VIRTUALUSDT', 'BEATUSDT', 'LITUSDT', 'EVAAUSDT',
]
