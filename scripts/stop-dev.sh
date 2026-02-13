#!/bin/bash
# Amplifier Distro - Stop Development Environment
#
# Stops and removes containers, volumes (clean slate).
# Usage: bash scripts/stop-dev.sh

set -e

echo "========================================"
echo "Amplifier Distro - Stopping Dev Environment"
echo "========================================"
echo ""

# Navigate to project root
cd "$(dirname "$0")/.."

echo "Tearing down containers and volumes..."
docker compose down -v

echo ""
echo "========================================"
echo "Environment stopped and cleaned."
echo "========================================"
echo ""
