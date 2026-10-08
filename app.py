"""
app.py — AIZEN AI boot sequence and main input loop.

Entry point: main()
"""

import sys
import time

import requests

from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

import config
from api.omniroute import fetch_models, send_chat, stream_chat
from commands.handlers import handle_command
from core.chat_manager import (
    create_new_chat,
    ensure_chat,
    generate_title,
    get_current_chat,
)
from core.storage import load_chats, load_config, save_chats, setup_storage
from core.token_manager import get_context_status, human_number, usage_warning
from ui.banner import exit_aizen
from ui.console import console, show_aizen_home
from ui.prompts import build_prompt, session


# ------------------------------------------------------------------
# ANALYTICS HELPERS
# ------------------------------------------------------------------

def _log_success(chat, **kwargs):
    """Safely log successful request to SQLite analytics DB."""
    try:
        from core.analytics import log_success
        chat_id = chat.get("id") if (chat and isinstance(chat, dict)) else None
        log_success(chat_id=chat_id, **kwargs)
    except Exception:
        pass


def _log_failure(chat, selected_model, actual_model, streaming, response_time_ms, error_code, error_message, **kwargs):
    """Safely log failed request to SQLite analytics DB."""
    try:
        from core.analytics import log_failure
        chat_id = chat.get("id") if (chat and isinstance(chat, dict)) else None
        log_failure(
            chat_id=chat_id,
            selected_model=selected_model,
            actual_model=actual_model,
            streaming=streaming,
            response_time_ms=response_time_ms,
            error_code=error_code,
            error_message=error_message,
            **kwargs,
        )
    except Exception:
        pass


# ------------------------------------------------------------------
# AI SEND
# ------------------------------------------------------------------

def _render_usage_panel(result, model_used=None):
    """Render the usage stats table after a completion."""
    context = get_context_status()

    chosen_model = model_used or config.current_model
    stats = Table(show_header=False, box=None)
    stats.add_row("Selected Model",       chosen_model)
    stats.add_row(
        "Actual Routed Model",
        str(result.get("actual_model") or chosen_model)
    )
    stats.add_row("Response Time",        f"{result.get('response_time', 0.0):.2f}s")

    prompt_tokens = result.get("prompt_tokens")
    completion_tokens = result.get("completion_tokens")
    total_tokens = result.get("total_tokens")

    stats.add_row(
        "Prompt Tokens",
        str(prompt_tokens) if prompt_tokens is not None else "Unavailable"
    )
    stats.add_row(
        "Output Tokens",
        str(completion_tokens) if completion_tokens is not None else "Unavailable"
    )
    stats.add_row(
        "Total Tokens",
        str(total_tokens) if total_tokens is not None else "Unavailable"
    )
    stats.add_row("Approx Chat Context",  human_number(context["used"]))

    if context["limit"]:
        stats.add_row("Context Limit",    human_number(context["limit"]))
        stats.add_row("Remaining Context",human_number(context["remaining"]))
        stats.add_row(
            "Context Used %",
            f"{context['percent']:.1f}% {usage_warning(context['percent'])}"
        )

    # Provider health (best-effort — silently skip if unresolvable)
    try:
        from core.provider_health import (
            get_provider_for_model, get_provider_status,
            STATUS_COLORS, STATUS_SYMBOLS,
        )
        actual = result.get("actual_model") or config.current_model
        provider = get_provider_for_model(actual)
        if provider:
            status = get_provider_status(provider)
            color  = STATUS_COLORS.get(status, "dim")
            symbol = STATUS_SYMBOLS.get(status, "·")
            stats.add_row("Provider",        provider)
            stats.add_row(
                "Provider Health",
                f"[{color}]{symbol} {status}[/{color}]"
            )
    except Exception:
        pass

    console.print(Panel(stats, title="Usage", border_style="dim"))

    # Context pressure warnings
    percent = context.get("percent")
    if percent is not None:
        if percent >= 95:
            console.print(
                "[bold red]⚠ Context almost full. Start /new soon.[/bold red]"
            )
        elif percent >= 85:
            console.print("[red]⚠ Context usage is high.[/red]")
        elif percent >= 70:
            console.print("[yellow]⚠ Context crossed 70%.[/yellow]")


def _render_sources_panel():
    """Render compact Sources Used panel if RAG was used."""
    sources = getattr(config, "last_rag_sources", [])
    if not sources:
        return

    seen = set()
    unique_sources = []
    for s in sources:
        key = (s.get("document_name"), s.get("page_number"))
        if key not in seen:
            seen.add(key)
            unique_sources.append(s)

    if not unique_sources:
        return

    table = Table(show_header=False, box=None)
    for i, s in enumerate(unique_sources, start=1):
        doc_name = s.get("document_name", "document")
        page = s.get("page_number", 1)
        table.add_row(f"[cyan]{i}.[/cyan]", f"[bold]{doc_name}[/bold] — page {page}")

    console.print(Panel(table, title="Sources Used", border_style="cyan"))


def _render_project_sources_panel():
    """Render compact Project Files Referenced panel if project context was used."""
    sources = getattr(config, "last_project_sources", [])
    if not sources:
        return

    table = Table(show_header=False, box=None)
    for i, s in enumerate(sources, start=1):
        file_name = s.get("file", "file")
        lines = s.get("lines", "")
        lang = s.get("language", "")
        line_str = f" (lines {lines})" if lines else ""
        lang_str = f" [{lang}]" if lang else ""
        table.add_row(f"[cyan]{i}.[/cyan]", f"[bold]{file_name}[/bold]{line_str}{lang_str}")

    console.print(Panel(table, title="Project Files Referenced", border_style="cyan"))


def _handle_agent_proposal(answer: str):
    """If agent mode is active and the response proposes a command, prompt user and execute safely."""
    if not getattr(config, "agent_enabled", False):
        return

    try:
        from core.agent_manager import (
            parse_agent_proposal,
            classify_proposal,
            resolve_cwd,
            proposals_exhausted,
            increment_proposal_count,
        )
        from core.command_safety import classify, DANGEROUS, BLOCKED, level_color, level_icon
        from core.command_runner import run_foreground

        proposal = parse_agent_proposal(answer)
        if not proposal:
            return

        if proposals_exhausted():
            console.print("[yellow]Agent proposal limit reached (5 proposals per turn). Use /run manually or ask to continue.[/yellow]")
            return

        safe, block_msg = classify_proposal(proposal)
        if not safe:
            console.print(Panel(
                f"[bold red]{block_msg or 'Proposed command blocked by AIZEN safety policy.'}[/bold red]",
                title="⛔ Agent Command Blocked",
                border_style="red"
            ))
            return

        cmd = proposal["command"]
        cwd = resolve_cwd(proposal.get("cwd", "."))
        safety = classify(cmd)
        color = level_color(safety.level)
        icon = level_icon(safety.level)

        console.print()
        console.print(Panel(
            f"[bold]Command:[/bold]   {cmd}\n"
            f"[bold]Directory:[/bold] {cwd}\n"
            f"[bold]Safety:[/bold]    [{color}]{icon} {safety.level}[/{color}]\n"
            f"[bold]Reason:[/bold]    {proposal.get('reason', 'Agent proposed command')}",
            title="🤖 Agent Proposed Command",
            border_style="cyan",
        ))

        if safety.level == DANGEROUS:
            console.print(
                "\n[bold red]⚠️ DANGEROUS COMMAND[/bold red]\n"
                "Type exactly [bold]EXECUTE[/bold] to confirm, or press Enter to cancel: ",
                end=""
            )
            try:
                answer_conf = input().strip()
            except (EOFError, KeyboardInterrupt):
                answer_conf = ""
            confirmed = (answer_conf == "EXECUTE")
        else:
            console.print("[bold yellow]Execute proposed command?[/bold yellow] [dim][y/N][/dim] ", end="")
            try:
                answer_conf = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer_conf = "n"
            confirmed = answer_conf in ("y", "yes")

        if not confirmed:
            console.print("[dim]Command proposal cancelled.[/dim]")
            return

        increment_proposal_count()
        with console.status(f"[bold cyan]Running: {cmd[:60]}[/bold cyan]", spinner="dots"):
            result = run_foreground(cmd, cwd, safety, timeout=config.command_timeout)

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
                console.print(Panel(output_text, title="Command Output", border_style="dim"))
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
    except Exception as e:
        console.print(f"[dim red]Agent proposal execution error: {e}[/dim red]")


def _ask_ai_non_stream(messages, chat, model_to_use=None, decision=None, fallback_used: bool = False, is_retry: bool = False):
    """Send request using standard non-streaming path."""
    target_model = model_to_use or config.current_model

    from core.free_model_registry import is_model_allowed
    from core.provider_health import get_provider_for_model
    prov = get_provider_for_model(target_model)
    if not is_model_allowed(prov, target_model):
        _rollback_last_user_message(chat)
        console.print(
            f"\n[bold red]❌ Request blocked by AIZEN Free-Only mode.[/bold red]\n"
            f"[dim]Model '{target_model}' is not verified free.[/dim]\n"
        )
        return

    t_start = time.time()

    router_used = bool(decision and not decision.is_manual_override)
    router_mode = getattr(config, "router_mode", "AUTO")
    classified_task = decision.task_type if decision else None

    try:
        with console.status(
            "[bold cyan]Aizen is thinking...[/bold cyan]",
            spinner="dots"
        ):
            result = send_chat(messages, target_model)

    except requests.exceptions.Timeout:
        _record_conn_failure(target_model, None, "Request timed out")
        if not is_retry and decision and not decision.is_manual_override:
            from core.router import get_retry_model
            retry_model = get_retry_model(target_model, decision.provider)
            if retry_model and retry_model != target_model:
                console.print(f"[dim yellow]Primary route unavailable — trying next eligible model ({retry_model}).[/dim yellow]")
                return _ask_ai_non_stream(messages, chat, model_to_use=retry_model, decision=decision, fallback_used=fallback_used, is_retry=True)

        _rollback_last_user_message(chat)
        _log_failure(
            chat, target_model, None, streaming=False,
            response_time_ms=(time.time() - t_start) * 1000,
            error_code=None, error_message="Request timed out",
            router_used=router_used, router_mode=router_mode,
            classified_task=classified_task,
            router_selected_model=target_model if router_used else None,
        )
        console.print("\n[bold red]Request timed out.[/bold red]")
        return

    except requests.exceptions.ConnectionError:
        _record_conn_failure(target_model, None, "Connection error")
        if not is_retry and decision and not decision.is_manual_override:
            from core.router import get_retry_model
            retry_model = get_retry_model(target_model, decision.provider)
            if retry_model and retry_model != target_model:
                console.print(f"[dim yellow]Primary route unavailable — trying next eligible model ({retry_model}).[/dim yellow]")
                return _ask_ai_non_stream(messages, chat, model_to_use=retry_model, decision=decision, fallback_used=fallback_used, is_retry=True)

        _rollback_last_user_message(chat)
        _log_failure(
            chat, target_model, None, streaming=False,
            response_time_ms=(time.time() - t_start) * 1000,
            error_code=None, error_message="Connection error",
            router_used=router_used, router_mode=router_mode,
            classified_task=classified_task,
            router_selected_model=target_model if router_used else None,
        )
        console.print("\n[bold red]Cannot connect to OmniRoute.[/bold red]")
        return

    except KeyboardInterrupt:
        _rollback_last_user_message(chat)
        # Ctrl+C: intentional cancel — no analytics row
        console.print("\n[yellow]Request cancelled.[/yellow]")
        return

    except RuntimeError as error:
        if not is_retry and decision and not decision.is_manual_override:
            from core.router import get_retry_model
            retry_model = get_retry_model(target_model, decision.provider)
            if retry_model and retry_model != target_model:
                console.print(f"[dim yellow]Primary route unavailable — trying next eligible model ({retry_model}).[/dim yellow]")
                return _ask_ai_non_stream(messages, chat, model_to_use=retry_model, decision=decision, fallback_used=fallback_used, is_retry=True)

        _rollback_last_user_message(chat)
        _log_failure(
            chat, target_model, None, streaming=False,
            response_time_ms=(time.time() - t_start) * 1000,
            error_code=None, error_message=str(error)[:300],
            router_used=router_used, router_mode=router_mode,
            classified_task=classified_task,
            router_selected_model=target_model if router_used else None,
        )
        console.print(
            Panel(str(error), title="API Error", border_style="red")
        )
        return

    except Exception as error:
        if not is_retry and decision and not decision.is_manual_override:
            from core.router import get_retry_model
            retry_model = get_retry_model(target_model, decision.provider)
            if retry_model and retry_model != target_model:
                console.print(f"[dim yellow]Primary route unavailable — trying next eligible model ({retry_model}).[/dim yellow]")
                return _ask_ai_non_stream(messages, chat, model_to_use=retry_model, decision=decision, fallback_used=fallback_used, is_retry=True)

        _rollback_last_user_message(chat)
        _log_failure(
            chat, target_model, None, streaming=False,
            response_time_ms=(time.time() - t_start) * 1000,
            error_code=None, error_message=str(error)[:300],
            router_used=router_used, router_mode=router_mode,
            classified_task=classified_task,
            router_selected_model=target_model if router_used else None,
        )
        console.print(f"\n[bold red]Error: {error}[/bold red]")
        return

    # Persist the assistant reply
    answer = result["answer"]

    # Native Tool Execution Loop (up to 8 iterations)
    from core.tool_parser import has_tool_call, parse_tool_call, strip_tool_markup
    from core.tool_executor import execute_tool
    import json

    iteration = 0
    max_tool_iterations = 8

    while has_tool_call(answer) and iteration < max_tool_iterations:
        tool_call = parse_tool_call(answer)
        if not tool_call:
            break

        tool_name = tool_call.get("tool", "unknown")
        tool_args = tool_call.get("args", {})
        arg_summary = ", ".join(f"{k}={repr(v)}" for k, v in tool_args.items())
        if len(arg_summary) > 80:
            arg_summary = arg_summary[:77] + "..."

        console.print(f"[bold cyan]⚡ Tool Execution:[/bold cyan] [bold]{tool_name}[/bold] [dim]({arg_summary})[/dim]")

        tool_result = execute_tool(tool_call)

        if tool_result.get("success"):
            out_preview = str(tool_result.get("output", ""))
            console.print(f"[dim]✓ {tool_name} completed ({len(out_preview)} chars)[/dim]")
        else:
            err_msg = tool_result.get("error") or "Unknown error"
            console.print(f"[dim red]✗ {tool_name} failed: {err_msg}[/dim red]")

        messages.append({
            "role": "assistant",
            "content": f"<tool_call>\n{json.dumps(tool_call)}\n</tool_call>"
        })
        messages.append({
            "role": "user",
            "content": f"[TOOL RESULT: {tool_name}]\n{json.dumps(tool_result, indent=2)}\n[END TOOL RESULT]"
        })

        iteration += 1

        try:
            with console.status("[bold cyan]Aizen is thinking...[/bold cyan]", spinner="dots"):
                next_result = send_chat(messages, target_model)
                answer = next_result["answer"]
                result = next_result
        except Exception as e:
            console.print(f"[bold red]Tool execution follow-up error: {e}[/bold red]")
            break

    # Clean final answer of any residual tool markup
    clean_answer = strip_tool_markup(answer) or answer

    # Persist the assistant reply
    chat["messages"].append({"role": "assistant", "content": clean_answer})
    save_chats()

    # Update global usage state
    config.last_usage = {
        "prompt_tokens":     result.get("prompt_tokens"),
        "completion_tokens": result.get("completion_tokens"),
        "total_tokens":      result.get("total_tokens"),
        "actual_model":      result.get("actual_model"),
        "response_time":     result.get("response_time", 0.0),
    }

    # Log analytics — one row per user request
    _log_success(
        chat,
        selected_model=target_model,
        actual_model=result.get("actual_model"),
        streaming=False,
        prompt_tokens=result.get("prompt_tokens"),
        completion_tokens=result.get("completion_tokens"),
        total_tokens=result.get("total_tokens"),
        response_time_ms=(result.get("response_time", 0.0) or 0.0) * 1000,
        fallback_used=fallback_used,
        router_used=router_used,
        router_mode=router_mode,
        classified_task=classified_task,
        router_selected_model=target_model if router_used else None,
    )

    # Render response
    console.print()
    console.print(
        Panel(
            Markdown(clean_answer),
            title="[bold cyan]AIZEN[/bold cyan]",
            border_style="cyan",
            padding=(1, 2)
        )
    )

    # Render usage stats & sources
    _render_usage_panel(result, model_used=target_model)
    _render_sources_panel()
    _render_project_sources_panel()

    # Agent proposal handling (Phase 10)
    _handle_agent_proposal(clean_answer)

    # Voice output (Phase 13) — read response aloud if enabled
    try:
        from core.voice_manager import speak_response_if_enabled
        speak_response_if_enabled(clean_answer)
    except Exception:
        pass


def _ask_ai_stream(messages, chat, model_to_use=None, decision=None, is_retry: bool = False):
    """
    Send request using streaming path.
    Falls back to non-streaming if route fails before content arrives.
    """
    target_model = model_to_use or config.current_model

    from core.free_model_registry import is_model_allowed
    from core.provider_health import get_provider_for_model
    prov = get_provider_for_model(target_model)
    if not is_model_allowed(prov, target_model):
        _rollback_last_user_message(chat)
        console.print(
            f"\n[bold red]❌ Request blocked by AIZEN Free-Only mode.[/bold red]\n"
            f"[dim]Model '{target_model}' is not verified free.[/dim]\n"
        )
        return

    t_start = time.time()
    status = console.status(
        "[bold cyan]Aizen is thinking...[/bold cyan]",
        spinner="dots"
    )
    status.start()

    chunks = []
    buffered_chunks = []
    first_chunk_received = False
    stream_flushed = False
    done_data = None

    router_used = bool(decision and not decision.is_manual_override)
    router_mode = getattr(config, "router_mode", "AUTO")
    classified_task = decision.task_type if decision else None

    try:
        for event_type, data in stream_chat(messages, target_model):
            if event_type == "content":
                chunks.append(data)
                if not stream_flushed:
                    buffered_chunks.append(data)
                    buffered_text = "".join(buffered_chunks)
                    trimmed = buffered_text.lstrip()
                    if trimmed.startswith(("<", "{", "```", "[")):
                        if (
                            "<tool_call" in trimmed or
                            "<invoke" in trimmed or
                            "<tool_code" in trimmed or
                            '"tool"' in trimmed or
                            "'tool'" in trimmed or
                            '"name"' in trimmed
                        ):
                            # It is a tool call — buffer silently
                            continue
                        elif len(trimmed) < 20:
                            # Keep buffering until confident
                            continue
                        else:
                            # Not a tool call, flush buffer
                            status.stop()
                            first_chunk_received = True
                            console.print("\n[bold cyan]AIZEN ❯[/bold cyan]\n")
                            sys.stdout.write(buffered_text)
                            sys.stdout.flush()
                            stream_flushed = True
                    else:
                        status.stop()
                        first_chunk_received = True
                        console.print("\n[bold cyan]AIZEN ❯[/bold cyan]\n")
                        sys.stdout.write(buffered_text)
                        sys.stdout.flush()
                        stream_flushed = True
                else:
                    sys.stdout.write(data)
                    sys.stdout.flush()
            elif event_type == "done":
                done_data = data

    except KeyboardInterrupt:
        status.stop()
        if first_chunk_received:
            sys.stdout.write("\n")
            sys.stdout.flush()
        _rollback_last_user_message(chat)
        console.print("\n[yellow]Generation cancelled.[/yellow]")
        return

    except (RuntimeError, requests.exceptions.RequestException, Exception) as error:
        status.stop()
        if not first_chunk_received:
            # Record the failure passively before falling back
            if isinstance(error, requests.exceptions.ConnectionError):
                _record_conn_failure(target_model, None, str(error))
            elif isinstance(error, requests.exceptions.Timeout):
                _record_conn_failure(target_model, None, "Streaming timeout")

            # Check if smart router retry is possible before falling back
            if not is_retry and decision and not decision.is_manual_override:
                from core.router import get_retry_model
                retry_model = get_retry_model(target_model, decision.provider)
                if retry_model and retry_model != target_model:
                    console.print(
                        f"[dim yellow]Primary route unavailable — trying next eligible model ({retry_model}).[/dim yellow]"
                    )
                    _ask_ai_stream(messages, chat, model_to_use=retry_model, decision=decision, is_retry=True)
                    return

            # Failed before meaningful content was received!
            # Automatically retry once using standard non-streaming path.
            # The fallback call will record its own analytics row (fallback_used=True).
            console.print(
                "[dim yellow]Streaming unavailable for this route — using standard response.[/dim yellow]"
            )
            _ask_ai_non_stream(messages, chat, model_to_use=target_model, decision=decision, fallback_used=True, is_retry=is_retry)
            return
        else:
            # Partial content was already printed; do not fallback to avoid duplicate text.
            sys.stdout.write("\n")
            sys.stdout.flush()
            _rollback_last_user_message(chat)
            # Log the streaming failure (partial output case)
            _log_failure(
                chat, target_model, None, streaming=True,
                response_time_ms=(time.time() - t_start) * 1000,
                error_code=None,
                error_message=str(error)[:300],
                router_used=router_used,
                router_mode=router_mode,
                classified_task=classified_task,
                router_selected_model=target_model if router_used else None,
            )
            console.print(f"\n[bold red]Stream error: {error}[/bold red]")
            return

    finally:
        try:
            status.stop()
        except Exception:
            pass

    if not chunks:
        # Stream finished without any content chunks
        if not is_retry and decision and not decision.is_manual_override:
            from core.router import get_retry_model
            retry_model = get_retry_model(target_model, decision.provider)
            if retry_model and retry_model != target_model:
                console.print(
                    f"[dim yellow]Primary route unavailable — trying next eligible model ({retry_model}).[/dim yellow]"
                )
                _ask_ai_stream(messages, chat, model_to_use=retry_model, decision=decision, is_retry=True)
                return

        console.print(
            "[dim yellow]Streaming unavailable for this route — using standard response.[/dim yellow]"
        )
        _ask_ai_non_stream(messages, chat, model_to_use=target_model, decision=decision, fallback_used=True, is_retry=is_retry)
        return

    if first_chunk_received:
        sys.stdout.write("\n\n")
        sys.stdout.flush()
    else:
        try:
            status.stop()
        except Exception:
            pass

    full_answer = "".join(chunks)

    # Native Tool Execution Loop (up to 8 iterations)
    from core.tool_parser import has_tool_call, parse_tool_call, strip_tool_markup
    from core.tool_executor import execute_tool
    import json

    iteration = 0
    max_tool_iterations = 8

    while has_tool_call(full_answer) and iteration < max_tool_iterations:
        tool_call = parse_tool_call(full_answer)
        if not tool_call:
            break

        tool_name = tool_call.get("tool", "unknown")
        tool_args = tool_call.get("args", {})
        arg_summary = ", ".join(f"{k}={repr(v)}" for k, v in tool_args.items())
        if len(arg_summary) > 80:
            arg_summary = arg_summary[:77] + "..."

        console.print(f"[bold cyan]⚡ Tool Execution:[/bold cyan] [bold]{tool_name}[/bold] [dim]({arg_summary})[/dim]")

        tool_result = execute_tool(tool_call)

        if tool_result.get("success"):
            out_preview = str(tool_result.get("output", ""))
            console.print(f"[dim]✓ {tool_name} completed ({len(out_preview)} chars)[/dim]")
        else:
            err_msg = tool_result.get("error") or "Unknown error"
            console.print(f"[dim red]✗ {tool_name} failed: {err_msg}[/dim red]")

        messages.append({
            "role": "assistant",
            "content": f"<tool_call>\n{json.dumps(tool_call)}\n</tool_call>"
        })
        messages.append({
            "role": "user",
            "content": f"[TOOL RESULT: {tool_name}]\n{json.dumps(tool_result, indent=2)}\n[END TOOL RESULT]"
        })

        iteration += 1

        try:
            with console.status("[bold cyan]Aizen is thinking...[/bold cyan]", spinner="dots"):
                next_res = send_chat(messages, target_model)
                full_answer = next_res["answer"]
                done_data = {
                    "actual_model": next_res.get("actual_model"),
                    "prompt_tokens": next_res.get("prompt_tokens"),
                    "completion_tokens": next_res.get("completion_tokens"),
                    "total_tokens": next_res.get("total_tokens"),
                    "response_time": next_res.get("response_time", 0.0),
                }
        except Exception as e:
            console.print(f"[bold red]Tool execution follow-up error: {e}[/bold red]")
            break

    # Strip any residual tool markup from the final answer
    clean_answer = strip_tool_markup(full_answer) or full_answer

    # If the tool loop ran, render the final answer in a Panel
    if iteration > 0:
        console.print()
        console.print(
            Panel(
                Markdown(clean_answer),
                title="[bold cyan]AIZEN[/bold cyan]",
                border_style="cyan",
                padding=(1, 2)
            )
        )

    chat["messages"].append({"role": "assistant", "content": clean_answer})
    save_chats()

    actual_model = (
        done_data.get("actual_model")
        if done_data
        else target_model
    )
    prompt_tokens = done_data.get("prompt_tokens") if done_data else None
    completion_tokens = done_data.get("completion_tokens") if done_data else None
    total_tokens = done_data.get("total_tokens") if done_data else None
    response_time = done_data.get("response_time", 0.0) if done_data else 0.0

    result = {
        "answer": clean_answer,
        "actual_model": actual_model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "response_time": response_time
    }

    config.last_usage = {
        "prompt_tokens":     prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens":      total_tokens,
        "actual_model":      actual_model,
        "response_time":     response_time,
    }

    # Log analytics — one row for the completed streaming request
    _log_success(
        chat,
        selected_model=target_model,
        actual_model=actual_model,
        streaming=True,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        response_time_ms=(response_time or 0.0) * 1000,
        fallback_used=False,
        router_used=router_used,
        router_mode=router_mode,
        classified_task=classified_task,
        router_selected_model=target_model if router_used else None,
    )

    _render_usage_panel(result, model_used=target_model)
    _render_sources_panel()
    _render_project_sources_panel()

    # Agent proposal handling (Phase 10)
    _handle_agent_proposal(full_answer)

    # Voice output (Phase 13) — read response aloud if enabled
    try:
        from core.voice_manager import speak_response_if_enabled
        speak_response_if_enabled(clean_answer)
    except Exception:
        pass


def ask_ai(prompt):
    """
    Send the user's message to OmniRoute, render the response, and
    update token/context usage statistics.
    """
    chat = get_current_chat()

    if chat is None:
        create_new_chat()
        chat = get_current_chat()

    # Append user message and auto-title the chat on first message
    chat["messages"].append({"role": "user", "content": prompt})

    if chat["title"] == "New Chat":
        chat["title"] = generate_title(prompt)

    save_chats()

    # Reset agent proposal count at start of turn
    try:
        from core.agent_manager import reset_proposal_count
        reset_proposal_count()
    except Exception:
        pass

    sys_prompt = config.SYSTEM_PROMPT
    if getattr(config, "agent_enabled", False):
        try:
            from core.agent_manager import get_agent_prompt_suffix
            sys_prompt += get_agent_prompt_suffix()
        except Exception:
            pass

    # Active Agent Skills & Rules
    try:
        from core.skill_loader import build_skills_context
        skills_ctx = build_skills_context()
        if skills_ctx:
            sys_prompt += "\n\n" + skills_ctx
    except Exception:
        pass

    # Native Tool Capabilities
    try:
        from core.tool_registry import registry
        tools_prompt = registry.get_tools_prompt()
        if tools_prompt:
            sys_prompt += "\n\n" + tools_prompt
    except Exception:
        pass

    messages = [{"role": "system", "content": sys_prompt}]

    # Phase 10: Include recent terminal output context if present
    if getattr(config, "last_command_result", None) is not None:
        try:
            res = config.last_command_result
            output_sample = res.stdout_preview or res.stderr_preview or "(No output)"
            if len(output_sample) > 2000:
                output_sample = output_sample[:2000] + "\n... [truncated]"
            term_ctx = (
                f"[TERMINAL RESULT]\n"
                f"Command: {res.command}\n"
                f"Working Directory: {res.cwd}\n"
                f"Exit Code: {res.exit_code}\n"
                f"Output:\n{output_sample}\n"
                f"[END TERMINAL RESULT]"
            )
            messages.append({"role": "system", "content": term_ctx})
        except Exception:
            pass

    # Priority 4: Explicit attachments (Phase 6)
    try:
        from core.file_manager import build_file_context
        file_ctx = build_file_context(chat)
        if file_ctx:
            messages.append({"role": "system", "content": file_ctx})
    except Exception:
        pass

    # Priority 5: Directly relevant project files (Phase 8)
    config.last_project_sources = []
    try:
        from core.project_manager import build_project_context
        project_ctx, project_sources = build_project_context(prompt)
        if project_ctx:
            messages.append({"role": "system", "content": project_ctx})
            config.last_project_sources = project_sources
    except Exception:
        pass

    # Priority 6: RAG chunks (Phase 7)
    config.last_rag_sources = []
    try:
        from core.kb_manager import build_rag_context
        rag_ctx, used_sources = build_rag_context(prompt)
        if rag_ctx:
            messages.append({"role": "system", "content": rag_ctx})
            config.last_rag_sources = used_sources
    except Exception:
        pass

    messages.extend(chat["messages"])

    # Phase 11: Smart Router
    from core.router import route, format_verbose_routing
    context_details = {
        "has_project": bool(config.last_project_sources),
        "has_rag": bool(config.last_rag_sources),
        "has_terminal": getattr(config, "last_command_result", None) is not None,
    }
    try:
        from core.file_manager import get_attached_files
        att_files = get_attached_files(chat)
        if att_files:
            context_details["has_attachments"] = True
            for f in att_files:
                fn = f.get("name", "").lower()
                if any(fn.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]):
                    context_details["has_images"] = True
    except Exception:
        pass

    decision = route(prompt, context_details)
    model_to_use = decision.selected_model

    if not model_to_use:
        _rollback_last_user_message(chat)
        console.print(
            "\n[bold red]❌ No verified-free model is currently available for this task.[/bold red]\n"
            "[dim]Paid/unknown models are blocked by AIZEN Free-Only mode. Use /pick or /free list to see eligible models.[/dim]\n"
        )
        return

    if getattr(config, "router_verbose", False):
        console.print(format_verbose_routing(decision))

    if config.streaming_enabled:
        _ask_ai_stream(messages, chat, model_to_use=model_to_use, decision=decision)
    else:
        _ask_ai_non_stream(messages, chat, model_to_use=model_to_use, decision=decision)


def _rollback_last_user_message(chat):
    """Remove the last user message from the chat if the request failed."""
    if chat["messages"] and chat["messages"][-1]["role"] == "user":
        chat["messages"].pop()
    save_chats()


def _record_conn_failure(model: str, code, error_text: str):
    """
    Best-effort passive health recording for connection/timeout errors
    that don't go through the omniroute HTTP layer (e.g. caught here in app.py).
    """
    try:
        from core.provider_health import get_provider_for_model, record_failure
        provider = get_provider_for_model(model)
        if provider:
            record_failure(provider, model, error_text, error_code=code)
    except Exception:
        pass



# ------------------------------------------------------------------
# STARTUP
# ------------------------------------------------------------------

def _startup():
    """Initialise storage, load persisted state, and show the home screen."""
    setup_storage()
    load_chats()
    load_config()
    ensure_chat()
    # Load persisted provider health before fetching models
    try:
        from core.provider_health import load_health
        load_health()
    except Exception:
        pass
    # Initialise analytics DB
    try:
        from core.analytics import init_db
        init_db()
    except Exception:
        pass
    # Initialise KB tables
    try:
        from core.kb_manager import init_kb_db
        init_kb_db()
    except Exception:
        pass
    # Initialise edit session tables (Phase 9)
    try:
        from core.backup_manager import init_edit_db
        init_edit_db()
    except Exception:
        pass
    # Initialise command history tables (Phase 10)
    try:
        from core.command_runner import init_command_db
        init_command_db()
    except Exception:
        pass
    # Restore active project if configured
    try:
        from core.project_manager import restore_project_on_startup
        restore_warn = restore_project_on_startup()
        if restore_warn:
            console.print(f"[yellow]{restore_warn}[/yellow]")
    except Exception:
        pass
    # Load project skills and rules
    try:
        from core.skill_loader import load_skills
        load_skills()
    except Exception:
        pass
    # Sweep stale voice temp audio files (Phase 13)
    try:
        from core.audio_manager import clean_stale_temp_audio_files
        clean_stale_temp_audio_files()
    except Exception:
        pass
    fetch_models()          # silent on failure — home screen shows ● Offline
    try:
        from core.storage import validate_and_sanitize_configured_model
        valid, warn = validate_and_sanitize_configured_model()
        if not valid and warn:
            console.print(f"[yellow]⚠ {warn}[/yellow]")
    except Exception:
        pass
    show_aizen_home()


# ------------------------------------------------------------------
# MAIN LOOP
# ------------------------------------------------------------------

def main():
    """Entry point for the AIZEN CLI."""
    _startup()

    while True:
        try:
            raw = session.prompt(build_prompt()).strip()

            if not raw:
                continue

            # Alt+M shortcut sentinel
            if raw == "__PICK__":
                from ui.picker import run_picker
                run_picker()
                continue

            # Alt+V push-to-talk sentinel (Phase 13)
            if raw == "__VOICE__":
                try:
                    from core.voice_manager import handle_push_to_talk
                    voice_prompt = handle_push_to_talk()
                    if voice_prompt and voice_prompt.strip():
                        ask_ai(voice_prompt.strip())
                except Exception as ve:
                    console.print(f"[dim red]Voice input error: {ve}[/dim red]")
                continue

            # Graceful exit via typed command
            if raw.lower() in ("/exit", "exit", "quit"):
                exit_aizen()

            # Slash commands
            if raw.startswith("/"):
                handle_command(raw)
                continue

            # Everything else → send to AI
            ask_ai(raw)

        except KeyboardInterrupt:
            console.print("\n[yellow]Input cancelled.[/yellow]")

        except EOFError:
            exit_aizen()
