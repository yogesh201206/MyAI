"""
core/project_manager.py — High-level project subsystem manager for AIZEN AI.

Coordinates project activation, deactivation, status reporting, lazy refresh,
file reading with boundary safety, tree generation, and prompt context building.
"""

import os
import time
from typing import Dict, List, Optional, Tuple

import config
from core.project_index import (
    ProjectIndex,
    is_binary_file,
    is_safe_boundary,
    MAX_FILE_SIZE_BYTES,
)
from core.project_search import (
    find_in_project,
    retrieve_project_context,
)
from core.storage import save_config

_active_index: Optional[ProjectIndex] = None


def get_active_index() -> Optional[ProjectIndex]:
    """Retrieve the current ProjectIndex instance, lazily restoring if necessary."""
    global _active_index
    if _active_index is None and config.active_project_path:
        if os.path.isdir(config.active_project_path):
            try:
                idx = ProjectIndex(config.active_project_path)
                idx.scan()
                _active_index = idx
            except Exception:
                _active_index = None
    return _active_index


def activate_project(path_input: str) -> Tuple[bool, str]:
    """
    Activate a software project by path.
    Supports '.' for current working directory or explicit relative/absolute paths.
    """
    global _active_index

    clean_path = path_input.strip() if path_input else "."
    if clean_path == ".":
        target_dir = os.path.realpath(os.getcwd())
    else:
        target_dir = os.path.realpath(os.path.abspath(os.path.expanduser(clean_path)))

    if not os.path.exists(target_dir):
        return False, f"Directory does not exist: {target_dir}"

    if not os.path.isdir(target_dir):
        return False, f"Path is not a directory: {target_dir}"

    if not os.access(target_dir, os.R_OK):
        return False, f"Directory is not readable: {target_dir}"

    index = ProjectIndex(target_dir)
    res = index.scan()
    if "error" in res:
        return False, res["error"]

    _active_index = index
    config.project_mode = True
    config.active_project_path = target_dir
    save_config()

    lang_str = ", ".join(res.get("languages", [])) or "None"
    frameworks_str = ", ".join(res.get("frameworks", [])) or "None"

    msg = (
        f"[green]Project '{index.project_name}' activated![/green]\n"
        f"Root: [cyan]{target_dir}[/cyan]\n"
        f"Indexed Files: [bold]{res['indexed_files']}[/bold] "
        f"(Ignored: {res['ignored_files']})\n"
        f"Languages: {lang_str}\n"
        f"Frameworks: {frameworks_str}"
    )
    return True, msg


def deactivate_project() -> str:
    """Disable project mode without deleting the index or project path."""
    config.project_mode = False
    save_config()
    return "Project mode disabled (OFF). Use [cyan]/project status[/cyan] or [cyan]/project .[/cyan] to reactivate."


def refresh_project() -> Tuple[bool, str]:
    """Force a fresh rescan of the active project index."""
    global _active_index
    idx = get_active_index()
    if not idx or not config.active_project_path:
        return False, "No active project to refresh. Use /project <path> to activate one."

    res = idx.scan()
    if "error" in res:
        return False, res["error"]

    return True, (
        f"[green]Project '{idx.project_name}' refreshed.[/green] "
        f"{res['indexed_files']} files indexed, {res['ignored_files']} ignored."
    )


def get_project_status() -> dict:
    """Return comprehensive status information for the active project."""
    idx = get_active_index()
    if not idx or not config.active_project_path:
        return {
            "mode": "OFF",
            "status": "INACTIVE",
            "project_name": "None",
            "root_path": "None",
            "indexed_files": 0,
            "supported_files": 0,
            "ignored_files": 0,
            "last_updated": 0.0,
            "languages": [],
            "frameworks": [],
        }

    return {
        "mode": "ON" if config.project_mode else "OFF",
        "status": idx.status,
        "project_name": idx.project_name,
        "root_path": idx.project_root,
        "indexed_files": len(idx.indexed_files),
        "supported_files": idx.total_supported_files,
        "ignored_files": idx.total_ignored_files,
        "last_updated": idx.last_updated,
        "languages": sorted(list(idx.detected_languages)),
        "frameworks": sorted(list(idx.detected_frameworks)),
    }


def restore_project_on_startup() -> Optional[str]:
    """Restore project mode on startup if path still exists; otherwise disable cleanly."""
    global _active_index
    if not config.active_project_path:
        return None

    path = config.active_project_path
    if os.path.isdir(path):
        try:
            idx = ProjectIndex(path)
            idx.scan()
            _active_index = idx
            return None
        except Exception as e:
            config.project_mode = False
            save_config()
            return f"Warning: Failed to restore project at {path}: {e}"
    else:
        # Project path no longer exists
        config.project_mode = False
        config.active_project_path = None
        save_config()
        return f"Warning: Previous project path '{path}' no longer exists. Project mode disabled."


def read_project_file(rel_path: str, line_range: Optional[str] = None) -> Tuple[bool, str]:
    """
    Read a project file safely with boundary enforcement, line numbering, and optional line ranges.
    Never executes or writes to the file.
    """
    idx = get_active_index()
    if not idx or not config.active_project_path:
        return False, "No active project. Use /project <path> to activate one."

    norm_rel = rel_path.strip().replace("\\", "/")
    full_path = os.path.realpath(os.path.join(idx.project_root, norm_rel))

    # Boundary check: ensure target does not escape project root
    if not is_safe_boundary(idx.project_root, full_path):
        return False, f"Access denied: Path '{norm_rel}' escapes project root."

    if not os.path.exists(full_path):
        return False, f"File not found: {norm_rel}"

    if not os.path.isfile(full_path):
        return False, f"Path is not a regular file: {norm_rel}"

    if os.path.getsize(full_path) > MAX_FILE_SIZE_BYTES:
        return False, f"File is too large to view directly (> 1 MB)."

    if is_binary_file(full_path):
        return False, f"Cannot view binary file '{norm_rel}'."

    try:
        lines = []
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(full_path, "r", encoding="latin-1") as f:
                lines = f.readlines()

        total_lines = len(lines)
        if total_lines == 0:
            return True, f"[dim]{norm_rel} is an empty file.[/dim]"

        start_line = 1
        end_line = total_lines
        has_custom_range = False

        if line_range:
            parts = line_range.strip().split("-")
            try:
                if len(parts) == 2:
                    start_line = max(1, int(parts[0]))
                    end_line = min(total_lines, int(parts[1]))
                    has_custom_range = True
                elif len(parts) == 1 and parts[0].isdigit():
                    start_line = max(1, int(parts[0]))
                    end_line = min(total_lines, start_line + 50)
                    has_custom_range = True
            except ValueError:
                pass

        # If file is large (> 120 lines) and no range specified, show first 120
        truncated_note = ""
        if not has_custom_range and total_lines > 120:
            end_line = 120
            truncated_note = f"\n[dim]Showing lines 1-120 of {total_lines}. Use /read {norm_rel} 121-240 to view more.[/dim]"

        rendered_lines = []
        for i in range(start_line, end_line + 1):
            line_content = lines[i - 1].rstrip()
            rendered_lines.append(f"{i:4d} | {line_content}")

        header = f"[bold cyan]{norm_rel}[/bold cyan] (Lines {start_line}-{end_line} of {total_lines}):\n"
        body = "\n".join(rendered_lines) + truncated_note
        return True, header + body

    except Exception as e:
        return False, f"Failed to read file: {e}"


def get_project_tree(max_depth: int = 3) -> str:
    """Generate a compact project tree representation."""
    idx = get_active_index()
    if not idx or not config.active_project_path:
        return "No active project. Use [cyan]/project <path>[/cyan] to activate one."
    return idx.generate_tree(max_depth=max_depth)


def search_project(query: str, limit: int = 20) -> List[dict]:
    """Execute multi-signal search across the active project."""
    idx = get_active_index()
    if not idx or not config.active_project_path:
        return []
    idx.check_and_update_stale()
    return find_in_project(idx, query, limit=limit)


def build_project_context(prompt: str) -> Tuple[str, List[dict]]:
    """
    Check if project mode is enabled, refresh stale files lazily,
    and retrieve relevant code snippets for the given prompt.
    """
    if not config.project_mode or not config.active_project_path:
        return "", []

    idx = get_active_index()
    if not idx:
        return "", []

    idx.check_and_update_stale()
    return retrieve_project_context(
        idx,
        prompt,
        max_tokens=config.DEFAULT_PROJECT_MAX_TOKENS
    )
