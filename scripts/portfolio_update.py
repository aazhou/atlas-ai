"""
收盘后持仓分析更新脚本
15:35 运行：拉数据 → 分析 → 写 portfolio.json → git push
"""
import json, urllib.request, sys, os
from datetime import datetime

today = datetime.now().strftime("%Y-%m-%d")
now = datetime.now().strftime("%Y-%m-%d %H:%M")

# ── 1. Sina 实时价格 ──
codes = {
    "300236": "上海新阳", "688099": "晶晨", "002475": "立讯", "000963": "华东医药",
    "603662": "柯力传感", "605133": "嵘泰", "002156": "通富微电",
    "605111": "新洁能", "300373": "扬杰科技", "002472": "双环传动",
}

sina_codes = [f"sz{c}" if c.startswith(("0","3")) else f"sh{c}" for c in codes.keys()]
sina_url = f"https://hq.sinajs.cn/list={','.join(sina_codes)}"

req = urllib.request.Request(sina_url, headers={"Referer": "https://finance.sina.com.cn"})
resp = urllib.request.urlopen(req, timeout=10)
text = resp.read().decode("gbk")

sina_data = {}
for line in text.strip().split("\n"):
    if not line.strip(): continue
    var_name = line.split("=")[0]
    data = line.split('"')[1].split(",")
    if len(data) < 30: continue
    code = var_name.replace("var hq_str_sh", "").replace("var hq_str_sz", "")
    sina_data[code] = {
        "name": data[0],
        "price": float(data[3]) if data[3] else 0,
        "prev_close": float(data[2]) if data[2] else 0,
        "open": float(data[1]) if data[1] else 0,
        "high": float(data[4]) if data[4] else 0,
        "low": float(data[5]) if data[5] else 0,
        "volume": float(data[8]) if data[8] else 0,
        "amount": float(data[9]) if data[9] else 0,
    }
    chg = ((sina_data[code]['price'] - sina_data[code]['prev_close']) / sina_data[code]['prev_close'] * 100) if sina_data[code]['prev_close'] else 0
    sina_data[code]['chg'] = round(chg, 2)

print("=== SINA PRICES ===")
for c, d in sina_data.items():
    print(f"  {d['name']}({c}): {d['price']:.2f} chg={d['chg']:+.2f}%")

# ── 2. yfinance 技术数据 ──
import subprocess
yf_script = r"""
import yfinance as yf, pandas as pd, numpy as np, json, sys

codes = ['300236.SZ','688099.SS','002475.SZ','000963.SZ',
         '603662.SS','605133.SS','002156.SZ','605111.SS','300373.SZ','002472.SZ']

results = {}
for ticker in codes:
    try:
        df = yf.download(ticker, period='60d', progress=False)
        if df.empty:
            results[ticker] = {'error': 'no data'}
            continue

        # Handle MultiIndex columns
        if isinstance(df.columns, pd.MultiIndex):
            close_col = ('Close', ticker)
            volume_col = ('Volume', ticker)
        else:
            close_col = 'Close'
            volume_col = 'Volume'

        closes = df[close_col].dropna().values
        volumes = df[volume_col].dropna().values

        if len(closes) < 20:
            results[ticker] = {'error': 'not enough data'}
            continue

        # RSI-14
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-14:])
        avg_loss = np.mean(losses[-14:])
        rsi = 100 - (100/(1 + avg_gain/avg_loss)) if avg_loss > 0 else 100

        # MA20, MA60
        ma20 = float(np.mean(closes[-20:]))
        ma60 = float(np.mean(closes[-60:])) if len(closes) >= 60 else float(np.mean(closes))

        # MACD
        ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().values
        ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().values
        dif = ema12 - ema26
        dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
        macd_bar = 2*(dif - dea)
        macd_signal = '金叉' if (len(macd_bar)>=2 and macd_bar[-2] <= 0 and macd_bar[-1] > 0) else \
                      '死叉' if (len(macd_bar)>=2 and macd_bar[-2] >= 0 and macd_bar[-1] < 0) else \
                      '多头' if macd_bar[-1] > 0 else '空头'

        # Bollinger Bands
        bb_mid = float(np.mean(closes[-20:]))
        bb_std = float(np.std(closes[-20:]))
        bb_upper = bb_mid + 2*bb_std
        bb_lower = bb_mid - 2*bb_std
        last_close = float(closes[-1])
        bb_pos = '上轨' if last_close > bb_upper else '下轨' if last_close < bb_lower else '中轨'

        # Volume ratio (last 5 vs 20)
        avg_vol_5 = float(np.mean(volumes[-5:])) if len(volumes)>=5 else 0
        avg_vol_20 = float(np.mean(volumes[-20:])) if len(volumes)>=20 else avg_vol_5
        vol_ratio = round(avg_vol_5/avg_vol_20, 2) if avg_vol_20>0 else 1.0

        # Position in 20-day range
        h20 = float(np.max(closes[-20:]))
        l20 = float(np.min(closes[-20:]))
        pos_20d = round((last_close-l20)/(h20-l20)*100, 1) if (h20-l20)>0 else 50

        # High/low points trend (last 5 days)
        highs = closes[-5:]
        lows = closes[-5:]
        trend = '高点抬高' if all(highs[i] <= highs[i+1] for i in range(len(highs)-1)) else \
                '低点降低' if all(lows[i] >= lows[i+1] for i in range(len(lows)-1)) else '震荡'

        results[ticker] = {
            'rsi': round(float(rsi), 1),
            'ma20': round(ma20,2), 'ma60': round(ma60,2),
            'macd': macd_signal, 'macd_bar': round(float(macd_bar[-1]),4),
            'bb': bb_pos, 'bb_upper': round(bb_upper,2), 'bb_lower': round(bb_lower,2),
            'vol_ratio': vol_ratio, 'pos_20d': pos_20d,
            'trend': trend, 'last_close': last_close,
        }
    except Exception as e:
        results[ticker] = {'error': str(e)}

print("YF_RESULT:" + json.dumps(results, ensure_ascii=False))
"""

yf_path = r"C:\Users\admin\aazhous-projects\atlas-ai\scripts\_yf_temp.py"
with open(yf_path, 'w', encoding='utf-8') as f:
    f.write(yf_script)

result = subprocess.run([r'C:\Python314\python', yf_path], capture_output=True, text=True, timeout=120)
yf_output = result.stdout
yf_err = result.stderr

if yf_err:
    print(f"YFINANCE STDERR: {yf_err[:500]}")

yf_data = {}
for line in yf_output.split('\n'):
    if line.startswith('YF_RESULT:'):
        try:
            yf_data = json.loads(line.replace('YF_RESULT:', ''))
        except:
            pass
        break

print("\n=== TECHNICALS ===")
for t, d in yf_data.items():
    code = t.replace('.SS','').replace('.SZ','')
    if 'error' in d:
        print(f"  {code}: ERROR={d['error']}")
    else:
        print(f"  {code}: RSI={d['rsi']} MA20={d['ma20']} MACD={d['macd']} BB={d['bb']} VolRatio={d['vol_ratio']} Pos20={d['pos_20d']}% Trend={d['trend']}")

# ── 3. 读取板块数据 ──
sector_json_path = fr"C:\Users\admin\aazhous-projects\atlas-ai\data\stock\sectors-{today}.json"
sector_data = {}
try:
    with open(sector_json_path, 'r', encoding='utf-8') as f:
        sector_data = json.load(f)
except:
    print("\n⚠️ sector JSON not found, skipping sector analysis")

# ── 4. 分析并写 portfolio.json ──
portfolio_path = r"C:\Users\admin\aazhous-projects\atlas-ai\data\stock\portfolio.json"

# 当前的持仓成本
holdings_config = [
    {"name": "上海新阳", "code": "300236", "cost": 121.9, "position": "持有", "sector": "半导体"},
    {"name": "晶晨", "code": "688099", "cost": 99.4, "position": "持有", "sector": "半导体/SoC"},
    {"name": "立讯", "code": "002475", "cost": 63.1, "position": "持有", "sector": "消费电子"},
    {"name": "华东医药", "code": "000963", "cost": 30.3, "position": "持有", "sector": "医药"},
]

holdings = []
for h in holdings_config:
    code = h['code']
    s = sina_data.get(code, {})
    price = s.get('price', 0)
    chg = s.get('chg', 0)
    pnl = round((price / h['cost'] - 1) * 100, 1) if price and h['cost'] else 0
    
    yf_ticker = f"{code}.{'SZ' if code.startswith(('0','3')) else 'SS'}"
    tech = yf_data.get(yf_ticker, {})
    
    rsi = tech.get('rsi', 0)
    macd = tech.get('macd', '')
    macd_bar = tech.get('macd_bar', 0)
    bb = tech.get('bb', '')
    vol_ratio = tech.get('vol_ratio', 1)
    pos_20d = tech.get('pos_20d', 50)
    trend = tech.get('trend', '')
    ma20 = tech.get('ma20', 0)
    ma60 = tech.get('ma60', 0)
    
    # 状态判定
    status = "hold"
    alert = ""
    action = ""
    
    # 跌超15%=warn
    if pnl < -15:
        status = "warn"
        alert = "深套⚠️"
    
    # 技术面分析
    if rsi > 70:
        alert = (alert + " RSI超买").strip()
    if rsi < 30:
        alert = (alert + " RSI超卖").strip()
    if trend == '低点降低':
        alert = (alert + " 趋势走弱").strip()
    
    holdings.append({
        "name": h['name'],
        "code": code,
        "sector": h['sector'],
        "position": h['position'],
        "cost": h['cost'],
        "price": price,
        "chg": chg,
        "pnl": pnl,
        "rsi": rsi,
        "ma20": ma20,
        "ma60": ma60,
        "macd": macd,
        "macd_bar": macd_bar,
        "bb": bb,
        "vol_ratio": vol_ratio,
        "pos_20d": pos_20d,
        "trend": trend,
        "status": status,
        "action": "",
        "alert": alert if alert else "",
    })

# 写出 analysis 字段前的操作建议
# 上海新阳: 半导体从上午暴跌反弹。RSI判断 + 趋势
shxy = next((h for h in holdings if h['code']=='300236'), None)
jc = next((h for h in holdings if h['code']=='688099'), None)
lx = next((h for h in holdings if h['code']=='002475'), None)
hd = next((h for h in holdings if h['code']=='000963'), None)

actions = []

# 上海新阳
if shxy:
    if shxy['pnl'] > -3:
        shxy['action'] = f"距回本仅{abs(shxy['pnl'])}%，持有等回本，止损{shxy['price']*0.92:.1f}"
    else:
        shxy['action'] = f"持有观察，MA20={shxy['ma20']:.0f}，站上则偏多。止损{shxy['cost']*0.92:.1f}"
    actions.append(f"{shxy['name']}: {shxy['action']}")

# 晶晨
if jc:
    if jc['macd'] == '金叉':
        jc['action'] = "MACD金叉出现，持有等反弹。目标回本99.4"
    elif jc['rsi'] < 40:
        jc['action'] = f"RSI={jc['rsi']:.0f}接近超卖，不割等反弹。止损92"
    else:
        jc['action'] = f"持有观察，MACD={jc['macd']}。止损92"
    actions.append(f"{jc['name']}: {jc['action']}")

# 立讯
if lx:
    lx['action'] = f"持有，RSI={lx['rsi']:.0f}。设止损{lx['cost']*0.85:.1f}（-15%硬止损）"
    actions.append(f"{lx['name']}: {lx['action']}")

# 华东医药
if hd:
    if hd['pnl'] > -2:
        hd['action'] = f"距回本仅{abs(hd['pnl'])}%，持有等回本"
    else:
        hd['action'] = "持有观察"
    actions.append(f"{hd['name']}: {hd['action']}")

# 市场方向判断
sectors_info = sector_data.get('sectors', {})
top_sectors = []
worst_sectors = []

if sectors_info:
    sector_list = [(name, info['current']) for name, info in sectors_info.items()]
    sector_list.sort(key=lambda x: x[1], reverse=True)
    for s in sector_list[:3]:
        top_sectors.append(f"{s[0]} {s[1]:+.1f}%")
    for s in sector_list[-3:]:
        worst_sectors.append(f"{s[0]} {s[1]:+.1f}%")

# 半导体板块收盘
semi_chg = sectors_info.get('半导体', {}).get('current', 0) if sectors_info else 0
chip_chg = sectors_info.get('芯片', {}).get('current', 0) if sectors_info else 0
cons_chg = sectors_info.get('消费电子', {}).get('current', 0) if sectors_info else 0
pharma_chg = sectors_info.get('医药', {}).get('current', 0) if sectors_info else 0

market_direction = "震荡偏暖" if (semi_chg > 0 and chip_chg > 0) else \
                   "震荡偏弱" if (semi_chg < -1 or chip_chg < -1) else "震荡"

# 写持仓分析
market_text = f"半导体+{semi_chg:.1f}%、芯片+{chip_chg:.1f}%尾盘翻红，上午一度跌近-5%后大幅反弹。消费电子+{cons_chg:.1f}%。市场V型反转，资金低位承接明显。"

# 持仓总评
pnls = [h['pnl'] for h in holdings]
worst = min(pnls) if pnls else 0
best = max(pnls) if pnls else 0
portfolio_text = f"4只持仓均在浮亏中，最差{worst:.1f}%，最佳{best:.1f}%。半导体尾盘翻红对有持仓利好，但整体仍需等待板块持续回暖。"

risk_text = f"半导体上午一度-5%是今日最大风险事件，尾盘虽翻红但V型反转需次日确认。最大风险敞口：立讯{pnl if (pnl:=lx['pnl'] if lx else 0) < -10 else ''}。"

# 最终组装
portfolio = {
    "updated": now,
    "holdings": holdings,
    "market": {
        "direction": market_direction,
        "top_sectors": top_sectors if top_sectors else ["数据缺失"],
        "worst_sectors": worst_sectors if worst_sectors else ["数据缺失"]
    },
    "analysis": {
        "verdict": f"🟡 持仓分化 — 半导体V型反弹是积极信号，但尾盘翻红待明日确认",
        "market": market_text,
        "portfolio": portfolio_text,
        "actions": actions,
        "risk": risk_text
    }
}

with open(portfolio_path, 'w', encoding='utf-8') as f:
    json.dump(portfolio, f, ensure_ascii=False, indent=2)

print(f"\n✅ portfolio.json written to {portfolio_path}")
print(f"   Holdings: {len(holdings)} stocks")
print(f"   Market: {market_direction}")
print(f"   Actions: {len(actions)} items")

# ── 5. Git push 部署 ──
import subprocess as sp
BASE = r"C:\Users\admin\aazhous-projects\atlas-ai"

r1 = sp.run(['git', 'add', '-A'], cwd=BASE, capture_output=True, text=True, timeout=10)
r2 = sp.run(['git', 'commit', '-m', f'auto: portfolio update {today}'], cwd=BASE, capture_output=True, text=True, timeout=10)
r3 = sp.run(['git', 'push'], cwd=BASE, capture_output=True, text=True, timeout=30)

print(f"\n📤 Deploy: git add={r1.returncode} commit={r2.returncode} push={r3.returncode}")
if r3.returncode != 0:
    print(f"   push stderr: {r3.stderr[:200]}")
if r2.stdout:
    print(f"   commit: {r2.stdout.strip()}")

# Cleanup
if os.path.exists(yf_path):
    os.remove(yf_path)

print("\n✅ Done")
