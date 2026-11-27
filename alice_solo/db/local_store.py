"""SQLite。郵便受け・日記・メモ。仕様書 v2.0 §3.4, §3.5。

サーバーの REST を置き換える層。呼び出し側は直接メソッドを叩く。
接続はスレッドごとに持つ（sqlite3 の接続はスレッドをまたげない）。
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from .. import config as C

SCHEMA = """
CREATE TABLE IF NOT EXISTS inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    device_id TEXT NOT NULL DEFAULT '',
    title TEXT,
    body TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP,
    UNIQUE(source, dedupe_key, device_id)
);

CREATE TABLE IF NOT EXISTS diary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,
    content TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                  -- 'like' / 'name'
    key TEXT NOT NULL,                   -- 覚えた対象
    text TEXT NOT NULL,                  -- 呼び戻しに使う文言
    created_date TEXT NOT NULL,          -- today_key 形式
    last_mentioned_date TEXT,
    mention_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(kind, key)
);

CREATE TABLE IF NOT EXISTS chat_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                  -- today_key 形式（朝5時境）
    role TEXT NOT NULL,                  -- 'user' / 'alice' / 'system'
    text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_inbox_read ON inbox(read_at, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_date ON chat_log(date, id);
"""


class LocalStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else C.DB_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self._conn() as c:
            c.executescript(SCHEMA)
        self._vacuum_if_large()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return conn

    def _vacuum_if_large(self) -> None:
        """起動時に 10MB を超えていたら詰める。仕様書 §3.5。"""
        try:
            if self.path.stat().st_size <= C.DB_VACUUM_THRESHOLD_BYTES:
                return
            self._conn().execute("VACUUM")
        except (OSError, sqlite3.Error):
            pass

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ------------------------------------------------------------ 郵便受け

    def put_inbox(self, source: str, dedupe_key: str, title: str,
                  body: str = "") -> None:
        """投函する。同じ鍵なら中身を上書きし、既読状態は保つ。"""
        with self._conn() as c:
            c.execute(
                """INSERT INTO inbox (source, dedupe_key, device_id, title, body)
                   VALUES (?, ?, '', ?, ?)
                   ON CONFLICT(source, dedupe_key, device_id)
                   DO UPDATE SET title=excluded.title, body=excluded.body""",
                (source, dedupe_key, title, body),
            )

    def get_inbox(self, unread_only: bool = False, limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM inbox"
        if unread_only:
            sql += " WHERE read_at IS NULL"
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, (limit,))]

    def unread_count(self) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM inbox WHERE read_at IS NULL"
            ).fetchone()
        return int(row["n"]) if row else 0

    def mark_read(self, item_id: int) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE inbox SET read_at=CURRENT_TIMESTAMP WHERE id=? AND read_at IS NULL",
                (item_id,),
            )

    def mark_all_read(self) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE inbox SET read_at=CURRENT_TIMESTAMP WHERE read_at IS NULL"
            )

    def delete_inbox(self, item_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM inbox WHERE id=?", (item_id,))

    def purge_inbox(self, days: int | None = None,
                    now: datetime | None = None) -> int:
        """古い投函を消す。戻り値は消した件数。仕様書 §3.5。"""
        if days is None:
            days = int(C.app_value("inbox.retention_days",
                                   C.INBOX_RETENTION_DAYS))
        limit = (now or datetime.now()) - timedelta(days=days)
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM inbox WHERE created_at < ?",
                (limit.strftime("%Y-%m-%d %H:%M:%S"),),
            )
            return cur.rowcount or 0

    # ------------------------------------------------------------ 日記

    def get_diary(self, date: str) -> str:
        with self._conn() as c:
            row = c.execute(
                "SELECT content FROM diary WHERE date=?", (date,)
            ).fetchone()
        return (row["content"] or "") if row else ""

    def save_diary(self, date: str, content: str) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO diary (date, content) VALUES (?, ?)
                   ON CONFLICT(date) DO UPDATE SET
                     content=excluded.content, updated_at=CURRENT_TIMESTAMP""",
                (date, content),
            )

    def diary_dates(self, limit: int = 400) -> list[str]:
        """書いた日の一覧。新しい順。空の日は含めない。"""
        with self._conn() as c:
            return [
                r["date"] for r in c.execute(
                    """SELECT date FROM diary
                       WHERE content IS NOT NULL AND TRIM(content) <> ''
                       ORDER BY date DESC LIMIT ?""", (limit,)
                )
            ]

    def delete_diary(self, date: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM diary WHERE date=?", (date,))

    # ------------------------------------------------------------ メモ

    def list_notes(self) -> list[dict]:
        with self._conn() as c:
            return [
                dict(r) for r in c.execute(
                    "SELECT * FROM notes ORDER BY updated_at DESC, id DESC"
                )
            ]

    def create_note(self, title: str = "", content: str = "") -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO notes (title, content) VALUES (?, ?)", (title, content)
            )
            return int(cur.lastrowid)

    def update_note(self, note_id: int, title: str, content: str) -> None:
        with self._conn() as c:
            c.execute(
                """UPDATE notes SET title=?, content=?, updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (title, content, note_id),
            )

    def delete_note(self, note_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM notes WHERE id=?", (note_id,))

    # ------------------------------------------------------------ 記憶（§3.4）

    def save_memory(self, kind: str, key: str, text: str,
                    now: datetime | None = None) -> None:
        """覚える。同じものを言い直されたら文言だけ更新し、日付は据え置く。

        日付を更新すると、毎日言うたびに呼び戻しが先送りされてしまう。
        """
        from ..engine.self_engine import store as _store
        today = _store.today_key(now or datetime.now())
        with self._conn() as c:
            c.execute(
                """INSERT INTO memories (kind, key, text, created_date)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(kind, key) DO UPDATE SET text=excluded.text""",
                (kind, key, text, today),
            )
        self.purge_memories()

    def get_memory_candidates(self, now: datetime | None = None) -> list[dict]:
        """呼び戻してよい記憶。新しい順ではなく、言った回数の少ない順。"""
        from ..engine.self_engine import store as _store
        from .. import config as C

        now = now or datetime.now()
        today = _store.today_key(now)
        out: list[dict] = []
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM memories WHERE kind != 'name'"
            )]
        for r in rows:
            age = _store.day_distance(r.get("created_date") or "", today)
            if not (C.MEMORY_CALLBACK_MIN_DAYS <= age <= C.MEMORY_CALLBACK_MAX_DAYS):
                continue
            if int(r.get("mention_count") or 0) >= C.MEMORY_MAX_MENTIONS:
                continue
            last = r.get("last_mentioned_date")
            if last and _store.day_distance(last, today) < C.MEMORY_CALLBACK_COOLDOWN_DAYS:
                continue
            out.append(r)
        out.sort(key=lambda r: (int(r.get("mention_count") or 0),
                                r.get("created_date") or ""))
        return out

    def mark_memory_mentioned(self, memory_id: int,
                              now: datetime | None = None) -> None:
        from ..engine.self_engine import store as _store
        today = _store.today_key(now or datetime.now())
        with self._conn() as c:
            c.execute(
                """UPDATE memories
                   SET last_mentioned_date=?, mention_count=mention_count+1
                   WHERE id=?""",
                (today, memory_id),
            )

    def get_memory(self, kind: str, key: str) -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM memories WHERE kind=? AND key=?", (kind, key)
            ).fetchone()
        return dict(row) if row else None

    def purge_memories(self) -> int:
        """上限を超えたら古いものから捨てる。名前は捨てない。"""
        from .. import config as C
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM memories WHERE kind != 'name'"
            ).fetchone()
            over = int(row["n"]) - C.MEMORY_MAX_ITEMS
            if over <= 0:
                return 0
            cur = c.execute(
                """DELETE FROM memories WHERE id IN (
                       SELECT id FROM memories WHERE kind != 'name'
                       ORDER BY created_date ASC, id ASC LIMIT ?)""",
                (over,),
            )
            return cur.rowcount or 0

    # ------------------------------------------------------------ チャット履歴（§5）

    def save_chat(self, role: str, text: str, now: datetime | None = None) -> None:
        from ..engine.self_engine import store as _store
        from .. import config as C

        today = _store.today_key(now or datetime.now())
        with self._conn() as c:
            c.execute(
                "INSERT INTO chat_log (date, role, text) VALUES (?, ?, ?)",
                (today, role, text),
            )
            # 1日あたりの上限。超えたぶんは古い行から捨てる
            c.execute(
                """DELETE FROM chat_log WHERE date=? AND id NOT IN (
                       SELECT id FROM chat_log WHERE date=?
                       ORDER BY id DESC LIMIT ?)""",
                (today, today, C.CHAT_LOG_MAX_PER_DAY),
            )

    def get_chat_log(self, date: str | None = None,
                     now: datetime | None = None) -> list[dict]:
        """当日分の履歴。古い順に返す。"""
        from ..engine.self_engine import store as _store
        date = date or _store.today_key(now or datetime.now())
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM chat_log WHERE date=? ORDER BY id ASC", (date,)
            )]

    def purge_chat_log(self, keep_date: str | None = None,
                       now: datetime | None = None) -> int:
        """当日以外の履歴を消す。履歴は当日分しか持たない（§5）。"""
        from ..engine.self_engine import store as _store
        keep = keep_date or _store.today_key(now or datetime.now())
        with self._conn() as c:
            cur = c.execute("DELETE FROM chat_log WHERE date != ?", (keep,))
            return cur.rowcount or 0
