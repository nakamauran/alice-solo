"""マスコット主窓。仕様書 v2.0 §8.5, §9.1-9.2。

透過・フレームレス・常に手前。ドラッグで移動、ホイールで拡大縮小、
右クリックでメニュー。吹き出しは別ウィンドウとして頭の上に出す。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QPoint, QRect, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtGui import QAction, QPainter, QPixmap, QColor, QFont
from PySide6.QtWidgets import QWidget, QMenu, QApplication

from .. import config as C
from ..engine.self_engine import store
from .dwm import apply_dwm_fixes
from .screen_layout import snap_point
from .theme import load_theme
from .screen_layout import clamp_point
from .sprite_compositor import SpriteCompositor


# ---------------------------------------------------------------- 吹き出し

class BubbleWindow(QWidget):
    """立ち絵の頭上に出る吹き出し。クリックを透過する。"""

    PADDING = 12
    RADIUS = 10
    MAX_WIDTH = 320
    SLACK = 4          # 採寸誤差の逃げ。これが無いと末尾が切れることがある
    MARGIN_ABOVE = 6   # 立ち絵の頭との間隔

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.Tool | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._text = ""
        self._border_color: str | None = None   # 層が上がった日だけ変える
        self._font = QFont()
        self._font.setPointSize(10)
        # 採寸と描画で同じフォントを使うこと。widget 既定のフォントで
        # 採寸すると実際より小さい矩形になり、末尾が切れる。
        self.setFont(self._font)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_text(self, text: str, anchor: QPoint, duration_ms: int) -> None:
        self._text = text or ""
        if not self._text:
            self.hide()
            return

        fm = QFontMetrics(self._font)
        flags = Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop
        rect = fm.boundingRect(
            QRect(0, 0, self.MAX_WIDTH, 10_000), flags, self._text
        )
        w = rect.width() + self.PADDING * 2 + self.SLACK
        h = rect.height() + self.PADDING * 2 + self.SLACK
        self.setFixedSize(w, h)
        x = anchor.x() - w // 2
        y = anchor.y() - h - self.MARGIN_ABOVE
        screen = QApplication.screenAt(anchor)
        if screen is not None:
            geom = screen.availableGeometry()
            if y < geom.top():
                # 頭上に収まらなければ立ち絵の下に出す
                y = anchor.y() + self.MARGIN_ABOVE
            x = max(geom.left(), min(x, geom.right() - w + 1))
            y = max(geom.top(), min(y, geom.bottom() - h + 1))
        self.move(x, y)
        self.update()
        self.show()
        self._hide_timer.start(duration_ms)

    def set_border_color(self, color: str | None) -> None:
        """枠の色。層が上がった日だけ変える（§4）。"""
        self._border_color = color
        self.update()

    def paintEvent(self, _event) -> None:
        theme = load_theme()
        bg = QColor(theme.get("surface", "#ffffff"))
        bg.setAlpha(235)
        border = QColor(self._border_color
                        or theme.get("accent_border", "#f1b7a8"))

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(border)
        p.setBrush(bg)
        rect = self.rect().adjusted(1, 1, -1, -1)
        p.drawRoundedRect(rect, self.RADIUS, self.RADIUS)
        p.setPen(QColor(theme.get("text", "#28282f")))
        p.setFont(self._font)
        p.drawText(
            self.rect().adjusted(self.PADDING, self.PADDING,
                                 -self.PADDING, -self.PADDING),
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
            self._text,
        )


# ---------------------------------------------------------------- 主窓

class VPetWindow(QWidget):
    def __init__(self, pack_dir: Path, user_scale: float = C.SCALE_DEFAULT):
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_menu)

        self.compositor = SpriteCompositor(pack_dir)
        # 表示倍率は user_config.json（設定）から受け取る。
        # ホイールでは変えない（誤操作で勝手に大きさが変わるのを防ぐ）。
        self.user_scale = max(C.SCALE_MIN, min(C.SCALE_MAX, float(user_scale)))
        self.category = "neutral"
        self.talking = False
        self.status: str | None = None

        self.bubble = BubbleWindow()
        self._drag_offset: QPoint | None = None
        self._pixmap: QPixmap = QPixmap()
        self._blinking = False
        self._blink_timer = QTimer(self)
        self._blink_timer.setSingleShot(True)
        self._blink_timer.timeout.connect(self._blink)
        self._blink_end = QTimer(self)
        self._blink_end.setSingleShot(True)
        self._blink_end.timeout.connect(self._blink_done)
        self._schedule_blink()

        # 外部から差し込むハンドラ（main.py が設定する）
        self.on_open_chat = None
        self.on_open_settings = None
        self.on_toggle_hud = None   # bool を受け取る
        self.hud_is_visible = None  # bool を返す
        self.on_open_mailbox = None
        self.on_open_diary = None
        self.on_open_notes = None
        self.on_open_timer = None
        self.on_open_debug = None
        self.on_open_config = None
        self.on_quit = None

        self._refresh_pixmap()
        self._restore_position()

    # ------------------------------------------------------------ 表示

    def _refresh_pixmap(self) -> None:
        self._pixmap = self.compositor.pixmap(
            self.category, talking=self.talking,
            status=self.status, user_scale=self.user_scale,
            blinking=self._blinking,
        )
        self.setFixedSize(self._pixmap.size())
        self.update()

    def set_category(self, category: str, talking: bool = False) -> None:
        if (category, talking) == (self.category, self.talking):
            return
        self.category = category
        self.talking = talking
        self._refresh_pixmap()

    def set_status(self, status: str | None) -> None:
        if status == self.status:
            return
        self.status = status
        self._refresh_pixmap()

    def say(self, text: str) -> None:
        anchor = QPoint(self.x() + self.width() // 2, self.y())
        self.bubble.show_text(text, anchor, C.utterance_display_ms(text))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pixmap)

        # 深夜は少し暗く・青く沈ませる（§6.3）。素材は増やさない。
        from ..engine.self_engine import calendar_ja as cal
        if cal.slot_of() == "late":
            r, g, b, a = C.LATE_OVERLAY_RGBA
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(r, g, b, a))
            p.drawRect(self.rect())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_dwm_fixes(int(self.winId()))

    # ------------------------------------------------------------ 瞬き

    def _schedule_blink(self) -> None:
        """次の瞬きまでの間隔をばらす。等間隔だと機械に見える。"""
        import random
        self._blink_timer.start(
            random.randint(C.BLINK_INTERVAL_MIN_MS, C.BLINK_INTERVAL_MAX_MS)
        )

    def _blink(self) -> None:
        # 喋っている間と考えている間は瞬かない（表情が競合するため）
        if self.talking or self.status:
            self._schedule_blink()
            return
        if not self.compositor.has_blink():
            self._schedule_blink()      # 素材が無ければ何もしない
            return
        self._blinking = True
        self._refresh_pixmap()
        self._blink_end.start(C.BLINK_DURATION_MS)

    def _blink_done(self) -> None:
        self._blinking = False
        self._refresh_pixmap()
        self._schedule_blink()

    # ------------------------------------------------------------ 操作

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            pos = event.globalPosition().toPoint() - self._drag_offset
            x, y = snap_point(pos.x(), pos.y(), self.width(), self.height())
            self.move(x, y)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self._save_position()
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and callable(self.on_open_chat):
            self.on_open_chat()

    def apply_scale(self, scale: float) -> None:
        """設定画面から倍率が変わったときに呼ぶ。"""
        new = max(C.SCALE_MIN, min(C.SCALE_MAX, float(scale)))
        if abs(new - self.user_scale) < 1e-9:
            return
        self.user_scale = new
        self.compositor.clear_cache()
        self._refresh_pixmap()

    def _open_menu(self, pos) -> None:
        menu = QMenu(self)

        act_chat = QAction("チャット", self)
        if callable(self.on_open_chat):
            act_chat.triggered.connect(lambda: self.on_open_chat())
        else:
            act_chat.setEnabled(False)
        menu.addAction(act_chat)

        menu.addSeparator()
        # HUD は開く/閉じるではなく「出す/しまう」の切り替えにする
        act_hud = QAction("HUD を表示", self)
        act_hud.setCheckable(True)
        if callable(self.hud_is_visible):
            act_hud.setChecked(bool(self.hud_is_visible()))
        if callable(self.on_toggle_hud):
            act_hud.toggled.connect(lambda on: self.on_toggle_hud(on))
        else:
            act_hud.setEnabled(False)
        menu.addAction(act_hud)

        entries = (
            ("郵便受け", "on_open_mailbox"),
            ("日記", "on_open_diary"),
            ("メモ", "on_open_notes"),
            ("タイマー", "on_open_timer"),
        )
        for label, attr in entries:
            handler = getattr(self, attr, None)
            a = QAction(label, self)
            if callable(handler):
                a.triggered.connect(lambda _=False, h=handler: h())
            else:
                a.setEnabled(False)
            menu.addAction(a)

        menu.addSeparator()
        if callable(self.on_open_debug):
            act_debug = QAction("デバッグ", self)
            act_debug.triggered.connect(lambda: self.on_open_debug())
            menu.addAction(act_debug)
        act_settings = QAction("設定", self)
        if callable(self.on_open_settings):
            act_settings.triggered.connect(lambda: self.on_open_settings())
        else:
            act_settings.setEnabled(False)
        menu.addAction(act_settings)

        act_config = QAction("設定ファイルを開く", self)
        if callable(self.on_open_config):
            act_config.triggered.connect(lambda: self.on_open_config())
        else:
            act_config.setEnabled(False)
        menu.addAction(act_config)

        menu.addSeparator()
        act_quit = QAction("終了", self)
        act_quit.triggered.connect(
            lambda: self.on_quit() if callable(self.on_quit) else QApplication.quit()
        )
        menu.addAction(act_quit)

        menu.exec(self.mapToGlobal(pos))

    # ------------------------------------------------------------ 位置

    def _save_position(self) -> None:
        self._write_json(C.WINDOW_POS_FILE, {"x": self.x(), "y": self.y()})

    def _restore_position(self) -> None:
        data = self._read_json(C.WINDOW_POS_FILE)
        try:
            x, y = clamp_point(
                int(data["x"]), int(data["y"]), self.width(), self.height()
            )
        except (KeyError, TypeError, ValueError):
            x = y = None
        if x is not None:
            self.move(x, y)
            return
        screen = QApplication.primaryScreen()
        if screen:
            g = screen.availableGeometry()
            self.move(g.right() - self.width() - 40, g.bottom() - self.height() - 40)

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        # アトミック化のため store.write_json に統一する
        store.write_json(path, data)
