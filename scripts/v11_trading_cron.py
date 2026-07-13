"""
V11 模拟交易引擎 + GitHub Pages 部署
"""
import subprocess, sys, os

BASE = r'C:\Users\admin\aazhous-projects\atlas-ai'
PYTHON = r'C:\Python314\python'

try:
    r = subprocess.run([PYTHON, os.path.join(BASE, 'scripts', 'v11_sim_trading.py')],
                       capture_output=True, text=True, cwd=BASE, timeout=60)
    
    output = (r.stdout + r.stderr).strip()
    has_change = 'OPEN' in output or 'CLOSE' in output
    
    if has_change:
        print(output)
        subprocess.run(['git', 'add', '-A'], cwd=BASE, capture_output=True, timeout=10)
        subprocess.run(['git', 'commit', '-m', 'auto: crypto trading update'], cwd=BASE, capture_output=True, timeout=10)
        r2 = subprocess.run(['git', 'push'], cwd=BASE, capture_output=True, text=True, timeout=30)
        if r2.returncode == 0:
            print('Git push OK')
        else:
            print(f'Push FAIL: {r2.stderr[-200:]}')
    
    sys.exit(0)
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)
