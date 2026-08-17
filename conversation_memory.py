"""
JARVIS Conversation Memory — persistent chat history across sessions.

Every user turn and JARVIS reply is stored in SQLite so JARVIS can recall
previous conversations ("last time we discussed..."), warm-start new sessions
with recent context, and search past exchanges.
"""

import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("jarvis.convo")

DB_PATH = Path(__file__).parent / "data" / "jarvis.db"


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,           -- 'user' | 'assistant'
            content TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS conv_session_idx ON conversations(session_id);
        CREATE INDEX IF NOT EXISTS conv_created_idx ON conversations(created_at);
        CREATE VIRTUAL TABLE IF NOT EXISTS convo_fts USING fts5(
            content, role, content='conversations', content_rowid='id'
        );
    """)
    conn.close()


def log_turn(session_id: str, role: str, content: str) -> int:
    if not content or not content.strip():
        return 0
    conn = _get_db()
    cur = conn.execute(
        "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (session_id, role, content.strip(), time.time()),
    )
    row_id = cur.lastrowid
    conn.execute("INSERT INTO convo_fts (rowid, content, role) VALUES (?, ?, ?)",
                 (row_id, content.strip(), role))
    conn.commit()
    conn.close()
    return row_id


def get_recent(limit: int = 10) -> list[dict]:
    """Return the most recent N turns across all sessions, newest last."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM conversations ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return list(reversed([dict(r) for r in rows]))


def get_session(session_id: str, limit: int = 50) -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM conversations WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _sanitize_fts(q: str) -> str:
    cleaned = q.replace("'", "").replace('"', "").replace("*", "").replace("-", " ")
    words = [w for w in cleaned.split() if len(w) > 2]
    if not words:
        return ""
    return " OR ".join(words[:6])


def search(query: str, limit: int = 10) -> list[dict]:
    fts_q = _sanitize_fts(query)
    if not fts_q:
        return []
    conn = _get_db()
    try:
        rows = conn.execute("""
            SELECT c.* FROM convo_fts f JOIN conversations c ON f.rowid = c.id
            WHERE convo_fts MATCH ? ORDER BY rank LIMIT ?
        """, (fts_q, limit)).fetchall()
    except Exception:
        rows = []
    conn.close()
    return [dict(r) for r in rows]


def format_recent_for_prompt(limit: int = 6) -> str:
    """Format the last N turns as a short summary block to prepend to a new
    session's context, so JARVIS 'remembers' where the last conversation left off."""
    recent = get_recent(limit=limit)
    if not recent:
        return ""
    lines = []
    for r in recent:
        ts = datetime.fromtimestamp(r["created_at"]).strftime("%H:%M")
        who = "You" if r["role"] == "user" else "JARVIS"
        snippet = r["content"][:180].replace("\n", " ")
        lines.append(f"  [{ts}] {who}: {snippet}")
    return "RECENT CONVERSATION:\n" + "\n".join(lines)


def format_search_for_voice(query: str, limit: int = 3) -> str:
    hits = search(query, limit=limit)
    if not hits:
        return f"I don't recall any previous conversation about {query}, sir."
    lines = [f"We discussed {query}. Here's what came up:"]
    for h in hits[:limit]:
        ago = time.time() - h["created_at"]
        when = "just now" if ago < 60 else (
            f"{int(ago/60)} minutes ago" if ago < 3600 else
            f"{int(ago/3600)} hours ago" if ago < 86400 else
            datetime.fromtimestamp(h["created_at"]).strftime("%B %d")
        )
        snippet = h["content"][:120]
        lines.append(f"{when}: {snippet}")
    return " ".join(lines)


init_db()
