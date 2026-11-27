"""メモ帳。仕様書 v2.0 §9.2。

複数メモ。タイトルと内容。自動削除はしない。
"""
from __future__ import annotations

from datetime import datetime

from PySide6 import QtCore, QtWidgets


class NotesWindow(QtWidgets.QWidget):
    def __init__(self, local_store):
        super().__init__(None)
        self.store = local_store
        self.setWindowTitle("メモ")
        self.resize(560, 420)

        self._current_id: int | None = None
        self._dirty = False

        self.list = QtWidgets.QListWidget(self)
        self.list.setFixedWidth(180)
        self.list.currentItemChanged.connect(self._on_pick)

        btn_new = QtWidgets.QPushButton("新規", self)
        btn_new.clicked.connect(self._new_note)
        btn_del = QtWidgets.QPushButton("削除", self)
        btn_del.clicked.connect(self._delete_note)

        side_buttons = QtWidgets.QHBoxLayout()
        side_buttons.addWidget(btn_new)
        side_buttons.addWidget(btn_del)

        side = QtWidgets.QVBoxLayout()
        side.addWidget(self.list, 1)
        side.addLayout(side_buttons)

        self.title = QtWidgets.QLineEdit(self)
        self.title.setPlaceholderText("タイトル")
        self.title.textChanged.connect(self._on_changed)

        self.body = QtWidgets.QPlainTextEdit(self)
        self.body.setPlaceholderText("内容")
        self.body.textChanged.connect(self._on_changed)

        self.status = QtWidgets.QLabel("", self)

        right = QtWidgets.QVBoxLayout()
        right.addWidget(self.title)
        right.addWidget(self.body, 1)
        right.addWidget(self.status)

        layout = QtWidgets.QHBoxLayout(self)
        layout.addLayout(side)
        layout.addLayout(right, 1)

        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1200)
        self._save_timer.timeout.connect(self.save)

        self.reload()

    # ------------------------------------------------------------ 一覧

    def reload(self, select_id: int | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for note in self.store.list_notes():
            label = (note.get("title") or "").strip() or "（無題）"
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, note)
            self.list.addItem(item)
        self.list.blockSignals(False)

        target = select_id if select_id is not None else self._current_id
        picked: dict | None = None
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            data = self.list.item(i).data(QtCore.Qt.UserRole)
            if data and int(data["id"]) == target:
                self.list.setCurrentRow(i)
                picked = data
                break
        else:
            if self.list.count():
                self.list.setCurrentRow(0)
                picked = self.list.item(0).data(QtCore.Qt.UserRole)
        self.list.blockSignals(False)
        # setCurrentRow をシグナル停止中に呼んだので _on_pick は走らない。
        # そのぶん表示はここで直接切り替える。
        self._show(picked)

    # ------------------------------------------------------------ 編集

    def _on_pick(self, current, _previous) -> None:
        self.save()
        self._show(current.data(QtCore.Qt.UserRole) if current else None)

    def _show(self, note: dict | None) -> None:
        self.title.blockSignals(True)
        self.body.blockSignals(True)
        if note:
            self._current_id = int(note["id"])
            self.title.setText(note.get("title") or "")
            self.body.setPlainText(note.get("content") or "")
            self.title.setEnabled(True)
            self.body.setEnabled(True)
        else:
            self._current_id = None
            self.title.clear()
            self.body.clear()
            self.title.setEnabled(False)
            self.body.setEnabled(False)
        self.title.blockSignals(False)
        self.body.blockSignals(False)
        self._dirty = False
        self.status.setText("")

    def _on_changed(self) -> None:
        if self._current_id is None:
            return
        self._dirty = True
        self.status.setText("…")
        self._save_timer.start()

    def save(self) -> None:
        if not self._dirty or self._current_id is None:
            return
        self.store.update_note(
            self._current_id, self.title.text(), self.body.toPlainText()
        )
        self._dirty = False
        self.status.setText(f"保存しました（{datetime.now():%H:%M}）")
        keep = self._current_id
        self.reload(select_id=keep)

    def _new_note(self) -> None:
        self.save()
        new_id = self.store.create_note("", "")
        self.reload(select_id=new_id)
        self.title.setFocus(QtCore.Qt.OtherFocusReason)

    def _delete_note(self) -> None:
        if self._current_id is None:
            return
        answer = QtWidgets.QMessageBox.question(
            self, "メモの削除", "このメモを削除しますか。",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        self.store.delete_note(self._current_id)
        self._dirty = False
        self._current_id = None
        self.reload()

    def closeEvent(self, event) -> None:
        self.save()
        event.ignore()
        self.hide()
