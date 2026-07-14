import requests, json, sys

API_KEY = "2ba21b0426a6258b59f0e74e907b6172"
SPORT = "soccer_china_superleague"

r = requests.get(
    f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/",
    params={
        "apiKey": API_KEY,
        "regions": "us,uk,eu",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso"
    },
    timeout=15
)

print(f"Status: {r.status_code}")
print(f"Remaining: {r.headers.get('x-requests-remaining', 'N/A')}")
data = r.json()

# Save raw
with open("/c/Users/admin/aazhous-projects/atlas-ai/data/football/_csl_odds_raw.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Matches found: {len(data)}")
for m in data:
    home = m.get("home_team", "?")
    away = m.get("away_team", "?")
    ct = m.get("commence_time", "?")
    print(f"  {home} vs {away} | {ct}")
    # Show bookmaker count
    bms = m.get("bookmakers", [])
    print(f"    Bookmakers: {len(bms)}")
    # Show Pinnacle H2H if present
    for bm in bms:
        if bm.get("key") == "pinnacle":
            for mk in bm.get("markets", []):
                if mk["key"] == "h2h":
                    prices = {o["name"]: o["price"] for o in mk["outcomes"]}
                    print(f"    Pinnacle H2H: {prices}")
