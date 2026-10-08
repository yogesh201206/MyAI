# AIZEN AI — Changelog

All notable changes to the **AIZEN AI** project are documented in this file.

---

## [1.0.0] — 2026-10-03 (Phase 15: Production Release & Hardening)

### Added
- **Global Versioning**: Integrated `AIZEN_VERSION = "1.0.0"`, `/version` command, and `--version` CLI flag.
- **Diagnostic Doctor**: Integrated `myai --doctor` and in-app `/doctor` health check suite inspecting Python runtime, virtual environment, OmniRoute server, SQLite databases, and voice engines.
- **Debug Mode**: Added `--debug` CLI flag, `/debug [on|off]` command, and controlled exception reporting.
- **Atomic Storage**: Re-architected `core/storage.py` with atomic writes via temporary files, fsync, and automatic recovery from `.bak` snapshots.
- **Comprehensive Test Suite**: Created `tests/test_phase15.py` with 73 automated unit and integration tests across storage, safety, routing, CLI, and UI subsystems.
- **Production Documentation**: Published `README.md`, `USER_GUIDE.md`, `DEVELOPER_GUIDE.md`, `SECURITY.md`, `TROUBLESHOOTING.md`, and `RELEASE_CHECKLIST.md`.
- **Packaging & Git**: Added `.gitignore`, `requirements.txt`, and executable `install.sh`.

### Fixed
- Fixed bug in `ui/console.py` where provider health summaries were omitted from the home dashboard due to loop indentation.
- Eliminated dead monolithic backup file (`myai_before_modelpicker.py`).
- Transitioned API key loading to prioritize `OMNIROUTE_API_KEY` environment variables.
- Hardened `start-myai.sh` launcher with dynamic OmniRoute binary resolution and argument forwarding.

---

## [0.14.0] — Phase 14: Polishing & Resilience
- Improved terminal UI rendering and prompt_toolkit auto-completion styling.
- Added session statistics and token breakdown panels.

## [0.13.0] — Phase 13: Local Voice Mode
- Added push-to-talk speech-to-text powered by `faster-whisper`.
- Added text-to-speech output playback powered by `pyttsx3` / eSpeak.
- Added `/voice [on|off|ptt|stop|speed|language]` control commands.

## [0.12.0] — Phase 12: Real-Time Web Research
- Added DuckDuckGo web search integration via `/search`.
- Added multi-source deep research pipeline with HTML scraping and synthesis via `/research`.

## [0.11.0] — Phase 11: AIZEN Smart Router
- Built heuristic classifier for coding, math, reasoning, creative, and fast chit-chat tasks.
- Enabled automatic model switching based on prompt intent via `/route auto`.

## [0.10.0] — Phase 10: Safe Terminal Execution & Autonomous Developer Agent
- Built deterministic 5-tier command safety sandbox (`READ_ONLY`, `SAFE_BUILD`, `WRITE`, `DANGEROUS`, `BLOCKED`).
- Implemented multi-step autonomous developer agent mode (`/agent on`).

## [0.9.0] — Phase 9: Safe Code Editing & Diff Rollback
- Added unified diff generator (`/diff`) and atomic file patch applier (`/apply`).
- Created backup checkpoint manager with instant rollback capability (`/undo`).

## [0.8.0] — Phase 8: Project-Aware Assistant
- Added project workspace detection and context gathering via `/project`.
- Added recursive codebase indexing and file structure representation.

## [0.7.0] — Phase 7: Local RAG Knowledge Base
- Implemented local embeddings with `sentence-transformers` (`all-MiniLM-L6-v2`).
- Added FAISS vector database integration for PDF and text document retrieval (`/rag index`).

## [0.6.0] — Phase 6: File Attachments & Context
- Added `/attach` command supporting files and directories.
- Implemented auto-detection of binary files and file size thresholds.

## [0.5.0] — Phase 5: Persistent Usage Analytics
- Created SQLite database schema in `~/.myai/aizen.db`.
- Added prompt/completion token tracking and `/usage` analytics command.

## [0.4.0] — Phase 4: Provider Health Dashboard
- Built asynchronous health checker for connected AI providers.
- Added `/providers` dashboard displaying latency, status, and error rates.

## [0.3.0] — Phase 3: Streaming Responses
- Implemented low-latency Server-Sent Events (SSE) streaming consumer.
- Added live Markdown rendering and syntax highlighting in Rich console.

## [0.2.0] — Phase 2: Interactive Model Picker
- Built full-screen interactive keyboard browser (`/models`).
- Added fuzzy search, pagination, and persistent model selection.

## [0.1.0] — Phase 1: Modular Refactor
- Refactored monolithic prototype into clean modular packages: `core/`, `ui/`, `commands/`.
