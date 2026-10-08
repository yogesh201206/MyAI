# AIZEN AI — User Guide

Welcome to **AIZEN AI**, the terminal assistant designed for seamless multi-model intelligence. This guide covers daily workflows, all slash commands, and advanced features.

---

## Table of Contents
1. [Starting AIZEN](#starting-aizen)
2. [Interface Overview](#interface-overview)
3. [Model Selection & Browsing](#model-selection--browsing)
4. [Streaming & Output Customization](#streaming--output-customization)
5. [Managing Chats & Sessions](#managing-chats--sessions)
6. [Smart Routing](#smart-routing)
7. [Local RAG & Knowledge Base](#local-rag--knowledge-base)
8. [Developer Agent & Safe Tools](#developer-agent--safe-tools)
9. [Safe Code Editing (Diff / Apply / Undo)](#safe-code-editing)
10. [Safe Terminal Execution](#safe-terminal-execution)
11. [Voice Mode (Speech-to-Text & Text-to-Speech)](#voice-mode)
12. [Web Search & Research](#web-search--research)
13. [Diagnostics & Troubleshooting](#diagnostics--troubleshooting)

---

## 1. Starting AIZEN

Launch AIZEN AI from your terminal:

```bash
myai
```

Or using the local shell script:

```bash
./start-myai.sh
```

### CLI Flags
- `myai --help`: View available command-line flags.
- `myai --version`: Display current version and system environment.
- `myai --doctor`: Perform health checks on local services, OmniRoute, and voice engines.
- `myai --debug`: Launch AIZEN with debug mode enabled (detailed stack traces on errors).

---

## 2. Interface Overview

On startup, AIZEN displays the status dashboard:

- **Chat**: Current active chat title.
- **Selected Model**: The active model ID or `auto` if Smart Routing is active.
- **Provider**: The backend provider handling requests.
- **Models**: Number of models discovered on OmniRoute.
- **OmniRoute**: Server connection indicator (`● Connected` / `○ Offline`).
- **Streaming**: Output mode (`ON` or `OFF`).
- **Providers**: Health summary of connected model providers.
- **Agent**: Autonomous developer mode (`ON` or `OFF`).
- **Route**: Routing engine state (`AUTO` or `MANUAL`).

---

## 3. Model Selection & Browsing (Free-Only Policy)

AIZEN enforces a strict provider-agnostic **Free-Only Model Policy**. Only models explicitly verified as genuinely free through their configured API access appear in the catalog. All paid, billing-required, promotional-credit, or unknown models are hidden by default.

### Interactive Picker (`/pick` or `Alt+M`)
Type `/pick` or press `Alt+M` to launch the interactive full-screen picker for verified-free models.
- **Up / Down arrows**: Move selection.
- **Type text**: Live fuzzy-search by model name or provider (e.g. `/pick groq`).
- **Enter**: Select highlighted model.
- **Esc / Ctrl+C**: Cancel picker and keep current model.
- **Policy status**: Shows `FREE VERIFIED` alongside provider health.

### Models Table (`/models`)
Type `/models` to display a table of all available verified-free models:
- `/models`: Lists verified-free models.
- `/models <filter>`: Filters verified-free models by query keyword.

### Direct Switch (`/use`)
Select a model by list number or exact verified ID:
```text
/use 1
/use groq/openai/gpt-oss-120b
/use auto
```
Attempting to select an unverified or paid model is strictly rejected with a cost-protection warning:
```text
❌ Model is not available in AIZEN Free-Only mode.
Only verified free models can be selected.
```

---

## 4. Streaming & Output Customization

By default, responses stream token-by-token with syntax-highlighted Markdown.
- Toggle streaming off: `/stream off`
- Toggle streaming on: `/stream on`
- Check streaming state: `/stream`

---

## 5. Managing Chats & Sessions

Conversations are automatically saved to `~/.myai/chats.json` with atomic writes.

- `/new`: Start a new conversation.
- `/chats`: List recent conversations with their IDs, dates, and message counts.
- `/load <id>`: Switch to a past conversation.
- `/delete <id>`: Remove a conversation permanently.
- `/clear`: Clear the messages in the current conversation without creating a new session.

---

## 6. Smart Routing

The AIZEN Smart Router analyzes your prompt intent and routes the query to the best suited model automatically:

| Intent Category | Typical Routing Target | Example Queries |
| :--- | :--- | :--- |
| **Coding** | Claude 3.5 Sonnet / GPT-4o | "Refactor this async function" |
| **Reasoning / Math** | DeepSeek R1 / o1 | "Solve this combinatorics problem" |
| **Fast / Chit-chat** | Llama 3.3 70B / Groq | "Summarize this in three bullets" |
| **Creative / Long** | Gemini 1.5 Pro | "Draft a blog post about distributed consensus" |

- `/route auto`: Enable automatic model selection based on intent.
- `/route manual`: Lock model to the user's manual selection.
- `/route`: Display current routing strategy and recent routing decisions.

---

## 7. Local RAG & Knowledge Base

AIZEN can index documents and source repositories to ground answers in your local files without uploading data to external third parties.

### Indexing
```text
/rag index ./docs
/rag index ~/notes/meeting.pdf
```
Supported formats: `.txt`, `.md`, `.py`, `.js`, `.json`, `.pdf`, `.rst`.

### Querying
When RAG is enabled, AIZEN retrieves relevant chunks via vector similarity (FAISS) and injects them into the prompt context:
- `/rag on`: Enable RAG context retrieval.
- `/rag off`: Disable RAG context retrieval.
- `/rag status`: Check indexed documents, vector dimensions, and store size.

---

## 8. Developer Agent & Safe Tools

Enable agent mode to allow AIZEN to autonomously inspect directories, read source code, propose diffs, and run test suites:

- `/agent on`: Activate developer agent.
- `/agent off`: Deactivate agent mode.
- `/tools`: View the registered agent tools (`file_read`, `file_write`, `file_search`, `list_files`, `run_command`).

When agent mode is active, AIZEN creates multi-step plans and requests confirmation before modifying state.

---

## 9. Safe Code Editing

AIZEN never mutates source files blindly.

1. **Review Diffs**: Whenever the assistant or agent proposes file modifications, run `/diff` to inspect colored unified diffs in your terminal.
2. **Apply Changes**: Run `/apply` to accept and write the changes. An atomic backup checkpoint is automatically captured.
3. **Rollback**: Made a mistake? Run `/undo` to revert modified files to their previous checkpoint.

---

## 10. Safe Terminal Execution

When executing shell commands, AIZEN classifies commands using a strict 5-tier safety engine:

- **READ_ONLY** (`ls`, `cat`, `git status`): Safe to run without side effects.
- **SAFE_BUILD** (`npm test`, `pytest`, `cargo check`): Builds or tests code without altering source files.
- **WRITE** (`touch`, `mkdir`, `git checkout`): Alters files or state; prompts user confirmation.
- **DANGEROUS** (`git reset --hard`, `sudo`, `kill`): Prompts with high-visibility warning.
- **BLOCKED** (`rm -rf /`, `mkfs`, fork bombs): **Strictly blocked.** AIZEN will refuse to execute these commands under any condition.

---

## 11. Voice Mode

Interact with AIZEN using your voice:

- `/voice on`: Enable voice mode.
- `/voice off`: Disable voice mode.
- `/voice ptt`: Trigger push-to-talk recording. Speak your prompt, and press Enter to transcribe and send.
- `/voice stop`: Immediately stop active text-to-speech audio output.
- `/voice speed <0.5-2.0>`: Adjust speech rate.
- `/voice language <en|es|fr|...>`: Configure speech recognition language.

---

## 12. Web Search & Research

Fetch real-time information from the web:

- `/search <query>`: Perform a fast web search and summarize key findings with links.
- `/research <query>`: Conduct multi-source deep research, extracting web page contents and synthesizing a structured technical brief.

---

## 13. Diagnostics & Troubleshooting

If you encounter issues:

- `/status`: Verify model state, provider latency, and tokens.
- `/doctor`: Run automated verification on Python environment, OmniRoute port 20128, local databases, and audio backends.
- `/debug on`: Enable verbose diagnostic logging.
