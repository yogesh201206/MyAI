"""
ui/console.py — Shared Rich console instance and all display functions.

The single `console` object defined here is imported by every other
module that needs to print to the terminal.
"""

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.align import Align
from rich.text import Text

import config

# The one-and-only Rich Console for the entire application
console = Console()


# ------------------------------------------------------------------
# HOME SCREEN
# ------------------------------------------------------------------

def show_aizen_home():
    """Clear the screen and render the AIZEN status dashboard."""
    from api.omniroute import check_connection
    from core.chat_manager import get_current_chat
    from core.model_manager import get_model_provider
    from core.token_manager import get_context_status, human_number
    from ui.banner import clear_terminal, show_banner

    clear_terminal()
    show_banner(console)

    connected = check_connection()
    connection_text = (
        "[green]● Connected[/green]" if connected else "[red]● Offline[/red]"
    )

    chat = get_current_chat()
    chat_title = chat["title"] if chat else "None"
    context = get_context_status()

    table = Table(show_header=False, box=None)
    table.add_row("Chat", chat_title)
    table.add_row("Selected Model", config.current_model)
    table.add_row("Provider", get_model_provider())
    table.add_row("Models", f"{len(config.model_catalog)} Free Verified")

    if context["limit"]:
        table.add_row(
            "Context",
            f"{human_number(context['used'])}/{human_number(context['limit'])}"
        )

    table.add_row("OmniRoute", connection_text)
    streaming_text = (
        "[green]ON[/green]" if config.streaming_enabled else "[yellow]OFF[/yellow]"
    )
    table.add_row("Streaming", streaming_text)

    # Attached files (compact display if files exist)
    try:
        from core.file_manager import get_attached_files_count
        f_count = get_attached_files_count()
        if f_count > 0:
            table.add_row("Files Attached", str(f_count))
    except Exception:
        pass

    # Knowledge Base summary (compact display if docs exist)
    try:
        from core.kb_manager import get_kb_counts
        d_count, _ = get_kb_counts()
        if d_count > 0:
            rag_str = "ON" if config.rag_enabled else "OFF"
            table.add_row("Knowledge Base", f"{d_count} docs (RAG {rag_str})")
    except Exception:
        pass

    # Project summary (compact display if project path is set)
    try:
        from core.project_manager import get_project_status
        p_st = get_project_status()
        if p_st["project_name"] != "None":
            mode_color = "green" if p_st["mode"] == "ON" else "yellow"
            table.add_row("Project", f"{p_st['project_name']} [{mode_color}]({p_st['mode']})[/{mode_color}]")
    except Exception:
        pass

    # Provider health summary (only when data exists)
    try:
        from core.provider_health import get_summary, STATUS_COLORS, STATUS_SYMBOLS
        summary = get_summary()
        if summary:
            parts = []
            order = ["ONLINE", "DEGRADED", "RATE_LIMITED", "AUTH_ERROR", "OFFLINE", "UNKNOWN"]
            for s in order:
                count = summary.get(s, 0)
                if count:
                    color = STATUS_COLORS.get(s, "dim")
                    sym   = STATUS_SYMBOLS.get(s, "·")
                    parts.append(f"[{color}]{sym} {count} {s.title()}[/{color}]")
            if parts:
                table.add_row("Providers", "  ".join(parts))
    except Exception:
        pass

    # Agent mode (Phase 10)
    agent_text = "[green]ON[/green]" if getattr(config, "agent_enabled", False) else "[yellow]OFF[/yellow]"
    table.add_row("Agent", agent_text)

    # Route indicator (Phase 11)
    route_mode = getattr(config, "router_mode", "AUTO")
    sel_mode = getattr(config, "model_selection_mode", "ROUTER").upper()
    if sel_mode == "MANUAL":
        table.add_row("Route", f"[yellow]MANUAL[/yellow] [dim]({config.current_model})[/dim]")
    else:
        table.add_row("Route", f"[bold cyan]{route_mode}[/bold cyan]")

    # Voice mode (Phase 13) — only show when enabled
    if getattr(config, "voice_enabled", False):
        v_in = "🎤 ON" if config.voice_input_enabled else "OFF"
        v_out = "🔊 ON" if config.voice_output_enabled else "OFF"
        table.add_row("Voice", f"Input: {v_in}  Output: {v_out}")

    # Debug mode indicator (Phase 15)
    if getattr(config, "debug_mode", False):
        table.add_row("Mode", "[bold yellow]DEBUG[/bold yellow]")

    console.print(Panel(table, title="AIZEN", border_style="cyan"))

    console.print("\nType [cyan]/help[/cyan] for commands.")
    console.print(
        "[dim]Use /models to browse • "
        "/use <number> to select • "
        "/usage for token info[/dim]\n"
    )


# ------------------------------------------------------------------
# STATUS
# ------------------------------------------------------------------

def show_status():
    """Print the AIZEN status panel."""
    from api.omniroute import check_connection
    from core.chat_manager import get_current_chat
    from core.model_manager import get_model_provider
    from core.token_manager import get_context_status, human_number

    connected = check_connection()
    status_text = (
        "[green]● Connected[/green]" if connected else "[red]● Offline[/red]"
    )

    chat = get_current_chat()
    chat_title = chat["title"] if chat else "None"
    context = get_context_status()

    table = Table(show_header=False, box=None)
    table.add_row("OmniRoute", status_text)
    streaming_text = (
        "[green]ON[/green]" if config.streaming_enabled else "[yellow]OFF[/yellow]"
    )
    table.add_row("Streaming", streaming_text)
    table.add_row("Selected Model", config.current_model)
    table.add_row("Provider", get_model_provider())
    table.add_row("Chat", chat_title)
    table.add_row("Saved Chats", str(len(config.chats)))
    raw_count = len(getattr(config, "raw_model_catalog", []))
    raw_str = f" ({raw_count} total discovered)" if raw_count else ""
    table.add_row("Models Loaded", f"{len(config.model_catalog)} verified-free{raw_str}")
    table.add_row("Approx Context", human_number(context["used"]))

    if context["limit"]:
        table.add_row("Context Limit", human_number(context["limit"]))
        table.add_row("Remaining", human_number(context["remaining"]))

    # Provider health breakdown
    try:
        from core.provider_health import get_summary, STATUS_COLORS, STATUS_SYMBOLS
        summary = get_summary()
        order = ["ONLINE", "DEGRADED", "RATE_LIMITED", "AUTH_ERROR", "OFFLINE", "UNKNOWN"]
        for s in order:
            count = summary.get(s, 0)
            if count:
                color = STATUS_COLORS.get(s, "dim")
                sym   = STATUS_SYMBOLS.get(s, "·")
                table.add_row(
                    f"Providers {s.title()}",
                    f"[{color}]{sym} {count}[/{color}]"
                )
    except Exception:
        pass

    # Analytics summary (today)
    try:
        from core.analytics import get_today_summary
        t_summary = get_today_summary()
        req_today = t_summary.get("requests_today", 0)
        tok_today = t_summary.get("tokens_today")
        table.add_row("Requests Today", str(req_today))
        table.add_row(
            "Tokens Today",
            human_number(tok_today) if tok_today is not None else "0"
        )
    except Exception:
        pass

    # Attached files
    try:
        from core.file_manager import get_attached_files_count
        f_count = get_attached_files_count()
        table.add_row("Attached Files", str(f_count))
    except Exception:
        pass

    # Knowledge base & RAG
    try:
        from core.kb_manager import get_kb_counts
        from core.embeddings import get_model_name
        d_count, c_count = get_kb_counts()
        table.add_row("Knowledge Base Documents", str(d_count))
        table.add_row("Knowledge Base Chunks", str(c_count))
        rag_state = "[green]ON[/green]" if config.rag_enabled else "[yellow]OFF[/yellow]"
        table.add_row("RAG", rag_state)
        table.add_row("Embedding Backend", get_model_name().split("/")[-1])
    except Exception:
        pass

    # Project status
    try:
        from core.project_manager import get_project_status
        p_st = get_project_status()
        if p_st["project_name"] != "None":
            table.add_row("Project", p_st["project_name"])
            p_mode_str = "[green]ON[/green]" if p_st["mode"] == "ON" else "[yellow]OFF[/yellow]"
            table.add_row("Project Mode", p_mode_str)
            table.add_row("Project Files", f"{p_st['indexed_files']} indexed")
            if p_st["frameworks"]:
                table.add_row("Frameworks", ", ".join(p_st["frameworks"]))
    except Exception:
        pass

    # Pending edit
    try:
        if config.pending_edit is not None:
            table.add_row("Pending Edit", "[yellow]YES[/yellow]")
        else:
            table.add_row("Pending Edit", "[dim]none[/dim]")
    except Exception:
        pass

    # Agent Mode & Running Jobs (Phase 10)
    try:
        from core.job_manager import get_job_manager
        jm = get_job_manager()
        running_jobs = len(jm.running_jobs())
        agent_st = "[green]ON[/green]" if getattr(config, "agent_enabled", False) else "[yellow]OFF[/yellow]"
        table.add_row("Agent Mode", agent_st)
        table.add_row("Running Jobs", str(running_jobs))
    except Exception:
        pass

    # Smart Router (Phase 11)
    try:
        r_mode = getattr(config, "router_mode", "AUTO")
        s_mode = getattr(config, "model_selection_mode", "ROUTER").upper()
        s_mode_styled = "[yellow]MANUAL[/yellow]" if s_mode == "MANUAL" else "[green]ROUTER[/green]"
        table.add_row("Router Mode", r_mode)
        table.add_row("Model Selection", s_mode_styled)
    except Exception:
        pass

    # Voice Mode (Phase 13)
    try:
        v_enabled = getattr(config, "voice_enabled", False)
        v_input = getattr(config, "voice_input_enabled", True)
        v_output = getattr(config, "voice_output_enabled", False)
        table.add_row("Voice", "[green]ON[/green]" if v_enabled else "[dim]OFF[/dim]")
        table.add_row("Voice Input", "[green]ON[/green]" if v_input else "[dim]OFF[/dim]")
        table.add_row("Voice Out", "[green]ON[/green]" if v_output else "[dim]OFF[/dim]")
    except Exception:
        pass

    console.print(Panel(table, title="AIZEN Status", border_style="cyan"))


# ------------------------------------------------------------------
# MODEL INFO
# ------------------------------------------------------------------

def show_model_info(model_id=None, selected_message=False):
    """Print a model metadata panel for the given model (defaults to current)."""
    from core.model_manager import get_model_meta
    from core.token_manager import get_context_status, human_number, usage_warning

    if model_id is None:
        model_id = config.current_model

    meta = get_model_meta(model_id)
    context = get_context_status()

    table = Table(show_header=False, box=None)
    table.add_row("Selected Model", f"[cyan]{model_id}[/cyan]")

    # Policy status indicator
    if model_id == "auto":
        policy_status = "[bold green]FREE-ONLY (Smart Router)[/bold green]"
    else:
        from core.free_model_registry import is_verified_free
        from core.provider_health import get_provider_for_model
        p = get_provider_for_model(model_id)
        if is_verified_free(p, model_id):
            policy_status = "[bold green]FREE VERIFIED[/bold green]"
        else:
            policy_status = "[bold red]NOT VERIFIED (BLOCKED)[/bold red]"
    table.add_row("Policy Status", policy_status)

    if meta:
        table.add_row("Provider", str(meta.get("owned_by", "Unknown")))
        table.add_row("Context Limit", human_number(meta.get("context_length")))
        table.add_row("Max Input", human_number(meta.get("max_input_tokens")))
        table.add_row("Max Output", human_number(meta.get("max_output_tokens")))

        capabilities = meta.get("capabilities", {})
        supported = []
        if capabilities.get("reasoning"):
            supported.append("reasoning")
        if capabilities.get("thinking"):
            supported.append("thinking")
        if capabilities.get("tool_calling"):
            supported.append("tool calling")
        if capabilities.get("vision"):
            supported.append("vision")

        table.add_row("Capabilities", ", ".join(supported) if supported else "none")
    else:
        table.add_row("Provider", "Unknown")
        table.add_row("Context Limit", "—")
        table.add_row("Max Input", "—")
        table.add_row("Max Output", "—")
        table.add_row("Capabilities", "none")

    table.add_row("Current Chat Approx Usage", human_number(context["used"]))

    if context["limit"]:
        table.add_row("Remaining Context", human_number(context["remaining"]))
        table.add_row(
            "Context Used",
            f"{context['percent']:.1f}% {usage_warning(context['percent'])}"
        )
    else:
        table.add_row("Remaining Context", "Unlimited / Unknown")

    title = "Selected Model" if selected_message else "Model Information"
    console.print(Panel(table, title=title, border_style="cyan"))


# ------------------------------------------------------------------
# TOKEN USAGE & ANALYTICS VIEWS
# ------------------------------------------------------------------

def show_usage(subcommand=""):
    """Print a token usage panel or route to detailed usage subcommands."""
    sub = (subcommand or "").strip().lower()
    if sub in ("today", "week", "month", "all"):
        show_usage_period(sub)
    elif sub in ("models", "model"):
        show_usage_models()
    elif sub in ("providers", "provider"):
        show_usage_providers()
    elif sub == "chat":
        show_usage_chat()
    elif sub in ("db", "database"):
        show_usage_db()
    elif sub:
        console.print(
            f"[yellow]Unknown usage option '{subcommand}'.[/yellow]\n"
            "[dim]Available: /usage [today|week|month|all|models|providers|chat|db][/dim]"
        )
    else:
        from core.token_manager import get_context_status, human_number, usage_warning

        context = get_context_status()

        table = Table(show_header=False, box=None)
        table.add_row("Selected Model", config.current_model)
        table.add_row(
            "Last Routed Model",
            config.last_usage.get("actual_model") or "No request yet"
        )
        pt = config.last_usage.get("prompt_tokens")
        ct = config.last_usage.get("completion_tokens")
        tt = config.last_usage.get("total_tokens")

        table.add_row(
            "Last Prompt Tokens",
            str(pt) if pt is not None else "Unavailable"
        )
        table.add_row(
            "Last Output Tokens",
            str(ct) if ct is not None else "Unavailable"
        )
        table.add_row(
            "Last Request Total",
            str(tt) if tt is not None else "Unavailable"
        )
        table.add_row(
            "Last Response Time",
            f"{config.last_usage.get('response_time', 0):.2f}s"
        )
        table.add_row("Approx Current Chat", human_number(context["used"]))

        if context["limit"]:
            table.add_row("Context Limit", human_number(context["limit"]))
            table.add_row("Remaining", human_number(context["remaining"]))
            table.add_row(
                "Context Used",
                f"{context['percent']:.1f}% {usage_warning(context['percent'])}"
            )

        # Today's summary
        try:
            from core.analytics import get_period_stats
            today_stats = get_period_stats("today")
            req_today = today_stats.get("total_requests", 0)
            tok_today = today_stats.get("total_tokens")
            avg_ms = today_stats.get("avg_response_ms")

            table.add_row("", "")
            table.add_row("[bold dim]── Today ──[/bold dim]", "")
            table.add_row("Requests Today", str(req_today))
            table.add_row(
                "Total Tokens Today",
                human_number(tok_today) if tok_today is not None else "0"
            )
            avg_str = f"{avg_ms/1000:.2f}s" if avg_ms is not None else "—"
            table.add_row("Average Response Time", avg_str)
        except Exception:
            pass

        console.print(Panel(table, title="Token Usage", border_style="cyan"))
        console.print(
            "[dim]API request token values are exact when provided. "
            "Full chat context is estimated.\n"
            "Use [cyan]/usage today[/cyan], [cyan]/usage week[/cyan], [cyan]/usage models[/cyan], "
            "[cyan]/usage providers[/cyan], [cyan]/usage chat[/cyan], [cyan]/usage db[/cyan] for detailed analytics.[/dim]"
        )


def show_usage_period(period: str):
    """Display aggregate usage statistics for a time period (today, week, month, all)."""
    from core.analytics import get_period_stats
    from core.token_manager import human_number

    stats = get_period_stats(period)

    period_labels = {
        "today": "Today (Local Day)",
        "week":  "Last 7 Days",
        "month": "Last 30 Days",
        "all":   "All Time",
    }
    label = period_labels.get(period, period.capitalize())

    table = Table(show_header=False, box=None)
    table.add_row("Period", f"[bold cyan]{label}[/bold cyan]")
    table.add_row("Total Requests", str(stats["total_requests"]))
    table.add_row("Successful Requests", f"[green]{stats['successful']}[/green]")
    table.add_row("Failed Requests", f"[red]{stats['failed']}[/red]" if stats['failed'] > 0 else "0")
    table.add_row("Success Rate", f"{stats['success_rate']:.1f}%")

    inp = stats["input_tokens"]
    out = stats["output_tokens"]
    tot = stats["total_tokens"]

    table.add_row("Input Tokens", human_number(inp) if inp is not None else "0")
    table.add_row("Output Tokens", human_number(out) if out is not None else "0")
    table.add_row("Total Tokens", human_number(tot) if tot is not None else "0")

    avg_ms = stats["avg_response_ms"]
    avg_str = f"{avg_ms/1000:.2f}s" if avg_ms is not None else "—"
    table.add_row("Average Response Time", avg_str)
    table.add_row("Most Used Model", stats["most_used_model"] or "—")
    table.add_row("Most Used Provider", stats["most_used_provider"] or "—")

    console.print(Panel(table, title=f"Usage Analytics — {label}", border_style="cyan"))
    if stats.get("tokens_include_partial"):
        console.print("[dim]* Token counts include only requests with reported token usage.[/dim]\n")


def show_usage_models():
    """Display per-model usage analytics."""
    from core.analytics import get_model_stats
    from core.token_manager import human_number

    models = get_model_stats("all")
    if not models:
        console.print("[dim]No model usage recorded yet.[/dim]\n")
        return

    table = Table(title="Model Usage Analytics")
    table.add_column("Model", style="cyan", no_wrap=True)
    table.add_column("Requests", justify="right")
    table.add_column("Success", justify="right")
    table.add_column("Failures", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Output Tokens", justify="right")
    table.add_column("Total Tokens", justify="right")
    table.add_column("Avg Latency", justify="right")

    for m in models:
        avg_lat = m.get("avg_latency_ms")
        lat_str = f"{avg_lat:.0f}ms" if avg_lat is not None else "—"
        inp = human_number(m.get("input_tokens")) if m.get("input_tokens") is not None else "0"
        out = human_number(m.get("output_tokens")) if m.get("output_tokens") is not None else "0"
        tot = human_number(m.get("total_tokens")) if m.get("total_tokens") is not None else "0"
        succ = str(m.get("successful", 0))
        fail = str(m.get("failed", 0))

        table.add_row(
            m["model"],
            str(m["requests"]),
            succ,
            fail,
            inp,
            out,
            tot,
            lat_str,
        )

    console.print(table)
    console.print("\n[dim]Sorted primarily by request count descending.[/dim]\n")


def show_usage_providers():
    """Display per-provider usage analytics."""
    from core.analytics import get_provider_stats
    from core.token_manager import human_number

    providers = get_provider_stats("all")
    if not providers:
        console.print("[dim]No provider usage recorded yet.[/dim]\n")
        return

    table = Table(title="Provider Usage Analytics")
    table.add_column("Provider", style="cyan", no_wrap=True)
    table.add_column("Requests", justify="right")
    table.add_column("Success", justify="right")
    table.add_column("Failures", justify="right")
    table.add_column("Success Rate", justify="right")
    table.add_column("Total Tokens", justify="right")
    table.add_column("Avg Latency", justify="right")

    for p in providers:
        avg_lat = p.get("avg_latency_ms")
        lat_str = f"{avg_lat:.0f}ms" if avg_lat is not None else "—"
        tot = human_number(p.get("total_tokens")) if p.get("total_tokens") is not None else "0"
        rate = f"{p['success_rate']:.1f}%"

        table.add_row(
            p["provider"],
            str(p["requests"]),
            str(p["successful"]),
            str(p["failed"]),
            rate,
            tot,
            lat_str,
        )

    console.print(table)
    console.print("\n[dim]Sorted by request count descending.[/dim]\n")


def show_usage_chat():
    """Display usage analytics for currently active chat."""
    from core.analytics import get_chat_stats
    from core.chat_manager import get_current_chat
    from core.token_manager import human_number

    chat = get_current_chat()
    if not chat or not chat.get("id"):
        console.print(
            "[yellow]No active chat session.[/yellow]\n"
            "[dim]Create a chat with /new or load one with /load.[/dim]"
        )
        return

    chat_id = chat["id"]
    title = chat.get("title", "Untitled")
    stats = get_chat_stats(chat_id)

    table = Table(show_header=False, box=None)
    table.add_row("Chat Title", f"[bold cyan]{title}[/bold cyan]")
    table.add_row("Chat ID", f"[dim]{chat_id}[/dim]")
    table.add_row("Total Requests", str(stats["requests"]))

    inp = stats["input_tokens"]
    out = stats["output_tokens"]
    tot = stats["total_tokens"]

    table.add_row("Input Tokens", human_number(inp) if inp is not None else "0")
    table.add_row("Output Tokens", human_number(out) if out is not None else "0")
    table.add_row("Total Tokens", human_number(tot) if tot is not None else "0")

    avg_ms = stats["avg_response_ms"]
    avg_str = f"{avg_ms/1000:.2f}s" if avg_ms is not None else "—"
    table.add_row("Average Response Time", avg_str)

    models_str = ", ".join(stats["models_used"]) if stats["models_used"] else "—"
    table.add_row("Models Used", models_str)

    providers_str = ", ".join(stats["providers_used"]) if stats["providers_used"] else "—"
    table.add_row("Providers Used", providers_str)

    console.print(Panel(table, title="Active Chat Usage Analytics", border_style="cyan"))


def show_usage_db():
    """Display database diagnostics."""
    from core.analytics import get_db_info

    info = get_db_info()

    def _fmt_size(b: int) -> str:
        if b < 1024:
            return f"{b} B"
        elif b < 1024 * 1024:
            return f"{b / 1024:.1f} KB"
        else:
            return f"{b / (1024 * 1024):.2f} MB"

    table = Table(show_header=False, box=None)
    table.add_row("Database Path", info["db_path"])
    table.add_row("Database Size", _fmt_size(info["db_size_bytes"]))
    table.add_row("Total Analytics Rows", str(info["total_rows"]))
    table.add_row("Oldest Record", info["oldest_record"] or "—")
    table.add_row("Newest Record", info["newest_record"] or "—")

    console.print(Panel(table, title="Analytics Database Diagnostics", border_style="cyan"))


# ------------------------------------------------------------------
# HELP
# ------------------------------------------------------------------

def show_help():
    """Print the command reference and keyboard shortcut tables."""
    commands = [
        ("/providers",       "Show provider health dashboard"),
        ("/providers nvidia", "Provider detail / filter"),
        ("/models",      "Show models"),
        ("/models gemini", "Filter models"),
        ("/use 4",       "Select model from last list"),
        ("/use model-id", "Select exact model"),
        ("/model",       "Show model information"),
        ("/limits",      "Show token limits"),
        ("/usage",       "Show token usage & today summary"),
        ("/usage today", "Analytics for today"),
        ("/usage week",  "Analytics for last 7 days"),
        ("/usage month", "Analytics for last 30 days"),
        ("/usage all",   "All-time analytics"),
        ("/usage models","Per-model usage breakdown"),
        ("/usage providers", "Per-provider usage breakdown"),
        ("/usage chat",  "Usage for current chat"),
        ("/usage db",    "Database diagnostics"),
        ("/refresh",     "Reload model catalog"),
        ("/pick",        "Interactive model picker"),
        ("/pick nvidia",  "Picker pre-filtered by keyword"),
        ("/stream",      "Show streaming state (or /stream on|off)"),
        ("/auto",        "Automatic routing"),
        ("/smart",       "Smart routing"),
        ("/fast",        "Fast routing"),
        ("/code",        "Coding routing"),
        ("/free",        "Free models overview & summary"),
        ("/free list",   "List verified-free models"),
        ("/free status", "Show registry verification status"),
        ("/free verify", "Show models needing verification or verify"),
        ("/free refresh","Recalculate staleness & rebuild catalog"),
        ("/new",         "Create new chat"),
        ("/chats",       "Show saved chats"),
        ("/load 2",      "Load chat"),
        ("/delete 2",    "Delete chat"),
        ("/title name",  "Rename chat"),
        ("/history",     "Show history"),
        ("/clear",       "Clear current conversation"),
        ("/attach <path>","Attach a text/code file to chat"),
        ("/files",       "List attached files and status"),
        ("/remove <n>",  "Remove attached file by number"),
        ("/clearfiles",  "Clear all attached files"),
        ("/kb add <path>","Add PDF/text to knowledge base"),
        ("/kb list",     "List knowledge base documents"),
        ("/kb search <q>","Semantic search knowledge base"),
        ("/kb remove <n>","Remove document from KB"),
        ("/kb status",   "Show KB and vector index stats"),
        ("/rag",         "Show RAG status (or /rag on|off)"),
        ("/project <path>","Activate project coding assistant"),
        ("/project status","Show project metadata & frameworks"),
        ("/project off", "Disable project context"),
        ("/project refresh","Rescan and update project index"),
        ("/tree [depth]","Display project directory tree"),
        ("/find <query>","Search project files, symbols, & code"),
        ("/read <path> [range]","Safely view project file with lines"),
        ("/edit <instruction>","Propose safe code changes to project"),
        ("/diff",            "Preview pending edit as unified diff"),
        ("/apply",           "Apply pending edit (requires confirmation)"),
        ("/discard",         "Discard pending edit proposal"),
        ("/changes",         "Show edit history for current project"),
        ("/undo",            "Undo last applied edit (requires confirmation)"),
        ("/run <command>",   "Run terminal command safely (requires confirmation)"),
        ("/run --background <cmd>", "Run long-running command in background"),
        ("/agent",           "Show/toggle agent mode (/agent on|off|status)"),
        ("/jobs",            "List background jobs (or /jobs <id> for output)"),
        ("/kill <job-id>",   "Stop an AIZEN background job (requires confirmation)"),
        ("/lastcmd",         "Show last executed command details and output"),
        ("/mode",            "Show current router mode or change (/mode auto|coding|...)"),
        ("/router",          "Show smart router status (auto-selects free models)"),
        ("/router on",       "Enable automatic smart routing (Free-Only)"),
        ("/router off",      "Disable smart routing (use current model)"),
        ("/router status",   "Show smart router configuration and status"),
        ("/router verbose",  "Enable routing decision preview before replies"),
        ("/router quiet",    "Disable verbose routing decision preview"),
        ("/router explain",  "Show detailed breakdown of last routing decision"),
        ("/router manual",   "Disable smart routing and lock to current model"),
        ("/router history",  "Show history of recent routing decisions"),
        ("/skills",          "List loaded project rules and agent skills"),
        ("/skills reload",   "Rescan and reload .agents/ rules and skills"),
        ("/tools",           "List available native execution tools and schemas"),
        ("/tools status",    "Show native tool execution status"),
        ("/voice",           "Show voice subsystem status"),
        ("/voice on|off",    "Enable / disable voice mode"),
        ("/voice input on|off",  "Enable / disable microphone input"),
        ("/voice output on|off", "Enable / disable text-to-speech output"),
        ("/voice devices",   "List audio input/output devices"),
        ("/voice voices",    "List available TTS voices"),
        ("/voice speed 1.2", "Set TTS speech speed (0.5–3.0)"),
        ("/voice language ta","Set STT language (en, ta, auto)"),
        ("/voice stop",      "Stop current TTS speech output"),
        ("/cls",         "Clear screen + restore AIZEN home"),
        ("/status",      "Show status"),
        ("/help",        "Show commands"),
        ("/version",     "Show AIZEN AI version"),
        ("/debug on|off","Toggle debug mode (verbose errors + timing)"),
        ("/doctor",      "Run system health diagnostics"),
        ("/exit",        "Exit AIZEN"),
    ]

    cmd_table = Table(title="AIZEN Commands")
    cmd_table.add_column("Command", style="cyan")
    cmd_table.add_column("Description")

    for cmd, desc in commands:
        cmd_table.add_row(cmd, desc)

    console.print(cmd_table)
    console.print("[dim]* All terminal execution requires confirmation. Commands are classified: READ_ONLY, SAFE_BUILD, WRITE, DANGEROUS, BLOCKED.[/dim]\n")

    shortcuts = [
        ("← / →",           "Move one character"),
        ("Home / End",       "Start / end"),
        ("Ctrl + ← / →",    "Move by word"),
        ("Ctrl + A / E",     "Start / end"),
        ("Ctrl + W",         "Delete previous word"),
        ("Ctrl + U",         "Delete before cursor"),
        ("Ctrl + K",         "Delete after cursor"),
        ("↑ / ↓",            "Prompt history"),
        ("Ctrl + R",         "Search history"),
        ("Ctrl + L",         "Clear + restore AIZEN"),
        ("Ctrl + N",         "New chat"),
        ("Ctrl + G",         "Coding mode"),
        ("Alt + S",          "Smart mode"),
        ("Alt + F",          "Fast mode"),
        ("Alt + A",          "Auto mode"),
        ("Alt + M",          "Interactive model picker"),
        ("Alt + V",          "Push-to-talk (voice input)"),
        ("Ctrl + D",         "Exit"),
    ]

    kb_table = Table(title="Keyboard Shortcuts")
    kb_table.add_column("Shortcut", style="green")
    kb_table.add_column("Action")

    for shortcut, action in shortcuts:
        kb_table.add_row(shortcut, action)

    console.print(kb_table)


# ------------------------------------------------------------------
# PROVIDER HEALTH VIEWS
# ------------------------------------------------------------------

def show_providers(filter_text=""):
    """
    Display a Rich table of all known providers with health metrics.
    If filter_text is given, show only providers whose name contains it.
    """
    from core.provider_health import (
        get_all_providers, get_provider_record, get_provider_status,
        STATUS_COLORS, STATUS_SYMBOLS,
    )

    query = (filter_text or "").strip().lower()
    all_providers = get_all_providers()

    matched = (
        [p for p in all_providers if query in p.lower()]
        if query else all_providers
    )

    if not matched:
        console.print(
            f"[yellow]No providers matching '{filter_text}'.[/yellow]\n"
            "[dim]Run /providers to see all.[/dim]"
        )
        return

    # If exactly one match and filter was given → show detail view
    if len(matched) == 1 and query:
        show_provider_detail(matched[0])
        return

    title = f"Provider Health — {filter_text}" if filter_text else "Provider Health Dashboard"
    table = Table(title=title)
    table.add_column("Provider",   style="cyan", no_wrap=True)
    table.add_column("Status",     no_wrap=True)
    table.add_column("Models",     justify="right")
    table.add_column("Avg Lat",    justify="right")
    table.add_column("Success",    justify="right")
    table.add_column("Failures",   justify="right")
    table.add_column("Last Used",  justify="left")
    table.add_column("Last Error", justify="left")

    for pname in matched:
        record  = get_provider_record(pname) or {}
        status  = get_provider_status(pname)
        color   = STATUS_COLORS.get(status, "dim")
        symbol  = STATUS_SYMBOLS.get(status, "·")

        avg_lat = record.get("average_latency_ms")
        lat_str = f"{avg_lat:.0f}ms" if avg_lat is not None else "—"

        success = str(record.get("success_count", 0))
        failure = str(record.get("failure_count", 0))
        num_models = str(len(record.get("available_models", [])))

        last_model = record.get("last_used_model") or "—"
        if len(last_model) > 32:
            last_model = last_model[:29] + "…"

        last_err = record.get("last_error") or ""
        last_code = record.get("last_error_code")
        if last_code:
            err_short = f"HTTP {last_code}"
        elif last_err:
            err_short = last_err[:30]
        else:
            err_short = "—"

        table.add_row(
            pname,
            f"[{color}]{symbol} {status}[/{color}]",
            num_models,
            lat_str,
            success,
            failure,
            last_model,
            err_short,
        )

    console.print(table)
    console.print(
        "\n[dim]Use [cyan]/providers <name>[/cyan] for detailed view.[/dim]\n"
    )


def show_provider_detail(provider_name: str):
    """
    Render a detailed Rich panel for a single provider including
    all health metrics and a list of its models.
    """
    from core.provider_health import (
        get_provider_record, get_provider_status,
        STATUS_COLORS, STATUS_SYMBOLS,
    )
    from core.token_manager import human_number

    record = get_provider_record(provider_name)
    if record is None:
        console.print(
            f"[yellow]Provider '[bold]{provider_name}[/bold]' not found.[/yellow]\n"
            "[dim]Run /providers to see known providers.[/dim]"
        )
        return

    status = get_provider_status(provider_name)
    color  = STATUS_COLORS.get(status, "dim")
    symbol = STATUS_SYMBOLS.get(status, "·")

    avg_lat    = record.get("average_latency_ms")
    recent_lat = record.get("recent_latency_ms")

    table = Table(show_header=False, box=None)
    table.add_row("Provider",             f"[bold cyan]{provider_name}[/bold cyan]")
    table.add_row("Status",               f"[{color}]{symbol} {status}[/{color}]")
    table.add_row("Available Models",     str(len(record.get("available_models", []))))
    table.add_row(
        "Average Latency",
        f"{avg_lat:.0f} ms" if avg_lat is not None else "—"
    )
    table.add_row(
        "Recent Latency",
        f"{recent_lat:.0f} ms" if recent_lat is not None else "—"
    )
    table.add_row("Success Count",        str(record.get("success_count", 0)))
    table.add_row("Failure Count",        str(record.get("failure_count", 0)))
    table.add_row("Consecutive Failures", str(record.get("consecutive_failures", 0)))
    table.add_row("Last Success",         record.get("last_success") or "—")
    table.add_row("Last Failure",         record.get("last_failure") or "—")
    table.add_row("Last Error",           (record.get("last_error") or "—")[:80])
    table.add_row("Last Error Code",      str(record.get("last_error_code") or "—"))
    table.add_row("Last Used Model",      record.get("last_used_model") or "—")
    if record.get("rate_limited_until"):
        table.add_row("Rate Limited Until", record["rate_limited_until"])

    console.print(Panel(
        table,
        title=f"[bold]{provider_name}[/bold] — Provider Health",
        border_style="cyan"
    ))

    # List the provider's models
    models = record.get("available_models", [])
    if models:
        model_table = Table(title=f"{provider_name} Models")
        model_table.add_column("Model",   style="cyan")
        model_table.add_column("Context", justify="right")
        model_table.add_column("Output",  justify="right")
        model_table.add_column("Capabilities")

        for mid in sorted(models):
            meta = config.model_map.get(mid, {})
            ctx  = human_number(meta.get("context_length"))
            out  = human_number(meta.get("max_output_tokens"))
            caps = meta.get("capabilities", {})
            cap_tags = []
            if caps.get("reasoning"):    cap_tags.append("reasoning")
            if caps.get("thinking"):     cap_tags.append("thinking")
            if caps.get("tool_calling"): cap_tags.append("tool calling")
            if caps.get("vision"):       cap_tags.append("vision")
            model_table.add_row(mid, ctx, out, ", ".join(cap_tags) or "—")

        console.print(model_table)
    else:
        console.print("[dim]No models listed for this provider.[/dim]\n")


# ------------------------------------------------------------------
# TOOLS DISPLAY
# ------------------------------------------------------------------

def show_tools(argument: str = ""):
    """Display native tools and their status."""
    import os
    from rich.panel import Panel
    from rich.table import Table
    import config
    from core.tool_registry import registry

    sub = (argument or "").strip().lower()
    if sub == "status":
        tbl = Table(show_header=False, box=None)
        tbl.add_row("Registered Tools", f"[bold green]{len(registry.list_tools())} loaded[/bold green]")
        tbl.add_row("Execution Engine", "[bold cyan]Active (safe sandbox & boundary check)[/bold cyan]")
        boundary = getattr(config, "active_project_dir", None) or os.getcwd()
        tbl.add_row("Allowed Boundary", boundary)
        tbl.add_row("Max Loop Iterations", "8 per turn")
        console.print(Panel(tbl, title="Native Tool Execution Status", border_style="cyan"))
        return

    table = Table(title="Available Native Tools")
    table.add_column("Tool", style="bold cyan")
    table.add_column("Description")
    table.add_column("Parameters", style="dim")
    table.add_column("Aliases", style="magenta")

    for t in registry.list_tools():
        props = t.parameters.get("properties", {})
        req = set(t.parameters.get("required", []))
        param_strs = []
        for p, p_info in props.items():
            is_req = "*" if p in req else ""
            param_strs.append(f"{p}{is_req} ({p_info.get('type', 'any')})")
        params_display = ", ".join(param_strs) if param_strs else "none"
        alias_display = ", ".join(t.aliases) if t.aliases else "—"
        table.add_row(t.name, t.description, params_display, alias_display)

    console.print(table)
    console.print("[dim]* = required parameter. Use /tools status for execution engine details.[/dim]\n")


# ------------------------------------------------------------------
# FREE MODEL REGISTRY DISPLAYS (Phase 13)
# ------------------------------------------------------------------

def show_free_models_overview():
    """Display the AIZEN Free Models catalog overview with summary statistics."""
    from rich.table import Table
    from rich.panel import Panel
    from core.free_model_registry import get_free_registry

    reg = get_free_registry()
    verified_records = reg.get_verified_free_models()
    stale_records = reg.get_stale_models()
    raw_catalog = getattr(config, "raw_model_catalog", []) or getattr(config, "model_catalog", [])
    unknown_models = reg.get_unknown_models(raw_catalog)
    hidden_models = reg.get_hidden_models(raw_catalog)

    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
    table.add_column("Provider", style="magenta")
    table.add_column("Model", style="white")
    table.add_column("Status", style="bold green")

    if verified_records:
        for r in verified_records:
            table.add_row(r.provider.upper(), r.model, "VERIFIED")
    else:
        table.add_row("—", "[dim]No verified-free models currently available[/dim]", "[red]NONE[/red]")

    content = Table.grid(padding=(0, 1))
    content.add_column()
    content.add_row(table)
    content.add_row("")
    content.add_row(f"[bold]Verified Free:[/bold]  [green]{len(verified_records)}[/green]")
    content.add_row(f"[bold]Hidden / Paid:[/bold]  [yellow]{len(hidden_models)}[/yellow]")
    content.add_row(f"[bold]Stale:[/bold]          [yellow]{len(stale_records)}[/yellow]")
    content.add_row(f"[bold]Unknown:[/bold]        [dim]{len(unknown_models)}[/dim]")
    content.add_row("")
    content.add_row("[dim]Policy: Strict Default Deny — Unknown & Stale models are hidden.[/dim]")
    content.add_row("[dim]Commands: /free list • /free status • /free verify • /free refresh[/dim]")

    console.print(Panel(content, title="AIZEN FREE MODELS", border_style="cyan"))


def show_free_models_list():
    """Display detailed list of all currently verified-free models."""
    from rich.table import Table
    from core.free_model_registry import get_free_registry

    reg = get_free_registry()
    verified_records = reg.get_verified_free_models()

    if not verified_records:
        console.print("[yellow]No models are currently verified as free.[/yellow]")
        console.print("[dim]Run /free status or /free refresh to inspect registry state.[/dim]\n")
        return

    table = Table(title="AIZEN Verified Free Models", header_style="bold cyan")
    table.add_column("Provider", style="magenta")
    table.add_column("Model", style="bold white")
    table.add_column("Display Name", style="cyan")
    table.add_column("Verified Date", style="dim")
    table.add_column("Status", style="bold green")

    for r in verified_records:
        table.add_row(
            r.provider.upper(),
            r.model,
            r.display_name or r.model,
            r.verified_at or "Unknown",
            "VERIFIED FREE",
        )

    console.print(table)
    console.print(f"[dim]Total verified-free models: {len(verified_records)} (Verification window: {getattr(config, 'free_verification_days', 30)} days)[/dim]\n")


def show_free_registry_status():
    """Display Free Model Registry status and policy information."""
    from rich.table import Table
    from rich.panel import Panel
    from datetime import datetime, timezone
    from core.free_model_registry import get_free_registry

    reg = get_free_registry()
    verified = reg.get_verified_free_models()
    stale = reg.get_stale_models()

    if not getattr(config, "raw_model_catalog", None):
        try:
            from api.omniroute import fetch_models
            fetch_models(show_message=False)
        except Exception:
            pass

    raw_catalog = getattr(config, "raw_model_catalog", []) or getattr(config, "model_catalog", [])
    unknown = reg.get_unknown_models(raw_catalog)
    hidden = reg.get_hidden_models(raw_catalog)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    v_days = getattr(config, "free_verification_days", 30)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")

    table.add_row("Verified Free", f"[bold green]{len(verified)}[/bold green]")
    table.add_row("Stale", f"[yellow]{len(stale)}[/yellow]")
    table.add_row("Unknown", f"[dim]{len(unknown)}[/dim]")
    table.add_row("Hidden / Paid", f"[red]{len(hidden)}[/red]")
    table.add_row("Total Discovered", str(len(raw_catalog)))
    table.add_row("Registry Checked", now_str)
    table.add_row("Verification Window", f"{v_days} days (free_verification_days)")
    table.add_row("Verification Policy", "[bold red]Strict Default Deny[/bold red]")
    table.add_row("Policy Detail", "Only models verified zero-cost with current evidence are permitted")

    console.print(Panel(table, title="Free Registry Status", border_style="cyan"))


def show_free_verify(argument: str = ""):
    """Explain models requiring verification or manually record verification evidence."""
    from core.free_model_registry import get_free_registry

    reg = get_free_registry()
    arg = (argument or "").strip()

    if not arg:
        verified = reg.get_verified_free_models()
        stale = reg.get_stale_models()
        raw_catalog = getattr(config, "raw_model_catalog", []) or getattr(config, "model_catalog", [])
        unknown = reg.get_unknown_models(raw_catalog)

        console.print("\n[bold cyan]AIZEN Free Verification[/bold cyan]\n")
        console.print("[bold green]Verified:[/bold green]")
        if verified:
            for v in verified:
                console.print(f"  [green]✓[/green] {v.provider}/{v.model} [dim]({v.verification_source})[/dim]")
        else:
            console.print("  [dim]No models currently verified free[/dim]")

        console.print("\n[bold yellow]Needs verification:[/bold yellow]")
        needs = []
        for s in stale:
            needs.append(f"  [yellow]![/yellow] {s.provider}/{s.model} [dim](Reason: Verification is stale > {getattr(config, 'free_verification_days', 30)} days)[/dim]")
        for u in unknown[:10]:
            prov = u.get("owned_by") or (u.get("id", "").split("/")[0] if "/" in u.get("id", "") else "unknown")
            needs.append(f"  [dim]?[/dim] {prov}/{u.get('id')} [dim](Reason: Current free-access evidence is unavailable or unverified)[/dim]")

        if needs:
            for item in needs:
                console.print(item)
            if len(unknown) > 10:
                console.print(f"  [dim]... and {len(unknown) - 10} more unverified models in discovered catalog[/dim]")
        else:
            console.print("  [dim]None[/dim]")

        console.print("\n[bold]Reason:[/bold] Current free-access evidence is unavailable, expired, or stale.")
        console.print("[dim]To verify a model with documented official evidence:[/dim]")
        console.print("[cyan]/free verify <provider> <model_id> <source_citation> [optional display name][/cyan]\n")
        return

    parts = arg.split(maxsplit=3)
    if len(parts) < 3:
        console.print("[red]Usage: /free verify <provider> <model_id> <source_citation> [optional display name][/red]")
        return

    prov = parts[0]
    mid = parts[1]
    src = parts[2]
    disp = parts[3] if len(parts) > 3 else mid.split("/")[-1].title()

    rec = reg.verify_model(
        provider=prov,
        model=mid,
        display_name=disp,
        source=src,
        notes="Manually verified with official documentation citation.",
    )
    console.print(f"[green]✓ Verified model registered:[/green] [bold]{rec.provider}/{rec.model}[/bold]")
    console.print(f"[dim]Source: {rec.verification_source}[/dim]")
    console.print(f"[dim]Verified Date: {rec.verified_at}[/dim]\n")


def show_free_refresh():
    """Recalculate staleness and rebuild the free model catalog without paid requests."""
    from core.free_model_registry import get_free_registry

    reg = get_free_registry()
    stats = reg.refresh()

    console.print("\n[green]✓ Free Model Registry refreshed.[/green]")
    console.print(f"Verified Free: [bold green]{stats['verified_count']}[/bold green] | "
                  f"Stale: [bold yellow]{stats['stale_count']}[/bold yellow] | "
                  f"Unknown: [dim]{stats['unknown_count']}[/dim] | "
                  f"Hidden/Paid: [red]{stats['hidden_count']}[/red]")
    console.print(f"[dim]Checked at {stats['checked_at']}. Rebuilt free catalog ({len(getattr(config, 'model_catalog', []))} active models).[/dim]\n")


