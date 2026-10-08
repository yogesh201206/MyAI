"""
commands/handlers.py — Slash-command dispatcher.

handle_command() receives the raw input string (e.g. "/use 3") and
routes it to the appropriate function in core or ui.
"""

import config
from core.storage import save_config
from ui.console import console


def handle_command(command):
    """Parse and dispatch a slash command."""
    parts = command.split(maxsplit=1)
    cmd = parts[0].lower()
    argument = parts[1] if len(parts) > 1 else ""

    # ---- MODEL COMMANDS ----

    if cmd == "/models":
        from core.model_manager import show_models
        show_models(argument)

    elif cmd == "/use":
        from core.model_manager import select_model
        select_model(argument)

    elif cmd in ("/model", "/limits"):
        from ui.console import show_model_info
        show_model_info()

    elif cmd == "/usage":
        from ui.console import show_usage
        show_usage(argument)

    elif cmd == "/refresh":
        from api.omniroute import fetch_models
        from ui.console import show_model_info
        fetch_models(show_message=True)
        show_model_info()

    elif cmd == "/auto":
        config.current_model = "auto"
        config.model_selection_mode = "router"
        config.router_mode = "AUTO"
        save_config()
        console.print("[green]AUTO mode enabled (Free-Only Smart Router).[/green]")
        from ui.console import show_model_info
        show_model_info(selected_message=True)

    elif cmd == "/smart":
        config.current_model = "auto"
        config.model_selection_mode = "router"
        config.router_mode = "AUTO"
        save_config()
        console.print("[green]Smart router mode enabled (Free-Only).[/green]")
        from ui.console import show_model_info
        show_model_info(selected_message=True)

    elif cmd == "/fast":
        config.current_model = "auto"
        config.model_selection_mode = "router"
        config.router_mode = "FAST"
        save_config()
        console.print("[green]Fast router mode enabled (Free-Only).[/green]")
        from ui.console import show_model_info
        show_model_info(selected_message=True)

    elif cmd == "/code":
        config.current_model = "auto"
        config.model_selection_mode = "router"
        config.router_mode = "CODING"
        save_config()
        console.print("[green]Coding router mode enabled (Free-Only).[/green]")
        from ui.console import show_model_info
        show_model_info(selected_message=True)

    elif cmd == "/free":
        sub = argument.strip()
        parts_sub = sub.split(maxsplit=1)
        subcmd = parts_sub[0].lower() if parts_sub else ""
        subarg = parts_sub[1] if len(parts_sub) > 1 else ""

        if not subcmd:
            from ui.console import show_free_models_overview
            show_free_models_overview()
        elif subcmd == "list":
            from ui.console import show_free_models_list
            show_free_models_list()
        elif subcmd == "status":
            from ui.console import show_free_registry_status
            show_free_registry_status()
        elif subcmd == "verify":
            from ui.console import show_free_verify
            show_free_verify(subarg)
        elif subcmd == "refresh":
            from ui.console import show_free_refresh
            show_free_refresh()
        else:
            console.print(f"[yellow]Unknown /free option: '{subcmd}'.[/yellow]")
            console.print("[dim]Available commands: /free, /free list, /free status, /free verify, /free refresh[/dim]\n")

    # ---- CHAT COMMANDS ----

    elif cmd == "/new":
        from core.chat_manager import create_new_chat
        from ui.console import show_model_info
        create_new_chat()
        show_model_info()

    elif cmd == "/chats":
        from core.chat_manager import show_chats
        show_chats()

    elif cmd == "/load":
        if argument:
            from core.chat_manager import load_chat
            load_chat(argument)
        else:
            console.print("[yellow]Usage: /load <number>[/yellow]")

    elif cmd == "/delete":
        if argument:
            from core.chat_manager import delete_chat
            delete_chat(argument)
        else:
            console.print("[yellow]Usage: /delete <number>[/yellow]")

    elif cmd == "/title":
        from core.chat_manager import rename_chat
        rename_chat(argument)

    elif cmd == "/history":
        from core.chat_manager import show_history
        show_history()

    elif cmd == "/clear":
        from core.chat_manager import clear_chat
        clear_chat()

    # ---- FILE ATTACHMENTS ----

    elif cmd == "/attach":
        from core.file_manager import attach_file
        attach_file(argument)

    elif cmd == "/files":
        from core.file_manager import show_files
        show_files()

    elif cmd == "/remove":
        from core.file_manager import remove_attachment
        remove_attachment(argument)

    elif cmd == "/clearfiles":
        from core.file_manager import clear_attachments
        clear_attachments()

    # ---- DISPLAY COMMANDS ----

    elif cmd in ("/cls", "/clear-screen"):
        from ui.console import show_aizen_home
        show_aizen_home()

    elif cmd == "/status":
        from ui.console import show_status
        show_status()

    elif cmd == "/help":
        from ui.console import show_help
        show_help()

    # ---- PICKER ----

    elif cmd == "/pick":
        from ui.picker import run_picker
        run_picker(argument)

    # ---- PROVIDER HEALTH ----

    elif cmd == "/providers":
        from ui.console import show_providers
        show_providers(argument)

    # ---- STREAMING ----

    elif cmd == "/stream":
        arg = argument.strip().lower()
        if not arg:
            state = "[green]ON[/green]" if config.streaming_enabled else "[yellow]OFF[/yellow]"
            console.print(
                f"Streaming is currently {state}. "
                "[dim](Use [cyan]/stream on[/cyan] or [cyan]/stream off[/cyan])[/dim]"
            )
        elif arg == "on":
            config.streaming_enabled = True
            save_config()
            console.print("[green]Streaming enabled (ON).[/green]")
        elif arg == "off":
            config.streaming_enabled = False
            save_config()
            console.print("[yellow]Streaming disabled (OFF).[/yellow]")
        else:
            console.print("[yellow]Usage: /stream [on|off][/yellow]")

    # ---- KNOWLEDGE BASE & RAG ----

    elif cmd == "/kb":
        parts = argument.strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        sub_arg = parts[1] if len(parts) > 1 else ""

        if sub == "add":
            from core.kb_manager import add_document
            add_document(sub_arg)
        elif sub == "list":
            from core.kb_manager import list_documents
            list_documents()
        elif sub == "search":
            from core.kb_manager import handle_search_command
            handle_search_command(sub_arg)
        elif sub == "remove":
            from core.kb_manager import remove_document
            remove_document(sub_arg)
        elif sub == "clear":
            from core.kb_manager import clear_kb
            clear_kb()
        elif sub in ("status", ""):
            from core.kb_manager import show_kb_status
            show_kb_status()
        else:
            console.print(
                f"[yellow]Unknown /kb command '{sub}'.[/yellow]\n"
                "[dim]Available: /kb [add <path>|list|search <query>|remove <id>|clear|status][/dim]"
            )

    elif cmd == "/rag":
        arg = argument.strip().lower()
        if not arg:
            state = "[green]ON[/green]" if config.rag_enabled else "[yellow]OFF[/yellow]"
            console.print(
                f"RAG retrieval is currently {state}. "
                "[dim](Use [cyan]/rag on[/cyan] or [cyan]/rag off[/cyan])[/dim]"
            )
        elif arg == "on":
            config.rag_enabled = True
            save_config()
            console.print("[green]RAG automatic retrieval enabled (ON).[/green]")
        elif arg == "off":
            config.rag_enabled = False
            save_config()
            console.print("[yellow]RAG automatic retrieval disabled (OFF).[/yellow]")
        else:
            console.print("[yellow]Usage: /rag [on|off][/yellow]")

    # ---- PROJECT COMMANDS ----

    elif cmd == "/project":
        arg = argument.strip()
        sub = arg.lower()

        if sub == "off":
            from core.project_manager import deactivate_project
            msg = deactivate_project()
            console.print(f"[yellow]{msg}[/yellow]")

        elif sub == "refresh":
            from core.project_manager import refresh_project
            success, msg = refresh_project()
            console.print(msg)

        elif sub in ("status", ""):
            from core.project_manager import get_project_status
            st = get_project_status()
            from rich.table import Table
            from rich.panel import Panel
            import time

            t = Table(show_header=False, box=None)
            t.add_row("Project Name", f"[bold cyan]{st['project_name']}[/bold cyan]")
            t.add_row("Root Path", st['root_path'])
            mode_color = "green" if st['mode'] == "ON" else "yellow"
            t.add_row("Mode", f"[{mode_color}]{st['mode']}[/{mode_color}]")
            t.add_row("Status", st['status'])
            t.add_row("Indexed Files", str(st['indexed_files']))
            t.add_row("Supported Files", str(st['supported_files']))
            t.add_row("Ignored Files", str(st['ignored_files']))
            lang_str = ", ".join(st['languages']) if st['languages'] else "None"
            t.add_row("Languages", lang_str)
            fw_str = ", ".join(st['frameworks']) if st['frameworks'] else "None"
            t.add_row("Frameworks", fw_str)
            if st['last_updated'] > 0:
                t.add_row("Last Updated", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st['last_updated'])))
            console.print(Panel(t, title="Project Status", border_style="cyan"))

        else:
            from core.project_manager import activate_project
            success, msg = activate_project(arg)
            console.print(msg)

    elif cmd == "/tree":
        from core.project_manager import get_project_tree
        depth = 3
        arg = argument.strip()
        if arg.isdigit():
            depth = max(1, min(10, int(arg)))
        tree_text = get_project_tree(max_depth=depth)
        from rich.panel import Panel
        console.print(Panel(tree_text, title=f"Project Tree (depth {depth})", border_style="dim"))

    elif cmd == "/find":
        query = argument.strip()
        if not query:
            console.print("[yellow]Usage: /find <query>[/yellow]")
        else:
            from core.project_manager import search_project
            from rich.table import Table
            matches = search_project(query, limit=20)
            if not matches:
                console.print(f"[dim]No matches found for '{query}'.[/dim]")
            else:
                tbl = Table(title=f"Search Results for '{query}'")
                tbl.add_column("#", style="dim", width=4)
                tbl.add_column("File", style="cyan")
                tbl.add_column("Line", style="magenta", width=6)
                tbl.add_column("Match Type", style="green")
                tbl.add_column("Preview", style="white")

                for m in matches:
                    tbl.add_row(
                        str(m["rank"]),
                        m["file"],
                        str(m["line"]),
                        m["match_type"],
                        m["preview"]
                    )
                console.print(tbl)

    elif cmd == "/read":
        arg = argument.strip()
        if not arg:
            console.print("[yellow]Usage: /read <relative-path> [start-end][/yellow]")
        else:
            parts = arg.split(maxsplit=1)
            rel_file = parts[0]
            l_range = parts[1] if len(parts) > 1 else None
            from core.project_manager import read_project_file
            from rich.panel import Panel
            success, out = read_project_file(rel_file, l_range)
            if success:
                console.print(Panel(out, border_style="cyan"))
            else:
                console.print(f"[bold red]Error: {out}[/bold red]")

    # ---- PHASE 9: EDIT COMMANDS ----

    elif cmd == "/edit":
        instruction = argument.strip()
        if not instruction:
            console.print("[yellow]Usage: /edit <instruction>[/yellow]")
        else:
            from core.edit_manager import generate_edit_proposal
            with console.status(
                "[bold cyan]Analyzing project and preparing changes...[/bold cyan]",
                spinner="dots"
            ):
                success, msg = generate_edit_proposal(instruction)
            console.print(msg)

    elif cmd == "/diff":
        from core.edit_manager import show_pending_diff
        show_pending_diff()

    elif cmd == "/apply":
        from core.edit_manager import apply_pending_edit, show_pending_diff
        from rich.panel import Panel

        if config.pending_edit is None:
            console.print("[yellow]No pending edit. Use [cyan]/edit <instruction>[/cyan] first.[/yellow]")
        else:
            # Show brief summary before confirm
            show_pending_diff()
            changes = config.pending_edit["changes"]
            n_files = len({c["file"] for c in changes})
            console.print(
                f"\n[bold yellow]Apply {len(changes)} change(s) across {n_files} file(s)?[/bold yellow] "
                "[dim][y/N][/dim] ",
                end=""
            )
            try:
                answer = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            confirmed = answer in ("y", "yes")
            success, msg = apply_pending_edit(confirmed)
            console.print(msg)
            if success:
                try:
                    from core.agent_manager import suggest_validation_command
                    vcmd = suggest_validation_command()
                    if vcmd:
                        console.print(f"\n[cyan]Recommended validation:[/cyan] [bold]{vcmd}[/bold]")
                        console.print(f"[bold yellow]Run now?[/bold yellow] [dim][y/N][/dim] ", end="")
                        try:
                            v_ans = input().strip().lower()
                        except (EOFError, KeyboardInterrupt):
                            v_ans = "n"
                        if v_ans in ("y", "yes"):
                            handle_command(f"/run {vcmd}")
                except Exception:
                    pass

    elif cmd == "/discard":
        from core.edit_manager import discard_pending_edit
        msg = discard_pending_edit()
        console.print(msg)

    elif cmd == "/changes":
        from core.edit_manager import get_changes_history
        from rich.table import Table
        from rich.panel import Panel

        history = get_changes_history()
        if not history:
            console.print("[dim]No edit history for this project.[/dim]")
        else:
            tbl = Table(title="Edit History", expand=False)
            tbl.add_column("ID",          style="dim",    max_width=10)
            tbl.add_column("Time",        style="cyan",   max_width=20)
            tbl.add_column("Instruction", style="white",  max_width=50)
            tbl.add_column("Files",       style="magenta", max_width=6)
            tbl.add_column("Status",      style="bold",   max_width=12)

            status_colors = {
                "PENDING":   "yellow",
                "APPLIED":   "green",
                "DISCARDED": "dim",
                "UNDONE":    "dim",
                "FAILED":    "red",
            }

            for row in history:
                s = row.get("status", "")
                c = status_colors.get(s, "white")
                short_id = row.get("session_id", "")[:8]
                tbl.add_row(
                    short_id,
                    row.get("created_at", "")[:16],
                    row.get("instruction", "")[:50],
                    str(row.get("files_changed", 0)),
                    f"[{c}]{s}[/{c}]",
                )
            console.print(tbl)

    elif cmd == "/undo":
        from core.edit_manager import get_undo_preview, undo_last_edit
        from rich.panel import Panel

        preview = get_undo_preview()
        if not preview:
            console.print("[yellow]No applied edits to undo for this project.[/yellow]")
        else:
            console.print(Panel(
                f"[bold]Undo last edit?[/bold]\n\n"
                f"Instruction: [cyan]{preview.get('instruction', '')}[/cyan]\n"
                f"Applied At:  [dim]{preview.get('applied_at', 'unknown')}[/dim]",
                title="Confirm Undo",
                border_style="yellow",
            ))
            console.print("[bold yellow]Confirm undo?[/bold yellow] [dim][y/N][/dim] ", end="")
            try:
                answer = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            confirmed = answer in ("y", "yes")
            success, msg = undo_last_edit(confirmed)
            console.print(msg)

    # ---- PHASE 10: TERMINAL COMMANDS ----

    elif cmd == "/run":
        from core.command_safety import classify, BLOCKED, DANGEROUS, level_color, level_icon
        from core.command_runner import run_foreground
        from rich.panel import Panel

        arg = argument.strip()
        background = False

        if arg.startswith("--background "):
            background = True
            arg = arg[len("--background "):].strip()
        elif arg.startswith("-bg "):
            background = True
            arg = arg[len("-bg "):].strip()

        if not arg:
            console.print("[yellow]Usage: /run <command>  or  /run --background <command>[/yellow]")
        else:
            safety = classify(arg)
            cwd = config.active_project_path or config.startup_cwd

            if safety.level == BLOCKED:
                console.print(Panel(
                    f"[bold red]{safety.block_message}[/bold red]",
                    title="\u26d4 Command Blocked",
                    border_style="red",
                ))
            else:
                color = level_color(safety.level)
                icon  = level_icon(safety.level)
                affects = (f"\n[bold]Affects:[/bold]   {', '.join(safety.affected_paths)}"
                           if safety.affected_paths else "")
                console.print(Panel(
                    f"[bold]Command:[/bold]   {arg}\n"
                    f"[bold]Directory:[/bold] {cwd}\n"
                    f"[bold]Safety:[/bold]    [{color}]{icon} {safety.level}[/{color}]\n"
                    f"[bold]Reason:[/bold]    {safety.reason}{affects}",
                    title="Proposed Command",
                    border_style=color,
                ))

                if safety.level == DANGEROUS:
                    console.print(
                        "\n[bold red]\u26a0 DANGEROUS COMMAND[/bold red]\n"
                        "Type exactly [bold]EXECUTE[/bold] to confirm, or press Enter to cancel: ",
                        end=""
                    )
                    try:
                        answer = input().strip()
                    except (EOFError, KeyboardInterrupt):
                        answer = ""
                    confirmed = (answer == "EXECUTE")
                else:
                    console.print("[bold yellow]Execute?[/bold yellow] [dim][y/N][/dim] ", end="")
                    try:
                        answer = input().strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        answer = "n"
                    confirmed = answer in ("y", "yes")

                if not confirmed:
                    console.print("[dim]Command cancelled.[/dim]")
                elif background:
                    from core.job_manager import get_job_manager
                    jm = get_job_manager()
                    ok, msg, job = jm.start(arg, cwd, safety)
                    console.print(f"[green]{msg}[/green]" if ok else f"[red]{msg}[/red]")
                else:
                    with console.status(
                        f"[bold cyan]Running: {arg[:60]}[/bold cyan]", spinner="dots"
                    ):
                        result = run_foreground(arg, cwd, safety, timeout=config.command_timeout)

                    output_parts = []
                    if result.stdout:
                        output_parts.append(result.stdout.rstrip())
                    if result.stderr:
                        output_parts.append(f"[stderr]\n{result.stderr.rstrip()}")
                    output_text = "\n".join(output_parts)

                    if result.cancelled:
                        console.print("[yellow]Command cancelled.[/yellow]")
                    elif result.timed_out:
                        console.print(f"[red]Command timed out after {config.command_timeout}s.[/red]")
                    else:
                        if output_text.strip():
                            console.print(Panel(
                                output_text,
                                title="Command Output",
                                border_style="dim",
                            ))
                        else:
                            console.print("[dim](No output)[/dim]")

                    if result.error_message:
                        console.print(f"[red]Error: {result.error_message}[/red]")

                    ec = result.exit_code
                    ec_color = "green" if ec == 0 else "red"
                    console.print(
                        f"Exit Code: [{ec_color}]{ec}[/{ec_color}]  "
                        f"Duration: [dim]{result.duration_ms/1000:.2f}s[/dim]"
                    )
                    if result.truncated:
                        console.print("[dim yellow]Output truncated (size limit reached).[/dim yellow]")

    elif cmd == "/agent":
        arg = argument.strip().lower()
        if arg == "on" or (not arg):
            config.agent_enabled = True
            save_config()
            console.print("[green]Agent mode ON.[/green] AIZEN may now propose terminal commands.")
        elif arg == "off":
            config.agent_enabled = False
            save_config()
            console.print("[yellow]Agent mode OFF.[/yellow]")
        elif arg == "status":
            state = "[green]ON[/green]" if config.agent_enabled else "[yellow]OFF[/yellow]"
            from core.job_manager import get_job_manager
            running = len(get_job_manager().running_jobs())
            console.print(f"Agent mode: {state}  |  Running jobs: {running}")
        else:
            console.print("[yellow]Usage: /agent [on|off|status][/yellow]")

    elif cmd == "/jobs":
        from core.job_manager import get_job_manager, JOB_RUNNING, JOB_EXITED, JOB_FAILED, JOB_STOPPED
        from rich.table import Table
        from rich.panel import Panel

        jm = get_job_manager()
        arg = argument.strip()

        if arg.isdigit():
            job = jm.get(int(arg))
            if not job:
                console.print(f"[red]No job #{arg}.[/red]")
            else:
                output = job.recent_output(n=30)
                console.print(Panel(
                    output or "[dim](no output yet)[/dim]",
                    title=f"Job #{job.job_id}: {job.command[:60]}",
                    border_style="dim",
                ))
        else:
            jobs = jm.list_jobs()
            if not jobs:
                console.print("[dim]No background jobs.[/dim]")
            else:
                status_colors = {
                    JOB_RUNNING: "green", JOB_EXITED: "dim",
                    JOB_FAILED: "red",   JOB_STOPPED: "yellow",
                }
                tbl = Table(title="Background Jobs")
                tbl.add_column("ID",      style="dim",    max_width=6)
                tbl.add_column("PID",     style="dim",    max_width=8)
                tbl.add_column("Command", style="white",  max_width=45)
                tbl.add_column("Status",  style="bold",   max_width=10)
                tbl.add_column("Started", style="cyan",   max_width=18)
                tbl.add_column("Runtime", style="magenta",max_width=10)
                for j in jobs:
                    sc = status_colors.get(j.status, "white")
                    tbl.add_row(
                        str(j.job_id), str(j.pid),
                        j.command[:45],
                        f"[{sc}]{j.status}[/{sc}]",
                        j.started_at[:16],
                        f"{j.runtime_seconds():.0f}s",
                    )
                console.print(tbl)

    elif cmd == "/kill":
        from core.job_manager import get_job_manager
        from rich.panel import Panel

        arg = argument.strip()
        if not arg.isdigit():
            console.print("[yellow]Usage: /kill <job-id>[/yellow]")
        else:
            jm = get_job_manager()
            job_id = int(arg)
            job = jm.get(job_id)
            if not job:
                console.print(f"[red]No job with ID {job_id}.[/red]")
            else:
                console.print(Panel(
                    f"Stop job [bold]{job_id}[/bold]: [cyan]{job.command[:80]}[/cyan]\nPID: {job.pid}",
                    title="Confirm Kill",
                    border_style="yellow",
                ))
                console.print("[bold yellow]Stop this job?[/bold yellow] [dim][y/N][/dim] ", end="")
                try:
                    answer = input().strip().lower()
                except (EOFError, KeyboardInterrupt):
                    answer = "n"
                if answer in ("y", "yes"):
                    ok, msg = jm.kill(job_id)
                    console.print(f"[green]{msg}[/green]" if ok else f"[red]{msg}[/red]")
                else:
                    console.print("[dim]Kill cancelled.[/dim]")

    elif cmd == "/lastcmd":
        from core.command_runner import get_last_command
        from rich.panel import Panel
        from rich.table import Table

        result = get_last_command()
        if result is None:
            console.print("[dim]No command has been executed in this session.[/dim]")
        else:
            tbl = Table(show_header=False, box=None)
            tbl.add_row("Command",   result.command)
            tbl.add_row("Directory", result.cwd)
            tbl.add_row("Safety",    result.safety_level)
            ec_display = str(result.exit_code) if result.exit_code is not None else "\u2014"
            tbl.add_row("Exit Code", ec_display)
            tbl.add_row("Duration",  f"{result.duration_ms/1000:.3f}s")
            tbl.add_row("Timestamp", result.timestamp)
            if result.timed_out:
                tbl.add_row("Note", "[red]Timed out[/red]")
            if result.cancelled:
                tbl.add_row("Note", "[yellow]Cancelled by user[/yellow]")
            console.print(Panel(tbl, title="Last Command", border_style="cyan"))
            if result.stdout.strip():
                console.print(Panel(
                    "\n".join(result.stdout.splitlines()[:30]),
                    title="stdout (preview)", border_style="dim"
                ))
            if result.stderr.strip():
                console.print(Panel(
                    "\n".join(result.stderr.splitlines()[:10]),
                    title="stderr (preview)", border_style="dim red"
                ))

    # ---- PHASE 11: SMART ROUTER ----

    elif cmd == "/mode":
        from core.task_classifier import VALID_MODES
        arg = argument.strip().upper()
        if not arg:
            sel_mode = "[yellow]MANUAL[/yellow]" if getattr(config, "model_selection_mode", "ROUTER").lower() == "manual" else "[green]ROUTER[/green]"
            console.print(f"Router Mode: [bold cyan]{config.router_mode}[/bold cyan]  |  Selection: {sel_mode}")
            console.print("[dim]Usage: /mode [auto|coding|reasoning|fast|chat|research|vision][/dim]")
        elif arg in VALID_MODES:
            config.router_mode = arg
            config.model_selection_mode = "router"
            save_config()
            console.print(f"[bold green]✓ Router mode set to:[/bold green] [cyan]{arg}[/cyan]")
            console.print("[dim]Smart router selection activated.[/dim]")
        else:
            valid_list = ", ".join(sorted([m.lower() for m in VALID_MODES]))
            console.print(f"[red]Unknown mode '{argument.strip()}'.[/red] Choose from: {valid_list}")

    elif cmd == "/router":
        from core.router import format_routing_explanation, count_free_candidates
        from rich.table import Table
        from rich.panel import Panel

        arg = argument.strip().lower()
        if arg in ("", "status"):
            router_on = getattr(config, "router_enabled", True)
            is_manual = getattr(config, "model_selection_mode", "ROUTER").lower() == "manual"
            free_count = count_free_candidates()

            tbl = Table(show_header=False, box=None)

            # Status row
            if not router_on:
                status_str = "[yellow]OFF[/yellow]"
            elif is_manual:
                status_str = "[yellow]ON (Manual override active)[/yellow]"
            else:
                status_str = "[green]ON[/green]"
            tbl.add_row("Router", status_str)

            tbl.add_row("Mode",           f"[bold cyan]{config.router_mode}[/bold cyan]")

            sel_str = ("[yellow]MANUAL OVERRIDE[/yellow]" if is_manual
                       else "[green]AUTOMATIC[/green]")
            tbl.add_row("Selection",      sel_str)
            tbl.add_row("Free Candidates", f"[bold]{free_count}[/bold]")
            tbl.add_row("Max Fallbacks",  str(getattr(config, "router_max_fallbacks", 2)))

            last = getattr(config, "last_routing_decision", None)
            if last:
                tbl.add_row("Last Task",      last.task_type)
                tbl.add_row("Last Model",     last.selected_model or "[dim]None[/dim]")
                tbl.add_row("Last Provider",  last.provider)
                tbl.add_row("Last Reason",    last.reason[:60] if last.reason else "[dim]—[/dim]")
            else:
                tbl.add_row("Last Task",      "[dim]None yet[/dim]")
                tbl.add_row("Current Model",  config.current_model)

            verb_str = "[green]ON[/green]" if getattr(config, "router_verbose", False) else "[dim]OFF[/dim]"
            tbl.add_row("Verbose",         verb_str)

            # Scoring weights
            tbl.add_row("Weight: Capability",   f"{getattr(config,'router_capability_weight', 0.40):.0%}")
            tbl.add_row("Weight: Context",      f"{getattr(config,'router_context_weight', 0.20):.0%}")
            tbl.add_row("Weight: Health",       f"{getattr(config,'router_health_weight', 0.20):.0%}")
            tbl.add_row("Weight: Reliability",  f"{getattr(config,'router_reliability_weight', 0.15):.0%}")
            tbl.add_row("Weight: Latency",      f"{getattr(config,'router_latency_weight', 0.05):.0%}")

            tbl.add_row("Free Policy",    "[bold]Strict Default Deny[/bold]")
            console.print(Panel(tbl, title="AIZEN Smart Router Status", border_style="cyan"))

        elif arg == "on":
            config.router_enabled = True
            config.model_selection_mode = "ROUTER"
            config.router_mode = "AUTO"
            save_config()
            console.print("[green]Smart router enabled (ON).[/green] Router will automatically select verified-free models.")
            console.print("[dim]Free-only policy remains enforced regardless of router state.[/dim]")

        elif arg == "off":
            config.router_enabled = False
            save_config()
            console.print("[yellow]Smart router disabled (OFF).[/yellow] Using currently selected model.")
            console.print(f"[dim]Model: {config.current_model} — Free-only policy still enforced.[/dim]")

        elif arg == "verbose":
            config.router_verbose = True
            save_config()
            console.print("[green]Router verbose mode enabled (ON).[/green] Routing decision banner will appear before responses.")

        elif arg == "quiet":
            config.router_verbose = False
            save_config()
            console.print("[yellow]Router verbose mode disabled (OFF).[/yellow]")

        elif arg == "manual":
            config.model_selection_mode = "manual"
            save_config()
            console.print("[yellow]Router disabled — manual model override active.[/yellow]")
            console.print(f"[dim]Locked to model: {config.current_model}. Use /router on to restore router control.[/dim]")

        elif arg == "explain":
            explanation = format_routing_explanation()
            console.print(Panel(explanation, title="Smart Router Explanation", border_style="cyan"))

        elif arg == "history":
            history = getattr(config, "routing_history", [])
            if not history:
                console.print("[dim]No routing history recorded yet.[/dim]")
            else:
                tbl = Table(title="Routing Decision History")
                tbl.add_column("Time",     style="cyan",    max_width=12)
                tbl.add_column("Task",     style="bold",    max_width=18)
                tbl.add_column("Model",    style="white",   max_width=35)
                tbl.add_column("Provider", style="dim",     max_width=15)
                tbl.add_column("Mode",     style="magenta", max_width=10)
                tbl.add_column("Score",    justify="right", max_width=8)
                for d in history[-10:]:
                    score_str = f"{d.factors.get('total', 0):.0f}" if d.factors else "—"
                    m_str = "MANUAL" if d.is_manual_override else "ROUTER"
                    tbl.add_row(
                        d.timestamp[11:19] if len(d.timestamp) >= 19 else d.timestamp,
                        d.task_type,
                        d.selected_model[:35],
                        d.provider[:15],
                        m_str,
                        score_str,
                    )
                console.print(tbl)
        else:
            console.print("[yellow]Usage: /router [on|off|status|verbose|quiet|explain|manual|history][/yellow]")


    # ---- SKILLS & TOOLS ----

    elif cmd == "/skills":
        arg = argument.strip().lower()
        if arg == "reload":
            from core.skill_loader import reload_skills
            reloaded = reload_skills()
            console.print(f"[green]✓ Reloaded {len(reloaded)} project rule(s) and skill(s).[/green]")
        elif arg in ("", "list"):
            from core.skill_loader import show_skills_table
            show_skills_table()
        else:
            console.print("[yellow]Usage: /skills or /skills reload[/yellow]")

    elif cmd == "/tools":
        from ui.console import show_tools
        show_tools(argument)

    # ---- VOICE MODE (Phase 13) ----

    elif cmd == "/voice":
        arg = argument.strip().lower()
        parts = arg.split(maxsplit=1)
        sub = parts[0] if parts else ""
        sub2 = parts[1] if len(parts) > 1 else ""

        if sub == "on":
            from core.voice_manager import set_voice_mode
            set_voice_mode(True)

        elif sub == "off":
            from core.voice_manager import set_voice_mode
            set_voice_mode(False)

        elif sub in ("status", ""):
            from core.voice_manager import show_voice_status
            show_voice_status()

        elif sub == "input":
            from core.voice_manager import set_voice_input
            if sub2 == "on":
                set_voice_input(True)
            elif sub2 == "off":
                set_voice_input(False)
            else:
                console.print("[yellow]Usage: /voice input [on|off][/yellow]")

        elif sub == "output":
            from core.voice_manager import set_voice_output
            if sub2 == "on":
                set_voice_output(True)
            elif sub2 == "off":
                set_voice_output(False)
            else:
                console.print("[yellow]Usage: /voice output [on|off][/yellow]")

        elif sub == "devices":
            from core.voice_manager import show_voice_devices
            show_voice_devices()

        elif sub == "voices":
            from core.voice_manager import show_voice_voices
            show_voice_voices()

        elif sub == "stop":
            from core.text_to_speech import stop_speech
            stop_speech()
            console.print("[dim]Voice output stopped.[/dim]")

        elif sub == "speed":
            try:
                val = float(sub2)
                from core.voice_manager import set_voice_speed
                set_voice_speed(val)
            except ValueError:
                console.print("[yellow]Usage: /voice speed <value>  (e.g. 0.8 or 1.5)[/yellow]")

        elif sub == "language":
            if sub2:
                from core.voice_manager import set_voice_language
                set_voice_language(sub2)
            else:
                console.print("[yellow]Usage: /voice language <code|auto>  (e.g. en, ta, auto)[/yellow]")

        elif sub == "help":
            console.print(
                "[bold cyan]Voice Commands:[/bold cyan]\n"
                "  [cyan]/voice[/cyan] or [cyan]/voice status[/cyan]   — Show voice subsystem status\n"
                "  [cyan]/voice on[/cyan] / [cyan]/voice off[/cyan]      — Enable/disable voice mode\n"
                "  [cyan]/voice input on|off[/cyan]      — Enable/disable microphone input\n"
                "  [cyan]/voice output on|off[/cyan]     — Enable/disable text-to-speech output\n"
                "  [cyan]/voice devices[/cyan]             — List audio input/output devices\n"
                "  [cyan]/voice voices[/cyan]              — List available TTS voices\n"
                "  [cyan]/voice speed <val>[/cyan]         — Set TTS speed (0.5–3.0)\n"
                "  [cyan]/voice language <code>[/cyan]     — Set STT language (en, ta, auto)\n"
                "  [cyan]/voice stop[/cyan]                — Stop current speech output\n"
                "  [bold green]Alt + V[/bold green]                      — Push-to-talk (record & transcribe)\n"
            )

        else:
            console.print(
                f"[red]Unknown /voice subcommand '{sub}'.[/red]\n"
                "[dim]Use /voice help or /help for full command list.[/dim]"
            )

    # ---- PHASE 15: VERSION / DEBUG / DOCTOR ----

    elif cmd in ("/version", "/ver"):
        import platform
        console.print(
            f"[bold cyan]AIZEN AI[/bold cyan] v[bold]{config.AIZEN_VERSION}[/bold]\n"
            f"[dim]Python {platform.python_version()} · {platform.system()} {platform.machine()}[/dim]"
        )

    elif cmd == "/debug":
        arg = argument.strip().lower()
        if arg in ("on", ""):
            config.debug_mode = True
            save_config()
            console.print("[bold yellow]⚠ Debug mode[/bold yellow] [green]ON[/green] — verbose errors and timing enabled.")
        elif arg == "off":
            config.debug_mode = False
            save_config()
            console.print("[dim]Debug mode OFF.[/dim]")
        else:
            state = "[green]ON[/green]" if config.debug_mode else "[dim]OFF[/dim]"
            console.print(f"Debug mode is currently {state}. Use [cyan]/debug on[/cyan] or [cyan]/debug off[/cyan].")

    elif cmd in ("/doctor", "/health"):
        import sys
        import os
        import socket
        import platform
        import shutil

        PASS_SYM = "✓"
        FAIL_SYM = "✗"
        WARN_SYM = "!"

        def doctor_check(label, ok, note="", warn_only=False):
            if ok:
                console.print(f"  [green]{PASS_SYM}[/green] {label}" + (f"  [dim]{note}[/dim]" if note else ""))
            elif warn_only:
                console.print(f"  [yellow]{WARN_SYM}[/yellow] {label}" + (f"  [dim]{note}[/dim]" if note else ""))
            else:
                console.print(f"  [red]{FAIL_SYM}[/red] {label}" + (f"  [dim]{note}[/dim]" if note else ""))

        console.print()
        console.print(f"[bold cyan]AIZEN AI v{config.AIZEN_VERSION} — Diagnostics[/bold cyan]")
        console.print("[dim]─────────────────────────────────────────────[/dim]")

        # Python
        py_ok = sys.version_info >= (3, 10)
        doctor_check("Python ≥ 3.10", py_ok, platform.python_version())

        # OmniRoute server
        omni_ok = False
        try:
            s = socket.create_connection(("127.0.0.1", 20128), timeout=2)
            s.close()
            omni_ok = True
        except Exception:
            pass
        doctor_check("OmniRoute server", omni_ok,
                     "port 20128 reachable" if omni_ok else "offline — run: omniroute serve")

        # API
        api_ok = False
        if omni_ok:
            from api.omniroute import check_connection
            api_ok = check_connection()
        doctor_check("OmniRoute API", api_ok,
                     config.API_BASE if api_ok else "unreachable")

        # Config file
        cfg_ok = os.path.isfile(config.CONFIG_FILE)
        doctor_check("Configuration file", cfg_ok, config.CONFIG_FILE)

        # Chats file
        chats_ok = os.path.isfile(config.CHATS_FILE)
        doctor_check("Chat storage", chats_ok, config.CHATS_FILE)

        # Data dir writable
        dw_ok = os.access(config.DATA_DIR, os.W_OK)
        doctor_check("Data directory writable", dw_ok, config.DATA_DIR)

        # Voice: sounddevice
        try:
            import sounddevice as sd; sd.query_devices()
            voice_ok = True
        except Exception:
            voice_ok = False
        doctor_check("Voice input (PortAudio)", voice_ok,
                     "available" if voice_ok else "unavailable — optional, text mode works fine",
                     warn_only=True)

        # TTS
        try:
            import pyttsx3; pyttsx3.init()
            tts_ok = True
        except Exception:
            tts_ok = False
        doctor_check("Text-to-speech (eSpeak)", tts_ok,
                     "available" if tts_ok else "unavailable — optional, install espeak via apt",
                     warn_only=True)

        # STT
        try:
            import faster_whisper
            stt_ok = True
        except ImportError:
            stt_ok = False
        doctor_check("Speech recognition (faster-whisper)", stt_ok,
                     "available" if stt_ok else "unavailable — optional",
                     warn_only=True)

        console.print("[dim]─────────────────────────────────────────────[/dim]")
        console.print("[dim]Tip: run myai --doctor for extended system checks.[/dim]\n")

    # ---- EXIT ----

    elif cmd == "/exit":
        from ui.banner import exit_aizen
        exit_aizen()

    else:
        console.print(
            "[red]Unknown command.[/red] Type [cyan]/help[/cyan]."
        )

