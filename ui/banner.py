"""
ui/banner.py — AIZEN logo, screen clearing, and exit sequence.

Imports only stdlib and Rich — no project modules — so it can be
imported early in the boot process without side effects.
"""

import random
import sys
import time

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

import config

# Module-local console for banner output
_console = Console()


def clear_terminal():
    """Clear the terminal using ANSI escape codes."""
    print("\033[2J\033[H", end="", flush=True)


def show_banner(console=None):
    """Print the AIZEN ASCII logo and tagline."""
    if console is None:
        console = _console

    console.print(
        Align.center(
            Text(config.AIZEN_LOGO, style="bold cyan")
        )
    )

    console.print(
        Align.center(
            Text("AIZEN AI • Multi-Model Intelligence", style="bold white")
        )
    )

    console.print()


def exit_aizen(console=None):
    """Display the exit animation and terminate the process."""
    if console is None:
        console = _console

    dialogue = random.choice(config.EXIT_DIALOGUES)

    console.print()

    console.print(
        Panel(
            Align.center(Text(dialogue, style="italic cyan")),
            title="[bold cyan]AIZEN[/bold cyan]",
            border_style="cyan"
        )
    )

    console.print("\n[dim]Saving conversation...[/dim]")

    # Check for active background jobs (Phase 10)
    try:
        from core.job_manager import get_job_manager
        jm = get_job_manager()
        running = jm.running_jobs()
        if running:
            console.print(f"\n[bold yellow]{len(running)} background job(s) are still running.[/bold yellow]")
            console.print("[yellow]Stop running jobs before exit?[/yellow] [dim][Y/n][/dim] ", end="")
            try:
                ans = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "y"
            if ans in ("", "y", "yes"):
                count = jm.cleanup_on_exit()
                console.print(f"[dim]Stopped {count} background job(s).[/dim]")
    except Exception:
        pass

    # Persist before shutting down
    from core.storage import save_chats, save_config
    save_chats()
    save_config()

    time.sleep(0.5)
    console.print("[dim]Closing neural route...[/dim]")
    time.sleep(0.5)
    console.print("[dim]Releasing AIZEN session...[/dim]")
    time.sleep(0.5)
    console.print("\n[cyan]Returning control to Yoges.[/cyan]")
    time.sleep(1.2)

    clear_terminal()
    sys.exit(0)
