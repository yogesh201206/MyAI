"""
core/diff_manager.py — Unified diff generation, patch validation, and range-overlap detection.

Provides:
- generate_diff()      : produce unified diff text between old and new content
- render_diff_rich()   : print a colored unified diff to the Rich console
- diff_stats()         : count +/- lines in a diff
- check_overlap()      : detect overlapping edit ranges within one file
"""

import difflib
import re
from typing import List, Optional, Tuple

from rich.console import Console
from rich.text import Text


def generate_diff(
    old_text: str,
    new_text: str,
    from_label: str = "a/file",
    to_label: str = "b/file",
    context_lines: int = 3,
) -> str:
    """
    Produce a unified diff string between old_text and new_text.

    Returns an empty string if content is identical.
    """
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=from_label,
            tofile=to_label,
            n=context_lines,
        )
    )
    return "".join(diff_lines)


def diff_stats(diff_text: str) -> Tuple[int, int]:
    """
    Count lines added (+) and removed (-) in a unified diff text.
    Excludes --- / +++ header lines.

    Returns (lines_added, lines_removed).
    """
    added = 0
    removed = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def render_diff_rich(diff_text: str, console: Console) -> None:
    """
    Print a colored unified diff to the Rich console.
    Green for additions, red for deletions, cyan for @@ headers.
    """
    if not diff_text.strip():
        console.print("[dim]No changes.[/dim]")
        return

    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            console.print(f"[bold white]{line}[/bold white]")
        elif line.startswith("@@"):
            console.print(f"[cyan]{line}[/cyan]")
        elif line.startswith("+"):
            console.print(f"[green]{line}[/green]")
        elif line.startswith("-"):
            console.print(f"[red]{line}[/red]")
        else:
            console.print(f"[dim]{line}[/dim]")


def apply_replacement(
    original_content: str,
    old_text: str,
    new_text: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> Tuple[bool, str, str]:
    """
    Apply a single replacement to original_content.

    If start_line/end_line are provided, replaces that specific line range.
    Otherwise performs a text-match replacement for old_text.

    Returns:
        (success: bool, result_content: str, error_message: str)
    """
    if start_line is not None and end_line is not None:
        lines = original_content.splitlines(keepends=True)
        total = len(lines)
        s = max(1, start_line) - 1   # 0-indexed
        e = min(total, end_line)      # exclusive upper bound

        # Verify the range content matches expected old_text
        range_content = "".join(lines[s:e])
        if old_text and old_text.strip() and range_content.strip() != old_text.strip():
            return (
                False,
                original_content,
                f"Content mismatch at lines {start_line}–{end_line}: "
                f"expected text does not match current file content."
            )

        new_lines = new_text.splitlines(keepends=True)
        # Ensure trailing newline on new content if original had it
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"

        updated = lines[:s] + new_lines + lines[e:]
        return True, "".join(updated), ""

    # Fallback: text-based replacement
    if old_text not in original_content:
        return (
            False,
            original_content,
            "Expected old text not found in file content."
        )
    result = original_content.replace(old_text, new_text, 1)
    return True, result, ""


def check_overlap(changes: List[dict]) -> Optional[str]:
    """
    Check for overlapping edit ranges within a single file.

    Each change dict must have: file, start_line, end_line.

    Returns an error message if overlaps are detected, otherwise None.
    """
    from collections import defaultdict
    file_ranges: dict = defaultdict(list)

    for ch in changes:
        f = ch.get("file", "")
        s = ch.get("start_line", 0)
        e = ch.get("end_line", s)
        file_ranges[f].append((s, e, ch))

    for f, ranges in file_ranges.items():
        # Sort by start line
        sorted_r = sorted(ranges, key=lambda x: x[0])
        for i in range(1, len(sorted_r)):
            prev_end = sorted_r[i - 1][1]
            curr_start = sorted_r[i][0]
            if curr_start <= prev_end:
                return (
                    f"Overlapping edit ranges in '{f}': "
                    f"lines {sorted_r[i-1][0]}–{prev_end} and "
                    f"lines {curr_start}–{sorted_r[i][1]}. "
                    "Regenerate the edit proposal."
                )
    return None


def validate_syntax(file_path: str, content: str, extension: str) -> Tuple[bool, str]:
    """
    Perform lightweight syntax validation on content before writing.

    Python: compile() check.
    JSON:   json.loads() check.
    YAML:   yaml.safe_load() if available.
    Others: pass through.

    Returns (valid: bool, error_message: str).
    """
    ext = extension.lower()

    if ext == ".py":
        try:
            import py_compile, tempfile, os
            fd, tmp = tempfile.mkstemp(suffix=".py")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                py_compile.compile(tmp, doraise=True)
                return True, ""
            finally:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
        except py_compile.PyCompileError as e:
            return False, f"Python syntax error: {e}"
        except Exception as e:
            return True, ""  # If compiler unavailable, allow through

    if ext == ".json":
        try:
            import json
            json.loads(content)
            return True, ""
        except json.JSONDecodeError as e:
            return False, f"JSON syntax error: {e}"

    if ext in (".yml", ".yaml"):
        try:
            import yaml
            yaml.safe_load(content)
            return True, ""
        except Exception as e:
            return False, f"YAML syntax error: {e}"

    return True, ""
