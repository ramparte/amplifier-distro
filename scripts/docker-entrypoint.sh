#!/bin/bash
# Docker entrypoint for amplifier-distro development container.
#
# Installs dependencies into the venv and uses PYTHONPATH for the
# project source (avoids egg-info permission issues on bind mounts).

set -e

STAMP="/home/testuser/.distro-venv/.installed"
PYPROJECT="/workspace/pyproject.toml"

# Install dependencies (not the project itself) into the venv
if [ ! -f "$STAMP" ] || [ "$PYPROJECT" -nt "$STAMP" ]; then
    echo "[entrypoint] Installing dependencies into venv..."
    cd /workspace
    # Install only dependencies, not the project (editable fails on bind mounts)
    uv pip install fastapi uvicorn pydantic pyyaml httpx pytest 2>&1 | tail -3
    touch "$STAMP"
    echo "[entrypoint] Done."
fi

# Source is bind-mounted at /workspace/src - add to PYTHONPATH for live imports
export PYTHONPATH="/workspace/src:${PYTHONPATH:-}"

exec "$@"
