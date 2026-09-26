#!/usr/bin/env bash
# JobHunt one-time setup (macOS 12+ and Linux).
#
# Run from the project folder:
#   chmod +x setup.sh run.sh   # first time only
#   ./setup.sh
#
# What it does:
#   1. Checks python3 3.10+
#   2. Installs Python packages (requirements.txt) — into a local .venv on
#      Linux systems whose Python forbids system-wide pip installs (PEP 668)
#   3. Ensures the bundled tectonic LaTeX engine (downloads it if missing)
#   4. Creates .env from .env.example if missing
#   5. Runs the interactive `python agent.py setup` wizard (skip with --skip-wizard)
#   6. Runs `python agent.py doctor` to prove everything works
set -euo pipefail

SKIP_WIZARD=0
for arg in "$@"; do
    case "$arg" in
        --skip-wizard) SKIP_WIZARD=1 ;;
        -h|--help)
            echo "Usage: ./setup.sh [--skip-wizard]"
            exit 0 ;;
        *) echo "Unknown option: $arg (see --help)"; exit 2 ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

OS="$(uname -s)"
case "$OS" in
    Darwin) ;;
    Linux) ;;
    *)
        echo "Unsupported OS: $OS." >&2
        echo "On Windows use setup.ps1 (or double-click setup.cmd)." >&2
        exit 2 ;;
esac

TECTONIC_VERSION="0.17.0"
TECTONIC_DIR="$REPO_ROOT/tools/tectonic"
PYBIN="python3"

fail() { echo ""; echo "SETUP FAILED: $1" >&2; exit 1; }

echo "== JobHunt setup ($OS) =="

# 1. python3 3.10+
# Note: macOS 12.3+ ships no python3 (a stub may offer Xcode tools instead).
if [ "$OS" = "Darwin" ]; then
    PY_HINT="Install it via https://www.python.org/downloads/macos/ or 'brew install python@3.12' (plus 'xcode-select --install' if pip needs a compiler), then re-run."
else
    PY_HINT="Install it via your package manager (e.g. 'sudo apt install python3 python3-pip python3-venv'), then re-run."
fi
echo -n "-- Checking python3... "
command -v python3 >/dev/null 2>&1 || fail "python3 not found. $PY_HINT"
PYV="$(python3 --version 2>&1)"
if ! python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
    fail "Found '$PYV' — need real Python 3.10+. $PY_HINT"
fi
echo "$PYV OK"

# 1b. Ensure pip exists (Debian/Ubuntu split it into python3-pip).
if ! "$PYBIN" -m pip --version >/dev/null 2>&1; then
    echo "  (no pip — trying ensurepip...)"
    "$PYBIN" -m ensurepip >/dev/null 2>&1 || true
fi
if ! "$PYBIN" -m pip --version >/dev/null 2>&1; then
    if [ "$OS" = "Linux" ] && command -v apt-get >/dev/null 2>&1; then
        echo "  (installing python3-pip + python3-venv via apt; may ask for sudo...)"
        sudo apt-get install -y python3-pip python3-venv || true
    fi
fi
"$PYBIN" -m pip --version >/dev/null 2>&1 \
    || fail "python3 has no pip and it could not be bootstrapped. $PY_HINT"

# 2. Python packages.
# On PEP 668 systems (Debian 12+/Ubuntu 23.04+) system-wide pip installs are
# refused; there we use a local .venv instead of fighting the OS.
echo "-- Installing requirements... (first run downloads ~100 MB)"
"$PYBIN" -m pip install --upgrade pip >/dev/null 2>&1 || echo "  (pip upgrade skipped)"
PIP_OUT=""
if PIP_OUT="$("$PYBIN" -m pip install -r "$REPO_ROOT/requirements.txt" 2>&1)"; then
    echo "  requirements OK"
elif echo "$PIP_OUT" | grep -qi "externally-managed"; then
    echo "  (system Python forbids pip installs — using a local .venv instead)"
    if [ ! -x "$REPO_ROOT/.venv/bin/python" ]; then
        "$PYBIN" -m venv "$REPO_ROOT/.venv" \
            || fail "Could not create .venv (try: sudo apt install python3-venv)."
    fi
    PYBIN="$REPO_ROOT/.venv/bin/python"
    "$PYBIN" -m pip install --upgrade pip >/dev/null 2>&1 || true
    "$PYBIN" -m pip install -r "$REPO_ROOT/requirements.txt" \
        || fail "pip install into .venv failed. Check your network and re-run."
    echo "  requirements OK (in .venv/ — run.sh uses it automatically)"
else
    echo "$PIP_OUT" | tail -5
    fail "pip install failed. Check your network and re-run."
fi

# 3. Tectonic (bundled; download only if missing)
echo -n "-- Checking tectonic... "
if [ -x "$TECTONIC_DIR/tectonic" ]; then
    echo "bundled copy OK"
else
    ARCH="$(uname -m)"
    if [ "$OS" = "Darwin" ]; then
        case "$ARCH" in
            arm64)  TECTONIC_TRIPLE="aarch64-apple-darwin" ;;
            x86_64) TECTONIC_TRIPLE="x86_64-apple-darwin" ;;
            *) fail "Unsupported Mac architecture: $ARCH." ;;
        esac
    else
        case "$ARCH" in
            # musl builds are fully static: they run on glibc AND musl distros.
            x86_64)  TECTONIC_TRIPLE="x86_64-unknown-linux-musl" ;;
            aarch64|arm64) TECTONIC_TRIPLE="aarch64-unknown-linux-musl" ;;
            *) fail "Unsupported Linux architecture: $ARCH. See https://github.com/tectonic-typesetting/tectonic/releases for a manual download." ;;
        esac
    fi
    echo "missing, downloading v$TECTONIC_VERSION for $TECTONIC_TRIPLE (~20 MB)..."
    TECTONIC_URL="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.17.0/tectonic-0.17.0-${TECTONIC_TRIPLE}.tar.gz"
    TMPDIR_WORK="$(mktemp -d)"
    trap 'rm -rf "$TMPDIR_WORK"' EXIT
    if ! curl -fL "$TECTONIC_URL" -o "$TMPDIR_WORK/tectonic.tar.gz"; then
        fail "tectonic download failed. Manual fix: download the $TECTONIC_TRIPLE asset from https://github.com/tectonic-typesetting/tectonic/releases and unpack the tectonic binary to tools/tectonic/."
    fi
    mkdir -p "$TECTONIC_DIR"
    tar -xzf "$TMPDIR_WORK/tectonic.tar.gz" -C "$TECTONIC_DIR"
    rm -rf "$TMPDIR_WORK"
    trap - EXIT
    [ -x "$TECTONIC_DIR/tectonic" ] || fail "tectonic binary not found after unpacking. See manual steps above."
    echo "  tectonic v$TECTONIC_VERSION installed to tools/tectonic/"
fi

# 4. .env scaffold
if [ ! -f "$REPO_ROOT/.env" ]; then
    [ -f "$REPO_ROOT/.env.example" ] || fail ".env.example missing — are you in the JobHunt project folder?"
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    echo "-- Created .env from .env.example"
else
    echo "-- .env already exists, kept as-is"
fi

# 5. Interactive key wizard (or skip)
if [ "$SKIP_WIZARD" -eq 1 ]; then
    echo "-- Skipping interactive wizard (--skip-wizard)"
else
    echo "-- Starting interactive setup (Ctrl+C keeps saved progress)..."
    "$PYBIN" agent.py setup
fi

# 6. Prove it
echo ""
echo "-- Final check:"
"$PYBIN" agent.py doctor

echo ""
echo "Done. Launch the app with:  ./run.sh"
