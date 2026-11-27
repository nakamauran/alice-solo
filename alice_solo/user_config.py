"""ユーザ設定（%APPDATA%/Alice/user_config.json）の読み書き。

同梱の assets/config.yaml は既定値であり実行時に書き換えない。
利用者が変えてよい値だけをこのファイルに持つ。設定画面は
ここを読み書きする。初回起動時に既定値で作成するので、設定画面が
出来るまでは利用者がこのファイルを直接編集できる。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from . import config as C

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "character_pack": "koyuki",
    "display_name": None,        # None ならキャラクターパックの値を使う
    "first_person": None,        # 同上
    "scale": C.SCALE_DEFAULT,    # 立ち絵の表示倍率 0.2-3.0
    "hud_visible": True,
    "mailbox_scale": 1.0,
    "mailbox_icon_mode": "always",   # always / unread_only（§8）
    "first_run_done": False,         # 初回ガイドを出したか（§8）
    "autostart": False,
    # 初期値は東京だが「利用者がまだ選んでいない」ことを別に持つ。
    # 黙って東京の天気を答え続けるのを避けるため。
    "weather_configured": False,
    "weather": {
        "label": "東京都",
        "latitude": 35.6895,
        "longitude": 139.6917,
    },
}


class UserConfig:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else C.USER_CONFIG_FILE
        self.data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            data = json.loads(json.dumps(DEFAULTS))   # 深いコピー
            self._write(data)
            return data
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        # 欠けたキーは既定値で埋める（バージョン上げでキーが増えても壊れない）
        data = json.loads(json.dumps(DEFAULTS))
        for k, v in raw.items():
            if isinstance(v, dict) and isinstance(data.get(k), dict):
                data[k].update(v)
            else:
                data[k] = v
        return data

    def _write(self, data: dict) -> None:
        tmp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False, indent=2))
            os.replace(tmp, self.path)
            tmp = None
        except OSError as e:
            logger.warning("user_config.json の書き込みに失敗しました: %s", e)
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def save(self) -> None:
        self._write(self.data)

    # ------------------------------------------------------------ 参照

    def get(self, key: str, fallback: Any = None) -> Any:
        return self.data.get(key, fallback)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

    @property
    def scale(self) -> float:
        try:
            v = float(self.data.get("scale", C.SCALE_DEFAULT))
        except (TypeError, ValueError):
            return C.SCALE_DEFAULT
        return max(C.SCALE_MIN, min(C.SCALE_MAX, v))

    @property
    def mailbox_scale(self) -> float:
        """郵便受けアイコンの表示倍率。scale と同じ 0.2〜3.0 で検証・クランプする。"""
        try:
            v = float(self.data.get("mailbox_scale", 1.0))
        except (TypeError, ValueError):
            return 1.0
        return max(C.SCALE_MIN, min(C.SCALE_MAX, v))

    @property
    def character_pack(self) -> str:
        return str(self.data.get("character_pack") or "koyuki")
