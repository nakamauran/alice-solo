"""SpriteCompositor の検証 + 全カテゴリの一覧画像を作る（オフスクリーン）。"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path

# リポジトリの場所はこのファイルからたどる。絶対パスを書くと
# 別の環境で動かない。
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPainter, QPixmap, QColor, QFont
from PySide6.QtCore import Qt

from alice_solo import config as C
from alice_solo.ui.sprite_compositor import SpriteCompositor

app = QApplication([])
pack = C.BUNDLED_CHARACTERS_DIR / "koyuki"
sc = SpriteCompositor(pack)

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {label} {extra}")
    else:    fail += 1; print(f"  FAIL {label} {extra}")

print("== 解決 ==")
check("neutral -> base", sc.resolve_file("neutral") == "normal.png")
check("happy_strong", sc.resolve_file("happy_strong") == "joy.png")
check("happy_weak は未登録 -> base", sc.resolve_file("happy_weak") == "normal.png")
check("angry は未登録 -> base", sc.resolve_file("angry") == "normal.png")
check("anxious -> thinking", sc.resolve_file("anxious") == "thinking.png")
check("drowsy と sleepy は同じ",
      sc.resolve_file("drowsy") == sc.resolve_file("sleepy") == "sleepy.png")
check("neutral+talking -> speak", sc.resolve_file("neutral", talking=True) == "speak.png")
# 改善仕様書 §6.2：発話中はカテゴリに関わらず口の開いた絵を優先する
check("sad+talking も speak", sc.resolve_file("sad", talking=True) == "speak.png")
check("発話が終われば sad に戻る", sc.resolve_file("sad") == "sad.png")
check("status thinking が最優先",
      sc.resolve_file("happy_strong", status="thinking") == "thinking.png")

print("== 倍率 ==")
scale = sc.content_scale()
check("base_content_height を読めている", sc.base_content_height == 1044.0, sc.base_content_height)
check("倍率 = 880/1044", abs(scale - 880.0/1044.0) < 1e-9, f"{scale:.4f}")

heights = {}
for cat in C.EMOTION_CATEGORIES:
    pm = sc.pixmap(cat, user_scale=1.0)
    heights[cat] = pm.height()
check("全カテゴリで同じ表示高さ", len(set(heights.values())) == 1, heights)
check("キャッシュ上限", len(sc._cache) <= C.SPRITE_CACHE_SIZE, len(sc._cache))

print("== 一覧画像 ==")
labels = ["neutral", "neutral(talking)", "happy_strong", "happy_weak",
          "sad", "angry", "shy", "anxious", "sleepy", "thinking(status)"]
pms = [
    sc.pixmap("neutral"), sc.pixmap("neutral", talking=True),
    sc.pixmap("happy_strong"), sc.pixmap("happy_weak"),
    sc.pixmap("sad"), sc.pixmap("angry"), sc.pixmap("shy"),
    sc.pixmap("anxious"), sc.pixmap("sleepy"),
    sc.pixmap("neutral", status="thinking"),
]
cw = max(p.width() for p in pms) + 16
ch = max(p.height() for p in pms) + 40
sheet = QPixmap(cw * len(pms), ch)
sheet.fill(QColor(40, 40, 48))
p = QPainter(sheet)
f = QFont(); f.setPointSize(11); p.setFont(f)
for i, (lab, pm) in enumerate(zip(labels, pms)):
    p.drawPixmap(i * cw + (cw - pm.width()) // 2, 30, pm)
    p.setPen(QColor(230, 230, 235))
    p.drawText(i * cw, 0, cw, 26, Qt.AlignCenter, lab)
p.end()
sheet.save("/home/claude/sprite_sheet.png")
print(f"  saved {sheet.width()}x{sheet.height()}")

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
