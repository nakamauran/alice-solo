"""自我エンジン共通の土台。仕様書 v2.0 §4.4.1。

日付の境は朝5時。「今日」は現在時刻から5時間引いた日付を指す。
深夜2時に言ったことは前日ぶんとして扱われる。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ... import config as C


def today_key(now: datetime | None = None) -> str:
    """朝5時を境にした「今日」。YYYY-MM-DD。"""
    now = now or datetime.now()
    return (now - timedelta(hours=C.DAY_START_HOUR)).strftime("%Y-%m-%d")


def day_distance(a: str, b: str) -> int:
    """today_key 形式の2つの日付の差（日）。壊れていたら 0。"""
    try:
        da = datetime.strptime(a, "%Y-%m-%d")
        db = datetime.strptime(b, "%Y-%m-%d")
    except (TypeError, ValueError):
        return 0
    return (db - da).days


def read_json(path: Path, fallback: dict | None = None) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else dict(fallback or {})
    except (OSError, ValueError):
        return dict(fallback or {})


def write_json(path: Path, data: dict[str, Any]) -> None:
    """一時ファイル経由の原子置換。途中で落ちても壊れた JSON を残さない。"""
    path = Path(path)
    tmp: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        os.replace(tmp, path)
        tmp = None  # 置換済みのため一時ファイルはもう存在しない
    except Exception as e:  # OSError だけでなく json 化の失敗も含む
        logging.getLogger("alice").warning("write_json 失敗: %s: %s", path, e)
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
