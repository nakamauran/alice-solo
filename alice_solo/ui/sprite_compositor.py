"""立ち絵の読み込みと背丈の正規化。仕様書 v2.0 §8.1-8.2, §8.4。

現行パックの差分はすべて「全身1枚の special_pose」なので、合成は
実質「どのファイルを出すか」の解決になる。face_overlay を使う構造は
将来のために残してある。

**背丈の正規化は base 1枚の中身高さだけを基準にする。**
差分ごとに測ると、ポーズによって中身の高さが違うため、感情が変わる
たびにキャラが伸縮する（koyuki では sad 1110 / sleepy 972 で14%差）。
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import yaml
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from .. import config as C


class SpriteCompositor:
    def __init__(self, pack_dir: Path):
        self.pack_dir = Path(pack_dir)
        self.sprites_dir = self.pack_dir / "sprites"
        self.layout = self._load_layout()

        self.base_file: str = self.layout.get("base", {}).get("file", "")
        self.special: dict = self.layout.get("special_pose") or {}
        self.face: dict = self.layout.get("face_overlay") or {}
        self.blink: dict = self.layout.get("blink") or {}
        self.status: dict = self.layout.get("status_pose") or {}
        self.talking_file: str = (self.layout.get("talking_pose") or {}).get("file", "")

        self.base_content_height: float = float(
            self.layout.get("base_content_height") or 0.0
        )
        self._cache: OrderedDict[tuple[str, int], QPixmap] = OrderedDict()
        self._scale_ratio: float | None = None

    # ------------------------------------------------------------ レイアウト

    def _load_layout(self) -> dict:
        path = self.sprites_dir / "layout.yaml"
        if not path.exists():
            raise FileNotFoundError(f"layout.yaml が見つかりません: {path}")
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    # ------------------------------------------------------------ 解決

    def resolve_file(self, category: str, talking: bool = False,
                     status: str | None = None) -> str:
        """表示すべきファイル名を決める。未登録キーは base に落とす。"""
        if status:
            entry = self.status.get(status)
            if entry and entry.get("file"):
                return entry["file"]

        # 発話中はカテゴリに関わらず口の開いた絵にする（§6.2）。
        # 以前はニュートラル限定だったので、喜んでいる最中に口が動かなかった。
        if talking and self.talking_file:
            return self.talking_file

        entry = self.special.get(category)
        if entry and entry.get("file"):
            return entry["file"]

        return self.base_file

    # ------------------------------------------------------------ 倍率

    def content_scale(self) -> float:
        """base の中身高さを基準にした正規化倍率。パック全体で1つ。"""
        if self._scale_ratio is not None:
            return self._scale_ratio

        h = self.base_content_height
        if h <= 0:
            # layout.yaml に書かれていなければ base を実測する（後方互換）
            h = self._measure_content_height(self.base_file) or C.REFERENCE_CONTENT_HEIGHT
            self.base_content_height = h

        self._scale_ratio = C.REFERENCE_CONTENT_HEIGHT / h
        return self._scale_ratio

    def _measure_content_height(self, filename: str) -> float:
        path = self.sprites_dir / filename
        if not path.exists():
            return 0.0
        img = QPixmap(str(path)).toImage()
        if img.isNull():
            return 0.0
        top, bottom = None, None
        for y in range(img.height()):
            row_has = False
            for x in range(0, img.width(), 2):      # 2px 飛ばしで十分
                if img.pixelColor(x, y).alpha() > 0:
                    row_has = True
                    break
            if row_has:
                if top is None:
                    top = y
                bottom = y
        if top is None or bottom is None:
            return 0.0
        return float(bottom - top + 1)

    # ------------------------------------------------------------ 取得

    def has_blink(self) -> bool:
        """瞬き用の素材があるか。無ければ瞬きは出さない。"""
        return bool(self.blink.get("file"))

    def pixmap(self, category: str, talking: bool = False,
               status: str | None = None, user_scale: float = 1.0,
               blinking: bool = False) -> QPixmap:
        """表示用の QPixmap。LRU で最大 SPRITE_CACHE_SIZE 枚だけ保持する。"""
        filename = self.resolve_file(category, talking, status)
        total = self.content_scale() * max(C.SCALE_MIN, min(C.SCALE_MAX, user_scale))
        # 顔パーツと瞬きは重ねる絵が変わるので、キャッシュの鍵に入れる
        parts = self._face_parts(category, talking, status, blinking)
        key = (filename, int(round(total * 1000)), tuple(sorted(parts)))

        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit

        path = self.sprites_dir / filename
        pm = QPixmap(str(path))
        if parts and not pm.isNull():
            pm = self._compose_face(pm, parts)
        if pm.isNull():
            pm = QPixmap(1, 1)
            pm.fill(Qt.transparent)
        else:
            w = max(1, int(pm.width() * total))
            h = max(1, int(pm.height() * total))
            pm = pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        self._cache[key] = pm
        while len(self._cache) > C.SPRITE_CACHE_SIZE:
            self._cache.popitem(last=False)
        return pm

    def clear_cache(self) -> None:
        self._cache.clear()

    # ------------------------------------------------------------ 顔パーツ

    def _face_parts(self, category: str, talking: bool, status: str | None,
                    blinking: bool) -> list[str]:
        """重ねる顔パーツのファイル名。素材が無ければ空。

        全身差し替え（special_pose）が当たっているときは重ねない。
        顔つきが二重になるため。
        """
        if status or (talking and self.talking_file):
            return []
        if self.special.get(category, {}).get("file"):
            return []

        out: list[str] = []
        entry = self.face.get(category) or {}
        for slot in ("eyes", "mouth"):
            name = entry.get(slot)
            if name:
                out.append(name)

        if blinking and self.blink.get("file"):
            # 瞬きは目を上書きする。目のパーツが既にあれば差し替える。
            out = [n for n in out if n != entry.get("eyes")]
            out.insert(0, self.blink["file"])
        return out

    def _compose_face(self, base: QPixmap, parts: list[str]) -> QPixmap:
        """base の上に顔パーツを重ねる。座標は layout.yaml の指定に従う。"""
        from PySide6.QtGui import QPainter

        out = QPixmap(base)
        painter = QPainter(out)
        for name in parts:
            path = self.sprites_dir / name
            if not path.exists():
                continue
            part = QPixmap(str(path))
            if part.isNull():
                continue
            pos = (self.layout.get("face_pos") or {}).get(name) or {}
            painter.drawPixmap(int(pos.get("x", 0)), int(pos.get("y", 0)), part)
        painter.end()
        return out
