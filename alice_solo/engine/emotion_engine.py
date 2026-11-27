"""感情スコアの計算とカテゴリ分類。仕様書 v2.0 §4.2。

形態素解析も機械学習も使わない。語の有無だけで極性を決める。
"""
from __future__ import annotations

import unicodedata
from datetime import datetime

from .. import config as C

# ------------------------------------------------------------------ 語彙

POSITIVE_WORDS = (
    "好き", "すき", "嬉しい", "うれしい", "楽しい", "たのしい", "最高",
    "ありがとう", "感謝", "かわいい", "可愛い", "すごい", "えらい",
    "おもしろ", "面白", "よかった", "良かった", "助かる", "大好き",
    "がんばる", "頑張る", "やった", "笑", "www",
)

NEGATIVE_WORDS = (
    "嫌い", "きらい", "つらい", "辛い", "疲れ", "つかれ", "だるい",
    "しんどい", "うざい", "むかつく", "最悪", "だめ", "ダメ", "無理",
    "むり", "悲しい", "かなしい", "さみしい", "寂しい", "怒", "いらいら",
    "イライラ", "失敗", "めんどう", "面倒",
)

SHY_TRIGGERS = (
    "かわいい", "可愛い", "好き", "すき", "大好き", "愛して",
    "きれい", "綺麗", "美人", "似合", "褒め", "ほめ",
)
SLEEPY_TRIGGERS = ("おやすみ", "寝る", "ねる", "寝よ", "就寝", "布団", "ふとん")
DROWSY_TRIGGERS = ("眠い", "ねむい", "あくび", "眠たい", "うとうと")


def normalize(text: str) -> str:
    """NFKC 正規化 + 小文字化。全角英数はここで半角になる。"""
    return unicodedata.normalize("NFKC", text or "").lower()


def _negated_at(text: str, end: int) -> bool:
    """位置 end の直後に打ち消し語があるか。

    「好きじゃない」の「好き」のように、語の直後 NEGATION_WINDOW 文字以内に
    打ち消しが来たら、その語は無かったものとして扱う。反転はしない
    （「嫌いじゃない」を肯定にすると誤判定が増えるため）。
    """
    window = text[end:end + C.NEGATION_WINDOW + max(len(w) for w in C.NEGATION_WORDS)]
    return any(window.startswith(w) or w in window[:C.NEGATION_WINDOW + len(w)]
               for w in C.NEGATION_WORDS)


def _contains(text: str, words) -> bool:
    """打ち消されていない出現が1つでもあるか。"""
    for w in words:
        start = 0
        while True:
            i = text.find(w, start)
            if i < 0:
                break
            if not _negated_at(text, i + len(w)):
                return True
            start = i + 1
    return False


# ------------------------------------------------------------------ 極性

def text_polarity(text: str) -> float:
    """+0.7 / -0.7 / 0.0 の三値。両方含めば 0。

    打ち消し（「好きじゃない」）はその語を無かったことにする。
    肯定にも否定にもならないので、結果は 0 になる（改善仕様書 §3.3）。
    """
    t = normalize(text)
    pos = _contains(t, POSITIVE_WORDS)
    neg = _contains(t, NEGATIVE_WORDS)
    if pos and neg:
        return 0.0
    if pos:
        return C.TEXT_POLARITY_MAGNITUDE
    if neg:
        return -C.TEXT_POLARITY_MAGNITUDE
    return 0.0


def score(text: str, satiety: float, tension: float, boredom: float) -> float:
    """仕様書 §4.2.1 の計算式。"""
    v = (
        text_polarity(text) * C.WEIGHT_TEXT
        + ((satiety - 50.0) / 50.0) * C.WEIGHT_SATIETY
        + ((tension - 30.0) / 70.0) * C.WEIGHT_TENSION
        + (-boredom) * C.WEIGHT_BOREDOM
    )
    return max(-1.0, min(1.0, v))


# ------------------------------------------------------------------ 分類

def score_to_category(value: float, text: str = "", now: datetime | None = None) -> str:
    """トリガーがスコアより優先される。優先度は shy > sleepy > drowsy。"""
    t = normalize(text)

    # shy のトリガーにも打ち消しを効かせる（「好きじゃない」で照れない）
    if _contains(t, SHY_TRIGGERS):
        return "shy"
    if _contains(t, SLEEPY_TRIGGERS):
        return "sleepy"
    if _contains(t, DROWSY_TRIGGERS):
        return "drowsy"

    # late スロット（00:00-04:59）は既定を sleepy にする
    now = now or datetime.now()
    if now.hour < C.DAY_START_HOUR:
        return "sleepy"

    if value >= 0.6:
        return "happy_strong"
    if value >= 0.2:
        return "happy_weak"
    if value <= -0.6:
        return "angry"
    if value <= -0.3:
        return "sad"
    if value < -0.1:
        return "anxious"
    return "neutral"


def evaluate(text: str, satiety: float, tension: float, boredom: float,
             now: datetime | None = None) -> tuple[float, str]:
    """(スコア, カテゴリ) を返す。"""
    v = score(text, satiety, tension, boredom)
    return v, score_to_category(v, text, now)


def is_mixed(text: str) -> bool:
    """肯定語と否定語の両方を含むか。emotion_response.mixed の判定に使う。"""
    t = normalize(text)
    return _contains(t, POSITIVE_WORDS) and _contains(t, NEGATIVE_WORDS)


def has_negation(text: str) -> bool:
    """打ち消しによって極性が消された語があるか。

    emotion_response.negated の判定に使う。打ち消しが無ければ False。
    """
    t = normalize(text)
    for words in (POSITIVE_WORDS, NEGATIVE_WORDS):
        for w in words:
            start = 0
            while True:
                i = t.find(w, start)
                if i < 0:
                    break
                if _negated_at(t, i + len(w)):
                    return True
                start = i + 1
    return False
