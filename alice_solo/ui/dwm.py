"""Windows 11 の DWM がフレームレス窓に付ける装飾を消す。

角丸(33)と背景(38)だけでは枠線が残る。境界色(34)に DWMWA_COLOR_NONE を
入れるのが要点。show() でネイティブ窓が作り直されるため、showEvent() から
毎回呼ぶこと。

透過して常駐する窓すべて（立ち絵・郵便受けアイコン・HUD）に当てる。
1つでも忘れると、その窓だけ灰色の角丸板が背後に出る。
"""
from __future__ import annotations

import sys

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWA_COLOR_NONE = 0xFFFFFFFE
DWMWCP_DONOTROUND = 1
DWMSBT_NONE = 1


def apply_dwm_fixes(hwnd: int) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes
        from ctypes import wintypes

        dwm = ctypes.windll.dwmapi

        def set_attr(attr: int, value: int) -> None:
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), ctypes.c_uint(attr),
                ctypes.byref(v), ctypes.sizeof(v),
            )

        set_attr(DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND)
        set_attr(DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_NONE)
        set_attr(DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE)
    except Exception:
        pass      # 枠線が残るだけなので落とさない
