"""
ui/prompts.py — prompt_toolkit session, key bindings, and dynamic prompt.

Defines:
  - COMMANDS list (for tab-completion)
  - command_completer
  - bindings (all keyboard shortcuts)
  - prompt_style
  - session (the global PromptSession)
  - build_prompt()  — callable that returns the live prompt string
"""

import config
from core.storage import save_config
from ui.console import console

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style


# ------------------------------------------------------------------
# TAB COMPLETION
# ------------------------------------------------------------------

COMMANDS = [
    "/models", "/use", "/model", "/limits",
    "/usage", "/usage today", "/usage week", "/usage month", "/usage all",
    "/usage models", "/usage providers", "/usage chat", "/usage db",
    "/refresh",
    "/auto", "/smart", "/fast", "/code", "/free",
    "/pick",
    "/providers",
    "/stream", "/stream on", "/stream off",
    "/new", "/chats", "/load", "/delete", "/title",
    "/history", "/clear",
    "/attach", "/files", "/remove", "/clearfiles",
    "/kb", "/kb add", "/kb list", "/kb search", "/kb remove", "/kb clear", "/kb status",
    "/rag", "/rag on", "/rag off",
    "/project", "/project .", "/project status", "/project off", "/project refresh",
    "/tree", "/find", "/read",
    "/edit", "/diff", "/apply", "/discard", "/changes", "/undo",
    "/run", "/agent", "/agent on", "/agent off", "/agent status",
    "/jobs", "/kill", "/lastcmd",
    "/mode", "/mode auto", "/mode coding", "/mode reasoning", "/mode fast", "/mode chat", "/mode research", "/mode vision",
    "/router", "/router status", "/router verbose", "/router quiet", "/router explain", "/router manual", "/router history",
    "/skills", "/skills reload",
    "/tools", "/tools status",
    "/voice", "/voice on", "/voice off", "/voice status",
    "/voice input on", "/voice input off",
    "/voice output on", "/voice output off",
    "/voice devices", "/voice voices",
    "/voice stop", "/voice speed", "/voice language", "/voice help",
    "/status", "/cls", "/help",
    "/version", "/debug", "/debug on", "/debug off",
    "/doctor", "/health",
    "/exit",
]

command_completer = WordCompleter(
    COMMANDS,
    ignore_case=True,
    sentence=True
)


# ------------------------------------------------------------------
# KEY BINDINGS
# ------------------------------------------------------------------

bindings = KeyBindings()


@bindings.add("c-l")
def shortcut_clear(event):
    """Ctrl+L — clear screen and restore AIZEN home."""
    from ui.console import show_aizen_home
    show_aizen_home()
    event.app.invalidate()


@bindings.add("c-n")
def shortcut_new_chat(event):
    """Ctrl+N — create a new chat without submitting input."""
    from core.chat_manager import create_new_chat
    create_new_chat()
    event.app.current_buffer.reset()


@bindings.add("c-g")
def shortcut_code(event):
    """Ctrl+G — switch to coding routing mode."""
    config.current_model = "auto"
    config.model_selection_mode = "router"
    config.router_mode = "CODING"
    save_config()
    console.print("\n[green]CODING mode enabled (Free-Only Smart Router).[/green]")


@bindings.add("escape", "s")
def shortcut_smart(event):
    """Alt+S — switch to smart routing mode."""
    config.current_model = "auto"
    config.model_selection_mode = "router"
    config.router_mode = "AUTO"
    save_config()
    console.print("\n[green]SMART mode enabled (Free-Only Smart Router).[/green]")


@bindings.add("escape", "f")
def shortcut_fast(event):
    """Alt+F — switch to fast routing mode."""
    config.current_model = "auto"
    config.model_selection_mode = "router"
    config.router_mode = "FAST"
    save_config()
    console.print("\n[green]FAST mode enabled (Free-Only Smart Router).[/green]")


@bindings.add("escape", "a")
def shortcut_auto(event):
    """Alt+A — switch to automatic routing mode."""
    config.current_model = "auto"
    config.model_selection_mode = "router"
    config.router_mode = "AUTO"
    save_config()
    console.print("\n[green]AUTO mode enabled (Free-Only Smart Router).[/green]")


@bindings.add("c-d")
def shortcut_exit(event):
    """Ctrl+D — exit AIZEN gracefully."""
    event.app.exit(result="/exit")


@bindings.add("escape", "m")
def shortcut_pick(event):
    """Alt+M — open the interactive model picker.

    Exits the current prompt with a sentinel value so the main loop
    can launch the picker Application without nesting two pt apps.
    """
    event.app.exit(result="__PICK__")


@bindings.add("escape", "v")
def shortcut_voice_ptt(event):
    """Alt+V — push-to-talk: capture microphone audio and transcribe.

    Exits the current prompt with a sentinel value so the main loop
    can run handle_push_to_talk() and re-prompt with the transcription.
    """
    event.app.exit(result="__VOICE__")


# ------------------------------------------------------------------
# PROMPT STYLE
# ------------------------------------------------------------------

prompt_style = Style.from_dict({
    "prompt":                          "bold #00ff88",
    "model":                           "bold #00d7ff",
    "usage":                           "#888888",
    "completion-menu.completion":      "bg:#202020 #ffffff",
    "completion-menu.completion.current": "bg:#00aaaa #000000",
})


# ------------------------------------------------------------------
# SESSION
# ------------------------------------------------------------------

session = PromptSession(
    history=FileHistory(config.PROMPT_HISTORY_FILE),
    completer=command_completer,
    complete_while_typing=False,
    key_bindings=bindings,
    style=prompt_style,
    enable_history_search=True
)


# ------------------------------------------------------------------
# DYNAMIC PROMPT BUILDER
# ------------------------------------------------------------------

def short_model_name():
    """Truncate long model names for the prompt display."""
    name = config.current_model
    if len(name) > 28:
        return name[:25] + "..."
    return name


def build_prompt():
    """
    Return a list of (style-class, text) tuples for the prompt_toolkit
    prompt. Called on every input iteration so it reflects live state.
    """
    from core.token_manager import get_context_status, human_number

    context = get_context_status()
    used = human_number(context["used"])

    if context["limit"]:
        usage_text = f"{used}/{human_number(context['limit'])}"
    else:
        usage_text = used

    return [
        ("class:prompt", "You "),
        ("class:model",  f"[{short_model_name()}]"),
        ("class:usage",  f"[{usage_text}]"),
        ("class:prompt", " ❯ "),
    ]
