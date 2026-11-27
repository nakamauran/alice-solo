"""好感度と人格層。仕様書 v2.0 §4.3。

キャラ切り替えを廃止したことで、好感度は「人格の層を切り替える」役を
引き受けている。guard（防衛）/ accept（受容）/ empathy（共感）の3段。

設計上の要点:
  - 起動した日は減らさない。未起動日だけ減らす。常時減衰にすると
    毎日使っていても寝ている間に削られて層が往復する
  - 層の境界にヒステリシスを置き、上がる閾値と下がる閾値をずらす
  - 層が変わるのは1日1回まで。会話の途中で口調が変わらないようにする
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .. import config as C
from .self_engine import store


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


class Affinity:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else C.AFFINITY_FILE
        self.data = store.read_json(self.path, {
            "value": C.AFFINITY_INITIAL,
            "tier": "guard" if C.AFFINITY_INITIAL < C.TIER_UP_ACCEPT else C.DEFAULT_TIER,
            "tier_changed_date": "",
            "today_key": "",
            "today_gain": 0.0,
            "last_launch_date": "",
            "consecutive_days": 0,
        })

    # ------------------------------------------------------------ 参照

    @property
    def value(self) -> float:
        try:
            return float(self.data.get("value", C.AFFINITY_INITIAL))
        except (TypeError, ValueError):
            return C.AFFINITY_INITIAL

    @property
    def tier(self) -> str:
        t = self.data.get("tier")
        return t if t in C.TIERS else C.DEFAULT_TIER

    @property
    def talk_rate(self) -> str:
        return C.TIER_TALK_RATE.get(self.tier, "normal")

    def save(self) -> None:
        store.write_json(self.path, self.data)

    # ------------------------------------------------------------ 起動時

    def on_launch(self, now: datetime | None = None) -> dict:
        """未起動日の減衰・継続ボーナス・日次リセット・層判定をまとめて行う。

        戻り値は何が起きたかの控え。UI 側が「層が上がった」を拾うために使う。
        """
        now = now or datetime.now()
        today = store.today_key(now)
        last = self.data.get("last_launch_date") or ""
        result = {"decayed": 0.0, "streak_bonus": 0.0, "tier_before": self.tier,
                  "tier_after": self.tier, "tier_up": False, "gap_days": 0}

        # 未起動日ぶんの減衰（初回起動時は減らさない）
        if last:
            gap = store.day_distance(last, today)
            result["gap_days"] = max(0, gap)
            if gap >= 2:
                lost = (gap - 1) * C.AFFINITY_IDLE_DECAY_PER_DAY
                self.data["value"] = _clamp(self.value - lost)
                result["decayed"] = lost
            if gap == 1:
                self.data["value"] = _clamp(self.value + C.AFFINITY_GAIN_STREAK)
                result["streak_bonus"] = C.AFFINITY_GAIN_STREAK
                try:
                    streak = int(self.data.get("consecutive_days", 0))
                except (TypeError, ValueError):
                    streak = 0
                self.data["consecutive_days"] = streak + 1
            elif gap > 1:
                self.data["consecutive_days"] = 1
            # gap <= 0 は同日（または未来日付の起動）扱い。連続日数は変えない。
        else:
            self.data["consecutive_days"] = 1

        # 日次カウンタ
        if self.data.get("today_key") != today:
            self.data["today_key"] = today
            self.data["today_gain"] = 0.0

        self.data["last_launch_date"] = today
        before = self.tier
        self._reevaluate_tier(today)
        result["tier_before"] = before
        result["tier_after"] = self.tier
        result["tier_up"] = C.TIERS.index(self.tier) > C.TIERS.index(before)
        self.save()
        return result

    # ------------------------------------------------------------ 日付境界

    def on_day_rollover(self, now: datetime | None = None) -> bool:
        """朝5時をまたいだときに呼ぶ。層が上がったら True。"""
        today = store.today_key(now or datetime.now())
        if self.data.get("today_key") == today:
            return False
        self.data["today_key"] = today
        self.data["today_gain"] = 0.0
        # 起動しっぱなしで日をまたいでも、次回 on_launch() で
        # 「未起動日」扱いになって減衰しないよう当日へ更新する。
        self.data["last_launch_date"] = today
        before = self.tier
        self._reevaluate_tier(today)
        self.save()
        return C.TIERS.index(self.tier) > C.TIERS.index(before)

    # ------------------------------------------------------------ 増加

    def on_interaction(self, positive: bool = False,
                       now: datetime | None = None) -> float:
        """会話1回ぶん。1日の上限に達していたら 0 を返す。"""
        today = store.today_key(now or datetime.now())
        if self.data.get("today_key") != today:
            self.data["today_key"] = today
            self.data["today_gain"] = 0.0

        gain = C.AFFINITY_GAIN_POSITIVE if positive else C.AFFINITY_GAIN_TALK
        try:
            used = float(self.data.get("today_gain", 0.0))
        except (TypeError, ValueError):
            used = 0.0
        room = max(0.0, C.AFFINITY_DAILY_CAP - used)
        gain = min(gain, room)
        if gain <= 0.0:
            return 0.0

        self.data["value"] = _clamp(self.value + gain)
        self.data["today_gain"] = used + gain
        self.save()
        return gain

    # ------------------------------------------------------------ 層

    def _reevaluate_tier(self, today: str) -> None:
        """ヒステリシス付きの層判定。1日1回しか動かさない。"""
        if self.data.get("tier_changed_date") == today:
            return

        v = self.value
        cur = self.tier
        new = cur

        if cur == "guard":
            if v >= C.TIER_UP_ACCEPT:
                new = "accept"
        elif cur == "accept":
            if v >= C.TIER_UP_EMPATHY:
                new = "empathy"
            elif v < C.TIER_DOWN_ACCEPT:
                new = "guard"
        elif cur == "empathy":
            if v < C.TIER_DOWN_EMPATHY:
                new = "accept"

        if new != cur:
            self.data["tier"] = new
            self.data["tier_changed_date"] = today
