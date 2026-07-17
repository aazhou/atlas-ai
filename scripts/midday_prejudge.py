import requests, re, json, os, sys
from datetime import datetime

today = datetime.now().strftime('%Y-%m-%d')

# Step 0: Real-time prices
codes = 'sz300236,sh688099,sz002475,sz000963,sz300034'
try:
    r = requests.get(f'https://hq.sinajs.cn/list={codes}', headers={'Referer':'https://finance.sina.com.cn/'}, timeout=10)
    r.encoding = 'gbk'
except Exception as e:
    print(f"新浪API错误: {e}")
    sys.exit(1)

print("=== 实时行情 ===")
holdings = {}
for line in r.text.strip().split('\n'):
    if not line.strip(): continue
    parts = line.split('"')[1].split(',')
    name = parts[0]
    cur = float(parts[3])
    yest = float(parts[2])
    chg = (cur/yest - 1) * 100
    holdings[name] = {'cur': cur, 'yest': yest, 'chg': chg}
    print(f"{name} | 现价:{cur:.2f} | 昨收:{yest:.2f} | 涨跌:{chg:+.2f}%")

# Step 1-2: Read data files
base = 'C:/Users/admin/aazhous-projects/atlas-ai/data/stock'
momentum_file = f'{base}/sector_momentum-{today}.json'
sectors_file = f'{base}/sectors-{today}.json'

print("\n=== 动量数据 ===")
try:
    with open(momentum_file, 'r') as f:
        mom = json.load(f)
    print(f"更新时间: {mom.get('updated', 'unknown')}")
    if 'accel_up' in mom:
        print(f"加速流入板块 ({len(mom['accel_up'])}):")
        for s in mom['accel_up'][:5]:
            print(f"  + {s}")
    if 'accel_down' in mom:
        print(f"加速流出板块 ({len(mom['accel_down'])}):")
        for s in mom['accel_down'][:5]:
            print(f"  - {s}")
    if 'rotation' in mom:
        print(f"轮动信号: {mom['rotation']}")
except FileNotFoundError:
    print("动量文件不存在")

print("\n=== 板块数据 ===")
try:
    with open(sectors_file, 'r') as f:
        sec = json.load(f)
    print(f"更新时间: {sec.get('updated', 'unknown')}")
    if 'alerts' in sec:
        print(f"异动记录 ({len(sec['alerts'])}):")
        for a in sec['alerts'][-5:]:
            print(f"  {a}")
    # 找持仓相关板块
    target_sectors = ['半导体', '电子', '消费电子', '医药', '军工', '材料', '自动化']
    if 'sectors' in sec:
        for s_name, s_data in sec['sectors'].items():
            for t in target_sectors:
                if t in s_name:
                    flow = s_data.get('fund_flow', 0)
                    chg = s_data.get('chg_pct', 0)
                    print(f"  {s_name}: 资金{flow:+.1f}亿 | 涨跌{chg:+.2f}%")
                    break
except FileNotFoundError:
    print("板块文件不存在")

# Step 3: Forward-looking reasoning
print("\n=== 前瞻推理 ===")

# 持仓板块映射
holding_sectors = {
    '上海新阳': '半导体材料',
    '晶晨股份': '半导体/SoC',
    '立讯精密': '消费电子',
    '华东医药': '医药',
    '钢研高纳': '军工/高温合金'
}

# 判断整体方向
for name, sector in holding_sectors.items():
    if name in holdings:
        h = holdings[name]
        alert = ""
        if abs(h['chg']) > 3:
            alert = " ⚠️ 大幅波动!"
        print(f"{name}({sector}): {h['chg']:+.2f}%{alert}")
