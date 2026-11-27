"""自動起動。スタートアップフォルダにショートカットを置く。仕様書 §10。

レジストリの Run キーは使わない。利用者がエクスプローラで見て、
自分で消せるほうがよいため。

ショートカットの作成は Windows Script Host（WScript.Shell）経由で行う。
winshell のような追加パッケージは入れない。
失敗しても落とさない。設定値だけが残る。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

LINK_NAME = "Alice Solo.lnk"


def startup_dir() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata or sys.platform != "win32":
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def link_path() -> Path | None:
    d = startup_dir()
    return (d / LINK_NAME) if d else None


def is_enabled() -> bool:
    p = link_path()
    return bool(p and p.exists())


def _target() -> tuple[str, str, str]:
    """(実行ファイル, 引数, 作業フォルダ) を返す。

    配布版（PyInstaller）は exe を直接指す。開発中は pythonw.exe で
    run.py を起動する（コンソールの黒窓を出さないため）。
    """
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return exe, "", str(Path(exe).parent)

    root = Path(__file__).resolve().parent.parent
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw if pythonw.exists() else sys.executable)
    return exe, f'"{root / "run.py"}"', str(root)


def enable() -> bool:
    """スタートアップにショートカットを作る。できたら True。"""
    p = link_path()
    if p is None:
        return False
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        target, args, workdir = _target()

        import win32com.client            # type: ignore
        shell = win32com.client.Dispatch("WScript.Shell")
        link = shell.CreateShortCut(str(p))
        link.TargetPath = target
        link.Arguments = args
        link.WorkingDirectory = workdir
        link.IconLocation = _icon_location(target)
        link.Save()
        return True
    except ImportError:
        return _enable_via_powershell()
    except Exception:
        return False


def _enable_via_powershell() -> bool:
    """pywin32 が無い環境でも作れるように PowerShell で作る。"""
    p = link_path()
    if p is None:
        return False
    try:
        import subprocess

        target, args, workdir = _target()
        script = (
            "$s=(New-Object -COM WScript.Shell).CreateShortcut('%s');"
            "$s.TargetPath='%s';$s.Arguments='%s';"
            "$s.WorkingDirectory='%s';$s.IconLocation='%s';$s.Save()"
        ) % (p, target, args.replace("'", "''"), workdir, _icon_location(target))
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True, capture_output=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return p.exists()
    except Exception:
        return False


def _icon_location(target: str) -> str:
    from . import config as C
    ico = C.ASSETS_DIR / "ui" / "app_icon.ico"
    return str(ico) if ico.exists() else target


def disable() -> bool:
    """ショートカットを消す。もともと無ければ何もせず True。"""
    p = link_path()
    if p is None:
        return False
    try:
        if p.exists():
            p.unlink()
        return True
    except OSError:
        return False


def apply(enabled: bool) -> bool:
    return enable() if enabled else disable()
