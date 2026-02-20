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

# ── Ensure git is available ─────────────────────────────────────
ensure_git() {
    if command -v git &>/dev/null; then
        return
    fi
    echo "[install] ERROR: git is required but not installed."
    echo "  Install git and try again: https://git-scm.com/downloads"
    exit 1
}

# ── Ensure gh CLI is available ─────────────────────────────────
ensure_gh() {
    if command -v gh &>/dev/null; then
        return
    fi
    echo "[install] ERROR: GitHub CLI (gh) is required but not installed."
    echo "  Install it and try again: https://cli.github.com"
    exit 1
}

# ── Ensure uv is available ───────────────────────────────────────
UV_INSTALLED_BY_US=false

ensure_uv() {
    if command -v uv &>/dev/null; then
        echo "[install] uv: $(uv --version)"
        return
    fi
    echo "[install] Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    UV_INSTALLED_BY_US=true
}

# ── Editable install (source checkout) ───────────────────────────
install_editable() {
    echo "[install] Source checkout detected — editable install"
    echo ""

    echo "[1/3] Installing amplifier-distro (editable)..."
    if [ ! -d ".venv" ]; then
        uv venv
    fi
    export VIRTUAL_ENV="$PWD/.venv"
    export PATH="$PWD/.venv/bin:$PATH"
    uv pip install -e ".[all,dev]"

    echo ""
    if command -v amplifier &>/dev/null; then
        echo "[2/3] Amplifier CLI already installed — skipping (use 'amplifier update' to upgrade)"
    else
        echo "[2/3] Installing Amplifier CLI..."
        uv tool install --force "git+${AMPLIFIER_URL}"
    fi

    echo ""
    if command -v amplifier-tui &>/dev/null; then
        echo "[3/3] amplifier-tui already installed — skipping (reinstall with: uv tool install --force git+${TUI_URL})"
    else
        echo "[3/3] Installing amplifier-tui..."
        uv tool install --force "git+${TUI_URL}"
    fi
}

# ── Standalone install (no source checkout) ──────────────────────
install_standalone() {
    echo "[install] Standalone install — uv tools"
    echo ""

    echo "[1/3] Installing amplifier-distro..."
    uv tool install "git+${REPO_URL}"

    echo ""
    if command -v amplifier &>/dev/null; then
        echo "[2/3] Amplifier CLI already installed — skipping (use 'amplifier update' to upgrade)"
    else
        echo "[2/3] Installing Amplifier CLI..."
        uv tool install "git+${AMPLIFIER_URL}"
    fi

    echo ""
    if command -v amplifier-tui &>/dev/null; then
        echo "[3/3] amplifier-tui already installed — skipping (reinstall with: uv tool install --force git+${TUI_URL})"
    else
        echo "[3/3] Installing amplifier-tui..."
        uv tool install "git+${TUI_URL}"
    fi
}

# ── Main ─────────────────────────────────────────────────────────
echo "=== Amplifier Distro - Install ==="
echo ""

ensure_git
ensure_gh
ensure_uv
echo ""

INSTALL_MODE=""
if [ -f "pyproject.toml" ]; then
    INSTALL_MODE="editable"
    install_editable
else
    INSTALL_MODE="standalone"
    install_standalone
fi

echo ""
echo "=== Install complete ==="
echo ""

# ── Post-install guidance (shown BEFORE commands list) ───────
if [ "$INSTALL_MODE" = "editable" ]; then
    # Always show: the script's own export of VIRTUAL_ENV doesn't
    # survive into the parent shell, so the user must activate.
    echo "IMPORTANT: Activate the virtualenv before using the commands:"
    echo ""
    echo "  source .venv/bin/activate"
    echo ""
elif [ "$INSTALL_MODE" = "standalone" ]; then
    if [ "$UV_INSTALLED_BY_US" = true ]; then
        # uv was freshly installed — its installer already modified the
        # user's shell profile. They just need to restart or source it.
        echo "NOTE: uv was installed for the first time during this setup."
        echo "Restart your shell (or open a new terminal) for PATH changes to take effect."
        echo ""
    else
        # uv was already present. PATH is almost certainly fine, but check
        # in case uv was installed via a system package manager and
        # ~/.local/bin (where uv tool install puts binaries) isn't on PATH.
        tool_bin=$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")
        if ! echo "$PATH" | tr ':' '\n' | grep -qxF "$tool_bin"; then
            echo "IMPORTANT: Add $tool_bin to your PATH:"
            echo ""
            echo "  export PATH=\"$tool_bin:\$PATH\""
            echo ""
            echo "To make it permanent, add that line to your shell config"
            echo "(~/.bashrc, ~/.zshrc, or ~/.config/fish/config.fish)."
            echo ""
        fi
    fi
fi

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
