#!/usr/bin/env python3
"""立ち絵からアプリのアイコン（.ico）を作る。

ドット絵なので、縮小は NEAREST ではなく「整数倍で間引いてから
LANCZOS で詰める」二段にする。いきなり小さくすると線が消え、
NEAREST だけだと小サイズで形が崩れるため。

使い方:
    python3 tools/make_icon.py [--preview]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "characters" / "koyuki" / "sprites" / "normal.png"
OUT_ICO = ROOT / "assets" / "ui" / "app_icon.ico"
OUT_PNG = ROOT / "assets" / "ui" / "app_icon.png"

SIZES = (16, 24, 32, 48, 64, 128, 256)

# 顔を切り出す範囲。立ち絵の上部を正方形で取る。
HEAD_TOP_RATIO = 0.055      # 髪の先が切れない位置から
HEAD_SIZE_RATIO = 0.78      # 画像の幅に対する一辺


def head_box(im: Image.Image) -> tuple[int, int, int, int]:
    """顔まわりの正方形を返す。中身の横中心にそろえる。"""
    a = np.asarray(im.convert("RGBA"))
    opaque = a[:, :, 3] > 0
    ys, xs = np.nonzero(opaque)
    if len(xs) == 0:
        side = min(im.size)
        return 0, 0, side, side

    cx = int((xs.min() + xs.max()) / 2)
    top = int(im.height * HEAD_TOP_RATIO)
    side = int(im.width * HEAD_SIZE_RATIO)
    side = min(side, im.height - top)

    left = max(0, min(cx - side // 2, im.width - side))
    return left, top, left + side, top + side


def downscale(im: Image.Image, size: int) -> Image.Image:
    """ドット絵を崩さずに縮める。"""
    work = im
    # まず整数倍で間引く（ドットの格子を保つ）
    while work.width // 2 >= size:
        work = work.resize((work.width // 2, work.height // 2), Image.NEAREST)
    return work.resize((size, size), Image.LANCZOS)


def main() -> int:
    if not SRC.exists():
        print(f"元の画像がありません: {SRC}", file=sys.stderr)
        return 1

    im = Image.open(SRC).convert("RGBA")
    box = head_box(im)
    head = im.crop(box)
    print(f"切り出し: {box} -> {head.size}")

    OUT_ICO.parent.mkdir(parents=True, exist_ok=True)
    frames = [downscale(head, s) for s in SIZES]
    frames[-1].save(OUT_PNG)
    frames[-1].save(OUT_ICO, format="ICO",
                    sizes=[(s, s) for s in SIZES])
    print(f"書き出し: {OUT_ICO} ({OUT_ICO.stat().st_size // 1024}KB)")
    print(f"          {OUT_PNG}")

    if "--preview" in sys.argv:
        pad = 8
        width = sum(s + pad for s in SIZES) + pad
        sheet = Image.new("RGBA", (width, 256 + pad * 2), (45, 45, 55, 255))
        x = pad
        for s, f in zip(SIZES, frames):
            sheet.alpha_composite(f, (x, pad + (256 - s) // 2))
            x += s + pad
        sheet.convert("RGB").save(ROOT / "docs" / "icon_preview.png")
        print(f"見本: {ROOT / 'docs' / 'icon_preview.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
