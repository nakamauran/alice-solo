"""対話エンジン。仕様書 v2.0 §5。

意図判定は上から順に評価し、当たった時点で返す。
返事は「枕・本題・尾ひれ」の3段で組み立てる。
レラ・ファイル探索・選曲・ホスト操作・電車の判定は持たない。
"""
from __future__ import annotations

import random
import re
from datetime import datetime

from .. import config as C
from . import emotion_engine as E
from .phrase_pool import PhrasePool
from .self_engine import calendar_ja

# ---------------------------------------------------------------- 語彙

TIME_KEYWORDS = (
    "今何時", "いま何時", "なんじ", "何時", "時刻", "時間を教え",
    "いまなんじ", "time",
)
TIME_EXCLUDE = ("何時から", "何時まで", "何時ごろ", "時間がない", "時間ある")

WEATHER_KEYWORDS = (
    "天気", "てんき", "気温", "きおん", "暑い", "寒い",
    "雨", "あめ", "雪", "ゆき", "晴れ", "はれ", "曇", "くもり",
    "傘", "かさ", "weather",
)
FORECAST_HINTS = (
    "明日", "あした", "あす", "明後日", "予報", "これから",
    "午後", "夕方", "今夜", "今晩", "週末", "土日",
)

GREETING_KEYWORDS = (
    "おはよ", "こんにち", "こんばん", "やあ", "やっほ", "ハロー", "はろー",
    "hello", "hi", "ただいま", "おかえり", "おやすみ", "またね",
    "ばいばい", "バイバイ", "さようなら", "お疲れ", "おつかれ",
)

# 「ただいま／おかえり」「バイバイ」は挨拶とは別に判定し、先に引く。
HOME_KEYWORDS = ("ただいま", "おかえり")
BYE_KEYWORDS = ("ばいばい", "さようなら", "さよなら", "またね", "じゃあね",
                "いってきます", "いってらっしゃい")

# 相づち。発話全体がこれと一致したときだけ「相づち」とみなす（部分一致にしない）。
FOLLOW_UP_ACK_WORDS = (
    "うん", "うんうん", "そうだね", "そうなんだ", "そっか", "なるほど",
    "へえ", "ふーん", "ふうん", "ああ", "はい", "ええ",
)

# 「覚えている」会話の収集パターン（§3.4）。
# 抽出は欲張らない。外すと的外れな呼び戻しになって逆効果なので、
# はっきりした言い回しだけを拾う。
LIKE_PATTERNS = (
    re.compile(r"([^\s、。!?！？]{2,8})(?:が|は)?大好き"),
    re.compile(r"([^\s、。!?！？]{2,8})(?:が|は)好き"),
)
NAME_PATTERNS = (
    re.compile(r"(?:わたし|私|ぼく|僕|おれ|俺)は([^\s、。!?！？]{1,10}?)(?:です|だよ|だ)?$"),
    re.compile(r"([^\s、。!?！？]{1,10}?)(?:って|と)呼んで"),
)
# 抽出の末尾に残りやすい助詞・語尾。覚える前に落とす。
MEMORY_TRAILING = ("が", "は", "も", "を", "の", "って", "です", "だよ", "だ")
# 対象から外す語。これ自体を「好きなもの」として覚えても意味がない。
MEMORY_STOPWORDS = {
    "好き", "大好き", "嫌い", "それ", "これ", "あれ", "なに", "何",
    "きみ", "君", "あなた", "わたし", "私", "ぼく", "僕",
}

# 天気テキストから引く天気別のキー
WEATHER_TEXT_KEYS = (
    ("晴", "weather_sunny"),
    ("雨", "weather_rain"),
    ("曇", "weather_cloudy"),
    ("くもり", "weather_cloudy"),
    ("雪", "weather_snow"),
)

SLOT_TO_GREETING_KEY = {
    "morning": "greeting_slot.morning",
    "night": "greeting_slot.night",
    "late": "greeting_slot.late",
}


def slot_of(now: datetime | None = None) -> str:
    """時間帯スロット。仕様書 §4.4.2。calendar_ja へ委譲（重複解消）。"""
    return calendar_ja.slot_of(now)


def _hit(text: str, words) -> bool:
    return any(w in text for w in words)


# ---------------------------------------------------------------- 本体

class DialogueEngine:
    def __init__(self, pool: PhrasePool, affinity, state_manager,
                 character=None, weather_provider=None, mood=None,
                 rng: random.Random | None = None):
        self.pool = pool
        self.affinity = affinity
        self.state = state_manager
        self.character = character or {}
        self.weather_provider = weather_provider   # フェーズ4で差し込む
        self.mood = mood                            # 気分連動（§3.5）
        self.rng = rng or random.Random()
        self._pending_remarks: list[str] = []
        self._greeted_mem: dict[str, str] = {}   # state に記録できない場合の予備
        self._long_time_said_date: str | None = None  # 久しぶりは1日1回まで
        # 直近1往復だけ覚える（§3.6）。相づちへの返しに使う。
        self._last_intent: str | None = None
        self._last_category: str | None = None
        # 層が上がった直後に1回だけ使うフラグ（§3.5 台本）
        self._tier_up_pending = False

    # ------------------------------------------------------------ 差し込み

    def _fields(self, now: datetime) -> dict:
        return {
            "name": self.character.get("display_name", ""),
            "me": self.character.get("first_person", "わたし"),
            "time": now.strftime("%H時%M分"),
        }

    # ------------------------------------------------------------ 入口

    def handle_user_message(self, text: str, now: datetime | None = None) -> dict:
        """返事と、そのとき表示すべき感情カテゴリを返す。"""
        now = now or datetime.now()
        norm = E.normalize(text)

        s = self.state.state
        value, category = E.evaluate(text, s.satiety, s.tension, s.boredom, now)
        self.state.set_emotion(value)
        self.state.record_interaction(now)

        positive = E.text_polarity(text) > 0
        self.affinity.on_interaction(positive=positive, now=now)

        tier = self.affinity.tier
        body, intent = self._intent_reply(norm, text, category, tier, now)
        reply = self._decorate(body, tier, now)

        self._last_intent = intent
        self._last_category = category if intent == "emotion" else None

        # 覚える（§3.4）。失敗しても返事は返す。
        try:
            self._collect_memories(text, now)
        except Exception:
            pass

        return {
            "reply": reply,
            "category": category,
            "score": value,
            "tier": tier,
            "intent": intent,
        }

    def notify_tier_up(self) -> None:
        """層が上がったことを伝える。次の1回だけ after_tier_up を返す。"""
        self._tier_up_pending = True

    # ------------------------------------------------------------ 意図判定

    def _intent_reply(self, norm: str, raw: str, category: str, tier: str,
                      now: datetime) -> tuple[str, str]:
        """(本題, 当たった意図) を返す。意図は follow_up の判定に使う。"""
        f = self._fields(now)

        # 0. 層が上がった直後の1回だけ
        if self._tier_up_pending:
            self._tier_up_pending = False
            said = self.pool.pick("after_tier_up", tier, **f)
            if said:
                return said, "tier_up"

        # 0.5 相づち。直前の話題を踏まえて返す（§3.6）
        if norm.strip("。、！？!? ") in FOLLOW_UP_ACK_WORDS and self._last_intent:
            said = self._follow_up_reply(tier, f)
            if said:
                return said, self._last_intent

        # 1. 時刻。スロット別を先に試す
        if _hit(norm, TIME_KEYWORDS) and not _hit(norm, TIME_EXCLUDE):
            slot = slot_of(now)
            said = (self.pool.pick(f"time_answer_slot.{slot}", tier, **f)
                    or self.pool.pick("time_answer", tier, **f))
            return (said or f"{f['time']}。"), "time"

        # 2 / 3. 天気
        if _hit(norm, WEATHER_KEYWORDS):
            forecast = _hit(norm, FORECAST_HINTS)
            said = self._weather_reply(forecast, tier, f)
            if said:
                return said, "weather"

        # 4. 挨拶。ただいま／バイバイは時間帯挨拶より先に引く
        if _hit(norm, HOME_KEYWORDS):
            said = self.pool.pick("greeting_home", tier, **f)
            if said:
                return said, "greeting"
        if _hit(norm, BYE_KEYWORDS):
            said = self.pool.pick("greeting_bye", tier, **f)
            if said:
                return said, "greeting"
        if _hit(norm, GREETING_KEYWORDS):
            key = SLOT_TO_GREETING_KEY.get(slot_of(now), "greeting")
            said = self.pool.pick(key, tier, **f) or self.pool.pick("greeting", tier, **f)
            if said:
                return said, "greeting"

        # 5. 感情応答。打ち消し・両極性は専用のキーに回す
        if E.has_negation(raw):
            said = self.pool.pick("emotion_response.negated", tier, **f)
            if said:
                return said, "emotion"
        if E.is_mixed(raw):
            said = self.pool.pick("emotion_response.mixed", tier, **f)
            if said:
                return said, "emotion"

        said = self.pool.pick(f"emotion_response.{category}", tier, **f)
        if said:
            return said, "emotion"
        return (self.pool.pick("emotion_response.neutral", tier, **f) or "……。"), "emotion"

    def _follow_up_reply(self, tier: str, f: dict) -> str | None:
        """相づちへの返し。直前が感情応答なら、そのカテゴリで返す。"""
        if self._last_intent == "emotion" and self._last_category:
            return self.pool.pick(
                f"emotion_response.{self._last_category}", tier, **f
            )
        return self.pool.pick(f"follow_up.{self._last_intent}", tier, **f)

    def _weather_reply(self, forecast: bool, tier: str, f: dict) -> str | None:
        if self.weather_provider is None:
            return self.pool.pick("weather_unavailable", tier, **f) \
                or "いまは分からない。"
        try:
            data = self.weather_provider.forecast() if forecast \
                else self.weather_provider.current()
        except Exception:
            data = None
        if not data:
            return self.pool.pick("weather_unavailable", tier, **f) \
                or "いまは分からない。"

        text = data.get("text", "") or ""
        temp = data.get("temp", "")
        if temp is None:
            temp = ""
        extra = {"weather": text, "temp": temp, **f}

        if forecast:
            return self.pool.pick("weather_forecast", tier, **extra)

        # 天気別の言い回しを優先する
        for needle, key in WEATHER_TEXT_KEYS:
            if needle in text:
                said = self.pool.pick(key, tier, **extra)
                if said:
                    return said
                break

        # 気温が取れないときは {temp} を使わない言い回しに逃がす
        if temp == "":
            said = self.pool.pick("weather_now_no_temp", tier, **extra)
            if said:
                return said

        return self.pool.pick("weather_now", tier, **extra)

    # ------------------------------------------------------------ 装飾

    def push_remark(self, text: str) -> None:
        """尾ひれとして言いたいことを溜める（好き嫌いの変動など）。"""
        if text and text not in self._pending_remarks:
            self._pending_remarks.append(text)

    def _decorate(self, body: str, tier: str, now: datetime) -> str:
        """枕と尾ひれを付ける。長い本題には付けない。"""
        if len(body) > C.DECORATE_MAX_LEN:
            return body

        f = self._fields(now)
        parts: list[str] = []

        # 気分による枕（§3.5）。沈んでいる日は寄り添いを前に出し、
        # 元気な日は枕そのものが付きやすくなる。
        label = getattr(self.mood, "label", "futsuu") if self.mood else "futsuu"
        if label in ("shizumi", "darui") \
                and self.rng.random() < C.MOOD_REMARK_PROBABILITY:
            said = self.pool.pick(f"mood.{label}", tier, **f)
            if said:
                parts.append(said)

        opener_p = (C.MOOD_OPENER_PROBABILITY_GENKI
                    if label in ("genki", "jougen") else C.OPENER_PROBABILITY)
        if self.rng.random() < opener_p:
            opener = self.pool.pick("opener", tier, **f)
            if opener:
                parts.append(opener)

        parts.append(body)

        if self._pending_remarks and self.rng.random() < C.REMARK_PROBABILITY:
            parts.append(self._pending_remarks.pop(0))

        return " ".join(parts)

    # ------------------------------------------------------------ 自発発話

    def idle_phrase(self, now: datetime | None = None,
                    mood_label: str | None = None,
                    talk_bias: float = 0.0,
                    topic: str | None = None,
                    weather_changed: bool = False,
                    launch_gap: int = 0) -> str | None:
        """自分から話す。まず黙るかを決める。仕様書 §5.3。

        順番：(1)時間帯の挨拶（同じスロットは1日1回まで）→(2)天気が変わった
        →(3)久しぶり（前回起動から3日以上）→(4)その日の気分→(5)話題
        →(7)かまって。(6)好き嫌いが動いた話は尾ひれ（push_remark）で回す。
        """
        now = now or datetime.now()
        tier = self.affinity.tier
        rate = C.TIER_TALK_RATE.get(tier, "normal")
        skip = C.TALK_RATE_SKIP.get(rate, 0.15) + max(-0.2, min(0.2, talk_bias))
        if self.rng.random() < skip:
            return None

        f = self._fields(now)
        s = self.state.state
        today = now.strftime("%Y-%m-%d")

        # 1. 時間帯の挨拶（同じスロットは1日1回まで。2回目以降は下へ回す）
        slot = slot_of(now)
        if slot in SLOT_TO_GREETING_KEY and not self._greeted(slot, today):
            said = self.pool.pick(SLOT_TO_GREETING_KEY[slot], tier, **f)
            if said:
                self._mark_greeted(slot, today)
                return said

        # 2. 天気が変わった
        if weather_changed:
            said = self.pool.pick("weather_changed", tier, **f)
            if said:
                return said

        # 3. 久しぶり（前回起動から3日以上。1日1回まで）
        if launch_gap >= 3 and self._long_time_said_date != today:
            said = self.pool.pick("long_time_no_see", tier, **f)
            if said:
                self._long_time_said_date = today
                return said

        # 4. その日の気分
        if mood_label:
            said = self.pool.pick(f"mood.{mood_label}", tier, **f)
            if said:
                return said

        # 5. 手元のデータから拾った話題
        if topic:
            return topic

        # 7. かまって
        if s.boredom >= C.IDLE_LONELY_BOREDOM_MIN:
            said = self.pool.pick("idle_lonely", tier, **f)
            if said:
                return said

        return None

    # ------------------------------------------------------------ 挨拶の回数制限

    def _greeted(self, slot: str, today: str) -> bool:
        """そのスロットの挨拶を今日すでに言ったか（state.json に記録）。"""
        fn = getattr(self.state, "greeted_today", None)
        if callable(fn):
            try:
                return bool(fn(slot, today))
            except Exception:
                pass
        return self._greeted_mem.get(slot) == today

    def _mark_greeted(self, slot: str, today: str) -> None:
        """そのスロットの挨拶を今日言ったと記録する。"""
        fn = getattr(self.state, "mark_greeted", None)
        if callable(fn):
            try:
                fn(slot, today)
                return
            except Exception:
                pass
        self._greeted_mem[slot] = today

    # ------------------------------------------------------------ 記憶（§3.4）

    @staticmethod
    def _clean_thing(word: str) -> str:
        """抽出した語から、末尾に残った助詞・語尾を落とす。

        「猫が大好き」から「猫が」を、「わたしは中村です」から「中村です」を
        拾ってしまうため、後ろから削る。
        """
        word = (word or "").strip()
        changed = True
        while changed and word:
            changed = False
            for suffix in MEMORY_TRAILING:
                if len(word) > len(suffix) and word.endswith(suffix):
                    word = word[: -len(suffix)]
                    changed = True
                    break
        return word

    def _collect_memories(self, text: str, now: datetime) -> None:
        """発話から「好きなもの」と「名前」を拾って覚える。

        store が無ければ何もしない。抽出できなくても黙って通す。
        """
        store = getattr(self, "memory_store", None)
        if store is None:
            return

        norm = E.normalize(text)

        for pattern in LIKE_PATTERNS:
            m = pattern.search(norm)
            if not m:
                continue
            thing = self._clean_thing(m.group(1))
            if len(thing) < 2 or thing in MEMORY_STOPWORDS:
                break
            store.save_memory("like", thing, thing, now)
            break

        for pattern in NAME_PATTERNS:
            m = pattern.search(norm)
            if not m:
                continue
            name = self._clean_thing(m.group(1))
            if not name or name in MEMORY_STOPWORDS:
                break
            # 名前は1人ぶんだけ持つ。言い直されたら上書きする。
            store.save_memory("name", "user", name, now)
            break
