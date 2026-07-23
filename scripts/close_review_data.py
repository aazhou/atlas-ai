import json, sys, os, re
from datetime import datetime

os.chdir('C:/Users/admin/aazhous-projects/atlas-ai')

# === 1. 板块数据 ===
with open('data/stock/fund_flows-2026-07-23.json', 'r', encoding='utf-8') as f:
    ff = json.load(f)

sectors = ff['sectors']

# 按主力流入排序
by_inflow = sorted(sectors.items(), key=lambda x: x[1]['fund_flow'], reverse=True)
by_outflow = sorted(sectors.items(), key=lambda x: x[1]['fund_flow'])
by_chg_up = sorted(sectors.items(), key=lambda x: x[1]['current'], reverse=True)
by_chg_down = sorted(sectors.items(), key=lambda x: x[1]['current'])

total_in = sum(v['fund_flow'] for v in sectors.values() if v['fund_flow'] > 0)
total_out = sum(v['fund_flow'] for v in sectors.values() if v['fund_flow'] < 0)
net_flow = total_in + total_out
up_count = sum(1 for v in sectors.values() if v['current'] > 0)
down_count = sum(1 for v in sectors.values() if v['current'] < 0)
flat_count = sum(1 for v in sectors.values() if v['current'] == 0)

print(f"=== SECTOR STATS ===")
print(f"Total sectors: {len(sectors)}")
print(f"Up: {up_count}, Down: {down_count}, Flat: {flat_count}")
print(f"Net flow: {net_flow:.1f}亿 (In: {total_in:.1f}亿, Out: {total_out:.1f}亿)")

print(f"\n=== TOP10 BY INFLOW ===")
for name, v in by_inflow[:10]:
    print(f"  {name}: inflow={v['fund_flow']:.2f}亿, chg={v['current']:.2f}%")

print(f"\n=== TOP5 BY CHG UP (small cap leaders) ===")
for name, v in by_chg_up[:5]:
    print(f"  {name}: chg={v['current']:.2f}%, flow={v['fund_flow']:.2f}亿")

print(f"\n=== TOP5 BY CHG DOWN (worst) ===")
for name, v in by_chg_down[:5]:
    print(f"  {name}: chg={v['current']:.2f}%, flow={v['fund_flow']:.2f}亿")

print(f"\n=== TOP5 BY OUTFLOW ===")
for name, v in by_outflow[:5]:
    print(f"  {name}: outflow={v['fund_flow']:.2f}亿, chg={v['current']:.2f}%")

# === 2. A股指数 (Sina API with GBK handling) ===
try:
    import subprocess
    result = subprocess.run(
        ['curl', '-s', 'https://hq.sinajs.cn/list=s_sh000001,s_sz399001,s_sz399006,s_sh000688,s_sh000300',
         '-H', 'Referer: https://finance.sina.com.cn'],
        capture_output=True, timeout=15
    )
    # Try GBK decode
    raw = result.stdout
    try:
        text = raw.decode('gbk')
    except:
        text = raw.decode('utf-8', errors='replace')
    
    print(f"\n=== A-INDEX RAW ===")
    print(text)
    
    # Parse
    indices = {}
    for line in text.strip().split('\n'):
        if '=' not in line:
            continue
        var_part = line.split('=')[0].strip()
        data_part = line.split('"')[1] if '"' in line else ''
        if not data_part:
            continue
        
        # Map var names
        name_map = {
            'var hq_str_s_sh000001': '上证指数',
            'var hq_str_s_sz399001': '深证成指',
            'var hq_str_s_sz399006': '创业板指',
            'var hq_str_s_sh000688': '科创50',
            'var hq_str_s_sh000300': '沪深300',
        }
        idx_name = name_map.get(var_part, var_part)
        parts = data_part.split(',')
        if len(parts) >= 4:
            name = parts[0]
            price = float(parts[1]) if parts[1] else 0
            chg_amt = float(parts[2]) if parts[2] else 0
            chg_pct = float(parts[3]) if parts[3] else 0
            print(f"  {name}: {price:.0f} ({chg_pct:+.2f}%)")
            indices[idx_name] = {'name': name, 'price': price, 'chg': chg_pct}

except Exception as e:
    print(f"\n=== SINA ERROR: {e} ===")

# === 3. 港股指数 (yfinance) ===
try:
    import yfinance as yf
    
    print(f"\n=== HK INDICES ===")
    for tkr, label in [('^HSI','恒生指数'), ('^HSCE','国企指数'), ('3032.HK','恒生科技ETF')]:
        try:
            t = yf.Ticker(tkr)
            h = t.history(period='3d')
            if len(h) >= 2:
                prev_close = float(h['Close'].iloc[-2])
                curr_close = float(h['Close'].iloc[-1])
                chg_pct = (curr_close / prev_close - 1) * 100
                print(f"  {label} ({tkr}): {curr_close:.0f} ({chg_pct:+.2f}%)")
            elif len(h) >= 1:
                curr_close = float(h['Close'].iloc[-1])
                chg_pct = float(h.iloc[-1]['Close'] - h.iloc[-1]['Open']) / float(h.iloc[-1]['Open']) * 100 if h.iloc[-1]['Open'] else 0
                print(f"  {label} ({tkr}): {curr_close:.0f} (today chg: {chg_pct:+.2f}%)")
            else:
                print(f"  {label}: no data")
        except Exception as e:
            print(f"  {label}: ERROR {e}")

except Exception as e:
    print(f"=== YFINANCE ERROR: {e} ===")

print(f"\n=== DONE ===")
