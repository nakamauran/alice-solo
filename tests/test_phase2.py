"""フェーズ2の検証: PhrasePool / Affinity / DialogueEngine。"""
import os, sys, random, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
from pathlib import Path

# リポジトリの場所はこのファイルからたどる。絶対パスを書くと
# 別の環境で動かない。
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from datetime import datetime, timedelta

import importlib
import alice_solo.config as C
importlib.reload(C)

from alice_solo.engine.phrase_pool import PhrasePool
from alice_solo.engine.affinity import Affinity
from alice_solo.engine.dialogue_engine import DialogueEngine, slot_of
from alice_solo.engine.state_manager import StateManager
from alice_solo.engine.self_engine import store

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {label} {extra}")
    else:    fail += 1; print(f"  FAIL {label} {extra}")

PACK = _ROOT / "assets" / "characters" / "koyuki"
pool = PhrasePool(PACK / "phrases.yaml", rng=random.Random(1))

print("== phrases.yaml 検証 ==")
w = pool.validate()
check("必須キーの欠落なし", not w.missing, w.missing)
check("候補3件以上", not w.thin, w.thin)

print("== 層フォールバック ==")
check("guard に固有の挨拶", pool.candidates("greeting", "guard")[0].startswith("…"))
check("empathy に固有の挨拶",
      pool.candidates("greeting", "empathy") != pool.candidates("greeting", "accept"))
check("未定義キーは accept に落ちる",
      pool.candidates("mood.futsuu", "guard") != [])
check("shared に落ちる", pool.candidates("opener", "guard") == pool.shared["opener"])
check("存在しないキーは空", pool.candidates("nonexistent.key", "guard") == [])
for tier in C.TIERS:
    for cat in C.EMOTION_CATEGORIES:
        if not pool.candidates(f"emotion_response.{cat}", tier):
            check(f"{tier}/{cat} に候補", False); break
    else:
        check(f"{tier} は全9カテゴリに候補あり", True)

print("== 差し込み ==")
t = pool._format("{me}は{name}。{undefined}", {"me": "わたし", "name": "こゆき"})
check("未定義変数は空文字", t == "わたしはこゆき。", repr(t))
got = pool.pick("idle_lonely", "empathy", me="わたし")
check("pick が文字列を返す", isinstance(got, str) and got, repr(got))
check("波括弧が残らない", "{" not in (got or ""))

print("== 重複除外 ==")
p2 = PhrasePool(PACK / "phrases.yaml", rng=random.Random(7))
seq = [p2.pick("greeting", "accept") for _ in range(40)]
pairs = sum(1 for a, b in zip(seq, seq[1:]) if a == b)
check("直前と同じ文が出ない", pairs == 0, f"連続={pairs}")
check("候補を一巡して使う", len(set(seq)) == len(pool.candidates("greeting", "accept")))

print("== Affinity: 層とヒステリシス ==")
apath = Path(tempfile.mkdtemp()) / "affinity.json"
a = Affinity(apath)
check("初期は guard", a.tier == "guard", f"{a.value} {a.tier}")

a.data["value"] = 39.0; a.data["tier_changed_date"] = ""
a._reevaluate_tier("2026-11-20")
check("39 では昇格しない", a.tier == "guard")
a.data["value"] = 40.0; a.data["tier_changed_date"] = ""
a._reevaluate_tier("2026-11-20")
check("40 で accept へ", a.tier == "accept")
a.data["value"] = 37.0; a.data["tier_changed_date"] = ""
a._reevaluate_tier("2026-11-21")
check("37 では降格しない（ヒステリシス）", a.tier == "accept")
a.data["value"] = 34.0; a.data["tier_changed_date"] = ""
a._reevaluate_tier("2026-11-22")
check("35未満で guard へ", a.tier == "guard")
a.data["value"] = 80.0; a.data["tier_changed_date"] = ""
a._reevaluate_tier("2026-11-23")
check("guard からは一気に empathy へ飛ばない", a.tier == "accept")
a.data["tier_changed_date"] = ""
a._reevaluate_tier("2026-11-24")
check("翌日に empathy へ", a.tier == "empathy")
a.data["value"] = 90.0
a._reevaluate_tier("2026-11-24")
check("同じ日に2回は動かない", a.data["tier_changed_date"] == "2026-11-24")

print("== Affinity: 増加と上限 ==")
a2 = Affinity(Path(tempfile.mkdtemp()) / "a.json")
a2.data["value"] = 50.0
base = a2.value
total = sum(a2.on_interaction(positive=False) for _ in range(100))
check("1日の上限は +10", abs(total - C.AFFINITY_DAILY_CAP) < 1e-9, f"{total}")
check("値に反映", abs(a2.value - (base + C.AFFINITY_DAILY_CAP)) < 1e-9, f"{a2.value}")
a3 = Affinity(Path(tempfile.mkdtemp()) / "a.json")
a3.data["value"] = 50.0
g = a3.on_interaction(positive=True)
check("肯定語は +1.0", abs(g - C.AFFINITY_GAIN_POSITIVE) < 1e-9, f"{g}")

print("== Affinity: 未起動日のみ減衰 ==")
a4 = Affinity(Path(tempfile.mkdtemp()) / "a.json")
a4.data["value"] = 60.0
now = datetime(2026, 11, 20, 12, 0)
a4.data["last_launch_date"] = store.today_key(now)
r = a4.on_launch(now)                                   # 同じ日に再起動
check("同日再起動で減らない", abs(a4.value - 60.0) < 1e-9, f"{a4.value}")
a4.data["value"] = 60.0
r = a4.on_launch(now + timedelta(days=1))               # 翌日
check("連日起動はボーナス +1", abs(a4.value - 61.0) < 1e-9, f"{a4.value}")
a4.data["value"] = 60.0
r = a4.on_launch(now + timedelta(days=6))               # 5日あけ
check("5日あけは -12", abs(a4.value - (60.0 - 4*3.0)) < 1e-9, f"{a4.value} {r}")

print("== DialogueEngine: 意図判定 ==")
spath = Path(tempfile.mkdtemp()) / "state.json"
sm = StateManager(spath)
aff = Affinity(Path(tempfile.mkdtemp()) / "a.json")
aff.data["tier"] = "accept"
de = DialogueEngine(pool, aff, sm,
                    character={"display_name": "こゆき", "first_person": "わたし"},
                    rng=random.Random(3))

noon = datetime(2026, 11, 20, 12, 0)
r = de.handle_user_message("いま何時？", noon)
check("時刻を答える", "12時00分" in r["reply"], r["reply"])
r = de.handle_user_message("今日の天気は？", noon)
check("天気は未取得として黙らない", len(r["reply"]) > 0, r["reply"])
r = de.handle_user_message("時間がないんだ", noon)
check("除外語で時刻判定に落ちない", "12時00分" not in r["reply"], r["reply"])
r = de.handle_user_message("おはよう", datetime(2026, 11, 20, 7, 0))
check("朝の挨拶", "おはよ" in r["reply"], r["reply"])
r = de.handle_user_message("おはよう", datetime(2026, 11, 20, 23, 0))
check("夜は夜の挨拶", "おはよ" not in r["reply"], r["reply"])
r = de.handle_user_message("かわいいね", noon)
check("shy に落ちる", r["category"] == "shy", r["reply"])
r = de.handle_user_message("ファイルを探して", noon)
check("ファイル探索は判定しない", r["category"] in C.EMOTION_CATEGORIES, r["reply"])

print("== DialogueEngine: スロット ==")
check("05:00 は morning", slot_of(datetime(2026,11,20,5,0)) == "morning")
check("11:00 は daytime", slot_of(datetime(2026,11,20,11,0)) == "daytime")
check("17:00 は evening", slot_of(datetime(2026,11,20,17,0)) == "evening")
check("21:00 は night", slot_of(datetime(2026,11,20,21,0)) == "night")
check("02:00 は late", slot_of(datetime(2026,11,20,2,0)) == "late")

print("== DialogueEngine: 枕と尾ひれ ==")
de2 = DialogueEngine(pool, aff, sm, character={"display_name":"こゆき","first_person":"わたし"},
                     rng=random.Random(11))
openers = pool.shared["opener"]
hits = 0
for _ in range(400):
    out = de2._decorate("うん。", "accept", noon)
    if any(out.startswith(o) for o in openers):
        hits += 1
check("枕は約25%", 0.18 < hits/400 < 0.33, f"{hits/400:.2f}")
long_body = "あ" * (C.DECORATE_MAX_LEN + 1)
check("長文には付けない",
      all(de2._decorate(long_body, "accept", noon) == long_body for _ in range(50)))
de2.push_remark("……そういえば、雨が好きになってきた。")
got = [de2._decorate("うん。", "accept", noon) for _ in range(20)]
check("尾ひれは溜めから1回だけ出る",
      sum("雨が好き" in g for g in got) == 1, [g for g in got if "雨が好き" in g])

print("== DialogueEngine: 層で口調が変わる ==")
replies = {}
for tier in C.TIERS:
    aff.data["tier"] = tier
    d = DialogueEngine(pool, aff, sm,
                       character={"display_name":"こゆき","first_person":"わたし"},
                       rng=random.Random(5))
    replies[tier] = {d.handle_user_message("こんにちは", noon)["reply"] for _ in range(12)}
check("3層で挨拶が重ならない",
      not (replies["guard"] & replies["accept"]) and
      not (replies["accept"] & replies["empathy"]),
      {k: list(v)[:2] for k, v in replies.items()})

print("== idle_phrase ==")
# 言うことが無ければ必ず黙るのが仕様。黙る確率を測るため、
# 退屈度を上げて「かまって」を言える状態にしてから評価する。
sm.state.boredom = 1.0
check("材料ゼロなら黙る",
      DialogueEngine(pool, aff, StateManager(Path(tempfile.mkdtemp())/"s.json"),
                     character={"display_name":"こ","first_person":"わ"},
                     rng=random.Random(0)
                     ).idle_phrase(datetime(2026,11,20,13,0)) is None)
aff.data["tier"] = "guard"
d = DialogueEngine(pool, aff, sm, character={"display_name":"こゆき","first_person":"わたし"},
                   rng=random.Random(2))
silent = sum(1 for _ in range(400)
             if d.idle_phrase(datetime(2026,11,20,13,0)) is None)
check("guard は約半分黙る", 0.40 < silent/400 < 0.62, f"{silent/400:.2f}")
aff.data["tier"] = "accept"
d2 = DialogueEngine(pool, aff, sm, character={"display_name":"こゆき","first_person":"わたし"},
                    rng=random.Random(2))
silent2 = sum(1 for _ in range(400)
              if d2.idle_phrase(datetime(2026,11,20,13,0)) is None)
check("accept はあまり黙らない", silent2 < silent, f"{silent2/400:.2f} < {silent/400:.2f}")

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
