"""Alice Solo の定数とパス解決。

仕様書 v2.0 付録A に対応する。値を変えるときは仕様書も直すこと。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Alice"

# ---------------------------------------------------------------- パス解決

def _package_dir() -> Path:
    """同梱アセットの置き場。PyInstaller の onefile にも対応する。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


PACKAGE_DIR = _package_dir()


def _assets_dir() -> Path:
    """assets の置き場を探す。

    開発時はリポジトリ直下（alice-solo/assets）に置き、配布時は
    パッケージ内（alice_solo/assets）に同梱する。どちらでも動くよう
    両方を見る。
    """
    for cand in (PACKAGE_DIR / "assets", PACKAGE_DIR.parent / "assets"):
        if (cand / "characters").is_dir() or (cand / "config.yaml").is_file():
            return cand
    return PACKAGE_DIR / "assets"


ASSETS_DIR = _assets_dir()
BUNDLED_CHARACTERS_DIR = ASSETS_DIR / "characters"
CONFIG_YAML = ASSETS_DIR / "config.yaml"


def app_data_dir() -> Path:
    """%APPDATA%/Alice。Windows 以外では ~/.local/share/Alice に落とす。"""
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


DATA_DIR = app_data_dir()
SELF_DIR = DATA_DIR / "self"
NEWS_DIR = DATA_DIR / "news"
USER_CHARACTERS_DIR = DATA_DIR / "characters"

STATE_FILE = DATA_DIR / "state.json"
USER_CONFIG_FILE = DATA_DIR / "user_config.json"
WINDOW_POS_FILE = DATA_DIR / "window_pos.json"
DB_FILE = DATA_DIR / "local_store.db"
# 表示倍率は user_config.json に持つ（window_scale.json は廃止）

AFFINITY_FILE = SELF_DIR / "affinity.json"
CHARACTER_STATE_FILE = SELF_DIR / "character.json"
MOOD_FILE = SELF_DIR / "mood.json"
DAY_WEATHER_FILE = SELF_DIR / "day_weather.json"

NEWS_HTML = NEWS_DIR / "today_news.html"


def ensure_dirs() -> None:
    for d in (DATA_DIR, SELF_DIR, NEWS_DIR, USER_CHARACTERS_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- A.1 状態

SATIETY_DECAY_PER_SEC = 0.00463   # 6時間で 100 -> 0
TENSION_DECAY_PER_SEC = 0.01389   # 2時間で 100 -> 0

MEAL_RECOVERY = 35.0
MEAL_HOURS = ((7, 30), (12, 30), (19, 0))
WAKE_HOUR = 7
NIGHT_DECAY_START_HOUR = 22
NIGHT_DECAY_FACTOR = 2.0
SLEEP_HOURS = (2, 6)              # [2:00, 6:00) はテンション下限を固定
TENSION_SLEEP_FLOOR = 20.0

BOREDOM_FULL_SEC = 2700           # 45分で boredom = 1.0
STATE_TICK_MS = 30_000
STATE_SAVE_DEBOUNCE_MS = 2_000

# ---------------------------------------------------------------- A.2 感情

WEIGHT_TEXT = 0.5
WEIGHT_SATIETY = 0.2
WEIGHT_TENSION = 0.2
WEIGHT_BOREDOM = 0.1
TEXT_POLARITY_MAGNITUDE = 0.7

# 打ち消し（改善仕様書 §3.3）。極性語の直後 NEGATION_WINDOW 文字以内に
# これらが現れたら、その語の極性を無効化する（反転ではない）。
# 「〜ない」単独は対象にしない。「疲れたくない」のような願望の否定と
# 区別がつかず、誤判定が増えるため。
NEGATION_WORDS = ("じゃない", "ではない", "わけじゃない", "じゃありません",
                  "ではありません", "じゃなかった", "ではなかった")
NEGATION_WINDOW = 4

EMOTION_CATEGORIES = (
    "happy_strong", "happy_weak", "neutral", "anxious",
    "sad", "angry", "shy", "drowsy", "sleepy",
)

# ---------------------------------------------------------------- A.3 好感度

AFFINITY_INITIAL = 30.0
AFFINITY_GAIN_TALK = 0.5
AFFINITY_GAIN_POSITIVE = 1.0
AFFINITY_GAIN_STREAK = 1.0
AFFINITY_DAILY_CAP = 10.0
AFFINITY_IDLE_DECAY_PER_DAY = 3.0

TIER_UP_ACCEPT = 40.0
TIER_DOWN_ACCEPT = 35.0
TIER_UP_EMPATHY = 75.0
TIER_DOWN_EMPATHY = 70.0

TIERS = ("guard", "accept", "empathy")
DEFAULT_TIER = "accept"

# ---------------------------------------------------------------- A.4 自我

DAY_START_HOUR = 5

HABIT_GAIN = 0.04
HABIT_HEADROOM = 0.3
EVENT_STEP = 0.08
RETURN_RATE = 0.05
MAX_GAP_DAYS = 30
MAX_KEYS = 200
REMARK_DELTA = 0.10
REMARK_COOLDOWN_DAYS = 3
MOOD_CHANCE = 0.35
MOOD_THRESHOLD = 0.20

# ---------------------------------------------------------------- A.5 対話

# 発話プール1キーあたりの最低件数。3件だと重複除外の履歴長が2件になり
# 実質ローテーションになるため、5件を下限とする（改善仕様書 §3.1）。
PHRASE_MIN_COUNT = 5

OPENER_PROBABILITY = 0.25
REMARK_PROBABILITY = 0.5
DECORATE_MAX_LEN = 80
TALK_RATE_SKIP = {"low": 0.5, "normal": 0.15, "high": 0.0}
TIER_TALK_RATE = {"guard": "low", "accept": "normal", "empathy": "normal"}
# 気分による枕（改善仕様書 §3.5）
MOOD_REMARK_PROBABILITY = 0.5          # shizumi / darui の日に気分の枕が付く確率
MOOD_OPENER_PROBABILITY_GENKI = 0.4    # genki / jougen の日の opener 確率

IDLE_LONELY_BOREDOM_MIN = 0.5
IDLE_TALK_CHECK_MS = 180_000
# 深夜帯（late）は声かけを間引く。2 なら2回に1回だけ抽選する（§3.2）。
IDLE_TALK_LATE_SKIP = 2

# 「覚えている」会話（§3.4）
MEMORY_MAX_ITEMS = 50
MEMORY_CALLBACK_MIN_DAYS = 2
MEMORY_CALLBACK_MAX_DAYS = 7
MEMORY_CALLBACK_COOLDOWN_DAYS = 3
MEMORY_MAX_MENTIONS = 3

# チャット履歴（§5）
CHAT_LOG_MAX_PER_DAY = 200

# ---------------------------------------------------------------- A.6 表示

REFERENCE_CONTENT_HEIGHT = 880.0
UTTERANCE_DISPLAY_MS = 4_000
UTTERANCE_DISPLAY_MAX_MS = 10_000


def utterance_display_ms(text: str) -> int:
    """吹き出しの表示時間（ms）。文字数連動：文字数×0.15秒＋2秒。

    下限は UTTERANCE_DISPLAY_MS（4秒）、上限は 10秒。
    吹き出し（vpet.say）と話し中リセット（main.py の talk_reset）の
    両方でこの関数を使うこと（表示と talking 状態のズレ防止）。
    """
    ms = int(len(text or "") * 150 + 2_000)
    return max(UTTERANCE_DISPLAY_MS, min(UTTERANCE_DISPLAY_MAX_MS, ms))
SETTLE_MS = 800
SPRITE_CACHE_SIZE = 3

# HUD（§4）
HUD_WIDTH = 240
HUD_HEIGHT = 196
TIER_UP_BUBBLE_BORDER_COLOR = "#e07856"   # 層が上がった日の吹き出し枠（暫定値）

# 瞬き（§6.2）
BLINK_INTERVAL_MIN_MS = 3_000
BLINK_INTERVAL_MAX_MS = 7_000
BLINK_DURATION_MS = 200

# 深夜のオーバーレイ（§6.3）。暫定値。
LATE_OVERLAY_RGBA = (40, 60, 120, 31)     # 0.12 * 255 ≒ 31

# 画面端への吸着（§8）
SNAP_DISTANCE_PX = 12
SCALE_MIN = 0.2
SCALE_MAX = 3.0
SCALE_STEP = 0.1
SCALE_DEFAULT = 1.0

# ---------------------------------------------------------------- A.7 その他

WEATHER_TIMEOUT_SEC = 3
WEATHER_REFRESH_INTERVAL_MS = 3_600_000
METRICS_INTERVAL_MS = 300_000
MEDIA_INTERVAL_MS = 10_000
NEWS_HOUR = 9
NEWS_TIMEOUT_SEC = 5
NEWS_MAX_ITEMS = 10
INBOX_RETENTION_DAYS = 30
INBOX_PURGE_HOUR = 10
DB_VACUUM_THRESHOLD_BYTES = 10_485_760


# ---------------------------------------------------------------- 同梱設定

_app_config_cache: dict | None = None


def load_app_config() -> dict:
    """assets/config.yaml（同梱既定値）。実行時に書き換えない。"""
    global _app_config_cache
    if _app_config_cache is not None:
        return _app_config_cache
    data: dict = {}
    try:
        import yaml
        if CONFIG_YAML.is_file():
            with CONFIG_YAML.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
    except Exception:
        data = {}
    _app_config_cache = data
    return data


# ---------------------------------------------------------------- 設定の取り出し
#
# 運用値（タイムアウト・間隔・しきい値・保持期間）は assets/config.yaml を
# 正とする。このファイルの定数は、config.yaml に無い／読めないときの
# フォールバック値である（改善仕様書 §7.2）。
# **値を変えるときは config.yaml を変えること。**

def app_value(path: str, fallback=None):
    """config.yaml から "news.max_items" のような道で値を取る。

    欠けていれば fallback を返す。config.yaml が壊れていても落ちない。
    """
    node = load_app_config()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return fallback
        node = node[part]
    return node if node is not None else fallback
