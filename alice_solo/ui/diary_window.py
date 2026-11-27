"""日記。仕様書 v2.0 §9.2。

日付ごとに1エントリ。プレーンテキスト。自動削除はしない。
日付の境は朝5時なので、深夜2時に書いたぶんは前日の日記になる。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6 import QtCore, QtWidgets

from ..engine.self_engine import store


class DiaryWindow(QtWidgets.QWidget):
    def __init__(self, local_store):
        super().__init__(None)
        self.store = local_store
        self.setWindowTitle("日記")
        self.resize(480, 460)

        self._date = store.today_key()
        self._dirty = False

        self.date_label = QtWidgets.QLabel(self)
        btn_prev = QtWidgets.QPushButton("← 前の日", self)
        btn_prev.clicked.connect(lambda: self._shift(-1))
        btn_next = QtWidgets.QPushButton("次の日 →", self)
        btn_next.clicked.connect(lambda: self._shift(1))
        btn_today = QtWidgets.QPushButton("今日", self)
        btn_today.clicked.connect(self._go_today)

        head = QtWidgets.QHBoxLayout()
        head.addWidget(btn_prev)
        head.addWidget(self.date_label, 1, QtCore.Qt.AlignCenter)
        head.addWidget(btn_next)
        head.addWidget(btn_today)

        self.editor = QtWidgets.QPlainTextEdit(self)
        self.editor.setPlaceholderText("今日はどんな日でしたか。")
        self.editor.textChanged.connect(self._on_changed)

        self.history = QtWidgets.QComboBox(self)
        self.history.currentTextChanged.connect(self._on_history_picked)

        self.status = QtWidgets.QLabel("", self)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self.editor, 1)
        layout.addWidget(QtWidgets.QLabel("書いた日", self))
        layout.addWidget(self.history)
        layout.addWidget(self.status)

        # 書くたびに保存すると重いので、手が止まってから保存する
        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1200)
        self._save_timer.timeout.connect(self.save)

        # _reload_history() を先に呼ぶ。_load() がコンボへ一時項目を
        # 追加するので、順序が逆だと起動時に消えてしまう。
        self._reload_history()
        self._load()

    # ------------------------------------------------------------ 日付

    def _shift(self, days: int) -> None:
        self.save()
        d = datetime.strptime(self._date, "%Y-%m-%d") + timedelta(days=days)
        self._date = d.strftime("%Y-%m-%d")
        self._load()

    def _go_today(self) -> None:
        self.save()
        self._date = store.today_key()
        self._load()

    def _on_history_picked(self, text: str) -> None:
        if text and text != self._date:
            self.save()
            self._date = text
            self._load()

    # ------------------------------------------------------------ 読み書き

    def _load(self) -> None:
        self.editor.blockSignals(True)
        self.editor.setPlainText(self.store.get_diary(self._date))
        self.editor.blockSignals(False)
        self._dirty = False
        self.date_label.setText(self._date)
        self.status.setText("")
        # コンボの選択を _date に合わせる。まだ日記が無い日付は
        # 一時項目として追加する（書いた日一覧に無い日も選べるようにする）。
        # 前回の一時項目（日記が無い日付）はここで掃除する。
        saved = set(self.store.diary_dates())
        self.history.blockSignals(True)
        for i in range(self.history.count() - 1, -1, -1):
            if self.history.itemText(i) not in saved:
                self.history.removeItem(i)
        idx = self.history.findText(self._date)
        if idx >= 0:
            self.history.setCurrentIndex(idx)
        else:
            self.history.addItem(self._date)
            self.history.setCurrentIndex(self.history.count() - 1)
        self.history.blockSignals(False)

    def _on_changed(self) -> None:
        self._dirty = True
        self.status.setText("…")
        self._save_timer.start()

    def save(self) -> None:
        if not self._dirty:
            return
        self.store.save_diary(self._date, self.editor.toPlainText())
        self._dirty = False
        self.status.setText(f"保存しました（{datetime.now():%H:%M}）")
        self._reload_history()

    def _reload_history(self) -> None:
        dates = self.store.diary_dates()
        self.history.blockSignals(True)
        self.history.clear()
        self.history.addItems(dates)
        idx = self.history.findText(self._date)
        if idx >= 0:
            self.history.setCurrentIndex(idx)
        self.history.blockSignals(False)

    def closeEvent(self, event) -> None:
        self.save()
        event.ignore()
        self.hide()
