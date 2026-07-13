import duckdb
con = duckdb.connect('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb', read_only=True)
SYM = 'TUSDT'
klines = con.execute(f"SELECT open_time/1000,open,high,low,close,volume FROM kline WHERE symbol='{SYM}' AND interval='15m' ORDER BY open_time").fetchall()
n = len(klines)
hm = eng = bvol = ama = nsup = hpb = 0
for i in range(50, n):
    o, hi, lo, c, v = klines[i][1], klines[i][2], klines[i][3], klines[i][4], klines[i][5]
    po, pc = klines[i-1][1], klines[i-1][4]
    body = abs(c-o); wl = min(o,c)-lo; tot = max(hi-lo, 1e-8)
    if wl > body*2 and body < tot and c > o: hm += 1
    if pc < po and c > o and o <= pc and c >= po: eng += 1
    if c > o and v > sum(k[5] for k in klines[i-20:i])/20*2: bvol += 1
    sma20 = sum(k[4] for k in klines[i-20:i])/20
    if c > sma20: ama += 1
    lo20 = min(k[3] for k in klines[i-20:i])
    if (c-lo20)/max(lo20, 1e-8) < 0.03: nsup += 1
    hi20 = max(k[2] for k in klines[i-20:i]); pb = (hi20-c)/max(hi20, 1e-8)
    if 0.05 < pb < 0.15: hpb += 1
t = n-50
print(f'{SYM} {t} bars:')
print(f'Hammer:{hm}({hm/t*100:.0f}%) Engulf:{eng}({eng/t*100:.0f}%) BullVol:{bvol}({bvol/t*100:.0f}%)')
print(f'AboveMA:{ama}({ama/t*100:.0f}%) NearSup:{nsup}({nsup/t*100:.0f}%) HealthyPB:{hpb}({hpb/t*100:.0f}%)')
con.close()
