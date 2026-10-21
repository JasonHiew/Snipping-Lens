#!/bin/bash

set -euo pipefail

# --hidden: run by the Snipping Lens.app bundle as it starts, so there is no
# terminal to write to; without it this is the first-time setup a user runs
# from Terminal, which then opens the bundle.
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

APP_BUNDLE="$HOME/Applications/Snipping Lens.app"
# the name sniplens.shortcuts looks for when it signs the bundle
SIGNING_CERTIFICATE="Snipping Lens Signing"

# macOS ties the permissions it grants to the bundle's signature. Signed
# ad-hoc, every rebuild loses them; signed with a certificate, they last. So
# the first-time setup offers to create a self-signed one, which goes into the
# user's login keychain and therefore only on a yes.
offer_signing_certificate() {
    # grep reads to the end: -q would stop early and, under pipefail, the
    # cut-off security call would read as no certificate
    if security find-identity -p codesigning 2>/dev/null | grep -F "\"$SIGNING_CERTIFICATE\"" >/dev/null; then
        return
    fi
    if [ ! -t 0 ]; then
        return
    fi
    echo
    echo "Optional: create a \"$SIGNING_CERTIFICATE\" certificate in your login keychain?"
    echo "  It lets macOS keep the Screen Recording and Input Monitoring permissions"
    echo "  when Snipping Lens is rebuilt (a Python update, or moving this folder)."
    echo "  It is self-signed, never leaves this Mac, and can be deleted in Keychain Access."
    read -r -p "Create it? [y/N] " answer
    case "$answer" in
        [yY]*) ;;
        *)
            echo "Skipped; the readme explains how to create it later."
            return
            ;;
    esac
    # the system's LibreSSL, not a Homebrew OpenSSL 3+ earlier on the PATH:
    # security cannot read the newer .p12 format those write, and reports it
    # as a wrong password
    local openssl=/usr/bin/openssl cert_dir password
    cert_dir="$(mktemp -d -t sniplens-cert)"
    password="$("$openssl" rand -hex 16)"
    cat > "$cert_dir/cert.cnf" <<EOF_CNF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = $SIGNING_CERTIFICATE
[ext]
basicConstraints = critical, CA:false
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, codeSigning
EOF_CNF
    if "$openssl" req -x509 -newkey rsa:2048 -nodes -days 3650 -config "$cert_dir/cert.cnf" \
            -keyout "$cert_dir/key.pem" -out "$cert_dir/cert.pem" 2>/dev/null \
        && "$openssl" pkcs12 -export -inkey "$cert_dir/key.pem" -in "$cert_dir/cert.pem" \
            -name "$SIGNING_CERTIFICATE" -passout "pass:$password" -out "$cert_dir/identity.p12" \
        && security import "$cert_dir/identity.p12" -k "$HOME/Library/Keychains/login.keychain-db" \
            -P "$password" -T /usr/bin/codesign; then
        echo "Created. If macOS asks whether codesign may use the key, choose Always Allow."
    else
        echo "Could not create the certificate; Snipping Lens will sign itself ad-hoc instead."
    fi
    rm -f "$cert_dir/cert.cnf" "$cert_dir/key.pem" "$cert_dir/cert.pem" "$cert_dir/identity.p12"
    rmdir "$cert_dir"
}

if [ "$HIDDEN" = false ]; then
    offer_signing_certificate
fi

# keeps the bundle, and its copy of Python, in step with this install
PYTHONPATH=src "$PYTHON" -c "from sniplens.shortcuts import ensure_app_bundle; ensure_app_bundle()"

if [ "$HIDDEN" = true ]; then
    # run by the bundle as it starts, which then goes on to run the app itself
    exit 0
fi

# First-time setup from Terminal: hand the app over to the bundle, so macOS
# asks for Screen Recording on behalf of "Snipping Lens", not Terminal.
open "$APP_BUNDLE"
echo
echo "Snipping Lens is starting in the menu bar."
echo "  - macOS will ask for Screen Recording access on your first snip. After"
echo "    allowing it, quit Snipping Lens from the menu bar and reopen it from"
echo "    ~/Applications or Spotlight."
echo "  - Global hotkeys also need Input Monitoring access (System Settings >"
echo "    Privacy & Security > Input Monitoring)."
echo "You can close this Terminal window."
