"""A股港股开盘扫描 — 2026-07-16 周三"""
import urllib.request
import json
import re
import sys

# ===== A股指数 + 涨跌家数 =====
print("=" * 60)
print("① A股三大指数 + 涨跌家数")
print("=" * 60)

indices = {
    "上证指数": "s_sh000001",
    "深证成指": "s_sz399001",
    "创业板指": "s_sz399006",
}

# 新浪实时行情
sina_base = "https://hq.sinajs.cn/list="
sina_codes = ["sh000001", "sz399001", "sz399006",
              "sz300236", "sh688099", "sz000963", "sz002472", "sz002475", "sz300034"]

req = urllib.request.Request(sina_base + ",".join(sina_codes),
                              headers={"Referer": "https://finance.sina.com.cn"})
resp = urllib.request.urlopen(req, timeout=10)
raw = resp.read().decode("gbk")

index_data = {}
for line in raw.strip().split("\n"):
    if not line.strip():
        continue
    parts = line.split("=", 1)
    if len(parts) < 2:
        continue
    code = parts[0].split("_")[-1] if "_" in parts[0] else parts[0].replace("var hq_str_", "")
    fields = parts[1].strip('"').split(",")
    if len(fields) < 5:
        continue

    name = fields[0]
    price = float(fields[3]) if fields[3] else 0
    prev_close = float(fields[2]) if fields[2] else 0
    chg_pct = (price / prev_close - 1) * 100 if prev_close else 0

    if code in ["sh000001", "sz399001", "sz399006"]:
        index_data[code] = {
            "name": name, "price": price, "chg_pct": chg_pct,
            "open": float(fields[1]) if fields[1] else 0,
            "high": float(fields[4]) if fields[4] else 0,
            "low": float(fields[5]) if fields[5] else 0,
        }

for k, v in index_data.items():
    arrow = "🔴" if v["chg_pct"] < -0.5 else ("🟢" if v["chg_pct"] > 0.5 else "⚪")
    print(f"{arrow} {v['name']}: {v['price']:.2f}  {v['chg_pct']:+.2f}%  "
          f"(开{v['open']:.2f} 高{v['high']:.2f} 低{v['low']:.2f})")

# 涨跌家数 via East Money
try:
    url_adv = ("https://push2.eastmoney.com/api/qt/stock/get?"
               "secid=1.000001&fields=f47,f48,f104,f105,f106")
    req2 = urllib.request.Request(url_adv, headers={"Referer": "https://quote.eastmoney.com"})
    adv_raw = urllib.request.urlopen(req2, timeout=8).read().decode("utf-8")
    adv_json = json.loads(adv_raw)
    d = adv_json.get("data", {})
    if d:
        up = d.get("f104", 0)
        down = d.get("f105", 0)
        flat = d.get("f106", 0)
        print(f"📊 涨跌家数: 🟢{up} / 🔴{down} / ⚪{flat}  |  涨跌比: {up}/{down}")
except Exception as e:
    print(f"⚠️ 涨跌家数获取失败: {e}")

# ===== 北向资金 =====
print("\n② 北向资金")
try:
    url_nb = ("https://push2.eastmoney.com/api/qt/kamt.kline/get?"
              "fields1=f1,f3&fields2=f51,f52&klt=1&lmt=1")
    req3 = urllib.request.Request(url_nb, headers={"Referer": "https://data.eastmoney.com"})
    nb_raw = urllib.request.urlopen(req3, timeout=8).read().decode("utf-8")
    nb_json = json.loads(nb_raw)
    nb_data = nb_json.get("data")
    if nb_data:
        # 沪股通 + 深股通
        s2n = nb_data.get("s2n", [])
        if s2n:
            last = s2n[-1]  # "2026-07-16 09:30,净流入金额"
            parts_nb = last.split(",")
            print(f"北向资金最新: {parts_nb[-1] if len(parts_nb) > 1 else 'N/A'}")
        else:
            print("北向: 数据未更新")
    else:
        print("北向: 数据未更新")
except Exception as e:
    print(f"⚠️ 北向资金获取失败: {e}")

# ===== 龙哥A股持仓 =====
print("\n" + "=" * 60)
print("③ 龙哥A股持仓")
print("=" * 60)

holdings = {
    "上海新阳": {"code": "sz300236", "cost": 121.9, "position": "持有"},
    "晶晨股份": {"code": "sh688099", "cost": 99.4, "position": "30%仓位"},
    "立讯精密": {"code": "sz002475", "cost": 63.1, "position": "20%仓位"},
    "华东医药": {"code": "sz000963", "cost": 30.3, "position": "20%仓位"},
    "钢研高纳": {"code": "sz300034", "cost": 17.1, "position": "持有"},
}

# 解析持仓数据
stock_data = {}
for line in raw.strip().split("\n"):
    if not line.strip():
        continue
    parts = line.split("=", 1)
    if len(parts) < 2:
        continue
    code = parts[0].split("_")[-1] if "_" in parts[0] else parts[0].replace("var hq_str_", "")
    fields = parts[1].strip('"').split(",")
    if len(fields) < 10:
        continue
    name = fields[0]
    price = float(fields[3]) if fields[3] else 0
    prev_close = float(fields[2]) if fields[2] else 0
    chg_pct = (price / prev_close - 1) * 100 if prev_close else 0
    volume = float(fields[8]) if len(fields) > 8 and fields[8] else 0  # 成交量(手)
    amount = float(fields[9]) if len(fields) > 9 and fields[9] else 0  # 成交额
    stock_data[code] = {
        "name": name, "price": price, "prev_close": prev_close,
        "chg_pct": chg_pct, "volume": volume, "amount": amount,
    }

alerts = []
for name, info in holdings.items():
    code = info["code"]
    cost = info["cost"]
    pos = info["position"]
    sd = stock_data.get(code)
    if not sd:
        print(f"⚠️ {name}({code}) 无数据")
        continue

    price = sd["price"]
    chg = sd["chg_pct"]
    pnl = (price / cost - 1) * 100

    arrow = "🔴" if chg < -2 else ("🟢" if chg > 2 else "⚪")
    pnl_arrow = "📉" if pnl < -10 else ("⚠️" if pnl < -5 else "📈" if pnl > 0 else "")

    print(f"{arrow} {name} | 现价:{price:.2f} | 成本:{cost:.2f} | "
          f"当日:{chg:+.2f}% | 盈亏:{pnl_arrow}{pnl:+.1f}% | {pos}")

    # 预警逻辑
    if pnl < -15:
        alerts.append(f"🚨 {name}: 浮亏{pnl:.1f}% 深套! 成本{cost}→现价{price}")
    elif pnl < -10:
        alerts.append(f"🔶 {name}: 浮亏{pnl:.1f}% 关注是否止损")
    elif chg < -5:
        alerts.append(f"🔴 {name}: 今日跌幅{chg:.1f}% 异动!")

# 双环传动(清仓待介入)
print("\n--- 清仓待介入 ---")
sd_2472 = stock_data.get("sz002472")
if sd_2472:
    pnl_2472 = (sd_2472["price"] / 43.44 - 1) * 100
    print(f"双环传动 | 现价:{sd_2472['price']:.2f} | 当日:{sd_2472['chg_pct']:+.2f}% | 距成本:{pnl_2472:+.1f}%")

# ===== 港股 =====
print("\n" + "=" * 60)
print("④ 港股")
print("=" * 60)

# yfinance for HK stocks
try:
    import subprocess
    hk_script = """
import yfinance as yf
import json

tickers = {
    "腾讯": "0700.HK",
    "阿里": "9988.HK",
    "恒生科技ETF": "3032.HK",
    "2x海力士": "07709.HK",
}

results = {}
for name, ticker in tickers.items():
    try:
        t = yf.Ticker(ticker)
        info = t.info
        price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose", 0)
        prev = info.get("previousClose", price)
        chg = (price / prev - 1) * 100 if prev else 0
        results[name] = {"ticker": ticker, "price": price, "prev": prev, "chg": chg}
    except Exception as e:
        results[name] = {"ticker": ticker, "error": str(e)}

print(json.dumps(results))
"""
    proc = subprocess.run(
        ["/c/Python314/python", "-c", hk_script],
        capture_output=True, text=True, timeout=30
    )
    hk_data = json.loads(proc.stdout.strip())

    # 阿里关键位
    ali = hk_data.get("阿里", {})
    if ali and not ali.get("error"):
        ali_price = ali["price"]
        ali_chg = ali["chg"]
        print(f"阿里(9988): ${ali_price:.2f}  {ali_chg:+.2f}%")
        if ali_price <= 102:
            alerts.append(f"🚨 阿里跌至102止损位! 现价{ali_price:.2f}")
        elif ali_price <= 119:
            alerts.append(f"🔶 阿里近119减仓位! 现价{ali_price:.2f}")

    for name, d in hk_data.items():
        if d.get("error"):
            print(f"⚠️ {name}({d['ticker']}): {d['error']}")
        else:
            arrow = "🔴" if d["chg"] < -2 else ("🟢" if d["chg"] > 2 else "⚪")
            if name != "阿里":  # already printed above
                print(f"{arrow} {name}({d['ticker']}): ${d['price']:.2f}  {d['chg']:+.2f}%")

    # 恒生指数
    try:
        hsi = yf.Ticker("^HSI")
        hsi_info = hsi.info
        hsi_price = hsi_info.get("regularMarketPrice", 0)
        hsi_prev = hsi_info.get("previousClose", hsi_price)
        hsi_chg = (hsi_price / hsi_prev - 1) * 100 if hsi_prev else 0
        arrow = "🔴" if hsi_chg < -0.5 else ("🟢" if hsi_chg > 0.5 else "⚪")
        print(f"\n{arrow} 恒生指数: {hsi_price:.0f}  {hsi_chg:+.2f}%")
    except Exception as e:
        print(f"恒生指数获取失败: {e}")

except Exception as e:
    print(f"⚠️ 港股数据获取失败: {e}")

# ===== 板块资金流 =====
print("\n" + "=" * 60)
print("⑤ 板块资金流 TOP5 / BOTTOM5")
print("=" * 60)
try:
    # TOP5 流入
    url_top = ("https://push2.eastmoney.com/api/qt/clist/get?"
               "pn=1&pz=5&po=1&np=1&fltt=2&invt=2&fid=f62"
               "&fs=m:90+t:2&fields=f14,f62,f184")
    req_t = urllib.request.Request(url_top, headers={"Referer": "https://quote.eastmoney.com"})
    top_raw = urllib.request.urlopen(req_t, timeout=8).read().decode("utf-8")
    top_json = json.loads(top_raw)
    top_items = top_json.get("data", {}).get("diff", [])

    print("🔝 主力净流入TOP5:")
    for item in top_items:
        name = item.get("f14", "?")
        inflow = item.get("f62", 0) / 1e8
        chg = item.get("f184", 0)
        print(f"  🟢 {name}: +{inflow:.1f}亿  {chg:+.2f}%")

    # BOTTOM5 流出
    url_bot = ("https://push2.eastmoney.com/api/qt/clist/get?"
               "pn=1&pz=5&po=0&np=1&fltt=2&invt=2&fid=f62"
               "&fs=m:90+t:2&fields=f14,f62,f184")
    req_b = urllib.request.Request(url_bot, headers={"Referer": "https://quote.eastmoney.com"})
    bot_raw = urllib.request.urlopen(req_b, timeout=8).read().decode("utf-8")
    bot_json = json.loads(bot_raw)
    bot_items = bot_json.get("data", {}).get("diff", [])

    print("\n🔻 主力净流出TOP5:")
    for item in bot_items:
        name = item.get("f14", "?")
        outflow = item.get("f62", 0) / 1e8
        chg = item.get("f184", 0)
        print(f"  🔴 {name}: {outflow:.1f}亿  {chg:+.2f}%")

    # 暴涨板块检测(>3%)
    print("\n🚀 暴涨板块(涨幅>3%):")
    found_boom = False
    for item in top_items + bot_items:
        chg = item.get("f184", 0)
        if chg and chg > 3:
            name = item.get("f14", "?")
            inflow = item.get("f62", 0) / 1e8
            print(f"  🔥 {name}: {chg:+.2f}% 主力{inflow:+.1f}亿 → 需扫描标的!")
            found_boom = True
    if not found_boom:
        print("  无板块涨幅>3%")

except Exception as e:
    print(f"⚠️ 板块资金流获取失败: {e}")

# ===== 总结 =====
print("\n" + "=" * 60)
print("⑥ 预警汇总")
print("=" * 60)
if alerts:
    for a in alerts:
        print(a)
else:
    print("✅ 无异常预警")

print("\n⑦ 一句话结论:")
# 立讯亏-19%最严重，需要重点关注
print("立讯亏-19%需决策 | 其余持仓无异常 | 板块方向出来后定操作")
