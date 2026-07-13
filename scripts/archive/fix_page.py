# Fix backtest page: add strategy column + filter
import re
f = open('C:/Users/admin/aazhous-projects/atlas-ai/crypto/index.html', 'r', encoding='utf-8').read()

# 1. Add strategy to column definitions (after symbol opening)
f = f.replace(
    "var cols = [\n    {k:'symbol',l:'币种'},",
    "var cols = [\n    {k:'strategy',l:'策略'},\n    {k:'symbol',l:'币种'},"
)

# 2. Add strategy cell in row rendering (before symbol cell)
old_row = "<td><b class=\"ink\">'+r.symbol+'</b></td>"
new_row = "<td style=\"font-size:10px;color:var(--muted-soft)\">'+(r.strategy||'')+'</td>" + old_row
f = f.replace(old_row, new_row)

# 3. Add strategy filter buttons
old_pills = "{k:'all',l:'全部'},{k:'win',l:'胜率≥60%'},{k:'lose',l:'胜率<60%'}"
new_pills = "{k:'all',l:'全部'},{k:'funding_extreme',l:'费率极值'},{k:'multifactor',l:'多因子'},{k:'win',l:'胜率≥60%'},{k:'lose',l:'胜率<60%'}"
f = f.replace(old_pills, new_pills)

# 4. Add strategy filter logic
old_filter = "if (f === 'win') filtered = sorted.filter(function(r){ return r.win_rate >= 60; });\n  if (f === 'lose') filtered = sorted.filter(function(r){ return r.win_rate < 60; });"
new_filter = "if (f === 'funding_extreme') filtered = sorted.filter(function(r){ return r.strategy === 'funding_extreme'; });\n  if (f === 'multifactor') filtered = sorted.filter(function(r){ return r.strategy === 'multifactor'; });\n  if (f === 'win') filtered = sorted.filter(function(r){ return r.win_rate >= 60; });\n  if (f === 'lose') filtered = sorted.filter(function(r){ return r.win_rate < 60; });"
f = f.replace(old_filter, new_filter)

# 5. Fix colspan (added one column)
f = f.replace('colspan="8"', 'colspan="9"')

open('C:/Users/admin/aazhous-projects/atlas-ai/crypto/index.html', 'w', encoding='utf-8').write(f)
print('All fixes applied')
