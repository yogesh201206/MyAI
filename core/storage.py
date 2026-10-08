"""
core/storage.py — Disk I/O for chats and configuration.

Reads and writes ~/.myai/chats.json and ~/.myai/config.json.
All paths come from config so they are never duplicated.

Safety features (Phase 15):
  - Atomic writes via temp file + os.replace() to prevent corruption on crash.
  - Backup preservation on load failure.
  - Recovery from backup on primary file corruption.
"""

import json
import os
import shutil
import tempfile
import time

import config


def _atomic_write(path: str, data: dict | list) -> None:
    """
    Write JSON to `path` atomically using a temporary file + os.replace().
    Prevents corruption if the process is interrupted mid-write.
    """
    dir_name = os.path.dirname(path)
    os.makedirs(dir_name, exist_ok=True)

    # Write to a temp file in the same directory (so rename is atomic on same FS)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)  # atomic on POSIX
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


def _backup_path(path: str) -> str:
    """Return the backup path for a given data file."""
    return path + ".backup"


def setup_storage():
    """Create ~/.myai/ and seed empty files if they do not exist."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.VOICE_TMP_DIR, exist_ok=True)

    if not os.path.exists(config.CHATS_FILE):
        _atomic_write(config.CHATS_FILE, [])

    if not os.path.exists(config.CONFIG_FILE):
        _atomic_write(
            config.CONFIG_FILE,
            {
                "current_chat_id": None,
                "current_model": config.DEFAULT_MODEL,
                "streaming_enabled": config.DEFAULT_STREAMING,
                "voice_enabled": config.DEFAULT_VOICE_ENABLED,
                "voice_input_enabled": config.DEFAULT_VOICE_INPUT_ENABLED,
                "voice_output_enabled": config.DEFAULT_VOICE_OUTPUT_ENABLED,
                "voice_stt_backend": config.DEFAULT_VOICE_STT_BACKEND,
                "voice_tts_backend": config.DEFAULT_VOICE_TTS_BACKEND,
                "voice_language": config.DEFAULT_VOICE_LANGUAGE,
                "voice_speed": config.DEFAULT_VOICE_SPEED,
                "voice_push_to_talk": config.DEFAULT_VOICE_PUSH_TO_TALK,
            }
        )


# ------------------------------------------------------------------
# CHATS
# ------------------------------------------------------------------

def load_chats():
    """Load chats from disk into config.chats. Recovers from corruption."""
    loaded = False

    for attempt_path in [config.CHATS_FILE, _backup_path(config.CHATS_FILE)]:
        if not os.path.exists(attempt_path):
            continue
        try:
            with open(attempt_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                config.chats = data
                for chat in config.chats:
                    if isinstance(chat, dict) and "attachments" not in chat:
                        chat["attachments"] = []
                loaded = True
                break
        except Exception:
            continue

    if not loaded:
        config.chats = []


def save_chats():
    """Persist config.chats to disk atomically. Creates a backup first."""
    # Rotate previous file to backup before overwriting
    if os.path.exists(config.CHATS_FILE):
        try:
            shutil.copy2(config.CHATS_FILE, _backup_path(config.CHATS_FILE))
        except Exception:
            pass
    _atomic_write(config.CHATS_FILE, config.chats)


# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------

def _apply_config_defaults():
    """Reset all config state to defaults (used as fallback on load failure)."""
    config.current_chat_id = None
    config.current_model = config.DEFAULT_MODEL
    config.streaming_enabled = config.DEFAULT_STREAMING
    config.rag_enabled = config.DEFAULT_RAG_ENABLED
    config.project_mode = config.DEFAULT_PROJECT_MODE
    config.active_project_path = None
    config.agent_enabled = config.DEFAULT_AGENT_ENABLED
    config.router_mode = config.DEFAULT_ROUTER_MODE
    config.model_selection_mode = config.DEFAULT_MODEL_SELECTION_MODE
    config.router_verbose = config.DEFAULT_ROUTER_VERBOSE
    config.debug_mode = config.DEFAULT_DEBUG_MODE
    config.router_enabled = config.DEFAULT_ROUTER_ENABLED
    config.router_capability_weight = config.DEFAULT_ROUTER_CAPABILITY_WEIGHT
    config.router_context_weight = config.DEFAULT_ROUTER_CONTEXT_WEIGHT
    config.router_health_weight = config.DEFAULT_ROUTER_HEALTH_WEIGHT
    config.router_reliability_weight = config.DEFAULT_ROUTER_RELIABILITY_WEIGHT
    config.router_latency_weight = config.DEFAULT_ROUTER_LATENCY_WEIGHT
    config.router_max_fallbacks = config.DEFAULT_ROUTER_MAX_FALLBACKS
    config.voice_enabled = config.DEFAULT_VOICE_ENABLED
    config.voice_input_enabled = config.DEFAULT_VOICE_INPUT_ENABLED
    config.voice_output_enabled = config.DEFAULT_VOICE_OUTPUT_ENABLED
    config.voice_stt_backend = config.DEFAULT_VOICE_STT_BACKEND
    config.voice_tts_backend = config.DEFAULT_VOICE_TTS_BACKEND
    config.voice_language = config.DEFAULT_VOICE_LANGUAGE
    config.voice_speed = config.DEFAULT_VOICE_SPEED
    config.voice_push_to_talk = config.DEFAULT_VOICE_PUSH_TO_TALK
    config.voice_max_speech_chars = config.DEFAULT_VOICE_MAX_SPEECH_CHARS
    config.voice_input_device = None
    config.voice_output_device = None
    config.free_verification_days = config.DEFAULT_FREE_VERIFICATION_DAYS


def _apply_config_dict(data: dict) -> None:
    """Apply a loaded config dict to the config module, with backward-compat defaults."""
    config.current_chat_id = data.get("current_chat_id")
    config.current_model = data.get("current_model", config.DEFAULT_MODEL)
    config.streaming_enabled = data.get("streaming_enabled", config.DEFAULT_STREAMING)
    config.rag_enabled = data.get("rag_enabled", config.DEFAULT_RAG_ENABLED)
    config.project_mode = data.get("project_mode", config.DEFAULT_PROJECT_MODE)
    config.active_project_path = data.get("active_project_path", None)
    config.agent_enabled = data.get("agent_enabled", config.DEFAULT_AGENT_ENABLED)
    config.router_mode = data.get("router_mode", config.DEFAULT_ROUTER_MODE)
    config.model_selection_mode = data.get("model_selection_mode", config.DEFAULT_MODEL_SELECTION_MODE)
    config.router_verbose = data.get("router_verbose", config.DEFAULT_ROUTER_VERBOSE)
    config.debug_mode = data.get("debug_mode", config.DEFAULT_DEBUG_MODE)
    config.router_enabled = data.get("router_enabled", config.DEFAULT_ROUTER_ENABLED)
    config.router_capability_weight = float(data.get("router_capability_weight", config.DEFAULT_ROUTER_CAPABILITY_WEIGHT))
    config.router_context_weight = float(data.get("router_context_weight", config.DEFAULT_ROUTER_CONTEXT_WEIGHT))
    config.router_health_weight = float(data.get("router_health_weight", config.DEFAULT_ROUTER_HEALTH_WEIGHT))
    config.router_reliability_weight = float(data.get("router_reliability_weight", config.DEFAULT_ROUTER_RELIABILITY_WEIGHT))
    config.router_latency_weight = float(data.get("router_latency_weight", config.DEFAULT_ROUTER_LATENCY_WEIGHT))
    config.router_max_fallbacks = int(data.get("router_max_fallbacks", config.DEFAULT_ROUTER_MAX_FALLBACKS))

    # Voice settings (Phase 13)
    config.voice_enabled = data.get("voice_enabled", config.DEFAULT_VOICE_ENABLED)
    config.voice_input_enabled = data.get("voice_input_enabled", config.DEFAULT_VOICE_INPUT_ENABLED)
    config.voice_output_enabled = data.get("voice_output_enabled", config.DEFAULT_VOICE_OUTPUT_ENABLED)
    config.voice_stt_backend = data.get("voice_stt_backend", config.DEFAULT_VOICE_STT_BACKEND)
    config.voice_tts_backend = data.get("voice_tts_backend", config.DEFAULT_VOICE_TTS_BACKEND)
    config.voice_language = data.get("voice_language", config.DEFAULT_VOICE_LANGUAGE)
    config.voice_speed = float(data.get("voice_speed", config.DEFAULT_VOICE_SPEED))
    config.voice_push_to_talk = data.get("voice_push_to_talk", config.DEFAULT_VOICE_PUSH_TO_TALK)
    config.voice_max_speech_chars = int(data.get("voice_max_speech_chars", config.DEFAULT_VOICE_MAX_SPEECH_CHARS))
    config.voice_input_device = data.get("voice_input_device", None)
    config.voice_output_device = data.get("voice_output_device", None)
    config.free_verification_days = int(data.get("free_verification_days", config.DEFAULT_FREE_VERIFICATION_DAYS))


def load_config():
    """Read config.json and update config state with backward-compatible defaults.
    
    On corruption: attempts backup recovery, then falls back to defaults.
    Shows a warning (but does not crash) if recovery was needed.
    """
    from ui.console import console

    for attempt_path in [config.CONFIG_FILE, _backup_path(config.CONFIG_FILE)]:
        if not os.path.exists(attempt_path):
            continue
        try:
            with open(attempt_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _apply_config_dict(data)
                if attempt_path != config.CONFIG_FILE:
                    console.print(
                        "[yellow]⚠ config.json was corrupted — recovered from backup. "
                        "Your settings have been restored.[/yellow]"
                    )
                return
        except Exception:
            continue

    # Total fallback — silently apply defaults
    _apply_config_defaults()


def save_config():
    """Persist current state to config.json atomically. Creates a backup first."""
    if os.path.exists(config.CONFIG_FILE):
        try:
            shutil.copy2(config.CONFIG_FILE, _backup_path(config.CONFIG_FILE))
        except Exception:
            pass

    _atomic_write(
        config.CONFIG_FILE,
        {
            "current_chat_id": config.current_chat_id,
            "current_model": config.current_model,
            "streaming_enabled": config.streaming_enabled,
            "rag_enabled": config.rag_enabled,
            "project_mode": config.project_mode,
            "active_project_path": config.active_project_path,
            "agent_enabled": config.agent_enabled,
            "router_mode": config.router_mode,
            "model_selection_mode": config.model_selection_mode,
            "router_verbose": config.router_verbose,
            "debug_mode": config.debug_mode,
            "router_enabled": config.router_enabled,
            "router_capability_weight": config.router_capability_weight,
            "router_context_weight": config.router_context_weight,
            "router_health_weight": config.router_health_weight,
            "router_reliability_weight": config.router_reliability_weight,
            "router_latency_weight": config.router_latency_weight,
            "router_max_fallbacks": config.router_max_fallbacks,
            "voice_enabled": config.voice_enabled,
            "voice_input_enabled": config.voice_input_enabled,
            "voice_output_enabled": config.voice_output_enabled,
            "voice_stt_backend": config.voice_stt_backend,
            "voice_tts_backend": config.voice_tts_backend,
            "voice_language": config.voice_language,
            "voice_speed": config.voice_speed,
            "voice_push_to_talk": config.voice_push_to_talk,
            "voice_max_speech_chars": config.voice_max_speech_chars,
            "voice_input_device": config.voice_input_device,
            "voice_output_device": config.voice_output_device,
            "free_verification_days": config.free_verification_days,
        }
    )


def validate_and_sanitize_configured_model() -> tuple[bool, str | None]:
    """
    Validate that config.current_model conforms to AIZEN Free-Only policy.

    If current_model is not verified free:
      1. Detects that the model is no longer allowed.
      2. Marks it invalid/unavailable.
      3. Selects an available verified-free model (or 'auto') if one exists.
      4. Preserves config.json and chats.json without corruption.

    Returns:
        (was_valid: bool, notification_message: Optional[str])
    """
    from core.free_model_registry import is_model_allowed, get_default_free_model

    model = getattr(config, "current_model", None)
    if not model or model == "auto":
        return True, None

    provider = None
    try:
        from core.provider_health import get_provider_for_model
        provider = get_provider_for_model(model)
    except Exception:
        pass

    if not is_model_allowed(provider, model):
        old_model = model
        safe_replacement = get_default_free_model() or "auto"
        config.current_model = safe_replacement
        if safe_replacement == "auto":
            config.model_selection_mode = "router"
        save_config()

        msg = (
            f"Configured model '{old_model}' is not available in AIZEN Free-Only mode. "
            f"Switched to verified-free model '{safe_replacement}'."
        )
        return False, msg

    return True, None
