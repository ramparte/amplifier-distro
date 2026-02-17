# amplifier-distro

An opinionated distribution for AI-assisted development with Amplifier.

## What This Is

A set of shared conventions, tools, and defaults that make Amplifier
"just work" for a team. One config file, one setup command, consistent
behavior across CLI, TUI, Voice, and any other interface.

**Guiding principle:** Minimize human attentional load. Every choice
here exists so you don't have to make it.

## Documents

| File | Read This To... |
|------|-----------------|
| [OPINIONS.md](OPINIONS.md) | Understand the 10 shared conventions |
| [ROADMAP.md](ROADMAP.md) | See the build plan with phases and tasks |
| [context/DISTRO-PROJECT-CONTEXT.md](context/DISTRO-PROJECT-CONTEXT.md) | Resume work on this project from any session |
| [planning/](planning/) | Deep research: friction analysis, architecture, gaps, task lists |

## Install


### General installation (for most users just wanting to try things out)

```bash
curl -fsSL https://raw.githubusercontent.com/ramparte/amplifier-distro/main/scripts/install.sh | bash
amp-distro init
```

### Developer

```bash
git clone https://github.com/ramparte/amplifier-distro && cd amplifier-distro
bash scripts/install.sh
source .venv/bin/activate
```

### GitHub Codespace

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://github.com/codespaces/new?repo=ramparte/amplifier-distro)

Opens a browser-based environment with everything installed.

### Docker (for isolated testing)

```bash
docker build -t amplifier-distro .
docker run -p 8400:8400 amplifier-distro # runs the web server
```

## Usage

The install gives you four commands:

### `amp-distro` — Distro management CLI

Set up your environment, check health, and manage the Amplifier ecosystem.

```bash
amp-distro init          # First-time setup: identity, workspace, config
amp-distro status        # Check that everything is healthy
amp-distro doctor --fix  # Diagnose and auto-repair common problems
amp-distro backup        # Back up state to a private GitHub repo
amp-distro restore       # Restore state from backup
amp-distro update        # Self-update to the latest release
```

### `amp-distro-server` — Web UI and API

```bash
amp-distro-server              # Start on http://localhost:8400
amp-distro-server --dev        # Dev mode (mock sessions, no LLM needed)
amp-distro-server start        # Run as a background daemon
amp-distro-server stop         # Stop the daemon
```

The server hosts the web chat, settings, Slack bridge simulator, voice interface, and routines scheduler. Visit the app at http://localhost:8400/.

### `amplifier` — AI coding agent

```bash
amplifier                      # Start an interactive session
amplifier "fix the login bug"  # Start with a prompt
amplifier continue             # Resume the most recent session
```

### `amplifier-tui` — Terminal UI

```bash
amplifier-tui                  # Full-screen terminal interface
amplifier-tui --web            # Launch web interface instead
amplifier-tui --doctor         # Check environment health
```

## Quick Orientation

```
Ring 3: Workflows (attention firewall, morning brief, idea funnel)
Ring 2: Interfaces (CLI, TUI, Voice - all share state)
Ring 1: Foundation (distro.yaml, pre-flight, session handoffs, memory)
Engine: amplifier-core + amplifier-foundation
```

We're building Rings 1-2. Ring 3 comes after. The engine already exists.
