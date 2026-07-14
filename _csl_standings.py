import requests, json

# CFL standings API
r = requests.get("https://www.cfl-china.cn/zh/statistics/list.html?competition_code=CSL", timeout=15)
print(f"Standings page status: {r.status_code}")
print(f"Content length: {len(r.text)}")

# Try API endpoint
r2 = requests.get("https://www.cfl-china.cn/api/standings?competition_code=CSL", timeout=15)
print(f"API status: {r2.status_code}")
if r2.status_code == 200:
    data = r2.json()
    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
