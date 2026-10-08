"""
core/command_safety.py — Command safety classification for Phase 10.

Every command goes through this module before any execution is proposed.
It is the single source of truth for safety levels.

Safety Levels (ordered by risk):
    READ_ONLY   — no side effects, safe to inspect
    SAFE_BUILD  — build/test only; modifies derived artifacts, not source
    WRITE       — modifies project or system state reversibly
    DANGEROUS   — may permanently discard data or alter system
    BLOCKED     — must never execute regardless of user approval

Design:
    - Matches against command name AND arguments.
    - Uses shlex.split for safe parsing; falls back to naive split.
    - Returns a SafetyResult with level, reason, and affected_paths hints.
    - Is deterministic and has no side-effects (pure functions).
"""

import re
import shlex
from dataclasses import dataclass, field
from typing import List, Optional


# ------------------------------------------------------------------
# LEVELS
# ------------------------------------------------------------------

READ_ONLY   = "READ_ONLY"
SAFE_BUILD  = "SAFE_BUILD"
WRITE       = "WRITE"
DANGEROUS   = "DANGEROUS"
BLOCKED     = "BLOCKED"

LEVEL_ORDER = [READ_ONLY, SAFE_BUILD, WRITE, DANGEROUS, BLOCKED]


@dataclass
class SafetyResult:
    level: str
    reason: str
    affected_paths: List[str] = field(default_factory=list)
    needs_strong_confirm: bool = False   # True for DANGEROUS / BLOCKED
    block_message: str = ""              # Non-empty for BLOCKED


# ------------------------------------------------------------------
# BLOCKED PATTERNS — hard-stop regardless of args
# ------------------------------------------------------------------

_BLOCKED_COMMANDS = frozenset({
    "mkfs", "fdisk", "parted", "wipefs", "shred",
    "shutdown", "reboot", "poweroff", "halt", "init",
    "dd",            # covered separately by arg inspection
})

_BLOCKED_PATTERNS: List[tuple] = [
    # rm -rf / or rm -rf ~
    (r"^rm\b.*-[a-zA-Z]*r[a-zA-Z]*f\b.*(/|~|/home|/root|/boot|/etc|/var|/usr|/sys|/proc).*", "Recursive forced deletion of critical system paths"),
    # dd to disk devices
    (r"^dd\b.*of=/dev/(sd|hd|nvme|vd|mmcblk)", "Direct disk write via dd"),
    # fork bomb
    (r":\s*\(\s*\)\s*\{", "Fork bomb pattern detected"),
    # curl/wget piped to shell
    (r"(curl|wget)\b.*(http[s]?://).*\|\s*(sh|bash|zsh|python|ruby|perl|node)", "Remote code execution via pipe"),
    # key/credential extraction
    (r"cat\b.*/(\.ssh|\.gnupg|\.aws|\.config/gcloud)/(id_rsa|id_ed25519|credentials|keyfile)", "SSH/credential file read attempt"),
    # browser credential access
    (r"(sqlite3|cat)\b.*/Library/Application Support/Google/Chrome", "Browser credential access"),
    # /etc/passwd /etc/shadow
    (r"cat\b.*/etc/(shadow|passwd|sudoers)", "System credential file read"),
    # python -c exec with base64 decode
    (r"python[23]?\s+-c\b.*exec\(.*decode", "Obfuscated code execution pattern"),
    # mkfs variants
    (r"mkfs\.", "Disk filesystem creation"),
]

# ------------------------------------------------------------------
# DANGEROUS PATTERNS
# ------------------------------------------------------------------

_DANGEROUS_COMMANDS = frozenset({
    "chmod", "chown", "chgrp",
    "kill", "pkill", "killall",
    "systemctl", "service",
    "sudo",
    "su",
    "passwd",
    "visudo",
    "crontab",
    "at",
})

_DANGEROUS_GIT_SUBCOMMANDS = frozenset({
    "reset", "clean", "push", "force-push",
})

_DANGEROUS_PATTERNS: List[tuple] = [
    (r"^git\b.*\breset\b.*--hard\b",        "Permanently discards uncommitted changes"),
    (r"^git\b.*\bclean\b.*-[a-zA-Z]*f",     "Permanently removes untracked files"),
    (r"^git\b.*\bpush\b.*--force",          "Force push may overwrite remote history"),
    (r"^rm\b",                               "Removes files from disk"),
    (r"^rmdir\b",                            "Removes directories"),
    (r"^sudo\b",                             "Runs with elevated privileges"),
    (r"^su\b",                               "Switches user account"),
    (r"^systemctl\b",                        "Controls system services"),
    (r"^service\b",                          "Controls system services"),
    (r"^kill\b",                             "Sends signal to process"),
    (r"^pkill\b",                            "Kills processes by name"),
    (r"^killall\b",                          "Kills all named processes"),
    (r"^chmod\b",                            "Modifies file permissions"),
    (r"^chown\b",                            "Modifies file ownership"),
    (r"(ssh|scp|nc|netcat|ncat)\b",         "Network/remote access command"),
    (r"^curl\b",                             "Network data transfer"),
    (r"^wget\b",                             "Network data download"),
]

# ------------------------------------------------------------------
# WRITE PATTERNS
# ------------------------------------------------------------------

_WRITE_COMMANDS = frozenset({
    "touch", "mkdir", "mv", "cp",
    "tee", "truncate",
    "ln",
})

_WRITE_PATTERNS: List[tuple] = [
    (r"^npm\s+install\b",             ["package-lock.json", "node_modules/"]),
    (r"^yarn\s+(install|add)\b",      ["yarn.lock", "node_modules/"]),
    (r"^pnpm\s+(install|add)\b",      ["pnpm-lock.yaml", "node_modules/"]),
    (r"^pip\s+install\b",             ["site-packages/"]),
    (r"^pip3\s+install\b",            ["site-packages/"]),
    (r"^mvn\s+dependency",            ["~/.m2/"]),
    (r"^gradle\b.*dependencies",      ["~/.gradle/"]),
    (r"^apt(-get)?\s+install\b",      ["/usr/", "/etc/apt/"]),
    (r"^apt(-get)?\s+remove\b",       ["/usr/"]),
    (r"^dnf\s+install\b",             ["/usr/"]),
    (r"^brew\s+install\b",            ["/usr/local/", "/opt/homebrew/"]),
    (r"^git\s+add\b",                 ["staging area"]),
    (r"^git\s+commit\b",              ["git history"]),
    (r"^git\s+checkout\b",            ["working tree"]),
    (r"^git\s+switch\b",              ["working branch"]),
    (r"^git\s+merge\b",               ["git history"]),
    (r"^git\s+rebase\b",              ["git history"]),
    (r"^git\s+stash\b",               ["stash"]),
    (r"^git\s+tag\b",                 ["git tags"]),
    (r"^touch\b",                     ["file timestamps/create"]),
    (r"^mkdir\b",                     ["directories"]),
    (r"^mv\b",                        ["file location"]),
    (r"^cp\b",                        ["file copies"]),
    (r"^tee\b",                       ["file contents"]),
    (r">\s*\S+",                      ["output redirect target"]),  # redirection
    (r">>\s*\S+",                     ["output redirect target"]),
]

# ------------------------------------------------------------------
# SAFE_BUILD PATTERNS
# ------------------------------------------------------------------

_SAFE_BUILD_PATTERNS: List[tuple] = [
    r"^mvn\s+(clean\s+)?(test|verify|package|compile|install|spring-boot:run|spring-boot:build-image)\b",
    r"^\./mvnw\s+(clean\s+)?(test|verify|package|compile|install|spring-boot:run|spring-boot:build-image)\b",
    r"^gradle\b(?!.*dependencies)",
    r"^\./gradlew\b",
    r"^npm\s+(test|run\s+build|run\s+test|start|run\s+dev|run\s+lint)\b",
    r"^yarn\s+(test|build|start|lint)\b",
    r"^pnpm\s+(test|build|start)\b",
    r"^pytest\b",
    r"^python[23]?\s+-m\s+(pytest|unittest)\b",
    r"^python3?\s+-m\s+unittest\b",
    r"^cargo\s+(test|build|run|check)\b",
    r"^go\s+(test|build|run)\b",
    r"^make\b",
    r"^cmake\b",
    r"^rake\b",
    r"^mix\s+(test|compile)\b",
    r"^dotnet\s+(test|build|run)\b",
    r"^composer\s+(install|update|test)\b",
    r"^php\s+artisan\b",
    r"^ruby\b",
    r"^bundle\s+(exec|install)\b",
    r"^tsc\b",
    r"^ng\s+(test|build|serve|lint)\b",
]

# ------------------------------------------------------------------
# READ_ONLY PATTERNS
# ------------------------------------------------------------------

_READ_ONLY_COMMANDS = frozenset({
    "pwd", "echo", "ls", "la", "ll", "dir",
    "tree", "cat", "less", "more", "head", "tail",
    "grep", "rg", "ripgrep", "ag", "ack",
    "find", "locate", "which", "whereis", "type",
    "wc", "sort", "uniq", "cut", "awk", "sed",
    "diff", "comm",
    "file", "stat", "du", "df",
    "ps", "top", "htop", "uptime", "uname",
    "hostname", "whoami", "id", "groups",
    "date", "cal",
    "env", "printenv", "export",
    "man", "info", "help",
    "python", "python3",    # covered below — only when -c/read
    "node",
})

_READ_ONLY_GIT = frozenset({
    "status", "log", "diff", "show",
    "branch", "tag", "remote",
    "fetch",       # fetch is read-only locally
    "describe",
    "shortlog",
    "reflog",
    "stash list",
    "blame",
    "ls-files",
    "ls-tree",
    "rev-parse",
    "config --list",
    "config --get",
    "submodule status",
})

_NETWORK_ELEVATED = frozenset({
    "curl", "wget", "ssh", "scp", "sftp",
    "nc", "netcat", "ncat",
    "telnet", "ftp",
    "rsync",
    "nmap",
})

# Env vars that may contain secrets — redact from logs
_SECRET_ENV_PATTERNS = re.compile(
    r"(TOKEN|KEY|SECRET|PASSWORD|AUTH|CREDENTIAL|PASS|APIKEY|API_KEY|PWD|PRIVATE)",
    re.IGNORECASE,
)


# ------------------------------------------------------------------
# PUBLIC API
# ------------------------------------------------------------------

def parse_command(raw: str) -> List[str]:
    """
    Safely split a raw command string into tokens using shlex.
    Falls back to simple whitespace split on error.
    """
    try:
        return shlex.split(raw.strip())
    except ValueError:
        return raw.strip().split()


def classify(raw_command: str) -> SafetyResult:
    """
    Classify a raw command string and return a SafetyResult.

    Inspection order:
        1. BLOCKED patterns (abort immediately)
        2. DANGEROUS patterns
        3. WRITE patterns
        4. SAFE_BUILD patterns
        5. READ_ONLY patterns
        6. Default → WRITE (conservative fallback)
    """
    raw = raw_command.strip()
    if not raw:
        return SafetyResult(READ_ONLY, "Empty command")

    tokens = parse_command(raw)
    base_cmd = tokens[0].lstrip("./") if tokens else ""
    base_cmd_lower = base_cmd.lower()

    # ── 1. BLOCKED ────────────────────────────────────────────────
    for pattern, reason in _BLOCKED_PATTERNS:
        if re.search(pattern, raw, re.IGNORECASE | re.DOTALL):
            return SafetyResult(
                BLOCKED, reason,
                needs_strong_confirm=True,
                block_message=f"Command blocked by AIZEN safety policy.\n{reason}."
            )

    if base_cmd_lower in _BLOCKED_COMMANDS:
        return SafetyResult(
            BLOCKED,
            f"'{base_cmd}' is unconditionally blocked.",
            needs_strong_confirm=True,
            block_message=f"Command blocked by AIZEN safety policy.\n'{base_cmd}' is a destructive system command that cannot be executed through AIZEN.",
        )

    # Special: dd — inspect args for of= to disk
    if base_cmd_lower == "dd":
        for tok in tokens:
            if tok.startswith("of=/dev/"):
                return SafetyResult(
                    BLOCKED, "Direct disk write via dd",
                    needs_strong_confirm=True,
                    block_message="Command blocked: dd with of=/dev/* is a destructive disk operation.",
                )

    # ── 2. DANGEROUS ──────────────────────────────────────────────
    for pattern, reason in _DANGEROUS_PATTERNS:
        if re.search(pattern, raw, re.IGNORECASE):
            return SafetyResult(
                DANGEROUS, reason,
                needs_strong_confirm=True,
            )

    if base_cmd_lower in _DANGEROUS_COMMANDS:
        return SafetyResult(
            DANGEROUS, f"'{base_cmd}' requires elevated privileges or has destructive potential",
            needs_strong_confirm=True,
        )

    # ── 3. WRITE ──────────────────────────────────────────────────
    for pattern, affected in _WRITE_PATTERNS:
        if re.search(pattern, raw, re.IGNORECASE):
            if isinstance(affected, list):
                return SafetyResult(WRITE, f"Modifies: {', '.join(affected)}", affected_paths=affected)
            return SafetyResult(WRITE, "Modifies project or system state")

    if base_cmd_lower in _WRITE_COMMANDS:
        return SafetyResult(WRITE, f"'{base_cmd}' modifies the filesystem")

    # git with write subcommand
    if base_cmd_lower == "git" and len(tokens) > 1:
        sub = tokens[1].lower()
        if sub in _DANGEROUS_GIT_SUBCOMMANDS:
            # Already caught by patterns above — double safety
            return SafetyResult(
                DANGEROUS, f"git {sub} may have destructive effects",
                needs_strong_confirm=True,
            )
        if sub not in _READ_ONLY_GIT:
            # Unknown git subcommand — conservative WRITE
            return SafetyResult(WRITE, f"git {sub} may modify repository state")

    # ── 4. SAFE_BUILD ─────────────────────────────────────────────
    for pattern in _SAFE_BUILD_PATTERNS:
        if re.search(pattern, raw, re.IGNORECASE):
            return SafetyResult(SAFE_BUILD, "Build/test command — modifies only derived artifacts")

    # ── 5. READ_ONLY ──────────────────────────────────────────────
    # git read-only subcommands
    if base_cmd_lower == "git" and len(tokens) > 1:
        sub = tokens[1].lower()
        if sub == "branch":
            rest = [t for t in tokens[2:] if not t.startswith("-") or t in ("-d", "-D", "-m", "-M", "-c", "-C")]
            if rest:
                if any(t in ("-d", "-D") for t in tokens[2:]):
                    return SafetyResult(DANGEROUS, "git branch deletion is dangerous", needs_strong_confirm=True)
                return SafetyResult(WRITE, "git branch creates or modifies branches")
            return SafetyResult(READ_ONLY, "git branch is read-only")
        if sub == "tag":
            rest = [t for t in tokens[2:] if not t.startswith("-") or t in ("-d", "-D")]
            if rest:
                if any(t in ("-d", "-D") for t in tokens[2:]):
                    return SafetyResult(DANGEROUS, "git tag deletion is dangerous", needs_strong_confirm=True)
                return SafetyResult(WRITE, "git tag creates or modifies tags")
            return SafetyResult(READ_ONLY, "git tag is read-only")

        if sub in _READ_ONLY_GIT or f"{sub} {' '.join(tokens[2:3])}".strip() in _READ_ONLY_GIT:
            return SafetyResult(READ_ONLY, f"git {sub} is read-only")

    if base_cmd_lower in _READ_ONLY_COMMANDS:
        # env/printenv — mark write-ish (exposes secrets)
        if base_cmd_lower in ("env", "printenv"):
            return SafetyResult(WRITE, "Outputs environment variables which may contain secrets")
        return SafetyResult(READ_ONLY, f"'{base_cmd}' is a read-only inspection command")

    # Network commands — elevate to DANGEROUS even if not already caught
    if base_cmd_lower in _NETWORK_ELEVATED:
        return SafetyResult(DANGEROUS, f"'{base_cmd}' is a network command requiring scrutiny", needs_strong_confirm=True)

    # ── 6. CONSERVATIVE FALLBACK ─────────────────────────────────
    return SafetyResult(WRITE, f"'{base_cmd}' has unknown effects — classified conservatively")


def is_outside_project(cwd: str, project_root: Optional[str]) -> bool:
    """Return True if cwd is outside the active project root."""
    if not project_root:
        return False
    import os
    cwd_real = os.path.realpath(cwd)
    root_real = os.path.realpath(project_root)
    return not cwd_real.startswith(root_real)


def sanitize_for_log(command: str) -> str:
    """
    Return a sanitized version of the command for storage.
    Replaces likely secret values with [REDACTED].
    """
    # Regex replacement for Authorization headers or Bearer tokens
    sanitized = re.sub(
        r"(Bearer\s+)[A-Za-z0-9_\-\.]+",
        r"\1[REDACTED]",
        command,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"((?:token|key|secret|password|auth|credential|apikey|api_key|pwd|private)[=:\s]+)[^\s'\"]+",
        r"\1[REDACTED]",
        sanitized,
        flags=re.IGNORECASE,
    )
    tokens = parse_command(sanitized)
    result_tokens = []
    redact_next = False
    for tok in tokens:
        if redact_next:
            result_tokens.append("[REDACTED]")
            redact_next = False
            continue
        if "=" in tok:
            key, _, val = tok.partition("=")
            if _SECRET_ENV_PATTERNS.search(key):
                result_tokens.append(f"{key}=[REDACTED]")
                continue
        if _SECRET_ENV_PATTERNS.search(tok) and tok.startswith("-"):
            redact_next = True
        result_tokens.append(tok)
    return shlex.join(result_tokens)


def level_color(level: str) -> str:
    """Return a Rich color string for a safety level."""
    return {
        READ_ONLY:  "green",
        SAFE_BUILD: "cyan",
        WRITE:      "yellow",
        DANGEROUS:  "bold red",
        BLOCKED:    "red on white",
    }.get(level, "white")


def level_icon(level: str) -> str:
    return {
        READ_ONLY:  "🟢",
        SAFE_BUILD: "🔵",
        WRITE:      "🟡",
        DANGEROUS:  "🔴",
        BLOCKED:    "⛔",
    }.get(level, "⚪")
