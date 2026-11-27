"""天気。Open-Meteo（APIキー不要）。仕様書 v2.0 §6.1。

取得は1日1回ぶんをまとめて行い、self/day_weather.json に控える。
失敗しても対話や抽選は止めない。前日の控えがあればそれを使い、
それも無ければ天気の話題だけ黙る。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import requests

from .. import config as C
from ..engine.self_engine import calendar_ja as cal
from ..engine.self_engine import store

DEFAULT_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
# 後方互換。参照していた箇所のために残す。
ENDPOINT = DEFAULT_ENDPOINT

# 朝・昼・夕・夜の4区分。夜は24時で切る（翌日に食い込ませない）。
SLOTS: list[tuple[str, str, int, int]] = [
    ("morning", "朝", 6, 11),
    ("daytime", "昼", 11, 17),
    ("evening", "夕方", 17, 21),
    ("night", "夜", 21, 24),
]


def _slot_now(hour: int) -> str:
    # 0〜4時は夜。5時は朝（6時からの morning につなぐ）。
    if hour < 5 or hour >= 21:
        return "night"
    for key, _label, start, end in SLOTS:
        if start <= hour < end:
            return key
    return "morning"


class WeatherService:
    def __init__(self, location: dict | None = None, path: Path | None = None):
        self.path = Path(path) if path else C.DAY_WEATHER_FILE
        self.location = location or {"label": "東京都",
                                     "latitude": 35.6895, "longitude": 139.6917}
        self.data = store.read_json(self.path, {})

    # ------------------------------------------------------------ 取得

    def set_location(self, location: dict) -> None:
        if location and location.get("latitude") is not None:
            self.location = location
            self.data = {}          # 地点が変わったら控えは捨てる

    def fetch(self, now: datetime | None = None) -> bool:
        """通信する。UIスレッドから直接呼ばないこと。成功したら True。"""
        now = now or datetime.now()
        endpoint = C.app_value("weather.endpoint", DEFAULT_ENDPOINT)
        timezone = C.app_value("weather.timezone", "Asia/Tokyo")
        timeout = C.app_value("weather.timeout_sec", C.WEATHER_TIMEOUT_SEC)
        params = {
            "latitude": self.location.get("latitude"),
            "longitude": self.location.get("longitude"),
            "hourly": "temperature_2m,weather_code",
            "current": "temperature_2m,weather_code",
            "forecast_days": 2,
            "timezone": timezone,
        }
        try:
            r = requests.get(endpoint, params=params, timeout=timeout)
            r.raise_for_status()
            raw = r.json()
        except Exception:
            return False

        parsed = self._parse(raw, now)
        if not parsed:
            return False
        parsed["label"] = self.location.get("label", "")
        parsed["date"] = store.today_key(now)
        self.data = parsed
        store.write_json(self.path, self.data)
        return True

    @staticmethod
    def _parse(raw: dict, now: datetime) -> dict | None:
        hourly = raw.get("hourly") or {}
        times = hourly.get("time") or []
        temps = hourly.get("temperature_2m") or []
        codes = hourly.get("weather_code") or []
        if not times:
            return None

        today = now.strftime("%Y-%m-%d")
        buckets: dict[str, dict] = {}
        for key, _label, start, end in SLOTS:
            picked_t, picked_c = [], []
            for i, ts in enumerate(times):
                if not ts.startswith(today):
                    continue
                try:
                    hour = int(ts[11:13])
                except (ValueError, IndexError):
                    continue
                if start <= hour < end:
                    if i < len(temps) and temps[i] is not None:
                        picked_t.append(float(temps[i]))
                    if i < len(codes) and codes[i] is not None:
                        picked_c.append(int(codes[i]))
            if not picked_c:
                continue
            # その区分で最も多く出た天気コードを代表にする
            code = max(set(picked_c), key=picked_c.count)
            buckets[key] = {
                "code": code,
                "key": cal.weather_key(code),
                "text": cal.label_of(cal.weather_key(code) or ""),
                "temp": round(sum(picked_t) / len(picked_t)) if picked_t else None,
            }

        cur = raw.get("current") or {}
        current = None
        if cur.get("weather_code") is not None:
            k = cal.weather_key(int(cur["weather_code"]))
            temp_raw = cur.get("temperature_2m")
            try:
                temp = round(float(temp_raw)) if temp_raw is not None else None
            except (TypeError, ValueError):
                temp = None
            current = {
                "code": int(cur["weather_code"]),
                "key": k,
                "text": cal.label_of(k or ""),
                "temp": temp,
            }

        if not buckets and not current:
            return None
        return {"slots": buckets, "current": current}

    # ------------------------------------------------------------ 参照

    @property
    def is_today(self) -> bool:
        return bool(self.data) and self.data.get("date") == store.today_key()

    def _is_fresh(self, now: datetime) -> bool:
        """控えの日付が今日・昨日なら使う。日付が無ければ古いものとみなす。"""
        date = self.data.get("date")
        if not date:
            return False
        today = store.today_key(now)
        yesterday = store.today_key(now - timedelta(days=1))
        return date in (today, yesterday)

    def current(self, now: datetime | None = None) -> dict | None:
        """いまの天気。current が無ければ、いまの時間帯の区分で代用する。

        控えの日付が今日・昨日より古ければ None を返す（古い天気を答え続けない）。
        """
        if not self.data:
            return None
        now = now or datetime.now()
        if not self._is_fresh(now):
            return None
        cur = self.data.get("current")
        if cur:
            return cur
        return (self.data.get("slots") or {}).get(_slot_now(now.hour))

    def forecast(self, now: datetime | None = None) -> dict | None:
        """このあとの天気。残りの区分のうち最初のもの。無ければ夜。

        控えの日付が今日・昨日より古ければ None を返す。
        """
        if not self.data:
            return None
        now = now or datetime.now()
        if not self._is_fresh(now):
            return None
        slots = self.data.get("slots") or {}
        for key, label, start, _end in SLOTS:
            if start > now.hour and key in slots:
                out = dict(slots[key])
                out["slot_label"] = label
                return out
        return slots.get("night")

    def today_key(self) -> str | None:
        """likes に渡す天気キー。取得できていなければ None。"""
        cur = self.current()
        return cur.get("key") if cur else None
