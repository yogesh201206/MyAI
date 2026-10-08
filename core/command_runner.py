"""
core/command_runner.py — Safe subprocess execution for Phase 10.

Responsibilities:
    - Execute foreground commands with timeout and output capture
    - Track execution metadata (cwd, duration, exit code)
    - Persist result to command_history in aizen.db
    - Signal-safe Ctrl+C handling (kills child, keeps AIZEN alive)
    - Output size capping (1 MB / MAX_LINES)

Never called directly — always goes through agent_manager or command handlers.
"""

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

import config
from core.command_safety import SafetyResult, sanitize_for_log

# ------------------------------------------------------------------
# CONSTANTS
# ------------------------------------------------------------------

DEFAULT_TIMEOUT_SECONDS = 120
MAX_OUTPUT_BYTES        = 1024 * 1024   # 1 MB
MAX_OUTPUT_LINES        = 2000
PREVIEW_LINES           = 50            # lines stored in DB preview


# ------------------------------------------------------------------
# RESULT
# ------------------------------------------------------------------

@dataclass
class CommandResult:
    command: str
    cwd: str
    safety_level: str
    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False
    cancelled: bool = False
    error_message: str = ""
    truncated: bool = False
    timestamp: str = ""

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    @property
    def stdout_preview(self) -> str:
        lines = self.stdout.splitlines()
        return "\n".join(lines[:PREVIEW_LINES])

    @property
    def stderr_preview(self) -> str:
        lines = self.stderr.splitlines()
        return "\n".join(lines[:PREVIEW_LINES])


# ------------------------------------------------------------------
# SCHEMA INIT
# ------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS command_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    project_root    TEXT,
    cwd             TEXT NOT NULL,
    command         TEXT NOT NULL,
    safety_level    TEXT,
    approved        INTEGER NOT NULL DEFAULT 1,
    exit_code       INTEGER,
    duration_ms     REAL,
    status          TEXT,
    stdout_preview  TEXT,
    stderr_preview  TEXT
);

CREATE INDEX IF NOT EXISTS idx_ch_timestamp    ON command_history (timestamp);
CREATE INDEX IF NOT EXISTS idx_ch_project_root ON command_history (project_root);
"""


def init_command_db():
    """Create command_history table in aizen.db if not present."""
    import sqlite3
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        conn = sqlite3.connect(config.ANALYTICS_DB, timeout=10)
        conn.executescript(_SCHEMA)
        conn.commit()
        conn.close()
    except Exception:
        pass


def _persist(result: CommandResult, project_root: Optional[str]):
    """Persist command result to command_history table."""
    import sqlite3
    try:
        status = "CANCELLED" if result.cancelled else (
                 "TIMEOUT"   if result.timed_out  else (
                 "OK"        if result.exit_code == 0 else "FAILED"))
        safe_cmd = sanitize_for_log(result.command)
        conn = sqlite3.connect(config.ANALYTICS_DB, timeout=10)
        conn.execute(
            """INSERT INTO command_history
               (timestamp, project_root, cwd, command, safety_level,
                approved, exit_code, duration_ms, status,
                stdout_preview, stderr_preview)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
            (
                result.timestamp,
                project_root,
                result.cwd,
                safe_cmd,
                result.safety_level,
                result.exit_code,
                result.duration_ms,
                status,
                result.stdout_preview,
                result.stderr_preview,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ------------------------------------------------------------------
# FOREGROUND EXECUTION
# ------------------------------------------------------------------

def run_foreground(
    command: str,
    cwd: str,
    safety: SafetyResult,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    use_shell: bool = False,
) -> CommandResult:
    """
    Execute a command in the foreground.

    - Captures stdout + stderr separately.
    - Respects timeout — kills child on expiry.
    - Ctrl+C kills the child but keeps AIZEN alive.
    - Caps output to MAX_OUTPUT_BYTES / MAX_OUTPUT_LINES.
    - Persists result to command_history.

    Returns a CommandResult.
    """
    from core.command_safety import parse_command

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    start = time.perf_counter()
    truncated = False
    cancelled = False
    timed_out = False
    exit_code  = None
    stdout     = ""
    stderr     = ""
    error_msg  = ""

    try:
        if use_shell:
            args = command
        else:
            args = parse_command(command)
            if not args:
                return CommandResult(
                    command=command, cwd=cwd,
                    safety_level=safety.level,
                    exit_code=1, stdout="", stderr="",
                    duration_ms=0, error_message="Empty command",
                    timestamp=timestamp,
                )

        env = _clean_env()

        proc = subprocess.Popen(
            args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            shell=use_shell,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        try:
            raw_out, raw_err = proc.communicate(timeout=timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            try:
                raw_out, raw_err = proc.communicate(timeout=5)
            except Exception:
                raw_out, raw_err = "", ""
            exit_code = proc.returncode
        except KeyboardInterrupt:
            cancelled = True
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
            raw_out, raw_err = "", ""
            exit_code = proc.returncode

        # Cap output
        stdout, stdout_trunc = _cap(raw_out)
        stderr, stderr_trunc = _cap(raw_err)
        truncated = stdout_trunc or stderr_trunc

    except FileNotFoundError:
        error_msg = f"Command not found: {command.split()[0] if command else '?'}"
        exit_code = 127
    except PermissionError as e:
        error_msg = f"Permission denied: {e}"
        exit_code = 126
    except Exception as e:
        error_msg = str(e)
        exit_code = 1

    duration_ms = (time.perf_counter() - start) * 1000

    result = CommandResult(
        command=command,
        cwd=cwd,
        safety_level=safety.level,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        timed_out=timed_out,
        cancelled=cancelled,
        error_message=error_msg,
        truncated=truncated,
        timestamp=timestamp,
    )

    _persist(result, config.active_project_path)
    # Keep reference for /lastcmd
    config.last_command_result = result

    return result


def _cap(text: str) -> tuple[str, bool]:
    """Truncate text to MAX_OUTPUT_BYTES/MAX_OUTPUT_LINES. Returns (text, was_truncated)."""
    if not text:
        return "", False

    lines = text.splitlines(keepends=True)
    truncated = False

    if len(lines) > MAX_OUTPUT_LINES:
        lines = lines[:MAX_OUTPUT_LINES]
        truncated = True

    text = "".join(lines)
    if len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        text = text.encode("utf-8")[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        truncated = True

    return text, truncated


def _clean_env() -> dict:
    """Return a copy of the current environment without modification."""
    return dict(os.environ)


# ------------------------------------------------------------------
# LAST COMMAND HELPER
# ------------------------------------------------------------------

def get_last_command() -> Optional[CommandResult]:
    """Return the most recent CommandResult stored in config."""
    return getattr(config, "last_command_result", None)


def get_command_history(limit: int = 20) -> list:
    """Retrieve recent command_history rows from SQLite."""
    import sqlite3
    try:
        conn = sqlite3.connect(config.ANALYTICS_DB, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT id, timestamp, cwd, command, safety_level,
                      exit_code, duration_ms, status
               FROM command_history
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []
