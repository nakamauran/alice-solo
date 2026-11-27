"""吹き出しの採寸検証。描画結果の実ピクセルから、文字がはみ出していないか見る。"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path

# リポジトリの場所はこのファイルからたどる。絶対パスを書くと
# 別の環境で動かない。
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtCore import QPoint, Qt

from alice_solo.ui.vpet_window import BubbleWindow

app = QApplication([])
ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {label} {extra}")
    else:    fail += 1; print(f"  FAIL {label} {extra}")

CASES = [
    "……ねむい。",
    "……っ、そういうの、よく分からない。",
    "うん、いいよ。無理しないでね。今日はゆっくり休んだほうがいいと思うな。",
    "あ",
    "……。",
    "今 12 時 34 分だよ。" * 6,
]

b = BubbleWindow()
for text in CASES:
    b.show_text(text, QPoint(500, 500), 999_999)
    w, h = b.width(), b.height()

    # 実際に描かせて、文字の黒ピクセルが角丸の内側に収まっているか確かめる
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    b.render(pm)
    img = pm.toImage()

    ink = [(x, y) for y in range(h) for x in range(w)
           if img.pixelColor(x, y).alpha() > 0
           and img.pixelColor(x, y).lightness() < 120]
    label = (text[:18] + "…") if len(text) > 18 else text
    if not ink:
        check(f"描画あり: {label}", False, "文字が描かれていない")
        continue
    xs = [p[0] for p in ink]; ys = [p[1] for p in ink]
    right_gap = w - 1 - max(xs)
    bottom_gap = h - 1 - min(max(ys), h - 1)
    check(f"右が切れていない: {label}", right_gap >= 4, f"余白{right_gap}px w={w}")
    check(f"下が切れていない: {label}", bottom_gap >= 4, f"余白{bottom_gap}px h={h}")
    check(f"左上も収まる: {label}", min(xs) >= 4 and min(ys) >= 4,
          f"left={min(xs)} top={min(ys)}")
    check(f"最大幅を超えない: {label}", w <= b.MAX_WIDTH + b.PADDING*2 + b.SLACK, f"w={w}")

# 位置：頭の上に出る
b.show_text("てすと", QPoint(500, 400), 999_999)
check("アンカーの上に出る", b.y() + b.height() <= 400, f"y={b.y()} h={b.height()}")
check("アンカー中央に寄る", abs((b.x() + b.width()//2) - 500) <= 1, f"x={b.x()}")

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
