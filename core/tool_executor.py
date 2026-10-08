"""
core/tool_executor.py — Native tool execution engine for AIZEN.

Validates tool calls against ToolRegistry and executes them safely:
  - file_read: Read text with path boundary checks and truncation limits
  - file_write: Safe file writing within project directory
  - file_search: Regex/text pattern search across project files
  - list_files: Directory listing within project directory
  - run_command: Command execution respecting command_safety and approvals

Returns structured results:
  {
      "success": True,
      "tool": "file_read",
      "output": "...",
      "error": None
  }
"""

import os
import re
from typing import Any, Dict, List, Optional, Tuple

import config
from core.command_runner import run_foreground
from core.command_safety import BLOCKED, DANGEROUS, READ_ONLY, SAFE_BUILD, WRITE, classify, level_color, level_icon
from core.tool_registry import registry
from ui.console import console

MAX_READ_LINES = 1000
MAX_READ_BYTES = 64 * 1024       # 64 KB
MAX_SEARCH_RESULTS = 50
MAX_LIST_ENTRIES = 100

_IGNORE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".idea", ".vscode", ".mypy_cache", ".pytest_cache"
}


def _get_project_root() -> str:
    """Get active project directory or fall back to current working directory."""
    active = getattr(config, "active_project_dir", None)
    if active and os.path.isdir(active):
        return os.path.realpath(active)
    return os.path.realpath(os.getcwd())


def _resolve_and_check_boundary(rel_or_abs_path: str, must_exist: bool = False) -> Tuple[bool, str, Optional[str]]:
    """
    Resolve path and ensure it does not escape the project boundary.
    Returns: (is_valid: bool, resolved_path: str, error_message: Optional[str])
    """
    root = _get_project_root()
    cleaned = (rel_or_abs_path or "").strip().strip("'\"")
    if not cleaned:
        cleaned = "."

    if os.path.isabs(cleaned):
        target = os.path.abspath(cleaned)
    else:
        target = os.path.abspath(os.path.join(root, cleaned))

    real_target = os.path.realpath(target)
    real_root = os.path.realpath(root)

    # Check path boundary
    if real_target != real_root and not real_target.startswith(real_root + os.sep):
        return False, target, f"Path traversal rejected: '{cleaned}' escapes the allowed project directory ({root})."

    if must_exist and not os.path.exists(real_target):
        return False, real_target, f"File or directory does not exist: '{cleaned}'"

    return True, real_target, None


# ------------------------------------------------------------------
# TOOL IMPLEMENTATIONS
# ------------------------------------------------------------------

def _execute_file_read(args: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
    """Read a text file with line ranges and size limits."""
    path = args.get("path")
    if not path:
        return False, "", "Missing required parameter 'path'."

    valid, target_path, err = _resolve_and_check_boundary(path, must_exist=True)
    if not valid:
        return False, "", err

    if os.path.isdir(target_path):
        return False, "", f"Target '{path}' is a directory, not a file. Use 'list_files' to view directory contents."

    # Read file content safely
    try:
        from core.file_manager import read_file_content
        content, read_err = read_file_content(target_path)
    except Exception:
        content = None
        read_err = None

    if content is None:
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception as e:
                return False, "", f"Error reading file '{path}': {e}"
        except Exception as e:
            return False, "", f"Error reading file '{path}': {e}"

    lines = content.splitlines()
    total_lines = len(lines)

    start_line = args.get("start_line")
    end_line = args.get("end_line")

    s_idx = 0
    e_idx = total_lines

    if start_line is not None:
        try:
            s_idx = max(0, int(start_line) - 1)
        except Exception:
            pass

    if end_line is not None:
        try:
            e_idx = min(total_lines, int(end_line))
        except Exception:
            pass

    if s_idx > e_idx:
        s_idx, e_idx = e_idx, s_idx

    selected_lines = lines[s_idx:e_idx]
    truncated = False

    if len(selected_lines) > MAX_READ_LINES:
        selected_lines = selected_lines[:MAX_READ_LINES]
        truncated = True

    output_text = "\n".join(selected_lines)
    if len(output_text.encode("utf-8")) > MAX_READ_BYTES:
        output_text = output_text[:MAX_READ_BYTES]
        truncated = True

    if truncated:
        output_text += (
            f"\n\n[Content truncated: showing lines {s_idx + 1}-{s_idx + len(selected_lines)} of {total_lines}. "
            f"Specify 'start_line' and 'end_line' to view specific sections.]"
        )

    return True, output_text, None


def _execute_file_write(args: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
    """Write text content to a file in the project."""
    path = args.get("path")
    if not path:
        return False, "", "Missing required parameter 'path'."

    content = args.get("content", "")
    valid, target_path, err = _resolve_and_check_boundary(path, must_exist=False)
    if not valid:
        return False, "", err

    try:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        bytes_written = len(content.encode("utf-8"))
        return True, f"Successfully wrote {bytes_written} bytes to '{path}'.", None
    except Exception as e:
        return False, "", f"Failed to write file '{path}': {e}"


def _execute_file_search(args: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
    """Search for text or regex pattern across files in project."""
    pattern = args.get("pattern") or args.get("query")
    if not pattern:
        return False, "", "Missing required parameter 'pattern'."

    sub_path = args.get("path", ".")
    valid, search_root, err = _resolve_and_check_boundary(sub_path, must_exist=True)
    if not valid:
        return False, "", err

    case_sensitive = bool(args.get("case_sensitive", False))
    flags = 0 if case_sensitive else re.IGNORECASE

    try:
        regex = re.compile(pattern, flags)
    except re.error:
        # Fall back to literal escaped regex
        regex = re.compile(re.escape(pattern), flags)

    matches: List[str] = []
    project_root = _get_project_root()

    for root, dirs, files in os.walk(search_root):
        # Prune ignored directories
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]

        for file in files:
            if file.startswith(".") or file.endswith((".pyc", ".png", ".jpg", ".jpeg", ".pdf", ".db", ".sqlite")):
                continue

            file_path = os.path.join(root, file)
            rel_file = os.path.relpath(file_path, project_root)

            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line_no, line in enumerate(f, start=1):
                        if regex.search(line):
                            snippet = line.strip()
                            if len(snippet) > 120:
                                snippet = snippet[:117] + "..."
                            matches.append(f"{rel_file}:{line_no}: {snippet}")
                            if len(matches) >= MAX_SEARCH_RESULTS:
                                break
            except Exception:
                continue

            if len(matches) >= MAX_SEARCH_RESULTS:
                break
        if len(matches) >= MAX_SEARCH_RESULTS:
            break

    if not matches:
        return True, f"No matches found for pattern '{pattern}' in '{sub_path}'.", None

    output = f"Found {len(matches)} match(es):\n" + "\n".join(matches)
    if len(matches) >= MAX_SEARCH_RESULTS:
        output += f"\n\n[Search capped at {MAX_SEARCH_RESULTS} matches.]"
    return True, output, None


def _execute_list_files(args: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
    """List directory contents within project boundary."""
    sub_path = args.get("path", ".")
    valid, target_dir, err = _resolve_and_check_boundary(sub_path, must_exist=True)
    if not valid:
        return False, "", err

    if not os.path.isdir(target_dir):
        return False, "", f"Path '{sub_path}' is not a directory."

    recursive = bool(args.get("recursive", False))
    max_depth = int(args.get("max_depth", 2))
    project_root = _get_project_root()

    entries: List[str] = []

    if not recursive:
        try:
            items = sorted(os.listdir(target_dir))
            for item in items:
                if item in _IGNORE_DIRS or item.startswith("."):
                    continue
                p = os.path.join(target_dir, item)
                rel = os.path.relpath(p, project_root)
                if os.path.isdir(p):
                    entries.append(f"[DIR]  {rel}/")
                else:
                    try:
                        size = os.path.getsize(p)
                        entries.append(f"[FILE] {rel} ({size} bytes)")
                    except Exception:
                        entries.append(f"[FILE] {rel}")
                if len(entries) >= MAX_LIST_ENTRIES:
                    break
        except Exception as e:
            return False, "", f"Error reading directory '{sub_path}': {e}"
    else:
        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
            rel_from_target = os.path.relpath(root, target_dir)
            depth = 0 if rel_from_target == "." else len(rel_from_target.split(os.sep))
            if depth >= max_depth:
                dirs.clear()

            for d in sorted(dirs):
                p = os.path.join(root, d)
                rel = os.path.relpath(p, project_root)
                entries.append(f"[DIR]  {rel}/")
                if len(entries) >= MAX_LIST_ENTRIES:
                    break

            for f in sorted(files):
                if f.startswith("."):
                    continue
                p = os.path.join(root, f)
                rel = os.path.relpath(p, project_root)
                try:
                    size = os.path.getsize(p)
                    entries.append(f"[FILE] {rel} ({size} bytes)")
                except Exception:
                    entries.append(f"[FILE] {rel}")
                if len(entries) >= MAX_LIST_ENTRIES:
                    break

            if len(entries) >= MAX_LIST_ENTRIES:
                break

    output = "\n".join(entries) if entries else "(Empty directory)"
    if len(entries) >= MAX_LIST_ENTRIES:
        output += f"\n\n[Listing capped at {MAX_LIST_ENTRIES} entries.]"
    return True, output, None


def _execute_run_command(args: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
    """Execute a shell command with safety classification and confirmation."""
    cmd = args.get("command")
    if not cmd or not str(cmd).strip():
        return False, "", "Missing required parameter 'command'."

    cmd_str = str(cmd).strip()
    cwd_rel = args.get("cwd", ".")
    valid, target_cwd, err = _resolve_and_check_boundary(cwd_rel, must_exist=True)
    if not valid:
        return False, "", err

    timeout = int(args.get("timeout", getattr(config, "command_timeout", 60)))

    # Safety classification
    safety = classify(cmd_str)

    if safety.level == BLOCKED:
        return False, "", f"Command blocked by AIZEN safety policy: {safety.reason or safety.block_message}"

    # Confirmation required for DANGEROUS or WRITE operations
    if safety.level in (DANGEROUS, WRITE):
        color = level_color(safety.level)
        icon = level_icon(safety.level)
        console.print()
        console.print(
            f"[bold yellow]⚠️ Tool requested command:[/bold yellow] [bold]{cmd_str}[/bold]\n"
            f"[bold]Directory:[/bold] {target_cwd}\n"
            f"[bold]Safety:[/bold]    [{color}]{icon} {safety.level}[/{color}] — {safety.reason}"
        )

        if safety.level == DANGEROUS:
            console.print("Type exactly [bold]EXECUTE[/bold] to approve, or Enter to reject: ", end="")
            try:
                conf = input().strip()
            except (EOFError, KeyboardInterrupt):
                conf = ""
            approved = (conf == "EXECUTE")
        else:
            console.print("Execute proposed command? [dim][y/N][/dim] ", end="")
            try:
                conf = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                conf = "n"
            approved = conf in ("y", "yes")

        if not approved:
            return False, "", "Command execution rejected by user."

    # Execute foreground command safely
    result = run_foreground(cmd_str, target_cwd, safety, timeout=timeout)

    output_parts = []
    if result.stdout:
        output_parts.append(result.stdout.rstrip())
    if result.stderr:
        output_parts.append(f"[stderr]\n{result.stderr.rstrip()}")
    output_text = "\n".join(output_parts) if output_parts else "(No output)"

    if result.cancelled:
        return False, output_text, "Command cancelled by user interrupt."
    if result.timed_out:
        return False, output_text, f"Command timed out after {timeout} seconds."

    if not result.success:
        err_msg = result.error_message or f"Command exited with non-zero code {result.exit_code}"
        return False, output_text, err_msg

    return True, output_text, None


# ------------------------------------------------------------------
# MAIN DISPATCHER
# ------------------------------------------------------------------

def execute_tool(tool_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a normalized tool call dictionary:
      {"tool": "file_read", "args": {...}}

    Returns:
      {
          "success": bool,
          "tool": str,
          "output": str,
          "error": Optional[str]
      }
    """
    if not isinstance(tool_dict, dict):
        return {
            "success": False,
            "tool": "unknown",
            "output": "",
            "error": "Invalid tool call payload; expected dictionary."
        }

    tool_name = tool_dict.get("tool")
    args = tool_dict.get("args") or {}

    tool_obj = registry.get_tool(tool_name)
    if not tool_obj:
        return {
            "success": False,
            "tool": tool_name or "unknown",
            "output": "",
            "error": f"Unknown tool '{tool_name}'. Available: {', '.join(t.name for t in registry.list_tools())}"
        }

    canonical = tool_obj.name

    try:
        if canonical == "file_read":
            success, output, error = _execute_file_read(args)
        elif canonical == "file_write":
            success, output, error = _execute_file_write(args)
        elif canonical == "file_search":
            success, output, error = _execute_file_search(args)
        elif canonical == "list_files":
            success, output, error = _execute_list_files(args)
        elif canonical == "run_command":
            success, output, error = _execute_run_command(args)
        else:
            return {
                "success": False,
                "tool": canonical,
                "output": "",
                "error": f"Tool '{canonical}' is registered but has no execution handler."
            }

        return {
            "success": success,
            "tool": canonical,
            "output": output,
            "error": error
        }

    except Exception as e:
        return {
            "success": False,
            "tool": canonical,
            "output": "",
            "error": f"Tool execution exception: {str(e)}"
        }
