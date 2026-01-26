#!/bin/bash

# Installation script for jfrog-transfer-automation (Unix/Linux/macOS)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Installing jfrog-transfer-automation..."

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but not found"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
REQUIRED_VERSION="3.9"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "Error: Python 3.9+ required, found Python $PYTHON_VERSION"
    exit 1
fi

# Check JFrog CLI
if ! command -v jf &> /dev/null; then
    echo "Warning: JFrog CLI (jf) not found in PATH"
    echo "Install from: https://jfrog.com/getcli/"
fi

# Install package
cd "$PROJECT_DIR"
python3 -m pip install --upgrade pip
python3 -m pip install -e .

echo ""
echo "Installation complete!"
echo ""
echo "Next steps:"
echo "1. Copy config.sample.yaml to config.yaml and configure"
echo "2. Run: jfrog-transfer-automation validate --config config.yaml"
echo "3. Run: jfrog-transfer-automation run-once --config config.yaml"
