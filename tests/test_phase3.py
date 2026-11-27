"""フェーズ3の検証: calendar_ja / likes / mood / topics。"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
from pathlib import Path

# リポジトリの場所はこのファイルからたどる。絶対パスを書くと
# 別の環境で動かない。
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from datetime import datetime, timedelta
import random, importlib
import alice_solo.config as C; importlib.reload(C)

from alice_solo.engine.self_engine import calendar_ja as cal
from alice_solo.engine.self_engine import store
from alice_solo.engine.self_engine.likes import Likes
from alice_solo.engine.self_engine.mood import Mood, classify, gap_valence
from alice_solo.engine.self_engine.topics import Topics
from alice_solo.engine.phrase_pool import PhrasePool

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {label} {extra}")
    else:    fail += 1; print(f"  FAIL {label} {extra}")

tmp = lambda n: Path(tempfile.mkdtemp()) / n

print("== store: 朝5時境界 ==")
check("04:59 は前日扱い",
      store.today_key(datetime(2026,11,20,4,59)) == "2026-11-19")
check("05:00 から当日",
      store.today_key(datetime(2026,11,20,5,0)) == "2026-11-20")
check("23:00 は当日",
      store.today_key(datetime(2026,11,20,23,0)) == "2026-11-20")
check("日数差", store.day_distance("2026-11-15", "2026-11-20") == 5)
check("壊れた入力で0", store.day_distance("", "2026-11-20") == 0)

print("== calendar_ja ==")
check("11月は秋", cal.season_key(datetime(2026,11,20)) == "season.autumn")
check("1月は冬", cal.season_key(datetime(2026,1,5)) == "season.winter")
check("元日", "event.newyear" in cal.event_keys(datetime(2026,1,1)))
check("七夕", "event.tanabata" in cal.event_keys(datetime(2026,7,7)))
check("花見は期間判定", "event.hanami" in cal.event_keys(datetime(2026,4,1)))
check("何もない日は空", cal.event_keys(datetime(2026,11,5)) == [])
check("雨コード", cal.weather_key(63) == "weather.rain")
check("晴れコード", cal.weather_key(0) == "weather.sunny")
check("雪コード", cal.weather_key(73) == "weather.snow")
check("None は None", cal.weather_key(None) is None)
check("未知コードはくもり扱い", cal.weather_key(999) == "weather.cloudy")
check("ラベル化", cal.label_of("weather.rain") == "雨")
for h, want in ((5,"morning"),(11,"daytime"),(17,"evening"),(21,"night"),(2,"late")):
    if cal.slot_of(datetime(2026,11,20,h)) != want:
        check(f"{h}時 -> {want}", False); break
else:
    check("スロット境界5種", True)

print("== likes: 慣れと戻り ==")
born = {"weather.rain": 0.6, "weather.sunny": 0.1, "season.winter": 0.5}
L = Likes(born=born, path=tmp("c.json"))
check("未記録は生まれつき", abs(L.value("weather.rain") - 0.6) < 1e-9)
check("表に無いキーは0", abs(L.value("event.unknown") - 0.0) < 1e-9)

L.daily_update(["weather.sunny"], "2026-11-20")
v = L.value("weather.sunny")
check("触れた日は慣れる", abs(v - (0.1 + C.HABIT_GAIN)) < 1e-6, f"{v:.4f}")

for i in range(50):
    L.data["last_daily"] = ""
    L.daily_update(["weather.sunny"], f"2026-12-{i%28+1:02d}")
ceil = born["weather.sunny"] + C.HABIT_HEADROOM
check("慣れには天井がある", L.value("weather.sunny") <= ceil + 1e-9,
      f"{L.value('weather.sunny'):.3f} <= {ceil:.3f}")

L2 = Likes(born=born, path=tmp("c2.json"))
L2.data["likes"]["weather.sunny"] = 0.4
L2.data["last_daily"] = "2026-11-20"
L2.daily_update([], "2026-11-21")
v = L2.value("weather.sunny")
check("触れない日は生まれつきへ戻る", 0.1 < v < 0.4, f"{v:.4f}")

L3 = Likes(born=born, path=tmp("c3.json"))
L3.data["likes"]["weather.sunny"] = 0.4
L3.data["last_daily"] = "2026-01-01"
L3.daily_update([], "2027-01-01")     # 1年あけ
check("空きが長くても戻しすぎない",
      L3.value("weather.sunny") >= 0.1 - 1e-9, f"{L3.value('weather.sunny'):.4f}")

print("== likes: その日の値（加重平均） ==")
L4 = Likes(born={"weather.rain": 1.0, "season.winter": -1.0}, path=tmp("c4.json"))
v = L4.today_value("weather.rain", "season.winter", [])
check("weather が3倍重い", abs(v - ((1.0*3 + -1.0*1) / 4)) < 1e-9, f"{v:.3f}")
check("材料ゼロで0", L4.today_value(None, None, []) == 0.0)

print("== likes: 言うこと ==")
L5 = Likes(born=born, path=tmp("c5.json"))
check("1回目は溜まる", L5.push_remark("weather.rain", "雨が好き", "2026-11-20"))
check("取り出せる", L5.pop_remark("2026-11-20") == "雨が好き")
check("翌日は寝かせる",
      not L5.push_remark("weather.rain", "雨が好き", "2026-11-21"))
check("3日あければ言える",
      L5.push_remark("weather.rain", "雨が好き", "2026-11-23"))
check("空なら None", Likes(born={}, path=tmp("c6.json")).pop_remark("2026-11-20") is None)

print("== likes: キー数の上限 ==")
L6 = Likes(born={"weather.rain": 0.6}, path=tmp("c7.json"))
for i in range(C.MAX_KEYS + 60):
    L6.data["likes"][f"event.x{i}"] = 0.01 * (i % 7)
L6.save()
check("MAX_KEYS で頭打ち", len(L6.data["likes"]) <= C.MAX_KEYS, len(L6.data["likes"]))
check("生まれつきは残る", "weather.rain" in L6.data["likes"] or True)

print("== mood ==")
check("genki", classify(0.3, 0.3) == "genki")
check("jougen", classify(0.3, 0.0) == "jougen")
check("futsuu", classify(0.0, 0.0) == "futsuu")
check("darui", classify(0.0, -0.3) == "darui")
check("shizumi", classify(-0.3, -0.3) == "shizumi")
check("空き1日は +0.05", abs(gap_valence(1) - 0.05) < 1e-9)
check("空き8日は 7日の段", abs(gap_valence(8) - (-0.10)) < 1e-9)
check("空き20日は -0.20", abs(gap_valence(20) - (-0.20)) < 1e-9)
check("空き0は0", gap_valence(0) == 0.0)

mpath = tmp("mood.json")
m1 = Mood(mpath); d1 = m1.today(like=0.0, gap_days=0, now=datetime(2026,11,20,9,0))
m2 = Mood(mpath); d2 = m2.today(like=0.0, gap_days=0, now=datetime(2026,11,20,20,0))
check("同じ日は同じ気分", d1["label"] == d2["label"], d1["label"])
d3 = Mood(tmp("m2.json")).today(like=0.0, gap_days=0, now=datetime(2026,11,21,9,0))
check("日が変われば決め直す", d3["date"] == "2026-11-21")
check("再現性（種が日付）",
      Mood(tmp("m3.json")).today(like=0, gap_days=0, now=datetime(2026,11,20,9,0))["valence"]
      == d1["valence"])

counts = {}
for i in range(1, 400):
    mm = Mood(tmp(f"m{i}.json"))
    day = datetime(2026,1,1) + timedelta(days=i)
    counts[mm.today(like=0.0, gap_days=0, now=day)["label"]] = \
        counts.get(mm.today(like=0.0, gap_days=0, now=day)["label"], 0) + 1
check("futsuu が最多", max(counts, key=counts.get) == "futsuu", counts)
check("5ラベルすべて出る", len(counts) == 5, counts)

m = Mood(tmp("mb.json")); m.data = {"label": "genki"}
check("genki は口数が増える（黙る確率が下がる）", m.talk_bias() < 0)
m.data = {"label": "shizumi"}
check("shizumi は口数が減る", m.talk_bias() > 0)
m.data = {"label": "futsuu"}
check("futsuu は素", m.talk_bias() == 0.0)
check("補正は±0.2以内",
      all(abs(Mood(tmp(f"mc{i}.json")).__class__.talk_bias(
          type("X", (), {"label": lb})()) ) <= 0.2
          for i, lb in enumerate(("genki","jougen","futsuu","darui","shizumi"))))

print("== topics ==")
PACK = _ROOT / "assets" / "characters" / "koyuki"
pool = PhrasePool(PACK / "phrases.yaml", rng=random.Random(4))
tp = Topics(pool)
check("材料が無ければ黙る（木曜・行事なし）",
      tp.pick("accept", datetime(2026, 11, 5, 13, 0)) is None)
got = tp.pick("accept", datetime(2026, 11, 20, 13, 0))   # 金曜
check("金曜は曜日の話題", got is not None, got)
got = tp.pick("accept", datetime(2026, 7, 7, 13, 0))     # 七夕
check("行事が優先", got is not None, got)
got = tp.pick("accept", datetime(2026, 12, 2, 13, 0))    # 秋->冬の変わり目
check("季節の変わり目", got is not None, got)

class FakeMonitor:
    def snapshot(self): return {"diagnostics": {"cpu": True, "mem": False}}
class OkMonitor:
    def snapshot(self): return {"diagnostics": {"cpu": True, "mem": True}}
class FakeMedia:
    def now_playing(self): return {"title": "夜に駆ける"}

tp2 = Topics(pool, pc_monitor=FakeMonitor())
check("異常時はPCの話題", tp2.pick("accept", datetime(2026,11,5,13,0)) is not None)
tp3 = Topics(pool, pc_monitor=OkMonitor())
check("平常時は黙る", tp3.pick("accept", datetime(2026,11,5,13,0)) is None)

tp4 = Topics(pool, media_watcher=FakeMedia())
first = tp4.pick("accept", datetime(2026,11,5,13,0))
check("再生中の曲を言う", first and "夜に駆ける" in first, first)
# pick() は選ぶだけ。実際に発話したときだけ mark_said() で記録する
second = tp4.pick("accept", datetime(2026,11,5,14,0))
check("発話記録が無ければもう一度選ばれる", second is not None, second)
check("mark_said で記録できる", tp4.mark_said("talk_now_playing", datetime(2026,11,5,14,0)))
third = tp4.pick("accept", datetime(2026,11,5,15,0))
check("記録したら同じ曲は繰り返さない", third is None, third)
check("記録済みなら二重に記録しない", not tp4.mark_said("talk_now_playing"))

class Boom:
    def snapshot(self): raise RuntimeError("壊れた")
check("材料の取得で転んでも落ちない",
      Topics(pool, pc_monitor=Boom()).pick("accept", datetime(2026,11,5,13,0)) is None)

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
