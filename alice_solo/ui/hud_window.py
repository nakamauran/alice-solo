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

# 端から何 px までをサイズ変更のつかみ代にするか
_RESIZE_MARGIN = 6
# 拡大・縮小の倍率の範囲（初期サイズを 1.0 とする）
_SCALE_MIN, _SCALE_MAX = 0.6, 2.5


def _warn_color() -> str:
    return load_theme().get("warn", "#b4453c")


class _Gauge(QtWidgets.QWidget):
    """1項目ぶんの行。ラベル・バー・数値。"""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.name_base = 44
        self.bar_base = 10
        self.value_base = 52
        self.name = QtWidgets.QLabel(label, self)
        self.name.setFixedWidth(self.name_base)

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

    def set_scale(self, f: float) -> None:
        """HUD の拡大・縮小に合わせて固定幅を変える。"""
        self.name.setFixedWidth(round(self.name_base * f))
        self.bar.setFixedHeight(max(4, round(self.bar_base * f)))
        # QProgressBar は既定の最小幅が大きく、縮小すると横がはみ出る
        self.bar.setMinimumWidth(round(24 * f))
        self.value.setFixedWidth(round(self.value_base * f))

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
        self._user_sized = False  # 先に用意（_hide_now_playing が参照する）

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
        self.affinity_gauge.value_base = 118
        self.affinity_gauge.set_scale(1.0)
        self.mood_label = QtWidgets.QLabel("気分：—", self.frame)
        self.likes_label = QtWidgets.QLabel("好き：—", self.frame)

        self.sep = QtWidgets.QFrame(self.frame)
        self.sep.setFrameShape(QtWidgets.QFrame.HLine)

        self.np_title = QtWidgets.QLabel("Now Playing", self.frame)
        self.np_text = QtWidgets.QLabel("—", self.frame)
        self.np_text.setWordWrap(True)

        inner = QtWidgets.QVBoxLayout(self.frame)
        self._inner = inner
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
        # 手動リサイズ（startSystemResize が使えない環境用）
        self._resize_edges = QtCore.Qt.Edges()
        self._resize_origin: tuple[QtCore.QPoint, QtCore.QRect] | None = None
        self._install_resize_watch()
        self._apply_frame_style()
        self.refresh()
        # 基準（倍率 1.0）のサイズと文字サイズ。これに対する比で拡大・縮小する。
        self._scale = 1.0
        self._base_pt = self.font().pointSizeF()
        self._base_size = self.size().expandedTo(self.minimumSizeHint())
        self.resize(self._base_size)
        self.setMinimumSize(self._base_size * _SCALE_MIN)
        self._restore_position()

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
        if not self._user_sized:
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

    # ------------------------------------------------------------ リサイズ

    def _install_resize_watch(self) -> None:
        """子ウィジェット上でも端を検出できるよう、全部にフィルタを付ける。"""
        for w in [self, *self.findChildren(QtWidgets.QWidget)]:
            w.setMouseTracking(True)
            w.installEventFilter(self)

    def _edges_at(self, gpos: QtCore.QPoint) -> QtCore.Qt.Edges:
        r = self.frameGeometry()
        m = _RESIZE_MARGIN
        edges = QtCore.Qt.Edges()
        if gpos.x() <= r.left() + m:
            edges |= QtCore.Qt.LeftEdge
        elif gpos.x() >= r.right() - m:
            edges |= QtCore.Qt.RightEdge
        if gpos.y() <= r.top() + m:
            edges |= QtCore.Qt.TopEdge
        elif gpos.y() >= r.bottom() - m:
            edges |= QtCore.Qt.BottomEdge
        return edges

    @staticmethod
    def _cursor_for(edges) -> QtCore.Qt.CursorShape | None:
        L, R = QtCore.Qt.LeftEdge, QtCore.Qt.RightEdge
        T, B = QtCore.Qt.TopEdge, QtCore.Qt.BottomEdge
        if edges == (L | T) or edges == (R | B):
            return QtCore.Qt.SizeFDiagCursor
        if edges == (R | T) or edges == (L | B):
            return QtCore.Qt.SizeBDiagCursor
        if edges & (L | R):
            return QtCore.Qt.SizeHorCursor
        if edges & (T | B):
            return QtCore.Qt.SizeVerCursor
        return None

    def eventFilter(self, obj, event) -> bool:
        et = event.type()
        if et == QtCore.QEvent.MouseMove:
            gpos = event.globalPosition().toPoint()
            if self._resize_origin is not None:
                self._manual_resize(gpos)
                return True
            if not (event.buttons() & QtCore.Qt.LeftButton):
                shape = self._cursor_for(self._edges_at(gpos))
                if shape is None:
                    self.unsetCursor()
                else:
                    self.setCursor(shape)
        elif et == QtCore.QEvent.MouseButtonPress \
                and event.button() == QtCore.Qt.LeftButton:
            gpos = event.globalPosition().toPoint()
            edges = self._edges_at(gpos)
            if edges:
                handle = self.windowHandle()
                if handle is not None and handle.startSystemResize(edges):
                    self._pending_save = True
                else:
                    self._resize_edges = edges
                    self._resize_origin = (gpos, self.geometry())
                return True
        elif et == QtCore.QEvent.MouseButtonRelease:
            if self._resize_origin is not None:
                self._resize_origin = None
                self._user_sized = True
                self._save_position()
                return True
        elif et == QtCore.QEvent.Leave and obj is self:
            self.unsetCursor()
        return super().eventFilter(obj, event)

    def _manual_resize(self, gpos: QtCore.QPoint) -> None:
        start, g0 = self._resize_origin
        d = gpos - start
        g = QtCore.QRect(g0)
        e = self._resize_edges
        mn = self._min_size()
        mw, mh = mn.width(), mn.height()
        if e & QtCore.Qt.LeftEdge:
            g.setLeft(min(g0.left() + d.x(), g0.right() - mw))
        if e & QtCore.Qt.RightEdge:
            g.setRight(max(g0.right() + d.x(), g0.left() + mw))
        if e & QtCore.Qt.TopEdge:
            g.setTop(min(g0.top() + d.y(), g0.bottom() - mh))
        if e & QtCore.Qt.BottomEdge:
            g.setBottom(max(g0.bottom() + d.y(), g0.top() + mh))
        self.setGeometry(g)

    def _min_size(self) -> QtCore.QSize:
        """中身が潰れない最小サイズ。レイアウトに決めさせる。"""
        return self.minimumSize()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        base = getattr(self, "_base_size", None)
        if base is not None and base.width() > 0 and base.height() > 0:
            f = min(self.width() / base.width(), self.height() / base.height())
            f = max(_SCALE_MIN, min(_SCALE_MAX, f))
            if abs(f - self._scale) >= 0.02:
                self._apply_scale(f)
        # startSystemResize 中は Qt にマウス解放が届かないので、
        # サイズが変わり終わってから少し待って保存する。
        if getattr(self, "_pending_save", False):
            if not hasattr(self, "_save_timer"):
                self._save_timer = QtCore.QTimer(self)
                self._save_timer.setSingleShot(True)
                self._save_timer.setInterval(400)
                self._save_timer.timeout.connect(self._finish_system_resize)
            self._save_timer.start()

    def _apply_scale(self, f: float) -> None:
        """文字・バー・余白を倍率 f にする。ウィンドウ自体の大きさは変えない。"""
        self._scale = f
        font = QtGui.QFont(self.font())
        if self._base_pt > 0:
            font.setPointSizeF(self._base_pt * f)
        # アプリのスタイルシートが font-family を指定していると、親の
        # setFont が子へ伝わらない。子それぞれに直接設定する。
        for w in [self, *self.findChildren(QtWidgets.QWidget)]:
            w.setFont(font)
        for g in [*self.gauges.values(), self.affinity_gauge]:
            g.set_scale(f)
        self._inner.setContentsMargins(
            round(12 * f), round(10 * f), round(12 * f), round(10 * f)
        )
        self._inner.setSpacing(max(1, round(4 * f)))

    def _finish_system_resize(self) -> None:
        self._pending_save = False
        self._user_sized = True
        self._save_position()

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
        data = {"x": self.x(), "y": self.y()}
        if self._user_sized:
            data["w"] = self.width()
            data["h"] = self.height()
        store.write_json(self._pos_file, data)

    def _restore_position(self) -> None:
        from ..engine.self_engine import store
        d = store.read_json(self._pos_file, {})
        try:
            w, h = int(d["w"]), int(d["h"])
            self.resize(QtCore.QSize(w, h).expandedTo(self._min_size()))
            self._user_sized = True
        except (KeyError, TypeError, ValueError):
            pass
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
