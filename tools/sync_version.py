#!/usr/bin/env python3
"""バージョンを alice_solo/__init__.py から配布ファイルへ書き写す。

一元管理（仕様書 §10）のための小道具。spec は実行時に読むので
対象外。iss は定数なので、ここで書き換える。

使い方:
    python3 tools/sync_version.py            # 書き写す
    python3 tools/sync_version.py --check    # ずれていないか見るだけ
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "alice_solo" / "__init__.py"
ISS = ROOT / "alice-solo.iss"


def current_version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"',
                  INIT.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("__version__ が見つかりません")
    return m.group(1)


def main() -> int:
    version = current_version()
    print(f"alice_solo/__init__.py: {version}")

    text = ISS.read_text(encoding="utf-8")
    m = re.search(r'#define AppVersion\s+"([^"]+)"', text)
    if not m:
        print("alice-solo.iss に AppVersion がありません", file=sys.stderr)
        return 1

    if m.group(1) == version:
        print(f"alice-solo.iss:        {m.group(1)}（一致）")
        return 0

    if "--check" in sys.argv:
        print(f"alice-solo.iss:        {m.group(1)}（ずれています）", file=sys.stderr)
        return 1

    ISS.write_text(
        text.replace(m.group(0), f'#define AppVersion   "{version}"'),
        encoding="utf-8",
    )
    print(f"alice-solo.iss:        {m.group(1)} -> {version}（書き換えました）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
