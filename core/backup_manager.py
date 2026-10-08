"""
core/backup_manager.py — Backup and undo history for Phase 9 safe edits.

Stores pre-edit backups under:
    ~/.myai/backups/<project_id>/<session_id>/

Also maintains an edit audit log in the AIZEN SQLite DB
(edit_sessions and edit_files tables).
"""

import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple

import config


# Edit session statuses
STATUS_PENDING   = "PENDING"
STATUS_APPLIED   = "APPLIED"
STATUS_DISCARDED = "DISCARDED"
STATUS_UNDONE    = "UNDONE"
STATUS_FAILED    = "FAILED"

# ------------------------------------------------------------------
# SCHEMA (added to existing aizen.db)
# ------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS edit_sessions (
    session_id      TEXT PRIMARY KEY,
    project_root    TEXT NOT NULL,
    instruction     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    created_at      TEXT NOT NULL,
    applied_at      TEXT,
    undone_at       TEXT,
    backup_dir      TEXT,
    files_changed   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS edit_files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    relative_path   TEXT NOT NULL,
    original_hash   TEXT,
    new_hash        TEXT,
    lines_added     INTEGER NOT NULL DEFAULT 0,
    lines_removed   INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(session_id) REFERENCES edit_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_es_project ON edit_sessions (project_root);
CREATE INDEX IF NOT EXISTS idx_es_status  ON edit_sessions (status);
CREATE INDEX IF NOT EXISTS idx_ef_session ON edit_files (session_id);
"""


@contextmanager
def _db():
    """Context manager yielding an sqlite3 connection to aizen.db."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(config.ANALYTICS_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_edit_db():
    """Create edit_sessions and edit_files tables if they do not exist."""
    try:
        with _db() as conn:
            conn.executescript(_SCHEMA)
    except Exception:
        pass


def sha256_file(file_path: str) -> Optional[str]:
    """Compute SHA-256 hex digest for a file; returns None on error."""
    try:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _project_id(project_root: str) -> str:
    """Derive a safe directory name from a project root path."""
    return hashlib.sha256(project_root.encode()).hexdigest()[:16]


def create_backup_session(
    session_id: str,
    project_root: str,
    instruction: str,
    files: List[Tuple[str, str]],   # [(relative_path, absolute_path), ...]
) -> Tuple[bool, str, Optional[str]]:
    """
    Create a backup of all files that will be modified.

    Stores original files under:
        ~/.myai/backups/<project_id>/<session_id>/

    Returns:
        (success: bool, message: str, backup_dir: str | None)
    """
    try:
        project_id = _project_id(project_root)
        backup_dir = os.path.join(config.BACKUPS_DIR, project_id, session_id)
        os.makedirs(backup_dir, exist_ok=True)

        backed_up = []
        for rel_path, abs_path in files:
            if not os.path.isfile(abs_path):
                continue
            safe_name = rel_path.replace("/", "__").replace("\\", "__")
            dest = os.path.join(backup_dir, safe_name)
            shutil.copy2(abs_path, dest)
            backed_up.append({
                "relative_path": rel_path,
                "absolute_path": abs_path,
                "backup_file":   safe_name,
                "original_hash": sha256_file(abs_path),
            })

        manifest = {
            "session_id":   session_id,
            "project_root": project_root,
            "instruction":  instruction,
            "created_at":   time.strftime("%Y-%m-%dT%H:%M:%S"),
            "files":        backed_up,
        }
        with open(os.path.join(backup_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)

        return True, f"Backup created at {backup_dir}", backup_dir

    except Exception as e:
        return False, f"Backup failed: {e}", None


def record_session(
    session_id: str,
    project_root: str,
    instruction: str,
    file_entries: List[dict],
    status: str = STATUS_PENDING,
    backup_dir: Optional[str] = None,
) -> bool:
    """Persist a new edit session and its file entries into SQLite."""
    try:
        with _db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO edit_sessions
                   (session_id, project_root, instruction, status, created_at, backup_dir, files_changed)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    project_root,
                    instruction,
                    status,
                    time.strftime("%Y-%m-%dT%H:%M:%S"),
                    backup_dir,
                    len(file_entries),
                ),
            )
            for fe in file_entries:
                conn.execute(
                    """INSERT INTO edit_files
                       (session_id, relative_path, original_hash, new_hash, lines_added, lines_removed)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        fe.get("file", ""),
                        fe.get("original_hash"),
                        None,
                        0,
                        0,
                    ),
                )
        return True
    except Exception:
        return False


def update_session_status(
    session_id: str,
    status: str,
    applied_at: Optional[str] = None,
    undone_at: Optional[str] = None,
    file_updates: Optional[List[dict]] = None,  # [{relative_path, new_hash, lines_added, lines_removed}]
) -> bool:
    """Update an edit session status and optionally refresh per-file metadata."""
    try:
        with _db() as conn:
            conn.execute(
                "UPDATE edit_sessions SET status=?, applied_at=?, undone_at=? WHERE session_id=?",
                (status, applied_at, undone_at, session_id),
            )
            if file_updates:
                for fu in file_updates:
                    conn.execute(
                        """UPDATE edit_files
                           SET new_hash=?, lines_added=?, lines_removed=?
                           WHERE session_id=? AND relative_path=?""",
                        (
                            fu.get("new_hash"),
                            fu.get("lines_added", 0),
                            fu.get("lines_removed", 0),
                            session_id,
                            fu.get("relative_path", ""),
                        ),
                    )
        return True
    except Exception:
        return False


def get_session_history(project_root: str, limit: int = 20) -> List[dict]:
    """Return edit session history for a project, newest first."""
    try:
        with _db() as conn:
            rows = conn.execute(
                """SELECT session_id, instruction, status, created_at, applied_at, files_changed
                   FROM edit_sessions
                   WHERE project_root=?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (project_root, limit),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_last_applied_session(project_root: str) -> Optional[dict]:
    """Return the most recently APPLIED (not yet undone) session for a project."""
    try:
        with _db() as conn:
            row = conn.execute(
                """SELECT session_id, instruction, applied_at, backup_dir
                   FROM edit_sessions
                   WHERE project_root=? AND status=?
                   ORDER BY applied_at DESC
                   LIMIT 1""",
                (project_root, STATUS_APPLIED),
            ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def get_session_files(session_id: str) -> List[dict]:
    """Return file entries for a given session."""
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT relative_path, original_hash, backup_file FROM edit_files WHERE session_id=?",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def restore_from_backup(session_id: str, project_root: str) -> Tuple[bool, str]:
    """
    Restore original file contents from a backup session.
    Returns (success, message).
    """
    try:
        project_id = _project_id(project_root)
        backup_dir = os.path.join(config.BACKUPS_DIR, project_id, session_id)

        manifest_path = os.path.join(backup_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            return False, f"Backup manifest not found at {manifest_path}"

        with open(manifest_path) as f:
            manifest = json.load(f)

        restored = []
        failed = []

        for entry in manifest.get("files", []):
            rel_path    = entry["relative_path"]
            abs_path    = entry["absolute_path"]
            backup_file = entry["backup_file"]
            src = os.path.join(backup_dir, backup_file)

            if not os.path.isfile(src):
                failed.append(f"{rel_path} (backup missing)")
                continue

            # Atomic write
            import tempfile
            dir_name = os.path.dirname(abs_path)
            os.makedirs(dir_name, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=dir_name)
            try:
                with os.fdopen(fd, "wb") as out:
                    with open(src, "rb") as inp:
                        shutil.copyfileobj(inp, out)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(tmp_path, abs_path)
                restored.append(rel_path)
            except Exception as e:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                failed.append(f"{rel_path} ({e})")

        if failed:
            return False, f"Restored {len(restored)} file(s). Failed: {', '.join(failed)}"
        return True, f"Restored {len(restored)} file(s) from backup."

    except Exception as e:
        return False, f"Restore failed: {e}"
