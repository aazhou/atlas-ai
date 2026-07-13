#!/usr/bin/env python3
"""Ultra-fast crypto scanner — top-50 volume pairs, LONG_A + LONG_B only"""
import json, time, requests, os, sys
from datetime import datetime

BASE_URL = 'https://fapi.binance.com'
TIMEOUT = 8
SLEEP = 0.05
FR_EXTREME_NEG = -0.0005
PRICE_DROP_PCT = -0.02
OI_SPIKE_PCT = 0.05
EMA_PERIOD = 20
KLINE_LIMIT = 50
TOP_N = 80  # scan top 80 by volume

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'crypto')
OUTPUT_FILE = os.path.join(OUTPUT_DIR, 'signals.json')


def fetch(url, params=None, retries=1):
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception:
            if i == retries:
                return None
            time.sleep(0.3)
    return None


def ema(closes):
    if len(closes) < EMA_PERIOD:
        return None
    k = 2 / (EMA_PERIOD + 1)
    val = sum(closes[:EMA_PERIOD]) / EMA_PERIOD
    for c in closes[EMA_PERIOD:]:
        val = c * k + val * (1 - k)
    return val


def main():
    start = time.time()

    # Step 1: Get tickers to find top volume pairs
    tickers_data = fetch(f'{BASE_URL}/fapi/v1/ticker/24hr')
    if not tickers_data:
        print('[ERR] tickers failed', file=sys.stderr)
        sys.exit(1)

    usdt_tickers = [t for t in tickers_data if t['symbol'].endswith('USDT')]
    usdt_tickers.sort(key=lambda t: float(t.get('quoteVolume', 0)), reverse=True)
    top_symbols = [t['symbol'] for t in usdt_tickers[:TOP_N]]
    ticker_map = {t['symbol']: t for t in usdt_tickers}

    print(f'Top {len(top_symbols)} by volume', file=sys.stderr)

    # Step 2: Get 1h klines for top symbols
    klines_cache = {}
    for i, sym in enumerate(top_symbols):
        k = fetch(f'{BASE_URL}/fapi/v1/klines', {'symbol': sym, 'interval': '1h', 'limit': KLINE_LIMIT})
        time.sleep(SLEEP)
        if k and len(k) >= EMA_PERIOD:
            klines_cache[sym] = [
                {'o': float(c[1]), 'h': float(c[2]), 'l': float(c[3]), 'c': float(c[4]), 'v': float(c[5])}
                for c in k
            ]
        if (i + 1) % 20 == 0:
            print(f'Kline: {i+1}/{len(top_symbols)} cached={len(klines_cache)}', file=sys.stderr)

    print(f'Kline done: {len(klines_cache)}/{len(top_symbols)}', file=sys.stderr)

    # Step 3: L2 scan (LONG_A + LONG_B only)
    signals = []
    for i, (sym, candles) in enumerate(klines_cache.items()):
        closes = [c['c'] for c in candles]
        ema20 = ema(closes)
        latest = candles[-1]
        price_2h_chg = (latest['c'] - candles[-3]['c']) / candles[-3]['c'] if len(candles) >= 3 else 0

        # LONG_A: funding reversal
        fh = fetch(f'{BASE_URL}/fapi/v1/fundingRate', {'symbol': sym, 'limit': 2})
        time.sleep(SLEEP * 0.5)
        if fh and len(fh) >= 2:
            prev_fr = float(fh[0]['fundingRate'])
            curr_fr = float(fh[1]['fundingRate'])
            if prev_fr < FR_EXTREME_NEG and curr_fr >= 0:
                signals.append({
                    'type': 'LONG_A',
                    'symbol': sym,
                    'entry_price': round(latest['c'], 8),
                    'reason': f"费率反转: {prev_fr*100:.4f}%{curr_fr*100:.4f}%",
                    'funding_rate': curr_fr,
                    'price': round(latest['c'], 8),
                    'confidence': 'HIGH' if prev_fr < -0.001 else 'MEDIUM',
                    'stop_loss': round(latest['c'] * 0.96, 8),
                    'take_profit': round(latest['c'] * 1.08, 8),
                })

        # LONG_B: OI divergence
        if price_2h_chg < PRICE_DROP_PCT and ema20 and latest['c'] >= ema20:
            oi5 = fetch(f'{BASE_URL}/fapi/v1/openInterestHist', {'symbol': sym, 'period': '5m', 'limit': 5})
            time.sleep(SLEEP * 0.5)
            if oi5 and len(oi5) >= 2:
                oi_now = float(oi5[-1]['sumOpenInterest'])
                oi_prev = float(oi5[-2]['sumOpenInterest'])
                if oi_prev > 0:
                    oi_chg = (oi_now - oi_prev) / oi_prev
                    if oi_chg > OI_SPIKE_PCT:
                        signals.append({
                            'type': 'LONG_B',
                            'symbol': sym,
                            'entry_price': round(latest['c'], 8),
                            'price': round(latest['c'], 8),
                            'reason': f"OI: {price_2h_chg:.1%} OI+{oi_chg:.1%} EMA20:{ema20:.4f}",
                            'oi_change_pct': round(oi_chg * 100, 2),
                            'price_change_pct': round(price_2h_chg * 100, 2),
                            'ema20': round(ema20, 8),
                            'confidence': 'MEDIUM',
                            'stop_loss': round(latest['c'] * 0.96, 8),
                            'take_profit': round(latest['c'] * 1.08, 8),
                        })

        if (i + 1) % 20 == 0:
            print(f'L2: {i+1}/{len(klines_cache)} sigs={len(signals)}', file=sys.stderr)

    # Also do L1 breakout scan on top symbols
    l1_signals = []
    for sym in top_symbols[:TOP_N]:
        t = ticker_map.get(sym, {})
        try:
            price = float(t.get('lastPrice', 0))
            high = float(t.get('highPrice', 0))
            low = float(t.get('lowPrice', 0))
            chg = float(t.get('priceChangePercent', 0))
            vol = float(t.get('quoteVolume', 0))
            trades = int(t.get('count', 0))
        except (ValueError, KeyError, TypeError):
            continue

        if price <= 0 or high <= 0 or vol < 5_000_000:
            continue

        high_pct = (high - price) / price * 100
        score = 0
        if 0 < high_pct < 3:
            score += 30
        elif 3 <= high_pct < 5:
            score += 20
        if chg > 0:
            score += min(int(chg * 10), 30)
        if vol > 50_000_000:
            score += 20
        elif vol > 20_000_000:
            score += 10
        if trades > 100000:
            score += 5

        if score >= 40:
            l1_signals.append({
                'symbol': sym,
                'price': price,
                'price_change_pct': chg,
                'high_24h': high,
                'low_24h': low,
                'high_proximity_pct': round(high_pct, 2),
                'volume_usdt': vol,
                'trades_count': trades,
                'signal_strength': score,
            })

    l1_signals.sort(key=lambda s: s['signal_strength'], reverse=True)
    l1_signals = l1_signals[:5]

    # Sort by confidence
    conf_order = {'HIGH': 0, 'MEDIUM': 1}
    signals.sort(key=lambda s: conf_order.get(s.get('confidence', 'MEDIUM'), 2))

    type_counts = {}
    for s in signals:
        t = s['type']
        type_counts[t] = type_counts.get(t, 0) + 1

    result = {
        'generated': datetime.now().isoformat(),
        'scan_duration_sec': round(time.time() - start, 1),
        'total_symbols': len(top_symbols),
        'scan_mode': f'top{TOP_N}_fast',
        'l1_breakout': {
            'description': '突破启动 — 量价齐升+近24h高',
            'candidates': len(l1_signals),
            'signals': l1_signals,
        },
        'l2_v5': {
            'description': 'v5.0 费率反转+LONG_B背离(快速扫描top80)',
            'strategy': 'funding_oi_long_only_v5',
            'params': {
                'SL': '-4%',
                'TP': '+8%',
                'hold': '8h',
                'scan_scope': f'TOP {TOP_N} by volume',
                'LONG_A_threshold': f'{FR_EXTREME_NEG:.4%}',
            },
            'type_counts': type_counts,
            'signals_count': len(signals),
            'signals': signals,
        },
        'portfolio': {'positions': [], 'closed': []},
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Print summary
    ts = datetime.now().strftime('%H:%M:%S')
    if signals or l1_signals:
        print(f'[{ts}] L1={len(l1_signals)} L2={len(signals)} {" ".join(f"{k}:{v}" for k,v in sorted(type_counts.items()))}')
        if signals:
            print('── v5.0 实时信号 ──')
            for i, s in enumerate(signals[:15]):
                icon = '🟢' if s['confidence'] == 'HIGH' else '🟡'
                print(f'{i+1}. {icon} {s["type"]:7s} {s["symbol"]:12s} ${s["entry_price"]:<10.4f} SL:${s["stop_loss"]:.4f} TP:${s["take_profit"]:.4f} {s["reason"][:70]}')
        if l1_signals:
            print('── L1突破候选 ──')
            for i, s in enumerate(l1_signals):
                bar = '█' * min(int(s['signal_strength'] / 10), 10)
                print(f'{i+1}. {s["symbol"]:12s} ${s["price"]:<10.4f} chg:{s["price_change_pct"]:+.1f}% 近高:{s["high_proximity_pct"]:.1f}% vol:${s["volume_usdt"]/1e6:.0f}M {s["signal_strength"]:.0f} {bar}')
    else:
        print(f'[{ts}] No signals found')
    print('DONE')


if __name__ == '__main__':
    main()
