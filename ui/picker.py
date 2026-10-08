"""
ui/picker.py — Interactive full-screen model picker.

Provides a prompt_toolkit Application with:
  - Live search filtering (just start typing)
  - ↑ / ↓ / PgUp / PgDn / Home / End navigation
  - Enter to select, Esc or Ctrl+C to cancel
  - Columns: model id, provider, context / max-in / max-out, capabilities
  - Current model is highlighted with ●
"""

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.styles import Style

import config


# ------------------------------------------------------------------
# CONSTANTS & STYLE
# ------------------------------------------------------------------

# How many model rows are visible at once (rest is scrolled)
VISIBLE_ROWS = 16

PICKER_STYLE = Style.from_dict({
    # Header / footer bars
    "header":         "bg:#0d1117 fg:#00d7ff bold",
    "col-header":     "bg:#0d1117 fg:#445566",
    "footer":         "bg:#0d1117 fg:#555555",

    # Search label ("🔍 Search: ")
    "search-label":   "fg:#00ff88 bold",

    # Model rows
    "model.normal":           "fg:#bbbbbb",
    "model.selected":         "bg:#003355 fg:#00d7ff bold",
    "model.current":          "fg:#00ff88 bold",
    "model.current.selected": "bg:#003355 fg:#00ff88 bold",

    # Column data
    "provider":       "fg:#777799",
    "ctx":            "fg:#9999bb",
    "caps":           "fg:#cc8800",

    # Misc
    "count":          "fg:#444444",
    "no-match":       "fg:#cc4444 italic",
    "scroll-bar":     "fg:#334455",
})


# ------------------------------------------------------------------
# FORMATTING HELPERS
# ------------------------------------------------------------------

def _fmt(value):
    """Compact integer formatter for token counts (no decimals)."""
    if value is None:
        return "—"
    try:
        v = int(value)
    except Exception:
        return "—"
    if v >= 1_000_000:
        return f"{v // 1_000_000}M"
    if v >= 1_000:
        return f"{v // 1_000}K"
    return str(v)


def _caps(meta):
    """One-line capability badge string."""
    c = meta.get("capabilities", {})
    tags = []
    if c.get("reasoning"):    tags.append("reasoning")
    if c.get("thinking"):     tags.append("thinking")
    if c.get("tool_calling"): tags.append("tool calling")
    if c.get("vision"):       tags.append("vision")
    return " · ".join(tags)


# ------------------------------------------------------------------
# PICKER CLASS
# ------------------------------------------------------------------

class ModelPicker:
    """
    Full-screen interactive model picker built on prompt_toolkit.

    Usage:
        picker = ModelPicker(models, initial_filter="nvidia")
        model_id = picker.run()   # None → cancelled
    """

    def __init__(self, models, initial_filter=""):
        self.all_models = models
        self.filtered:  list = []
        self.sel_idx:   int  = 0
        self.scroll:    int  = 0
        self.result            = None   # selected model id, or None

        # Buffer that powers the search box
        self.search_buf = Buffer(on_text_changed=self._on_text_changed)

        # Build initial filtered list before anything renders
        self._apply_filter(initial_filter)

        # Pre-fill search box with the initial filter keyword
        if initial_filter:
            self.search_buf.set_document(Document(initial_filter))

        # Position initial cursor on current_model if present in filtered list
        if config.current_model:
            for idx, m in enumerate(self.filtered):
                if m.get("id") == config.current_model:
                    self.sel_idx = idx
                    self._clamp_scroll()
                    break

        self._build_app()

    # ---- Filtering ------------------------------------------------

    def _apply_filter(self, query=""):
        q = query.strip().lower()
        if q:
            self.filtered = [
                m for m in self.all_models
                if q in (
                    m.get("id", "") + " " + str(m.get("owned_by", ""))
                ).lower()
            ]
        else:
            self.filtered = list(self.all_models)

        # Clamp selection index to valid range
        self.sel_idx = min(self.sel_idx, max(0, len(self.filtered) - 1))
        self._clamp_scroll()

    def _on_text_changed(self, buf):
        """Called on every keystroke in the search box."""
        # Remember which model was selected so we can re-find it after filtering
        prev_id = (
            self.filtered[self.sel_idx].get("id") if self.filtered else None
        )
        self._apply_filter(buf.text)

        # Re-select the same model if it still appears in results
        if prev_id:
            for i, m in enumerate(self.filtered):
                if m.get("id") == prev_id:
                    self.sel_idx = i
                    self.scroll  = 0
                    self._clamp_scroll()
                    break

    # ---- Navigation -----------------------------------------------

    def _clamp_scroll(self):
        """Keep the selected row inside the visible window."""
        if self.sel_idx < self.scroll:
            self.scroll = self.sel_idx
        elif self.sel_idx >= self.scroll + VISIBLE_ROWS:
            self.scroll = self.sel_idx - VISIBLE_ROWS + 1
        self.scroll = max(0, self.scroll)

    def _move(self, delta):
        if not self.filtered:
            return
        self.sel_idx = max(0, min(len(self.filtered) - 1, self.sel_idx + delta))
        self._clamp_scroll()

    # ---- Rendering ------------------------------------------------

    def _render_header(self):
        shown = len(self.filtered)
        total = len(self.all_models)
        return FormattedText([
            ("class:header", "  ⚡  AIZEN Free Model Picker  "),
            ("class:count",  f"  {shown} / {total} free models  "),
        ])

    def _render_col_header(self):
        return FormattedText([
            ("class:col-header",
             f"    {'MODEL ID':<36} {'PROVIDER':<12} {'POLICY STATUS':<16} {'HEALTH':<12}"
             f"  {'CTX':>6}/{'IN':>6}/{'OUT':>6}  CAPABILITIES\n"),
        ])


    def _render_list(self):
        lines = []

        if not self.filtered:
            lines.append(("class:no-match",
                          "  No verified-free models match your filter. "
                          "Keep typing or clear to see all.\n"))
            return FormattedText(lines)

        visible = self.filtered[self.scroll: self.scroll + VISIBLE_ROWS]

        for rel, model in enumerate(visible):
            abs_i    = self.scroll + rel
            mid      = model.get("id", "")
            provider = str(model.get("owned_by", ""))[:11]
            ctx      = _fmt(model.get("context_length"))
            max_in   = _fmt(model.get("max_input_tokens"))
            max_out  = _fmt(model.get("max_output_tokens"))
            caps_str = _caps(model)

            # Health indicator (best-effort; defaults to neutral on any error)
            try:
                from core.provider_health import (
                    get_provider_for_model, get_health_indicator,
                )
                prov = get_provider_for_model(mid) or model.get("owned_by", "")
                health_str = get_health_indicator(prov) if prov else "· UNKNOWN"
            except Exception:
                health_str = "· UNKNOWN"

            is_sel = abs_i == self.sel_idx
            is_cur = mid   == config.current_model

            # Left-most marker column
            if is_cur and is_sel:
                mark = " ●▶ "
            elif is_cur:
                mark = " ●  "
            elif is_sel:
                mark = " ▶  "
            else:
                mark = "    "

            # Row style: highlight current model and selected row
            if is_cur and is_sel:
                row_cls = "class:model.current.selected"
            elif is_cur:
                row_cls = "class:model.current"
            elif is_sel:
                row_cls = "class:model.selected"
            else:
                row_cls = "class:model.normal"

            lines.append((row_cls, mark))
            lines.append((row_cls, f"{mid:<36}"))
            lines.append(("class:provider", f" {provider:<12}"))
            lines.append(("class:search-label", f" {'FREE VERIFIED':<16}"))
            lines.append(("class:provider", f" {health_str:<12}"))
            lines.append(("class:ctx",
                          f"  {ctx:>6}/{max_in:>6}/{max_out:>6}"))
            if caps_str:
                lines.append(("class:caps", f"  {caps_str}"))
            lines.append(("", "\n"))


        # Scroll position indicator (only when list overflows)
        total = len(self.filtered)
        if total > VISIBLE_ROWS:
            end = min(self.scroll + VISIBLE_ROWS, total)
            pct = int((self.scroll / max(1, total - VISIBLE_ROWS)) * 100)
            lines.append(("class:scroll-bar",
                          f"  ↕  rows {self.scroll + 1}–{end} of {total}"
                          f"  ({pct}%)   item {self.sel_idx + 1}\n"))

        return FormattedText(lines)

    def _render_search_label(self):
        return FormattedText([("class:search-label", " 🔍 Search: ")])

    def _render_footer(self):
        return FormattedText([
            ("class:footer",
             "  ↑ ↓ navigate    Enter select    Esc cancel    "
             "Home/End jump    PgUp/PgDn page"),
        ])

    # ---- Key bindings --------------------------------------------

    def _make_kb(self):
        kb = KeyBindings()

        @kb.add("up", eager=True)
        def _up(event):
            self._move(-1)

        @kb.add("down", eager=True)
        def _down(event):
            self._move(1)

        @kb.add("pageup", eager=True)
        def _pgup(event):
            self._move(-VISIBLE_ROWS)

        @kb.add("pagedown", eager=True)
        def _pgdn(event):
            self._move(VISIBLE_ROWS)

        @kb.add("home", eager=True)
        def _home(event):
            """Jump to first model in list."""
            self.sel_idx = 0
            self.scroll  = 0

        @kb.add("end", eager=True)
        def _end(event):
            """Jump to last model in list."""
            self.sel_idx = max(0, len(self.filtered) - 1)
            self._clamp_scroll()

        @kb.add("enter", eager=True)
        def _enter(event):
            if self.filtered:
                self.result = self.filtered[self.sel_idx].get("id")
            event.app.exit()

        @kb.add("escape", eager=True)
        def _esc(event):
            self.result = None
            event.app.exit()

        @kb.add("c-c", eager=True)
        def _ctrlc(event):
            self.result = None
            event.app.exit()

        return kb

    # ---- Application ---------------------------------------------

    def _build_app(self):
        search_win = Window(
            content=BufferControl(buffer=self.search_buf, focusable=True),
            height=1,
        )

        layout = Layout(
            HSplit([
                # Title bar
                Window(
                    content=FormattedTextControl(
                        self._render_header, focusable=False
                    ),
                    height=1,
                ),
                # Search row: [label] [buffer input]
                VSplit([
                    Window(
                        content=FormattedTextControl(
                            self._render_search_label, focusable=False
                        ),
                        width=13,
                    ),
                    search_win,
                ]),
                # Column header row
                Window(
                    content=FormattedTextControl(
                        self._render_col_header, focusable=False
                    ),
                    height=1,
                ),
                # Scrollable model list
                Window(
                    content=FormattedTextControl(
                        self._render_list, focusable=False
                    ),
                    height=VISIBLE_ROWS + 2,
                    wrap_lines=False,
                ),
                # Key hint footer
                Window(
                    content=FormattedTextControl(
                        self._render_footer, focusable=False
                    ),
                    height=1,
                ),
            ]),
            focused_element=search_win,
        )

        self.app = Application(
            layout=layout,
            key_bindings=self._make_kb(),
            style=PICKER_STYLE,
            full_screen=True,
            mouse_support=False,
        )

    # ---- Public --------------------------------------------------

    def run(self):
        """Launch the picker. Returns selected model id or None."""
        self.app.run()
        return self.result


# ------------------------------------------------------------------
# PUBLIC ENTRY POINT
# ------------------------------------------------------------------

def run_picker(filter_text=""):
    """
    High-level entry point:  fetch models → open picker → apply selection.

    Called from commands/handlers.py (/pick) and ui/prompts.py (Alt+M).
    Returns the selected model id or None if cancelled / OmniRoute offline.
    """
    from api.omniroute import fetch_models
    from core.free_model_registry import is_model_allowed
    from core.provider_health import get_provider_for_model
    from core.storage import save_config
    from ui.console import console, show_model_info

    # Ensure catalog is fresh; refresh from OmniRoute if needed
    if not config.model_catalog:
        if not fetch_models(show_message=False) or not config.model_catalog:
            console.print(
                "[yellow]No verified free models available.[/yellow]\n"
                "[dim]Paid and unverified models are blocked by AIZEN Free-Only mode.[/dim]"
            )
            return None
    else:
        # Silently attempt to refresh live catalog without blocking if offline
        fetch_models(show_message=False)

    if not config.model_catalog:
        console.print(
            "[yellow]No verified free models available.[/yellow]\n"
            "[dim]Paid and unverified models are blocked by AIZEN Free-Only mode.[/dim]"
        )
        return None

    # If a filter was given, check for matches; return to prompt if none
    effective_filter = (filter_text or "").strip()
    if effective_filter:
        q = effective_filter.lower()
        matched = [
            m for m in config.model_catalog
            if q in (
                m.get("id", "") + " " + str(m.get("owned_by", ""))
            ).lower()
        ]
        if not matched:
            console.print(
                f"[yellow]No verified free models available for this provider ('{effective_filter}').[/yellow]"
            )
            return None

    # Launch the interactive picker
    picker = ModelPicker(config.model_catalog, initial_filter=effective_filter)
    selected_id = picker.run()

    if selected_id is None:
        console.print("[dim]Picker cancelled — model unchanged.[/dim]")
        return None

    # Validate against central Free-Only registry
    prov = get_provider_for_model(selected_id)
    if not is_model_allowed(prov, selected_id):
        console.print(
            "\n[bold red]❌ Model is not available in AIZEN Free-Only mode.[/bold red]\n"
            "[dim]Only verified free models can be selected.[/dim]\n"
        )
        return None

    # Persist and confirm
    config.current_model = selected_id
    config.model_selection_mode = "manual"
    save_config()

    console.print(
        f"\n[bold green]✓ Model selected:[/bold green] "
        f"[cyan]{selected_id}[/cyan] [green](FREE VERIFIED)[/green]\n"
        "[dim]Manual model override enabled.[/dim]\n"
    )
    show_model_info(selected_message=True)
    return selected_id
