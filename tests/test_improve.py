"""改善仕様書 v1.0 の受け入れ条件を確かめる。"""
import os, sys, tempfile, random
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
from pathlib import Path

# リポジトリの場所はこのファイルからたどる。絶対パスを書くと
# 別の環境で動かない。
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from datetime import datetime, timedelta
import importlib
import alice_solo.config as C; importlib.reload(C)
C.ensure_dirs()

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from alice_solo.engine import emotion_engine as E
from alice_solo.engine.phrase_pool import PhrasePool, REQUIRED_TIER_KEYS
from alice_solo.engine.dialogue_engine import DialogueEngine
from alice_solo.engine.affinity import Affinity
from alice_solo.engine.state_manager import StateManager
from alice_solo.engine.self_engine.topics import Topics
from alice_solo.db.local_store import LocalStore
from alice_solo.ui.theme import PRESETS, apply_preset, load_theme
from alice_solo.ui.screen_layout import snap_point

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {label} {extra}")
    else:    fail += 1; print(f"  FAIL {label} {extra}")

tmp = lambda n: Path(tempfile.mkdtemp()) / n
PACK = C.BUNDLED_CHARACTERS_DIR / "koyuki"
NOW = datetime(2026, 11, 27, 12, 0)

def engine(seed=1, mood=None, store=None):
    pool = PhrasePool(PACK / "phrases.yaml", rng=random.Random(seed))
    aff = Affinity(tmp("a.json"))
    de = DialogueEngine(pool, aff, StateManager(tmp("s.json")),
                        character={"display_name": "こゆき", "first_person": "わたし"},
                        mood=mood, rng=random.Random(seed))
    de.memory_store = store
    return de, pool, aff

print("== §3.1 発話プールの増量 ==")
pool = PhrasePool(PACK / "phrases.yaml")
w = pool.validate()
check("validate が警告を出さない", not w, w.report() if w else "")
check("最低件数は5", C.PHRASE_MIN_COUNT == 5)
short = [(t, k) for t in C.TIERS for k in REQUIRED_TIER_KEYS
         if len(pool.candidates(k, t)) < 5]
check("必須19キー×3層すべて5件以上", not short, short[:3])
seq = [pool.pick("emotion_response.neutral", "accept") for _ in range(20)]
check("同じ返しが連続しない", all(a != b for a, b in zip(seq, seq[1:])))
check("5種類以上が出る", len(set(seq)) >= 5, len(set(seq)))

print("== §3.3 否定・打ち消し ==")
for text, want in (("好き", 0.7), ("好きじゃない", 0.0), ("嫌いじゃない", 0.0),
                   ("嫌い", -0.7), ("疲れた", -0.7), ("疲れたくない", -0.7),
                   ("好きじゃないけど、楽しい", 0.7)):
    got = E.text_polarity(text)
    if abs(got - want) > 1e-9:
        check(f"極性 {text}", False, f"{got} != {want}"); break
else:
    check("仕様書の判定例7件すべて一致", True)
check("shy も打ち消される", E.score_to_category(0.0, "好きじゃない", NOW) != "shy")
check("打ち消しが無ければ shy", E.score_to_category(0.0, "かわいい", NOW) == "shy")
check("両極性の検出", E.is_mixed("嬉しいけどつらい") and not E.is_mixed("嬉しい"))

de, pool, aff = engine()
r = de.handle_user_message("好きじゃない", NOW)
check("打ち消しは negated の台詞", "じゃない" in r["reply"] or "違う" in r["reply"], r["reply"])
de, pool, aff = engine()
r = de.handle_user_message("嬉しいけどつらい", NOW)
check("両極性は mixed の台詞", r["reply"] in
      [x for x in pool.candidates("emotion_response.mixed", r["tier"])]
      or "どっち" in r["reply"], r["reply"])

print("== §3.2 自発発話 ==")
tp = Topics(PhrasePool(PACK / "phrases.yaml"), rng=random.Random(3))
class AllPC:
    def snapshot(self): return {"diagnostics": {"cpu": False}}
class AllMedia:
    def now_playing(self): return {"title": "曲A"}
tp2 = Topics(PhrasePool(PACK / "phrases.yaml"), pc_monitor=AllPC(),
             media_watcher=AllMedia(), rng=random.Random(3))
kinds = []
for i in range(12):
    tp2.pick("accept", datetime(2026, 11, 27, 13, 0))
    kinds.append(tp2._last_kind)
    tp2._said_song = None          # 曲は毎回言えるようにしておく
check("同じ話題が連続しない", all(a != b for a, b in zip(kinds, kinds[1:])), kinds[:6])
check("複数の話題が出る", len(set(kinds)) >= 2, set(kinds))
check("深夜の間引き定数", C.IDLE_TALK_LATE_SKIP == 2)

print("== §3.4 覚えている会話 ==")
db = LocalStore(tmp("m.db"))
de, pool, aff = engine(store=db)
de.handle_user_message("ラーメンが好き", NOW)
check("好きなものを覚える", db.get_memory("like", "ラーメン") is not None)
de.handle_user_message("こゆきって呼んで", NOW)
check("名前を覚える", (db.get_memory("name", "user") or {}).get("text") == "こゆき")
de.handle_user_message("それが好き", NOW)
check("指示語は覚えない", db.get_memory("like", "それ") is None)
check("直後は呼び戻さない", db.get_memory_candidates(NOW) == [])
check("2日後に呼び戻す", len(db.get_memory_candidates(NOW + timedelta(days=2))) == 1)
tp3 = Topics(PhrasePool(PACK / "phrases.yaml"), local_store=db, rng=random.Random(1))
said = tp3._memory("accept", NOW + timedelta(days=2), {"me": "わたし", "name": "こゆき"})
check("呼び戻しの台詞に対象が入る", said and "ラーメン" in said, said)
row = db.get_memory("like", "ラーメン")
check("言った回数が増える", int(row["mention_count"]) == 1)
for i in range(60):
    db.save_memory("like", f"もの{i}", f"もの{i}", NOW)
with db._conn() as c:
    n = c.execute("SELECT COUNT(*) AS n FROM memories WHERE kind!='name'").fetchone()["n"]
check("上限50件で頭打ち", n <= C.MEMORY_MAX_ITEMS, n)
check("名前は消えない", db.get_memory("name", "user") is not None)

print("== §3.5 感情と気分の連動 ==")
class Mood:
    def __init__(self, label): self.label = label
    def talk_bias(self): return 0.0
de, pool, aff = engine(seed=5, mood=Mood("shizumi"))
hits = sum(1 for _ in range(400) if any(
    m in de._decorate("うん。", "accept", NOW)
    for m in pool.candidates("mood.shizumi", "accept")))
check("沈んだ日は約半数に気分の枕", 0.35 < hits / 400 < 0.65, f"{hits/400:.2f}")
de, pool, aff = engine(seed=5, mood=Mood("genki"))
openers = pool.candidates("opener", "accept")
hits = sum(1 for _ in range(400)
           if any(de._decorate("うん。", "accept", NOW).startswith(o) for o in openers))
check("元気な日は枕が増える（0.4）", 0.32 < hits / 400 < 0.48, f"{hits/400:.2f}")
de, pool, aff = engine(seed=5, mood=Mood("futsuu"))
hits = sum(1 for _ in range(400)
           if any(de._decorate("うん。", "accept", NOW).startswith(o) for o in openers))
check("ふつうの日は従来どおり（0.25）", 0.18 < hits / 400 < 0.33, f"{hits/400:.2f}")

print("== §3.6 会話の文脈 ==")
de, pool, aff = engine(seed=7)
check("起動直後の相づちは落ちない", de.handle_user_message("うん", NOW)["reply"])
de, pool, aff = engine(seed=7)
de.handle_user_message("今日の天気は？", NOW)
r = de.handle_user_message("うん", NOW)
# 枕が前に付くことがあるので、候補を含むかで見る
check("天気のあとの相づちは follow_up.weather",
      any(c in r["reply"] for c in pool.candidates("follow_up.weather", r["tier"])),
      r["reply"])
de.handle_user_message("いま何時？", NOW)
r = de.handle_user_message("そうだね", NOW)
check("時刻のあとは follow_up.time",
      any(c in r["reply"] for c in pool.candidates("follow_up.time", r["tier"])),
      r["reply"])
r = de.handle_user_message("うん、そうだね、今日は寒いね", NOW)
check("相づち＋内容は通常判定へ", r["intent"] == "weather", r["intent"])

print("== 新しい意図分岐 ==")
de, pool, aff = engine(seed=11)
r = de.handle_user_message("ただいま", NOW)
check("ただいまは greeting_home",
      any(c in r["reply"] for c in pool.candidates("greeting_home", r["tier"])), r["reply"])
r = de.handle_user_message("ばいばい", NOW)
check("バイバイは greeting_bye",
      any(c in r["reply"] for c in pool.candidates("greeting_bye", r["tier"])), r["reply"])
r = de.handle_user_message("いま何時？", datetime(2026, 11, 27, 2, 0))
check("時刻は深夜スロットの言い回し",
      r["reply"].endswith(tuple(x[-6:] for x in
                                pool.candidates("time_answer_slot.late", r["tier"])))
      or "夜中" in r["reply"] or "遅い" in r["reply"], r["reply"])

class W:
    def __init__(self, text, temp): self.t, self.p = text, temp
    def current(self): return {"text": self.t, "temp": self.p}
    def forecast(self): return {"text": self.t, "temp": self.p}
de, pool, aff = engine(seed=13)
de.weather_provider = W("雨", 9)
r = de.handle_user_message("天気は？", NOW)
check("雨は専用の言い回し",
      any(c in r["reply"] for c in pool.candidates("weather_rain", r["tier"])), r["reply"])
de.weather_provider = W("晴れ", None)
r = de.handle_user_message("天気は？", NOW)
check("気温なしでも「度」が浮かない", "度" not in r["reply"] or "{" not in r["reply"],
      r["reply"])
check("波括弧が残らない", "{" not in r["reply"])

de, pool, aff = engine(seed=17)
de.notify_tier_up()
r = de.handle_user_message("こんにちは", NOW)
check("層が上がった直後は after_tier_up",
      any(c in r["reply"] for c in pool.candidates("after_tier_up", r["tier"])), r["reply"])
r2 = de.handle_user_message("こんにちは", NOW)
check("1回だけで元に戻る",
      not any(c in r2["reply"] for c in pool.candidates("after_tier_up", r2["tier"])), r2["reply"])

print("== §6.1 テーマ ==")
check("プリセット3種", set(PRESETS) == {"light", "dark", "koyuki"}, sorted(PRESETS))
for name in PRESETS:
    t = apply_preset(name)
    if not all(k in t for k in ("background", "surface", "text", "text_sub",
                                "accent", "accent_border", "highlight", "warn")):
        check(f"{name} に8トークン", False, sorted(t)); break
else:
    check("全プリセットに8トークン", True)
apply_preset("koyuki")
th = load_theme()
check("こゆきの配色が見本どおり",
      (th["background"], th["accent"], th["text"]) == ("#f4f8fc", "#5b8db8", "#3d4f61"),
      (th["background"], th["accent"], th["text"]))
th["accent"] = "#112233"
from alice_solo.ui.theme import save_theme
save_theme(th)
check("個別指定はプリセットの上に残る", load_theme()["accent"] == "#112233")
apply_preset("dark")
check("プリセットで個別指定は上書き", load_theme()["accent"] == "#4a3a35")
check("warn がテーマに入る", load_theme()["warn"] == "#e07856")

print("== §8 スナップ ==")
g = app.primaryScreen().availableGeometry()
check("左端に吸着", snap_point(g.left() + 5, 300, 100, 100)[0] == g.left())
check("離れていれば動かさない", snap_point(g.left() + 60, 300, 100, 100)[0] == g.left() + 60)
check("右端に吸着", snap_point(g.right() - 103, 300, 100, 100)[0] == g.right() + 1 - 100)
check("吸着距離は12px", C.SNAP_DISTANCE_PX == 12)

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
