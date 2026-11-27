"""バックアップの書き出しと復元。仕様書 v2.0 §3.6。

復元は上書きなので、転んだときに戻せるよう、先に現状を控える。
zip の中身は外から来たファイルとして扱い、展開先が保存フォルダの
外へ出ないことを必ず確かめる（zip slip 対策）。
"""
from __future__ import annotations

import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from . import config as C

SUFFIX = ".alicebackup.zip"

# 控えなくてよいもの。書き込み途中の破片とログは持って行かない。
SKIP_SUFFIXES = {".tmp"}
SKIP_DIRS = {"logs"}

# これが1つでも入っていれば Alice のバックアップとみなす
MARKERS = ("state.json", "user_config.json", "self/", "local_store.db")


def _is_marker(name: str) -> bool:
    """MARKERS 判定（完全一致寄り）。

    "state.json.bak" のような別ファイルを "state.json" の
    前方一致で拾わない。ディレクトリのマーカー（"self/"）は
    その配下ならよい。
    """
    for m in MARKERS:
        if m.endswith("/"):
            if name.startswith(m):
                return True
        elif name == m or name.startswith(m + "/"):
            return True
    return False


def default_name(now: datetime | None = None) -> str:
    return f"alice_{(now or datetime.now()):%Y%m%d_%H%M%S}{SUFFIX}"


# ---------------------------------------------------------------- 書き出し

def export_to(dest: Path, data_dir: Path | None = None) -> int:
    """保存フォルダを zip に固める。戻り値は入れたファイル数。"""
    root = Path(data_dir or C.DATA_DIR)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()

    count = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            if not f.is_file():
                continue
            if f.resolve() == dest_resolved:
                continue    # 書き出し先自身（保存フォルダ内に出す場合）は入れない
            rel = f.relative_to(root)
            if f.suffix in SKIP_SUFFIXES:
                continue
            if rel.parts and rel.parts[0] in SKIP_DIRS:
                continue
            z.write(f, rel.as_posix())
            count += 1
    return count


# ---------------------------------------------------------------- 復元

def inspect(src: Path) -> dict:
    """復元してよい zip か調べる。開かずに中身だけ見る。"""
    src = Path(src)
    out = {"ok": False, "reason": "", "files": 0, "unsafe": []}
    try:
        with zipfile.ZipFile(src) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
    except (OSError, zipfile.BadZipFile):
        out["reason"] = "zip として読めません。"
        return out

    if not names:
        out["reason"] = "中身が空です。"
        return out

    # 保存フォルダの外へ出ようとするものが混ざっていないか
    unsafe = [
        n for n in names
        if n.startswith("/") or ".." in Path(n).parts or Path(n).is_absolute()
        or (len(n) > 1 and n[1] == ":")
    ]
    if unsafe:
        out["unsafe"] = unsafe[:5]
        out["reason"] = "保存フォルダの外を指すファイルが含まれています。"
        return out

    if not any(_is_marker(n) for n in names):
        out["reason"] = "Alice のバックアップではないようです。"
        return out

    out["ok"] = True
    out["files"] = len(names)
    return out


def restore_from(src: Path, data_dir: Path | None = None) -> dict:
    """zip の中身で保存フォルダを上書きする（マージであり置き換えではない）。

    戻り値は {"ok", "reason", "restored", "safety_copy"}。
    復元前の状態は safety_copy に残すので、失敗しても戻せる。
    復元前に保存フォルダ内を空にする「置き換え」化は未対応。バックアップに
    含まれていないファイル（ログや利用者の追加ファイル）まで消す破壊的な
    操作になるため、勝手な全削除はしない。
    """
    root = Path(data_dir or C.DATA_DIR)
    info = inspect(src)
    if not info["ok"]:
        return {"ok": False, "reason": info["reason"], "restored": 0,
                "safety_copy": None}

    root.mkdir(parents=True, exist_ok=True)
    safety = root.parent / f"alice_restore_backup_{datetime.now():%Y%m%d_%H%M%S}.zip"
    try:
        export_to(safety, root)
    except OSError:
        safety = None       # 控えが取れなくても復元自体は続ける

    root_resolved = root.resolve()
    restored = 0
    try:
        with zipfile.ZipFile(src) as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                target = (root / name).resolve()
                # 念のためもう一度、展開先が保存フォルダの内側か確かめる
                if not target.is_relative_to(root_resolved):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as fsrc, open(target, "wb") as fdst:
                    shutil.copyfileobj(fsrc, fdst)
                restored += 1
    except (OSError, zipfile.BadZipFile) as e:
        return {"ok": False, "reason": str(e), "restored": restored,
                "safety_copy": safety}

    return {"ok": True, "reason": "", "restored": restored,
            "safety_copy": safety}
