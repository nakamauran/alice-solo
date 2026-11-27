"""暦。仕様書 v2.0 §4.4.2。

季節・行事・天気を「分類.名前」形式のキーに統一する。
好き嫌い（likes.py）はこのキーに対して値を持つので、キーの文字列を
変えると過去の蓄積が迷子になる。追加はしてよいが改名はしないこと。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

# ---------------------------------------------------------------- 季節

def season_key(d: date | datetime | None = None) -> str:
    m = (d or datetime.now()).month
    if m in (3, 4, 5):
        return "season.spring"
    if m in (6, 7, 8):
        return "season.summer"
    if m in (9, 10, 11):
        return "season.autumn"
    return "season.winter"


SEASON_LABELS = {
    "season.spring": "春",
    "season.summer": "夏",
    "season.autumn": "秋",
    "season.winter": "冬",
}

# ---------------------------------------------------------------- 行事

# (月, 日): キー。前日も「行事の日」として拾う。
_FIXED_EVENTS: dict[tuple[int, int], str] = {
    (1, 1): "event.newyear",
    (2, 3): "event.setsubun",
    (2, 14): "event.valentine",
    (3, 3): "event.hinamatsuri",
    (3, 14): "event.whiteday",
    (5, 5): "event.kodomo",
    (7, 7): "event.tanabata",
    (8, 15): "event.obon",
    (10, 31): "event.halloween",
    (11, 15): "event.shichigosan",
    (12, 24): "event.christmas",
    (12, 25): "event.christmas",
    (12, 31): "event.newyear_eve",
}

# 期間で判定するもの
_SEASON_EVENTS = [
    ((3, 25), (4, 10), "event.hanami"),
    ((6, 1), (6, 30), "event.tsuyu"),
    ((9, 15), (9, 30), "event.tsukimi"),
    ((11, 10), (11, 30), "event.koyo"),
]


def event_keys(d: date | datetime | None = None) -> list[str]:
    """その日に当たる行事キー。当日と前日を拾う。該当なしなら空。"""
    d = (d or datetime.now())
    if isinstance(d, datetime):
        d = d.date()
    out: list[str] = []

    # 当日と前日の両方を見る（前日が先に来ないよう当日を先に）。
    for day in (d, d - timedelta(days=1)):
        key = _FIXED_EVENTS.get((day.month, day.day))
        if key and key not in out:
            out.append(key)

        for (sm, sd), (em, ed), k in _SEASON_EVENTS:
            if (day.month, day.day) >= (sm, sd) and (day.month, day.day) <= (em, ed):
                if k not in out:
                    out.append(k)

    return out


EVENT_LABELS = {
    "event.newyear": "お正月",
    "event.newyear_eve": "大晦日",
    "event.setsubun": "節分",
    "event.valentine": "バレンタイン",
    "event.hinamatsuri": "ひな祭り",
    "event.whiteday": "ホワイトデー",
    "event.kodomo": "こどもの日",
    "event.tanabata": "七夕",
    "event.obon": "お盆",
    "event.halloween": "ハロウィン",
    "event.shichigosan": "七五三",
    "event.christmas": "クリスマス",
    "event.hanami": "お花見の時期",
    "event.tsuyu": "梅雨",
    "event.tsukimi": "お月見の時期",
    "event.koyo": "紅葉の時期",
}

# ---------------------------------------------------------------- 天気

# Open-Meteo の weather_code をまとめる。
_WMO_GROUPS = [
    ({0, 1}, "weather.sunny"),
    ({2, 3}, "weather.cloudy"),
    ({45, 48}, "weather.fog"),
    ({51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}, "weather.rain"),
    ({71, 73, 75, 77, 85, 86}, "weather.snow"),
    ({95, 96, 99}, "weather.storm"),
]


def weather_key(code: int | None) -> str | None:
    if code is None:
        return None
    for codes, key in _WMO_GROUPS:
        if code in codes:
            return key
    return "weather.cloudy"


WEATHER_LABELS = {
    "weather.sunny": "晴れ",
    "weather.cloudy": "くもり",
    "weather.rain": "雨",
    "weather.snow": "雪",
    "weather.fog": "霧",
    "weather.storm": "雷雨",
}

# ---------------------------------------------------------------- 時間帯

def slot_of(now: datetime | None = None) -> str:
    """morning / daytime / evening / night / late。仕様書 §4.4.2 の表。"""
    h = (now or datetime.now()).hour
    if 5 <= h < 11:
        return "morning"
    if 11 <= h < 17:
        return "daytime"
    if 17 <= h < 21:
        return "evening"
    if 21 <= h < 24:
        return "night"
    return "late"


WEEKDAY_LABELS = ("月", "火", "水", "木", "金", "土", "日")


def label_of(key: str) -> str:
    """暦キーを日本語に。未知のキーは末尾をそのまま返す。"""
    for table in (SEASON_LABELS, EVENT_LABELS, WEATHER_LABELS):
        if key in table:
            return table[key]
    return key.split(".")[-1]
