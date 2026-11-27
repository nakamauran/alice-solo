"""画面構成キーと画面内クランプ（UI補助）。

画面構成キー生成（画面数・解像度・並び）と、座標を現在の全画面
ジオメトリ内に収める clamp_point() を提供する。構成ごとの位置記憶は
しない（キーは将来の識別用に残す）。

PySide6 が無くても import できるよう、Qt への依存は関数内の遅延
import にしてある。Qt が無い・画面が取れない場合はフォールバックする。
"""
from __future__ import annotations


def _screens() -> list[tuple[int, int, int, int]]:
    """全画面のジオメトリ [(x, y, w, h), ...]。Qt が無ければ空。"""
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        return []
    app = QGuiApplication.instance()
    if app is None:
        return []
    rects = []
    for screen in QGuiApplication.screens():
        g = screen.geometry()
        rects.append((g.x(), g.y(), g.width(), g.height()))
    return sorted(rects)


def screen_layout_key() -> str:
    """画面構成キー。例: "2:0,0,1920x1080|1920,0,1920x1080"。

    画面数・各画面の位置と解像度・並び（左から・上から順）から作る。
    Qt が無い・画面が取れない場合は "unknown"。
    """
    rects = _screens()
    if not rects:
        return "unknown"
    parts = ",".join(f"{x},{y},{w}x{h}" for x, y, w, h in rects)
    return f"{len(rects)}:{parts}"


def virtual_geometry() -> tuple[int, int, int, int] | None:
    """全画面を覆う仮想ジオメトリ (x, y, w, h)。取れなければ None。"""
    rects = _screens()
    if not rects:
        return None
    left = min(x for x, _y, _w, _h in rects)
    top = min(y for _x, y, _w, _h in rects)
    right = max(x + w for x, _y, w, _h in rects)
    bottom = max(y + h for _x, y, _w, h in rects)
    return (left, top, right - left, bottom - top)


def clamp_point_to_rect(
    x: int, y: int, w: int, h: int, rect: tuple[int, int, int, int]
) -> tuple[int, int]:
    """幅 w・高さ h の窓の左上 (x, y) を rect 内に収める。"""
    left, top, width, height = rect
    x = max(left, min(x, left + max(0, width - w)))
    y = max(top, min(y, top + max(0, height - h)))
    return (x, y)


def clamp_point(x: int, y: int, w: int, h: int) -> tuple[int, int]:
    """幅 w・高さ h の窓の左上 (x, y) を現在の全画面内に収める。

    Qt が無い・画面が取れない場合は負の座標だけを 0 にする。
    """
    geom = virtual_geometry()
    if geom is None:
        return (max(0, x), max(0, y))
    return clamp_point_to_rect(x, y, w, h, geom)


def snap_point(x: int, y: int, w: int, h: int,
               distance: int | None = None) -> tuple[int, int]:
    """画面端に近ければ吸着させる（改善仕様書 §8）。

    ドラッグ中だけ使う。端にぴたりと合わせたいのに1pxずれる、という
    地味な面倒を無くすためのもの。
    """
    from .. import config as C
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    distance = C.SNAP_DISTANCE_PX if distance is None else distance
    screen = QApplication.screenAt(QPoint(x + w // 2, y + h // 2)) \
        or QApplication.primaryScreen()
    if screen is None:
        return x, y
    g = screen.availableGeometry()

    if abs(x - g.left()) <= distance:
        x = g.left()
    elif abs((x + w) - g.right() - 1) <= distance:
        x = g.right() + 1 - w
    if abs(y - g.top()) <= distance:
        y = g.top()
    elif abs((y + h) - g.bottom() - 1) <= distance:
        y = g.bottom() + 1 - h
    return x, y
