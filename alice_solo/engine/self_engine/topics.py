"""自分から話す話題。仕様書 v2.0 §4.4.5。

状態を持たず、材料を見に行って1つ返す。材料が無ければ黙る（None）。
例外は握り潰す。話題を1つ出すために本体を落としてはいけない。

v1.0 にあった「季節の曲」「お気に入り曲数」は音楽管理の廃止に伴い削除し、
代わりに「再生中の曲」（Windows SMTC）を入れてある。
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from ... import config as C
from . import calendar_ja as cal
from . import store


class Topics:
    def __init__(self, pool, pc_monitor=None, media_watcher=None,
                 local_store=None, rng: random.Random | None = None):
        self.pool = pool
        self.pc_monitor = pc_monitor       # フェーズ4で差し込む
        self.media_watcher = media_watcher # 同上
        self._said_song: str | None = None
        self._said_date: str | None = None
        self._pending_song: str | None = None
        self.store = local_store           # 「覚えたこと」の置き場（§3.4）
        self.rng = rng or random.Random()
        self._last_kind: str | None = None  # 同じ話題を2回続けない

    # ------------------------------------------------------------ 入口

    def pick(self, tier: str, now: datetime | None = None, **fields) -> str | None:
        """話題を1つ返す。順に試して、最初に材料があったものを使う。"""
        now = now or datetime.now()

        # 試行順は毎回シャッフルする。固定だと先に材料がある話題が毎回勝ち、
        # 曲が流れている日は曜日の話が一生出ない（§3.2）。
        candidates = [
            ("season", self._season_change),
            ("event", self._event),
            ("news", self._news),
            ("pc", self._pc_alert),
            ("weekday", self._weekday),
            ("now_playing", self._now_playing),
            ("memory", self._memory),
        ]
        self.rng.shuffle(candidates)

        # 前回と同じ話題は最後に回す。それしか材料が無ければ結局選ばれる。
        if self._last_kind:
            candidates.sort(key=lambda kv: kv[0] == self._last_kind)

        for kind, fn in candidates:
            try:
                said = fn(tier, now, fields)
            except Exception:
                said = None     # 材料の取得で転んでも黙るだけにする
            if said:
                self._last_kind = kind
                return said
        return None

    def mark_said(self, topic_key: str, now: datetime | None = None) -> bool:
        """「言った」記録を付ける。Now Playing 専用。

        pick() は話題を選ぶだけで「言った」記録は付けない（選ばれても
        実際に発話されるとは限らないため）。pick() が Now Playing を
        選んだときは曲名を ``_pending_song`` に控えておき、呼び出し側が
        その文を実際に発話したと分かったときにだけ本メソッドを呼ぶ。

        使い方（main.py の on_idle_check）::

            topic = self.topics.pick(...)
            text = self.dialogue.idle_phrase(..., topic=topic)
            if text and text == topic:
                self.topics.mark_said("talk_now_playing", now)

        ``topic_key`` は ``"talk_now_playing"`` または曲名そのものを
        受け取る。控え（``_pending_song``）と一致しない場合や、控えが
        無い場合は何もせず False を返す。記録したら True を返す。
        """
        if not self._pending_song:
            return False
        if topic_key not in ("talk_now_playing", self._pending_song):
            return False
        now = now or datetime.now()
        self._said_song = self._pending_song
        self._said_date = store.today_key(now)
        self._pending_song = None
        return True

    # ------------------------------------------------------------ 各話題

    def _season_change(self, tier, now, fields):
        """1週間前と季節が変わっていたら。同じ季節なら黙る。"""
        if cal.season_key(now) == cal.season_key(now - timedelta(days=7)):
            return None
        return self.pool.pick(
            "talk_season_change", tier,
            season=cal.label_of(cal.season_key(now)), **fields
        )

    def _event(self, tier, now, fields):
        keys = cal.event_keys(now)
        if not keys:
            return None
        return self.pool.pick(
            "talk_event", tier, event=cal.label_of(keys[0]), **fields
        )

    def _news(self, tier, now, fields):
        """新聞が届いているときだけ。ファイルが無ければ黙る。"""
        if not C.NEWS_HTML.exists():
            return None
        # 今日ぶんでなければ言わない（朝5時境の「今日」で判定）
        mtime = datetime.fromtimestamp(C.NEWS_HTML.stat().st_mtime)
        if store.today_key(mtime) != store.today_key(now):
            return None
        return self.pool.pick("talk_news", tier, **fields)

    def _pc_alert(self, tier, now, fields):
        """平常時は黙る。異常値があるときだけ触れる。"""
        if self.pc_monitor is None:
            return None
        snap = self.pc_monitor.snapshot()
        if not snap or all(snap.get("diagnostics", {}).values()):
            return None
        return self.pool.pick("talk_pc_alert", tier, **fields)

    def _now_playing(self, tier, now, fields):
        """同じ曲について1日に何度も言わない。"""
        if self.media_watcher is None:
            return None
        info = self.media_watcher.now_playing()
        if not info or not info.get("title"):
            return None
        title = info["title"]
        today = store.today_key(now)
        if self._said_song == title and self._said_date == today:
            return None
        said = self.pool.pick("talk_now_playing", tier, song=title, **fields)
        if said:
            # 「言った」記録はここでは付けない。実際に発話された後に
            # 呼び出し側が mark_said() を呼ぶまで _pending_song に控える。
            self._pending_song = title
        return said

    def _weekday(self, tier, now, fields):
        """月・金・土・日だけ。火〜木は黙る。"""
        if now.weekday() not in (0, 4, 5, 6):
            return None
        return self.pool.pick(
            "talk_weekday", tier,
            weekday=cal.WEEKDAY_LABELS[now.weekday()], **fields
        )

    # ------------------------------------------------------------ 記憶

    def _memory(self, tier, now, fields):
        """数日前に覚えたことを呼び戻す（§3.4）。

        直後に言うと「いま聞いたことをなぞっただけ」になるので2日以上あける。
        言いすぎないよう、回数と間隔にも上限を置く。
        """
        if self.store is None:
            return None
        rows = self.store.get_memory_candidates(now=now)
        if not rows:
            return None
        row = rows[0]
        said = self.pool.pick("topic_callback", tier,
                              thing=row.get("text", ""), **fields)
        if said:
            self.store.mark_memory_mentioned(int(row["id"]), now=now)
        return said
