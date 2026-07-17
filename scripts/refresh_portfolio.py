"""盘中持仓价格刷新 — 每5分钟更新 portfolio.json"""
import urllib.request, json, os, sys
from datetime import datetime

# 持仓代码映射：name → sina_code
HOLDINGS = {
    "上海新阳": "sz300236",
    "晶晨": "sh688099",
    "华东医药": "sz000963",
    "双环传动": "sz002472",
    "立讯精密": "sz002475",
}

PORTFOLIO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                "data", "stock", "portfolio.json")

def fetch_prices():
    codes = list(HOLDINGS.values())
    url = f"https://hq.sinajs.cn/list={','.join(codes)}"
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
    resp = urllib.request.urlopen(req, timeout=10)
    raw = resp.read().decode("gbk")
    
    prices = {}
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("=", 1)
        if len(parts) < 2:
            continue
        code_part = parts[0].split("_")[-1] if "_" in parts[0] else parts[0].replace("var hq_str_", "")
        fields = parts[1].strip('"').split(",")
        if len(fields) < 5:
            continue
        prices[code_part] = {
            "name": fields[0],
            "price": float(fields[3]) if fields[3] else 0,
            "prev_close": float(fields[2]) if fields[2] else 0,
        }
    return prices

def main():
    # 只在交易日运行
    now = datetime.now()
    if now.weekday() >= 5:
        return  # 周末跳过
    
    try:
        with open(PORTFOLIO_PATH, 'r', encoding='utf-8') as f:
            portfolio = json.load(f)
    except:
        print(f"[{now:%H:%M}] portfolio.json 读取失败", file=sys.stderr)
        sys.exit(1)
    
    prices = fetch_prices()
    
    for h in portfolio.get("holdings", []):
        name = h.get("name", "")
        code = HOLDINGS.get(name)
        if code and code in prices:
            p = prices[code]
            h["price"] = round(p["price"], 2)
            chg = round((p["price"] / p["prev_close"] - 1) * 100, 2) if p["prev_close"] else 0
            h["chg"] = chg
            if h.get("cost"):
                h["pnl"] = round((p["price"] / h["cost"] - 1) * 100, 2)
    
    portfolio["updated"] = now.strftime("%Y-%m-%d %H:%M")
    
    with open(PORTFOLIO_PATH, 'w', encoding='utf-8') as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)
    
    print(f"[{now:%H:%M}] portfolio.json 已刷新")

if __name__ == "__main__":
    main()
