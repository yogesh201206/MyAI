#!/usr/bin/env bash
# =============================================================================
# AIZEN AI — Launcher Script
# =============================================================================
# Auto-detects and starts OmniRoute if not already running, then launches AIZEN.
# Any arguments passed to this script are forwarded to AIZEN AI.
#
# Usage:
#   ./start-myai.sh [args...]
#   ./start-myai.sh --doctor
#   ./start-myai.sh --version
#   ./start-myai.sh --debug
# =============================================================================

set -u

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done

AIZEN_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
AIZEN_PY="$AIZEN_DIR/.venv/bin/python"
AIZEN_APP="$AIZEN_DIR/myai.py"

OMNI_HOST="127.0.0.1"
OMNI_PORT="20128"

OMNI_LOG="$HOME/.myai/omniroute.log"
OMNI_PID="$HOME/.myai/omniroute.pid"

mkdir -p "$HOME/.myai"

# Fallback to system python if venv python not found
if [ ! -x "$AIZEN_PY" ]; then
    AIZEN_PY="$(command -v python3 || command -v python)"
fi

find_omniroute() {
    if command -v omniroute >/dev/null 2>&1; then
        command -v omniroute
        return 0
    fi
    for pattern in \
        "$HOME/.nvm/versions/node/"*"/bin/omniroute" \
        "/usr/local/bin/omniroute" \
        "/usr/bin/omniroute" \
        "$HOME/.local/bin/omniroute"; do
        for cand in $pattern; do
            if [ -x "$cand" ]; then
                echo "$cand"
                return 0
            fi
        done
    done
    return 1
}

is_omniroute_running() {
    if command -v nc >/dev/null 2>&1; then
        nc -z "$OMNI_HOST" "$OMNI_PORT" >/dev/null 2>&1
        return $?
    fi

    ss -ltn 2>/dev/null | grep -q ":$OMNI_PORT "
}

start_omniroute() {
    local omni_bin
    omni_bin="$(find_omniroute)"
    if [ -z "$omni_bin" ] || [ ! -x "$omni_bin" ]; then
        echo "❌ omniroute binary not found. Please install omniroute."
        return 1
    fi

    echo
    echo "╭──────────────────────────────────────╮"
    echo "│  ⚡ OmniRoute is offline             │"
    echo "│  Starting OmniRoute server...        │"
    echo "╰──────────────────────────────────────╯"
    echo

    nohup "$omni_bin" serve >"$OMNI_LOG" 2>&1 &
    OMNI_PROCESS_PID=$!
    echo "$OMNI_PROCESS_PID" > "$OMNI_PID"

    echo "⏳ Waiting for OmniRoute on port $OMNI_PORT..."
    for _ in $(seq 1 30); do
        if is_omniroute_running; then
            echo "✅ OmniRoute is ready on port $OMNI_PORT"
            echo
            return 0
        fi
        sleep 1
    done

    echo
    echo "❌ OmniRoute failed to start."
    echo
    echo "Last log output:"
    echo "──────────────────────────────────────"
    tail -n 40 "$OMNI_LOG" 2>/dev/null || true
    echo "──────────────────────────────────────"
    echo
    return 1
}

# If user is asking for --version or --help, don't necessarily require omniroute to be running
case "${1:-}" in
    --help|-h|--version|-v)
        exec "$AIZEN_PY" "$AIZEN_APP" "$@"
        ;;
esac

# Check OmniRoute
if is_omniroute_running; then
    : # Running smoothly
else
    if ! start_omniroute; then
        echo "❌ AIZEN AI cannot start because OmniRoute is unavailable."
        exit 1
    fi
fi

# Start AIZEN AI
cd "$AIZEN_DIR" || exit 1
exec "$AIZEN_PY" "$AIZEN_APP" "$@"
