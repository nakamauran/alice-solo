"""フェーズ5の検証: local_store と周辺ウィンドウ。"""
import os, sys, tempfile, time
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
from alice_solo.db.local_store import LocalStore
from alice_solo.ui.mailbox_window import MailboxWindow, MailboxIcon
from alice_solo.ui.diary_window import DiaryWindow
from alice_solo.ui.notes_window import NotesWindow
from alice_solo.ui.timer_window import TimerWindow, _fmt
from alice_solo.ui.hud_window import HUDWindow
from alice_solo.engine.self_engine import store

app = QApplication([])
ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {label} {extra}")
    else:    fail += 1; print(f"  FAIL {label} {extra}")

db = LocalStore(Path(tempfile.mkdtemp()) / "t.db")

print("== local_store: 郵便受け ==")
db.put_inbox("news", "2026-11-27", "新聞が届きました", "本文")
db.put_inbox("timer", "t1", "タイマー", "時間です")
check("2件ある", len(db.get_inbox()) == 2)
check("未読2件", db.unread_count() == 2)
db.put_inbox("news", "2026-11-27", "新聞（差し替え）", "新しい本文")
check("同じ鍵は上書きで増えない", len(db.get_inbox()) == 2)
news = [i for i in db.get_inbox() if i["source"] == "news"][0]
check("中身が入れ替わる", news["title"] == "新聞（差し替え）")
db.mark_read(int(news["id"]))
check("既読にできる", db.unread_count() == 1)
db.put_inbox("news", "2026-11-27", "さらに差し替え", "本文3")
news2 = [i for i in db.get_inbox() if i["source"] == "news"][0]
check("上書きしても既読のまま", news2["read_at"] is not None)
db.mark_all_read()
check("すべて既読", db.unread_count() == 0)
db.delete_inbox(int(news2["id"]))
check("削除できる", len(db.get_inbox()) == 1)

print("== local_store: 自動整理 ==")
with db._conn() as c:
    old = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO inbox (source,dedupe_key,title,created_at) VALUES "
              "('old','o1','古い投函',?)", (old,))
check("古い投函が入った", len(db.get_inbox()) == 2)
n = db.purge_inbox()
check("30日より古いものを消す", n == 1 and len(db.get_inbox()) == 1, f"消した={n}")

print("== local_store: 日記 ==")
check("未記入は空文字", db.get_diary("2026-11-27") == "")
db.save_diary("2026-11-27", "今日のこと")
check("保存して読める", db.get_diary("2026-11-27") == "今日のこと")
db.save_diary("2026-11-27", "書き直した")
check("上書きできる", db.get_diary("2026-11-27") == "書き直した")
db.save_diary("2026-11-26", "前の日")
db.save_diary("2026-11-25", "   ")
dates = db.diary_dates()
check("新しい順", dates[:2] == ["2026-11-27", "2026-11-26"], dates)
check("空白だけの日は一覧に出ない", "2026-11-25" not in dates, dates)

print("== local_store: メモ ==")
nid = db.create_note("買い物", "牛乳")
check("作れる", isinstance(nid, int) and nid > 0)
db.update_note(nid, "買い物リスト", "牛乳とパン")
got = db.list_notes()[0]
check("更新できる", got["title"] == "買い物リスト" and got["content"] == "牛乳とパン")
db.create_note("もう1つ", "")
check("2件", len(db.list_notes()) == 2)
db.delete_note(nid)
check("削除できる", len(db.list_notes()) == 1)

print("== 郵便受けウィンドウ ==")
db2 = LocalStore(Path(tempfile.mkdtemp()) / "m.db")
db2.put_inbox("news", "k1", "お知らせA", "本文A")
db2.put_inbox("timer", "k2", "お知らせB", "本文B")
mw = MailboxWindow(db2)
check("一覧に2件並ぶ", mw.list.count() == 2)
check("未読は●が付く", mw.list.item(0).text().startswith("●"), mw.list.item(0).text())
mw.list.setCurrentRow(0)
check("選ぶと本文が出る", mw.body.toPlainText() in ("本文A", "本文B"),
      mw.body.toPlainText())
check("選ぶと既読になる", db2.unread_count() == 1)
mw._mark_all()
check("すべて既読ボタン", db2.unread_count() == 0)
empty = MailboxWindow(LocalStore(Path(tempfile.mkdtemp()) / "e.db"))
check("空のときの案内", "届いていません" in empty.body.toPlainText())

print("== 郵便受けアイコン ==")
pack = C.BUNDLED_CHARACTERS_DIR / "koyuki"
icon = MailboxIcon(pack, 1.0)
check("素材を見つけている", icon.available)
check("2枚とも読めている", len(icon._pixmaps) == 2)
check("大きさが基準どおり", icon.height() in (110, 109, 111), icon.height())
w0 = icon.width()
icon.apply_scale(2.0)
check("倍率で大きくなる", icon.width() > w0, f"{w0} -> {icon.width()}")
icon.apply_scale(0.1)
check("下限でクランプ", icon._scale == 0.6, icon._scale)

print("== 日記ウィンドウ ==")
dbd = LocalStore(Path(tempfile.mkdtemp()) / "d.db")
dw = DiaryWindow(dbd)
check("今日の日付で開く", dw.date_label.text() == store.today_key())
dw.editor.setPlainText("テスト本文")
dw.save()
check("保存される", dbd.get_diary(dw._date) == "テスト本文")
today = dw._date
dw._shift(-1)
check("前の日へ移れる", dw._date < today, dw._date)
check("別の日は空", dw.editor.toPlainText() == "")
dw._go_today()
check("今日へ戻れる", dw._date == today and dw.editor.toPlainText() == "テスト本文")

print("== メモウィンドウ ==")
db3 = LocalStore(Path(tempfile.mkdtemp()) / "n.db")
nw = NotesWindow(db3)
check("空なら編集欄は触れない", not nw.title.isEnabled())
nw._new_note()
check("新規で1件", len(db3.list_notes()) == 1)
check("編集できる状態", nw.title.isEnabled())
nw.title.setText("あとで読む")
nw.body.setPlainText("本文")
nw.save()
check("保存される", db3.list_notes()[0]["title"] == "あとで読む")
check("一覧の見出しが変わる", nw.list.item(0).text() == "あとで読む")
nw._new_note()
check("無題は（無題）と出る",
      any(nw.list.item(i).text() == "（無題）" for i in range(nw.list.count())))

print("== タイマー ==")
check("秒の整形", _fmt(65) == "01:05")
check("時間つき", _fmt(3725) == "01:02:05")
check("負値は0", _fmt(-5) == "00:00")
db4 = LocalStore(Path(tempfile.mkdtemp()) / "tm.db")
tw = TimerWindow(db4)
tw.min_spin.setValue(0); tw.sec_spin.setValue(1)
tw._toggle_timer()
check("開始すると終了時刻が入る", tw._timer_end is not None)
check("ボタンが一時停止に", tw.timer_start_btn.text() == "一時停止")
tw._toggle_timer()
check("一時停止で残りを覚える", tw._timer_end is None and tw._timer_rest > 0)
tw._toggle_timer()
tw._timer_end = datetime.now() - timedelta(seconds=1)   # 時間切れにする
tw._on_tick()
check("時間切れで郵便受けに積む", db4.unread_count() == 1)
check("ボタンが開始に戻る", tw.timer_start_btn.text() == "開始")
tw._reset_timer()
check("リセットで表示が戻る", tw.timer_display.text() == "00:01")

tw._alarm_at = datetime.now() - timedelta(seconds=1)
tw._on_tick()
check("アラームも積む", db4.unread_count() == 2)

tw._toggle_stopwatch()
time.sleep(0.05)
tw._on_tick()
tw._toggle_stopwatch()
check("ストップウォッチが進む", tw._sw_acc > 0, f"{tw._sw_acc:.3f}")
tw._reset_stopwatch()
check("リセットで0", tw._sw_acc == 0.0 and tw.sw_display.text() == "00:00")

print("== HUD ==")
class FakePC:
    def snapshot(self): return {"cpu": 12.0, "mem": 95.0, "disk": 60.0,
                                "diagnostics": {"cpu": True, "mem": False, "disk": True}}
class FakeMedia:
    available = True
    def display_text(self): return "YOASOBI - 夜に駆ける"
hud = HUDWindow(FakePC(), FakeMedia())
check("3つのゲージ", len(hud.gauges) == 3)
check("値が入る", hud.gauges["cpu"].value.text() == "12%", hud.gauges["cpu"].value.text())
check("異常は警告色", "b4453c" in hud.gauges["mem"].value.styleSheet(),
      hud.gauges["mem"].value.styleSheet())
check("正常は色なし", hud.gauges["cpu"].value.styleSheet() == "")
check("Now Playing が出る", hud.np_text.text() == "YOASOBI - 夜に駆ける")

class NoMedia:
    available = False
    def display_text(self): return ""
hud2 = HUDWindow(FakePC(), NoMedia())
check("SMTC 不可なら欄ごと隠す", not hud2.np_title.isVisible())

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
