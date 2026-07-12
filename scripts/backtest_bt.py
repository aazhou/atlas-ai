"""backtesting.py 费率极值策略回测"""
import duckdb, pandas as pd, json
from backtesting import Backtest, Strategy
from datetime import datetime, timedelta

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
con = duckdb.connect(DB, read_only=True)

SYM = 'TUSDT'  # Start with one coin to validate

# Build OHLCV DataFrame from duckdb 15m klines
klines = con.execute(f"""
SELECT open_time/1000 as time, open, high, low, close, volume
FROM kline WHERE symbol='{SYM}' AND interval='15m'
ORDER BY open_time
""").df()

klines['time'] = pd.to_datetime(klines['time'], unit='s')
klines.set_index('time', inplace=True)
klines = klines[['open','high','low','close','volume']]

print(f'{SYM}: {len(klines)} bars, {klines.index[0]} ~ {klines.index[-1]}')

# Funding data
funding = con.execute(f"""
SELECT funding_time/1000 as time, funding_rate
FROM funding WHERE symbol='{SYM}'
ORDER BY funding_time
""").df()
funding['time'] = pd.to_datetime(funding['time'], unit='s')
funding.set_index('time', inplace=True)

# Calculate rolling P5 (100-period lookback = ~33 days of 8h funding)
funding['p5'] = funding['funding_rate'].rolling(100, min_periods=30).quantile(0.05)
funding['signal'] = funding['funding_rate'] < funding['p5']

print(f'Funding: {len(funding)} periods, signals: {funding["signal"].sum()}')

# Merge funding signal with klines
# For each 15m bar, check if there was a funding signal in the last 8 hours
klines['hour'] = klines.index.floor('h')
klines['funding_signal'] = False

for idx in funding[funding['signal']].index:
    window_start = idx
    window_end = idx + pd.Timedelta(hours=24)  # Signal valid for 24h
    mask = (klines.index >= window_start) & (klines.index <= window_end)
    klines.loc[mask, 'funding_signal'] = True

signal_count = klines['funding_signal'].sum()
print(f'Kline bars with active signal: {signal_count}')

con.close()

class FundingReversal(Strategy):
    holding_bars = 96  # 24h in 15m bars
    tp_pct = 0.10
    sl_pct = 0.05
    
    def init(self):
        self.signal = self.I(lambda x: x, self.data.funding_signal)
        self.bars_held = 0
    
    def next(self):
        if self.position:
            self.bars_held += 1
            # Exit conditions
            if self.bars_held >= self.holding_bars:
                self.position.close()
                return
            # Take profit
            if self.data.close[-1] >= self.position.entry_price * (1 + self.tp_pct):
                self.position.close()
                return
            # Stop loss
            if self.data.low[-1] <= self.position.entry_price * (1 - self.sl_pct):
                self.position.close()
                return
        else:
            # Entry: funding signal active AND not already in a position
            if self.signal[-1] and not self.position:
                self.buy(size=1)
                self.bars_held = 0

# Run backtest
bt = Backtest(klines, FundingReversal, cash=10000, commission=0.0004)
stats = bt.run()
print(stats)

# Save equity curve for website
equity_curve = []
for i, row in stats['_equity_curve'].iterrows():
    equity_curve.append({
        'time': str(row.name),
        'equity': round(row['Equity'], 2),
        'drawdown': round(row.get('DrawdownPct', 0), 2)
    })

result = {
    'symbol': SYM,
    'bars': len(klines),
    'date_range': f"{klines.index[0].strftime('%Y-%m-%d')} ~ {klines.index[-1].strftime('%Y-%m-%d')}",
    'signals': int(funding['signal'].sum()),
    'return_pct': round(stats['Return [%]'], 2),
    'sharpe': round(stats.get('Sharpe Ratio', 0), 2),
    'max_dd': round(stats.get('Max. Drawdown [%]', 0), 2),
    'win_rate': round(stats.get('Win Rate [%]', 0), 2),
    'trades': stats.get('# Trades', 0),
    'equity_curve': equity_curve
}

with open(f'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/backtest_{SYM}.json', 'w') as f:
    json.dump(result, f, indent=2, default=str)

print(json.dumps(result, indent=2, default=str))
