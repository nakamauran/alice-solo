# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 設定。仕様書 §10。

    pyinstaller alice-solo.spec

onedir にしてある。onefile は起動のたびに展開が走って遅く、
assets（立ち絵が4MB近い）を抱えると体感がさらに落ちるため。

Qt の未使用モジュールを落として容量を削る。Solo 版は Web も
動画も QML も使わないので、まとめて除外できる。
"""
import re
from pathlib import Path

spec_dir = Path(SPECPATH)

# バージョンは alice_solo/__init__.py を正とする（§10）
_init = (spec_dir / "alice_solo" / "__init__.py").read_text(encoding="utf-8")
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', _init).group(1)
APP_NAME = "AliceSolo"
ICON = spec_dir / "assets" / "ui" / "app_icon.ico"

# 使わない Qt モジュール。入れると数百MBになる。
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSerialPort", "PySide6.QtSensors", "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtHelp", "PySide6.QtDesigner",
    "PySide6.QtUiTools", "PySide6.QtSvgWidgets",
    # 使っていない重い標準/外部モジュール
    "tkinter", "unittest", "pydoc", "doctest", "test",
    "numpy", "PIL", "matplotlib", "pandas",
]

a = Analysis(
    ["run.py"],
    pathex=[str(spec_dir)],
    binaries=[],
    # assets は丸ごと同梱する。キャラクターパックと config.yaml が要る。
    datas=[
        (str(spec_dir / "assets"), "assets"),
    ],
    hiddenimports=[
        # SMTC は任意依存。入っていれば拾う（無くても動く）
        "winsdk.windows.media.control",
        "winrt.windows.media.control",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,              # 常駐アプリ。黒窓を出さない
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
    version_info={
        "version": VERSION,
        "description": "Alice Solo",
        "product_name": "Alice Solo",
    } if False else None,       # version リソースは iss 側で付ける
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
