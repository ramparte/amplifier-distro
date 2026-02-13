#!/bin/bash
# Amplifier Distro - Development Environment Startup Script
#
# This script builds and starts the Docker development environment.
# Usage: bash scripts/start-dev.sh

set -e

echo "========================================"
echo "Amplifier Distro - Starting Dev Environment"
echo "========================================"
echo ""

# Navigate to project root (script is in scripts/ subdirectory)
cd "$(dirname "$0")/.."

echo "[1/4] Stopping any existing containers..."
docker compose down 2>/dev/null || true

echo ""
echo "[2/4] Building Docker images..."
docker compose --profile all build

echo ""
echo "[3/4] Starting all containers (CLI, TUI, GUI, Voice)..."
docker compose --profile all up -d

echo ""
echo "[4/5] Waiting for installation to complete..."
sleep 10  # Give entrypoint time to install packages

echo ""
echo "[5/5] Launching TUI..."
echo ""
echo "========================================"
echo "Starting Amplifier TUI interface..."
echo "========================================"
echo ""

# Launch the TUI (this will take over the terminal)
docker compose exec tui amplifier-tui

# After TUI exits, show info
echo ""
echo "========================================"
echo "TUI closed. Services are still running."
echo ""
echo "To restart TUI:"
echo "  docker compose exec tui amplifier-tui"
echo ""
echo "To enter CLI:"
echo "  docker compose exec cli bash"
echo ""
echo "To stop all services:"
echo "  docker compose down -v"
echo "========================================"
echo ""
