"""PC状態。psutil。仕様書 v2.0 §6.3。

CPU・メモリ・ディスクの使用率と、しきい値に対する良し悪しを返す。
これらの取得に管理者権限は要らない。
"""
from __future__ import annotations

import os

try:
    import psutil
except ImportError:      # psutil が無くても本体は動かす
    psutil = None        # type: ignore


DEFAULT_THRESHOLDS = {"cpu_warn": 85, "mem_warn": 85, "disk_warn": 90}


class PCMonitor:
    def __init__(self, thresholds: dict | None = None, disk_path: str | None = None):
        # しきい値は config.yaml が正（§7.2）。引数で渡されたものが最優先。
        from .. import config as C
        from_yaml = C.app_value("monitor.thresholds", {}) or {}
        self.thresholds = {**DEFAULT_THRESHOLDS, **from_yaml, **(thresholds or {})}
        self.disk_path = disk_path or (os.environ.get("SystemDrive", "") + "\\"
                                       if os.name == "nt" else "/")
        self.available = psutil is not None
        self._last: dict = {}
        if self.available:
            # 初回の cpu_percent は 0.0 を返すので、基準点だけ先に作る
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                self.available = False

    def measure(self) -> dict:
        """計測する。UIスレッドから呼んでもよい（interval=None で即返る）。"""
        if not self.available:
            return {}
        try:
            cpu = float(psutil.cpu_percent(interval=None))
            mem = float(psutil.virtual_memory().percent)
            disk = float(psutil.disk_usage(self.disk_path).percent)
        except Exception:
            return self._last

        self._last = {
            "cpu": round(cpu, 1),
            "mem": round(mem, 1),
            "disk": round(disk, 1),
            "diagnostics": {
                "cpu": cpu < self.thresholds["cpu_warn"],
                "mem": mem < self.thresholds["mem_warn"],
                "disk": disk < self.thresholds["disk_warn"],
            },
        }
        return self._last

    def snapshot(self) -> dict:
        """最後に測った値。まだ無ければ測る。"""
        return self._last or self.measure()

    def is_healthy(self) -> bool:
        snap = self.snapshot()
        if not snap:
            return True
        return all(snap.get("diagnostics", {}).values())
