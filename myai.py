#!/home/yoges/myai/.venv/bin/python
"""
myai.py — AIZEN AI entry point.

Handles CLI arguments then delegates to app.main().

Usage:
    myai                 Start AIZEN AI
    myai --version       Print version and exit
    myai --debug         Start in debug mode (verbose errors/timing)
    myai --doctor        Run diagnostics and exit
    myai --help          Show help
"""

import sys
import os

# Ensure the project root is on the path when invoked directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _print_version():
    import config
    import platform
    print(f"AIZEN AI v{config.AIZEN_VERSION}")
    print(f"Python {platform.python_version()} on {platform.system()} {platform.machine()}")
    try:
        import subprocess
        result = subprocess.run(
            ["omniroute", "--version"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            print(f"OmniRoute {result.stdout.strip()}")
    except Exception:
        pass


def _run_doctor():
    """Run full diagnostics and print a health report."""
    import platform
    import shutil
    import socket
    import config

    PASS = "[✓]"
    FAIL = "[✗]"
    WARN = "[!]"

    results = []

    def check(label, ok, note=""):
        mark = PASS if ok else FAIL
        results.append((mark, label, note))

    # Python version
    py_ok = sys.version_info >= (3, 10)
    check("Python ≥ 3.10", py_ok, f"Found {platform.python_version()}")

    # Virtual environment
    in_venv = hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )
    check("Virtual environment", in_venv, sys.prefix)

    # AIZEN installation
    check("AIZEN files", os.path.isfile(__file__), __file__)

    # OmniRoute binary
    omni_bin = shutil.which("omniroute")
    if not omni_bin:
        # Check common NVM path
        nvm_path = os.path.expanduser("~/.nvm/versions/node")
        if os.path.isdir(nvm_path):
            for ver_dir in sorted(os.listdir(nvm_path), reverse=True):
                candidate = os.path.join(nvm_path, ver_dir, "bin", "omniroute")
                if os.path.isfile(candidate):
                    omni_bin = candidate
                    break
    check("OmniRoute binary", bool(omni_bin), omni_bin or "not found in PATH")

    # OmniRoute server connectivity
    omni_ok = False
    try:
        s = socket.create_connection(("127.0.0.1", 20128), timeout=2)
        s.close()
        omni_ok = True
    except Exception as e:
        pass
    check("OmniRoute server (port 20128)", omni_ok,
          "Running" if omni_ok else "Offline — run: omniroute serve  OR  myai (auto-starts)")

    # API endpoint
    api_ok = False
    if omni_ok:
        try:
            import requests
            r = requests.get(config.MODELS_URL,
                             headers={"Authorization": f"Bearer {config.API_KEY}"},
                             timeout=5)
            api_ok = r.status_code == 200
        except Exception:
            pass
    check("OmniRoute API endpoint", api_ok, config.MODELS_URL if api_ok else "Unreachable (start OmniRoute first)")

    # Configuration file
    cfg_ok = os.path.isfile(config.CONFIG_FILE)
    if cfg_ok:
        try:
            import json
            with open(config.CONFIG_FILE) as f:
                json.load(f)
        except Exception:
            cfg_ok = False
    check("Configuration file", cfg_ok, config.CONFIG_FILE)

    # Chat storage
    chats_ok = os.path.isfile(config.CHATS_FILE)
    if chats_ok:
        try:
            import json
            with open(config.CHATS_FILE) as f:
                json.load(f)
        except Exception:
            chats_ok = False
    check("Chat storage", chats_ok, config.CHATS_FILE)

    # Analytics DB
    check("Analytics database", os.path.isfile(config.ANALYTICS_DB), config.ANALYTICS_DB)

    # Writable data dir
    data_writable = os.access(config.DATA_DIR, os.W_OK)
    check("Data directory writable", data_writable, config.DATA_DIR)

    # Voice: sounddevice / PortAudio
    try:
        import sounddevice as sd
        sd.query_devices()
        voice_audio_ok = True
    except Exception as e:
        voice_audio_ok = False
    results.append(
        (WARN if not voice_audio_ok else PASS,
         "Voice / PortAudio",
         "Available" if voice_audio_ok else "Unavailable (optional — text mode works fine)")
    )

    # Voice: pyttsx3 / eSpeak
    try:
        import pyttsx3
        pyttsx3.init()
        tts_ok = True
    except Exception:
        tts_ok = False
    results.append(
        (WARN if not tts_ok else PASS,
         "Text-to-speech / eSpeak",
         "Available" if tts_ok else "Unavailable (optional — install espeak via apt)")
    )

    # faster-whisper STT
    try:
        import faster_whisper
        stt_ok = True
    except ImportError:
        stt_ok = False
    results.append(
        (WARN if not stt_ok else PASS,
         "Speech-to-text / faster-whisper",
         "Available" if stt_ok else "Unavailable (optional)")
    )

    # Web search deps
    try:
        import bs4
        web_ok = True
    except ImportError:
        web_ok = False
    results.append(
        (WARN if not web_ok else PASS,
         "Web search (beautifulsoup4)",
         "Available" if web_ok else "Unavailable (optional)")
    )

    # Print report
    print()
    print("╭──────────────────────────────────────────────────────╮")
    print(f"│  AIZEN AI v{config.AIZEN_VERSION} — Doctor / Health Report              │")
    print("╰──────────────────────────────────────────────────────╯")
    print()
    for mark, label, note in results:
        note_str = f"  {note}" if note else ""
        print(f"  {mark} {label}{note_str}")
    print()

    failures = [r for r in results if r[0] == FAIL]
    if failures:
        print(f"  {FAIL} {len(failures)} critical issue(s) found. See above for details.")
    else:
        print(f"  {PASS} All critical checks passed.")
    print()


def main():
    args = sys.argv[1:]

    if "--version" in args or "-v" in args:
        _print_version()
        sys.exit(0)

    if "--doctor" in args:
        # Need to set up paths and config before doctor
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        _run_doctor()
        sys.exit(0)

    if "--help" in args or "-h" in args:
        print("AIZEN AI — Terminal Intelligence powered by OmniRoute")
        print()
        print("Usage:")
        print("  myai                 Start AIZEN AI (auto-starts OmniRoute if needed)")
        print("  myai --version       Print version info and exit")
        print("  myai --debug         Start with debug mode enabled")
        print("  myai --doctor        Run diagnostics and exit")
        print("  myai --help          Show this help")
        print()
        print("In-app commands: type /help after starting AIZEN AI")
        sys.exit(0)

    if "--debug" in args:
        import config as cfg
        cfg.debug_mode = True

    if args and args[0].startswith("/"):
        cmd_str = " ".join(args)
        from core.storage import setup_storage, load_chats, load_config
        from api.omniroute import fetch_models
        from commands.handlers import handle_command
        setup_storage()
        load_chats()
        load_config()
        fetch_models()
        handle_command(cmd_str)
        sys.exit(0)

    from app import main as app_main
    app_main()


if __name__ == "__main__":
    main()
