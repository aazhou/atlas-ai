import duckdb, json, math
from datetime import datetime

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
con = duckdb.connect(DB, read_only=True)

top20_syms = [s[0] for s in con.execute("""
    SELECT symbol FROM (
        SELECT symbol, AVG(volume*close) as avg_vol FROM kline WHERE interval='15m'
        GROUP BY symbol ORDER BY avg_vol DESC LIMIT 20
    )
""").fetchall()]

coin_params = {}
for sym in top20_syms:
    kl_15m = con.execute(f"SELECT open_time/1000, high, low, close FROM kline WHERE symbol='{sym}' AND interval='15m' ORDER BY open_time DESC LIMIT 200").fetchall()
    if len(kl_15m) < 100: continue
    
    trs = []
    for i in range(len(kl_15m)-1, max(len(kl_15m)-15, 0), -1):
        h = kl_15m[i][1]; l = kl_15m[i][2]
        pc = kl_15m[i+1][3] if i+1 < len(kl_15m) else kl_15m[i][3]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    atr = sum(trs)/len(trs) if trs else kl_15m[-1][3]*0.01
    
    price = kl_15m[0][3]
    vol_ratio = (atr / price * 100) if price > 0 else 1
    
    spreads = [(kl_15m[i][1]-kl_15m[i][2])/kl_15m[i][3]*100 for i in range(min(50, len(kl_15m)))]
    avg_spread = sum(spreads)/len(spreads) if spreads else 0.5
    
    vol_data = con.execute(f"SELECT AVG(volume*close) FROM kline WHERE symbol='{sym}' AND interval='15m'").fetchone()[0] or 0
    
    tier = 'HIGH' if vol_ratio > 2 else ('MED' if vol_ratio > 1 else 'LOW')
    
    coin_params[sym] = {
        'atr': round(atr, 8),
        'vol_ratio': round(vol_ratio, 2),
        'avg_spread': round(avg_spread, 2),
        'liquidity': round(vol_data, 0),
        'risk_tier': tier
    }

con.close()

# Print
print('=== 币种特性分析 ===')
header = '%-14s %6s %8s %6s %12s' % ('币种', 'ATR%', '振幅%', '风险', '流动性')
print(header)
for sym in sorted(coin_params, key=lambda x: coin_params[x]['liquidity'], reverse=True):
    p = coin_params[sym]
    row = '%-14s %5.1f%% %7.1f%% %6s $%10.0f' % (sym, p['vol_ratio'], p['avg_spread'], p['risk_tier'], p['liquidity'])
    print(row)

# Strategy design
strategy = {
    "name": "PA-V3 日内趋势跟踪",
    "principles": [
        "价格行为为主: 只在大周期S/R位等待15m反转K线入场",
        "均线为辅: 4h EMA20/50定方向, 15m EMA13做移动止盈",
        "每币种独立参数: 基于ATR动态设定止损止盈",
        "加密特性: 避开低流动性时段, BTC急跌暂停做多"
    ],
    "timeframes": {
        "trend": "4h EMA20 vs EMA50 判定趋势方向",
        "structure": "1h 识别关键支撑阻力位(前高/前低/EMA)",
        "entry": "15m 等待PA反转信号(pinbar/吞没/孕线突破) + 放量>1.5x"
    },
    "entry_conditions": [
        "1. 4h EMA20 > EMA50(做多) 或 EMA20 < EMA50(做空)",
        "2. 价格在1h关键位+-1%范围内",
        "3. 15m出现反转PA形态",
        "4. 15m成交量 > 前10根均值1.5倍"
    ],
    "stop_loss": "入场K线反侧极点 + 1 ATR(动态, 非固定%)",
    "take_profit": [
        "TP1: 1:1.5 RR 平50%",
        "TP2: 移动止盈用15m EMA13跟踪"
    ],
    "position_sizing": {
        "per_trade_risk": "账户2%",
        "max_concurrent": 3,
        "high_vol_coins": "仓位减半"
    },
    "crypto_specific": [
        "BTC 15分钟内急跌>2% -> 暂停所有做多",
        "资金费率极端(<-0.1%或>0.1%) -> 顺费率方向",
        "亚洲早盘(9-11点)流动性好, 欧美重叠(20-23点)波动大, 凌晨(2-6点)不交易"
    ],
    "coin_params": coin_params
}

with open('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/strategy_pa_v3.json', 'w') as f:
    json.dump(strategy, f, ensure_ascii=False, indent=2)

print('\n策略已保存: strategy_pa_v3.json')
print('覆盖币种: %d个' % len(coin_params))
