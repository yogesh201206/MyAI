# AIZEN AI — Developer & Architecture Guide

This document describes the internal architecture of **AIZEN AI**, its design patterns, module contracts, state flow, and guidelines for extending functionality.

---

## 1. Architectural Philosophy

AIZEN AI is designed around four core engineering principles:

1. **Modularity over Monoliths**: Subsystems (voice, safety, RAG, diff, routing, terminal UI) live in dedicated modules with explicit APIs.
2. **Defensive Storage & Crash Resilience**: Never lose user conversations or corrupt configuration files. Every write is atomic (`tempfile.NamedTemporaryFile` + `os.replace`), and corrupt files trigger automatic backup recovery.
3. **Safety by Default**: Autonomous agent actions (file edits, terminal execution) pass through explicit safety boundaries with dry-run diffs and classification before touching disk or executing shell commands.
4. **Rich Terminal Experience**: Pure Rich + prompt_toolkit interfaces without heavy web frameworks, providing blazing fast sub-second startup and low memory footprint.

---

## 2. Directory Layout & Module Responsibilities

```text
myai/
├── config.py               # Shared global state, defaults, and environment resolution
├── app.py                  # Main REPL orchestration loop
├── myai.py                 # CLI entry point, argument parser, and launcher
│
├── core/                   # Subsystems and business logic
│   ├── api.py              # OmniRoute client (streaming, non-streaming, fallback)
│   ├── command_safety.py   # Shell command parser and 5-tier safety classifier
│   ├── diff_engine.py      # Git-style diff generator, file applier, checkpoint backup
│   ├── model_picker.py     # Fuzzy model search, cache, and filtering
│   ├── provider_health.py  # Provider ping, latency measurement, circuit breaker
│   ├── rag_engine.py       # FAISS indexing, PDF/text parsing, similarity search
│   ├── router.py           # Prompt classifier and dynamic model selection
│   ├── speech_to_text.py   # faster-whisper integration for push-to-talk
│   ├── text_to_speech.py   # pyttsx3 / espeak audio playback worker
│   ├── storage.py          # Atomic JSON serialization with backup recovery
│   ├── token_manager.py    # Usage tracking, token estimation, SQLite logging
│   ├── tool_registry.py    # Native tool schemas (file_read, file_write, etc.)
│   └── web_search.py       # Live web search and HTML scraping pipelines
│
├── ui/                     # Terminal presentation layer
│   ├── banner.py           # Startup banner, splash headers, shutdown animations
│   ├── console.py          # Rich console singleton, styles, home dashboard, help
│   ├── picker.py           # Keyboard-navigable interactive model selector
│   └── prompts.py          # prompt_toolkit autocompletion, keybindings, input REPL
│
├── commands/               # Slash command controllers
│   └── handlers.py         # Central command router (/help, /rag, /route, etc.)
│
└── tests/                  # Automated test suite
    └── test_phase15.py     # 70+ test cases covering all subsystems
```

---

## 3. State Management & Configuration Flow

State is managed centrally in `config.py` and persisted in `~/.myai/config.json`.

```
                    ┌─────────────────────────┐
                    │    ~/.myai/config.json  │
                    └───────────┬─────────────┘
                                │ load_config() [atomic / safe backup]
                                ▼
                    ┌─────────────────────────┐
                    │        config.py        │
                    │   (Shared Global State) │
                    └───────────┬─────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
  ui/console.py           commands/handlers.py      core/router.py
  (Renders UI)            (Modifies State)          (Reads State)
```

### Key State Variables:
- `config.current_model`: Active model string or `"auto"`.
- `config.streaming_enabled`: Boolean flag for token streaming.
- `config.rag_enabled`: Boolean flag for vector retrieval injection.
- `config.agent_enabled`: Boolean flag for autonomous multi-step tool calls.
- `config.router_mode`: `"auto"` (smart router) or `"manual"`.
- `config.debug_mode`: Boolean flag for verbose error tracebacks.

### Persistence Protocol (`core/storage.py`):
1. Create backup: copy `config.json` -> `config.json.bak`.
2. Write new contents to temporary file in the same directory (`~/.myai/.config.json.tmp_...`).
3. Flush and `os.fsync` the file descriptor.
4. Perform atomic rename `os.replace(temp_path, final_path)`.
5. If primary file is corrupted, `load_config()` recovers from `config.json.bak`.

---

## 4. Autonomous Agent Architecture & Safe Execution

When `agent_enabled` is active, user prompts are evaluated against `core/tool_registry.py`.

```
User Query ──► Model ──► Tool Call JSON ──► Safety Sandbox ──► Confirmation ──► Execute
                                                    │
                                         [READ_ONLY / WRITE / ...]
                                         [BLOCKED -> Hard Stop]
```

### Adding a New Agent Tool
1. Open `core/tool_registry.py`.
2. Add a `Tool` dataclass instance to `_BUILTIN_TOOLS`:
   ```python
   Tool(
       name="calculate_hash",
       description="Computes SHA256 checksum of a file.",
       parameters={
           "type": "object",
           "properties": {
               "path": {"type": "string", "description": "Relative file path"}
           },
           "required": ["path"]
       }
   )
   ```
3. Implement the execution handler in `core/tool_registry.py` or `commands/handlers.py`.

---

## 5. Adding New Slash Commands

Slash commands are registered in `commands/handlers.py`:

1. Define the command syntax in `ui/prompts.py` under `COMMANDS` list for tab completion.
2. In `commands/handlers.py`, add a branch to `handle_command(user_input)`:
   ```python
   elif cmd == "/mycommand":
       console.print("[bold green]Executing my command![/bold green]")
       return True
   ```
3. Document the command in `ui/console.py` (`show_help()`) and in `docs/USER_GUIDE.md`.

---

## 6. Testing & Quality Assurance

Unit and regression tests are implemented using Python's standard `unittest` framework:

```bash
# Run all tests
PYTHONPATH=. .venv/bin/python -m unittest tests/test_phase15.py

# Run specific test class
PYTHONPATH=. .venv/bin/python -m unittest tests.test_phase15.TestConfigAtomicWrite

# Run with verbose output
PYTHONPATH=. .venv/bin/python -m unittest -v tests/test_phase15.py
```

### Mocking Guidelines:
Hardware (microphone, speakers) and external network dependencies (OmniRoute server, duckduckgo) should be mocked using `unittest.mock.patch` to guarantee fast, deterministic tests on headless CI environments.
