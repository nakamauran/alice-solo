"""チャット窓。仕様書 v2.0 §9.2 ＋ 改善仕様書 §5。

- 発言に時刻を付ける
- Enter で送信、Shift+Enter で改行
- 発言はすべて左寄せ。自分の発言は薄い背景、こゆきは白背景で区別する
- 当日分の履歴を復元する（保存は main.py が local_store へ行う）
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor, QKeyEvent, QTextBlockFormat, QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QPlainTextEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from .theme import load_theme

MAX_BLOCKS = 400


class _Input(QPlainTextEdit):
    """Enter で送信、Shift+Enter で改行する入力欄。"""

    submitted = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)      # 改行
            else:
                self.submitted.emit()
            return
        super().keyPressEvent(event)


class ChatWindow(QWidget):
    message_sent = Signal(str)

    def __init__(self, display_name: str = "こゆき"):
        super().__init__(None)
        self.display_name = display_name
        self.setWindowTitle(f"{display_name} - チャット")
        self.resize(440, 500)

        # 寄せとブロック背景を使うため QTextEdit を使う。QPlainTextEdit では
        # ブロックごとの背景色が付けられない。行数は _trim() で自前に抑える。
        self.history = QTextEdit(self)
        self.history.setReadOnly(True)

        self.input = _Input(self)
        self.input.setPlaceholderText("おはよう、って話しかけてみて")
        self.input.submitted.connect(self._send)
        line_h = self.input.fontMetrics().lineSpacing()
        self.input.setFixedHeight(line_h * 2 + 16)

        self.send_button = QPushButton("送信", self)
        self.send_button.clicked.connect(self._send)

        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(self.send_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.history, 1)
        layout.addLayout(row)

    # ------------------------------------------------------------ 表示

    def set_display_name(self, name: str) -> None:
        self.display_name = name or self.display_name
        self.setWindowTitle(f"{self.display_name} - チャット")

    def _append(self, who: str, text: str, mine: bool,
                stamp: str | None = None) -> None:
        theme = load_theme()
        # 見本どおり、自分の発言は accent-soft（highlight）。
        # accent は主ボタン用の濃い色なので、地に敷くと文字が読めない。
        bg = theme.get("highlight", "#ffd9e0") if mine \
            else theme.get("surface", theme.get("background", "#ffffff"))
        stamp = stamp or datetime.now().strftime("%H:%M")

        cursor = self.history.textCursor()
        cursor.movePosition(QTextCursor.End)
        if not self.history.document().isEmpty():
            cursor.insertBlock()

        block = QTextBlockFormat()
        # 時刻の位置をそろえるため、自分の発言も左寄せにする。
        block.setAlignment(Qt.AlignLeft)
        block.setBackground(QColor(bg))
        block.setTopMargin(2)
        block.setBottomMargin(2)
        block.setLeftMargin(8)
        block.setRightMargin(8)
        cursor.setBlockFormat(block)

        char = QTextCharFormat()
        char.setForeground(QColor(theme.get("text", "#5f4d45")))
        cursor.setCharFormat(char)
        cursor.insertText(f"[{stamp}] {who} {text}")

        self._trim()
        self.history.moveCursor(QTextCursor.End)
        self.history.ensureCursorVisible()

    def _trim(self) -> None:
        """古いブロックを捨てる。QTextEdit には行数上限が無いため自前で。"""
        doc = self.history.document()
        while doc.blockCount() > MAX_BLOCKS:
            cursor = QTextCursor(doc.firstBlock())
            cursor.select(QTextCursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    def append_user(self, text: str) -> None:
        self._append("あなた", text, mine=True)

    def append_reply(self, text: str) -> None:
        self._append(self.display_name, text, mine=False)

    def append_system(self, text: str) -> None:
        self._append("—", text, mine=False)

    def append_log_row(self, role: str, text: str, created_at: str = "") -> None:
        """保存された履歴を戻す。created_at は 'YYYY-MM-DD HH:MM:SS'。"""
        stamp = created_at[11:16] if len(created_at) >= 16 else ""
        who = "あなた" if role == "user" else self.display_name
        self._append(who, text, mine=(role == "user"), stamp=stamp or None)

    def clear_history(self) -> None:
        self.history.clear()

    # ------------------------------------------------------------ 送信

    def _send(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.append_user(text)
        self.message_sent.emit(text)

    def focus_input(self) -> None:
        self.input.setFocus(Qt.OtherFocusReason)
