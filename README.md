# AIZEN AI — Terminal Intelligence powered by OmniRoute

```
     █████╗ ██╗███████╗███████╗███╗   ██╗
    ██╔══██╗██║╚══███╔╝██╔════╝████╗  ██║
    ███████║██║  ███╔╝ █████╗  ██╔██╗ ██║
    ██╔══██║██║ ███╔╝  ██╔══╝  ██║╚██╗██║
    ██║  ██║██║███████╗███████╗██║ ╚████║
    ╚═╝  ╚═╝╚═╝╚══════╝╚══════╝╚═╝  ╚═══╝

   AIZEN AI • Multi-Model Intelligence v1.0.0
```

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Production](https://img.shields.io/badge/status-production--ready-brightgreen.svg)]()
[![OmniRoute](https://img.shields.io/badge/OmniRoute-connected-brightgreen.svg)](http://localhost:20128)

**AIZEN AI** is an advanced terminal-first multi-model AI assistant engineered for developers, power users, and researchers. Connected directly to **OmniRoute**, AIZEN provides real-time streaming, interactive model switching across 500+ models, multi-turn chat management, local RAG document retrieval, safe code editing, an autonomous developer agent with terminal sandboxing, smart routing, voice input/output, and live web research.

---

## ✨ Features at a Glance

| Subsystem | Highlights |
| :--- | :--- |
| **Free-Only Model Engine** | Provider-agnostic Free Model Registry exposing ONLY verified-free LLMs. Strict default-deny blocks paid/unknown models. Interactive picker (`/pick`, `/models`), fuzzy search, and `/use` protection. |
| **Real-Time Streaming** | Low-latency token-by-token streaming response rendering with smooth markdown formatting and code highlighting. Toggle with `/stream`. |
| **Smart Router** | Intelligently classifies prompt intent and routes only to eligible verified-free models automatically. Never falls back to paid routes. |
| **Local RAG & Knowledge Base** | Vector search over local PDFs, codebases, and documents using local embeddings (`sentence-transformers` + `FAISS`). Toggle with `/rag`. |
| **Developer Agent** | Multi-step autonomous agent (`/agent on`) with native tools: file read/write, file search, directory listing, and command execution. |
| **Safe Code Editing** | Unified diff generation, backup checkpoints, apply, and instant rollback (`/diff`, `/apply`, `/undo`) before any file modification. |
| **Safe Terminal Execution** | Strict security boundary (`READ_ONLY`, `SAFE_BUILD`, `WRITE`, `DANGEROUS`, `BLOCKED`) with explicit confirmation gates. |
| **Voice Mode** | Local-first push-to-talk speech-to-text (`faster-whisper`) and text-to-speech (`pyttsx3`/`espeak`) with device selection. |
| **Web Research** | Real-time web search and content extraction via DuckDuckGo and Beautiful Soup. Toggle with `/search` or `/research`. |
| **Health & Analytics** | Real-time provider status dashboard (`/providers`), usage tracking (`/usage`), and SQLite analytics (`~/.myai/aizen.db`). |
| **Production Hardened** | Atomic file writes, automatic backup & recovery on JSON corruption, CLI diagnostics (`--doctor`), `--debug` mode. |

---

## 🚀 Quick Start

### 1. Installation

Clone the repository and run the automated installer:

```bash
git clone https://github.com/your-org/myai.git
cd myai
bash install.sh
```

The installer verifies Python ≥ 3.10, creates the `.venv` virtual environment, installs all dependencies, locates your OmniRoute server, initializes storage directories, and links the `myai` launcher.

### 2. Launching AIZEN

Start AIZEN AI directly:

```bash
./start-myai.sh
```

Or using the installed command:

```bash
myai
```

### 3. Command Line Flags

```bash
myai                 # Start AIZEN AI
myai --version       # Show version and system information
myai --doctor        # Run environment and service health diagnostics
myai --debug         # Launch in debug mode with full stack traces
myai --help          # Display command line help
```

---

## ⌨️ Command Cheatsheet

### Core & Navigation
| Command | Description |
| :--- | :--- |
| `/help` | Display comprehensive command reference |
| `/cls` | Clear terminal and restore the AIZEN home dashboard |
| `/status` | Display current active settings and provider state |
| `/doctor` | Run deep health check of all dependencies and services |
| `/version` | Display AIZEN version, Python runtime, and OmniRoute status |
| `/debug [on\|off]` | Toggle debug logging and tracebacks |
| `/exit` | Exit AIZEN AI cleanly |

### Models & Routing
| Command | Description |
| :--- | :--- |
| `/models` | Open interactive interactive model browser |
| `/use <name\|num>` | Switch to a specific model by ID or picker index |
| `/route [auto\|manual]` | Toggle Smart Routing or view routing strategy |
| `/stream [on\|off]` | Toggle streaming token output |
| `/providers` | Display provider health status and latency |
| `/usage` | Display token usage and session cost analytics |

### Chats & Sessions
| Command | Description |
| :--- | :--- |
| `/new` | Start a fresh chat session |
| `/chats` | List all saved chat sessions |
| `/load <id>` | Load an existing chat session |
| `/delete <id>` | Delete a saved chat session |
| `/clear` | Clear the current conversation history |

### Project & Knowledge Base
| Command | Description |
| :--- | :--- |
| `/attach <path>` | Attach a file or folder context to the conversation |
| `/rag [on\|off]` | Toggle local RAG retrieval |
| `/rag index <path>` | Index a directory or PDF into the vector database |
| `/project [path]` | Set active project workspace directory |

### Code & Terminal Safety
| Command | Description |
| :--- | :--- |
| `/agent [on\|off]` | Toggle autonomous developer agent mode |
| `/diff` | Review staged code changes before applying |
| `/apply` | Apply staged changes with automatic backup |
| `/undo` | Roll back recent file edits from backup |
| `/tools` | List registered agent tools and schemas |

### Voice & Web Search
| Command | Description |
| :--- | :--- |
| `/voice [on\|off]` | Toggle voice mode |
| `/voice ptt` | Trigger push-to-talk speech input |
| `/voice stop` | Stop active text-to-speech playback |
| `/search <query>` | Perform real-time web search |
| `/research <query>` | Deep web research with source synthesis |

---

## 🏗️ Architecture

AIZEN AI is structured into decoupled, single-responsibility modules:

```
myai/
├── myai.py                 # CLI entry point with argument dispatch
├── start-myai.sh           # Safe launcher with OmniRoute daemon management
├── install.sh              # Production installation and dependency script
├── config.py               # Central configuration, constants, and global state
├── app.py                  # Main application loop and lifecycle manager
│
├── core/                   # Core business logic and engine subsystems
│   ├── api.py              # OmniRoute HTTP client with streaming support
│   ├── command_safety.py   # Deterministic command classification & safety sandbox
│   ├── diff_engine.py      # Safe diff generator, backup manager, and rollback
│   ├── model_picker.py     # Fuzzy search and model catalog manager
│   ├── provider_health.py  # Health monitoring and fallback circuit breaker
│   ├── rag_engine.py       # FAISS vector store and document chunker
│   ├── router.py           # Smart task classification and model router
│   ├── speech_to_text.py   # faster-whisper local STT engine
│   ├── text_to_speech.py   # pyttsx3 / eSpeak local TTS engine
│   ├── storage.py          # Atomic disk I/O and self-healing JSON recovery
│   ├── token_manager.py    # Context window tracking and human token math
│   ├── tool_registry.py    # Developer agent tool declarations and schemas
│   └── web_search.py       # DuckDuckGo and web scraping pipelines
│
├── ui/                     # Terminal user interface components (Rich)
│   ├── banner.py           # ASCII branding and startup splash
│   ├── console.py          # Theme definition, panels, tables, and home screen
│   ├── picker.py           # Interactive keyboard model browser
│   └── prompts.py          # prompt_toolkit bindings, auto-completion, styling
│
├── commands/               # Slash command controllers
│   └── handlers.py         # Command dispatcher and execution handlers
│
├── tests/                  # Comprehensive unit & regression test suite
│   ├── __init__.py
│   └── test_phase15.py     # 70+ automated unit and integration tests
│
└── docs/                   # Full documentation suite
    ├── USER_GUIDE.md       # Comprehensive user manual
    ├── DEVELOPER_GUIDE.md  # Architecture, APIs, and extension guide
    ├── SECURITY.md         # Security model, sandbox rules, and disclosures
    ├── TROUBLESHOOTING.md  # Failure recovery and debugging guide
    ├── CHANGELOG.md        # Release history across all 15 phases
    └── RELEASE_CHECKLIST.md# Production deployment checklist
```

---

## 🔒 Security & Safety

- **Atomic Writes**: All state mutations (`chats.json`, `config.json`) use temporary files with atomic rename operations to prevent corruption during sudden crashes or power loss.
- **Auto-Recovery**: Corrupt JSON files are automatically quarantined with `.bak` rollback.
- **Execution Sandboxing**: Commands proposed by the agent pass through `core/command_safety.py`. Commands in `BLOCKED` (such as `rm -rf /` or disk wiping) cannot be executed under any circumstance. Dangerous commands require affirmative user confirmation.
- **Secret Isolation**: API keys are read from `OMNIROUTE_API_KEY` environment variables with no hardcoded secret leakage.

---

## 🧪 Testing

Run the automated test suite:

```bash
PYTHONPATH=. .venv/bin/python -m unittest tests/test_phase15.py
```

---

## 📄 License

AIZEN AI is open source software released under the [MIT License](LICENSE).
