import json

path = r"C:\Users\admin\aazhous-projects\atlas-ai\data\football\2026-07-16.json"
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

match = data['matches'][0]

# Update score and clock
match['live_score'] = '1-1'
match['live_clock'] = "89'"
match['live_status'] = 'STATUS_SECOND_HALF'

# Update odds based on retail books (Pinnacle appears frozen, showing pre-match odds)
match['odds_h2h'] = {
    "home": 8.5,
    "draw": 1.25,
    "away": 6.0
}

match['odds_totals'] = {
    "line": 1.5,
    "over": 1.86,
    "under": 2.02,
    "lean": "over",
    "note": "89' 1-1 · 大小球线1.5 · 补时+可能加时"
}

match['odds_movement'] = "85' Enzo Fernández扳平1-1 · 平局崩溃3.50→1.20(-66%) · 大2.5已收@2.35 · 接近FT · 可能加时"

# Add timeline entry
new_timeline = {
    "time": "7/16 04:45",
    "event": "⚽ 进球 | 阿根廷 1-1 (85')",
    "detail": "Enzo Fernández 破门扳平！89' 1-1 · 平局赔率崩溃 3.50→1.20(-66%) · 零售盘口Draw@1.20市场定价加时 · 大2.5已收 · 英格兰55'Gordon进球后领先后被追平",
    "type": "goal"
}

data['timeline'].insert(0, new_timeline)
data['updated'] = "7/16 04:45"
match['updated'] = "7/16 04:45"

with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("JSON updated: 1-1, 89', Enzo Fernandez goal, odds collapse")
print("Timeline entries:", len(data['timeline']))
