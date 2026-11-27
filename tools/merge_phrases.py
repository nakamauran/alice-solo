#!/usr/bin/env python3
"""発話プールの追加分を phrases.yaml にマージする。

既存のリストを置き換えず、末尾に「追加」する。既に同じ文が入っている
場合は足さないので、何度流しても増えない（べき等）。

使い方:
    python3 tools/merge_phrases.py [--check]

    --check を付けると、書き込まずに結果だけ出す。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "assets" / "characters" / "koyuki" / "phrases.yaml"
SOURCES = [
    ROOT / "docs" / "phrases-additions.yaml",
    ROOT / "docs" / "phrases-additions-2.yaml",
]


def merge(base: dict, add: dict, path: str = "") -> tuple[int, int]:
    """add の内容を base に足す。(足した数, 重複で飛ばした数) を返す。"""
    added = skipped = 0
    for key, value in add.items():
        here = f"{path}.{key}" if path else key
        if isinstance(value, dict):
            node = base.setdefault(key, {})
            if not isinstance(node, dict):
                print(f"  !! {here}: 既存が辞書ではない。飛ばす", file=sys.stderr)
                continue
            a, s = merge(node, value, here)
            added += a
            skipped += s
        elif isinstance(value, list):
            node = base.setdefault(key, [])
            if not isinstance(node, list):
                print(f"  !! {here}: 既存がリストではない。飛ばす", file=sys.stderr)
                continue
            for line in value:
                if line in node:
                    skipped += 1
                else:
                    node.append(line)
                    added += 1
        else:
            base.setdefault(key, value)
    return added, skipped


def count_lines(node) -> int:
    if isinstance(node, dict):
        return sum(count_lines(v) for v in node.values())
    if isinstance(node, list):
        return len(node)
    return 0


def find_thin(node, minimum: int, path: str = "") -> list[tuple[str, int]]:
    """件数が足りないリストを探す。"""
    out: list[tuple[str, int]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out += find_thin(v, minimum, f"{path}.{k}" if path else k)
    elif isinstance(node, list) and len(node) < minimum:
        out.append((path, len(node)))
    return out


def find_duplicates(node, path: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out += find_duplicates(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list) and len(node) != len(set(node)):
        out.append(path)
    return out


def main() -> int:
    check_only = "--check" in sys.argv

    base = yaml.safe_load(TARGET.read_text(encoding="utf-8")) or {}
    before = count_lines(base)

    total_added = total_skipped = 0
    for src in SOURCES:
        if not src.exists():
            continue
        add = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
        a, s = merge(base, add, "")
        print(f"{src.name}: 追加 {a} 件 / 重複で飛ばし {s} 件")
        total_added += a
        total_skipped += s

    after = count_lines(base)
    print(f"合計: {before} -> {after} 行（追加 {total_added} / 飛ばし {total_skipped}）")

    dups = find_duplicates(base)
    print(f"重複のあるキー: {dups or 'なし'}")

    thin = find_thin(base.get("tiers", {}).get("accept", {}), 5, "tiers.accept")
    thin += find_thin(base.get("shared", {}), 5, "shared")
    if thin:
        print("5件に満たないキー:")
        for k, n in sorted(thin):
            print(f"  {k}: {n}件")
    else:
        print("5件に満たないキー: なし")

    if check_only:
        return 0

    TARGET.write_text(
        yaml.safe_dump(base, allow_unicode=True, sort_keys=False, width=200,
                       default_flow_style=False),
        encoding="utf-8",
    )
    print(f"書き込みました: {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
