"""Small, consent-first SQLite memory store for Ozzy."""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Iterable

VALID_CATEGORIES = {"preference", "project", "fact", "other"}


def default_data_dir() -> Path:
    """Return a per-user data directory, outside the HTTP-served project folder."""
    override = os.getenv("OZZY_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    home = Path.home()
    if os.name == "nt":
        base = Path(os.getenv("APPDATA", home / "AppData" / "Roaming"))
        return base / "Ozzy"
    if os.sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Ozzy"
    base = Path(os.getenv("XDG_DATA_HOME", home / ".local" / "share"))
    return base / "ozzy"


def database_path() -> Path:
    folder = default_data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "ozzy_memory.sqlite3"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(database_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def initialize() -> None:
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL CHECK(category IN ('preference','project','fact','other')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE(category, content COLLATE NOCASE)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_updated_at ON memories(updated_at DESC)"
        )


def validate_memory_content(content: str) -> str | None:
    """Reject empty/oversized content and obvious credentials or secrets."""
    text = " ".join(str(content or "").split())
    if not text:
        return "The memory was empty, so nothing was saved."
    if len(text) > 1500:
        return "Memories must be 1,500 characters or fewer. Ask Ozzy to save a shorter summary."

    low = text.lower()
    credential_patterns = [
        r"\b(api[_ -]?key|password|passwd|passcode|secret[_ -]?key|access[_ -]?token|refresh[_ -]?token)\b\s*(is|=|:|equals)\s*\S+",
        r"-----begin (rsa |ec |openssh )?private key-----",
        r"\bAIza[0-9A-Za-z_\-]{25,}\b",
        r"\bsk-[A-Za-z0-9_-]{20,}\b",
    ]
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in credential_patterns):
        return "Ozzy will not store passwords, API keys, access tokens, or private keys as memories."
    # Catch common credit-card-like digit runs; avoid attempting to store payment secrets.
    digits = re.sub(r"\D", "", text)
    if len(digits) in range(13, 20) and re.search(r"\b(card|credit|debit|cvv|cvc)\b", low):
        return "Ozzy will not store payment-card details as memories."
    return None


def save_memory(content: str, category: str = "fact") -> dict:
    """Insert an already-approved memory. Approval is handled by the UI/backend."""
    clean = " ".join(str(content or "").split())
    category = str(category or "fact").strip().lower()
    validation_error = validate_memory_content(clean)
    if validation_error:
        return {"ok": False, "message": validation_error}
    if category not in VALID_CATEGORIES:
        category = "fact"

    with _connect() as conn:
        row = conn.execute(
            "SELECT id, category, content, created_at, updated_at FROM memories WHERE category = ? AND content = ? COLLATE NOCASE",
            (category, clean),
        ).fetchone()
        if row:
            return {"ok": True, "duplicate": True, "memory": dict(row), "message": "That memory is already saved."}
        cur = conn.execute(
            "INSERT INTO memories(category, content) VALUES (?, ?)",
            (category, clean),
        )
        row = conn.execute(
            "SELECT id, category, content, created_at, updated_at FROM memories WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
        return {"ok": True, "duplicate": False, "memory": dict(row), "message": "Memory saved."}


def list_memories(limit: int = 100) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, category, content, created_at, updated_at FROM memories ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def search_memories(query: str, limit: int = 8) -> list[dict]:
    """Simple local keyword retrieval suitable for a first version."""
    limit = max(1, min(int(limit), 30))
    tokens = list(dict.fromkeys(re.findall(r"[a-zA-Z0-9_'-]{2,}", str(query or "").lower())))[:8]
    if not tokens:
        return list_memories(limit)

    clauses = []
    params: list[str | int] = []
    for token in tokens:
        escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("(lower(content) LIKE ? ESCAPE '\\' OR lower(category) LIKE ? ESCAPE '\\')")
        params.extend([f"%{escaped}%", f"%{escaped}%"])
    params.append(limit)
    sql = (
        "SELECT id, category, content, created_at, updated_at FROM memories WHERE "
        + " OR ".join(clauses)
        + " ORDER BY updated_at DESC, id DESC LIMIT ?"
    )
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def delete_memories(ids: Iterable[int]) -> int:
    clean_ids: list[int] = []
    for raw_id in ids:
        try:
            memory_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if memory_id > 0 and memory_id not in clean_ids:
            clean_ids.append(memory_id)
    if not clean_ids:
        return 0
    placeholders = ",".join("?" for _ in clean_ids)
    with _connect() as conn:
        cur = conn.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", clean_ids)
        return cur.rowcount


def get_memories_by_ids(ids: Iterable[int]) -> list[dict]:
    clean_ids: list[int] = []
    for raw_id in ids:
        try:
            memory_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if memory_id > 0 and memory_id not in clean_ids:
            clean_ids.append(memory_id)
    if not clean_ids:
        return []
    placeholders = ",".join("?" for _ in clean_ids)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id, category, content, created_at, updated_at FROM memories WHERE id IN ({placeholders}) ORDER BY updated_at DESC",
            clean_ids,
        ).fetchall()
    return [dict(row) for row in rows]
