"""ログ。仕様書 v2.0 §3.5（7日 / 最大5MB でローテーション）。

常駐アプリは利用者がコンソールを見ていないので、落ちたときに何も
残らないのが一番困る。日ごとに回して7日ぶん残し、1ファイルが5MBを
超えたらその場で回す。
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from . import config as C

LOG_DIR = C.DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "alice.log"

BACKUP_DAYS = 7
MAX_BYTES = 5 * 1024 * 1024

_logger: logging.Logger | None = None


def get_logger() -> logging.Logger:
    return _logger or logging.getLogger("alice")


def setup(level: int = logging.INFO) -> logging.Logger:
    """起動時に1度だけ呼ぶ。2度目以降は同じロガーを返す。"""
    global _logger
    if _logger is not None:
        return _logger

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("alice")
    logger.setLevel(level)
    logger.propagate = False

    handler = logging.handlers.TimedRotatingFileHandler(
        LOG_FILE, when="midnight", backupCount=BACKUP_DAYS, encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                          datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)

    # 日をまたがなくても大きくなりすぎたらその場で回す
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_BYTES:
            handler.doRollover()
    except OSError:
        pass

    _logger = logger
    _install_excepthook(logger)
    logger.info("--- Alice Solo 起動 ---")
    return logger


def _install_excepthook(logger: logging.Logger) -> None:
    """拾われなかった例外をログに残す。黙って消えるのを防ぐ。"""
    previous = sys.excepthook

    def hook(exc_type, exc, tb):
        logger.error("拾われなかった例外", exc_info=(exc_type, exc, tb))
        previous(exc_type, exc, tb)

    sys.excepthook = hook


def purge_old(days: int = BACKUP_DAYS) -> int:
    """回し損ねた古いログを消す。戻り値は消した数。"""
    import time

    if not LOG_DIR.is_dir():
        return 0
    limit = time.time() - days * 86400
    removed = 0
    for f in LOG_DIR.glob("alice.log.*"):
        try:
            if f.stat().st_mtime < limit:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed
