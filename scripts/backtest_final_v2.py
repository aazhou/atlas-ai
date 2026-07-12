"""
Final rigorous backtest with backtesting.py
Fixes:
  1. Volume Breakout: add variants (3x vol + break 20h vs 2x vol + break 10h vs 2x vol + above EMA20)
  2. BTC Leading: finalize_trades=True, tighter altcoin filtering (strong correlation only)
  3. Extended symbol coverage
"""
import sys
sys.path = [p for p in sys.path if 'venv' not in p.lower() and 'hermes-agent' not in p.lower()]

import duckdb, pandas as pd, numpy as np, json, os
from datetime import datetime, timedelta
from backtesting import Backtest, Strategy

DB_PATH = r'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
OUT_DIR = r'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto'

def load_kline(symbol, interval):
    con = duckdb.connect(DB_PATH)
    df = con.execute(f"""
        SELECT open_time, open, high, low, close, volume
        FROM kline WHERE symbol='{symbol}' AND interval='{interval}'
        ORDER BY open_time ASC
    """).fetchdf()
    con.close()
    if df.empty: return df
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df = df.set_index('open_time')
    df.columns = ['Open','High','Low','Close','Volume']
    df = df[~df.index.duplicated(keep='first')]
    return df

def calc_metrics(stats):
    def safe_float(v, default=0.0):
        try: return round(float(v), 3)
        except: return default
    return {
        'start': str(stats.get('Start','')),
        'end': str(stats.get('End','')),
        'duration': str(stats.get('Duration','')),
        'return_pct': safe_float(stats.get('Return [%]',0)),
        'buy_hold_pct': safe_float(stats.get('Buy & Hold Return [%]',0)),
        'sharpe': safe_float(stats.get('Sharpe Ratio',0)),
        'sortino': safe_float(stats.get('Sortino Ratio',0)),
        'max_dd_pct': safe_float(stats.get('Max. Drawdown [%]',0)),
        'win_rate_pct': safe_float(stats.get('Win Rate [%]',0)),
        'profit_factor': safe_float(stats.get('Profit Factor',0)),
        'num_trades': int(stats.get('# Trades',0)),
        'avg_trade_pct': safe_float(stats.get('Avg. Trade [%]',0)),
        'best_trade_pct': safe_float(stats.get('Best Trade [%]',0)),
        'worst_trade_pct': safe_float(stats.get('Worst Trade [%]',0)),
        'exposure_pct': safe_float(stats.get('Exposure Time [%]',0)),
        'equity_final': safe_float(stats.get('Equity Final [$]',100000)),
    }

# ─── Strategy Variants ──────────────────────────────────────────────────────

class VolBreakout_3x20h(Strategy):
    """Original: Vol>3x20MA + Close>=20bar high + Bull bar"""
    def init(self):
        self.vol_ma = self.I(lambda x: pd.Series(x).rolling(20).mean(), self.data.Volume)
        self.high_n = self.I(lambda x: pd.Series(x).rolling(20).max(), self.data.High)
    def next(self):
        if len(self.data) < 25: return
        if self.position.is_long:
            lt = self.trades[-1]
            if len(self.data)-1 - lt.entry_bar >= 96: self.position.close(); return
            pnl = (self.data.Close[-1] - lt.entry_price) / lt.entry_price
            if pnl >= 0.10 or pnl <= -0.08: self.position.close()
            return
        if (self.data.Volume[-1] > 3.0 * self.vol_ma[-1] and
            self.data.Close[-1] >= self.high_n[-1] and
            self.data.Close[-1] > self.data.Open[-1]):
            self.buy()

class VolBreakout_2x10h(Strategy):
    """Variant A: Vol>2x20MA + Close>=10bar high + Bull bar"""
    def init(self):
        self.vol_ma = self.I(lambda x: pd.Series(x).rolling(20).mean(), self.data.Volume)
        self.high_n = self.I(lambda x: pd.Series(x).rolling(10).max(), self.data.High)
    def next(self):
        if len(self.data) < 25: return
        if self.position.is_long:
            lt = self.trades[-1]
            if len(self.data)-1 - lt.entry_bar >= 96: self.position.close(); return
            pnl = (self.data.Close[-1] - lt.entry_price) / lt.entry_price
            if pnl >= 0.10 or pnl <= -0.08: self.position.close()
            return
        if (self.data.Volume[-1] > 2.0 * self.vol_ma[-1] and
            self.data.Close[-1] >= self.high_n[-1] and
            self.data.Close[-1] > self.data.Open[-1]):
            self.buy()

class VolBreakout_2xEMA(Strategy):
    """Variant B: Vol>2x20MA + Close>EMA20 + Bull bar (trend filter not breakout)"""
    def init(self):
        self.vol_ma = self.I(lambda x: pd.Series(x).rolling(20).mean(), self.data.Volume)
        self.ema20 = self.I(lambda x: pd.Series(x).ewm(span=20, adjust=False).mean(), self.data.Close)
    def next(self):
        if len(self.data) < 25: return
        if self.position.is_long:
            lt = self.trades[-1]
            if len(self.data)-1 - lt.entry_bar >= 96: self.position.close(); return
            pnl = (self.data.Close[-1] - lt.entry_price) / lt.entry_price
            if pnl >= 0.10 or pnl <= -0.08: self.position.close()
            return
        if (self.data.Volume[-1] > 2.0 * self.vol_ma[-1] and
            self.data.Close[-1] > self.ema20[-1] and
            self.data.Close[-1] > self.data.Open[-1] and
            self.data.Close[-2] <= self.ema20[-2]):  # cross above EMA20
            self.buy()

class BTCLeadStrict(Strategy):
    """BTC leading with precomputed signal, finalize_trades=True"""
    tp_pct = 0.10
    sl_pct = 0.08
    max_hold = 72
    def init(self): pass
    def next(self):
        if len(self.data) < 60: return
        if self.position.is_long:
            if self.trades:
                lt = self.trades[-1]
                if len(self.data)-1 - lt.entry_bar >= self.max_hold: self.position.close(); return
                pnl = (self.data.Close[-1] - lt.entry_price) / lt.entry_price
                if pnl >= self.tp_pct or pnl <= -self.sl_pct: self.position.close()
            return

# ─── Run All ─────────────────────────────────────────────────────────────────

SYMBOLS_15M = ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','DOGEUSDT',
               'ADAUSDT','AVAXUSDT','SUIUSDT','LINKUSDT','NEARUSDT']

ALT_SYMBOLS_1H = ['ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','DOGEUSDT',
                  'ADAUSDT','AVAXUSDT','LINKUSDT','NEARUSDT','SUIUSDT']

def run_strategy(name, StrategyClass, symbols, interval):
    results = {}
    for sym in symbols:
        df = load_kline(sym, interval)
        if df.empty or len(df) < 40:
            print(f"  [SKIP] {sym}: {len(df)} bars")
            continue
        bt = Backtest(df, StrategyClass, cash=100000, commission=.001, exclusive_orders=True)
        try:
            stats = bt.run()
        except Exception as e:
            print(f"  [ERR] {sym}: {e}")
            continue
        m = calc_metrics(stats)
        if m['num_trades'] > 0:
            print(f"  {sym}: trades={m['num_trades']} ret={m['return_pct']}% sharpe={m['sharpe']} "
                  f"wr={m['win_rate_pct']}% pf={m['profit_factor']} dd={m['max_dd_pct']}%")
        else:
            print(f"  {sym}: 0 trades")
        results[sym] = m
    return results

def run_btc_leading(symbols):
    """BTC leading with finalize_trades=True"""
    btc_df = load_kline('BTCUSDT', '1h')
    if btc_df.empty: return {}
    ema50 = btc_df['Close'].ewm(50, adjust=False).mean()
    btc_cross = (btc_df['Close'] > ema50) & (btc_df['Close'].shift(1) <= ema50.shift(1))
    cross_times = btc_cross[btc_cross].index
    print(f"  BTC 1h EMA50 cross-ups: {len(cross_times)} events")
    
    results = {}
    for sym in symbols:
        alt = load_kline(sym, '1h')
        if alt.empty or len(alt) < 100:
            print(f"  [SKIP] {sym}: {len(alt)} bars")
            continue
        
        cs = max(btc_df.index[0], alt.index[0])
        ce = min(btc_df.index[-1], alt.index[-1])
        alt = alt[cs:ce].copy()
        if len(alt) < 100: continue
        
        # Signal: BTC crossed in last 2h AND alt itself is up
        alt['Signal'] = 0
        for i, (idx, row) in enumerate(alt.iterrows()):
            recent = [t for t in cross_times if idx - pd.Timedelta(hours=2) <= t <= idx]
            if recent and alt['Close'].iloc[i] > alt['Close'].iloc[i-1] if i>0 else False:
                alt.loc[idx, 'Signal'] = 1
        
        sig_count = int(alt['Signal'].sum())
        if sig_count < 2:
            print(f"  {sym}: {sig_count} signals (<2, skip)")
            continue
        
        # Custom strategy that reads Signal
        class BTCLead(Strategy):
            tp_pct=0.10; sl_pct=0.08; max_hold=72
            def init(self):
                self.sig = self.I(lambda x: x, self.data.Signal, name='sig')
            def next(self):
                if len(self.data) < 60: return
                if self.position.is_long:
                    if self.trades:
                        lt = self.trades[-1]
                        if len(self.data)-1 - lt.entry_bar >= self.max_hold: self.position.close(); return
                        pnl = (self.data.Close[-1] - lt.entry_price) / lt.entry_price
                        if pnl >= self.tp_pct or pnl <= -self.sl_pct: self.position.close()
                    return
                if self.sig[-1] > 0:
                    self.buy()
        
        bt = Backtest(alt, BTCLead, cash=100000, commission=.001, exclusive_orders=True, finalize_trades=True)
        stats = bt.run()
        m = calc_metrics(stats)
        m['btc_crosses'] = len(cross_times)
        m['alt_signals'] = sig_count
        print(f"  {sym}: trades={m['num_trades']} ret={m['return_pct']}% sharpe={m['sharpe']} "
              f"wr={m['win_rate_pct']}% pf={m['profit_factor']} dd={m['max_dd_pct']}% "
              f"(signals={sig_count})")
        results[sym] = m
    
    return results

def summarize(name, results):
    if not results: return None
    trades = [m for m in results.values() if m['num_trades'] > 0]
    if not trades:
        return {'strategy': name, 'symbols': len(results), 'total_trades': 0,
                'avg_sharpe': None, 'avg_win_rate': None, 'meets_criteria': False,
                'per_symbol': results, 'verdict': 'NO_TRADES'}
    
    avg_sharpe = round(np.mean([t['sharpe'] for t in trades]), 3)
    avg_wr = round(np.mean([t['win_rate_pct'] for t in trades]), 3)
    avg_ret = round(np.mean([t['return_pct'] for t in trades]), 2)
    avg_dd = round(np.mean([t['max_dd_pct'] for t in trades]), 2)
    avg_pf = round(np.mean([t['profit_factor'] for t in trades]), 3)
    total_tr = sum(t['num_trades'] for t in trades)
    
    meets = avg_sharpe is not None and avg_sharpe > 1.0 and avg_wr > 40
    
    return {
        'strategy': name,
        'symbols_tested': len(results),
        'symbols_with_trades': len(trades),
        'total_trades': total_tr,
        'avg_sharpe': avg_sharpe,
        'avg_win_rate': avg_wr,
        'avg_return_pct': avg_ret,
        'avg_max_dd_pct': avg_dd,
        'avg_profit_factor': avg_pf,
        'meets_criteria': meets,
        'per_symbol': results,
    }

if __name__ == '__main__':
    print("="*70)
    print("FINAL RIGOROUS BACKTEST - backtesting.py v0.6.5")
    print(f"Data: {DB_PATH} | Time: {datetime.now().isoformat()}")
    print("="*70)
    
    summaries = []
    
    # ─── S1: Vol Breakout 3x20h (Original) ───
    print("\n## S1: Vol Breakout 3x20h (Original) [15m]")
    print("   Entry: Vol>3x20MA + Close>=20bar high + Bull bar")
    print("   Exit: TP+10%/SL-8%/Max24h")
    r1 = run_strategy('vol_breakout_3x20h', VolBreakout_3x20h, SYMBOLS_15M, '15m')
    s1 = summarize('volume_breakout_3x20h', r1)
    if s1: summaries.append(s1); print(f"  => {s1['verdict'] if 'verdict' in s1 else ('PASS' if s1['meets_criteria'] else 'FAIL')} sharpe={s1['avg_sharpe']} wr={s1['avg_win_rate']}% trades={s1['total_trades']}")
    
    # ─── S2: Vol Breakout 2x10h (Variant A) ───
    print("\n## S2: Vol Breakout 2x10h (Relaxed) [15m]")
    print("   Entry: Vol>2x20MA + Close>=10bar high + Bull bar")
    r2 = run_strategy('vol_breakout_2x10h', VolBreakout_2x10h, SYMBOLS_15M, '15m')
    s2 = summarize('volume_breakout_2x10h', r2)
    if s2: summaries.append(s2); print(f"  => {'PASS' if s2['meets_criteria'] else 'FAIL'} sharpe={s2['avg_sharpe']} wr={s2['avg_win_rate']}% trades={s2['total_trades']}")
    
    # ─── S3: Vol Breakout 2xEMA (Variant B) ───
    print("\n## S3: Vol Breakout 2xEMA (Trend) [15m]")
    print("   Entry: Vol>2x20MA + Close crosses above EMA20 + Bull bar")
    r3 = run_strategy('vol_breakout_2xEMA', VolBreakout_2xEMA, SYMBOLS_15M, '15m')
    s3 = summarize('volume_breakout_2xEMA', r3)
    if s3: summaries.append(s3); print(f"  => {'PASS' if s3['meets_criteria'] else 'FAIL'} sharpe={s3['avg_sharpe']} wr={s3['avg_win_rate']}% trades={s3['total_trades']}")
    
    # ─── S4: BTC Leading (finalize_trades) ───
    print("\n## S4: BTC Leading (1h) - finalize_trades=True")
    print("   Entry: BTC 1h EMA50 cross + Alt follows within 2h + Alt up")
    print("   Exit: TP+10%/SL-8%/Max72h")
    r4 = run_btc_leading(ALT_SYMBOLS_1H)
    s4 = summarize('btc_leading_1h', r4)
    if s4: summaries.append(s4); print(f"  => {'PASS' if s4['meets_criteria'] else 'FAIL'} sharpe={s4['avg_sharpe']} wr={s4['avg_win_rate']}% trades={s4['total_trades']}")
    
    # ─── S5: BTC Leading - Strong Alts Only (ETH, SOL, LINK, BNB) ───
    print("\n## S5: BTC Leading - Strong Alts Only [1h]")
    print("   Filter: Only ETH, SOL, LINK, BNB (high BTC correlation)")
    r5 = run_btc_leading(['ETHUSDT','SOLUSDT','LINKUSDT','BNBUSDT'])
    s5 = summarize('btc_leading_strong_alts', r5)
    if s5: summaries.append(s5); print(f"  => {'PASS' if s5['meets_criteria'] else 'FAIL'} sharpe={s5['avg_sharpe']} wr={s5['avg_win_rate']}% trades={s5['total_trades']}")
    
    # ─── Save ───
    output = {
        'generated': datetime.now().isoformat(),
        'engine': 'backtesting.py v0.6.5',
        'data_period': 'BTC 15m: 2026-07-01~07-12 | 1h: 2026-06-21~07-12',
        'strategies': summaries,
    }
    
    out_path = os.path.join(OUT_DIR, 'strategies.json')
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\n[DONE] Saved to {out_path}")
    
    # ─── FINAL VERDICT ───
    print("\n" + "="*70)
    print("FINAL VERDICT")
    print("="*70)
    any_pass = False
    for s in summaries:
        syms = s.get('symbols_with_trades', s.get('symbols_tested', 0))
        if s['meets_criteria']:
            print(f"  🟢 {s['strategy']}: Sharpe={s['avg_sharpe']} WR={s['avg_win_rate']}% Trades={s['total_trades']} Syms={syms} → PASS")
            any_pass = True
        elif s.get('verdict') == 'NO_TRADES':
            print(f"  ⚪ {s['strategy']}: 0 trades across all symbols → USELESS")
        else:
            print(f"  🔴 {s['strategy']}: Sharpe={s['avg_sharpe']} WR={s['avg_win_rate']}% Trades={s['total_trades']} Syms={syms} → FAIL")
    
    if not any_pass:
        print("\n  ⚠️ NO STRATEGY MEETS LIVE CRITERIA (Sharpe>1 AND WinRate>40%)")
        print("  Honest assessment: current market conditions (range-bound) don't support these strategies.")
