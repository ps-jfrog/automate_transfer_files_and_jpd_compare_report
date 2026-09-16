#!/bin/bash

# Installation script for jfrog-transfer-automation using a custom Python binary
# (e.g. Python 3.13 installed via mise), without touching system python3.
#
# Default: /root/.local/share/mise/installs/python/latest/bin/python3
# Override at runtime:
#   PYTHON_BIN=/usr/local/bin/python3.13 ./scripts/install_p13.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Full path to the Python interpreter to use for installation.
# Aliases (like `p13`) do NOT work inside scripts — use the real binary path.
PYTHON_BIN="${PYTHON_BIN:-/root/.local/share/mise/installs/python/latest/bin/python3}"

echo "Installing jfrog-transfer-automation..."
echo "Using Python: $PYTHON_BIN"

# Check the Python binary exists and is executable
if [ ! -x "$PYTHON_BIN" ]; then
    echo "Error: Python binary not found or not executable: $PYTHON_BIN"
    echo "Set PYTHON_BIN to a valid Python 3.9+ interpreter and retry."
    exit 1
fi

PYTHON_VERSION=$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
REQUIRED_VERSION="3.9"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "Error: Python 3.9+ required, found Python $PYTHON_VERSION at $PYTHON_BIN"
    exit 1
fi

echo "Python version OK: $PYTHON_VERSION"

# Check JFrog CLI
if ! command -v jf &> /dev/null; then
    echo "Warning: JFrog CLI (jf) not found in PATH"
    echo "Install from: https://jfrog.com/getcli/"
fi

# Install package using the chosen Python (system python3 is untouched)
cd "$PROJECT_DIR"
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -e .

# Where the CLI ended up
PY_BIN_DIR="$(dirname "$PYTHON_BIN")"

echo ""
echo "Installation complete!"
echo ""
echo "The 'jfrog-transfer-automation' command was installed under:"
echo "  $PY_BIN_DIR"
echo ""
echo "If that directory is not on your PATH, add it:"
echo "  export PATH=\"$PY_BIN_DIR:\$PATH\""
echo ""
echo "Next steps:"
echo "1. Copy config.sample.yaml to config.yaml and configure"
echo "2. Run: jfrog-transfer-automation validate --config config.yaml"
echo "3. Run: jfrog-transfer-automation run-once --config config.yaml"
