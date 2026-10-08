"""
core/analytics.py — Persistent usage analytics via SQLite.

Design principles:
  - Uses Python's built-in sqlite3 (no third-party deps).
  - DB is at ~/.myai/aizen.db (config.ANALYTICS_DB).
  - Schema initialisation is idempotent (safe to run on every startup).
  - All writes use parameterised SQL and explicit transactions.
  - Analytics failures NEVER crash the CLI — every public function is
    wrapped in a try/except and returns a safe fallback on error.

Cancellation policy:
  - Ctrl+C during generation is NOT logged as a failure; it is simply
    omitted from analytics to avoid polluting provider health or
    success-rate metrics.

Fallback policy:
  - If streaming fails before meaningful output and the non-streaming
    fallback succeeds, ONE success row is recorded with fallback_used=1.
  - If the non-streaming fallback also fails, ONE failure row is recorded.
  - A streaming request that delivers partial output then fails is logged
    as a failure row (partial output already rendered to screen).

Time periods (all local calendar time):
  today  — current local calendar day
  week   — last 7 days including today
  month  — last 30 days
  all    — all recorded rows
"""

import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

import config

# ------------------------------------------------------------------
# SCHEMA
# ------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS request_usage (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT    NOT NULL,
    chat_id             TEXT,
    selected_model      TEXT,
    actual_model        TEXT,
    provider            TEXT,
    streaming           INTEGER NOT NULL DEFAULT 0,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    total_tokens        INTEGER,
    response_time_ms    REAL,
    success             INTEGER NOT NULL,
    error_code          TEXT,
    error_message       TEXT,
    fallback_used       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ru_timestamp ON request_usage (timestamp);
CREATE INDEX IF NOT EXISTS idx_ru_provider  ON request_usage (provider);
CREATE INDEX IF NOT EXISTS idx_ru_model     ON request_usage (actual_model);
CREATE INDEX IF NOT EXISTS idx_ru_chat      ON request_usage (chat_id);
CREATE INDEX IF NOT EXISTS idx_ru_success   ON request_usage (success);
"""


# ------------------------------------------------------------------
# CONNECTION MANAGEMENT
# ------------------------------------------------------------------

@contextmanager
def _db():
    """
    Context manager yielding a sqlite3 connection.
    Creates the data directory and initialises the schema if needed.
    Raises on error (callers must wrap in try/except).
    """
    db_path = config.ANALYTICS_DB
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def init_db():
    """
    Create the database and initialise the schema.
    Safe to call multiple times (uses CREATE IF NOT EXISTS).
    Also performs safe column migrations for newer phases.
    """
    try:
        with _db() as con:
            con.executescript(_SCHEMA)
            # Safe migrations for Phase 11 router fields
            cursor = con.cursor()
            cursor.execute("PRAGMA table_info(request_usage)")
            cols = {row["name"] for row in cursor.fetchall()}
            if "router_used" not in cols:
                con.execute("ALTER TABLE request_usage ADD COLUMN router_used INTEGER DEFAULT 0")
            if "router_mode" not in cols:
                con.execute("ALTER TABLE request_usage ADD COLUMN router_mode TEXT")
            if "classified_task" not in cols:
                con.execute("ALTER TABLE request_usage ADD COLUMN classified_task TEXT")
            if "router_selected_model" not in cols:
                con.execute("ALTER TABLE request_usage ADD COLUMN router_selected_model TEXT")
            con.commit()
    except Exception:
        pass   # Never crash on analytics init failure


def _now_iso() -> str:
    """Current local time as ISO-8601 string (local, not UTC)."""
    return datetime.now().isoformat()


# ------------------------------------------------------------------
# WRITE HELPERS
# ------------------------------------------------------------------

def _resolve_provider(actual_model: str | None, selected_model: str | None) -> str | None:
    """Resolve provider from model id using Phase 4 helper."""
    try:
        from core.provider_health import get_provider_for_model
        model = actual_model or selected_model
        return get_provider_for_model(model) if model else None
    except Exception:
        return None


def log_success(
    chat_id: str | None,
    selected_model: str | None,
    actual_model: str | None,
    streaming: bool,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    response_time_ms: float | None,
    fallback_used: bool = False,
    router_used: bool = False,
    router_mode: str | None = None,
    classified_task: str | None = None,
    router_selected_model: str | None = None,
):
    """
    Log a successful request row.
    Never raises — analytics failure is silently swallowed.
    """
    try:
        provider = _resolve_provider(actual_model, selected_model)
        with _db() as con:
            con.execute(
                """
                INSERT INTO request_usage
                    (timestamp, chat_id, selected_model, actual_model, provider,
                     streaming, prompt_tokens, completion_tokens, total_tokens,
                     response_time_ms, success, fallback_used,
                     router_used, router_mode, classified_task, router_selected_model)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    _now_iso(), chat_id, selected_model, actual_model, provider,
                    1 if streaming else 0,
                    prompt_tokens, completion_tokens, total_tokens,
                    response_time_ms,
                    1 if fallback_used else 0,
                    1 if router_used else 0,
                    router_mode,
                    classified_task,
                    router_selected_model,
                )
            )
            con.commit()
    except Exception:
        pass


def log_failure(
    chat_id: str | None,
    selected_model: str | None,
    actual_model: str | None,
    streaming: bool,
    response_time_ms: float | None,
    error_code: str | None,
    error_message: str | None,
    router_used: bool = False,
    router_mode: str | None = None,
    classified_task: str | None = None,
    router_selected_model: str | None = None,
):
    """
    Log a failed request row.
    Never raises.
    """
    try:
        provider = _resolve_provider(actual_model, selected_model)
        with _db() as con:
            con.execute(
                """
                INSERT INTO request_usage
                    (timestamp, chat_id, selected_model, actual_model, provider,
                     streaming, response_time_ms, success, error_code, error_message,
                     router_used, router_mode, classified_task, router_selected_model)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now_iso(), chat_id, selected_model, actual_model, provider,
                    1 if streaming else 0,
                    response_time_ms,
                    str(error_code) if error_code is not None else None,
                    str(error_message)[:500] if error_message else None,
                    1 if router_used else 0,
                    router_mode,
                    classified_task,
                    router_selected_model,
                )
            )
            con.commit()
    except Exception:
        pass


# ------------------------------------------------------------------
# TIME PERIOD HELPERS
# ------------------------------------------------------------------

def _period_start(period: str) -> str | None:
    """
    Return ISO-8601 string for the start of the requested period.
    None means 'all time' (no lower bound).

    Periods (local calendar time):
      today  — start of current local day (midnight)
      week   — 7 days ago (same time)
      month  — 30 days ago (same time)
      all    — None
    """
    now = datetime.now()
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        return None
    return start.isoformat()


# ------------------------------------------------------------------
# AGGREGATE QUERIES
# ------------------------------------------------------------------

def get_period_stats(period: str = "all") -> dict:
    """
    Return aggregate stats for the given period.

    Keys:
      total_requests, successful, failed, success_rate,
      input_tokens, output_tokens, total_tokens,
      avg_response_ms, most_used_model, most_used_provider,
      tokens_include_partial  (True if some rows had NULL tokens)
    """
    empty = {
        "total_requests": 0,
        "successful": 0,
        "failed": 0,
        "success_rate": 0.0,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "avg_response_ms": None,
        "most_used_model": None,
        "most_used_provider": None,
        "tokens_include_partial": False,
    }
    try:
        start = _period_start(period)
        with _db() as con:
            where = "WHERE timestamp >= ?" if start else ""
            params: tuple = (start,) if start else ()

            row = con.execute(
                f"""
                SELECT
                    COUNT(*)                         AS total,
                    SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS succ,
                    SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) AS fail,
                    SUM(prompt_tokens)               AS inp,
                    SUM(completion_tokens)           AS out,
                    SUM(total_tokens)                AS tok,
                    AVG(response_time_ms)            AS avg_ms,
                    SUM(CASE WHEN prompt_tokens IS NULL THEN 1 ELSE 0 END) AS null_tok
                FROM request_usage {where}
                """,
                params,
            ).fetchone()

            if not row or row["total"] == 0:
                return empty

            total = row["total"]
            succ  = row["succ"] or 0
            fail  = row["fail"] or 0

            # Most used model
            mrow = con.execute(
                f"""
                SELECT COALESCE(actual_model, selected_model) AS mdl, COUNT(*) AS cnt
                FROM request_usage {where}
                GROUP BY mdl ORDER BY cnt DESC LIMIT 1
                """,
                params,
            ).fetchone()

            # Most used provider
            prow = con.execute(
                f"""
                SELECT COALESCE(provider, 'Unknown') AS prov, COUNT(*) AS cnt
                FROM request_usage {where}
                GROUP BY prov ORDER BY cnt DESC LIMIT 1
                """,
                params,
            ).fetchone()

            return {
                "total_requests":     total,
                "successful":         succ,
                "failed":             fail,
                "success_rate":       (succ / total * 100) if total > 0 else 0.0,
                "input_tokens":       row["inp"],
                "output_tokens":      row["out"],
                "total_tokens":       row["tok"],
                "avg_response_ms":    row["avg_ms"],
                "most_used_model":    mrow["mdl"] if mrow else None,
                "most_used_provider": prow["prov"] if prow else None,
                "tokens_include_partial": (row["null_tok"] or 0) > 0,
            }
    except Exception:
        return empty


def get_model_stats(period: str = "all") -> list[dict]:
    """
    Return per-model aggregate stats sorted by request count desc.

    Each dict has: model, requests, successful, failed,
                   input_tokens, output_tokens, total_tokens, avg_latency_ms
    """
    try:
        start = _period_start(period)
        where = "WHERE timestamp >= ?" if start else ""
        params: tuple = (start,) if start else ()
        with _db() as con:
            rows = con.execute(
                f"""
                SELECT
                    COALESCE(actual_model, selected_model, 'Unknown') AS model,
                    COUNT(*)                         AS requests,
                    SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS successful,
                    SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) AS failed,
                    SUM(prompt_tokens)               AS input_tokens,
                    SUM(completion_tokens)           AS output_tokens,
                    SUM(total_tokens)                AS total_tokens,
                    AVG(response_time_ms)            AS avg_latency_ms
                FROM request_usage {where}
                GROUP BY model
                ORDER BY requests DESC
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_provider_stats(period: str = "all") -> list[dict]:
    """
    Return per-provider aggregate stats sorted by request count desc.

    Each dict has: provider, requests, successful, failed,
                   success_rate, total_tokens, avg_latency_ms
    """
    try:
        start = _period_start(period)
        where = "WHERE timestamp >= ?" if start else ""
        params: tuple = (start,) if start else ()
        with _db() as con:
            rows = con.execute(
                f"""
                SELECT
                    COALESCE(provider, 'Unknown') AS provider,
                    COUNT(*)                         AS requests,
                    SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS successful,
                    SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) AS failed,
                    SUM(total_tokens)                AS total_tokens,
                    AVG(response_time_ms)            AS avg_latency_ms
                FROM request_usage {where}
                GROUP BY provider
                ORDER BY requests DESC
                """,
                params,
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["success_rate"] = (
                (d["successful"] / d["requests"] * 100)
                if d["requests"] > 0 else 0.0
            )
            result.append(d)
        return result
    except Exception:
        return []


def get_chat_stats(chat_id: str) -> dict:
    """
    Return aggregate stats for a specific chat session.

    Keys: requests, input_tokens, output_tokens, total_tokens,
          avg_response_ms, models_used, providers_used
    """
    empty = {
        "requests": 0,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "avg_response_ms": None,
        "models_used": [],
        "providers_used": [],
    }
    try:
        with _db() as con:
            row = con.execute(
                """
                SELECT
                    COUNT(*)              AS requests,
                    SUM(prompt_tokens)    AS inp,
                    SUM(completion_tokens)AS out,
                    SUM(total_tokens)     AS tok,
                    AVG(response_time_ms) AS avg_ms
                FROM request_usage
                WHERE chat_id = ?
                """,
                (chat_id,),
            ).fetchone()

            models = [
                r[0] for r in con.execute(
                    """
                    SELECT DISTINCT COALESCE(actual_model, selected_model)
                    FROM request_usage
                    WHERE chat_id = ? AND COALESCE(actual_model, selected_model) IS NOT NULL
                    """,
                    (chat_id,),
                ).fetchall()
            ]
            providers = [
                r[0] for r in con.execute(
                    """
                    SELECT DISTINCT provider
                    FROM request_usage
                    WHERE chat_id = ? AND provider IS NOT NULL
                    """,
                    (chat_id,),
                ).fetchall()
            ]

        return {
            "requests":      row["requests"] if row else 0,
            "input_tokens":  row["inp"]      if row else None,
            "output_tokens": row["out"]      if row else None,
            "total_tokens":  row["tok"]      if row else None,
            "avg_response_ms": row["avg_ms"] if row else None,
            "models_used":   models,
            "providers_used": providers,
        }
    except Exception:
        return empty


def get_today_summary() -> dict:
    """
    Return a lightweight today summary for the /status panel.
    Keys: requests_today, tokens_today
    """
    try:
        start = _period_start("today")
        with _db() as con:
            row = con.execute(
                """
                SELECT COUNT(*) AS req, SUM(total_tokens) AS tok
                FROM request_usage
                WHERE timestamp >= ?
                """,
                (start,),
            ).fetchone()
        return {
            "requests_today": row["req"] if row else 0,
            "tokens_today":   row["tok"] if row else None,
        }
    except Exception:
        return {"requests_today": 0, "tokens_today": None}


def get_db_info() -> dict:
    """
    Return diagnostic information about the analytics database.
    Keys: db_path, db_size_bytes, total_rows, oldest_record, newest_record
    """
    try:
        db_path = config.ANALYTICS_DB
        size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        with _db() as con:
            row = con.execute(
                "SELECT COUNT(*) AS n, MIN(timestamp) AS oldest, MAX(timestamp) AS newest "
                "FROM request_usage"
            ).fetchone()
        return {
            "db_path":       db_path,
            "db_size_bytes": size,
            "total_rows":    row["n"] if row else 0,
            "oldest_record": row["oldest"] if row else None,
            "newest_record": row["newest"] if row else None,
        }
    except Exception:
        return {
            "db_path":       config.ANALYTICS_DB,
            "db_size_bytes": 0,
            "total_rows":    0,
            "oldest_record": None,
            "newest_record": None,
        }
