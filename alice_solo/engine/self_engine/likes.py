"""好き嫌い。仕様書 v2.0 §4.4.3。

暦キー（weather.rain / season.winter / event.tanabata …）に対して
-1.0 〜 1.0 の値を持つ。

動きは2つだけ。
  慣れ: 触れた日は「生まれつき + HABIT_HEADROOM」へ向かって HABIT_GAIN 近づく
  戻り: 触れなかった日は「生まれつき」へ向かって RETURN_RATE ぶん戻る

値が REMARK_DELTA を超えて動いたら「言うこと」として溜める。
同じ話は REMARK_COOLDOWN_DAYS 日あける。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ... import config as C
from . import store


def _clamp(v: float) -> float:
    return max(-1.0, min(1.0, v))


def _is_valid_date(s) -> bool:
    """YYYY-MM-DD として読めれば True。"""
    if not isinstance(s, str):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return False
    return True


class Likes:
    def __init__(self, born: dict[str, float] | None = None,
                 path: Path | None = None):
        self.path = Path(path) if path else C.CHARACTER_STATE_FILE
        self.born = dict(born or {})
        self.data = store.read_json(self.path, {
            "likes": {},
            "last_daily": "",
            "remarks": [],       # [{"key":..., "text":..., "date":...}]
            "said": {},          # key -> 最後に言った日
        })
        self.data.setdefault("likes", {})
        self.data.setdefault("said", {})
        self.data.setdefault("remarks", [])

    # ------------------------------------------------------------ 参照

    def value(self, key: str) -> float:
        v = self.data["likes"].get(key)
        if v is None:
            return self._born(key)
        try:
            return _clamp(float(v))
        except (TypeError, ValueError):
            return self._born(key)

    def _born(self, key: str) -> float:
        if key not in self.born:
            return 0.0
        try:
            return float(self.born[key])
        except (TypeError, ValueError):
            # 生まれつき値が定義済みならその値を返す。数値でなければ
            # 呼び出し側の算術を壊さないよう 0.0 に落とす。
            v = self.born[key]
            return v if isinstance(v, (int, float)) else 0.0

    def save(self) -> None:
        self._trim()
        store.write_json(self.path, self.data)

    def _trim(self) -> None:
        """保持キー数の上限。生まれつき以外から、絶対値の小さい順に捨てる。"""
        likes = self.data["likes"]
        if len(likes) <= C.MAX_KEYS:
            return
        removable = [k for k in likes if k not in self.born]
        # float() 失敗時は value()（破損時は生まれつき値）で比べる。
        removable.sort(key=lambda k: abs(self.value(k) - self._born(k)))
        for k in removable[: len(likes) - C.MAX_KEYS]:
            likes.pop(k, None)

    # ------------------------------------------------------------ その日の値

    def today_value(self, weather: str | None, season: str | None,
                    events: list[str] | None = None) -> float:
        """加重平均。weather 3.0 / season 1.0 / event 1.0。"""
        num = den = 0.0
        if weather:
            num += self.value(weather) * 3.0
            den += 3.0
        if season:
            num += self.value(season) * 1.0
            den += 1.0
        for e in (events or []):
            num += self.value(e) * 1.0
            den += 1.0
        return num / den if den else 0.0

    # ------------------------------------------------------------ 日次更新

    def daily_update(self, touched: list[str], today: str) -> list[str]:
        """1日1回。触れたキーは慣れ、それ以外は生まれつきへ戻る。

        戻り値は、動きが大きくて「言うこと」になったキー。
        """
        last = self.data.get("last_daily") or ""
        if last == today:
            return []

        # 空きが長すぎる場合は戻しを打ち切る（何年ぶんも一気に戻さない）
        gap = max(1, min(C.MAX_GAP_DAYS, store.day_distance(last, today))) if last else 1

        likes = self.data["likes"]
        moved: list[str] = []
        touched_set = set(touched)

        keys = set(likes) | set(self.born) | touched_set
        for key in keys:
            before = self.value(key)
            born = self._born(key)

            if key in touched_set:
                # 慣れの天井は「生まれつき + HEADROOM」。嫌いなものは嫌いなまま
                ceiling = _clamp(born + C.HABIT_HEADROOM)
                if before < ceiling:
                    after = min(before + C.HABIT_GAIN, ceiling)
                elif before > ceiling:
                    # 天井より上にいるときも HABIT_GAIN ずつ下向きに近づける
                    after = max(before - C.HABIT_GAIN, ceiling)
                else:
                    after = before
            else:
                # 生まれつきへ戻る。空いた日数ぶんまとめて戻す
                after = before + (born - before) * (1 - (1 - C.RETURN_RATE) ** gap)

            after = _clamp(after)
            if abs(after - before) > 1e-9:
                likes[key] = after
            if abs(after - before) >= C.REMARK_DELTA:
                moved.append(key)

        self.data["last_daily"] = today
        self.save()
        return moved

    # ------------------------------------------------------------ 出来事

    def event(self, key: str, direction: int = 1) -> float:
        """出来事1回ぶん動かす。direction は +1 / -1。"""
        before = self.value(key)
        after = _clamp(before + C.EVENT_STEP * (1 if direction >= 0 else -1))
        self.data["likes"][key] = after
        self.save()
        return after - before

    # ------------------------------------------------------------ 言うこと

    def push_remark(self, key: str, text: str, today: str) -> bool:
        """同じ話は REMARK_COOLDOWN_DAYS 日あける。溜めたら True。"""
        remarks = self.data.get("remarks")
        if not isinstance(remarks, list):
            remarks = []
            self.data["remarks"] = remarks
        # 重複排除：同じキー・同じ文が既に溜まっていれば積まない
        if any(isinstance(r, dict) and r.get("key") == key
               and r.get("text") == text for r in remarks):
            return False
        said = self.data.get("said")
        if not isinstance(said, dict):
            said = {}
            self.data["said"] = said
        last = said.get(key)
        if last:
            # 日付パース失敗時はクールダウンなし扱い（壊れた日付で
            # 永久に言えなくならないようにする）
            if store.day_distance(last, today) < C.REMARK_COOLDOWN_DAYS \
                    and _is_valid_date(last) and _is_valid_date(today):
                return False
        remarks.append({"key": key, "text": text, "date": today})
        # 上限 10 件：古いものから捨てる
        while len(remarks) > 10:
            remarks.pop(0)
        self.save()
        return True

    def pop_remark(self, today: str) -> str | None:
        """溜めから1つ出す。出したらその話は寝かせる。"""
        remarks = self.data.get("remarks") or []
        if not remarks:
            return None
        item = remarks.pop(0)
        self.data["said"][item.get("key", "")] = today
        self.save()
        return item.get("text")

    @property
    def pending(self) -> int:
        return len(self.data.get("remarks") or [])
