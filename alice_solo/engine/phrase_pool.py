"""発話プール。仕様書 v2.0 §4.5。

YAML を入れ子辞書として読み、キーの道をたどって候補から1つ選ぶ。
層（guard / accept / empathy）ごとに差し替えられ、書かれていないキーは
accept -> shared の順に落ちる。パック作者が3層ぶん全部を書かなくてよい。
"""
from __future__ import annotations

import random
from collections import deque
from pathlib import Path
from typing import Any

import yaml

from .. import config as C


class MissingKeyWarning:
    """起動時検証の結果。落とさずに警告として集める。"""

    def __init__(self):
        self.missing: list[str] = []
        self.thin: list[tuple[str, int]] = []

    def __bool__(self) -> bool:
        return bool(self.missing or self.thin)

    def report(self) -> str:
        lines = []
        for k in self.missing:
            lines.append(f"  欠落: {k}")
        for k, n in self.thin:
            lines.append(f"  候補不足（{n}件、{C.PHRASE_MIN_COUNT}件以上）: {k}")
        return "\n".join(lines)


# 検証対象の必須キー（tiers.accept に揃っていること）
REQUIRED_TIER_KEYS = (
    "greeting",
    "greeting_slot.morning", "greeting_slot.night", "greeting_slot.late",
    "idle_lonely",
    *[f"emotion_response.{c}" for c in C.EMOTION_CATEGORIES],
    "mood.genki", "mood.jougen", "mood.futsuu", "mood.darui", "mood.shizumi",
)


def _dig(node: Any, path: str) -> Any:
    cur = node
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


class PhrasePool:
    def __init__(self, yaml_path: Path, rng: random.Random | None = None):
        self.path = Path(yaml_path)
        self.rng = rng or random.Random()
        with self.path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            data = {}
        self.shared: dict = data.get("shared") or {}
        self.tiers: dict = data.get("tiers") or {}
        if not isinstance(self.shared, dict):
            self.shared = {}
        if not isinstance(self.tiers, dict):
            self.tiers = {}
        self._history: dict[str, deque] = {}

    # ------------------------------------------------------------ 探索

    def candidates(self, key_path: str, tier: str) -> list[str]:
        """層 -> 既定層 -> shared の順にたどって候補リストを返す。"""
        for node in (self.tiers.get(tier),
                     self.tiers.get(C.DEFAULT_TIER),
                     self.shared):
            found = _dig(node, key_path)
            if isinstance(found, list) and found:
                return [str(x) for x in found]
            if isinstance(found, str) and found:
                return [found]
        return []

    def has(self, key_path: str, tier: str) -> bool:
        return bool(self.candidates(key_path, tier))

    # ------------------------------------------------------------ 抽選

    def pick(self, key_path: str, tier: str = C.DEFAULT_TIER, **fields) -> str | None:
        """候補から1つ選び、差し込みを適用して返す。無ければ None。"""
        pool = self.candidates(key_path, tier)
        if not pool:
            return None

        hist = self._history.setdefault(f"{tier}:{key_path}", deque())
        maxlen = max(1, min(8, len(pool) - 1))
        if hist.maxlen != maxlen:
            hist = deque(hist, maxlen=maxlen)
            self._history[f"{tier}:{key_path}"] = hist

        fresh = [p for p in pool if p not in hist]
        if not fresh:
            # 全部出きったら履歴を捨てる。ただし直前の1つだけは必ず避ける。
            last = hist[-1] if hist else None
            fresh = [p for p in pool if p != last] or list(pool)
            hist.clear()

        chosen = self.rng.choice(fresh)
        hist.append(chosen)
        return self._format(chosen, fields)

    @staticmethod
    def _format(text: str, fields: dict) -> str:
        """未定義の変数は空文字にする。台詞の書き間違いで落とさない。"""
        class _Blank(dict):
            def __missing__(self, key):   # noqa: D105
                return ""
        try:
            return text.format_map(_Blank(fields))
        except (ValueError, IndexError, AttributeError, KeyError):
            return text

    # ------------------------------------------------------------ 検証

    def validate(self) -> MissingKeyWarning:
        w = MissingKeyWarning()
        accept = self.tiers.get(C.DEFAULT_TIER) or {}
        for key in REQUIRED_TIER_KEYS:
            found = _dig(accept, key)
            if isinstance(found, str) and found:
                # 文字列1件でも有効な候補
                continue
            if not isinstance(found, list) or not found:
                # shared にあれば欠落とはしない（文字列も有効）
                shared_found = _dig(self.shared, key)
                if isinstance(shared_found, list) and shared_found:
                    continue
                if isinstance(shared_found, str) and shared_found:
                    continue
                w.missing.append(f"tiers.{C.DEFAULT_TIER}.{key}")
                continue
            if len(found) < C.PHRASE_MIN_COUNT:
                w.thin.append((f"tiers.{C.DEFAULT_TIER}.{key}", len(found)))
        return w
