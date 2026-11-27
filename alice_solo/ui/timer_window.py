"""タイマー・アラーム・ストップウォッチ。仕様書 v2.0 §9.2。

終了したら郵便受けに積む（サーバー通知の代わり）。
時刻の進みは QTimer ではなく実時刻の差で測る。スリープや負荷で
QTimer が遅れても、復帰したときに正しい残り時間になる。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6 import QtCore, QtWidgets


def _fmt(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class TimerWindow(QtWidgets.QWidget):
    finished = QtCore.Signal(str, str)      # (title, body)

    def __init__(self, local_store=None):
        super().__init__(None)
        self.store = local_store
        self.setWindowTitle("タイマー")
        self.resize(360, 300)

        self.tabs = QtWidgets.QTabWidget(self)
        self.tabs.addTab(self._build_timer(), "タイマー")
        self.tabs.addTab(self._build_alarm(), "アラーム")
        self.tabs.addTab(self._build_stopwatch(), "ストップウォッチ")

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.tabs)

        self._tick = QtCore.QTimer(self)
        self._tick.setInterval(200)
        self._tick.timeout.connect(self._on_tick)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._tick.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._tick.stop()

    # ------------------------------------------------------------ タイマー

    def _build_timer(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget(self)
        self._timer_end: datetime | None = None
        self._timer_rest: float = 0.0

        self.timer_display = QtWidgets.QLabel("00:00", w)
        f = self.timer_display.font()
        f.setPointSize(28)
        self.timer_display.setFont(f)
        self.timer_display.setAlignment(QtCore.Qt.AlignCenter)

        self.min_spin = QtWidgets.QSpinBox(w)
        self.min_spin.setRange(0, 600)
        self.min_spin.setValue(10)
        self.min_spin.setSuffix(" 分")
        self.sec_spin = QtWidgets.QSpinBox(w)
        self.sec_spin.setRange(0, 59)
        self.sec_spin.setSuffix(" 秒")

        inputs = QtWidgets.QHBoxLayout()
        inputs.addWidget(self.min_spin)
        inputs.addWidget(self.sec_spin)

        self.timer_start_btn = QtWidgets.QPushButton("開始", w)
        self.timer_start_btn.clicked.connect(self._toggle_timer)
        btn_reset = QtWidgets.QPushButton("リセット", w)
        btn_reset.clicked.connect(self._reset_timer)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.timer_start_btn)
        buttons.addWidget(btn_reset)

        layout = QtWidgets.QVBoxLayout(w)
        layout.addWidget(self.timer_display)
        layout.addLayout(inputs)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return w

    def _toggle_timer(self) -> None:
        if self._timer_end is not None:
            # 一時停止。残りを覚えておく
            self._timer_rest = max(
                0.0, (self._timer_end - datetime.now()).total_seconds()
            )
            self._timer_end = None
            self.timer_start_btn.setText("再開")
            return

        rest = self._timer_rest or (
            self.min_spin.value() * 60 + self.sec_spin.value()
        )
        if rest <= 0:
            return
        self._timer_end = datetime.now() + timedelta(seconds=rest)
        self._timer_rest = 0.0
        self.timer_start_btn.setText("一時停止")

    def _reset_timer(self) -> None:
        self._timer_end = None
        self._timer_rest = 0.0
        self.timer_start_btn.setText("開始")
        self.timer_display.setText(
            _fmt(self.min_spin.value() * 60 + self.sec_spin.value())
        )

    # ------------------------------------------------------------ アラーム

    def _build_alarm(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget(self)
        self._alarm_at: datetime | None = None

        self.alarm_time = QtWidgets.QTimeEdit(w)
        self.alarm_time.setDisplayFormat("HH:mm")
        self.alarm_time.setTime(QtCore.QTime.currentTime().addSecs(600))

        self.alarm_label = QtWidgets.QLabel("止まっています", w)
        self.alarm_btn = QtWidgets.QPushButton("セット", w)
        self.alarm_btn.clicked.connect(self._toggle_alarm)

        layout = QtWidgets.QVBoxLayout(w)
        layout.addWidget(self.alarm_time)
        layout.addWidget(self.alarm_btn)
        layout.addWidget(self.alarm_label)
        layout.addStretch(1)
        return w

    def _toggle_alarm(self) -> None:
        if self._alarm_at is not None:
            self._alarm_at = None
            self.alarm_btn.setText("セット")
            self.alarm_label.setText("止まっています")
            return

        t = self.alarm_time.time()
        now = datetime.now()
        at = now.replace(hour=t.hour(), minute=t.minute(), second=0, microsecond=0)
        if at <= now:
            at += timedelta(days=1)      # 過ぎていたら明日
        self._alarm_at = at
        self.alarm_btn.setText("解除")
        self.alarm_label.setText(f"{at:%m/%d %H:%M} に鳴ります")

    # ------------------------------------------------------------ ストップウォッチ

    def _build_stopwatch(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget(self)
        self._sw_start: datetime | None = None
        self._sw_acc: float = 0.0

        self.sw_display = QtWidgets.QLabel("00:00", w)
        f = self.sw_display.font()
        f.setPointSize(28)
        self.sw_display.setFont(f)
        self.sw_display.setAlignment(QtCore.Qt.AlignCenter)

        self.sw_btn = QtWidgets.QPushButton("開始", w)
        self.sw_btn.clicked.connect(self._toggle_stopwatch)
        btn_reset = QtWidgets.QPushButton("リセット", w)
        btn_reset.clicked.connect(self._reset_stopwatch)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.sw_btn)
        buttons.addWidget(btn_reset)

        layout = QtWidgets.QVBoxLayout(w)
        layout.addWidget(self.sw_display)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return w

    def _toggle_stopwatch(self) -> None:
        if self._sw_start is None:
            self._sw_start = datetime.now()
            self.sw_btn.setText("停止")
        else:
            self._sw_acc += (datetime.now() - self._sw_start).total_seconds()
            self._sw_start = None
            self.sw_btn.setText("再開")

    def _reset_stopwatch(self) -> None:
        self._sw_start = None
        self._sw_acc = 0.0
        self.sw_btn.setText("開始")
        self.sw_display.setText("00:00")

    # ------------------------------------------------------------ 進行

    def _on_tick(self) -> None:
        now = datetime.now()

        if self._timer_end is not None:
            rest = (self._timer_end - now).total_seconds()
            self.timer_display.setText(_fmt(rest))
            if rest <= 0:
                self._timer_end = None
                self.timer_start_btn.setText("開始")
                self._notify("タイマー", "時間になりました。")
        elif self._timer_rest:
            self.timer_display.setText(_fmt(self._timer_rest))

        if self._alarm_at is not None and now >= self._alarm_at:
            at = self._alarm_at
            self._alarm_at = None
            self.alarm_btn.setText("セット")
            self.alarm_label.setText("鳴りました")
            self._notify("アラーム", f"{at:%H:%M} になりました。")

        if self._sw_start is not None:
            total = self._sw_acc + (now - self._sw_start).total_seconds()
            self.sw_display.setText(_fmt(total))

    def _notify(self, title: str, body: str) -> None:
        """郵便受けに積む。鍵に時刻を入れて上書きを防ぐ。"""
        if self.store is not None:
            # 秒までの鍵だと、タイマーとアラームが同じ秒に鳴ったとき
            # UNIQUE で上書きされて1件に潰れる。種別とマイクロ秒まで入れる。
            key = f"{title}:{datetime.now():%Y%m%d%H%M%S%f}"
            self.store.put_inbox("timer", key, title, body)
        self.finished.emit(title, body)

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
