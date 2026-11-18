"""
core/context_budget.py — Model context budgeting and TPM rate-limit protection.

Guarantees requests stay safely below model context and provider TPM (tokens per minute)
rate limits (e.g. Groq 8,000 TPM limit on gpt-oss-20b).

Key capabilities:
  1. Configurable and detected TPM limits & context budgets per model.
  2. Safe request budgeting (reserving headroom for completion and estimation variance).
  3. Non-destructive pruning & summarization of old conversation messages for API dispatch
     (saved chat history in storage is NEVER deleted).
  4. Always preserves the latest user message and essential system instructions.
  5. Accurate HTTP 413/429 parsing, including 'retry_after', 'limit', and 'requested'.
  6. Rate-limit cooldown tracking to avoid repeating calls to throttled models.
"""

from dataclasses import dataclass
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import config


# ------------------------------------------------------------------
# DEFAULT LIMITS & CONSTANTS
# ------------------------------------------------------------------

# Known free-tier TPM (tokens per minute) limits
DEFAULT_MODEL_TPM_LIMITS: Dict[str, int] = {
    "groq/openai/gpt-oss-20b": 8000,
    "groq/openai/gpt-oss-120b": 8000,
    "groq/llama-3.3-70b-versatile": 6000,
    "groq/llama-3.1-8b-instant": 20000,
    "groq/mixtral-8x7b-32768": 5000,
}

# Model-specific safe request budgets (defaults)
DEFAULT_MODEL_CONTEXT_BUDGETS: Dict[str, int] = {
    "groq/openai/gpt-oss-20b": 6400,    # 8000 TPM * 0.80 safety factor
    "groq/openai/gpt-oss-120b": 6400,   # 8000 TPM * 0.80 safety factor
    "aihorde/aphrodite/TheDrummer/Cydonia-24B-v4.3": 4096,
    "aihorde/aphrodite/TheDrummer/Skyfall-31B-v4.2": 4096,
    "aihorde/google/gemma-4-31b": 4096,
}

DEFAULT_BUDGET_SAFETY_FACTOR = 0.80
DEFAULT_FALLBACK_BUDGET = 6400


# ------------------------------------------------------------------
# RUNTIME DETECTED STATE
# ------------------------------------------------------------------

_detected_tpm_limits: Dict[str, int] = {}
_model_cooldowns: Dict[str, float] = {}  # model_id -> epoch timestamp when cooldown expires


# ------------------------------------------------------------------
# ERROR DETAILS DATA STRUCTURE
# ------------------------------------------------------------------

@dataclass
class APIErrorDetails:
    status_code: Optional[int]
    is_413_or_tpm: bool
    is_rate_limited: bool
    retry_after: Optional[float]
    detected_tpm_limit: Optional[int]
    requested_tokens: Optional[int]
    error_message: str
    raw_text: str


# ------------------------------------------------------------------
# TOKEN ESTIMATION
# ------------------------------------------------------------------

def estimate_text_tokens(text: Optional[str]) -> int:
    """Estimate token count: ~1 token per 4 characters (min 1 for non-empty)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_message_tokens(msg: Dict[str, Any]) -> int:
    """Estimate tokens for a single chat message including formatting overhead."""
    content = msg.get("content", "")
    if isinstance(content, str):
        tokens = estimate_text_tokens(content)
    elif isinstance(content, list):
        tokens = 0
        for item in content:
            if isinstance(item, dict):
                tokens += estimate_text_tokens(item.get("text", ""))
            else:
                tokens += estimate_text_tokens(str(item))
    else:
        tokens = estimate_text_tokens(str(content))
    return tokens + 4  # role + delimiter overhead


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """Estimate total tokens for a sequence of chat messages."""
    return sum(estimate_message_tokens(m) for m in messages) + 3


# ------------------------------------------------------------------
# TPM & CONTEXT BUDGET ACCESSORS
# ------------------------------------------------------------------

def get_model_tpm_limit(model_id: Optional[str]) -> Optional[int]:
    """
    Return known or detected TPM (tokens per minute) rate limit for model.
    Checks: user config -> runtime detected -> default model dict -> default provider dict.
    """
    if not model_id or model_id == "auto":
        return None

    # 1. User configured in config.py / config.json
    cfg_limits = getattr(config, "model_tpm_limits", {}) or {}
    if model_id in cfg_limits:
        try:
            return int(cfg_limits[model_id])
        except (ValueError, TypeError):
            pass

    # 2. Runtime dynamically detected from provider error responses
    if model_id in _detected_tpm_limits:
        return _detected_tpm_limits[model_id]

    # 3. Built-in model TPM defaults
    if model_id in DEFAULT_MODEL_TPM_LIMITS:
        return DEFAULT_MODEL_TPM_LIMITS[model_id]

    return None


def record_detected_tpm_limit(model_id: str, limit: int):
    """Dynamically record a TPM limit reported by the provider at runtime."""
    if model_id and limit > 0:
        _detected_tpm_limits[model_id] = int(limit)


def get_model_context_budget(model_id: Optional[str]) -> int:
    """
    Return the maximum safe token budget for an API request to the given model.

    For local Ollama models this is the input budget only:
      OLLAMA_NUM_CTX - OLLAMA_NUM_PREDICT (output reservation) × 0.95 safety margin.
    For cloud models resolves in order:
      1. User configured model context budget (config.model_context_budgets)
      2. If TPM limit exists: min(context_length, int(tpm_limit * safety_factor))
      3. Model context_length or max_input_tokens from catalog
      4. Default safe fallback budget
    """
    if not model_id or model_id == "auto":
        return DEFAULT_FALLBACK_BUDGET

    # Local Ollama models: budget = total context window minus output reservation
    if str(model_id).startswith("ollama:"):
        # Allow per-model user override first
        cfg_budgets = getattr(config, "model_context_budgets", {}) or {}
        if model_id in cfg_budgets:
            try:
                return int(cfg_budgets[model_id])
            except (ValueError, TypeError):
                pass
        # Use pre-computed config constant (OLLAMA_NUM_CTX - OLLAMA_NUM_PREDICT) × 0.95
        return int(getattr(config, "OLLAMA_MAX_INPUT_TOKENS", 5832))

    safety_factor = getattr(config, "context_budget_safety_factor", DEFAULT_BUDGET_SAFETY_FACTOR)
    try:
        safety_factor = float(safety_factor)
    except (ValueError, TypeError):
        safety_factor = DEFAULT_BUDGET_SAFETY_FACTOR

    # 1. Explicit user override in config
    cfg_budgets = getattr(config, "model_context_budgets", {}) or {}
    if model_id in cfg_budgets:
        try:
            return int(cfg_budgets[model_id])
        except (ValueError, TypeError):
            pass

    # 2. Check TPM limit
    tpm = get_model_tpm_limit(model_id)

    # 3. Check catalog context window
    from core.model_manager import get_model_context_limit
    ctx_limit = get_model_context_limit(model_id)
    try:
        ctx_limit = int(ctx_limit) if ctx_limit else None
    except (ValueError, TypeError):
        ctx_limit = None

    if tpm is not None:
        safe_tpm = max(500, int(tpm * safety_factor))
        if ctx_limit is not None:
            return min(ctx_limit, safe_tpm)
        return safe_tpm

    # Check built-in budget defaults
    if model_id in DEFAULT_MODEL_CONTEXT_BUDGETS:
        return DEFAULT_MODEL_CONTEXT_BUDGETS[model_id]

    if ctx_limit is not None:
        return ctx_limit

    return DEFAULT_FALLBACK_BUDGET


# ------------------------------------------------------------------
# COOLDOWN TRACKING
# ------------------------------------------------------------------

def set_model_cooldown(model_id: str, retry_after: float):
    """Mark a model as cooling down until time.time() + retry_after."""
    if model_id and retry_after > 0:
        _model_cooldowns[model_id] = time.time() + float(retry_after)


def is_model_cooling_down(model_id: str) -> Tuple[bool, float]:
    """
    Return (is_cooling, remaining_seconds).
    If cooling down has expired, clears the entry.
    """
    if not model_id or model_id not in _model_cooldowns:
        return False, 0.0

    exp = _model_cooldowns[model_id]
    rem = exp - time.time()
    if rem > 0:
        return True, rem
    else:
        _model_cooldowns.pop(model_id, None)
        return False, 0.0


def clear_model_cooldown(model_id: str):
    """Clear cooldown for a model."""
    _model_cooldowns.pop(model_id, None)


# ------------------------------------------------------------------
# ERROR PARSER
# ------------------------------------------------------------------

def parse_api_error(
    status_code: Optional[int],
    error_text: str,
    headers: Optional[Dict[str, str]] = None,
) -> APIErrorDetails:
    """
    Parse an API error response for 413 / 429 status codes, TPM rate limits,
    requested vs limit tokens, and retry-after wait duration.
    """
    headers = headers or {}
    text = str(error_text or "")
    text_lower = text.lower()

    # Determine 413 or TPM / payload size issue
    is_413_or_tpm = False
    if status_code == 413:
        is_413_or_tpm = True
    elif "request too large" in text_lower:
        is_413_or_tpm = True
    elif "tokens per minute" in text_lower or "tpm" in text_lower:
        is_413_or_tpm = True
    elif "context_length_exceeded" in text_lower or "maximum context length" in text_lower:
        is_413_or_tpm = True

    # Determine rate limited
    is_rate_limited = (
        status_code == 429 or
        is_413_or_tpm or
        "rate limit" in text_lower or
        "rate_limit" in text_lower or
        "tokens per minute" in text_lower
    )

    # Parse retry-after from header or text
    retry_after: Optional[float] = None
    # 1. Header check
    for k, v in headers.items():
        if k.lower() == "retry-after":
            try:
                retry_after = float(v)
                break
            except (ValueError, TypeError):
                pass

    # 2. JSON body check
    parsed_json = None
    try:
        parsed_json = json.loads(text)
        if isinstance(parsed_json, dict):
            err_obj = parsed_json.get("error", {})
            if isinstance(err_obj, dict):
                if "retry_after" in err_obj:
                    try:
                        retry_after = float(err_obj["retry_after"])
                    except Exception:
                        pass
    except Exception:
        pass

    # 3. Regex in text (e.g. "try again in 35s", "Please try again in 35.2 seconds", "retry-after: 35")
    if retry_after is None:
        m = re.search(r"(?:try again in|retry[ -_]after[:=\s]+)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:s|seconds?)?", text_lower)
        if m:
            try:
                retry_after = float(m.group(1))
            except Exception:
                pass
        else:
            m2 = re.search(r"in\s+([0-9]+(?:\.[0-9]+)?)\s*s(?:econds?)?", text_lower)
            if m2:
                try:
                    retry_after = float(m2.group(1))
                except Exception:
                    pass

    # Parse detected TPM limit
    detected_tpm_limit: Optional[int] = None
    m_limit = re.search(r"(?:tpm limit|limit)[:=\s]+([0-9]+)", text, re.IGNORECASE)
    if m_limit:
        try:
            detected_tpm_limit = int(m_limit.group(1))
        except Exception:
            pass

    # Parse requested tokens
    requested_tokens: Optional[int] = None
    m_req = re.search(r"(?:requested|requested tokens)[:=\s]+([0-9]+)", text, re.IGNORECASE)
    if m_req:
        try:
            requested_tokens = int(m_req.group(1))
        except Exception:
            pass

    # Friendly error message
    clean_message = text
    if parsed_json and isinstance(parsed_json, dict):
        err = parsed_json.get("error", {})
        if isinstance(err, dict) and "message" in err:
            clean_message = str(err["message"])

    return APIErrorDetails(
        status_code=status_code,
        is_413_or_tpm=is_413_or_tpm,
        is_rate_limited=is_rate_limited,
        retry_after=retry_after,
        detected_tpm_limit=detected_tpm_limit,
        requested_tokens=requested_tokens,
        error_message=clean_message,
        raw_text=text,
    )


# ------------------------------------------------------------------
# MESSAGE PRUNING & CONTEXT BUDGETING
# ------------------------------------------------------------------

def prepare_budgeted_messages(
    messages: List[Dict[str, Any]],
    model_id: str,
    max_tokens: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], bool, Dict[str, Any]]:
    """
    Prepare a safe message sequence for API dispatch fitting within the model's budget.

    Guarantees:
      - Saved chat history is NEVER mutated or deleted (a fresh list copy is returned).
      - Always preserves the latest user message.
      - Always preserves the essential system instructions (messages[0]).
      - Prunes older conversation turns oldest-first if total exceeds budget.
      - Inserts a compact summarization note for pruned turns.
      - Truncates supplemental contexts (attachments, project, RAG, terminal) if needed.

    Returns:
      (budgeted_messages, was_pruned, stats_dict)
    """
    if not messages:
        return [], False, {"original_tokens": 0, "final_tokens": 0, "pruned_turns": 0}

    budget = max_tokens if (max_tokens is not None and max_tokens > 0) else get_model_context_budget(model_id)
    original_tokens = estimate_messages_tokens(messages)

    if original_tokens <= budget:
        # Fits comfortably without pruning
        return list(messages), False, {
            "original_tokens": original_tokens,
            "final_tokens": original_tokens,
            "pruned_turns": 0,
            "budget": budget,
            "exceeds_essential": False,
        }

    # Separate messages into logical segments:
    # 1. Essential system prompt (first system message)
    # 2. Supplemental system contexts (terminal, files, project, rag)
    # 3. Conversation history turns (prior user/assistant messages)
    # 4. Latest user message (the current turn prompt)
    # 5. Native tool follow-up messages (if any)

    essential_system: Optional[Dict[str, Any]] = None
    supplemental_systems: List[Dict[str, Any]] = []
    history_turns: List[Dict[str, Any]] = []
    latest_user_message: Optional[Dict[str, Any]] = None
    tool_followups: List[Dict[str, Any]] = []

    # Find the latest user message from the end
    last_user_idx = -1
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].get("role") == "user" and not str(messages[idx].get("content", "")).startswith("[TOOL RESULT"):
            last_user_idx = idx
            break

    for idx, msg in enumerate(messages):
        role = msg.get("role")
        content = str(msg.get("content", ""))

        if role == "system":
            if essential_system is None:
                essential_system = dict(msg)
            else:
                supplemental_systems.append(dict(msg))
        elif idx == last_user_idx:
            latest_user_message = dict(msg)
        elif idx > last_user_idx:
            tool_followups.append(dict(msg))
        else:
            history_turns.append(dict(msg))

    # Fallback if no user message found (e.g. system-only payload)
    if latest_user_message is None and history_turns:
        latest_user_message = history_turns.pop()

    # Minimum essential tokens required:
    essential_tokens = (estimate_message_tokens(essential_system) if essential_system else 0)
    latest_user_tokens = (estimate_message_tokens(latest_user_message) if latest_user_message else 0)
    min_required = essential_tokens + latest_user_tokens + 10

    if min_required > budget:
        # Prompt + essential system ALONE exceeds budget!
        # Cannot fit even with 0 history and 0 supplemental context.
        # Preserve essential system + latest user message, mark exceeds_essential = True.
        res = []
        if essential_system:
            res.append(essential_system)
        if latest_user_message:
            res.append(latest_user_message)
        return res, True, {
            "original_tokens": original_tokens,
            "final_tokens": estimate_messages_tokens(res),
            "pruned_turns": len(history_turns),
            "budget": budget,
            "exceeds_essential": True,
        }

    # Remaining token budget for supplemental contexts, history, and tool followups
    remaining_budget = budget - min_required

    # 1. Budget tool followups (current turn actions)
    kept_tool_followups = []
    for tf in tool_followups:
        cost = estimate_message_tokens(tf)
        if cost <= remaining_budget:
            kept_tool_followups.append(tf)
            remaining_budget -= cost
        else:
            # Compress tool result if it is oversized
            content_str = str(tf.get("content", ""))
            allowed_chars = max(200, remaining_budget * 3)
            truncated_content = content_str[:allowed_chars] + "\n... [Output truncated to preserve context budget]"
            compressed_tf = dict(tf)
            compressed_tf["content"] = truncated_content
            kept_tool_followups.append(compressed_tf)
            remaining_budget = 0
            break

    # 2. Budget supplemental system contexts (files, project, rag, terminal)
    kept_supplemental = []
    for supp in supplemental_systems:
        cost = estimate_message_tokens(supp)
        if cost <= remaining_budget:
            kept_supplemental.append(supp)
            remaining_budget -= cost
        else:
            if remaining_budget >= 150:
                # Truncate supplemental context to available budget
                content_str = str(supp.get("content", ""))
                allowed_chars = remaining_budget * 3
                compressed_supp = dict(supp)
                compressed_supp["content"] = content_str[:allowed_chars] + "\n... [Context truncated for budget]"
                kept_supplemental.append(compressed_supp)
                remaining_budget = 0
            break

    # 3. Budget conversation history (walk backwards from newest to oldest)
    kept_history = []
    pruned_count = 0
    for turn in reversed(history_turns):
        cost = estimate_message_tokens(turn)
        if cost <= remaining_budget:
            kept_history.append(turn)
            remaining_budget -= cost
        else:
            pruned_count += 1

    kept_history.reverse()

    # Build final message list
    final_messages: List[Dict[str, Any]] = []
    if essential_system:
        final_messages.append(essential_system)

    for supp in kept_supplemental:
        final_messages.append(supp)

    # If history turns were pruned, insert a compact summarization notice
    if pruned_count > 0:
        summary_notice = {
            "role": "system",
            "content": f"[Earlier conversation history ({pruned_count} turn{'s' if pruned_count > 1 else ''}) condensed to stay safely within model token budget.]"
        }
        final_messages.append(summary_notice)

    final_messages.extend(kept_history)

    if latest_user_message:
        final_messages.append(latest_user_message)

    final_messages.extend(kept_tool_followups)

    final_tokens = estimate_messages_tokens(final_messages)

    return final_messages, True, {
        "original_tokens": original_tokens,
        "final_tokens": final_tokens,
        "pruned_turns": pruned_count,
        "budget": budget,
        "exceeds_essential": False,
    }
