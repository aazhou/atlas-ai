import duckdb, json, math
from datetime import datetime

con=duckdb.connect('C:/Users/admin/aazhous-projects/atlas-ai/data/crypto/market.duckdb', read_only=True)
for sym in ['SKLUSDT']:
    kl=con.execute(f"SELECT open_time/1000, open, high, low, close, volume FROM kline WHERE symbol='{sym}' AND interval='5m' ORDER BY open_time").fetchall()
    kl4=con.execute(f"SELECT open_time/1000, close FROM kline WHERE symbol='{sym}' AND interval='4h' ORDER BY open_time").fetchall()
    fr=con.execute(f"SELECT funding_time, funding_rate FROM funding WHERE symbol='{sym}' ORDER BY funding_time").fetchall()
    
    c4=[c for _,c in kl4]
    trends=[]
    for i in range(len(kl4)):
        if i<20: trends.append(True)
        else:
            ma20=sum(c4[i-20:i])/20; ma50=sum(c4[max(0,i-50):i])/min(50,i)
            trends.append(ma20>ma50)
    
    rates=[r for _,r in fr]
    p5=sorted(rates)[int(len(rates)*0.05)]
    p95=sorted(rates)[int(len(rates)*0.95)]
    
    trades_long=[]; trades_short=[]
    pos=None; fi=0
    
    for i in range(100,len(kl)):
        t=int(kl[i][0]); o,h,l,c,v=kl[i][1:6]
        while fi+1<len(fr) and fr[fi+1][0]<=t*1000: fi+=1
        rate=fr[fi][1] if fi<len(fr) else 0
        fhi=0
        while fhi+1<len(kl4) and kl4[fhi+1][0]<=t: fhi+=1
        tu=trends[fhi] if fhi<len(trends) else True
        
        if pos:
            pnl=(c/pos['ep']-1)*100
            if pos['dir']=='SHORT': pnl=-pnl
            h=(t-pos['et'])/3600
            er=None
            if pnl<=-10: er='止损'
            elif pnl>=5: er='止盈'
            elif h>=48: er='超时'
            elif i==len(kl)-1: er='收盘'
            if er:
                rec={'pnl':round(pnl,2),'reason':er,'dur':f'{h:.0f}h'}
                (trades_long if pos['dir']=='LONG' else trades_short).append(rec)
                pos=None
        else:
            if i<20: continue
            po,pc=kl[i-1][1],kl[i-1][4]
            body=abs(c-o); wl=min(o,c)-l; wh=h-max(o,c); tr=max(h-l,1e-8)
            cn=((1 if wl>body*1.5 and wl>wh*1.5 else 0)+(1 if pc<po and c>o and o<po and c>pc else 0))/2
            avg_vol=sum(kl[j][5] for j in range(i-20,i))/20
            vl=min(v/max(avg_vol,1e-8)/3,1) if c>o else 0
            sma20=sum(kl[j][4] for j in range(i-20,i))/20
            sma50=sum(kl[j][4] for j in range(max(0,i-50),i))/min(50,i) if i>=50 else sma20
            trend=1.0 if c>sma50 else(0.3 if c>sma20 else 0)
            lo20=min(kl[j][3] for j in range(i-20,i)); hi20=max(kl[j][2] for j in range(i-20,i))
            pb=(hi20-c)/max(hi20,1e-8)
            pa=((1 if 0.03<pb<0.20 else 0)+(1 if c>sma20 else 0))/2
            sc=round(0.2*cn+0.4*vl+0.3*pa+0.1*trend,2)
            
            if rate<p5 and tu and sc>=0.18:
                pos={'et':t,'ep':c,'dir':'LONG'}
            elif rate>p95 and not tu and sc>=0.18:
                pos={'et':t,'ep':c,'dir':'SHORT'}
    
    print(f'\nSKL ({len(kl)} bars, {datetime.fromtimestamp(kl[0][0]).strftime("%Y-%m-%d")} -> {datetime.fromtimestamp(kl[-1][0]).strftime("%Y-%m-%d")}):')
    for name, trades in [('LONG',trades_long),('SHORT',trades_short)]:
        if len(trades)<3: 
            print(f'  {name}: {len(trades)} trades (insufficient)')
            continue
        rets=[t['pnl'] for t in trades]
        wins=sum(1 for r in rets if r>0)
        avg=sum(rets)/len(rets)
        std=math.sqrt(sum((r-avg)**2 for r in rets)/len(rets)) if len(rets)>1 else 1
        sh=min((avg/max(std,0.01))*math.sqrt(len(rets)),99.99)
        eq=0; peak=0; dd=0
        for r in rets:
            eq+=r
            if eq>peak: peak=eq
            if peak-eq>dd: dd=peak-eq
        sc=min(sh/3,1)*30+min(wins/len(rets)/0.8,1)*20+max(0,1-dd/40)*25+min(len(rets)/30,1)*15
        print(f'  {name}: {len(rets)}T WR={wins/len(rets)*100:.0f}% avg={avg:+.1f}% DD={dd:.0f}% Sh={sh:.1f} Score={sc:.0f}')

con.close()
