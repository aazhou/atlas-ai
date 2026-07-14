import requests
import re
import json
import os
import sys
from datetime import datetime

results = {}
today = datetime.now().strftime('%Y-%m-%d')
now = datetime.now()
print(f"=== Atlas 盘中预判 {now.strftime('%H:%M')} ===")
print(f"日期: {today}\n")

# Step 0: 实时行情
codes = 'sz300236,sh688099,sz002475,sz000963,sz300034'
try:
    r = requests.get(f'https://hq.sinajs.cn/list={codes}',
                     headers={'Referer':'https://finance.sina.com.cn/'}, timeout=10)
    r.encoding = 'gbk'

    stocks = {}
    for line in r.text.strip().split('\n'):
        if not line.strip():
            continue
        m = re.match(r'var hq_str_(\w+)="(.+)"', line)
        if m:
            code = m.group(1)
            fields = m.group(2).split(',')
            name = fields[0]
            open_price = float(fields[1]) if fields[1] else 0
            yest_close = float(fields[2]) if fields[2] else 0
            cur_price = float(fields[3]) if fields[3] else 0
            high = float(fields[4]) if fields[4] else 0
            low = float(fields[5]) if fields[5] else 0

            if yest_close > 0:
                chg_pct = (cur_price - yest_close) / yest_close * 100
            else:
                chg_pct = 0

            stocks[code] = {
                'name': name, 'cur': cur_price, 'yest': yest_close,
                'chg_pct': round(chg_pct, 2), 'high': high, 'low': low,
                'open': open_price
            }

    results['stocks'] = stocks
    print("=== 实时行情 ===")
    for code, s in stocks.items():
        direction = "🔴" if s['chg_pct'] < -2 else ("🟢" if s['chg_pct'] > 2 else ("🔻" if s['chg_pct'] < 0 else "🔺"))
        print(f"{direction} {s['name']}({code}): {s['cur']:.2f} | {s['chg_pct']:+.2f}% | 高{s['high']:.2f}低{s['low']:.2f}")

except Exception as e:
    results['stocks'] = {}
    print(f"新浪行情错误: {e}")

# Step 1: 动量数据
base = r'C:\Users\admin\aazhous-projects\atlas-ai\data\stock'
mom_path = os.path.join(base, f'sector_momentum-{today}.json')

if os.path.exists(mom_path):
    with open(mom_path, 'r', encoding='utf-8') as f:
        mom_data = json.load(f)
    results['momentum'] = mom_data
    print("\n=== 板块动量 ===")
    # 加速流入
    accel_up = mom_data.get('accel_up', [])
    if accel_up:
        print("📈 加速流入:")
        for s in accel_up[:5]:
            print(f"  {s.get('name','?')}: {s.get('inflow',0):+.2f}亿 | 动量变化{s.get('delta',0):+.2f}")
    # 加速流出
    accel_down = mom_data.get('accel_down', [])
    if accel_down:
        print("📉 加速流出:")
        for s in accel_down[:5]:
            print(f"  {s.get('name','?')}: {s.get('inflow',0):+.2f}亿 | 动量变化{s.get('delta',0):+.2f}")
    # 轮动
    rot = mom_data.get('rotation', [])
    if rot:
        print("🔄 轮动信号:")
        for r in rot[:3]:
            print(f"  {r}")
else:
    results['momentum'] = {}
    print(f"\n⚠️ 动量文件不存在: {mom_path}")

# Step 2: 板块数据
sec_path = os.path.join(base, f'sectors-{today}.json')
if os.path.exists(sec_path):
    with open(sec_path, 'r', encoding='utf-8') as f:
        sec_data = json.load(f)
    results['sectors'] = sec_data
    print("\n=== 板块行情 ===")
    
    sectors_list = []
    if isinstance(sec_data, dict):
        # Try different keys
        for key in ['sectors', 'data', 'items']:
            if key in sec_data and isinstance(sec_data[key], list):
                sectors_list = sec_data[key]
                break
        if not sectors_list and 'top_sectors' in sec_data:
            # Handle market summary format
            top = sec_data.get('top_sectors', [])
            worst = sec_data.get('worst_sectors', [])
            print("领涨板块:")
            for s in top[:5]:
                if isinstance(s, dict):
                    print(f"  {s.get('name','?')}: {s.get('chg',0):+.2f}%")
            print("领跌板块:")
            for s in worst[:5]:
                if isinstance(s, dict):
                    print(f"  {s.get('name','?')}: {s.get('chg',0):+.2f}%")
    elif isinstance(sec_data, list):
        sectors_list = sec_data
    
    if sectors_list:
        # Sort by change
        sorted_sec = sorted(sectors_list, key=lambda x: float(x.get('change', x.get('chg', x.get('f184', 0))) if x.get('change') or x.get('chg') or x.get('f184') else 0), reverse=True)
        print("领涨TOP3:")
        for s in sorted_sec[:3]:
            chg = float(s.get('change', s.get('chg', s.get('f184', 0))) or 0)
            name = s.get('name', s.get('f14', '?'))
            print(f"  {name}: {chg:+.2f}%")
        print("领跌TOP3:")
        for s in sorted_sec[-3:]:
            chg = float(s.get('change', s.get('chg', s.get('f184', 0))) or 0)
            name = s.get('name', s.get('f14', '?'))
            print(f"  {name}: {chg:+.2f}%")
else:
    results['sectors'] = {}
    print(f"\n⚠️ 板块文件不存在: {sec_path}")

# Step 3: 资金流数据
flow_path = os.path.join(base, f'fund_flows-{today}.json')
if os.path.exists(flow_path):
    with open(flow_path, 'r', encoding='utf-8') as f:
        flow_data = json.load(f)
    results['fund_flows'] = flow_data
    print("\n=== 板块资金流 ===")
    
    flow_list = []
    if isinstance(flow_data, list):
        flow_list = flow_data
    elif isinstance(flow_data, dict):
        for key in ['data', 'items', 'flows']:
            if key in flow_data and isinstance(flow_data[key], list):
                flow_list = flow_data[key]
                break
    
    if flow_list:
        sorted_by_flow = sorted(flow_list, key=lambda x: float(x.get('f62', 0)) if x.get('f62') else 0, reverse=True)
        print("流入TOP5:")
        for s in sorted_by_flow[:5]:
            flow_yi = float(s.get('f62', 0)) / 1e8 if s.get('f62') else 0
            name = s.get('f14', '?')
            chg = float(s.get('f184', 0)) if s.get('f184') else 0
            print(f"  {name}: {flow_yi:+.2f}亿 | {chg:+.2f}%")
        print("流出TOP5:")
        for s in sorted_by_flow[-5:]:
            flow_yi = float(s.get('f62', 0)) / 1e8 if s.get('f62') else 0
            name = s.get('f14', '?')
            chg = float(s.get('f184', 0)) if s.get('f184') else 0
            print(f"  {name}: {flow_yi:+.2f}亿 | {chg:+.2f}%")
else:
    results['fund_flows'] = {}
    print(f"\n⚠️ 资金流文件不存在: {flow_path}")

# Output all for downstream processing
print("\n__JSON_START__")
# Clean results for JSON
clean = {}
if 'stocks' in results:
    clean['stocks'] = {k: {kk: vv for kk, vv in v.items() if kk != 'volume'} for k, v in results['stocks'].items()}
if 'momentum' in results:
    m = results['momentum']
    clean['momentum_summary'] = {
        'has_accel_up': bool(m.get('accel_up')),
        'accel_up_count': len(m.get('accel_up', [])),
        'has_accel_down': bool(m.get('accel_down')),
        'accel_down_count': len(m.get('accel_down', [])),
        'has_rotation': bool(m.get('rotation'))
    }
if 'fund_flows' in results:
    flow_list = results['fund_flows']
    if isinstance(flow_list, dict):
        for key in ['data', 'items', 'flows']:
            if key in flow_list and isinstance(flow_list[key], list):
                flow_list = flow_list[key]
                break
    if isinstance(flow_list, list) and flow_list:
        sorted_f = sorted(flow_list, key=lambda x: float(x.get('f62', 0)) if x.get('f62') else 0, reverse=True)
        clean['top_inflow'] = [{'name': s.get('f14','?'), 'flow_yi': round(float(s.get('f62',0))/1e8, 2) if s.get('f62') else 0, 'chg': float(s.get('f184',0)) if s.get('f184') else 0} for s in sorted_f[:5]]
        clean['top_outflow'] = [{'name': s.get('f14','?'), 'flow_yi': round(float(s.get('f62',0))/1e8, 2) if s.get('f62') else 0, 'chg': float(s.get('f184',0)) if s.get('f184') else 0} for s in sorted_f[-5:]]
print(json.dumps(clean, ensure_ascii=False))
print("__JSON_END__")
