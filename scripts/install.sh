#!/bin/bash
# Amplifier Distro - Install Script
#
# Single script used by all install paths:
#
#   Codespaces / devcontainer:
#     postCreateCommand: bash scripts/install.sh
#
#   Dockerfile:
#     RUN bash scripts/install.sh
#
#   curl | bash (standalone):
#     curl -fsSL https://raw.githubusercontent.com/ramparte/amplifier-distro/main/scripts/install.sh | bash
#
#   Local developer:
#     git clone ... && cd amplifier-distro && bash scripts/install.sh
#
# Behavior:
#   - If pyproject.toml exists in cwd → editable install (developer / devcontainer)
#   - Otherwise → clone repo and install as uv tools (standalone)

set -e

REPO_URL="https://github.com/ramparte/amplifier-distro"
AMPLIFIER_URL="https://github.com/microsoft/amplifier"
TUI_URL="https://github.com/ramparte/amplifier-tui"

# ── Ensure uv is available ───────────────────────────────────────
ensure_uv() {
    if command -v uv &>/dev/null; then
        echo "[install] uv: $(uv --version)"
        return
    fi
    echo "[install] Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
}

# ── Editable install (source checkout) ───────────────────────────
install_editable() {
    echo "[install] Source checkout detected — editable install"
    echo ""

    echo "[1/3] Installing amplifier-distro (editable)..."
    uv venv
    export VIRTUAL_ENV="$PWD/.venv"
    export PATH="$PWD/.venv/bin:$PATH"
    uv pip install -e ".[all,dev]"

    echo ""
    echo "[2/3] Installing Amplifier CLI..."
    uv tool install --force "git+${AMPLIFIER_URL}"

    echo ""
    echo "[3/3] Installing amplifier-tui..."
    uv tool install --force "git+${TUI_URL}"
}

# ── Standalone install (no source checkout) ──────────────────────
install_standalone() {
    echo "[install] Standalone install — uv tools"
    echo ""

    echo "[1/3] Installing amplifier-distro..."
    uv tool install "git+${REPO_URL}"

    echo ""
    echo "[2/3] Installing Amplifier CLI..."
    uv tool install "git+${AMPLIFIER_URL}"

    echo ""
    echo "[3/3] Installing amplifier-tui..."
    uv tool install "git+${TUI_URL}"
}

# ── Main ─────────────────────────────────────────────────────────
echo "=== Amplifier Distro - Install ==="
echo ""

ensure_uv
echo ""

if [ -f "pyproject.toml" ]; then
    install_editable
else
    install_standalone
fi

echo ""
echo "=== Install complete ==="
echo ""
echo "Commands available:"
echo "  amp-distro          Distro management CLI"
echo "  amp-distro-server   Web server (localhost:8400)"
echo "  amplifier           Amplifier CLI agent"
echo "  amplifier-tui       Terminal UI"
echo ""
echo "Quick start:"
echo "  amp-distro init       # first-time setup"
echo "  amp-distro-server     # start web UI"
echo ""
