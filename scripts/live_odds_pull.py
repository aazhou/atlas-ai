import requests, json, sys
API_KEY = "2ba21b0426a6258b59f0e74e907b6172"
SPORT = "soccer_fifa_world_cup"
resp = requests.get(
    f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/",
    params={
        "apiKey": API_KEY,
        "regions": "us,uk,eu",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso"
    },
    timeout=20
)
remaining = resp.headers.get("x-requests-remaining", "?")
print(f"REMAINING: {remaining}")
data = resp.json()

# Find England vs Argentina
for m in data:
    ht = m.get("home_team", "")
    at = m.get("away_team", "")
    if "England" in ht and "Argentina" in at:
        print(f"MATCH: {ht} vs {at}")
        # Get all bookmakers' H2H
        for bk in m.get("bookmakers", []):
            title = bk.get("title", "")
            markets = bk.get("markets", [])
            for mk in markets:
                key = mk.get("key", "")
                if key == "h2h":
                    outcomes = {o["name"]: o["price"] for o in mk.get("outcomes", [])}
                    print(f"H2H | {title}: {json.dumps(outcomes)}")
                elif key == "totals":
                    for out in mk.get("outcomes", []):
                        print(f"TOTALS | {title}: line={out.get('point')} {out.get('name')}={out.get('price')}")
        break
