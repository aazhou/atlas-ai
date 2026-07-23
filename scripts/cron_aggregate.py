#!/usr/bin/env python3
"""cron_aggregate.py — 全局总览数据聚合
cron: 每天早上8:30 或 每次cron产出后触发
产出: data/terminal/overview.json (更新 flow + cross_market 字段)
"""
import json, os, sys
from datetime import date, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return None

def main():
    today = date.today().isoformat()

    # Load existing overview
    ov_path = os.path.join(DATA, "terminal", "overview.json")
    overview = load_json(ov_path) or {}
    overview["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ─── 1. 资金流 ───
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
        # Total inflow
        total = round(sum(s["flow"] for s in sector_list), 1)
        # Top/Bottom
        sorted_by_flow = sorted(sector_list, key=lambda x: x["flow"], reverse=True)
        top10 = sorted_by_flow[:10]
        bottom10 = sorted(sorted_by_flow, key=lambda x: x["flow"])[:10]

        # Rotation text
        top_names = "/".join(s["name"] for s in top10[:3])
        bottom_names = "/".join(s["name"] for s in bottom10[:3])
        rotation = f"今日资金趋势：主力流入集中在{top_names}方向，流出集中在{bottom_names}方向。"

        overview["flow"] = {
            "total_inflow": total,
            "top_inflow": [{"name": s["name"], "amount": s["flow"]} for s in top10 if s["flow"] > 0],
            "top_outflow": [{"name": s["name"], "amount": s["flow"]} for s in bottom10 if s["flow"] < 0],
            "rotation_text": ff.get("rotation_ai_text", rotation)
        }

    # ─── 2. 跨市场联动 ───
    chain = []
    # US data
    us_path = os.path.join(DATA, "us", "market.json")
    us = load_json(us_path)
    if us and us.get("indices"):
        qqq = next((i for i in us["indices"] if i.get("symbol") == "QQQ"), us["indices"][0])
        chain.append({
            "from": "🇺🇸 " + qqq.get("symbol", "QQQ"),
            "to": "🇭🇰 恒生科技",
            "direction": "up" if qqq.get("chg_pct", 0) >= 0 else "down",
            "chg": round(qqq.get("chg_pct", 0), 2)
        })
    # HK data
    hk_path = os.path.join(DATA, "hk", "market.json")
    hk = load_json(hk_path)
    if hk and hk.get("index"):
        chain.append({
            "from": "🇭🇰 恒指",
            "to": "🇨🇳 科创50",
            "direction": "up" if hk["index"].get("chg_pct", 0) >= 0 else "down",
            "chg": round(hk["index"].get("chg_pct", 0), 2)
        })

    # Anomaly detection
    anomaly = None
    if us and hk and us.get("indices") and hk.get("index"):
        qqq_chg = next((i.get("chg_pct", 0) for i in us["indices"] if i.get("symbol") == "QQQ"), 0)
        hk_chg = hk["index"].get("chg_pct", 0)
        if qqq_chg > 0.5 and hk_chg < -0.5:
            anomaly = "美股科技上涨但港股下跌——港股弱势，A股可能也承压"
        elif qqq_chg < -0.5 and hk_chg > 0.5:
            anomaly = "美股科技下跌但港股抗跌——内资托底，港股独立行情"

    overview["cross_market"] = {
        "chain": chain,
        "anomaly": anomaly
    }

    # ─── 保存 ───
    os.makedirs(os.path.dirname(ov_path), exist_ok=True)
    with open(ov_path, "w", encoding="utf-8") as f:
        json.dump(overview, f, ensure_ascii=False, indent=2)

    print(f"[cron_aggregate] wrote {ov_path}")
    print(f"  flow: {overview.get('flow', {}).get('total_inflow', 'N/A')}亿")
    print(f"  cross_market: {len(chain)} links, anomaly: {anomaly}")

if __name__ == "__main__":
    main()
