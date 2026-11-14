"""Stage 6: consent-first persistent library for reusable Ozzy workflows.

Templates are stored locally in Ozzy's existing SQLite database. A template is
validated again when loaded and executed through Stage 5's existing workflow
engine, so this module adds persistence, not a new automation bypass.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import memory_service
import workflow_engine

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 240
MAX_TEMPLATES = 50
MAX_RUNS = 30
ALLOWED_RUN_STATUSES = {
    "completed", "completed_unverified", "failed", "verification_failed",
    "paused_unverified", "cancelled", "timed_out",
}

_SECRET_TEXT = re.compile(
    r"\b(?:password|passwd|passcode|api[_ -]?key|apikey|client[_ -]?secret|clientsecret|access[_ -]?token|"
    r"accesstoken|refresh[_ -]?token|refreshtoken|bearer)\b[\"']?\s*[:=]\s*[\"']?\S+|"
    r"\bAIza[0-9A-Za-z_-]{25,}\b|\bsk-[A-Za-z0-9_-]{20,}\b|"
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b|"
    r"\bxox[baprs]-[A-Za-z0-9-]{15,}\b|"
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    re.IGNORECASE,
)
_SENSITIVE_QUERY = re.compile(
    r"[?&](?:api[_-]?key|apikey|client[_-]?secret|clientsecret|access[_-]?token|accesstoken|"
    r"refresh[_-]?token|refreshtoken|token|key|secret|password|passwd|auth|verification[_-]?code)=",
    re.I,
)


class WorkflowLibraryError(ValueError):
    """A saved workflow template is invalid or cannot be selected safely."""


def _connect() -> sqlite3.Connection:
    path = memory_service.database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _clean_name(value: Any) -> str:
    if not isinstance(value, str):
        raise WorkflowLibraryError("Workflow name must be text.")
    name = " ".join(value.split())
    if not name or len(name) > MAX_NAME_LENGTH:
        raise WorkflowLibraryError(f"Workflow names must contain 1 to {MAX_NAME_LENGTH} characters.")
    if any(ord(ch) < 32 for ch in name):
        raise WorkflowLibraryError("Workflow name contains unsupported control characters.")
    if _SECRET_TEXT.search(name):
        raise WorkflowLibraryError("Workflow names must not contain credentials or secrets.")
    return name


def _clean_description(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise WorkflowLibraryError("Workflow description must be text.")
    description = " ".join(value.split())
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise WorkflowLibraryError(f"Workflow descriptions must be {MAX_DESCRIPTION_LENGTH} characters or fewer.")
    if _SECRET_TEXT.search(description):
        raise WorkflowLibraryError("Workflow descriptions must not contain credentials or secrets.")
    return description


def prepare_template(name: Any, description: Any, steps: Any) -> dict[str, Any]:
    """Normalize and validate a proposed template before asking for approval."""
    clean_name = _clean_name(name)
    clean_description = _clean_description(description)
    clean_steps = workflow_engine.validate_steps(steps)
    serialized = json.dumps(clean_steps, ensure_ascii=True, separators=(",", ":"))
    if _SECRET_TEXT.search(serialized) or _SENSITIVE_QUERY.search(serialized):
        raise WorkflowLibraryError("This workflow appears to contain a credential, secret, or sensitive URL parameter and cannot be saved.")
    return {"name": clean_name, "description": clean_description, "steps": clean_steps}


def initialize() -> None:
    """Create Stage 6 tables in Ozzy's existing local SQLite database."""
    conn = _connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                steps_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                last_used_at TEXT,
                use_count INTEGER NOT NULL DEFAULT 0 CHECK(use_count >= 0)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_template_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL REFERENCES workflow_templates(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                completed_steps INTEGER NOT NULL DEFAULT 0,
                total_steps INTEGER NOT NULL DEFAULT 0,
                duration_seconds REAL NOT NULL DEFAULT 0,
                summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_templates_updated ON workflow_templates(updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_runs_template ON workflow_template_runs(template_id, created_at DESC)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _template_from_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        steps = json.loads(row["steps_json"])
        steps = workflow_engine.validate_steps(steps)
    except Exception as exc:
        raise WorkflowLibraryError("This saved workflow is invalid or no longer supported. It was not executed.") from exc
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "description": str(row["description"]),
        "steps": steps,
        "step_count": len(steps),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_used_at": row["last_used_at"],
        "use_count": int(row["use_count"]),
    }


def save_template(name: Any, description: Any, steps: Any) -> dict[str, Any]:
    """Persist a template after the server has received explicit UI approval."""
    template = prepare_template(name, description, steps)
    serialized = json.dumps(template["steps"], ensure_ascii=True, separators=(",", ":"))
    conn = _connect()
    try:
        current_count = int(conn.execute("SELECT COUNT(*) FROM workflow_templates").fetchone()[0])
        if current_count >= MAX_TEMPLATES:
            raise WorkflowLibraryError(f"The local workflow library is full ({MAX_TEMPLATES} recipes). Delete an old recipe before saving another.")
        try:
            cursor = conn.execute(
                "INSERT INTO workflow_templates(name, description, steps_json) VALUES (?, ?, ?)",
                (template["name"], template["description"], serialized),
            )
        except sqlite3.IntegrityError as exc:
            raise WorkflowLibraryError(f"A saved workflow named '{template['name']}' already exists. Choose another name.") from exc
        row = conn.execute("SELECT * FROM workflow_templates WHERE id = ?", (cursor.lastrowid,)).fetchone()
        conn.commit()
        return {"ok": True, "template": _template_from_row(row), "message": f"Saved workflow '{template['name']}'."}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_templates(limit: int = MAX_TEMPLATES) -> list[dict[str, Any]]:
    try:
        size = int(limit)
    except (TypeError, ValueError):
        size = 30
    size = max(1, min(size, MAX_TEMPLATES))
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM workflow_templates ORDER BY updated_at DESC, id DESC LIMIT ?", (size,)).fetchall()
        return [_template_from_row(row) for row in rows]
    finally:
        conn.close()


def search_templates(query: Any, limit: int = 12) -> list[dict[str, Any]]:
    if not isinstance(query, str):
        raise WorkflowLibraryError("Search query must be text.")
    clean_query = " ".join(query.split())
    if not clean_query or len(clean_query) > 100:
        raise WorkflowLibraryError("Provide a search phrase from 1 to 100 characters.")
    size = max(1, min(int(limit), 20))
    escaped = clean_query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM workflow_templates WHERE lower(name) LIKE ? ESCAPE '\\' OR lower(description) LIKE ? ESCAPE '\\' ORDER BY updated_at DESC, id DESC LIMIT ?",
            (f"%{escaped}%", f"%{escaped}%", size),
        ).fetchall()
        return [_template_from_row(row) for row in rows]
    finally:
        conn.close()


def get_template(name: Any) -> dict[str, Any] | None:
    clean_name = _clean_name(name)
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM workflow_templates WHERE name = ? COLLATE NOCASE", (clean_name,)).fetchone()
        return _template_from_row(row) if row else None
    finally:
        conn.close()


def get_template_by_id(template_id: Any) -> dict[str, Any] | None:
    if isinstance(template_id, bool):
        raise WorkflowLibraryError("Workflow ID must be a positive integer.")
    try:
        clean_id = int(template_id)
    except (TypeError, ValueError):
        raise WorkflowLibraryError("Workflow ID must be a positive integer.") from None
    if clean_id <= 0:
        raise WorkflowLibraryError("Workflow ID must be a positive integer.")
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM workflow_templates WHERE id = ?", (clean_id,)).fetchone()
        return _template_from_row(row) if row else None
    finally:
        conn.close()


def mark_template_used(template_id: int) -> None:
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE workflow_templates SET use_count = use_count + 1, last_used_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (int(template_id),),
        )
        if cursor.rowcount != 1:
            raise WorkflowLibraryError("The saved workflow no longer exists.")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_run(template_id: int, result: dict[str, Any]) -> dict[str, Any]:
    status = str(result.get("status") or "failed")
    if status not in ALLOWED_RUN_STATUSES:
        status = "failed"
    completed = max(0, min(int(result.get("completed_steps", 0) or 0), 8))
    total = max(0, min(int(result.get("total_steps", 0) or 0), 8))
    duration = max(0.0, min(float(result.get("duration_seconds", 0) or 0), 120.0))
    # Keep history as metadata only; never persist observed page text, titles,
    # window names, URLs, or exception details from a workflow result.
    summary = f"{status}: {completed}/{total} step(s) verified."
    conn = _connect()
    try:
        cursor = conn.execute(
            "INSERT INTO workflow_template_runs(template_id, status, completed_steps, total_steps, duration_seconds, summary) VALUES (?, ?, ?, ?, ?, ?)",
            (int(template_id), status, completed, total, duration, summary),
        )
        # Retain only the latest bounded history for this recipe.
        conn.execute(
            "DELETE FROM workflow_template_runs WHERE template_id = ? AND id NOT IN ("
            "SELECT id FROM workflow_template_runs WHERE template_id = ? ORDER BY created_at DESC, id DESC LIMIT ?)",
            (int(template_id), int(template_id), MAX_RUNS),
        )
        row = conn.execute("SELECT * FROM workflow_template_runs WHERE id = ?", (cursor.lastrowid,)).fetchone()
        conn.commit()
        return dict(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_runs(name: Any, limit: int = 10) -> list[dict[str, Any]]:
    template = get_template(name)
    if template is None:
        raise WorkflowLibraryError("No saved workflow with that name was found.")
    size = max(1, min(int(limit), MAX_RUNS))
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, status, completed_steps, total_steps, duration_seconds, summary, created_at FROM workflow_template_runs WHERE template_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (template["id"], size),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_template(template_id: Any) -> dict[str, Any]:
    if isinstance(template_id, bool):
        raise WorkflowLibraryError("Workflow ID must be a positive integer.")
    try:
        clean_id = int(template_id)
    except (TypeError, ValueError):
        raise WorkflowLibraryError("Workflow ID must be a positive integer.") from None
    if clean_id <= 0:
        raise WorkflowLibraryError("Workflow ID must be a positive integer.")
    conn = _connect()
    try:
        row = conn.execute("SELECT name FROM workflow_templates WHERE id = ?", (clean_id,)).fetchone()
        if row is None:
            raise WorkflowLibraryError("The saved workflow no longer exists.")
        conn.execute("DELETE FROM workflow_templates WHERE id = ?", (clean_id,))
        conn.commit()
        return {"ok": True, "deleted_id": clean_id, "deleted_name": str(row["name"]), "message": f"Deleted saved workflow '{row['name']}' and its run history."}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
