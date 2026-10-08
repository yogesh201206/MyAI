"""
core/edit_manager.py — Safe code editing lifecycle for Phase 9.

Responsibilities:
  - Generate structured edit proposals via the model
  - Validate proposals (file boundaries, protected files, content match, overlaps)
  - Build pending edit state in config.pending_edit
  - Apply edits atomically with pre-write backup
  - Refresh the Phase 8 project index after successful apply
  - Undo: restore from backup
  - Show edit history (/changes)

NO file is ever written without explicit user confirmation via /apply.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from typing import Dict, List, Optional, Tuple

import config
from core.backup_manager import (
    STATUS_APPLIED,
    STATUS_DISCARDED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_UNDONE,
    create_backup_session,
    get_last_applied_session,
    get_session_files,
    get_session_history,
    init_edit_db,
    record_session,
    restore_from_backup,
    sha256_file,
    update_session_status,
)
from core.diff_manager import (
    apply_replacement,
    check_overlap,
    diff_stats,
    generate_diff,
    render_diff_rich,
    validate_syntax,
)
from core.project_index import (
    is_safe_boundary,
    is_sensitive_file,
    MAX_FILE_SIZE_BYTES,
)

from ui.console import console

# ------------------------------------------------------------------
# PROTECTED FILE PATTERNS
# ------------------------------------------------------------------

_PROTECTED_NAMES = {
    ".env", ".env.local", ".env.development", ".env.production",
    ".env.test", ".env.staging",
    "id_rsa", "id_ed25519", "id_dsa", "id_ecdsa",
    "credentials.json", "auth.json", "token.json",
    "auth-token", "jwt.key",
}

_PROTECTED_PATTERNS = [
    r"^\.env(\..+)?$",      # .env, .env.local, etc.
    r".*\.pem$",
    r".*\.key$",
    r".*\.p12$",
    r".*\.pfx$",
    r".*\.keystore$",
    r"^credentials.*",
    r"^secrets.*",
    r"^token.*",
    r"^auth-token.*",
]


def is_protected_file(filename: str) -> bool:
    """Return True if the file matches any protected pattern."""
    base = os.path.basename(filename).lower()
    if base in _PROTECTED_NAMES:
        return True
    for pat in _PROTECTED_PATTERNS:
        if re.match(pat, base, re.IGNORECASE):
            return True
    return False


# ------------------------------------------------------------------
# SYSTEM PROMPT FOR EDIT GENERATION
# ------------------------------------------------------------------

_EDIT_SYSTEM_PROMPT = """\
You are AIZEN Code Editor.

Your task is to produce MINIMAL, TARGETED code changes based on the user's instruction.

Rules:
- Preserve all unrelated code and formatting exactly.
- Do NOT refactor, rename, or restructure beyond what the instruction requires.
- For each file that needs modification output a JSON object.
- Return ONLY a JSON block — no prose, no markdown fences, no explanation outside the JSON.

Output format:
{
  "changes": [
    {
      "file": "<relative path from project root>",
      "reason": "<brief explanation of why this change is needed>",
      "start_line": <1-indexed line number where replacement starts>,
      "end_line": <1-indexed line number where replacement ends (inclusive)>,
      "old_text": "<exact current content of those lines, including newlines>",
      "new_text": "<replacement content with same indentation conventions>"
    }
  ]
}

Important:
- If no changes are needed, return: {"changes": []}
- start_line and end_line MUST be positive integers referencing the file as it currently exists.
- old_text MUST match the actual file content exactly (same whitespace).
- new_text must be non-empty unless the intent is to delete lines.
"""


# ------------------------------------------------------------------
# PARSE & VALIDATE MODEL RESPONSE
# ------------------------------------------------------------------

def _extract_json(raw: str) -> Optional[dict]:
    """
    Extract and parse a JSON block from raw model output.
    Handles both plain JSON and JSON wrapped in markdown code fences.
    """
    # Strip markdown fences if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1)

    # Try the whole text first, then progressively trim leading non-{ chars
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None


def _validate_change(change: dict, project_root: str) -> Tuple[bool, str]:
    """
    Validate a single change entry from the model response.

    Returns (valid, error_message).
    """
    required = ["file", "start_line", "end_line", "old_text", "new_text"]
    for field in required:
        if field not in change:
            return False, f"Missing required field '{field}' in change."

    rel_path = str(change["file"]).strip()
    if not rel_path:
        return False, "Change 'file' field is empty."

    # Resolve absolute path and verify boundary
    abs_path = os.path.realpath(os.path.join(project_root, rel_path))
    if not is_safe_boundary(project_root, abs_path):
        return False, f"Path traversal rejected: '{rel_path}' is outside project root."

    if not os.path.isfile(abs_path):
        return False, f"Target file does not exist: '{rel_path}'."

    if is_protected_file(abs_path):
        return False, f"Protected file rejected: '{rel_path}'. Use explicit /read and manual editing."

    if is_sensitive_file(abs_path):
        return False, f"Sensitive file rejected: '{rel_path}'."

    if os.path.getsize(abs_path) > MAX_FILE_SIZE_BYTES:
        return False, f"File too large to edit safely: '{rel_path}'."

    try:
        s = int(change["start_line"])
        e = int(change["end_line"])
    except (ValueError, TypeError):
        return False, "start_line and end_line must be integers."

    if s < 1 or e < s:
        return False, f"Invalid line range: {s}–{e}."

    if not change.get("new_text") and change.get("new_text") != "":
        return False, "new_text must not be None."

    return True, ""


# ------------------------------------------------------------------
# EDIT PROPOSAL GENERATION
# ------------------------------------------------------------------

def generate_edit_proposal(instruction: str) -> Tuple[bool, str]:
    """
    Generate a structured edit proposal using the current model.

    Steps:
      1. Verify project is active.
      2. Retrieve relevant project context.
      3. Send structured edit request (non-streaming).
      4. Parse and validate the model response.
      5. Populate config.pending_edit.

    Returns (success: bool, message: str).
    """
    if not config.project_mode or not config.active_project_path:
        return False, "No active project. Use /project <path> first."

    if config.pending_edit is not None:
        return False, (
            "A pending edit already exists.\n"
            "Use [cyan]/diff[/cyan] to review, [cyan]/apply[/cyan] to apply, "
            "or [cyan]/discard[/cyan] to discard it first."
        )

    if not instruction.strip():
        return False, "Edit instruction cannot be empty."

    project_root = config.active_project_path

    # Retrieve relevant project files
    try:
        from core.project_manager import get_active_index
        from core.project_search import retrieve_project_context
        idx = get_active_index()
        if not idx:
            return False, "Project index unavailable. Try /project refresh."
        ctx, _ = retrieve_project_context(idx, instruction, max_tokens=3000)
    except Exception as e:
        return False, f"Failed to retrieve project context: {e}"

    # Build messages for edit request
    messages = [
        {"role": "system", "content": _EDIT_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Project root: {project_root}\n\n"
            f"Edit instruction: {instruction}\n\n"
            + (f"Relevant project files:\n{ctx}" if ctx else "")
        )},
    ]

    # Non-streaming call even if streaming is globally ON
    from api.omniroute import send_chat
    try:
        result = send_chat(messages, config.current_model)
    except Exception as e:
        return False, f"Model request failed: {e}"

    raw = result.get("answer", "")
    parsed = _extract_json(raw)

    if parsed is None:
        return False, (
            "Model returned unparseable output. "
            "Could not extract a valid JSON edit block.\n"
            f"Raw output (truncated):\n{raw[:400]}"
        )

    changes = parsed.get("changes", [])
    if not changes:
        return True, "Model determined no changes are needed for this instruction."

    # Validate and enrich changes
    validated_changes = []
    file_hashes: Dict[str, str] = {}

    for i, ch in enumerate(changes):
        valid, err = _validate_change(ch, project_root)
        if not valid:
            return False, f"Change #{i+1} rejected: {err}"

        rel_path = ch["file"].strip()
        abs_path = os.path.realpath(os.path.join(project_root, rel_path))

        # Verify old_text is actually in the file at the specified line range
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                file_lines = f.readlines()
        except Exception as e:
            return False, f"Cannot read target file '{rel_path}': {e}"

        s = int(ch["start_line"]) - 1  # 0-indexed
        e = int(ch["end_line"])         # exclusive
        range_text = "".join(file_lines[s:e])

        old_text = ch.get("old_text", "")
        if old_text.strip() and range_text.strip() != old_text.strip():
            return False, (
                f"Change #{i+1}: old_text mismatch in '{rel_path}' "
                f"at lines {ch['start_line']}–{ch['end_line']}. "
                "File content may have changed — regenerate the proposal."
            )

        # File hash at proposal time
        if rel_path not in file_hashes:
            file_hashes[rel_path] = sha256_file(abs_path) or ""

        validated_changes.append({
            "file":          rel_path,
            "abs_path":      abs_path,
            "reason":        ch.get("reason", ""),
            "start_line":    int(ch["start_line"]),
            "end_line":      int(ch["end_line"]),
            "old_text":      old_text,
            "new_text":      ch.get("new_text", ""),
            "original_hash": file_hashes[rel_path],
        })

    # Overlap check within each file
    overlap_err = check_overlap(validated_changes)
    if overlap_err:
        return False, overlap_err

    # Build the pending edit
    session_id = str(uuid.uuid4())
    config.pending_edit = {
        "session_id":   session_id,
        "project_root": project_root,
        "instruction":  instruction,
        "changes":      validated_changes,
        "created_at":   time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status":       STATUS_PENDING,
    }

    # Persist session skeleton (will be updated on apply)
    record_session(
        session_id, project_root, instruction,
        [{"file": c["file"], "original_hash": c["original_hash"]} for c in validated_changes],
        status=STATUS_PENDING,
    )

    n = len(validated_changes)
    files_touched = list({c["file"] for c in validated_changes})
    return True, (
        f"[green]✓ Edit proposal ready.[/green] "
        f"{n} change(s) across {len(files_touched)} file(s).\n"
        "Run [cyan]/diff[/cyan] to preview · [cyan]/apply[/cyan] to apply · "
        "[cyan]/discard[/cyan] to discard."
    )


# ------------------------------------------------------------------
# DIFF PREVIEW
# ------------------------------------------------------------------

def show_pending_diff() -> bool:
    """
    Render a unified diff of the pending edit to the console.
    Returns True if there is a pending edit, False otherwise.
    """
    from rich.panel import Panel

    if config.pending_edit is None:
        console.print("[yellow]No pending edit. Use [cyan]/edit <instruction>[/cyan] to create one.[/yellow]")
        return False

    changes = config.pending_edit["changes"]
    total_added = 0
    total_removed = 0

    for ch in changes:
        abs_path = ch["abs_path"]
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                original = f.read()
        except Exception:
            console.print(f"[red]Cannot read {ch['file']}[/red]")
            continue

        # Build proposed content
        ok, proposed, err = apply_replacement(
            original,
            ch["old_text"],
            ch["new_text"],
            ch["start_line"],
            ch["end_line"],
        )
        if not ok:
            console.print(f"[red]Cannot generate diff for {ch['file']}: {err}[/red]")
            continue

        diff = generate_diff(
            original, proposed,
            from_label=f"a/{ch['file']}",
            to_label=f"b/{ch['file']}",
        )

        added, removed = diff_stats(diff)
        total_added += added
        total_removed += removed

        console.print(f"\n[bold]── {ch['file']} ──[/bold]")
        if ch.get("reason"):
            console.print(f"[dim italic]  Reason: {ch['reason']}[/dim italic]")
        render_diff_rich(diff, console)

    console.print(
        f"\n[cyan]Summary:[/cyan] "
        f"[green]+{total_added} added[/green]  [red]-{total_removed} removed[/red]  "
        f"across {len(changes)} change(s) in "
        f"{len({c['file'] for c in changes})} file(s)."
    )
    return True


# ------------------------------------------------------------------
# APPLY
# ------------------------------------------------------------------

def apply_pending_edit(confirmed: bool) -> Tuple[bool, str]:
    """
    Apply the pending edit to disk.

    confirmed=True means the user has already approved the prompt.
    Returns (success, message).
    """
    if config.pending_edit is None:
        return False, "No pending edit to apply."

    session_id   = config.pending_edit["session_id"]
    project_root = config.pending_edit["project_root"]
    instruction  = config.pending_edit["instruction"]
    changes      = config.pending_edit["changes"]

    if not confirmed:
        return False, "Apply cancelled."

    # Ensure session row exists (idempotent — covers cases where the caller
    # set config.pending_edit directly without going through generate_edit_proposal)
    record_session(
        session_id, project_root, instruction,
        [{"file": c["file"], "original_hash": c.get("original_hash", "")} for c in changes],
        status=STATUS_PENDING,
    )

    # --- Pre-apply validation: hash check ---
    for ch in changes:
        current_hash = sha256_file(ch["abs_path"])
        if current_hash and ch["original_hash"] and current_hash != ch["original_hash"]:
            return False, (
                f"File '{ch['file']}' has changed since the proposal was generated. "
                "Run [cyan]/discard[/cyan] then [cyan]/edit[/cyan] again to regenerate."
            )

    # --- Backup ---
    file_pairs = [(ch["file"], ch["abs_path"]) for ch in changes]
    bk_ok, bk_msg, backup_dir = create_backup_session(
        session_id, project_root, instruction, file_pairs
    )
    if not bk_ok:
        return False, f"Backup failed — aborting apply. {bk_msg}"

    # --- Apply changes file-by-file, atomically ---
    applied_files: List[str] = []
    rollback_needed = False
    error_msg = ""
    file_updates = []

    # Sort changes by file then descending start_line to avoid line-shift issues
    sorted_changes = sorted(changes, key=lambda c: (c["file"], -c["start_line"]))
    # Group by file
    from itertools import groupby
    from operator import itemgetter

    file_map: Dict[str, List[dict]] = {}
    for ch in sorted_changes:
        file_map.setdefault(ch["file"], []).append(ch)

    new_contents: Dict[str, str] = {}

    for rel_path, chs in file_map.items():
        abs_path = chs[0]["abs_path"]
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            error_msg = f"Cannot read '{rel_path}': {e}"
            rollback_needed = True
            break

        # Apply all changes for this file in descending line-number order
        for ch in sorted(chs, key=lambda x: -x["start_line"]):
            ok, content, err = apply_replacement(
                content, ch["old_text"], ch["new_text"],
                ch["start_line"], ch["end_line"],
            )
            if not ok:
                error_msg = f"Apply failed for '{rel_path}': {err}"
                rollback_needed = True
                break

        if rollback_needed:
            break

        # Syntax validation
        _, ext = os.path.splitext(rel_path)
        syn_ok, syn_err = validate_syntax(abs_path, content, ext)
        if not syn_ok:
            error_msg = f"Syntax validation failed for '{rel_path}': {syn_err}"
            rollback_needed = True
            break

        new_contents[rel_path] = content

    if not rollback_needed:
        # Atomic file writes
        for rel_path, content in new_contents.items():
            abs_path = file_map[rel_path][0]["abs_path"]
            dir_name = os.path.dirname(abs_path)
            try:
                stat_before = os.stat(abs_path)
                fd, tmp_path = tempfile.mkstemp(dir=dir_name)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(content)
                        f.flush()
                        os.fsync(f.fileno())
                    # Preserve permissions
                    try:
                        os.chmod(tmp_path, stat.S_IMODE(stat_before.st_mode))
                    except Exception:
                        pass
                    os.replace(tmp_path, abs_path)
                    applied_files.append(rel_path)
                except Exception as e:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
                    error_msg = f"Write failed for '{rel_path}': {e}"
                    rollback_needed = True
                    break
            except Exception as e:
                error_msg = f"Cannot access '{rel_path}': {e}"
                rollback_needed = True
                break

    if rollback_needed:
        # Attempt rollback of already-written files
        for rel_path in applied_files:
            abs_path = file_map[rel_path][0]["abs_path"]
            bk_dir_path = backup_dir or ""
            safe_name = rel_path.replace("/", "__").replace("\\", "__")
            src = os.path.join(bk_dir_path, safe_name) if bk_dir_path else ""
            if src and os.path.isfile(src):
                try:
                    shutil.copy2(src, abs_path)
                except Exception:
                    pass

        update_session_status(session_id, STATUS_FAILED)
        config.pending_edit["status"] = STATUS_FAILED
        return False, f"Apply failed and rolled back. {error_msg}"

    # --- Update backup dir in session record ---
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    for rel_path in applied_files:
        abs_path = file_map[rel_path][0]["abs_path"]
        new_hash = sha256_file(abs_path)
        orig_content_lines = 0
        new_lines = len(new_contents.get(rel_path, "").splitlines())
        for ch in file_map[rel_path]:
            added, removed = diff_stats(
                generate_diff(ch["old_text"], ch["new_text"],
                              from_label=ch["file"], to_label=ch["file"])
            )
        file_updates.append({
            "relative_path": rel_path,
            "new_hash":      new_hash,
            "lines_added":   added,
            "lines_removed": removed,
        })

    update_session_status(
        session_id, STATUS_APPLIED,
        applied_at=now,
        file_updates=file_updates,
    )

    # Update backup manifest with backup_dir
    try:
        from core.backup_manager import _db as bk_db
        with bk_db() as conn:
            conn.execute(
                "UPDATE edit_sessions SET backup_dir=? WHERE session_id=?",
                (backup_dir, session_id),
            )
    except Exception:
        pass

    # Refresh Phase 8 project index for modified files
    try:
        from core.project_manager import get_active_index
        idx = get_active_index()
        if idx:
            idx.check_and_update_stale()
    except Exception:
        pass

    config.pending_edit = None
    return True, (
        f"[green]✓ Applied {len(applied_files)} file change(s).[/green]\n"
        f"Backup: [dim]{backup_dir}[/dim]\n"
        "Run [cyan]/undo[/cyan] to revert if needed."
    )


# ------------------------------------------------------------------
# DISCARD
# ------------------------------------------------------------------

def discard_pending_edit() -> str:
    """Discard the current pending edit without modifying any files."""
    if config.pending_edit is None:
        return "No pending edit to discard."
    session_id = config.pending_edit["session_id"]
    update_session_status(session_id, STATUS_DISCARDED)
    config.pending_edit = None
    return "[yellow]Pending edit discarded.[/yellow]"


# ------------------------------------------------------------------
# UNDO
# ------------------------------------------------------------------

def undo_last_edit(confirmed: bool) -> Tuple[bool, str]:
    """
    Undo the most recently applied edit for the active project.

    Returns (success, message).
    """
    if not config.active_project_path:
        return False, "No active project."

    session = get_last_applied_session(config.active_project_path)
    if not session:
        return False, "No applied edits to undo for this project."

    if not confirmed:
        return False, "Undo cancelled."

    session_id = session["session_id"]
    ok, msg = restore_from_backup(session_id, config.active_project_path)

    if ok:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        update_session_status(session_id, STATUS_UNDONE, undone_at=now)
        # Refresh project index
        try:
            from core.project_manager import get_active_index
            idx = get_active_index()
            if idx:
                idx.check_and_update_stale()
        except Exception:
            pass
        return True, f"[green]✓ Undo successful.[/green] {msg}"

    return False, f"[red]Undo failed:[/red] {msg}"


def get_undo_preview() -> Optional[dict]:
    """Return metadata for the most recent applied session (for user confirmation)."""
    if not config.active_project_path:
        return None
    return get_last_applied_session(config.active_project_path)


# ------------------------------------------------------------------
# CHANGES HISTORY
# ------------------------------------------------------------------

def get_changes_history() -> List[dict]:
    """Return edit history for the active project."""
    if not config.active_project_path:
        return []
    return get_session_history(config.active_project_path)


# ------------------------------------------------------------------
# MISSING STAT IMPORT FIX
# ------------------------------------------------------------------

import stat
