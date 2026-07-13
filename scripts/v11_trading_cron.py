"""
V11 模拟交易引擎 + 自动部署
"""
import subprocess, sys, os, shutil

BASE = r'C:\Users\admin\aazhous-projects\atlas-ai'
PYTHON = r'C:\Python314\python'
VERCEL = shutil.which('vercel') or r'C:\Users\admin\AppData\Roaming\npm\vercel.cmd'

try:
    # 1. Run trading engine
    r = subprocess.run([PYTHON, os.path.join(BASE, 'scripts', 'v11_sim_trading.py')],
                       capture_output=True, text=True, cwd=BASE, timeout=60)
    
    output = (r.stdout + r.stderr).strip()
    has_change = 'OPEN' in output or 'CLOSE' in output
    
    if has_change:
        print(output)
        # 2. Deploy
        r2 = subprocess.run([VERCEL, '--prod', '--yes'],
                           capture_output=True, text=True, cwd=BASE, timeout=60)
        if r2.returncode == 0:
            print('Deploy OK')
        else:
            print(f'Deploy FAIL: {r2.stderr[-200:]}')
    # else: silent
    
    sys.exit(0)
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)
