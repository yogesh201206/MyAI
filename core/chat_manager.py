"""
core/chat_manager.py — Chat session CRUD and conversation operations.

Manages config.chats, config.current_chat_id, and all user-visible chat
actions. Storage calls go through core.storage; display calls go through
ui.console.
"""

import uuid
from datetime import datetime

from rich.markdown import Markdown
from rich.panel import Panel

import config
from core.storage import save_chats, save_config
from ui.console import console


# ------------------------------------------------------------------
# LOOKUP
# ------------------------------------------------------------------

def get_current_chat():
    """Return the active chat dict or None."""
    for chat in config.chats:
        if chat["id"] == config.current_chat_id:
            if "attachments" not in chat:
                chat["attachments"] = []
            return chat
    return None


# ------------------------------------------------------------------
# CREATE
# ------------------------------------------------------------------

def create_new_chat():
    """Create a blank chat, set it as current, persist, and print confirmation."""
    chat_id = str(uuid.uuid4())

    new_chat = {
        "id": chat_id,
        "title": "New Chat",
        "created_at": datetime.now().isoformat(),
        "messages": [],
        "attachments": [],
    }

    config.chats.append(new_chat)
    config.current_chat_id = chat_id

    save_chats()
    save_config()

    console.print("\n[bold green]✓ New chat created[/bold green]\n")


def ensure_chat():
    """Create a new chat if none is currently active."""
    if get_current_chat() is None:
        create_new_chat()


def generate_title(prompt):
    """Generate a short chat title from the first message."""
    words = prompt.split()
    if len(words) <= 6:
        return " ".join(words)
    return " ".join(words[:6]) + "..."


# ------------------------------------------------------------------
# LOAD
# ------------------------------------------------------------------

def load_chat(number):
    """Switch to the chat at position <number> in the saved chat list."""
    try:
        index = int(number) - 1

        if index < 0 or index >= len(config.chats):
            console.print("[red]Invalid chat number.[/red]")
            return

        config.current_chat_id = config.chats[index]["id"]
        save_config()

        console.print(
            f"\n[green]Loaded:[/green] {config.chats[index]['title']}"
        )

        # Show model info after loading
        from ui.console import show_model_info
        show_model_info()

    except ValueError:
        console.print("[yellow]Usage: /load <number>[/yellow]")


# ------------------------------------------------------------------
# DELETE
# ------------------------------------------------------------------

def delete_chat(number):
    """Remove the chat at position <number>."""
    try:
        index = int(number) - 1

        if index < 0 or index >= len(config.chats):
            console.print("[red]Invalid chat number.[/red]")
            return

        removed = config.chats.pop(index)

        # If we deleted the active chat, fall back to the last one
        if removed["id"] == config.current_chat_id:
            config.current_chat_id = (
                config.chats[-1]["id"] if config.chats else None
            )

        save_chats()
        save_config()

        console.print(f"[green]Deleted:[/green] {removed['title']}")

    except ValueError:
        console.print("[yellow]Usage: /delete <number>[/yellow]")


# ------------------------------------------------------------------
# RENAME
# ------------------------------------------------------------------

def rename_chat(title):
    """Rename the current chat."""
    chat = get_current_chat()

    if chat is None:
        console.print("[red]No active chat.[/red]")
        return

    if not title.strip():
        console.print("[yellow]Usage: /title <name>[/yellow]")
        return

    chat["title"] = title.strip()
    save_chats()

    console.print(f"[green]Renamed to:[/green] {title.strip()}")


# ------------------------------------------------------------------
# CLEAR
# ------------------------------------------------------------------

def clear_chat():
    """Erase all messages in the current chat."""
    chat = get_current_chat()

    if chat is None:
        console.print("[yellow]No active chat.[/yellow]")
        return

    chat["messages"] = []
    save_chats()

    console.print("[green]Current chat cleared.[/green]")


# ------------------------------------------------------------------
# DISPLAY
# ------------------------------------------------------------------

def show_chats():
    """Print the list of all saved chats as a Rich table."""
    from rich.table import Table

    if not config.chats:
        console.print("[yellow]No saved chats.[/yellow]")
        return

    table = Table(title="Saved Chats")
    table.add_column("#", style="cyan")
    table.add_column("Title")
    table.add_column("Messages")
    table.add_column("Status")

    for index, chat in enumerate(config.chats, start=1):
        status = "● Current" if chat["id"] == config.current_chat_id else ""
        table.add_row(
            str(index),
            chat["title"],
            str(len(chat["messages"])),
            status
        )

    console.print(table)


def show_history():
    """Print full conversation history for the current chat."""
    chat = get_current_chat()

    if chat is None:
        console.print("[yellow]No active chat.[/yellow]")
        return

    if not chat["messages"]:
        console.print("[yellow]No conversation history.[/yellow]")
        return

    console.print(f"\n[bold cyan]{chat['title']}[/bold cyan]\n")

    for message in chat["messages"]:
        if message["role"] == "user":
            console.print(
                Panel(
                    message["content"],
                    title="YOU",
                    border_style="green"
                )
            )
        elif message["role"] == "assistant":
            console.print(
                Panel(
                    Markdown(message["content"]),
                    title="AIZEN",
                    border_style="cyan"
                )
            )
