"""state.json の読み書きと経時変化。仕様書 v2.0 §4.1。

餌やり・遊びを廃止したため、満腹度とテンションは「生活リズム」で
自動回復する。ユーザ操作では動かない。
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path

from .. import config as C

ISO = "%Y-%m-%dT%H:%M:%S"


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _parse(s: str | None, fallback: datetime) -> datetime:
    if not s:
        return fallback
    try:
        return datetime.strptime(s[:19], ISO)
    except (ValueError, TypeError):
        return fallback


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class VPetState:
    satiety: float = 80.0
    tension: float = 60.0
    boredom: float = 0.0
    emotion: float = 0.0
    last_interaction_time: str = ""
    last_tick_time: str = ""
    last_meal_applied: str = ""
    last_wake_applied: str = ""
    # 時間帯挨拶を言った記録（slot -> "YYYY-MM-DD"。同じスロットの挨拶は1日1回まで）
    greeted_slots: dict = field(default_factory=dict)


class StateManager:
    """state.json を1つだけ持つ。履歴は残さない。"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else C.STATE_FILE
        self.state = self._load()
        self._dirty = False

    # ------------------------------------------------------------ 読み書き

    def _load(self) -> VPetState:
        now = _now()
        if not self.path.exists():
            s = VPetState()
            s.last_interaction_time = now.strftime(ISO)
            s.last_tick_time = now.strftime(ISO)
            return s
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        s = VPetState()
        _defaults = asdict(s)
        _float_fields = ("satiety", "tension", "boredom", "emotion")
        for k in _defaults:
            if k not in raw:
                continue
            if k in _float_fields:
                try:
                    setattr(s, k, float(raw[k]))
                except (TypeError, ValueError):
                    setattr(s, k, _defaults[k])
            elif k == "greeted_slots":
                # 辞書フィールドは辞書のときだけ採用する
                if isinstance(raw[k], dict):
                    setattr(s, k, raw[k])
            else:
                setattr(s, k, raw[k])
        if not s.last_tick_time:
            s.last_tick_time = now.strftime(ISO)
        if not s.last_interaction_time:
            s.last_interaction_time = now.strftime(ISO)
        return s

    def save(self) -> None:
        """一時ファイルへ書いてから原子置換する。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(asdict(self.state), ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp, self.path)
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        self._dirty = False

    def save_if_dirty(self) -> None:
        if self._dirty:
            self.save()

    # ------------------------------------------------------------ 生活リズム

    @staticmethod
    def _meal_times_in(start: datetime, end: datetime) -> list[datetime]:
        """(start, end] に入る食事時刻を昇順で返す。"""
        out: list[datetime] = []
        day = start.date()
        while day <= end.date():
            for h, m in C.MEAL_HOURS:
                t = datetime.combine(day, datetime.min.time()).replace(hour=h, minute=m)
                if start < t <= end:
                    out.append(t)
            day += timedelta(days=1)
        return sorted(out)

    @staticmethod
    def _wake_times_in(start: datetime, end: datetime) -> list[datetime]:
        out: list[datetime] = []
        day = start.date()
        while day <= end.date():
            t = datetime.combine(day, datetime.min.time()).replace(hour=C.WAKE_HOUR)
            if start < t <= end:
                out.append(t)
            day += timedelta(days=1)
        return sorted(out)

    @staticmethod
    def _tension_decay_rate(at: datetime) -> float:
        rate = C.TENSION_DECAY_PER_SEC
        if at.hour >= C.NIGHT_DECAY_START_HOUR:
            rate *= C.NIGHT_DECAY_FACTOR
        return rate

    # ------------------------------------------------------------ tick

    def tick(self, now: datetime | None = None) -> None:
        """減衰・生活リズム・退屈度をまとめて更新する。

        未起動中に通過した食事/起床は、まとめて加算せず **最後の1回だけ**
        適用する（3食ぶん一気に満腹になるのを防ぐ）。
        """
        now = now or _now()
        last = _parse(self.state.last_tick_time, now)
        if now <= last:
            # 時計が戻っても last_tick_time を過去に書き戻さない。
            return

        elapsed = (now - last).total_seconds()

        # 自然減衰
        self.state.satiety = _clamp(
            self.state.satiety - C.SATIETY_DECAY_PER_SEC * elapsed, 0.0, 100.0
        )
        self.state.tension = _clamp(
            self.state.tension - self._tension_decay_rate(now) * elapsed, 0.0, 100.0
        )

        # 食事（最後の1回だけ）
        meals = self._meal_times_in(last, now)
        if meals:
            latest = meals[-1]
            if _parse(self.state.last_meal_applied, datetime.min) < latest:
                self.state.satiety = _clamp(
                    self.state.satiety + C.MEAL_RECOVERY, 0.0, 100.0
                )
                self.state.last_meal_applied = latest.strftime(ISO)

        # 起床（最後の1回だけ）
        wakes = self._wake_times_in(last, now)
        if wakes:
            latest = wakes[-1]
            if _parse(self.state.last_wake_applied, datetime.min) < latest:
                self.state.tension = 100.0
                self.state.last_wake_applied = latest.strftime(ISO)

        # 就寝帯はテンションの下限を固定
        lo, hi = C.SLEEP_HOURS
        if lo <= now.hour < hi:
            self.state.tension = max(self.state.tension, C.TENSION_SLEEP_FLOOR)

        # 退屈度
        since = (now - _parse(self.state.last_interaction_time, now)).total_seconds()
        self.state.boredom = _clamp(since / C.BOREDOM_FULL_SEC, 0.0, 1.0)

        self.state.last_tick_time = now.strftime(ISO)
        self._dirty = True

    # ------------------------------------------------------------ 時間帯挨拶の記録

    def greeted_today(self, slot: str, today: str) -> bool:
        """そのスロットの挨拶を今日すでに言ったか。"""
        slots = self.state.greeted_slots
        return isinstance(slots, dict) and slots.get(slot) == today

    def mark_greeted(self, slot: str, today: str) -> None:
        """そのスロットの挨拶を今日言ったと記録する。"""
        if not isinstance(self.state.greeted_slots, dict):
            self.state.greeted_slots = {}
        self.state.greeted_slots[slot] = today
        self._dirty = True

    def record_interaction(self, now: datetime | None = None) -> None:
        """会話1回ぶん。好感度は affinity.py が別に処理する。"""
        now = now or _now()
        self.state.last_interaction_time = now.strftime(ISO)
        self.state.boredom = 0.0
        self.state.tension = _clamp(self.state.tension + 1.0, 0.0, 100.0)
        self._dirty = True

    def set_emotion(self, score: float) -> None:
        self.state.emotion = _clamp(score, -1.0, 1.0)
        self._dirty = True

    # ------------------------------------------------------------ 参照

    def snapshot(self) -> dict:
        return asdict(self.state)
