import sys, json
from datetime import datetime

# Check trading day
today = datetime.now()
print(f"Today: {today.strftime('%Y-%m-%d')} Weekday: {today.weekday()}")
try:
    from trading_calendar import is_a_stock_trading_day
    print(f"Trading day: {is_a_stock_trading_day()}")
except ImportError:
    print(f"Trading day (weekday): {today.weekday() < 5}")

# Sector data
import os, glob
sector_files = sorted(glob.glob('/c/Users/admin/aazhous-projects/atlas-ai/data/sectors-2026-07-*.json'))
print(f"\nSector files found: {len(sector_files)}")
if sector_files:
    latest = sector_files[-1]
    print(f"Latest: {latest}")
    with open(latest) as f:
        data = json.load(f)
    if isinstance(data, list) and len(data) > 0:
        # Show top/bottom by change
        sorted_data = sorted(data, key=lambda x: x.get('change_pct', 0), reverse=True)
        print("\nTop 5 sectors:")
        for s in sorted_data[:5]:
            print(f"  {s.get('name','?')}: {s.get('change_pct',0):+.2f}%")
        print("\nBottom 5 sectors:")
        for s in sorted_data[-5:]:
            print(f"  {s.get('name','?')}: {s.get('change_pct',0):+.2f}%")
