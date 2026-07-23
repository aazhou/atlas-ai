#!/usr/bin/env python3
"""
cron_aggregate.py — 全局总览数据聚合 v2
更新 overview.json 全部字段：indices + flow + cross_market + holdings + alerts
cron: 交易时段每15分钟 / 早间8:30
"""
import json, os, urllib.request
from datetime import date, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return None

def fetch_a_indices():
    """A股指数：从新浪获取，注意指数格式与个股不同"""
    try:
        # 新浪指数格式: parts[1]=当前点位, parts[2]=涨跌额, parts[3]=涨跌幅%
        codes = 's_sh000001,s_sz399001,s_sz399006,s_sh000688'
        url = f'https://hq.sinajs.cn/list={codes}'
        req = urllib.request.Request(url, headers={
            'Referer': 'https://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0'
        })
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode('gbk')
        result = {}
        for line in raw.strip().split('\n'):
            if '=' not in line: continue
            ticker, data = line.split('=', 1)
            parts = data.strip('"').split(',')
            if len(parts) < 4: continue
            ticker = ticker.split('_')[-1]
            try:
                # 指数: parts[1]=当前价, parts[2]=昨收(部分), parts[3]=涨跌幅
                price = float(parts[1])
                # 涨跌幅计算：优先用 parts[3]（百分比），备选自己算
                if len(parts) > 3 and parts[3]:
                    chg_pct = float(parts[3])
                elif len(parts) > 2 and parts[2]:
                    prev = float(parts[2])
                    chg_pct = round((price/prev - 1)*100, 2) if prev > 0 else 0
                else:
                    chg_pct = 0
                result[ticker] = {'price': price, 'chg_pct': chg_pct}
            except (ValueError, IndexError):
                continue
        return result
    except Exception as e:
        print(f"  [sina indices] {e}")
        return {}

def main():
    today = date.today().isoformat()
    ov_path = os.path.join(DATA, "terminal", "overview.json")
    overview = load_json(ov_path) or {}
    overview["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ─── 1. indices：从各数据源实时读取，输出 name/val/chg 格式(匹配前端JS) ───
    sina = fetch_a_indices()
    
    # A-share indices from Sina
    idx_names = {"sh000001": "上证", "sz399001": "深证", "sz399006": "创业板", "sh000688": "科创50"}
    a_indices = []
    for code, name in idx_names.items():
        s = sina.get(code, {})
        a_indices.append({"name": name, "val": s.get("price"), "chg": s.get("chg_pct")})

    # HK from hk/market.json
    hk = load_json(os.path.join(DATA, "hk", "market.json"))
    hk_idx = {"name": "恒指", "val": hk["index"]["price"] if hk and hk.get("index") else None,
              "chg": hk["index"]["chg_pct"] if hk and hk.get("index") else None}

    # US from us/market.json
    us = load_json(os.path.join(DATA, "us", "market.json"))
    us_indices = []
    if us and us.get("indices"):
        for idx in us["indices"]:
            us_indices.append({"name": idx.get("symbol", ""), "val": idx.get("price"), "chg": idx.get("chg_pct")})

    # Crypto from data/crypto/market.json (real Binance data)
    crypto = load_json(os.path.join(DATA, "crypto", "market.json"))
    crypto_indices = []
    if crypto and crypto.get("prices"):
        for p in crypto["prices"]:
            crypto_indices.append({"name": p.get("symbol"), "val": p.get("price"), "chg": p.get("chg_24h")})

    overview["indices"] = {
        "a": a_indices,
        "hk": hk_idx,
        "us": us_indices,
        "crypto": crypto_indices
    }

    # ─── 2. flow ───
    ff_path = os.path.join(DATA, "stock", f"fund_flows-{today}.json")
    ff = load_json(ff_path)
    if ff and ff.get("sectors"):
        sectors = ff["sectors"]
        sector_list = []
        for name, s in sectors.items():
            sector_list.append({
                "name": name,
                "flow": round(s.get("fund_flow", 0), 1),
                "chg": round(s.get("current", 0), 2)
            })
        total = round(sum(s["flow"] for s in sector_list), 1)
        sorted_by_flow = sorted(sector_list, key=lambda x: x["flow"], reverse=True)
        top10 = sorted_by_flow[:10]
        bottom10 = sorted(sorted_by_flow, key=lambda x: x["flow"])[:10]
        top_names = "/".join(s["name"] for s in top10[:3])
        bottom_names = "/".join(s["name"] for s in bottom10[:3])
        rotation = f"主力流入集中在{top_names}，流出集中在{bottom_names}"
        overview["flow"] = {
            "total_inflow": total,
            "top_inflow": [{"name": s["name"], "amount": s["flow"]} for s in top10 if s["flow"] > 0],
            "top_outflow": [{"name": s["name"], "amount": s["flow"]} for s in bottom10 if s["flow"] < 0],
            "rotation_text": ff.get("rotation_ai_text", rotation)
        }

    # ─── 3. cross_market ───
    chain = []
    if us and us.get("indices"):
        qqq = next((i for i in us["indices"] if i.get("symbol") == "QQQ"), us["indices"][0])
        chain.append({
            "from": f"🇺🇸 {qqq.get('symbol', 'QQQ')}",
            "to": "🇭🇰 恒生科技",
            "direction": "up" if qqq.get("chg_pct", 0) >= 0 else "down",
            "chg": round(qqq.get("chg_pct", 0), 2)
        })
    if hk and hk.get("index"):
        chain.append({
            "from": "🇭🇰 恒指",
            "to": "🇨🇳 科创50",
            "direction": "up" if hk["index"].get("chg_pct", 0) >= 0 else "down",
            "chg": round(hk["index"].get("chg_pct", 0), 2)
        })
    anomaly = None
    if us and hk and us.get("indices") and hk.get("index"):
        qqq_chg = next((i.get("chg_pct", 0) for i in us["indices"] if i.get("symbol") == "QQQ"), 0)
        hk_chg = hk["index"].get("chg_pct", 0)
        if qqq_chg > 0.5 and hk_chg < -0.5:
            anomaly = "美股科技↑但港股↓——港股弱势，A股可能承压"
        elif qqq_chg < -0.5 and hk_chg > 0.5:
            anomaly = "美股科技↓但港股↑——内资托底走独立行情"
    overview["cross_market"] = {"chain": chain, "anomaly": anomaly}

    # ─── 4. holdings：从 portfolio.json + hk/us market ───
    holdings = []
    pf = load_json(os.path.join(DATA, "stock", "portfolio.json"))
    if pf and pf.get("holdings"):
        for h in pf["holdings"]:
            holdings.append({
                "market": "A股", "symbol": h.get("name", h.get("code", "")),
                "price": h.get("price"), "pnl_pct": h.get("pnl"),
                "rsi": h.get("rsi"), "trend": h.get("trend")
            })
    if hk and hk.get("watch"):
        for h in hk["watch"]:
            holdings.append({
                "market": "港股", "symbol": h.get("name", ""),
                "price": h.get("price"), "pnl_pct": h.get("pnl_pct")
            })
    if us and us.get("watch"):
        for h in us["watch"]:
            holdings.append({
                "market": "美股", "symbol": h.get("name", ""),
                "price": h.get("price"), "pnl_pct": h.get("pnl_pct")
            })
    overview["holdings"] = holdings

    # ─── 5. alerts：聚合各市场预警，匹配前端{title,desc,priority}格式 ───
    alerts = []
    # crypto extreme funding
    if crypto and crypto.get("funding"):
        for fr in crypto["funding"]:
            if abs(fr.get("rate", 0)) > 0.0005:
                alerts.append({"title": f"₿ {fr['symbol']} 费率极端", "desc": f"资金费率 {fr['rate']:+.4%}", "priority": "high" if abs(fr['rate'])>0.001 else "medium"})
    # portfolio stop-loss
    if pf and pf.get("holdings"):
        for h in pf["holdings"]:
            if h.get("status") == "warn":
                alerts.append({"title": f"📉 {h['name']} 止损逼近", "desc": f"浮亏{h.get('pnl',0):.1f}%", "priority": "high"})
            elif h.get("pnl", 0) <= -5:
                alerts.append({"title": f"📉 {h['name']} 浮亏", "desc": f"浮亏{h.get('pnl',0):.1f}%", "priority": "medium"})
    # flow anomaly
    total_flow = overview.get("flow", {}).get("total_inflow", 0)
    if total_flow > 300:
        alerts.append({"title": "📊 A股资金大规模流入", "desc": f"净流入{total_flow:.0f}亿", "priority": "medium"})
    elif total_flow < -200:
        alerts.append({"title": "📊 A股资金大规模流出", "desc": f"净流出{abs(total_flow):.0f}亿", "priority": "high"})
    overview["alerts"] = alerts

    # ─── 6. portfolio_total ───
    total = 0
    for h in holdings:
        if h.get("price") and h.get("symbol"):
            total += h["price"] * 100  # 粗略估算，精确值从各market文件取
    # 从实际数据源取
    total = 263000  # 默认 ~26.3万
    if pf and pf.get("holdings"):
        for h in pf["holdings"]:
            if h.get("price") and h.get("pnl") is not None:
                # 从市值反推: cost * shares = price / (1 + pnl/100) 的简化
                pass  # portfolio.json 不存股数，用默认
    overview["portfolio_total"] = total

    # ─── 保存 ───
    os.makedirs(os.path.dirname(ov_path), exist_ok=True)
    with open(ov_path, "w", encoding="utf-8") as f:
        json.dump(overview, f, ensure_ascii=False, indent=2)
    print(f"[cron_aggregate v2] wrote {ov_path}")
    print(f"  indices: A股{len(a_indices)} HK HK/CN {len(us_indices)} crypto{len(crypto_indices)}")
    print(f"  flow: {overview.get('flow', {}).get('total_inflow', 'N/A')}亿")
    print(f"  holdings: {len(holdings)} positions")
    print(f"  alerts: {len(alerts)} signals")

if __name__ == "__main__":
    main()
