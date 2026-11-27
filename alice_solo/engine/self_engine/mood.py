"""その日の気分。仕様書 v2.0 §4.4.4。

朝（日付境界の後）最初の呼び出しで2軸を決め、その日は固定する。
偶然の種は「キー:日付」から作るので、同じ日に何度呼んでも同じ値になる。
"""
from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

from ... import config as C
from . import store

# 曜日ごとの元気の下駄。月曜は下がり、金土は上がる。
WEEKDAY_ENERGY = (-0.15, 0.0, 0.0, 0.0, 0.10, 0.15, 0.0)   # 月〜日

# 前回起動からの空き日数 -> 快の補正。仕様書 §4.4.4。
# （キャラ切り替え廃止により AWAY_VALENCE を読み替えたもの）
LAUNCH_GAP_VALENCE = ((1, 0.05), (3, 0.10), (7, -0.10), (14, -0.20))

LABELS = ("genki", "jougen", "futsuu", "darui", "shizumi")


def gap_valence(gap_days: int) -> float:
    """空き日数に対応する補正。表の中で最も近い（超えない）段を使う。"""
    out = 0.0
    for days, value in LAUNCH_GAP_VALENCE:
        if gap_days >= days:
            out = value
    return out


def _chance(key: str, today: str) -> float:
    """再現性のある偶然。-CHANCE 〜 +CHANCE。"""
    rnd = random.Random(f"{key}:{today}")
    return (rnd.random() * 2.0 - 1.0) * C.MOOD_CHANCE


def classify(valence: float, energy: float) -> str:
    t = C.MOOD_THRESHOLD
    if valence >= t and energy >= t:
        return "genki"
    if valence >= t:
        return "jougen"
    if valence <= -t and energy <= -t:
        return "shizumi"
    if energy <= -t:
        return "darui"
    return "futsuu"


class Mood:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else C.MOOD_FILE
        self.data = store.read_json(self.path, {})

    def today(self, like: float = 0.0, gap_days: int = 0,
              now: datetime | None = None) -> dict:
        """その日の気分。既に決まっていればそれを返す。"""
        now = now or datetime.now()
        today = store.today_key(now)
        if self.data.get("date") == today:
            return self.data

        valence = 0.6 * like + gap_valence(gap_days) + _chance("valence", today)
        # 曜日下駄は「今日」（朝5時境）の日付の曜日から取る。
        # 深夜0〜5時は now.weekday() だと前日扱いになってしまうため。
        try:
            weekday = datetime.strptime(today, "%Y-%m-%d").weekday()
        except ValueError:
            weekday = now.weekday()
        energy = 0.2 * like + WEEKDAY_ENERGY[weekday] + _chance("energy", today)
        valence = max(-1.0, min(1.0, valence))
        energy = max(-1.0, min(1.0, energy))

        self.data = {
            "date": today,
            "valence": round(valence, 4),
            "energy": round(energy, 4),
            "label": classify(valence, energy),
        }
        store.write_json(self.path, self.data)
        return self.data

    @property
    def label(self) -> str:
        return self.data.get("label", "futsuu")

    def talk_bias(self) -> float:
        """口数の補正。genki で増え、darui / shizumi で減る。±0.2 まで。

        黙る確率に足す値なので、元気なときは負（黙りにくい）になる。
        """
        label = self.label
        if label == "genki":
            return -0.2
        if label == "jougen":
            return -0.1
        if label == "darui":
            return 0.15
        if label == "shizumi":
            return 0.2
        return 0.0
