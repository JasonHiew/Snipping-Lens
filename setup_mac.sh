#!/bin/bash

set -euo pipefail

# --hidden: launched by the Snipping Lens.app bundle (or the login item), so
# there is no terminal to write to; without it this is the first-time setup a
# user runs from Terminal.
HIDDEN=false
if [[ "${1:-}" == "--hidden" ]]; then
    HIDDEN=true
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ "$HIDDEN" = true ]; then
    mkdir -p "bin/mac/logs"
    exec >> "bin/mac/logs/setup.log" 2>&1
fi

# portable CPython from astral-sh/python-build-standalone; MsPy has no macOS build
PYTHON_RELEASE="20261003"
PYTHON_VERSION="3.11.17"
case "$(uname -m)" in
    arm64)
        PYTHON_ARCH="aarch64"
        PYTHON_SHA256="3663b71c18364eccfbad74c4f21f9f6149e40b07329cd776287410cc1da5d612"
        ;;
    x86_64)
        PYTHON_ARCH="x86_64"
        PYTHON_SHA256="4338dc0c2b954f20ca6437406db5b806626c69bae3cafeec43f1b7d57dd72a88"
        ;;
    *)
        echo "Error: unsupported CPU architecture $(uname -m)"
        exit 1
        ;;
esac
PYTHON_TARBALL="cpython-${PYTHON_VERSION}+${PYTHON_RELEASE}-${PYTHON_ARCH}-apple-darwin-install_only.tar.gz"
PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_RELEASE}/${PYTHON_TARBALL}"
PYTHON_DIR="int/mac/python-${PYTHON_VERSION}"
PYTHON_BINARY="$PYTHON_DIR/bin/python3.11"
VENV_DIR="int/mac/venv"

if [ ! -x "$PYTHON_BINARY" ]; then
    echo "Python ${PYTHON_VERSION} not found. Downloading..."
    rm -rf "$PYTHON_DIR"
    mkdir -p "$PYTHON_DIR"
    DOWNLOAD="$(mktemp -t sniplens-python)"
    curl -fL -o "$DOWNLOAD" "$PYTHON_URL"
    if [ "$(shasum -a 256 "$DOWNLOAD" | awk '{print $1}')" != "$PYTHON_SHA256" ]; then
        rm -f "$DOWNLOAD"
        echo "Error: the Python download failed its checksum, please run the setup again."
        exit 1
    fi
    # the archive's top-level folder is "python/"
    tar -xzf "$DOWNLOAD" -C "$PYTHON_DIR" --strip-components 1
    rm -f "$DOWNLOAD"
    if [ ! -x "$PYTHON_BINARY" ]; then
        echo "Error: Binary not found at $PYTHON_BINARY after extraction"
        exit 1
    fi
    echo "Python ${PYTHON_VERSION} successfully downloaded and extracted"
fi

VENV_NEEDS_RECREATION=false
EXPECTED_PYTHON_HOME=$(cd "$(dirname "$PYTHON_BINARY")" && pwd)
if [ ! -f "$VENV_DIR/bin/python" ]; then
    VENV_NEEDS_RECREATION=true
elif ! grep -q "home = $EXPECTED_PYTHON_HOME" "$VENV_DIR/pyvenv.cfg" 2>/dev/null; then
    echo "Virtual environment points to the wrong Python location, recreating..."
    VENV_NEEDS_RECREATION=true
fi

if [ "$VENV_NEEDS_RECREATION" = true ]; then
    echo "Creating new virtual environment..."
    rm -rf "$VENV_DIR"
    "$PYTHON_BINARY" -m venv "$VENV_DIR"
fi

PYTHON="$VENV_DIR/bin/python"
REQUIREMENTS_HASH_FILE="$VENV_DIR/.requirements.sha256"
REQ_HASH="$(shasum -a 256 src/requirements.txt | awk '{print $1}')-$(shasum -a 256 src/requirements-mac.txt | awk '{print $1}')"
OLD_REQ_HASH="$(cat "$REQUIREMENTS_HASH_FILE" 2>/dev/null || true)"

if [ "$VENV_NEEDS_RECREATION" = true ] || [ "$REQ_HASH" != "$OLD_REQ_HASH" ]; then
    echo "Installing/updating dependencies..."
    "$PYTHON" -m pip install --upgrade pip
    "$PYTHON" -m pip install -r src/requirements.txt -r src/requirements-mac.txt
    echo "$REQ_HASH" > "$REQUIREMENTS_HASH_FILE"
else
    echo "Dependencies are up to date (skipping pip install)"
fi

if [ "$HIDDEN" = true ]; then
    exec "$PYTHON" src/main.py
fi

# First-time setup from Terminal: hand the app over to the launcher bundle, so
# macOS asks for Screen Recording on behalf of "Snipping Lens", not Terminal.
PYTHONPATH=src "$PYTHON" -c "from sniplens.shortcuts import ensure_app_bundle; ensure_app_bundle()"
open "$HOME/Applications/Snipping Lens.app"
echo
echo "Snipping Lens is starting in the menu bar."
echo "  - macOS will ask for Screen Recording access on your first snip. After"
echo "    allowing it, quit Snipping Lens from the menu bar and reopen it from"
echo "    ~/Applications or Spotlight."
echo "  - Global hotkeys also need Accessibility access (System Settings >"
echo "    Privacy & Security > Accessibility)."
echo "You can close this Terminal window."
