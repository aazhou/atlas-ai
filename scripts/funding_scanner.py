"""费率极值信号扫描 + 模拟持仓跟踪 — 当 funding < P5 时触发 LONG 信号"""
import duckdb, json, time, urllib.request, os, sys
from datetime import datetime, timezone, timedelta

DB = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb'
OUT = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/signals.json'
PF = 'C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/portfolio.json'
BJ = timezone(timedelta(hours=8))

con = duckdb.connect(DB, read_only=True)
syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM funding ORDER BY symbol").fetchall()]

now = datetime.now(BJ)
signals = []

# ── Load portfolio ──
portfolio = {"positions": [], "closed": [], "updated": ""}
if os.path.exists(PF):
    try:
        with open(PF, 'r', encoding='utf-8') as f:
            portfolio = json.load(f)
            # migrate old format
            if "closed" not in portfolio:
                portfolio["closed"] = []
    except Exception:
        pass

# Index open positions by raw symbol (includes USDT suffix)
pos_map = {}
for p in portfolio.get("positions", []):
    pos_map[p["symbol"]] = p

closed_now = []  # newly closed this scan

for sym in syms:
    # Calculate P5 from all historical funding for this coin
    p5 = con.execute(f"SELECT PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY funding_rate) FROM funding WHERE symbol='{sym}'").fetchone()[0]
    if not p5: continue

    # Get latest funding rate
    latest = con.execute(f"SELECT funding_rate FROM funding WHERE symbol='{sym}' ORDER BY funding_time DESC LIMIT 1").fetchone()
    if not latest: continue

    curr_fr = latest[0]

    # Previous funding rate for context
    prev = con.execute(f"SELECT funding_rate FROM funding WHERE symbol='{sym}' ORDER BY funding_time DESC LIMIT 1 OFFSET 1").fetchone()
    prev_fr = prev[0] if prev else None

    # Trend check: 4h EMA21 > EMA50?
    trend = con.execute(f"""
    SELECT CASE WHEN 
        (SELECT AVG(close) FROM (SELECT close FROM kline WHERE symbol='{sym}' AND interval='4h' ORDER BY open_time DESC LIMIT 21) t1) >
        (SELECT AVG(close) FROM (SELECT close FROM kline WHERE symbol='{sym}' AND interval='4h' ORDER BY open_time DESC LIMIT 50) t2)
    THEN 1 ELSE 0 END
    """).fetchone()[0]

    # Get real-time ticker price (not delayed K-line close)
    try:
        ticker_url = f'https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}'
        ticker_data = json.loads(urllib.request.urlopen(ticker_url, timeout=5).read())
        entry_px = float(ticker_data['price'])
    except:
        continue

    symbol_short = sym.replace('USDT', '')

    # ── Portfolio management ──
    close_reason = None
    close_pnl = None

    if sym in pos_map:
        # Existing position: update current price & check exit conditions
        pos = pos_map[sym]
        pos["current_price"] = round(entry_px, 6)
        cost = pos["entry_price"]
        pnl_pct = round((entry_px / cost - 1) * 100, 2) if cost else 0
        pos["unrealized_pnl"] = pnl_pct

        # Exit conditions
        entry_time_str = pos.get("entry_time", "")
        try:
            entry_time = datetime.fromisoformat(entry_time_str)
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=BJ)
            hours_held = (now - entry_time).total_seconds() / 3600
        except Exception:
            hours_held = 0

        if entry_px >= cost * 1.10:
            close_reason = "止盈 +10%"
            close_pnl = round((entry_px / cost - 1) * 100, 2)
        elif entry_px <= cost * 0.90:
            close_reason = "止损 -10%"
            close_pnl = round((entry_px / cost - 1) * 100, 2)
        elif hours_held >= 48:
            close_reason = f"超时 {hours_held:.0f}h"
            close_pnl = pnl_pct

        if close_reason:
            pos["exit_reason"] = close_reason
            pos["exit_price"] = round(entry_px, 6)
            pos["exit_pnl"] = close_pnl
            pos["exit_time"] = now.strftime('%Y-%m-%d %H:%M:%S')
            portfolio.setdefault("closed", []).insert(0, pos)
            closed_now.append(pos)
    else:
        # Only create new position if signal is active
        if curr_fr < p5:
            new_pos = {
                "symbol": sym,
                "symbol_short": symbol_short,
                "entry_price": round(entry_px, 6),
                "current_price": round(entry_px, 6),
                "unrealized_pnl": 0.0,
                "entry_time": now.strftime('%Y-%m-%d %H:%M:%S'),
                "strategy": "funding_extreme",
                "funding_at_entry": round(curr_fr * 100, 4),
                "p5_at_entry": round(p5 * 100, 4),
                "trend_up": bool(trend),
            }
            portfolio.setdefault("positions", []).append(new_pos)
            pos_map[sym] = new_pos

    # ── Signal output (only when funding < P5) ──
    if curr_fr < p5:
        confidence = 'HIGH' if curr_fr < p5 * 1.5 else 'MEDIUM'
        if trend: confidence = 'HIGH'

        # Current price & unrealized PnL from portfolio if tracked
        cp = None
        upnl = None
        if sym in pos_map:
            cp = pos_map[sym].get("current_price")
            upnl = pos_map[sym].get("unrealized_pnl")

        signals.append({
            'symbol': symbol_short,
            'funding_rate': round(curr_fr*100, 4),
            'p5_threshold': round(p5*100, 4),
            'entry_price': round(entry_px, 6) if entry_px else None,
            'current_price': round(cp, 6) if cp else round(entry_px, 6),
            'unrealized_pnl': round(upnl, 2) if upnl is not None else 0.0,
            'trend_up': bool(trend),
            'direction': 'LONG','confidence': confidence,
            'stop_loss': round(entry_px*0.90, 6) if entry_px else None,
            'take_profit': round(entry_px*1.10, 6) if entry_px else None,
            'reason': f'费率{curr_fr*100:.3f}%<P5({p5*100:.3f}%) {"+4h涨势" if trend else ""}',
            'time': now.strftime('%H:%M:%S')
        })

# ── Check remaining tracked positions not in current symbol scan ──
tracked_syms = set(syms)
for sym, pos in list(pos_map.items()):
    if sym in tracked_syms:
        continue  # already processed above
    # Update current price for this orphaned position
    entry_row = con.execute(f"SELECT close FROM kline WHERE symbol='{sym}' AND interval='15m' ORDER BY open_time DESC LIMIT 1").fetchone()
    if not entry_row:
        continue
    cur_px = entry_row[0]
    cost = pos["entry_price"]
    pos["current_price"] = round(cur_px, 6)
    pnl_pct = round((cur_px / cost - 1) * 100, 2) if cost else 0
    pos["unrealized_pnl"] = pnl_pct

    # Exit conditions
    entry_time_str = pos.get("entry_time", "")
    try:
        entry_time = datetime.fromisoformat(entry_time_str)
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=BJ)
        hours_held = (now - entry_time).total_seconds() / 3600
    except Exception:
        hours_held = 0

    close_reason = None
    if cur_px >= cost * 1.10:
        close_reason = "止盈 +10%"
    elif cur_px <= cost * 0.90:
        close_reason = "止损 -10%"
    elif hours_held >= 48:
        close_reason = f"超时 {hours_held:.0f}h"

    if close_reason:
        pos["exit_reason"] = close_reason
        pos["exit_price"] = round(cur_px, 6)
        pos["exit_pnl"] = round((cur_px / cost - 1) * 100, 2)
        pos["exit_time"] = now.strftime('%Y-%m-%d %H:%M:%S')
        portfolio.setdefault("closed", []).insert(0, pos)
        closed_now.append(pos)

con.close()

# ── Remove closed positions from open list ──
closed_symbols = {p["symbol"] for p in closed_now}
portfolio["positions"] = [p for p in portfolio.get("positions", []) if p["symbol"] not in closed_symbols]
portfolio["updated"] = now.strftime('%Y-%m-%d %H:%M:%S')

# Write portfolio.json
with open(PF, 'w', encoding='utf-8') as f:
    json.dump(portfolio, f, indent=2, ensure_ascii=False)

# ── Output signals.json ──
output = {
    'updated': now.strftime('%Y-%m-%d %H:%M:%S'),
    'strategy': 'funding_extreme_long',
    'description': 'Funding rate below P5 percentile → LONG with 4h trend filter + simulated portfolio',
    'signal_count': len(signals),
    'signals': signals,
    'portfolio': {
        'open_count': len(portfolio.get("positions", [])),
        'closed_total': len(portfolio.get("closed", [])),
        'closed_recent': [
            {
                'symbol': p.get('symbol_short', p['symbol'].replace('USDT','')),
                'entry_price': p['entry_price'],
                'exit_price': p.get('exit_price'),
                'exit_pnl': p.get('exit_pnl'),
                'exit_reason': p.get('exit_reason'),
                'exit_time': p.get('exit_time'),
            }
            for p in closed_now
        ] if closed_now else [],
        'open_positions': [
            {
                'symbol': p.get('symbol_short', p['symbol'].replace('USDT','')),
                'entry_price': p['entry_price'],
                'current_price': p.get('current_price'),
                'unrealized_pnl': p.get('unrealized_pnl'),
                'entry_time': p.get('entry_time'),
            }
            for p in portfolio.get("positions", [])
        ],
    }
}

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

# ── Print summary ──
print(f"Scanned {len(syms)} coins | {len(signals)} signals | {len(portfolio.get('positions',[]))} open | {len(closed_now)} closed")
for s in signals[:5]:
    pnl_str = f' PnL={s["unrealized_pnl"]:+.2f}%' if s["unrealized_pnl"] != 0 else ''
    print(f"  {s['symbol']:10s} FR={s['funding_rate']:+.4f}% < P5={s['p5_threshold']:+.4f}% {'↑' if s['trend_up'] else '↓'} {s['confidence']} @${s['current_price']}{pnl_str}")
for c in closed_now:
    print(f"  🔔 平仓: {c.get('symbol_short',c['symbol'].replace('USDT',''))} {c['exit_reason']} PnL={c.get('exit_pnl',0):+.2f}%")
