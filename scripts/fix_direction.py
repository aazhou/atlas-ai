import re
f = open('C:/Users/admin/aazhous-projects/atlas-ai/crypto/index.html', 'r').read()

# Add direction column in header
old = '<th>币种</th><th>费率</th><th>入场</th>'
new = '<th>币种</th><th>方向</th><th>费率</th><th>入场</th>'
f = f.replace(old, new)

# Add direction cell in row
old2 = "<td><b class=\"ink\">'+sg.symbol+'</b></td>"
new2 = "<td><b class=\"ink\">'+sg.symbol+'</b></td><td style=\"font-size:11px\">'+(sg.direction||'LONG')+'</td>"
f = f.replace(old2, new2)

open('C:/Users/admin/aazhous-projects/atlas-ai/crypto/index.html', 'w').write(f)
print('done')
