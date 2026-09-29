import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "history.db"
_local = threading.local()


def _conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        c.row_factory = sqlite3.Row
        _local.conn = c
    return c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    conn = _conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY,
            title TEXT DEFAULT '',
            model TEXT DEFAULT '',
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            role TEXT,
            content TEXT,
            image_request TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            message_id INTEGER,
            prompt_en TEXT,
            seed INTEGER,
            steps INTEGER,
            cfg REAL,
            aspect TEXT,
            filename TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    _migrate()
    conn.commit()


def _migrate() -> None:
    conn = _conn()
    for col, decl in (("tps", "REAL"), ("tokens", "INTEGER"), ("seconds", "REAL"), ("thinking", "INTEGER")):
        try:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass


def create_session() -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO sessions (title, model, created_at) VALUES ('', '', ?)", (_now(),)
    )
    conn.commit()
    return cur.lastrowid


def set_session_title(session_id: int, title: str, model: str) -> None:
    conn = _conn()
    conn.execute("UPDATE sessions SET title = ?, model = ? WHERE id = ?", (title, model, session_id))
    conn.commit()


def add_message(session_id: int, role: str, content: str, image_request: str | None = None,
                tps: float | None = None, tokens: int | None = None, seconds: float | None = None,
                thinking: int | None = None) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO messages (session_id, role, content, image_request, tps, tokens, seconds, thinking, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, role, content, image_request, tps, tokens, seconds, thinking, _now()),
    )
    conn.commit()
    return cur.lastrowid


def get_session(session_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def list_sessions() -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        """
        SELECT s.id, s.title, s.model, s.created_at,
               (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count,
               (SELECT COUNT(*) FROM images i WHERE i.session_id = s.id) AS image_count
        FROM sessions s
        ORDER BY s.id DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_messages(session_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_images(session_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM images WHERE session_id = ? ORDER BY id ASC", (session_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def add_image(session_id, message_id, prompt_en, seed, steps, cfg, aspect, filename) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO images (session_id, message_id, prompt_en, seed, steps, cfg, aspect, filename, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, message_id, prompt_en, seed, steps, cfg, aspect, filename, _now()),
    )
    conn.commit()
    return cur.lastrowid


def get_image(image_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
    return dict(row) if row else None


def get_setting(key: str) -> str | None:
    conn = _conn()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    conn = _conn()
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    conn.commit()


def delete_setting(key: str) -> None:
    conn = _conn()
    conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    conn.commit()
