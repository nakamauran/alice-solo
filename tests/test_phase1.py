"""フェーズ1のロジック検証（UI非依存の部分のみ）。"""
import sys, tempfile, os
from datetime import datetime, timedelta

from pathlib import Path

# リポジトリの場所はこのファイルからたどる。絶対パスを書くと
# 別の環境で動かない。
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from alice_solo.engine import emotion_engine as E
from alice_solo.engine.state_manager import StateManager, ISO
from alice_solo import config as C

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1; print(f"  OK   {label} {extra}")
    else:
        fail += 1; print(f"  FAIL {label} {extra}")

print("== emotion: 極性 ==")
check("肯定", E.text_polarity("今日はたのしい") == 0.7)
check("否定", E.text_polarity("つかれた") == -0.7)
check("両方で0", E.text_polarity("楽しいけど疲れた") == 0.0)
check("中立で0", E.text_polarity("そうですか") == 0.0)
check("全角正規化", E.text_polarity("ＳＵＫＩ すき") == 0.7)

print("== emotion: カテゴリ ==")
noon = datetime(2026, 11, 20, 12, 0)
night = datetime(2026, 11, 20, 2, 0)
check("shyトリガー優先", E.score_to_category(-0.9, "かわいいね", noon) == "shy")
check("sleepyトリガー", E.score_to_category(0.9, "おやすみ", noon) == "sleepy")
check("drowsyトリガー", E.score_to_category(0.0, "ねむい", noon) == "drowsy")
check("深夜は既定sleepy", E.score_to_category(0.0, "そうですか", night) == "sleepy")
check("happy_strong", E.score_to_category(0.7, "", noon) == "happy_strong")
check("happy_weak", E.score_to_category(0.3, "", noon) == "happy_weak")
check("neutral", E.score_to_category(0.0, "", noon) == "neutral")
check("anxious", E.score_to_category(-0.2, "", noon) == "anxious")
check("sad", E.score_to_category(-0.4, "", noon) == "sad")
check("angry", E.score_to_category(-0.8, "", noon) == "angry")
cats = {E.score_to_category(v/10, "", noon) for v in range(-10, 11)}
cats |= {"shy", "drowsy", "sleepy"}
check("9カテゴリ網羅", len(cats) == 9, sorted(cats))

print("== emotion: スコア式 ==")
v = E.score("", 50.0, 30.0, 0.0)
check("中庸入力で0", abs(v) < 1e-9, f"v={v}")
v = E.score("すき", 100.0, 100.0, 0.0)
check("満点で上振れ", v > 0.6, f"v={v:.3f}")
v = E.score("つらい", 0.0, 0.0, 1.0)
check("最低で下振れ", v < -0.6, f"v={v:.3f}")
check("クランプ", -1.0 <= E.score("つらい", 0, 0, 1.0) <= 1.0)

print("== state: 生活リズム ==")
tmp = Path(tempfile.mkdtemp()) / "state.json"

def fresh(satiety=80.0, tension=60.0, at=None):
    if tmp.exists(): tmp.unlink()
    sm = StateManager(tmp)
    sm.state.satiety = satiety
    sm.state.tension = tension
    base = at or datetime(2026, 11, 20, 10, 0)
    sm.state.last_tick_time = base.strftime(ISO)
    sm.state.last_interaction_time = base.strftime(ISO)
    return sm, base

sm, base = fresh()
sm.tick(base + timedelta(hours=1))
check("満腹度が1時間で約16.7減", abs(sm.state.satiety - (80 - 0.00463*3600)) < 0.5,
      f"{sm.state.satiety:.1f}")

sm, base = fresh(satiety=20.0, at=datetime(2026, 11, 20, 12, 0))
sm.tick(datetime(2026, 11, 20, 13, 0))   # 12:30 の食事をまたぐ
check("食事で回復", sm.state.satiety > 35, f"{sm.state.satiety:.1f}")

sm, base = fresh(satiety=20.0, at=datetime(2026, 11, 20, 6, 0))
sm.tick(datetime(2026, 11, 20, 20, 0))   # 3食ぶんまたぐ
check("未起動catch-upは1回だけ", sm.state.satiety <= 20 + C.MEAL_RECOVERY + 0.01,
      f"{sm.state.satiety:.1f}")

sm, base = fresh(tension=10.0, at=datetime(2026, 11, 20, 6, 0))
sm.tick(datetime(2026, 11, 20, 8, 0))    # 07:00 起床をまたぐ
check("起床でテンション回復", sm.state.tension > 80, f"{sm.state.tension:.1f}")

sm, base = fresh(tension=0.0, at=datetime(2026, 11, 20, 3, 0))
sm.tick(datetime(2026, 11, 20, 3, 30))
check("就寝帯の下限固定", sm.state.tension == C.TENSION_SLEEP_FLOOR, f"{sm.state.tension}")

sm, base = fresh(tension=100.0, at=datetime(2026, 11, 20, 22, 0))
sm.tick(datetime(2026, 11, 20, 23, 0))
day, _ = fresh(tension=100.0, at=datetime(2026, 11, 20, 14, 0))
day.tick(datetime(2026, 11, 20, 15, 0))
check("夜間は減衰2倍", (100 - sm.state.tension) > (100 - day.state.tension) * 1.9,
      f"night={sm.state.tension:.1f} day={day.state.tension:.1f}")

print("== state: 退屈度と相互作用 ==")
sm, base = fresh()
sm.tick(base + timedelta(minutes=45))
check("45分でboredom=1.0", abs(sm.state.boredom - 1.0) < 1e-6, f"{sm.state.boredom}")
sm.record_interaction(base + timedelta(minutes=45))
check("会話でリセット", sm.state.boredom == 0.0)
sm, base = fresh()
sm.tick(base + timedelta(minutes=22, seconds=30))
check("22.5分で約0.5", abs(sm.state.boredom - 0.5) < 0.01, f"{sm.state.boredom:.3f}")

print("== state: 保存 ==")
sm, base = fresh()
sm.tick(base + timedelta(minutes=10))
sm.save()
sm2 = StateManager(tmp)
check("往復で一致", abs(sm2.state.satiety - sm.state.satiety) < 1e-9)
check("原子置換で.tmpが残らない",
      not any(p.suffix == ".tmp" for p in tmp.parent.iterdir()))

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
