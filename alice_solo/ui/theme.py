"""配色とスタイルシート。原型クライアント common.py からの移植。

QApplication レベルで当てることで、あとから作るウィンドウにも自動で
反映される。配色は theme.json に保存し、設定ウィンドウから変えられる。
"""
from __future__ import annotations

from pathlib import Path

from .. import config as C
from ..engine.self_engine import store

# 配色のトークン。5色から8色に増やした（改善仕様書 §6.1）。
#   surface   … 吹き出し・メニューの地。background より一段手前の面
#   text_sub  … 補足・ショートカットなど、本文より弱い文字
#   warn      … 警告。これまで hud_window.py に直書きしていたものを集約
DEFAULT_THEME = {
    "background": "#fffaf7",      # 窓・パネルの地
    "surface": "#ffffff",         # 吹き出し・メニュー
    "text": "#5f4d45",            # 本文
    "text_sub": "#a08a80",        # 補足
    "accent": "#ffe5d8",          # 主ボタン・バー
    "accent_border": "#f1b7a8",   # 区切り・枠線
    "highlight": "#ffd9e0",       # ホバー・選択・自分の発言
    "warn": "#b4453c",            # 警告（全プリセット共通寄り）
    "on_accent": "#5f4d45",       # accent の上に載る文字色
}

# プリセット。設定画面の3ボタンから選ぶ。
# 「こゆき」はパック固有テーマの見本で、パック切替で連動させる想定。
PRESETS: dict[str, dict] = {
    "light": {
        "label": "明るい",
        "background": "#fffaf7",
        "surface": "#ffffff",
        "text": "#5f4d45",
        "text_sub": "#a08a80",
        "accent": "#ffe5d8",
        "accent_border": "#f1b7a8",
        "highlight": "#ffd9e0",
        "warn": "#b4453c",
        "on_accent": "#5f4d45",     # accent が淡いので文字は本文色のまま
    },
    "dark": {
        "label": "夜",
        "background": "#2b2624",
        "surface": "#3a3230",
        "text": "#f5ebe6",
        "text_sub": "#b5a49c",
        "accent": "#4a3a35",
        "accent_border": "#7a5a52",
        "highlight": "#5a4038",
        "warn": "#e07856",
        "on_accent": "#f5ebe6",
    },
    "koyuki": {
        "label": "こゆき",
        "background": "#f4f8fc",
        "surface": "#ffffff",
        "text": "#3d4f61",
        "text_sub": "#7e97ab",
        "accent": "#5b8db8",
        "accent_border": "#d3e4f1",
        "highlight": "#d9ecfa",     # accent-soft：ホバー・自分の発言
        "warn": "#b4453c",
        "on_accent": "#ffffff",     # accent が濃い青なので文字は白
    },
}

DEFAULT_PRESET = "light"

THEME_LABELS = {
    "background": "背景色",
    "surface": "面の色（吹き出し）",
    "text": "文字色",
    "text_sub": "補足の文字色",
    "accent": "アクセント色（ボタン等）",
    "accent_border": "縁取り色",
    "highlight": "ハイライト色（選択時）",
    "warn": "警告色",
    "on_accent": "ボタンの文字色",
}

THEME_FILE = C.DATA_DIR / "theme.json"


def load_theme() -> dict:
    """保存された配色。プリセットを土台に、個別指定があれば上に載せる。"""
    d = store.read_json(THEME_FILE, {})
    preset = d.get("preset") if d.get("preset") in PRESETS else DEFAULT_PRESET
    theme = {k: v for k, v in PRESETS[preset].items() if k != "label"}
    theme.update({k: v for k, v in d.items() if k in DEFAULT_THEME})
    theme["preset"] = preset
    return theme


def apply_preset(name: str) -> dict:
    """プリセットを当てる。個別指定はすべて上書きされる（§6.1）。"""
    if name not in PRESETS:
        name = DEFAULT_PRESET
    theme = {k: v for k, v in PRESETS[name].items() if k != "label"}
    theme["preset"] = name
    store.write_json(THEME_FILE, theme)
    return theme


def save_theme(theme: dict) -> None:
    out = {k: v for k, v in theme.items() if k in DEFAULT_THEME}
    if theme.get("preset") in PRESETS:
        out["preset"] = theme["preset"]
    store.write_json(THEME_FILE, out)


def build_stylesheet(theme: dict | None = None) -> str:
    t = dict(DEFAULT_THEME)
    if theme:
        t.update({k: v for k, v in theme.items() if k in DEFAULT_THEME})

    return f"""
QWidget, QDialog {{
  background-color: {t['background']};
  color: {t['text']};
  font-family: "Yu Gothic UI", "Meiryo", "Segoe UI", sans-serif;
}}
QLabel {{
  color: {t['text']};
  background: transparent;
}}

/* 主ボタン。accent は「主ボタン・バー・チェック」の色なので、
   地に敷いて文字は on_accent にする。淡色テーマでは on_accent が
   本文色なので、これまでと同じ見た目になる。 */
QPushButton {{
  background: {t['accent']};
  color: {t['on_accent']};
  border: 1px solid {t['accent']};
  border-radius: 8px;
  padding: 6px 12px;
}}
QPushButton:hover {{
  background: {t['highlight']};
  color: {t['text']};
  border: 1px solid {t['accent']};
}}
QPushButton:pressed {{
  background: {t['accent_border']};
  color: {t['text']};
}}
QPushButton:disabled {{
  background: {t['accent_border']};
  color: {t['text_sub']};
  border: 1px solid {t['accent_border']};
}}

/* 入力欄は surface（白）に置く。地と同色だと境目が消える。 */
QLineEdit, QTextEdit, QPlainTextEdit, QListWidget, QSpinBox, QDoubleSpinBox,
QComboBox, QTimeEdit {{
  background: {t['surface']};
  color: {t['text']};
  border: 1px solid {t['accent_border']};
  border-radius: 8px;
  padding: 6px;
  selection-background-color: {t['highlight']};
  selection-color: {t['text']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus {{
  border: 1px solid {t['accent']};
}}
QComboBox QAbstractItemView {{
  background: {t['surface']};
  color: {t['text']};
  selection-background-color: {t['highlight']};
  selection-color: {t['text']};
  border: 1px solid {t['accent_border']};
}}
QListWidget::item:hover {{ background: {t['highlight']}; }}
QListWidget::item:selected {{ background: {t['highlight']}; color: {t['text']}; }}

QCheckBox {{ background: transparent; }}
QCheckBox::indicator {{
  width: 16px;
  height: 16px;
  border: 1px solid {t['accent_border']};
  border-radius: 4px;
  background-color: {t['surface']};
}}
QCheckBox::indicator:checked {{
  background-color: {t['accent']};
  border: 1px solid {t['accent']};
}}

QSlider::groove:horizontal {{
  height: 6px;
  background: {t['accent_border']};
  border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
  height: 6px;
  background: {t['accent']};
  border-radius: 3px;
}}
QSlider::handle:horizontal {{
  width: 14px;
  margin: -5px 0;
  background: {t['accent']};
  border: 1px solid {t['accent']};
  border-radius: 7px;
}}

QProgressBar {{
  background: {t['accent_border']};
  border: none;
  border-radius: 5px;
}}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 5px; }}

QGroupBox {{
  border: 1px solid {t['accent_border']};
  border-radius: 8px;
  margin-top: 10px;
  padding-top: 10px;
}}
QGroupBox::title {{
  subcontrol-origin: margin;
  left: 10px;
  padding: 0 4px;
  color: {t['text_sub']};
}}

QTabWidget::pane {{
  border: 1px solid {t['accent_border']};
  border-radius: 8px;
  background: {t['surface']};
}}
QTabBar::tab {{
  background: {t['background']};
  color: {t['text_sub']};
  padding: 6px 14px;
  border: 1px solid {t['accent_border']};
  border-bottom: none;
  border-top-left-radius: 6px;
  border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{
  background: {t['surface']};
  color: {t['text']};
}}
QTabBar::tab:hover {{ background: {t['highlight']}; color: {t['text']}; }}

QMenu {{
  background-color: {t['surface']};
  color: {t['text']};
  border: 1px solid {t['accent_border']};
  border-radius: 8px;
}}
QMenu::item {{ padding: 6px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background-color: {t['highlight']}; color: {t['text']}; }}
QMenu::item:disabled {{ color: {t['text_sub']}; }}
QMenu::separator {{ height: 1px; background: {t['accent_border']}; margin: 4px 8px; }}

QMessageBox {{ background-color: {t['background']}; }}
QScrollBar:vertical {{
  background: {t['background']};
  width: 10px;
  border-radius: 5px;
}}
QScrollBar::handle:vertical {{ background: {t['accent_border']}; border-radius: 5px; }}
QScrollBar::handle:vertical:hover {{ background: {t['accent']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QFrame[frameShape="4"] {{ color: {t['accent_border']}; }}
QToolTip {{
  background-color: {t['surface']};
  color: {t['text']};
  border: 1px solid {t['accent_border']};
  border-radius: 6px;
  padding: 4px;
}}
"""


def apply_theme(app, theme: dict | None = None) -> None:
    app.setStyleSheet(build_stylesheet(theme or load_theme()))
