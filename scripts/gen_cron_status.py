import json, os

d = r'C:\Users\admin\aazhous-projects\atlas-ai\data\stock'

cats = {
    '🇨🇳 A股': {
        'jobs': [
            {'name': '板块采集', 'schedule': '*/5 9-14', 'type': '脚本', 'last': '15:00', 'status': 'ok'},
            {'name': '持仓哨兵', 'schedule': '*/10 9-14', 'type': '脚本', 'last': '14:50', 'status': 'ok'},
            {'name': '盘中预判', 'schedule': '10,11,13,14', 'type': 'AI', 'last': '14:00', 'status': 'ok'},
            {'name': '收盘更新', 'schedule': '15:35', 'type': 'AI', 'last': '—', 'status': 'pending'},
        ],
        'error': 0, 'paused': 0
    },
    '🇭🇰 港股': {
        'jobs': [
            {'name': '紧急盯盘', 'schedule': '10,11,14,15', 'type': '脚本', 'last': '14:00', 'status': 'ok'},
            {'name': 'AI盯盘', 'schedule': '10:30,14:30', 'type': 'AI', 'last': '14:30', 'status': 'ok'},
        ],
        'error': 0, 'paused': 0
    },
    '🇺🇸 美股': {
        'jobs': [
            {'name': '异动监控', 'schedule': '22-3', 'type': '脚本', 'last': '待启动', 'status': 'pending'},
            {'name': '早间简报', 'schedule': '8:00', 'type': 'AI', 'last': '明日8:00', 'status': 'pending'},
        ],
        'error': 0, 'paused': 0
    },
    '🔧 加密': {
        'jobs': [
            {'name': 'V11模拟交易', 'schedule': '*/10', 'type': '脚本', 'last': '运行中', 'status': 'ok'},
        ],
        'error': 0, 'paused': 0
    },
}

all_jobs = []
for c in cats.values():
    all_jobs.extend(c['jobs'])

total = len(all_jobs)
active = sum(1 for j in all_jobs if j['status'] == 'ok')
pending = sum(1 for j in all_jobs if j['status'] == 'pending')
error = sum(1 for j in all_jobs if j['status'] == 'error')
paused = sum(1 for j in all_jobs if j['status'] == 'paused')

data = {
    'updated': '2026-07-13 15:35',
    'total': total,
    'active': active,
    'ok': active,
    'error': error,
    'paused': paused,
    'categories': cats,
}

with open(os.path.join(d, 'cron_status.json'), 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f'Wrote: {total} jobs, {active} active')
