#!/bin/bash
# Automatically start TUI when codespace opens

set -e

echo "========================================"
echo "Amplifier Distro - Auto-starting TUI"
echo "========================================"
echo ""

# Give user a moment to read
sleep 2

# Build and start all services, then launch TUI
bash scripts/start-dev.sh

# If user exits TUI, show helpful message
echo ""
echo "To restart TUI: bash scripts/start-dev.sh"
echo "To stop services: bash scripts/stop-dev.sh"
