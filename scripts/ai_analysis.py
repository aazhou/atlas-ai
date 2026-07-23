"""
A股 AI 分析引擎 — 读全量数据 → 生成分析JSON → 供 stock/ai.html 展示
"""
import json, os
from datetime import datetime

DATA_DIR = r'C:\Users\admin\aazhous-projects\atlas-ai\data\stock'
today = datetime.now().strftime('%Y-%m-%d')

# ===== 加载数据 =====
def load(name):
    path = os.path.join(DATA_DIR, f'{name}-{today}.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return None

fund = load('fund_flows')      # 450板块资金流
limit = load('limit_data')     # 涨跌停
market = load('market_summary') # 市场汇总

if not fund:
    print("无今日数据"); exit(1)

sectors = fund['sectors']
all_list = [(n, s['fund_flow'], s['current']) for n, s in sectors.items()]

# ===== 核心指标 =====
total_in = sum(f for _, f, _ in all_list if f > 0)
total_out = sum(f for _, f, _ in all_list if f < 0)
net = total_in + total_out
up_count = sum(1 for _, _, c in all_list if c > 0)
down_count = sum(1 for _, _, c in all_list if c < 0)
flat_count = len(all_list) - up_count - down_count

# 涨幅TOP/BOTTOM
by_chg = sorted(all_list, key=lambda x: x[2], reverse=True)
by_flow = sorted(all_list, key=lambda x: x[1], reverse=True)

top_gainers = [(n, c, f) for n, f, c in by_chg[:8]]
top_losers = [(n, c, f) for n, f, c in by_chg[-8:]]
top_inflow = [(n, f, c) for n, f, c in by_flow[:10]]
top_outflow = [(n, f, c) for n, f, c in by_flow if f < 0][:10]

# 涨跌停
dt_total = limit['limit_down']['total'] if limit else 0
zt_total = limit['limit_up']['total'] if limit else 0
dt_300 = limit['limit_down']['gem_300'] if limit else 0
dt_688 = limit['limit_down']['star_688'] if limit else 0

# ===== AI判定 =====
# 市场情绪评分: -100(极度恐慌) ~ +100(极度贪婪)
# 因素: 涨跌比、净流向、涨跌停比、板块集中度
up_ratio = up_count / len(all_list)
emotion_score = 0
emotion_score += (up_ratio - 0.5) * 80  # 涨跌比
emotion_score += max(-40, min(40, net / 5))  # 净流向(每5亿=1分)
if dt_total > 0:
    emotion_score -= min(50, dt_total / 4)  # 跌停惩罚
emotion_score += min(30, zt_total / 4)  # 涨停加分
emotion_score = max(-100, min(100, emotion_score))

# 方向判定
if emotion_score > 40:
    direction = "🟢 偏多"
    direction_desc = "资金面积极，市场做多情绪占主导"
elif emotion_score > 10:
    direction = "🟡 震荡偏多"
    direction_desc = "多方略占优，但力度不够，方向待确认"
elif emotion_score > -10:
    direction = "⚪ 中性震荡"
    direction_desc = "多空力量均衡，市场在等待方向选择"
elif emotion_score > -40:
    direction = "🟠 震荡偏空"
    direction_desc = "空方主导，多数板块承压，防守为主"
else:
    direction = "🔴 偏空"
    direction_desc = "资金大面积撤离，恐慌情绪蔓延，现金为王"

# 轮动分析
# 找持续流入板块(3日以上)
# 简化: 用今日TOP流入判断主线
main_line = [n for n, f, c in top_inflow[:5] if f > 5]
escape_from = [n for n, f, c in top_outflow[:5] if f < -5]

# 风格判断
style_map = {
    "科技": ["计算机","IT服务","半导体","通信","电子","芯片","软件","5G"],
    "周期": ["电力","煤炭","石油","有色","钢铁","化工","公用事业"],
    "消费": ["白酒","食品饮料","医药","医疗","汽车","旅游"],
    "金融": ["银行","保险","证券","非银"],
}
style_scores = {}
for style, keywords in style_map.items():
    inflow = sum(f for n, f, _ in all_list if any(k in n for k in keywords) and f > 0)
    outflow = sum(abs(f) for n, f, _ in all_list if any(k in n for k in keywords) and f < 0)
    count = sum(1 for n, _, _ in all_list if any(k in n for k in keywords))
    style_scores[style] = {"inflow": round(inflow, 1), "outflow": round(outflow, 1), "count": count}

# 主导风格
leading_style = max(style_scores.items(), key=lambda x: x[1]['inflow'] - x[1]['outflow'])

# ===== 风险信号 =====
risks = []
if dt_total > 300:
    risks.append({"level": "🔴", "msg": f"{dt_total}只跌停，其中科创板{dt_688}只、创业板{dt_300}只，小票系统性踩踏"})
elif dt_total > 100:
    risks.append({"level": "🟠", "msg": f"{dt_total}只跌停，个股风险加剧，注意中小盘"})
if net < -200:
    risks.append({"level": "🔴", "msg": f"全市场净流出{abs(net):.0f}亿，资金加速撤离"})
elif net < -50:
    risks.append({"level": "🟠", "msg": f"全市场净流出{abs(net):.0f}亿，资金面偏紧"})
if down_count > len(all_list) * 0.7:
    risks.append({"level": "🟠", "msg": f"{down_count}/{len(all_list)}板块下跌，市场广度极差"})

# ===== 操作建议 =====
actions = []
if net < -100:
    actions.append({"priority": 1, "action": "不开新仓", "detail": f"净流出{abs(net):.0f}亿+{dt_total}只跌停，现金为王", "type": "avoid"})
if emotion_score < -20:
    actions.append({"priority": 2, "action": "减仓防守", "detail": "降低仓位至5成以下，保留现金等恐慌底", "type": "reduce"})
if main_line:
    actions.append({"priority": 3, "action": "仅持有资金流入方向", "detail": f"资金仅集中在{'/'.join(main_line[:4])}，其他板块不碰", "type": "focus"})
if zt_total < 30:
    actions.append({"priority": 4, "action": "不追涨停", "detail": f"涨停仅{zt_total}只，赚钱效应极差，追板=接盘", "type": "avoid"})

# 如果有持仓分析
try:
    with open(os.path.join(DATA_DIR, 'portfolio.json'), encoding='utf-8') as f:
        portfolio = json.load(f)
    portfolio_actions = portfolio.get('analysis', {}).get('actions', [])
except:
    portfolio_actions = []

# ===== 明日预判 =====
tomorrow = []
# 基于今天模式推演明天
if net < -200 and dt_total > 200:
    tomorrow.append("⚠️ 明天大概率低开。若低开后跌停数收敛到100只以下→短期底，可轻仓博反弹")
    tomorrow.append("若明天继续300+跌停→系统性风险升级，必须大幅减仓")
elif net < -50:
    tomorrow.append("明天大概率惯性下探，关注10:00前跌停数是否收敛")
if main_line:
    tomorrow.append(f"若反弹，资金大概率回流{'/'.join(main_line[:3])}")
if escape_from:
    tomorrow.append(f"规避{'/'.join(escape_from[:3])}方向，资金撤离趋势未结束")
if not tomorrow:
    tomorrow.append("市场方向不明，等明天早盘信号")

# ===== 一句话总结 =====
if emotion_score > 20:
    summary = f"市场偏暖，{up_count}个板块上涨，资金净流入{net:.0f}亿。主线在{'/'.join(main_line[:3])}。"
elif emotion_score > -20:
    summary = f"市场震荡分化，{up_count}涨{down_count}跌，净流向{net:+.0f}亿。无明确主线，观望。"
else:
    summary = f"市场偏弱，{down_count}个板块下跌，净流出{abs(net):.0f}亿。{dt_total}只跌停。防御为主。"

# ===== 输出 =====
result = {
    "date": today,
    "updated": datetime.now().strftime('%H:%M'),
    "summary": summary,
    "direction": direction,
    "direction_desc": direction_desc,
    "emotion_score": round(emotion_score),
    "market": {
        "sectors_total": len(all_list),
        "up": up_count, "down": down_count, "flat": flat_count,
        "net_flow": round(net),
        "total_in": round(total_in),
        "total_out": round(abs(total_out)),
        "limit_up": zt_total,
        "limit_down": dt_total,
        "dt_gem": dt_300,
        "dt_star": dt_688,
    },
    "style_rotation": {
        "leading": leading_style[0],
        "styles": {k: v for k, v in sorted(style_scores.items(), key=lambda x: x[1]['inflow'] - x[1]['outflow'], reverse=True)},
        "main_line": main_line,
        "escape_from": escape_from,
    },
    "top_movers": {
        "gainers": [{"name": n, "chg": round(c, 1), "flow": round(f, 1)} for n, f, c in top_gainers],
        "losers": [{"name": n, "chg": round(c, 1), "flow": round(f, 1)} for n, f, c in top_losers],
    },
    "risks": risks,
    "actions": actions,
    "portfolio_actions": portfolio_actions,
    "tomorrow": tomorrow,
    "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
}

out_path = os.path.join(DATA_DIR, f'ai_analysis-{today}.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"✅ AI分析已生成: {out_path}")
print(f"   市场方向: {direction} (评分{emotion_score:.0f})")
print(f"   净流向: {net:+.0f}亿 | 跌停{dt_total}只")
print(f"   主导风格: {leading_style[0]}")
print(f"   主线: {', '.join(main_line[:4])}")
