"""HUD。PC状態と再生中の曲。仕様書 v2.0 §9.2。

原型の hud_window.py は CONTROL のジョブ表示や音楽操作を抱えていたが、
Solo 版はどちらも無いので、計測値の表示だけに絞ってある。
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from .dwm import apply_dwm_fixes
from .screen_layout import clamp_point
from .. import config as C
from ..engine.self_engine import calendar_ja as cal
from .theme import load_theme

# 層とその日本語表示。値そのものより「どのくらい打ち解けたか」を見せる。
TIER_LABELS = {"guard": "まだ慣れてない", "accept": "慣れてきた", "empathy": "仲良し"}
MOOD_LABELS = {"genki": "元気", "jougen": "上機嫌", "futsuu": "ふつう",
               "darui": "だるい", "shizumi": "しずみ"}
TIER_NEXT = {"guard": ("accept", C.TIER_UP_ACCEPT),
             "accept": ("empathy", C.TIER_UP_EMPATHY)}


def _warn_color() -> str:
    return load_theme().get("warn", "#b4453c")


class _Gauge(QtWidgets.QWidget):
    """1項目ぶんの行。ラベル・バー・数値。"""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.name = QtWidgets.QLabel(label, self)
        self.name.setFixedWidth(44)

        self.bar = QtWidgets.QProgressBar(self)
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)

        self.value = QtWidgets.QLabel("--%", self)
        self.value.setFixedWidth(52)
        self.value.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.name)
        row.addWidget(self.bar, 1)
        row.addWidget(self.value)

    def set_color(self, color: str) -> None:
        """バーの色を外から決める。好感度は層で色を変えるため。"""
        self.bar.setStyleSheet(
            f"QProgressBar {{ background: rgba(0,0,0,24); border-radius: 5px; }}"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 5px; }}"
        )

    def update_value(
        self, percent: float | None, healthy: bool, theme: dict | None = None
    ) -> None:
        if percent is None:
            self.bar.setValue(0)
            self.bar.setStyleSheet("")
            self.value.setText("--%")
            self.value.setStyleSheet("")
            return
        self.bar.setValue(int(percent))
        self.value.setText(f"{percent:.0f}%")
        self.value.setStyleSheet("" if healthy else f"color: {_warn_color()};")
        accent = (theme or load_theme()).get("accent_border", "#f1b7a8")
        color = accent if healthy else _warn_color()
        self.bar.setStyleSheet(
            f"QProgressBar {{ background: rgba(0,0,0,24); border-radius: 5px; }}"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 5px; }}"
        )


class HUDWindow(QtWidgets.QWidget):
    def __init__(self, pc_monitor, media_watcher,
                 affinity=None, mood=None, likes=None):
        super().__init__(None)
        self.pc = pc_monitor
        self.media = media_watcher
        self.affinity = affinity
        self.mood = mood
        self.likes = likes

        self.setWindowTitle("HUD")
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.resize(C.HUD_WIDTH, C.HUD_HEIGHT)

        # テーマは毎回 load_theme() せず、ここにキャッシュする
        self._theme = load_theme()

        self.frame = QtWidgets.QFrame(self)
        self.frame.setObjectName("hudFrame")

        self.title = QtWidgets.QLabel("診断", self.frame)
        self.gauges = {
            "cpu": _Gauge("CPU", self.frame),
            "mem": _Gauge("Mem", self.frame),
            "disk": _Gauge("Disk", self.frame),
        }

        # 自我エンジンの見える化（§4）。数字が動くのが見えないと
        # 「育てている」実感が出ない。
        self.self_sep = QtWidgets.QFrame(self.frame)
        self.self_sep.setFrameShape(QtWidgets.QFrame.HLine)
        self.affinity_gauge = _Gauge("なかよし", self.frame)
        self.mood_label = QtWidgets.QLabel("気分：—", self.frame)
        self.likes_label = QtWidgets.QLabel("好き：—", self.frame)

        self.sep = QtWidgets.QFrame(self.frame)
        self.sep.setFrameShape(QtWidgets.QFrame.HLine)

        self.np_title = QtWidgets.QLabel("Now Playing", self.frame)
        self.np_text = QtWidgets.QLabel("—", self.frame)
        self.np_text.setWordWrap(True)

        inner = QtWidgets.QVBoxLayout(self.frame)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.setSpacing(4)
        inner.addWidget(self.title)
        for g in self.gauges.values():
            inner.addWidget(g)
        inner.addWidget(self.self_sep)
        inner.addWidget(self.affinity_gauge)
        inner.addWidget(self.mood_label)
        inner.addWidget(self.likes_label)
        inner.addWidget(self.sep)
        inner.addWidget(self.np_title)
        inner.addWidget(self.np_text)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.frame)

        # SMTC が使えない環境では Now Playing の欄ごと隠す
        if not getattr(self.media, "available", False):
            self._hide_now_playing()

        self._drag_offset: QtCore.QPoint | None = None
        self._apply_frame_style()
        self._restore_position()
        self.refresh()

    # ------------------------------------------------------------ 表示

    def _apply_frame_style(self) -> None:
        t = self._theme
        self.frame.setStyleSheet(
            f"#hudFrame {{ background: {t['background']};"
            f" border: 1px solid {t['accent_border']}; border-radius: 10px; }}"
        )

    def refresh_theme(self) -> None:
        """配色が変わったときにだけ呼ぶ。テーマを読み直して反映する。"""
        self._theme = load_theme()
        self._apply_frame_style()
        self.refresh()

    def _hide_now_playing(self) -> None:
        self.sep.hide()
        self.np_title.hide()
        self.np_text.hide()
        self.adjustSize()

    def refresh(self) -> None:
        snap = self.pc.snapshot() or {}
        diag = snap.get("diagnostics", {})
        for key, gauge in self.gauges.items():
            gauge.update_value(
                snap.get(key), bool(diag.get(key, True)), theme=self._theme
            )

        self._refresh_self()

        if getattr(self.media, "available", False):
            text = self.media.display_text()
            self.np_text.setText(text or "—")
        elif self.np_title.isVisible():
            self._hide_now_playing()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_dwm_fixes(int(self.winId()))

    def _refresh_self(self) -> None:
        """好感度・気分・好きなものを書き換える。読み取りのみ。"""
        if self.affinity is not None:
            value = float(self.affinity.value)
            tier = self.affinity.tier
            self.affinity_gauge.update_value(value, True)
            nxt = TIER_NEXT.get(tier)
            if nxt:
                rest = max(0.0, nxt[1] - value)
                text = f"{value:.1f}（あと {rest:.1f}）"
            else:
                text = f"{value:.1f}（{TIER_LABELS.get(tier, tier)}）"
            self.affinity_gauge.value.setText(text)
            self.affinity_gauge.value.setFixedWidth(118)
            self.affinity_gauge.name.setToolTip(
                f"いまは「{TIER_LABELS.get(tier, tier)}」"
            )
            self.affinity_gauge.set_color(self._tier_color(tier))

        if self.mood is not None:
            self.mood_label.setText(
                f"気分：{MOOD_LABELS.get(self.mood.label, self.mood.label)}"
            )

        if self.likes is not None:
            self.likes_label.setText(f"好き：{self._favorite()}")

    @staticmethod
    def _mix(a: str, b: str, ratio: float) -> str:
        """2色を混ぜる。ratio が 0 で a、1 で b。"""
        def rgb(c: str) -> tuple[int, int, int]:
            c = c.lstrip("#")
            if len(c) == 3:
                c = "".join(ch * 2 for ch in c)
            return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        ar, ag, ab = rgb(a)
        br, bg, bb = rgb(b)
        m = lambda x, y: int(round(x + (y - x) * ratio))
        return f"#{m(ar, br):02x}{m(ag, bg):02x}{m(ab, bb):02x}"

    @classmethod
    def _tier_color(cls, tier: str) -> str:
        """層が進むほど濃くなる。

        accent_border / highlight をそのまま当てると、テーマによっては
        バーの地と同じ色になって見えなくなる（こゆきの guard が顕著）。
        accent を surface 側へ薄めて作ることで、どのテーマでも段差が出る。
        """
        t = load_theme()
        accent = t.get("accent", "#f1b7a8")
        surface = t.get("surface", t.get("background", "#ffffff"))
        return {
            "guard": cls._mix(accent, surface, 0.55),
            "accept": cls._mix(accent, surface, 0.25),
            "empathy": accent,
        }.get(tier, accent)

    def _favorite(self) -> str:
        """いちばん好きなもの。まだ何も傾いていなければそう言う。"""
        try:
            likes = self.likes.data.get("likes") or {}
            born = getattr(self.likes, "born", {}) or {}
            merged = {**born, **likes}
            if not merged:
                return "まだ分からない"
            key, value = max(merged.items(), key=lambda kv: float(kv[1]))
            if float(value) <= 0.0:
                return "まだ分からない"
            return cal.label_of(key)
        except Exception:
            return "まだ分からない"

    # ------------------------------------------------------------ 操作

    def mousePressEvent(self, event) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & QtCore.Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, _event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self._save_position()

    # ------------------------------------------------------------ 位置

    @property
    def _pos_file(self):
        from .. import config as C
        return C.DATA_DIR / "hud_pos.json"

    def _save_position(self) -> None:
        from ..engine.self_engine import store
        store.write_json(self._pos_file, {"x": self.x(), "y": self.y()})

    def _restore_position(self) -> None:
        from ..engine.self_engine import store
        d = store.read_json(self._pos_file, {})
        try:
            x, y = clamp_point(
                int(d["x"]), int(d["y"]), self.width(), self.height()
            )
        except (KeyError, TypeError, ValueError):
            x = y = None
        if x is not None:
            self.move(x, y)
            return
        screen = QtWidgets.QApplication.primaryScreen()
        if screen:
            g = screen.availableGeometry()
            self.move(g.right() - self.width() - 40, g.top() + 40)

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
