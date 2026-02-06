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
