"""
core/provider_health.py — Passive provider health tracking subsystem.

Design rules:
  - Health is PASSIVE-FIRST: data comes only from /v1/models catalog,
    actual request successes/failures, HTTP status codes, and latency.
    We NEVER send paid test prompts to probe health.
  - Health data is stored in ~/.myai/provider_health.json.
  - Status confidence decays to UNKNOWN after STALE_MINUTES of inactivity
    but historical counters (success_count, failure_count) are preserved.
  - File writes are done atomically (write-to-temp, then rename).

Status rules:
  ONLINE       — at least one recent success, zero consecutive failures
  DEGRADED     — recent failures (5xx, timeout, connection error) but also
                 has had prior successes; or consecutive_failures > 0 but < OFFLINE_THRESHOLD
  RATE_LIMITED — most recent error code was 429
  AUTH_ERROR   — most recent error code was 401, or 403 with auth-related message
  OFFLINE      — connection error / consecutive_failures >= OFFLINE_THRESHOLD with no
                 recent success; or never had a success and connection failed
  UNKNOWN      — no requests recorded yet, or last_success/failure is older than
                 STALE_MINUTES and no ongoing signal
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone

import config

# ------------------------------------------------------------------
# CONSTANTS
# ------------------------------------------------------------------

STALE_MINUTES      = 30          # status decays to UNKNOWN after this
OFFLINE_THRESHOLD  = 5           # consecutive failures before OFFLINE
LATENCY_WINDOW     = 10          # rolling average over last N samples

STATUS_ONLINE       = "ONLINE"
STATUS_DEGRADED     = "DEGRADED"
STATUS_RATE_LIMITED = "RATE_LIMITED"
STATUS_AUTH_ERROR   = "AUTH_ERROR"
STATUS_OFFLINE      = "OFFLINE"
STATUS_UNKNOWN      = "UNKNOWN"

# Symbols for display
STATUS_SYMBOLS = {
    STATUS_ONLINE:       "●",
    STATUS_DEGRADED:     "◐",
    STATUS_RATE_LIMITED: "◑",
    STATUS_AUTH_ERROR:   "⊗",
    STATUS_OFFLINE:      "○",
    STATUS_UNKNOWN:      "·",
}

STATUS_COLORS = {
    STATUS_ONLINE:       "green",
    STATUS_DEGRADED:     "yellow",
    STATUS_RATE_LIMITED: "dark_orange",
    STATUS_AUTH_ERROR:   "red",
    STATUS_OFFLINE:      "red",
    STATUS_UNKNOWN:      "dim",
}


# ------------------------------------------------------------------
# INTERNAL STATE
# ------------------------------------------------------------------

# In-memory registry: provider_name → health_record dict
_registry: dict[str, dict] = {}

# Flag: True after load_health() has been called once
_loaded = False


def _health_file() -> str:
    """Return absolute path to provider_health.json."""
    return config.PROVIDER_HEALTH_FILE


def _now_ts() -> float:
    """Current UTC time as float (unix epoch)."""
    return time.time()


def _now_iso() -> str:
    """Current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------
# BLANK RECORD FACTORY
# ------------------------------------------------------------------

def _blank_record(provider_name: str) -> dict:
    """Return a fresh, zeroed-out health record for a provider."""
    return {
        "provider_name":       provider_name,
        "status":              STATUS_UNKNOWN,
        "available_models":    [],
        "last_success":        None,      # ISO-8601 or None
        "last_failure":        None,
        "last_error":          None,
        "last_error_code":     None,
        "average_latency_ms":  None,
        "recent_latency_ms":   None,
        "latency_samples":     [],        # rolling window, not persisted in full
        "success_count":       0,
        "failure_count":       0,
        "consecutive_failures": 0,
        "last_used_model":     None,
        "rate_limited_until":  None,      # ISO-8601 or None
        "discovered_at":       _now_iso(),
    }


# ------------------------------------------------------------------
# PERSISTENCE
# ------------------------------------------------------------------

def load_health():
    """Load provider health from disk. Safe to call multiple times."""
    global _registry, _loaded

    path = _health_file()
    if not os.path.exists(path):
        _loaded = True
        return

    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)

        if not isinstance(raw, dict):
            raise ValueError("top-level is not a dict")

        providers = raw.get("providers", {})
        if not isinstance(providers, dict):
            raise ValueError("providers key is not a dict")

        # Merge loaded data into registry; blank-fill any missing keys
        for name, record in providers.items():
            base = _blank_record(name)
            base.update(record)          # loaded values win
            base["provider_name"] = name # ensure consistent
            _registry[name] = base

    except (json.JSONDecodeError, ValueError, KeyError, OSError):
        # Corrupt / unreadable file — start fresh, do not crash
        _registry = {}

    _loaded = True


def save_health():
    """
    Persist current registry to disk atomically.
    Strips the in-memory-only latency_samples list before writing.
    """
    _ensure_loaded()
    path = _health_file()

    # Build serialisable copy
    out_providers = {}
    for name, record in _registry.items():
        rec_copy = dict(record)
        rec_copy.pop("latency_samples", None)   # not persisted
        out_providers[name] = rec_copy

    payload = {
        "schema_version": 1,
        "saved_at":       _now_iso(),
        "providers":      out_providers,
    }

    # Atomic write: write to temp file in same dir, then rename
    dir_path = os.path.dirname(path)
    os.makedirs(dir_path, exist_ok=True)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError:
        pass    # Disk full or permission error — don't crash


def _ensure_loaded():
    """Lazily load health data on first access."""
    global _loaded
    if not _loaded:
        load_health()


# ------------------------------------------------------------------
# PROVIDER DISCOVERY
# ------------------------------------------------------------------

def get_provider_for_model(model_id: str) -> str | None:
    """
    Resolve a model_id to its provider name.

    Resolution order:
      1. Look up owned_by in config.model_map
      2. Use the prefix before '/' in model_id (e.g. 'google/...' → 'google')
      3. Return None if unresolvable
    """
    if not model_id:
        return None

    meta = config.model_map.get(model_id)
    if meta:
        owned = meta.get("owned_by")
        if owned:
            return str(owned)

    # Fallback: slash prefix
    if "/" in model_id:
        return model_id.split("/")[0]

    return None


def sync_catalog(model_catalog: list):
    """
    Discover providers from the live model catalog and ensure each
    provider has a registry entry.  Updates available_models lists.
    Does NOT overwrite existing health metrics.
    """
    _ensure_loaded()

    # Group models by provider
    provider_models: dict[str, list] = {}
    for model in model_catalog:
        model_id = model.get("id", "")
        provider = (
            model.get("owned_by")
            or (model_id.split("/")[0] if "/" in model_id else None)
        )
        if not provider:
            continue
        provider = str(provider)
        provider_models.setdefault(provider, []).append(model_id)

    for provider, models in provider_models.items():
        if provider not in _registry:
            _registry[provider] = _blank_record(provider)
        _registry[provider]["available_models"] = sorted(models)


# ------------------------------------------------------------------
# LATENCY HELPERS
# ------------------------------------------------------------------

def _update_latency(record: dict, latency_ms: float):
    """Update rolling latency samples and average."""
    samples: list = record.get("latency_samples", [])
    samples.append(latency_ms)
    if len(samples) > LATENCY_WINDOW:
        samples = samples[-LATENCY_WINDOW:]
    record["latency_samples"] = samples
    record["recent_latency_ms"] = latency_ms
    record["average_latency_ms"] = sum(samples) / len(samples)


# ------------------------------------------------------------------
# HEALTH RECORDING
# ------------------------------------------------------------------

def record_success(provider: str, model: str, latency_ms: float):
    """
    Called after every successful chat completion.

    Updates:
      - last_success timestamp
      - success_count +1
      - consecutive_failures reset to 0
      - last_used_model
      - rolling latency
      - status → ONLINE
    """
    if not provider:
        return

    _ensure_loaded()

    record = _registry.setdefault(provider, _blank_record(provider))

    record["last_success"]         = _now_iso()
    record["success_count"]       += 1
    record["consecutive_failures"] = 0
    record["last_used_model"]      = model
    record["status"]               = STATUS_ONLINE

    _update_latency(record, latency_ms)
    save_health()


def record_failure(
    provider: str,
    model: str,
    error: str,
    error_code: int | None = None,
    diagnostics: dict | None = None,
):
    """
    Called after every failed chat completion.

    Maps HTTP status codes to statuses:
      401              → AUTH_ERROR
      403 (auth text)  → AUTH_ERROR
      403 (other)      → DEGRADED
      429              → RATE_LIMITED
      5xx              → DEGRADED
      connection error → OFFLINE (no prior success) or DEGRADED
      timeout          → DEGRADED
      repeated (>= OFFLINE_THRESHOLD with no recent success) → OFFLINE
    """
    if not provider:
        return

    _ensure_loaded()

    record = _registry.setdefault(provider, _blank_record(provider))

    record["last_failure"]        = _now_iso()
    record["last_error"]          = str(error)[:500]
    record["last_error_code"]     = error_code
    record["failure_count"]      += 1
    record["consecutive_failures"] += 1
    record["last_used_model"]     = model

    # Use OmniRoute diagnostics if available
    if diagnostics:
        if diagnostics.get("provider") and not provider:
            provider = diagnostics["provider"]

    # Determine new status
    code = error_code
    consec = record["consecutive_failures"]
    has_prior_success = record["success_count"] > 0

    if code == 401:
        record["status"] = STATUS_AUTH_ERROR
    elif code == 403:
        err_lower = str(error).lower()
        if any(kw in err_lower for kw in ("auth", "account", "key", "credential", "unauthorized")):
            record["status"] = STATUS_AUTH_ERROR
        else:
            record["status"] = STATUS_DEGRADED
    elif code == 429:
        record["status"] = STATUS_RATE_LIMITED
    elif code is not None and 500 <= code < 600:
        record["status"] = STATUS_DEGRADED
    elif code is None:
        # Connection error or timeout
        if not has_prior_success or consec >= OFFLINE_THRESHOLD:
            record["status"] = STATUS_OFFLINE
        else:
            record["status"] = STATUS_DEGRADED
    else:
        # Other codes
        if consec >= OFFLINE_THRESHOLD and not has_prior_success:
            record["status"] = STATUS_OFFLINE
        else:
            record["status"] = STATUS_DEGRADED

    # Escalate to OFFLINE if too many consecutive failures
    if consec >= OFFLINE_THRESHOLD and record["status"] not in (
        STATUS_AUTH_ERROR, STATUS_RATE_LIMITED
    ):
        record["status"] = STATUS_OFFLINE

    save_health()


# ------------------------------------------------------------------
# STATUS RETRIEVAL
# ------------------------------------------------------------------

def get_provider_status(provider_name: str) -> str:
    """
    Return the current status for a provider.

    If the last signal (success or failure) is older than STALE_MINUTES,
    return UNKNOWN.  Historical counters are preserved.
    """
    _ensure_loaded()

    record = _registry.get(provider_name)
    if not record:
        return STATUS_UNKNOWN

    # Check staleness — use the more recent of last_success / last_failure
    last_ts = None
    for key in ("last_success", "last_failure"):
        val = record.get(key)
        if val:
            try:
                ts = datetime.fromisoformat(val).timestamp()
                if last_ts is None or ts > last_ts:
                    last_ts = ts
            except ValueError:
                pass

    if last_ts is None:
        return STATUS_UNKNOWN

    age_minutes = (_now_ts() - last_ts) / 60
    if age_minutes > STALE_MINUTES:
        return STATUS_UNKNOWN

    return record.get("status", STATUS_UNKNOWN)


def get_provider_record(provider_name: str) -> dict | None:
    """Return the full health record for a provider, or None."""
    _ensure_loaded()
    return _registry.get(provider_name)


def get_all_providers() -> list[str]:
    """Return sorted list of all known provider names."""
    _ensure_loaded()
    return sorted(_registry.keys())


def get_summary() -> dict:
    """
    Return a count summary of provider statuses.

    Returns dict: { status_string: count, ... }
    """
    _ensure_loaded()
    counts: dict[str, int] = {}
    for name in _registry:
        s = get_provider_status(name)
        counts[s] = counts.get(s, 0) + 1
    return counts


def get_health_indicator(provider_name: str) -> str:
    """
    Return a short one-character + status display string for use in
    the model picker or inline display.

    e.g.  "● ONLINE"  "◐ DEGRADED"  "· UNKNOWN"
    """
    status = get_provider_status(provider_name)
    symbol = STATUS_SYMBOLS.get(status, "·")
    return f"{symbol} {status}"
