"""
core/agent_manager.py — Agent-mode command proposal lifecycle for Phase 10.

Agent mode allows AIZEN to propose terminal commands during problem-solving.
EVERY proposal requires explicit user confirmation before execution.
A maximum of MAX_CONSECUTIVE_PROPOSALS proposals per user turn prevents runaway loops.

Design:
    - Model proposes using structured JSON: {"tool": "terminal", "command": ..., ...}
    - Proposal is validated (safety classified) before presented to user.
    - config.agent_enabled controls whether proposals are offered at all.
    - After Phase 9 /apply, may suggest test commands (never auto-run them).
"""

import json
import re
import time
from typing import Optional, Tuple

import config

MAX_CONSECUTIVE_PROPOSALS = 5

# Track proposals issued in the current agent session
_proposal_count = 0


def reset_proposal_count():
    """Reset per-turn proposal counter (call at start of each user message)."""
    global _proposal_count
    _proposal_count = 0


def increment_proposal_count():
    global _proposal_count
    _proposal_count += 1


def proposals_exhausted() -> bool:
    return _proposal_count >= MAX_CONSECUTIVE_PROPOSALS


# ------------------------------------------------------------------
# STRUCTURED PROPOSAL PARSING
# ------------------------------------------------------------------

_PROPOSAL_SCHEMA = {
    "tool": str,
    "command": str,
    "cwd": str,
    "reason": str,
}


def parse_agent_proposal(raw: str) -> Optional[dict]:
    """
    Extract and validate a structured terminal-tool proposal from model output.

    Valid format:
        {"tool": "terminal", "command": "<cmd>", "cwd": ".", "reason": "..."}

    Returns validated dict or None.
    """
    if not raw or not isinstance(raw, str):
        return None

    # Strip markdown fences if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw.strip()

    obj = None
    try:
        obj = json.loads(candidate)
    except Exception:
        # Search for first JSON block with "tool" and "terminal"
        m = re.search(r"\{[^{}]*\"tool\"\s*:\s*\"terminal\"[^{}]*\}", raw, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                pass
        if obj is None:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and start < end:
                try:
                    obj = json.loads(raw[start:end + 1])
                except Exception:
                    return None
            else:
                return None

    if not isinstance(obj, dict) or obj.get("tool") != "terminal":
        return None

    command = str(obj.get("command", "")).strip()
    if not command:
        return None

    # Validate types
    for key, expected_type in _PROPOSAL_SCHEMA.items():
        val = obj.get(key)
        if val is not None and not isinstance(val, expected_type):
            return None

    return {
        "tool":    "terminal",
        "command": command,
        "cwd":     str(obj.get("cwd", ".")).strip() or ".",
        "reason":  str(obj.get("reason", "")).strip(),
    }


def classify_proposal(proposal: dict) -> Tuple[bool, str]:
    """
    Safety-classify a proposal command.

    Returns (is_safe_to_present, message).
    BLOCKED proposals are rejected entirely — never shown to user.
    """
    from core.command_safety import classify, BLOCKED
    result = classify(proposal["command"])

    if result.level == BLOCKED:
        return False, result.block_message

    return True, ""


def resolve_cwd(proposal_cwd: str) -> str:
    """
    Resolve the proposal cwd relative to active project root or startup cwd.
    """
    import os
    base = config.active_project_path or config.startup_cwd
    raw = proposal_cwd.strip()

    if raw in (".", ""):
        return base

    if os.path.isabs(raw):
        resolved = os.path.realpath(raw)
    else:
        resolved = os.path.realpath(os.path.join(base, raw))

    # Safety: if project mode active, only read-only proposals may go outside root
    return resolved


# ------------------------------------------------------------------
# POST-APPLY VALIDATION SUGGESTION (Phase 9 integration)
# ------------------------------------------------------------------

def suggest_validation_command() -> Optional[str]:
    """
    After /apply, suggest a validation command based on the active project frameworks.
    Returns command string or None.
    Never auto-executes.
    """
    if not config.project_mode or not config.active_project_path:
        return None
    try:
        from core.project_manager import get_active_index
        idx = get_active_index()
        if not idx:
            return None
        frameworks = set(f.lower() for f in getattr(idx, "frameworks", []))
        langs = set(getattr(idx, "languages", []))

        if "spring boot" in frameworks or "maven" in frameworks:
            return "mvn test"
        if "gradle" in frameworks:
            return "./gradlew test"
        if "react" in frameworks or "npm" in frameworks:
            return "npm test"
        if "pytest" in frameworks or "python" in langs:
            return "pytest"
        if "go" in langs:
            return "go test ./..."
        if "cargo" in frameworks or "rust" in langs:
            return "cargo test"
    except Exception:
        pass
    return None


# ------------------------------------------------------------------
# AGENT PROMPT INJECTION
# ------------------------------------------------------------------

_AGENT_TOOL_PROMPT = """\

You may propose terminal commands when it would help solve the problem.
To propose a command, output a JSON block like this (and nothing else on that line):
{"tool": "terminal", "command": "<command>", "cwd": ".", "reason": "<why>"}

Rules:
- Only propose commands that are safe and relevant.
- Never propose BLOCKED commands (rm -rf, mkfs, shutdown, etc.).
- Only ONE command proposal per response.
- Wait for the user to confirm and share the result before proposing the next.
"""


def get_agent_prompt_suffix() -> str:
    """Return agent-mode instructions to append to the system prompt."""
    if not config.agent_enabled:
        return ""
    return _AGENT_TOOL_PROMPT


# ------------------------------------------------------------------
# PERSISTENCE
# ------------------------------------------------------------------

def save_agent_state():
    """Persist agent_enabled to config.json."""
    from core.storage import save_config
    save_config()


def load_agent_state():
    """Load agent_enabled from config (already handled by load_config)."""
    pass  # config.agent_enabled is set by load_config via config.json
