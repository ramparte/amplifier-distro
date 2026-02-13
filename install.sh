#!/bin/bash
# Amplifier Distro - One-Click Installer
#
# Quick install from URL:
#   curl -fsSL https://raw.githubusercontent.com/ramparte/amplifier-distro/main/install.sh | bash
#
# Or with wget:
#   wget -qO- https://raw.githubusercontent.com/ramparte/amplifier-distro/main/install.sh | bash

set -e

echo "========================================"
echo "Amplifier Distro - One-Click Installer"
echo "========================================"
echo ""

# Detect OS
OS="$(uname -s)"
case "${OS}" in
    Linux*)     MACHINE=Linux;;
    Darwin*)    MACHINE=Mac;;
    MINGW*|MSYS*|CYGWIN*)
        echo "ERROR: This installer is for Linux/Mac."
        echo "Windows users: Clone the repo and run scripts\\start-dev.bat"
        exit 1
        ;;
    *)
        echo "ERROR: Unsupported OS: ${OS}"
        exit 1
        ;;
esac

echo "Detected OS: ${MACHINE}"
echo ""

# Check prerequisites
echo "[1/6] Checking prerequisites..."

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed."
    echo "Install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check Docker Compose
if ! docker compose version &> /dev/null; then
    echo "ERROR: Docker Compose is not installed."
    echo "Install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

# Check Docker is running
if ! docker info &> /dev/null; then
    echo "ERROR: Docker is not running."
    echo "Start Docker and try again."
    exit 1
fi

echo "✓ Docker and Docker Compose are installed and running"
echo ""

# Determine install location
INSTALL_DIR="${AMPLIFIER_INSTALL_DIR:-$HOME/amplifier-distro}"

echo "[2/6] Installing to: ${INSTALL_DIR}"
echo ""

# Clone or download the repository
if [ -d "${INSTALL_DIR}" ]; then
    echo "Directory ${INSTALL_DIR} already exists."
    read -p "Delete and reinstall? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "${INSTALL_DIR}"
    else
        echo "Installation cancelled."
        exit 1
    fi
fi

# Check if git is available
if command -v git &> /dev/null; then
    echo "Cloning repository..."
    git clone https://github.com/ramparte/amplifier-distro.git "${INSTALL_DIR}"
else
    echo "Git not found. Downloading as archive..."
    TEMP_ZIP="${INSTALL_DIR}.zip"
    curl -fsSL https://github.com/ramparte/amplifier-distro/archive/refs/heads/main.zip -o "${TEMP_ZIP}"
    unzip -q "${TEMP_ZIP}" -d "$(dirname ${INSTALL_DIR})"
    mv "$(dirname ${INSTALL_DIR})/amplifier-distro-main" "${INSTALL_DIR}"
    rm "${TEMP_ZIP}"
fi

cd "${INSTALL_DIR}"
echo "✓ Repository downloaded"
echo ""

# Make scripts executable
echo "[3/6] Setting up scripts..."
chmod +x scripts/*.sh
echo "✓ Scripts ready"
echo ""

# Optional: Configure environment
echo "[4/6] Configuration"
if [ -f .env.local ]; then
    echo "✓ Found existing .env.local"
else
    echo "No .env.local found. You can create one later for API keys."
    echo "Example: echo 'ANTHROPIC_API_KEY=sk-ant-your-key' >> .env.local"
fi
echo ""

# Build and start
echo "[5/6] Building and starting containers..."
echo "This may take a few minutes on first run..."
echo ""

bash scripts/start-dev.sh

# The start-dev.sh script will automatically launch the TUI
# and this script will exit when the user exits the TUI

echo ""
echo "========================================"
echo "Installation complete!"
echo ""
echo "Amplifier Distro is installed at:"
echo "  ${INSTALL_DIR}"
echo ""
echo "To start again:"
echo "  cd ${INSTALL_DIR}"
echo "  bash scripts/start-dev.sh"
echo ""
echo "To stop:"
echo "  bash scripts/stop-dev.sh"
echo "========================================"
