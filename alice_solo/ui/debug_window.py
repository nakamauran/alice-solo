"""デバッグログの窓。

チャット欄に出すと会話が読めなくなるので、別窓に分けてある。
内部の数値（感情スコア・好感度・層・気分・外部取得の結果）を
時刻つきで流す。開いていなくても記録は溜まるので、あとから開いて
さかのぼれる。
"""
from __future__ import annotations

from collections import deque
from datetime import datetime

from PySide6 import QtCore, QtGui, QtWidgets

MAX_LINES = 500      # これを超えた古い行から捨てる

# 種別ごとの色。暗い背景に載せる前提。
CATEGORY_COLORS = {
    "chat": "#8fb8d8",
    "idle": "#a8c8a0",
    "self": "#d8c088",
    "net": "#c0a0d0",
    "warn": "#e08870",
    "info": "#b0b0b8",
}


class DebugWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("デバッグ")
        self.resize(620, 400)

        self._lines: deque[tuple[str, str, str]] = deque(maxlen=MAX_LINES)
        # 同じ行をログファイルにも落とすための差し込み口
        self.sink = None

        self.view = QtWidgets.QPlainTextEdit(self)
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.view.setMaximumBlockCount(MAX_LINES)
        font = QtGui.QFont("Consolas")
        font.setStyleHint(QtGui.QFont.Monospace)
        font.setPointSize(9)
        self.view.setFont(font)
        self.view.setStyleSheet(
            "QPlainTextEdit { background: #22222a; color: #d0d0d8;"
            " border: 1px solid #3a3a46; border-radius: 6px; }"
        )

        self.autoscroll = QtWidgets.QCheckBox("自動スクロール", self)
        self.autoscroll.setChecked(True)

        btn_clear = QtWidgets.QPushButton("クリア", self)
        btn_clear.clicked.connect(self.clear)
        btn_copy = QtWidgets.QPushButton("コピー", self)
        btn_copy.clicked.connect(self.copy_all)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.autoscroll)
        row.addStretch(1)
        row.addWidget(btn_copy)
        row.addWidget(btn_clear)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.view, 1)
        layout.addLayout(row)

    # ------------------------------------------------------------ 記録

    def log(self, category: str, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self._lines.append((stamp, category, text))
        if callable(self.sink):
            try:
                self.sink(category, text)
            except Exception:
                pass      # ログに落とせなくても画面表示は続ける
        color = CATEGORY_COLORS.get(category, CATEGORY_COLORS["info"])
        html = (
            f'<span style="color:#6a6a76;">{stamp}</span> '
            f'<span style="color:{color};">[{category}]</span> '
            f'<span style="color:#d0d0d8;">{self._escape(text)}</span>'
        )
        self.view.appendHtml(html)
        if self.autoscroll.isChecked():
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.maximum())

    @staticmethod
    def _escape(text: str) -> str:
        return (text.replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;"))

    # ------------------------------------------------------------ 操作

    def clear(self) -> None:
        self._lines.clear()
        self.view.clear()

    def copy_all(self) -> None:
        text = "\n".join(f"{s} [{c}] {t}" for s, c, t in self._lines)
        QtWidgets.QApplication.clipboard().setText(text)

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
