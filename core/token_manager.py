"""
core/token_manager.py — Token estimation and context usage tracking.

All functions are pure calculations or state reads from config.
No network calls, no UI output.
"""

import config


def human_number(value):
    """Format a large integer as a human-readable string (e.g. 128K, 1.2M)."""
    if value is None:
        return "Unknown"
    try:
        value = int(value)
    except Exception:
        return str(value)

    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def estimate_tokens(text):
    """Rough token estimate: ~1 token per 4 characters."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_chat_tokens():
    """
    Estimate total tokens consumed by the current chat including the system
    prompt. Used for context-window progress display.
    """
    from core.chat_manager import get_current_chat
    chat = get_current_chat()

    total = estimate_tokens(config.SYSTEM_PROMPT)

    if chat is None:
        return total

    for message in chat["messages"]:
        total += estimate_tokens(message.get("content", ""))
        total += 4  # per-message overhead

    return total


def get_context_status():
    """
    Return a dict describing how much of the model's context window is used.

        {
            "used":      int,
            "limit":     int | None,
            "remaining": int | None,
            "percent":   float | None
        }
    """
    from core.model_manager import get_model_context_limit

    used = estimate_chat_tokens()
    limit = get_model_context_limit()

    if not limit:
        return {"used": used, "limit": None, "remaining": None, "percent": None}

    limit = int(limit)
    remaining = max(0, limit - used)
    percent = (used / limit) * 100

    return {
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "percent": percent
    }


def usage_warning(percent):
    """Return a Rich-markup string indicating context pressure level."""
    if percent is None:
        return ""
    if percent >= 95:
        return "[bold red]CRITICAL[/bold red]"
    if percent >= 85:
        return "[red]HIGH[/red]"
    if percent >= 70:
        return "[yellow]WARNING[/yellow]"
    return "[green]OK[/green]"
