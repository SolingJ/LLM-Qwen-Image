import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "history.db"
ASSETS_ROOT = DB_PATH.parent / "assets"
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


def delete_session(session_id: int) -> bool:
    conn = _conn()
    conn.execute("DELETE FROM images WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    return cur.rowcount > 0


def fork_session(source_id: int, message_id: int) -> int | None:
    conn = _conn()
    src = conn.execute("SELECT * FROM sessions WHERE id = ?", (source_id,)).fetchone()
    msg = conn.execute("SELECT * FROM messages WHERE id = ? AND session_id = ?", (message_id, source_id)).fetchone()
    if not src or not msg:
        return None

    title = (src["title"] or f"セッション {source_id}") + " (fork)"
    cur = conn.execute(
        "INSERT INTO sessions (title, model, created_at) VALUES (?, ?, ?)",
        (title, src["model"], _now()),
    )
    new_id = cur.lastrowid

    rows = conn.execute(
        "SELECT * FROM messages WHERE session_id = ? AND id <= ? ORDER BY id ASC",
        (source_id, message_id),
    ).fetchall()

    old_to_new = {}
    for m in rows:
        c = conn.execute(
            "INSERT INTO messages (session_id, role, content, image_request, tps, tokens, seconds, thinking, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id,
                m["role"],
                m["content"],
                m["image_request"],
                m["tps"],
                m["tokens"],
                m["seconds"],
                m["thinking"],
                m["created_at"],
            ),
        )
        old_to_new[m["id"]] = c.lastrowid

    if old_to_new:
        qs = ",".join("?" for _ in old_to_new)
        imgs = conn.execute(
            f"SELECT * FROM images WHERE session_id = ? AND message_id IN ({qs})",
            [source_id, *old_to_new.keys()],
        ).fetchall()
        for im in imgs:
            new_filename = im["filename"]
            src_path = ASSETS_ROOT / im["filename"]
            if src_path.exists():
                new_filename = f"{new_id}/{Path(im['filename']).name}"
                dest_path = ASSETS_ROOT / new_filename
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dest_path)
            conn.execute(
                "INSERT INTO images (session_id, message_id, prompt_en, seed, steps, cfg, aspect, filename, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id,
                    old_to_new[im["message_id"]],
                    im["prompt_en"],
                    im["seed"],
                    im["steps"],
                    im["cfg"],
                    im["aspect"],
                    new_filename,
                    im["created_at"],
                ),
            )

    conn.commit()
    return new_id


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
