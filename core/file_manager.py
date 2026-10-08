"""
core/file_manager.py — File attachment and file context subsystem.

Responsibilities:
  - Validate files (existence, regular file, extension, readability, binary check)
  - Attach files to the active chat
  - Remove / clear attachments
  - List attached files with live status (Available, Modified, Missing, Unreadable)
  - Read file contents safely with UTF-8 and fallback
  - Build prompt context respecting model context limit, reserved output, and fair per-file budget
  - Never execute or import attached code
"""

import os
from datetime import datetime

import config
from ui.console import console

# ------------------------------------------------------------------
# CONSTANTS & SUPPORTED EXTENSIONS
# ------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".py", ".java", ".js", ".jsx",
    ".ts", ".tsx", ".json", ".xml", ".yaml", ".yml",
    ".html", ".css", ".sql",
}

EXT_TO_LANG = {
    ".py":   "python",
    ".java": "java",
    ".js":   "javascript",
    ".jsx":  "javascript",
    ".ts":   "typescript",
    ".tsx":  "typescript",
    ".json": "json",
    ".xml":  "xml",
    ".yaml": "yaml",
    ".yml":  "yaml",
    ".html": "html",
    ".css":  "css",
    ".sql":  "sql",
    ".md":   "markdown",
    ".txt":  "text",
}


# ------------------------------------------------------------------
# FORMATTING HELPERS
# ------------------------------------------------------------------

def format_size(size_bytes: int | None) -> str:
    """Format byte size into human readable string."""
    if size_bytes is None:
        return "—"
    try:
        b = int(size_bytes)
    except Exception:
        return str(size_bytes)

    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    else:
        return f"{b / (1024 * 1024):.2f} MB"


def _format_mtime(iso_str: str | None) -> str:
    """Format ISO timestamp to readable date/time."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_str[:16]


# ------------------------------------------------------------------
# VALIDATION
# ------------------------------------------------------------------

def validate_file_path(path_str: str) -> tuple[bool, str, str | None]:
    """
    Validate a file path before attaching.

    Returns:
        (is_valid: bool, error_message: str, normalized_abs_path: str | None)
    """
    cleaned = (path_str or "").strip().strip("'\"")
    if not cleaned:
        return False, "Usage: /attach <path>", None

    abs_path = os.path.abspath(os.path.expanduser(cleaned))

    if not os.path.exists(abs_path):
        return False, f"File does not exist: {abs_path}", None

    if os.path.isdir(abs_path):
        return False, f"Directories are not supported: {abs_path}", None

    if not os.path.isfile(abs_path):
        return False, f"Not a regular file: {abs_path}", None

    _, ext = os.path.splitext(abs_path)
    ext_lower = ext.lower()

    if ext_lower not in SUPPORTED_EXTENSIONS:
        ext_list = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        return (
            False,
            f"Unsupported file extension '{ext}'.\n"
            f"[dim]Supported: {ext_list}[/dim]",
            None,
        )

    # Check readability and binary content
    try:
        with open(abs_path, "rb") as f:
            sample = f.read(1024)
            if b"\x00" in sample:
                return (
                    False,
                    f"Binary file detected — only text and code files are supported: {os.path.basename(abs_path)}",
                    None,
                )
    except PermissionError:
        return False, f"Permission denied reading file: {abs_path}", None
    except Exception as e:
        return False, f"Cannot read file: {e}", None

    return True, "", abs_path


# ------------------------------------------------------------------
# ATTACHMENT OPERATIONS
# ------------------------------------------------------------------

def attach_file(path_str: str) -> bool:
    """
    Validate and attach a file to the currently active chat.
    Persists metadata to chats.json.
    """
    from core.chat_manager import ensure_chat, get_current_chat
    from core.storage import save_chats

    ensure_chat()
    chat = get_current_chat()
    if chat is None:
        console.print("[red]No active chat session.[/red]")
        return False

    if "attachments" not in chat:
        chat["attachments"] = []

    is_valid, err_msg, abs_path = validate_file_path(path_str)
    if not is_valid:
        console.print(f"[red]{err_msg}[/red]")
        return False

    name = os.path.basename(abs_path)
    _, ext = os.path.splitext(abs_path)
    ext_lower = ext.lower()

    # Prevent duplicate attachment of same absolute path in this chat
    for existing in chat["attachments"]:
        if existing.get("path") == abs_path:
            console.print(f"[yellow]File is already attached: {name}[/yellow]")
            return False

    try:
        stat = os.stat(abs_path)
        size_bytes = stat.st_size
        mtime_iso = datetime.fromtimestamp(stat.st_mtime).isoformat()
    except Exception as e:
        console.print(f"[red]Error inspecting file: {e}[/red]")
        return False

    record = {
        "path": abs_path,
        "name": name,
        "extension": ext_lower,
        "size_bytes": size_bytes,
        "attached_at": datetime.now().isoformat(),
        "last_modified": mtime_iso,
    }

    chat["attachments"].append(record)
    save_chats()

    console.print(
        f"[green]✓ Attached:[/green] [bold]{name}[/bold] "
        f"[dim]({format_size(size_bytes)})[/dim]"
    )
    return True


def remove_attachment(number_str: str) -> bool:
    """
    Remove an attached file by 1-based index from the active chat.
    Does NOT delete the file from disk.
    """
    from core.chat_manager import get_current_chat
    from core.storage import save_chats

    chat = get_current_chat()
    if chat is None or not chat.get("attachments"):
        console.print("[yellow]No files attached to current chat.[/yellow]")
        return False

    try:
        index = int(number_str) - 1
        if index < 0 or index >= len(chat["attachments"]):
            console.print("[red]Invalid attachment number.[/red]")
            return False

        removed = chat["attachments"].pop(index)
        save_chats()
        console.print(f"[green]✓ Removed attachment:[/green] {removed['name']}")
        return True
    except ValueError:
        console.print("[yellow]Usage: /remove <number>[/yellow]")
        return False


def clear_attachments() -> bool:
    """
    Clear all attachments from the active chat.
    Does NOT delete actual files from disk.
    """
    from core.chat_manager import get_current_chat
    from core.storage import save_chats

    chat = get_current_chat()
    if chat is None or not chat.get("attachments"):
        console.print("[dim]No attachments to clear.[/dim]")
        return False

    count = len(chat["attachments"])
    chat["attachments"] = []
    save_chats()
    console.print(f"[green]✓ Cleared {count} attached file(s) from current chat.[/green]")
    return True


# ------------------------------------------------------------------
# STATUS & LISTING
# ------------------------------------------------------------------

def get_attachment_status(att: dict) -> tuple[str, str]:
    """
    Determine the live status of an attached file.

    Returns:
        (status_text: str, color_name: str)
        Possible statuses: Available (green), Modified (yellow),
                           Missing (red), Unreadable (red)
    """
    path = att.get("path")
    if not path or not os.path.exists(path):
        return "Missing", "red"

    try:
        stat = os.stat(path)
        cur_mtime_iso = datetime.fromtimestamp(stat.st_mtime).isoformat()
        last_mod = att.get("last_modified", "")
        if cur_mtime_iso > last_mod:
            return "Modified", "yellow"
        return "Available", "green"
    except PermissionError:
        return "Unreadable", "red"
    except Exception:
        return "Unreadable", "red"


def show_files():
    """Display a Rich table of all attached files for the active chat."""
    from rich.table import Table
    from core.chat_manager import get_current_chat

    chat = get_current_chat()
    if chat is None or not chat.get("attachments"):
        console.print(
            "[yellow]No files attached to current chat.[/yellow]\n"
            "[dim]Use [cyan]/attach <path>[/cyan] to attach a file.[/dim]"
        )
        return

    table = Table(title="Attached Files")
    table.add_column("#", style="cyan", justify="right")
    table.add_column("Name", style="bold")
    table.add_column("Type", style="dim")
    table.add_column("Size", justify="right")
    table.add_column("Modified", justify="left")
    table.add_column("Status", justify="left")

    for i, att in enumerate(chat["attachments"], start=1):
        status, color = get_attachment_status(att)
        size_display = format_size(att.get("size_bytes"))
        # If file still exists on disk, show live size
        if status in ("Available", "Modified"):
            try:
                live_size = os.path.getsize(att["path"])
                size_display = format_size(live_size)
            except Exception:
                pass

        table.add_row(
            str(i),
            att.get("name", "Unknown"),
            att.get("extension", "—"),
            size_display,
            _format_mtime(att.get("last_modified")),
            f"[{color}]{status}[/{color}]",
        )

    console.print(table)
    console.print(
        "\n[dim]Use [cyan]/attach <path>[/cyan] to add, "
        "[cyan]/remove <number>[/cyan] to remove, "
        "[cyan]/clearfiles[/cyan] to clear all.[/dim]\n"
    )


def get_attached_files_count() -> int:
    """Return the number of files attached to the current active chat."""
    from core.chat_manager import get_current_chat
    chat = get_current_chat()
    if chat and isinstance(chat, dict):
        return len(chat.get("attachments", []))
    return 0


# ------------------------------------------------------------------
# SAFE CONTENT READING
# ------------------------------------------------------------------

def read_file_content(path: str) -> tuple[str | None, str | None]:
    """
    Read text file content safely.
    Attempts UTF-8 first, falls back to UTF-8 with replacement on decode errors.
    Never executes or imports code.

    Returns:
        (content: str | None, error_message: str | None)
    """
    if not os.path.exists(path):
        return None, "File missing"

    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except UnicodeDecodeError:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read(), None
        except Exception as e:
            return None, str(e)
    except Exception as e:
        return None, str(e)


# ------------------------------------------------------------------
# PROMPT CONTEXT PREPARATION
# ------------------------------------------------------------------

def build_file_context(chat: dict | None) -> str | None:
    """
    Prepare an attachment context block for the AI model prompt.

    Features:
      - Reads live content at request time
      - Updates metadata (size, last_modified) if file changed
      - Skips missing/unreadable files with subtle notification
      - Enforces context budget (reserves 20% for model response & safety)
      - Implements fair per-file budget allocation
      - Performs deterministic truncation when a file exceeds its budget
      - Never mutates chat['messages'] directly

    Returns:
        Formatted context string, or None if no valid attachment content.
    """
    if not chat or not chat.get("attachments"):
        return None

    from core.model_manager import get_model_context_limit
    from core.token_manager import get_context_status
    from core.storage import save_chats

    # 1. Filter and read available files
    valid_reads = []
    metadata_changed = False

    for att in chat["attachments"]:
        path = att.get("path")
        name = att.get("name", "file")
        status, _ = get_attachment_status(att)

        if status == "Missing":
            console.print(
                f"[dim yellow]Notice: Attached file '{name}' is missing and was skipped.[/dim yellow]"
            )
            continue
        elif status == "Unreadable":
            console.print(
                f"[dim yellow]Notice: Attached file '{name}' is unreadable and was skipped.[/dim yellow]"
            )
            continue

        content, err = read_file_content(path)
        if content is None:
            console.print(
                f"[dim yellow]Notice: Could not read attached file '{name}' ({err}).[/dim yellow]"
            )
            continue

        # Update metadata if modified
        try:
            stat = os.stat(path)
            cur_mtime_iso = datetime.fromtimestamp(stat.st_mtime).isoformat()
            if cur_mtime_iso != att.get("last_modified") or stat.st_size != att.get("size_bytes"):
                att["last_modified"] = cur_mtime_iso
                att["size_bytes"] = stat.st_size
                metadata_changed = True
        except Exception:
            pass

        valid_reads.append((att, content))

    if metadata_changed:
        save_chats()

    if not valid_reads:
        return None

    # 2. Calculate context budget
    limit = get_model_context_limit()
    if not limit or limit <= 0:
        limit = 16384  # conservative default if model limit unknown

    context_status = get_context_status()
    chat_used = context_status.get("used", 0)

    # Reserve at least 20% of context window for output & system safety
    reserved_output = int(limit * 0.20)
    avail_tokens = max(500, limit - reserved_output - chat_used)
    avail_chars = avail_tokens * 4

    # Fair distribution across attached files
    num_files = len(valid_reads)
    fair_char_limit = max(1000, avail_chars // num_files)

    # 3. Format sections
    file_sections = []
    for att, raw_content in valid_reads:
        name = att.get("name", "file")
        ext = att.get("extension", "").lower()
        lang = EXT_TO_LANG.get(ext, "")

        if len(raw_content) > fair_char_limit:
            truncated = raw_content[:fair_char_limit]
            omitted = len(raw_content) - fair_char_limit
            final_content = (
                f"{truncated}\n\n"
                f"[... Truncated: remaining {omitted} characters omitted due to context budget ...]\n"
            )
        else:
            final_content = raw_content

        file_sections.append(
            f"--- FILE: {name} ---\n"
            f"```{lang}\n"
            f"{final_content}\n"
            f"```\n"
            f"--- END FILE ---"
        )

    header = (
        "The following files are attached by the user.\n"
        "Treat them as reference material.\n"
        "Do not assume omitted portions are present."
    )

    return f"{header}\n\n" + "\n\n".join(file_sections)
