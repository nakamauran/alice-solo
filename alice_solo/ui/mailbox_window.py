"""郵便受け。仕様書 v2.0 §9.2。

2つの顔を持つ。
  MailboxIcon  … デスクトップに常駐する小さな郵便受けの絵。未読があると
                 封筒が出ている絵に変わる。クリックで一覧を開く
  MailboxWindow … 投函の一覧。クリックで既読にする

アイコンの素材はキャラクターに依存しないので assets/ui/ に置くが、
パック内の sprites/ に同名ファイルがあればそちらを優先する。
"""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .. import config as C
from .dwm import apply_dwm_fixes
from .screen_layout import clamp_point

MAILBOX_HEIGHT = 110      # 基準の高さ。設定の倍率はこれに掛かる
EMPTY_FILE = "mailbox_empty.png"
UNREAD_FILE = "mailbox_unread.png"


def resolve_icon(pack_dir: Path, filename: str) -> Path | None:
    """パック内 -> 共通UI素材 の順に探す。"""
    for cand in (pack_dir / "sprites" / filename, C.ASSETS_DIR / "ui" / filename):
        if cand.exists():
            return cand
    return None


class MailboxIcon(QtWidgets.QWidget):
    """デスクトップに置く郵便受けの絵。"""

    clicked = QtCore.Signal()

    def __init__(self, pack_dir: Path, scale: float = 1.0):
        super().__init__(None)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setToolTip("郵便受け")

        self._pack_dir = pack_dir
        self._scale = scale
        self._unread = False
        self._drag_offset: QtCore.QPoint | None = None
        self._pixmaps: dict[bool, QtGui.QPixmap] = {}
        # 素材が1枚も無ければアイコンは出さない。1x1 の透明な窓が
        # 残ると、見えないのにクリックを吸う窓になってしまう。
        self.available = any(
            resolve_icon(pack_dir, f) for f in (EMPTY_FILE, UNREAD_FILE)
        )
        self._reload()
        self._restore_position()

    # ------------------------------------------------------------ 表示

    def _reload(self) -> None:
        self._pixmaps.clear()
        for unread, filename in ((False, EMPTY_FILE), (True, UNREAD_FILE)):
            path = resolve_icon(self._pack_dir, filename)
            pm = QtGui.QPixmap(str(path)) if path else QtGui.QPixmap()
            if pm.isNull():
                pm = QtGui.QPixmap(1, 1)
                pm.fill(QtCore.Qt.transparent)
            else:
                h = max(1, int(MAILBOX_HEIGHT * self._scale))
                pm = pm.scaledToHeight(h, QtCore.Qt.SmoothTransformation)
            self._pixmaps[unread] = pm
        # 窓サイズは両 pixmap の最大サイズにする。片方だけ 1x1 の
        # フォールバックだと、そちらを選んだときに窓が 1x1 になってしまう。
        w = max(pm.width() for pm in self._pixmaps.values())
        h = max(pm.height() for pm in self._pixmaps.values())
        self.setFixedSize(w, h)
        self.update()

    def set_unread(self, unread: bool) -> None:
        if unread != self._unread:
            self._unread = unread
            self.update()

    def apply_scale(self, scale: float) -> None:
        self._scale = max(0.6, min(3.0, float(scale)))
        self._reload()

    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.drawPixmap(0, 0, self._pixmaps[self._unread])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_dwm_fixes(int(self.winId()))

    # ------------------------------------------------------------ 操作

    def mousePressEvent(self, event) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            self._moved = False

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & QtCore.Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self._moved = True

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is None:
            return
        self._drag_offset = None
        if getattr(self, "_moved", False):
            self._save_position()
        else:
            self.clicked.emit()      # 動かさずに離したらクリック扱い

    # ------------------------------------------------------------ 位置

    @property
    def _pos_file(self) -> Path:
        return C.DATA_DIR / "mailbox_pos.json"

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
            self.move(g.left() + 40, g.bottom() - self.height() - 40)


class MailboxWindow(QtWidgets.QWidget):
    """投函の一覧。"""

    read_changed = QtCore.Signal()

    def __init__(self, local_store):
        super().__init__(None)
        self.store = local_store
        self.setWindowTitle("郵便受け")
        self.resize(420, 420)

        self.list = QtWidgets.QListWidget(self)
        self.list.itemSelectionChanged.connect(self._on_selected)

        self.body = QtWidgets.QTextEdit(self)
        self.body.setReadOnly(True)
        self.body.setFixedHeight(110)

        btn_all = QtWidgets.QPushButton("すべて既読にする", self)
        btn_all.clicked.connect(self._mark_all)
        btn_del = QtWidgets.QPushButton("削除", self)
        btn_del.clicked.connect(self._delete_selected)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(btn_all)
        row.addWidget(btn_del)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.body)
        layout.addLayout(row)

        self.reload()

    def reload(self) -> None:
        selected = self.list.selectedItems()
        keep_id = None
        if selected:
            data = selected[0].data(QtCore.Qt.UserRole) or {}
            if data.get("id") is not None:
                keep_id = int(data["id"])
        self.list.blockSignals(True)
        self.list.clear()
        for item in self.store.get_inbox():
            unread = item.get("read_at") is None
            mark = "●" if unread else "　"
            created = (item.get("created_at") or "")[5:16]
            w = QtWidgets.QListWidgetItem(
                f"{mark} {created}  {item.get('title') or ''}"
            )
            w.setData(QtCore.Qt.UserRole, item)
            if unread:
                f = w.font()
                f.setBold(True)
                w.setFont(f)
            self.list.addItem(w)
        if self.list.count() == 0:
            self.list.blockSignals(False)
            self.body.setPlainText("まだ何も届いていません。")
            return
        # 同じ id の項目を再選択する（notes_window.py と同じ方式）。
        # シグナルを止めたまま選ぶので _on_selected は走らない。
        # そのぶん本文はここで直接入れる。
        restored = False
        if keep_id is not None:
            for i in range(self.list.count()):
                data = self.list.item(i).data(QtCore.Qt.UserRole) or {}
                if data.get("id") is not None and int(data["id"]) == keep_id:
                    self.list.setCurrentRow(i)
                    self.body.setPlainText(data.get("body") or "")
                    restored = True
                    break
        if not restored:
            self.list.setCurrentRow(-1)
            self.body.clear()
        self.list.blockSignals(False)

    def _on_selected(self) -> None:
        items = self.list.selectedItems()
        if not items:
            return
        data = items[0].data(QtCore.Qt.UserRole) or {}
        self.body.setPlainText(data.get("body") or "")
        if data.get("read_at") is None:
            self.store.mark_read(int(data["id"]))
            self.reload()
            self.read_changed.emit()

    def _mark_all(self) -> None:
        self.store.mark_all_read()
        self.reload()
        self.read_changed.emit()

    def _delete_selected(self) -> None:
        items = self.list.selectedItems()
        if not items:
            return
        data = items[0].data(QtCore.Qt.UserRole) or {}
        if data.get("id") is not None:
            self.store.delete_inbox(int(data["id"]))
            self.body.clear()
            self.reload()
            self.read_changed.emit()

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
