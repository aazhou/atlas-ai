import duckdb
c = duckdb.connect('data/crypto/market.duckdb')
tables = c.execute("SELECT name FROM sqlite_master WHERE type='table' OR type='view'").fetchall()
print('TABLES:', tables)
for t in tables:
    name = t[0]
    print(f'\n=== {name} ===')
    cols = c.execute(f'DESCRIBE "{name}"').fetchall()
    for col in cols:
        print(f'  {col}')
    n = c.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
    print(f'Rows: {n}')
    rows = c.execute(f'SELECT * FROM "{name}" LIMIT 2').fetchall()
    for r in rows:
        print(f'  Sample: {r}')
