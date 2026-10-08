#!/usr/bin/env bash
# =============================================================================
# AIZEN AI — Install / Setup Script
# =============================================================================
# Usage:
#   bash install.sh
#   bash install.sh --check   (dry-run health check only)
#
# This script:
#   1. Verifies Python 3.10+
#   2. Creates/updates the virtual environment
#   3. Installs/upgrades Python dependencies
#   4. Locates the OmniRoute binary
#   5. Creates ~/.myai/ directory structure
#   6. Installs the 'myai' launcher symlink or alias
#   7. Runs a final health check
# =============================================================================

set -euo pipefail

AIZEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$AIZEN_DIR/.venv"
DATA_DIR="$HOME/.myai"
LAUNCHER_SRC="$AIZEN_DIR/myai.py"
LAUNCHER_DST="/usr/local/bin/myai"
REQUIREMENTS="$AIZEN_DIR/requirements.txt"

CHECK_ONLY=false
if [[ "${1:-}" == "--check" ]]; then
    CHECK_ONLY=true
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
info() { echo -e "  ${CYAN}→${NC} $1"; }

echo
echo -e "${BOLD}${CYAN}╭──────────────────────────────────────────╮${NC}"
echo -e "${BOLD}${CYAN}│  AIZEN AI — Installation / Setup         │${NC}"
echo -e "${BOLD}${CYAN}╰──────────────────────────────────────────╯${NC}"
echo

# ─── 1. Python version ───────────────────────────────────────────────────────

PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
if [[ -z "$PYTHON_BIN" ]]; then
    fail "Python 3 not found. Install Python 3.10+ and retry."
    exit 1
fi

PYTHON_VER="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_MAJOR="$(echo "$PYTHON_VER" | cut -d. -f1)"
PYTHON_MINOR="$(echo "$PYTHON_VER" | cut -d. -f2)"

if [[ "$PYTHON_MAJOR" -lt 3 || ("$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 10) ]]; then
    fail "Python $PYTHON_VER found — AIZEN requires Python 3.10+."
    exit 1
fi
pass "Python $PYTHON_VER"

if [[ "$CHECK_ONLY" == true ]]; then
    echo
    info "Check-only mode — skipping installation steps."
    # Run myai --doctor if available
    if [[ -f "$VENV_DIR/bin/python" ]]; then
        cd "$AIZEN_DIR"
        PYTHONPATH="$AIZEN_DIR" "$VENV_DIR/bin/python" myai.py --doctor 2>/dev/null || true
    fi
    exit 0
fi

# ─── 2. Virtual environment ───────────────────────────────────────────────────

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment at $VENV_DIR ..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    pass "Virtual environment created"
else
    pass "Virtual environment already exists"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# ─── 3. Install dependencies ─────────────────────────────────────────────────

if [[ -f "$REQUIREMENTS" ]]; then
    info "Installing Python dependencies..."
    "$VENV_PIP" install --upgrade pip --quiet
    "$VENV_PIP" install -r "$REQUIREMENTS" --quiet
    pass "Dependencies installed"
else
    warn "No requirements.txt found — installing core dependencies..."
    "$VENV_PIP" install --upgrade pip --quiet
    "$VENV_PIP" install \
        rich \
        prompt_toolkit \
        requests \
        faiss-cpu \
        sentence-transformers \
        pypdf \
        chardet \
        faster-whisper \
        pyttsx3 \
        sounddevice \
        --quiet 2>/dev/null || true
    pass "Core dependencies installed"
fi

# ─── 4. Locate OmniRoute ─────────────────────────────────────────────────────

OMNI_BIN="$(command -v omniroute 2>/dev/null || true)"

if [[ -z "$OMNI_BIN" ]]; then
    # Check NVM paths
    if [[ -d "$HOME/.nvm/versions/node" ]]; then
        for ver_dir in $(ls -r "$HOME/.nvm/versions/node" 2>/dev/null); do
            candidate="$HOME/.nvm/versions/node/$ver_dir/bin/omniroute"
            if [[ -f "$candidate" ]]; then
                OMNI_BIN="$candidate"
                break
            fi
        done
    fi
fi

if [[ -n "$OMNI_BIN" ]]; then
    pass "OmniRoute found: $OMNI_BIN"
else
    warn "OmniRoute not found in PATH. Install it via: npm install -g omniroute"
fi

# ─── 5. Create data directories ──────────────────────────────────────────────

mkdir -p "$DATA_DIR" "$DATA_DIR/tmp" "$DATA_DIR/kb" "$DATA_DIR/backups"
pass "Data directory: $DATA_DIR"

# ─── 6. Install launcher ─────────────────────────────────────────────────────

# Make myai.py executable
chmod +x "$LAUNCHER_SRC"

# Set correct shebang in myai.py
SHEBANG="#!$VENV_PYTHON"
CURRENT_SHEBANG="$(head -1 "$LAUNCHER_SRC")"

if [[ "$CURRENT_SHEBANG" != "$SHEBANG" ]]; then
    # Update shebang
    TMPFILE="$(mktemp)"
    echo "$SHEBANG" > "$TMPFILE"
    tail -n +2 "$LAUNCHER_SRC" >> "$TMPFILE"
    mv "$TMPFILE" "$LAUNCHER_SRC"
    chmod +x "$LAUNCHER_SRC"
    info "Updated shebang in myai.py"
fi

# Try symlink to /usr/local/bin/myai
if command -v sudo > /dev/null 2>&1 && [[ -w "/usr/local/bin" ]]; then
    ln -sf "$LAUNCHER_SRC" "$LAUNCHER_DST"
    pass "Launcher installed: /usr/local/bin/myai"
else
    # Fallback: add alias to shell rc
    SHELL_RC="$HOME/.bashrc"
    ALIAS_LINE="alias myai='PYTHONPATH=$AIZEN_DIR $VENV_PYTHON $LAUNCHER_SRC'"
    if ! grep -q "alias myai=" "$SHELL_RC" 2>/dev/null; then
        echo "" >> "$SHELL_RC"
        echo "# AIZEN AI launcher" >> "$SHELL_RC"
        echo "$ALIAS_LINE" >> "$SHELL_RC"
        pass "Alias added to $SHELL_RC — run: source ~/.bashrc"
    else
        pass "Alias already in $SHELL_RC"
    fi
fi

# Also update start-myai.sh with correct paths
sed -i "s|AIZEN_PY=.*|AIZEN_PY=\"$VENV_PYTHON\"|" "$AIZEN_DIR/start-myai.sh" 2>/dev/null || true
sed -i "s|AIZEN_DIR=.*|AIZEN_DIR=\"$AIZEN_DIR\"|" "$AIZEN_DIR/start-myai.sh" 2>/dev/null || true

# ─── 7. Health check ─────────────────────────────────────────────────────────

echo
echo -e "${BOLD}Final health check:${NC}"

cd "$AIZEN_DIR"
PYTHONPATH="$AIZEN_DIR" "$VENV_PYTHON" myai.py --doctor 2>/dev/null || true

echo
echo -e "${GREEN}${BOLD}✓ AIZEN AI setup complete.${NC}"
echo
echo "To start AIZEN AI:"
echo "  myai"
echo "  — or —"
echo "  bash $AIZEN_DIR/start-myai.sh"
echo
echo "First time? Run:"
echo "  myai --doctor     (system health check)"
echo "  myai --version    (version info)"
echo
