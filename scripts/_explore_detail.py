import duckdb
c = duckdb.connect('data/crypto/market.duckdb')

print('=== SYMBOLS ===')
for table in ['funding_rate', 'kline', 'oi_snapshot']:
    syms = c.execute(f'SELECT DISTINCT symbol FROM {table} ORDER BY symbol').fetchall()
    print(f'{table}: {[s[0] for s in syms]}')

print('\n=== KLINE INTERVALS ===')
ints = c.execute('SELECT DISTINCT interval FROM kline ORDER BY interval').fetchall()
print([i[0] for i in ints])

print('\n=== TIME RANGES ===')
for table in ['funding_rate', 'kline', 'oi_snapshot']:
    if table == 'funding_rate':
        r = c.execute(f'SELECT MIN(funding_time), MAX(funding_time), COUNT(*) FROM {table}').fetchone()
    elif table == 'kline':
        r = c.execute(f'SELECT MIN(open_time), MAX(open_time), COUNT(*) FROM {table}').fetchone()
    else:
        r = c.execute(f'SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM {table}').fetchone()
    from datetime import datetime
    print(f'{table}: {datetime.fromtimestamp(r[0]/1000)} -> {datetime.fromtimestamp(r[1]/1000)} ({r[2]} rows)')

print('\n=== KLINE COUNT PER SYMBOL/INTERVAL ===')
for row in c.execute('SELECT symbol, interval, COUNT(*) FROM kline GROUP BY symbol, interval ORDER BY symbol, interval').fetchall():
    print(f'  {row}')

print('\n=== OI PERIODS ===')
pts = c.execute('SELECT DISTINCT period FROM oi_snapshot').fetchall()
print([p[0] for p in pts])

print('\n=== OI SAMPLE ===')
for row in c.execute('SELECT * FROM oi_snapshot ORDER BY timestamp DESC LIMIT 10').fetchall():
    from datetime import datetime
    print(f'  {row[0]} {row[1]} {datetime.fromtimestamp(row[2]/1000)} oi={row[3]}')

print('\n=== FUNDING SAMPLE ===')
for row in c.execute('SELECT * FROM funding_rate ORDER BY funding_time DESC LIMIT 10').fetchall():
    from datetime import datetime
    print(f'  {row[0]} {datetime.fromtimestamp(row[1]/1000)} rate={row[2]}')
