"""
初始化 atlas.duckdb — 统一数据底座
表: stock_sectors(板块涨跌), stock_fund_flows(资金流), stock_portfolio(持仓)
"""
import duckdb, os

DB = r'C:\Users\admin\aazhous-projects\atlas-ai\data\atlas.duckdb'
con = duckdb.connect(DB)

con.execute("""
CREATE TABLE IF NOT EXISTS stock_sectors (
    date VARCHAR,
    time VARCHAR,
    sector VARCHAR,
    chg DOUBLE,
    PRIMARY KEY (date, time, sector)
)
""")

con.execute("""
CREATE TABLE IF NOT EXISTS stock_fund_flows (
    date VARCHAR,
    time VARCHAR,
    sector VARCHAR,
    fund_flow DOUBLE,  -- 亿元
    chg DOUBLE,
    PRIMARY KEY (date, time, sector)
)
""")

con.execute("""
CREATE TABLE IF NOT EXISTS stock_portfolio (
    date VARCHAR,
    time VARCHAR,
    code VARCHAR,
    name VARCHAR,
    price DOUBLE,
    chg DOUBLE,
    pnl DOUBLE,
    cost DOUBLE,
    status VARCHAR,
    action VARCHAR,
    PRIMARY KEY (date, time, code)
)
""")

# Migrate existing JSON data into DuckDB
import json, glob

data_dir = r'C:\Users\admin\aazhous-projects\atlas-ai\data\stock'

# Migrate sectors
for f in sorted(glob.glob(f'{data_dir}/sectors-*.json')):
    date = os.path.basename(f).replace('sectors-', '').replace('.json', '')
    with open(f) as fp:
        d = json.load(fp)
    for sector, info in d.get('sectors', {}).items():
        for h in info.get('history', []):
            try:
                con.execute("INSERT OR IGNORE INTO stock_sectors VALUES (?, ?, ?, ?)",
                           [date, h['time'], sector, h['chg']])
            except:
                pass
    print(f'Migrated {date}: {len(d.get("sectors",{}))} sectors')

# Migrate portfolio history (we only have current snapshot, but let's save it)
pf_path = f'{data_dir}/portfolio.json'
if os.path.exists(pf_path):
    with open(pf_path) as f:
        pf = json.load(f)
    updated = pf.get('updated', '')
    date = updated[:10] if updated else '2026-07-13'
    time = updated[11:16] if len(updated) > 11 else '00:00'
    for h in pf.get('holdings', []):
        try:
            con.execute("INSERT OR IGNORE INTO stock_portfolio VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       [date, time, h['code'], h['name'], h['price'], h.get('chg', 0),
                        h.get('pnl', 0), h.get('cost', 0), h.get('status', ''), h.get('action', '')])
        except:
            pass
    print(f'Migrated portfolio: {len(pf.get("holdings",[]))} holdings')

con.close()
print('\nDone. atlas.duckdb created.')
