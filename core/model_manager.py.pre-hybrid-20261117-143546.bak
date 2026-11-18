"""
core/model_manager.py — Model catalog queries and model selection.

Reads from config.model_catalog / config.model_map (populated by
api.omniroute.fetch_models) and writes config.current_model.
"""

from rich.panel import Panel
from rich.table import Table

import config
from core.storage import save_config
from ui.console import console


# ------------------------------------------------------------------
# METADATA ACCESSORS
# ------------------------------------------------------------------

def get_model_meta(model_id=None):
    """Return the raw metadata dict for model_id (defaults to current model)."""
    if model_id is None:
        model_id = config.current_model
    return config.model_map.get(model_id)


def get_model_context_limit(model_id=None):
    """Return the context window size, preferring context_length over max_input_tokens."""
    meta = get_model_meta(model_id)
    if not meta:
        return None
    return meta.get("context_length") or meta.get("max_input_tokens")


def get_model_input_limit(model_id=None):
    """Return max input tokens, preferring max_input_tokens over context_length."""
    meta = get_model_meta(model_id)
    if not meta:
        return None
    return meta.get("max_input_tokens") or meta.get("context_length")


def get_model_output_limit(model_id=None):
    """Return max output tokens for the given model."""
    meta = get_model_meta(model_id)
    if not meta:
        return None
    return meta.get("max_output_tokens")


def get_model_provider(model_id=None):
    """Return the provider/owner name for the given model."""
    meta = get_model_meta(model_id)
    if not meta:
        return "Unknown"
    return meta.get("owned_by", "Unknown")


# ------------------------------------------------------------------
# ------------------------------------------------------------------
# MODEL LIST
# ------------------------------------------------------------------

def show_models(filter_text=""):
    """Display the verified-free model catalog as a Rich table, optionally filtered."""
    from api.omniroute import fetch_models
    from core.token_manager import human_number

    if not config.model_catalog:
        if not fetch_models(show_message=True):
            return

    if not config.model_catalog:
        console.print("[yellow]No verified free models available.[/yellow]")
        console.print("[dim]Paid and unverified models are blocked by AIZEN Free-Only mode.[/dim]")
        config.last_displayed_models = []
        return

    query = filter_text.strip().lower()

    results = [
        model for model in config.model_catalog
        if not query or query in (
            model.get("id", "") + " " + str(model.get("owned_by", ""))
        ).lower()
    ]

    if not results:
        console.print(
            f"[yellow]No verified free models found for '{filter_text}'.[/yellow]"
        )
        config.last_displayed_models = []
        return

    display_limit = 50
    shown = results[:display_limit]
    config.last_displayed_models = shown

    title_str = f"AIZEN Free Models — {filter_text}" if filter_text else "AIZEN Free Models"
    table = Table(title=title_str)
    table.add_column("#", style="cyan", justify="right")
    table.add_column("Provider")
    table.add_column("Model")
    table.add_column("Status", style="bold green", justify="center")
    table.add_column("Context", justify="right")
    table.add_column("Output", justify="right")

    for index, model in enumerate(shown, start=1):
        model_id = model.get("id", "")
        marker = " ✓" if model_id == config.current_model else ""

        table.add_row(
            str(index),
            str(model.get("owned_by", "Unknown")),
            model_id + marker,
            "FREE VERIFIED",
            human_number(model.get("context_length")),
            human_number(model.get("max_output_tokens"))
        )

    console.print(table)

    if len(results) > display_limit:
        console.print(
            f"[dim]Showing first {display_limit} of {len(results)} verified-free models. "
            f"Use /models <filter>.[/dim]"
        )

    console.print(
        "\n[dim]Select using /use <number> or /use <model-id> • Free-only policy active[/dim]"
    )


# ------------------------------------------------------------------
# MODEL SELECTION
# ------------------------------------------------------------------

def select_model(argument):
    """Select a model by list number or by model-id string."""
    from api.omniroute import fetch_models
    from core.free_model_registry import is_model_allowed
    from core.provider_health import get_provider_for_model
    from ui.console import show_model_info

    value = argument.strip()

    if not value:
        console.print("[yellow]Usage: /use <number|model-id>[/yellow]")
        return

    selected_id = None

    if value.isdigit():
        number = int(value)
        if number < 1 or number > len(config.last_displayed_models):
            console.print("[red]Invalid model number.[/red]")
            console.print("[dim]Run /models first.[/dim]")
            return
        selected_id = config.last_displayed_models[number - 1].get("id")
    else:
        selected_id = value

    # Ensure catalog is loaded before validating
    if not config.model_catalog:
        fetch_models()

    # Special handling for "auto"
    if selected_id == "auto":
        config.current_model = "auto"
        config.model_selection_mode = "router"
        save_config()
        console.print("\n[bold green]✓ AUTO mode enabled (Free-Only Smart Router).[/bold green]\n")
        show_model_info(selected_message=True)
        return

    # Central Free-Only Policy Check: Reject unverified or paid models immediately
    provider = get_provider_for_model(selected_id)
    if not is_model_allowed(provider, selected_id):
        console.print(
            "\n[bold red]❌ Model is not available in AIZEN Free-Only mode (blocked by AIZEN free-only policy).[/bold red]\n"
            "[yellow]Reason:[/yellow] This model is not currently verified as absolutely free.\n"
            "[dim]Use /pick or /free list to see eligible models.[/dim]\n"
        )
        return

    if selected_id not in config.model_map:
        console.print(
            f"[yellow]Model '{selected_id}' is verified free but not currently found in active catalog.[/yellow]"
        )
        console.print("[dim]Run /refresh then try again.[/dim]")
        return

    config.current_model = selected_id
    config.model_selection_mode = "manual"
    save_config()

    console.print(
        f"\n[bold green]✓ Model selected:[/bold green] "
        f"[cyan]{config.current_model}[/cyan] [green](FREE VERIFIED)[/green]\n"
        "[dim]Manual model override enabled.[/dim]\n"
    )

    show_model_info(selected_message=True)
