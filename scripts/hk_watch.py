"""港股盯盘 v2 — 实时价(Tencent) + 基础信号 + yfinance K线(可选)"""
import urllib.request, sys, time
from datetime import date, datetime

today = date.today()
now = datetime.now()
if today.weekday() >= 5: sys.exit(0)
t = (now.hour, now.minute)
if not ((9,30) <= t < (12,0) or (13,0) <= t < (16,1)): sys.exit(0)

# ─── 腾讯实时价 ───
req = urllib.request.Request("http://qt.gtimg.cn/q=hk00700,hk09988,hk03032",
    headers={"User-Agent": "Mozilla/5.0"})
resp = urllib.request.urlopen(req, timeout=10)
raw = resp.read().decode("gbk", errors="replace")

holdings = {}
for line in raw.strip().split("\n"):
    if "~" not in line: continue
    parts = line.split('"')
    if len(parts) < 2: continue
    data = parts[1].split("~")
    if len(data) < 33: continue
    code = data[2]
    holdings[code] = {
        "name": data[1], "price": float(data[3]) if data[3] else 0,
        "chg_pct": float(data[32]) if data[32] else 0,
    }

if not holdings: sys.exit(0)

# ─── yfinance (可选, 429容错) ───
import pandas as pd

def fetch_yf(ticker, retries=2):
    for attempt in range(retries):
        try:
            df = pd.read_csv(
                f"https://query1.finance.yahoo.com/v7/finance/download/{ticker}?"
                f"period1={int((pd.Timestamp.now() - pd.Timedelta(days=80)).timestamp())}&"
                f"period2={int(pd.Timestamp.now().timestamp())}&interval=1d&events=history",
                index_col=0, parse_dates=True
            )
            return df if (not df.empty and len(df) >= 20) else None
        except Exception:
            if attempt < retries - 1: time.sleep(2)
    return None

hsi = fetch_yf("%5EHSI")
hsi_str = ""
if hsi is not None and len(hsi) >= 2:
    pct = round(float((hsi["Close"].iloc[-1]/hsi["Close"].iloc[-2]-1)*100), 2)
    hsi_str = f"**恒指** {pct:+.2f}%"
else:
    hsi_str = "**恒指** — (yfinance限流)"

tickers = {"00700": "0700.HK", "09988": "9988.HK", "03032": "3032.HK"}
tech_data = {}

for code, yf_ticker in tickers.items():
    if code not in holdings: continue
    h = holdings[code]
    price = h["price"]
    chg = h["chg_pct"]
    sigs = []
    tech = {"ma20": "—", "pos_20d": "—", "vol_ratio": "—"}

    df = fetch_yf(yf_ticker)
    if df is not None:
        close = df["Close"]; high = df["High"]; low = df["Low"]; volume = df["Volume"]
        ma20 = close.rolling(20).mean().iloc[-1]
        tech["ma20"] = round(float(ma20), 2)
        h20 = high.iloc[-20:].max(); l20 = low.iloc[-20:].min()
        tech["pos_20d"] = round((price-l20)/(h20-l20)*100, 1) if h20 != l20 else 50
        vm5 = volume.rolling(5).mean().iloc[-1]
        tech["vol_ratio"] = round(float(volume.iloc[-1]/vm5), 1) if vm5 > 0 else 1.0

        if len(close) >= 3:
            c2, c3 = close.iloc[-2], close.iloc[-1]
            o2, o3 = df["Open"].iloc[-2], df["Open"].iloc[-1]
            h3v, l3v = high.iloc[-1], low.iloc[-1]
            v2, v3 = volume.iloc[-2], volume.iloc[-1]
            body = abs(c3-o3)
            upper = h3v - max(c3, o3); lwer = min(c3, o3) - l3v
            ma20_prev = close.rolling(20).mean().iloc[-2]

            if price > ma20 and tech["pos_20d"] > 70:
                if upper > body*2 and lwer < body*0.5: sigs.append("🔴 射击之星")
                if c2 > o2 and o3 > high.iloc[-2] and c3 < (o2+c2)/2: sigs.append("🔴 乌云盖顶")
            if price < ma20 and tech["pos_20d"] < 40:
                if lwer > body*2 and upper < body*0.5: sigs.append("🟢 锤子线")
                if c3 > o3 and c2 < o2 and c3 > o2 and o3 < c2: sigs.append("🟢 吞没形态")
            if c3 > c2 and v3 < v2*0.8: sigs.append("⚠️ 价涨量缩")
            if c3 < c2 and v3 > v2*1.5: sigs.append("🚨 价跌量增")
            if price > ma20 and close.iloc[-2] <= ma20_prev:
                sigs.append("🟢 突破MA20" + ("放量" if tech["vol_ratio"] > 1.3 else ""))
            if price < ma20 and close.iloc[-2] >= ma20_prev:
                sigs.append("🔴 跌破MA20")

    # 基础涨跌信号 (不依赖yfinance)
    if chg >= 3: sigs.append("🚀 +{:.0f}%".format(chg))
    elif chg <= -3: sigs.append("🔻 {:.0f}%".format(chg))

    holdings[code]["signals"] = sigs
    tech_data[code] = tech

# ─── 判断输出 ───
has_signal = any(h["signals"] for h in holdings.values())
if not has_signal:
    sys.exit(0)

lines = [f"## 🇭🇰 港股盯盘 {now.strftime('%H:%M')}", hsi_str, ""]

for code in ["00700", "09988", "03032"]:
    if code not in holdings: continue
    h = holdings[code]
    sigs = h["signals"]
    sig_str = " | ".join(sigs) if sigs else "—"
    t = tech_data.get(code, {})
    lines.append(f"**{h['name']} {h['price']:.2f}({h['chg_pct']:+.2f}%)：** {sig_str}")
    if sigs:
        lines.append(f"  MA20:{t.get('ma20','—')} 位置:{t.get('pos_20d','—')}% 量比:{t.get('vol_ratio','—')}")

print("\n".join(lines))
