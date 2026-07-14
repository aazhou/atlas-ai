import requests, re, json, sys, os
from datetime import datetime

today = datetime.now().strftime('%Y-%m-%d')

# Step 0: 新浪实时行情
codes = 'sz300236,sh688099,sz002475,sz000963,sz300034'
r = requests.get(f'https://hq.sinajs.cn/list={codes}', 
                 headers={'Referer':'https://finance.sina.com.cn/'}, timeout=10)
r.encoding = 'gbk'

results = {}
for line in r.text.strip().split('\n'):
    if not line.strip():
        continue
    parts = line.split('=')
    if len(parts) < 2:
        continue
    name_raw = parts[0].strip()
    code_match = re.search(r'hq_str_(.+)', name_raw)
    if not code_match:
        continue
    code = code_match.group(1)
    data = parts[1].strip('"').split(',')
    if len(data) < 32:
        continue
    
    name = data[0]
    cur = float(data[3])
    yest = float(data[2])
    high = float(data[4])
    low = float(data[5])
    vol = float(data[8])
    chg_pct = (cur / yest - 1) * 100
    
    results[code] = {
        'name': name, 'cur': round(cur, 2), 'yest': round(yest, 2),
        'high': round(high, 2), 'low': round(low, 2),
        'chg_pct': round(chg_pct, 2)
    }

print("=== 实时行情 ===")
print(json.dumps(results, ensure_ascii=False, indent=2))

# Step 1: 读动量数据
momentum_path = f'C:/Users/admin/aazhous-projects/atlas-ai/data/stock/sector_momentum-{today}.json'
momentum = None
if os.path.exists(momentum_path):
    with open(momentum_path, 'r', encoding='utf-8') as f:
        momentum = json.load(f)
    print("\n=== 板块动量 ===")
    print(json.dumps(momentum, ensure_ascii=False, indent=2, default=str))
else:
    print(f"\n=== 板块动量文件不存在: {momentum_path} ===")

# Step 2: 读板块原始数据
sectors_path = f'C:/Users/admin/aazhous-projects/atlas-ai/data/stock/sectors-{today}.json'
sectors = None
if os.path.exists(sectors_path):
    with open(sectors_path, 'r', encoding='utf-8') as f:
        sectors = json.load(f)
    print("\n=== 板块数据 (前20条) ===")
    if isinstance(sectors, list):
        for s in sectors[:20]:
            print(f"  {s.get('name','?')}: 涨跌{s.get('chg_pct',0)}% 主力净流入{s.get('net_flow',0)}亿")
    elif isinstance(sectors, dict):
        print(json.dumps(sectors, ensure_ascii=False, indent=2)[:2000])
else:
    print(f"\n=== 板块数据文件不存在: {sectors_path} ===")

# Also check fund_flows
fund_flows_path = f'C:/Users/admin/aazhous-projects/atlas-ai/data/stock/fund_flows-{today}.json'
if os.path.exists(fund_flows_path):
    with open(fund_flows_path, 'r', encoding='utf-8') as f:
        ff = json.load(f)
    print("\n=== 资金流 (前20条) ===")
    if isinstance(ff, list):
        for s in ff[:20]:
            print(f"  {s.get('name','?')}: 涨跌{s.get('chg_pct',0)}% 主力净流入{s.get('net_flow',0)}亿")
    elif isinstance(ff, dict):
        print(json.dumps(ff, ensure_ascii=False, indent=2)[:2000])
