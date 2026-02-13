# amplifier-distro

An opinionated distribution for AI-assisted development with Amplifier.

## 🚀 Quick Start - One-Click Install

### GitHub Codespaces (Fastest - No local install)

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://github.com/codespaces/new?repo=ramparte/amplifier-distro)

Click the badge above → TUI opens automatically in your browser!

### Command Line Install

**Linux / macOS / WSL:**
```bash
curl -fsSL https://raw.githubusercontent.com/ramparte/amplifier-distro/main/install.sh | bash
```

**Windows:**
```powershell
# Download and run: scripts\start-dev.bat
# Or use PowerShell:
iwr -useb https://raw.githubusercontent.com/ramparte/amplifier-distro/main/install-windows.ps1 | iex
```

See [ONE-CLICK-INSTALL.md](ONE-CLICK-INSTALL.md) for more options and troubleshooting.

---

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

## Quick Orientation

```
Ring 3: Workflows (attention firewall, morning brief, idea funnel)
Ring 2: Interfaces (CLI, TUI, Voice - all share state)
Ring 1: Foundation (distro.yaml, pre-flight, session handoffs, memory)
Engine: amplifier-core + amplifier-foundation
```

We're building Rings 1-2. Ring 3 comes after. The engine already exists.

## Status

Pre-Phase-0. Research and design complete. Ready to build.
