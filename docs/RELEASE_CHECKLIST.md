# AIZEN AI — Release Checklist

Use this checklist before releasing or distributing a new version of **AIZEN AI**.

---

## 1. Codebase & Integrity Checks
- [x] All syntax valid across all Python source files (`find . -name "*.py" | xargs python -m py_compile`).
- [x] No lingering dead code, obsolete monoliths, or scratch files.
- [x] `config.py` contains valid version number matching Git tag (`AIZEN_VERSION = "1.0.0"`).
- [x] All imports verified without circular dependency errors.

## 2. Security & Credentials
- [x] No hardcoded sensitive API keys in source files.
- [x] Secrets loaded via environment variables (`OMNIROUTE_API_KEY`).
- [x] `.gitignore` properly excludes `.venv/`, `~/.myai/`, `*.db`, `*.log`, and temporary files.
- [x] Terminal safety classifier blocks dangerous root modifications (`rm -rf /`, `mkfs`).

## 3. Storage & Resilience
- [x] Atomic write functions in `core/storage.py` preserve state on interrupted execution.
- [x] Automatic backup recovery active for `config.json` and `chats.json`.
- [x] Default values correctly populate on missing or fresh configurations.

## 4. CLI & UX Validation
- [x] `myai --version` outputs clean version info and exits with code 0.
- [x] `myai --help` displays command usage.
- [x] `myai --doctor` runs comprehensive system diagnostics without throwing unhandled exceptions.
- [x] `myai --debug` starts AIZEN with tracebacks enabled.
- [x] In-app `/doctor`, `/version`, `/debug` commands function identically.
- [x] `start-myai.sh` auto-detects OmniRoute and forwards all command-line arguments.

## 5. Automated Tests
- [x] All automated unit tests in `tests/test_phase15.py` pass (`OK`).
- [x] Regression tests cover storage, safety, routing, CLI, and UI subsystems.

## 6. Documentation
- [x] `README.md` updated with feature highlights, quickstart, and command table.
- [x] `docs/USER_GUIDE.md` details every user workflow and slash command.
- [x] `docs/DEVELOPER_GUIDE.md` details architecture, state management, and tool extensions.
- [x] `docs/SECURITY.md` defines the sandbox policy and vulnerability reporting.
- [x] `docs/TROUBLESHOOTING.md` provides solutions for common audio, OmniRoute, and RAG issues.
- [x] `docs/CHANGELOG.md` tracks all 15 development phases.
