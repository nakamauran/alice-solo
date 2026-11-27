"""フェーズ6の検証: バックアップ・ログ・初回起動。"""
import os, sys, tempfile, time, zipfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
APPDATA = tempfile.mkdtemp()
os.environ["APPDATA"] = APPDATA
from pathlib import Path

# リポジトリの場所はこのファイルからたどる。絶対パスを書くと
# 別の環境で動かない。
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from datetime import datetime
import importlib
import alice_solo.config as C; importlib.reload(C)
import alice_solo.backup as B; importlib.reload(B)
import alice_solo.logging_setup as L; importlib.reload(L)
C.ensure_dirs()

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {label} {extra}")
    else:    fail += 1; print(f"  FAIL {label} {extra}")

def make_data(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "self").mkdir(exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    (root / "state.json").write_text('{"satiety": 80}', encoding="utf-8")
    (root / "user_config.json").write_text('{"scale": 1.0}', encoding="utf-8")
    (root / "self" / "affinity.json").write_text('{"value": 55}', encoding="utf-8")
    (root / "local_store.db").write_bytes(b"sqlite-ish")
    (root / "state.json.tmp").write_text("破片", encoding="utf-8")
    (root / "logs" / "alice.log").write_text("ログ", encoding="utf-8")

print("== バックアップ: 書き出し ==")
src = Path(tempfile.mkdtemp()) / "data"
make_data(src)
dest = Path(tempfile.mkdtemp()) / B.default_name()
n = B.export_to(dest, src)
check("ファイル名の形", dest.name.endswith(".alicebackup.zip"), dest.name)
names = zipfile.ZipFile(dest).namelist()
check("4件入る（tmp とログは除く）", n == 4, f"{n}: {sorted(names)}")
check("tmp は入らない", not any(x.endswith(".tmp") for x in names))
check("ログは入らない", not any(x.startswith("logs/") for x in names))
check("階層が保たれる", "self/affinity.json" in names, names)

print("== バックアップ: 検査 ==")
info = B.inspect(dest)
check("正しい zip は通る", info["ok"] and info["files"] == 4, info)

bad = Path(tempfile.mkdtemp()) / "bad.zip"
bad.write_text("これは zip ではない", encoding="utf-8")
check("zip でなければ弾く", not B.inspect(bad)["ok"], B.inspect(bad)["reason"])

empty = Path(tempfile.mkdtemp()) / "empty.zip"
zipfile.ZipFile(empty, "w").close()
check("空なら弾く", not B.inspect(empty)["ok"], B.inspect(empty)["reason"])

other = Path(tempfile.mkdtemp()) / "other.zip"
with zipfile.ZipFile(other, "w") as z:
    z.writestr("photos/cat.jpg", "x")
check("別物の zip は弾く", not B.inspect(other)["ok"], B.inspect(other)["reason"])

evil = Path(tempfile.mkdtemp()) / "evil.zip"
with zipfile.ZipFile(evil, "w") as z:
    z.writestr("state.json", "{}")
    z.writestr("../../gotcha.txt", "脱出")
res = B.inspect(evil)
check("保存フォルダの外を指す zip を弾く", not res["ok"], res["reason"])
check("どれが危険か分かる", res["unsafe"], res["unsafe"])

print("== バックアップ: 復元 ==")
target = Path(tempfile.mkdtemp()) / "data"
make_data(target)
(target / "state.json").write_text('{"satiety": 10}', encoding="utf-8")
(target / "self" / "affinity.json").write_text('{"value": 99}', encoding="utf-8")
r = B.restore_from(dest, target)
check("復元できる", r["ok"] and r["restored"] == 4, r)
check("中身が戻る", '"satiety": 80' in (target / "state.json").read_text(encoding="utf-8"))
check("入れ子も戻る",
      '"value": 55' in (target / "self" / "affinity.json").read_text(encoding="utf-8"))
check("復元前の控えが残る", r["safety_copy"] and Path(r["safety_copy"]).exists(),
      r["safety_copy"])
with zipfile.ZipFile(r["safety_copy"]) as z:
    saved = z.read("state.json").decode("utf-8")
check("控えには復元前の値", '"satiety": 10' in saved, saved)

r2 = B.restore_from(evil, Path(tempfile.mkdtemp()) / "x")
check("危険な zip は復元しない", not r2["ok"], r2["reason"])
outside = Path(tempfile.mkdtemp())
check("脱出先にファイルが作られていない",
      not (outside / "gotcha.txt").exists())

print("== ログ ==")
logger = L.setup()
logger.info("テスト行")
check("ログファイルができる", L.LOG_FILE.exists(), L.LOG_FILE)
check("書かれている", "テスト行" in L.LOG_FILE.read_text(encoding="utf-8"))
check("2度目の setup は同じロガー", L.setup() is logger)
check("日ごとに回す設定", logger.handlers[0].when == "MIDNIGHT")
check("7日ぶん残す", logger.handlers[0].backupCount == 7)
check("上限は5MB", L.MAX_BYTES == 5 * 1024 * 1024)

old = L.LOG_DIR / "alice.log.2020-01-01"
old.write_text("古い", encoding="utf-8")
os.utime(old, (time.time() - 30 * 86400,) * 2)
removed = L.purge_old()
check("古いログを消す", removed == 1 and not old.exists(), removed)
fresh = L.LOG_DIR / "alice.log.2026-11-26"
fresh.write_text("新しい", encoding="utf-8")
check("新しいログは残す", L.purge_old() == 0 and fresh.exists())

check("例外フックが差さっている", sys.excepthook.__name__ == "hook",
      sys.excepthook.__name__)

print("== 初回起動 ==")
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
os.environ["APPDATA"] = tempfile.mkdtemp()
importlib.reload(C)
import alice_solo.main as M; importlib.reload(M)
C.ensure_dirs()
a = M.AliceSolo(app)
check("installed_at が入る", bool(a.cfg.get("installed_at")), a.cfg.get("installed_at"))
titles = [i["title"] for i in a.db.get_inbox()]
check("はじめましてが届く", "はじめまして" in titles, titles)
check("未読になっている", a.db.unread_count() == 1)
stamp = a.cfg.get("installed_at")
a.quit(); app.processEvents()

b = M.AliceSolo(app)
check("2回目は installed_at を上書きしない", b.cfg.get("installed_at") == stamp)
check("2回目は案内を増やさない", len(b.db.get_inbox()) == 1, len(b.db.get_inbox()))
b.quit(); app.processEvents()

print("== デバッグ窓 -> ログ ==")
log_text = L.LOG_FILE.read_text(encoding="utf-8")
check("デバッグ行がログにも落ちる", "[self]" in log_text or "[info]" in log_text,
      log_text.splitlines()[-1] if log_text else "")

class Boom:
    def __call__(self, *a): raise RuntimeError("壊れた")
from alice_solo.ui.debug_window import DebugWindow
d = DebugWindow(); d.sink = Boom()
d.log("info", "落ちないこと")
check("ログに落とせなくても画面表示は続く", len(d._lines) == 1)

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
