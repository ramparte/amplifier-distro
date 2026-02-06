# Amplifier Universal Environment: Research Index

Research conducted Feb 6, 2026, for brainstorming a "universal distribution" that
minimizes human attentional load across the Amplifier ecosystem.

## Research Files

| File | Contents |
|------|----------|
| `00-research-index.md` | This file - navigation and overview |
| `01-friction-analysis.md` | What's eating attention today (session data) |
| `02-current-landscape.md` | What exists: interfaces, tools, configs |
| `03-architecture-vision.md` | How this could be structured |
| `04-pieces-and-priorities.md` | Components, maturity, and priority ranking |
| `05-self-improving-loop.md` | The meta-system for continuous improvement |
| `06-anthropic-patterns.md` | Lessons from the parallel-Claude compiler project |
| `07-ring1-deep-dive.md` | Technical gaps in foundation layer, path to hands-off |
| `08-ring2-deep-dive.md` | Technical gaps in interfaces, path to hands-off |
| `09-setup-tool.md` | Setup tool / installer specification and UX |
| `10-project-structure.md` | How to structure and execute this project |
| `11-task-list.md` | Ordered task list with dependencies (start/stop friendly) |
| `12-nexus-synthesis.md` | Analysis of amplifier-nexus: distro vs product, conflicts, reconciliation |
| `research-anthropic-compiler.md` | Raw article text (saved from web) |

## The Core Thesis

Human attention is the scarcest resource. Models get smarter, inference gets
cheaper, but a person still has ~4 hours of deep focus per day. Every minute
spent on plumbing, re-explaining context, debugging bundles, or repairing
sessions is a minute stolen from actual creative work.

The goal: an environment that absorbs operational complexity so humans can
direct attention exclusively toward judgment, creativity, and decisions
that only humans can make.

## Key Numbers from Research

- ~45% of recent Amplifier time spent on friction, not actual work
- 6 major friction categories identified from 91 sessions
- 6 alternative interfaces exist (CLI, TUI, Voice, Web, Web-Unified, CarPlay)
- 7+ bundles composed into my-amplifier, with recurring syntax failures
- 534 notifications triaged by attention firewall (2 weeks)
- 16 conversational threads tracked across WhatsApp groups
- The team: 17 GitHub accounts across 3 sub-teams

## Guiding Principle

"Simple, transparent, and extensible" - but when forced to choose:
1. Simple wins over extensible (reduce attentional load)
2. Transparent wins over clever (humans must understand what happened)
3. Working wins over configurable (defaults > options)
