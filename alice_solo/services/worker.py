"""通信をUIスレッドから逃がすための薄い入れ物。

QThreadPool に投げ、終わったらシグナルで戻す。
仕様書 v2.0 §2.2（外部取得は QRunnable、UIをブロックしない）。
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

# 走っている間、Python 側から参照を持ち続ける。手放すと途中で回収され、
# 終了時に「Signal source has been deleted」で落ちることがある。
_running: set = set()


class _Signals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = _Signals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as e:      # 通信先の不調で本体を落とさない
            self._emit(self.signals.failed, str(e))
            return
        self._emit(self.signals.finished, result)

    def _emit(self, signal, value) -> None:
        """受け手が先に消えていても落とさない。

        アプリを閉じた直後に通信が返ってくると、繋ぎ先の窓がもう無い。
        """
        try:
            signal.emit(value)
        except RuntimeError:
            # 受け手が先に消えている。配送されないので、ここで手放す
            _running.discard(self)


def run_async(fn: Callable, on_done: Callable | None = None,
              on_fail: Callable | None = None, *args, **kwargs) -> Task:
    task = Task(fn, *args, **kwargs)
    _running.add(task)
    if on_done is not None:
        task.signals.finished.connect(on_done)
    if on_fail is not None:
        task.signals.failed.connect(on_fail)

    # 後始末は最後に繋ぐ。スロットは繋いだ順に呼ばれるので、利用側の
    # 処理が済んでから手放すことになる。
    def _release(*_args, task=task):
        _running.discard(task)

    task.signals.finished.connect(_release)
    task.signals.failed.connect(_release)

    QThreadPool.globalInstance().start(task)
    return task


def pending() -> int:
    """まだ走っている仕事の数。終了処理から様子を見るのに使う。"""
    return len(_running)
