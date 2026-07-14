import sys
from datetime import datetime, time, date

now = datetime.now()
t = now.time()
weekday = now.weekday()  # 0=周一

# 港股交易时段: 9:30-12:00, 13:00-16:00
hkt_morning = time(9,30) <= t <= time(12,0)
hkt_afternoon = time(13,0) <= t <= time(16,0)
in_session = hkt_morning or hkt_afternoon

print(f"HK_CHECK|time={now.strftime('%H:%M:%S')}|date={now.strftime('%Y-%m-%d')}|weekday={weekday}|morning={hkt_morning}|afternoon={hkt_afternoon}|session={in_session}")

if not in_session:
    print("HK_CHECK|NOT_IN_SESSION")
    sys.exit(0)

if weekday >= 5:
    print("HK_CHECK|WEEKEND")
    sys.exit(0)

print("HK_CHECK|IN_SESSION|MONITORING")
