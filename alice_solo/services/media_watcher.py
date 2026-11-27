"""再生中の曲。Windows SMTC。仕様書 v2.0 §6.4。

OS が認識しているメディアセッション（Spotify・ブラウザ・iTunes 等）から
曲名とアーティスト名を読むだけ。再生・停止・スキップの操作はしない。

起動時に1度だけ初期化を試み、失敗したら以後の呼び出しを全てスキップする。
Windows 10 1809 未満では API 自体が無く、Mac / Linux にも無い。
例外を利用者に見せないこと。
"""
from __future__ import annotations

import asyncio
import sys

# SMTC の取得が返ってこないときの上限。UI を固めないためのもの。
FETCH_TIMEOUT_SEC = 5.0


def _import_sessions():
    """winsdk / winrt のどちらでも動くようにする。"""
    try:
        from winsdk.windows.media.control import (        # type: ignore
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )
        return Manager
    except ImportError:
        pass
    try:
        from winrt.windows.media.control import (         # type: ignore
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )
        return Manager
    except ImportError:
        return None


class MediaWatcher:
    def __init__(self, enabled: bool = True):
        self.available = False
        self._manager_cls = None
        self._last: dict = {}
        self._fetching = False

        if not enabled or sys.platform != "win32":
            return
        self._manager_cls = _import_sessions()
        self.available = self._manager_cls is not None

    # ------------------------------------------------------------ 取得

    def poll(self) -> dict:
        """いま流れている曲。取れなければ空の辞書。

        同期版（ブロッキングする）。UI スレッドからは使わず、
        代わりに poll_async() を使うこと。取得には 5 秒の上限を付け、
        取得中の重複起動はしない。
        """
        if not self.available:
            return {}
        if self._fetching:
            return self._last
        self._fetching = True
        try:
            try:
                info = asyncio.run(
                    asyncio.wait_for(self._fetch(), timeout=FETCH_TIMEOUT_SEC))
            except Exception:
                # 一度でも転んだら以後は触らない。毎回例外を出すほうが害が大きい
                self.available = False
                return {}
        finally:
            self._fetching = False
        self._last = info or {}
        return self._last

    def _fetch_sync(self) -> dict:
        """run_async に投げるための同期版。ワーカー側でイベントループを作る。"""
        return asyncio.run(
            asyncio.wait_for(self._fetch(), timeout=FETCH_TIMEOUT_SEC))

    def poll_async(self, on_done=None, on_fail=None):
        """ワーカー経由で曲を取る。UI スレッドをブロックしない。

        取得が始まれば Task を返し、終わったら on_done(info) を呼ぶ。
        利用できない・取得中のときは None を返す（その場合は手元の控えを使う）。
        """
        if not self.available:
            return None
        if self._fetching:
            return None
        # worker.py は PySide6 を引くので、ここで遅延 import する。
        # （このモジュール自体は PySide6 無しでも import できるままにする）
        from .worker import run_async

        self._fetching = True

        def _done(info) -> None:
            self._fetching = False
            if isinstance(info, dict):
                self._last = info
            if on_done is not None:
                on_done(info)

        def _fail(_e) -> None:
            self._fetching = False
            self.available = False
            if on_fail is not None:
                on_fail(_e)

        return run_async(self._fetch_sync, on_done=_done, on_fail=_fail)

    async def _fetch(self) -> dict:
        manager = await self._manager_cls.request_async()
        session = manager.get_current_session()
        if session is None:
            return {}
        props = await session.try_get_media_properties_async()
        playback = session.get_playback_info()
        status = getattr(playback, "playback_status", None)
        return {
            "title": (getattr(props, "title", "") or "").strip(),
            "artist": (getattr(props, "artist", "") or "").strip(),
            "playing": int(status) == 4 if status is not None else False,
        }

    # ------------------------------------------------------------ 参照

    def now_playing(self) -> dict:
        """最後に取れた曲。topics.py はこれを見る。"""
        if not self._last or not self._last.get("title"):
            return {}
        return self._last

    def display_text(self) -> str:
        """HUD 用の1行。取れていなければ空。"""
        info = self.now_playing()
        if not info:
            return ""
        if info.get("artist"):
            return f"{info['artist']} - {info['title']}"
        return info["title"]
