#!/usr/bin/env python3
"""
加密Alpha雷达 v7 — 端到端流水线
  1. incremental_update.py: 拉最新数据追加到 DuckDB
  2. crypto_scanner.py: 纯 DuckDB 读取 + 信号扫描

用于 cron 触发，no_agent=true
"""
import subprocess
import sys
import os

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def run_step(name, script):
    print(f"\n{'='*50}", flush=True)
    print(f"  [{name}] {script}", flush=True)
    print(f"{'='*50}", flush=True)

    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, script)],
        capture_output=True, text=True,
        timeout=600,
    )

    # Print stderr (progress info)
    if result.stderr:
        sys.stderr.write(result.stderr)

    # Print stdout
    if result.stdout:
        sys.stdout.write(result.stdout)

    print(f"\n[{name}] exit={result.returncode}", flush=True)
    return result.returncode


def main():
    # Step 1: Incremental update (API calls → DuckDB)
    rc1 = run_step("INCR", "incremental_update.py")

    # Step 2: Scan (DuckDB read → signals.json)
    rc2 = run_step("SCAN", "crypto_scanner.py")

    # Exit with scanner's exit code (0=HIGH, 1=MEDIUM only, 2=empty)
    sys.exit(rc2)


if __name__ == "__main__":
    main()
