"""
Sniper Scanner — 量能极值反转狙击 (v3.0)
=========================================
单一策略：量能极值反转 (Volume Climax Reversal)
每15分钟扫描全部USDT永续合约。

五重过滤：
  1. 成交量 > 20倍20周期均量
  2. 收盘价距20周期最低 < 5%
  3. 锤子线确认（阳线 或 下影>30%蜡烛区间）
  4. 资金费率 > 0（非空头主导）
  5. BTC 1h 非急跌（跌幅 > -3% 则跳过全部山寨）

输出：data/crypto/sniper_signals.json
策略来源：data/crypto/sniper_strategy.json (回测胜率83%+)
"""
import json, os, sys, time
from datetime import datetime
import requests

BASE_URL = 'https://fapi.binance.com/fapi/v1'
ATLAS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGNALS_PATH = os.path.join(ATLAS_DIR, 'data', 'crypto', 'sniper_signals.json')
DB_PATH = os.path.join(ATLAS_DIR, 'data', 'crypto', 'market.duckdb')

# ── 策略参数 ──
VOL_MULT = 20           # 量 > N倍20周期均量
NEAR_BOTTOM_PCT = 5     # 价距20底 < N%
WICK_MIN_PCT = 30       # 下影 > N% 蜡烛区间
FUNDING_MIN = 0.0       # 资金费率 > 0 (非空头主导)
BTC_DROP_THRESHOLD = -3 # BTC 1h跌幅超过此值则全局跳过
TP_PCT = 10             # 止盈
SL_PCT = 7              # 止损
HOLD_CANDLES = 32       # 8h 最大持有 (32根15m蜡烛)
MIN_CANDLES = 50        # 最少K线数


def get_all_symbols():
    """从 DuckDB 读取已入库的币种列表（131个24h>$10M）"""
    import duckdb
    con = duckdb.connect(DB_PATH, read_only=True)
    syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM kline ORDER BY symbol").fetchall()]
    con.close()
    return syms


def get_klines(symbol, interval='15m', limit=100):
    """获取K线"""
    try:
        resp = requests.get(f'{BASE_URL}/klines', params={
            'symbol': symbol, 'interval': interval, 'limit': limit
        }, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [{
            'ts': int(d[0]),
            'o': float(d[1]), 'h': float(d[2]),
            'l': float(d[3]), 'c': float(d[4]),
            'v': float(d[5])
        } for d in data]
    except Exception:
        return []


def get_funding_rate(symbol):
    """获取最新资金费率"""
    try:
        resp = requests.get(f'{BASE_URL}/fundingRate', params={
            'symbol': symbol, 'limit': 1
        }, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return float(data[0]['fundingRate']) * 100 if data else None
    except Exception:
        return None


def get_btc_1h_change():
    """获取BTC 1小时涨跌幅 (%)"""
    try:
        klines = get_klines('BTCUSDT', '1h', 6)
        if len(klines) < 2:
            return 0
        last = klines[-2]  # 最近完成的1h蜡烛
        prev = klines[-3]
        return (last['c'] - prev['c']) / prev['c'] * 100
    except Exception:
        return 0


def detect_volume_climax(kline_data, funding_rate):
    """
    量能极值反转检测。
    检查最近一根已完成的15m蜡烛。
    返回信号dict或None。
    """
    if len(kline_data) < MIN_CANDLES:
        return None

    # 最近一根已完成蜡烛 (倒数第二根，最后一根是当前未完成)
    current = kline_data[-2]
    past_20 = kline_data[-22:-2]  # 前20根

    if len(past_20) < 15:
        return None

    # 1. 量能检查：当前量 > 20x 均量
    valid_vols = [c['v'] for c in past_20 if c['v'] > 0]
    avg_vol = sum(valid_vols) / len(valid_vols) if valid_vols else 0
    vol_ratio = current['v'] / avg_vol if avg_vol > 0 else 0
    if vol_ratio < VOL_MULT:
        return None

    # 2. 位置检查：收盘价距20周期最低 < 5%
    past_20_low = min(c['l'] for c in past_20)
    if past_20_low <= 0:
        return None
    near_bottom_pct = (current['c'] - past_20_low) / past_20_low * 100
    if near_bottom_pct > NEAR_BOTTOM_PCT:
        return None

    # 3. 反转K线：阳线 或 长下影 >30%
    candle_range = current['h'] - current['l']
    if candle_range > 0:
        lower_wick = (min(current['o'], current['c']) - current['l']) / candle_range * 100
    else:
        lower_wick = 0
    is_green = current['c'] > current['o']
    if not (is_green or lower_wick > WICK_MIN_PCT):
        return None

    # 4. 资金费率 > 0
    if funding_rate is not None and funding_rate <= FUNDING_MIN:
        return None

    # 5. 计算4h前跌幅（上下文）
    if len(kline_data) >= 18:
        past_4h_start = kline_data[-18]['o']
        past_4h_chg = (current['c'] - past_4h_start) / past_4h_start * 100
    else:
        past_4h_chg = 0

    entry_price = round(current['c'], 6)

    return {
        'vol_ratio': round(vol_ratio, 1),
        'near_bottom_pct': round(near_bottom_pct, 2),
        'lower_wick_pct': round(lower_wick, 1),
        'is_green': is_green,
        'funding_rate': round(funding_rate, 4) if funding_rate is not None else None,
        'past_4h_chg': round(past_4h_chg, 2),
        'entry_price': entry_price,
        'tp_price': round(entry_price * (1 + TP_PCT / 100), 6),
        'sl_price': round(entry_price * (1 - SL_PCT / 100), 6),
        'candle_ts': current['ts']
    }


def load_previous_signals():
    if os.path.exists(SIGNALS_PATH):
        with open(SIGNALS_PATH) as f:
            return json.load(f)
    return {'signals': [], 'last_updated': ''}


def save_signals(data):
    os.makedirs(os.path.dirname(SIGNALS_PATH), exist_ok=True)
    with open(SIGNALS_PATH, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_active_signals(prev_data):
    now = int(time.time() * 1000)
    active = []
    for s in prev_data.get('signals', []):
        if now - s['candle_ts'] < HOLD_CANDLES * 15 * 60 * 1000:
            active.append(s)
    return active


def main():
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[Sniper v3] {ts}  策略: 量能极值反转")

    # ── 全局风控：BTC急跌检查 ──
    btc_1h_chg = get_btc_1h_change()
    print(f"  BTC 1h change: {btc_1h_chg:+.2f}%")
    if btc_1h_chg < BTC_DROP_THRESHOLD:
        print(f"  ⛔ BTC 1h 跌幅 {btc_1h_chg:+.2f}% 超过阈值 {BTC_DROP_THRESHOLD}% — 全局跳过")
        # 仍保存空扫描记录
        prev_data = load_previous_signals()
        active_signals = get_active_signals(prev_data)
        save_signals({
            'signals': active_signals,
            'last_updated': datetime.now().isoformat(),
            'btc_filtered': True,
            'btc_1h_chg': round(btc_1h_chg, 2),
            'strategy': 'volume_climax_reversal',
            'stats': {
                'scanned': 0,
                'new': 0,
                'active': len(active_signals),
                'total': len(active_signals)
            }
        })
        print(f"  BTC filtered | Active: {len(active_signals)}")
        return

    # ── 获取全部交易对 ──
    try:
        symbols = get_all_symbols()
        print(f"  Scanning {len(symbols)} symbols...")
    except Exception as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    # ── 加载历史 ──
    prev_data = load_previous_signals()
    active_signals = get_active_signals(prev_data)

    # ── 扫描 ──
    new_signals = []
    scanned = 0

    for sym in symbols:
        try:
            klines = get_klines(sym, '15m', 100)
            if not klines:
                continue
            scanned += 1

            signal = detect_volume_climax(klines, None)  # 先不拉费率
            if signal is None:
                continue

            # 拉费率（仅在K线信号触发后才拉，节省API调用）
            funding = get_funding_rate(sym)
            if funding is not None and funding <= FUNDING_MIN:
                continue

            # 重新检测（带费率）
            signal = detect_volume_climax(klines, funding)
            if signal is None:
                continue

            signal['symbol'] = sym

            # 去重：同一根蜡烛不重复报警
            already = any(
                s['symbol'] == sym and s['candle_ts'] == signal['candle_ts']
                for s in prev_data.get('signals', [])
            )
            if not already:
                new_signals.append(signal)

        except Exception:
            continue

        # 限速：每50个休息0.15s
        if scanned % 50 == 0:
            time.sleep(0.15)

    # ── 保存 ──
    all_signals = active_signals + new_signals
    save_signals({
        'signals': all_signals,
        'last_updated': datetime.now().isoformat(),
        'btc_filtered': False,
        'btc_1h_chg': round(btc_1h_chg, 2),
        'strategy': 'volume_climax_reversal',
        'strategy_params': {
            'vol_gt': f'{VOL_MULT}x',
            'near_bottom': f'<{NEAR_BOTTOM_PCT}%',
            'hammer': f'green or wick>{WICK_MIN_PCT}%',
            'funding': f'>{FUNDING_MIN}%',
            'btc_1h': f'>{BTC_DROP_THRESHOLD}%',
            'tp': f'+{TP_PCT}%',
            'sl': f'-{SL_PCT}%',
            'hold_max': f'{HOLD_CANDLES * 15 // 60}h'
        },
        'stats': {
            'scanned': scanned,
            'new': len(new_signals),
            'active': len(active_signals),
            'total': len(all_signals)
        }
    })

    # ── 输出 ──
    if new_signals:
        print(f"\n  {'='*50}")
        print(f"  🎯 狙击信号: {len(new_signals)} 笔")
        print(f"  {'='*50}")
        for s in new_signals:
            wick_info = f"wick={s['lower_wick_pct']:.0f}%" if not s['is_green'] else "GREEN"
            fr_str = f"fund={s['funding_rate']:+.4f}%" if s['funding_rate'] else ""
            entry_str = f"{s['entry_price']:.6f}".rstrip('0').rstrip('.')
            tp_str = f"{s['tp_price']:.6f}".rstrip('0').rstrip('.')
            sl_str = f"{s['sl_price']:.6f}".rstrip('0').rstrip('.')
            print(f"  {s['symbol']:16s} vol={s['vol_ratio']:.0f}x  bottom={s['near_bottom_pct']:.1f}%  "
                  f"{wick_info}  {fr_str}")
            print(f"    → Entry={entry_str}  TP={tp_str}  SL={sl_str}")
        print()
        
        # ── 有新信号 → 自动部署到 Vercel ──
        print(f"  🚀 部署到 Vercel...")
        import subprocess
        result = subprocess.run(
            ['vercel', '--prod', '--yes'],
            cwd=ATLAS_DIR,
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'atlas-ai-brown.vercel.app' in line or 'Production' in line:
                    print(f"  ✅ {line.strip()}")
                    break
            else:
                print(f"  ✅ 部署成功")
        else:
            print(f"  [DEPLOY FAIL] {result.stderr.strip()[-200:]}")
    else:
        print(f"  No new signals. Active: {len(active_signals)} | Scanned: {scanned}")

    print(f"Scanned={scanned} | New={len(new_signals)} | Active={len(active_signals)} "
          f"| BTC_1h={btc_1h_chg:+.2f}%")


if __name__ == '__main__':
    main()
