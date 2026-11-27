#!/usr/bin/env python3
"""tests/ をまとめて実行する。

pytest は使っていない。各テストは単体で走る素のスクリプトで、
終了コードと「N passed, M failed」の行で結果を返す。

使い方:
    python tools/run_tests.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = sorted((ROOT / "tests").glob("test_*.py"))


def main() -> int:
    env = dict(os.environ)
    # UI のテストが画面を開かないようにする
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    total_pass = total_fail = 0
    failed_files: list[str] = []

    for path in TESTS:
        proc = subprocess.run(
            [sys.executable, "-I", str(path)],
            capture_output=True, text=True, env=env,
        )
        out = proc.stdout + proc.stderr
        m = re.search(r"(\d+) passed, (\d+) failed", out)
        if m:
            passed, failed = int(m.group(1)), int(m.group(2))
        else:
            passed, failed = 0, 1
            out += "\n（結果の行が見つかりませんでした）"

        total_pass += passed
        total_fail += failed
        mark = "OK  " if failed == 0 and proc.returncode == 0 else "FAIL"
        print(f"{mark} {path.name:20} {passed:3d} passed, {failed} failed")

        if failed or proc.returncode:
            failed_files.append(path.name)
            for line in out.splitlines():
                if "FAIL" in line or "Error" in line or "Traceback" in line:
                    print(f"       {line}")

    print(f"\n合計 {total_pass} passed, {total_fail} failed")
    if failed_files:
        print("失敗:", ", ".join(failed_files))
    return 1 if total_fail or failed_files else 0


if __name__ == "__main__":
    raise SystemExit(main())
