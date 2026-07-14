import json, urllib.request

# Check 300034 price quickly
url = 'https://hq.sinajs.cn/list=sz300034'
req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn'})
with urllib.request.urlopen(req) as resp:
    data = resp.read().decode('gbk')
print(data[:200])
