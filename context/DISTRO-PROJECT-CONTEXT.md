# Amplifier Distro: Project Context

This file exists so any future Amplifier session can pick up this
project where the last one left off. Read this first.

---

## What This Project Is

We're building an **Amplifier Distribution** - in the Linux sense.
A set of opinionated tools, conventions, and defaults that make
Amplifier "just work" for a team of AI-assisted developers.

The guiding principle: **minimize human attentional load.** Every
design decision optimizes for humans spending zero attention on
plumbing, configuration, or debugging their tools. Models get
smarter, inference gets cheaper, but humans have a fixed amount
of attention per day.

The motto: **"A choice is better than many, even if you don't agree."**

---

## The Team

| Person | GitHub | Role / Focus |
|--------|--------|-------------|
| Sam Schillace | samschillace (ramparte) | Lead. TUI, CarPlay, attention firewall, overall vision |
| Brian Krabach | bkrabach (robotdad) | Voice pipeline, VR+tmux setup, attention firewall |
| Michael Jabbour | michaeljabbour | GUI interface |
| Mark Licata | marklicata | Nexus product vision, amplifier-app-api backend |

Sam's workspace: `~/dev/ANext/`
This repo: `~/dev/ANext/amplifier-distro/`

---

## Key Repositories

| Repo | What | Relevance |
|------|------|-----------|
| `ramparte/amplifier-distro` | **This repo.** The distro itself. | Primary work location |
| `ramparte/amplifier-planning` | Brainstorming repo (Jan 22 Level 4 vision + environment research) | Historical context, also has copies of planning/ |
| `microsoft/amplifier-core` | Kernel - sessions, modules, events | Engine (don't modify unless necessary) |
| `microsoft/amplifier-foundation` | Bundles, utilities, agents | PRs for adapter, validation, handoffs go here |
| `microsoft/amplifier-app-cli` | Reference CLI | PRs for `amp distro` commands may go here |
| `samschillace/amplifier-tui` | TUI interface (Textual) | Needs rewrite on Interface Adapter |
| `bkrabach/amplifier-voice` | Voice interface | Needs config extraction |
| `marklicata/amplifier-nexus` | Product vision docs (850KB planning, zero code) | Context only - we build distro first, Nexus layers on top |
| `marklicata/amplifier-app-api` | FastAPI backend for web/mobile | Future Ring 3, not distro core |

---

## Architecture: Three Rings

```
Ring 3: Workflows + Products
  [Attention Firewall] [Team Tracking] [Morning Brief]
  [Idea Funnel] [Friction Detection]
  [Nexus Product Layer (optional): Web, Mobile, Desktop]

Ring 2: Interfaces (any viewport, same session)
  [CLI] [TUI] [Voice] [CarPlay] [GUI] [Custom]

Ring 1: Foundation (set once, works forever)
  [Interface Adapter] [Bundle Validation] [Pre-flight]
  [Session Handoffs] [Memory] [Health Checks]
  [distro.yaml] [Distro Base Bundle]
  [Standard Workspace: ~/dev/]

Engine: amplifier-core + amplifier-foundation
  [Sessions] [Agents] [Providers] [Tools] [Hooks]
```

Ring 1 = set up once, never think about again.
Ring 2 = pick your viewport(s), they all share state.
Ring 3 = workflows that work FOR you.

---

## Key Design Decisions (Settled)

1. **distro.yaml** is the central config file. Lives at
   `~/.amplifier/distro.yaml`. Every tool reads it. Contains:
   workspace_root, identity, bundle config, cache config, interface
   registry.

2. **Interfaces are viewports**, not isolated apps. They share
   sessions, memory, and config through the filesystem. They do
   NOT import from each other. They use the Interface Adapter.

3. **The Interface Adapter** is a library in amplifier-foundation,
   not a backend service. create_session(), cleanup(), config reader.
   A backend service (for web/mobile) is Ring 3, optional.

4. **Bundle validation is strict by default.** Missing includes are
   errors, not warnings. Pre-flight runs on every session start.

5. **Memory is at ~/.amplifier/memory/.** One location, YAML format,
   shared across all interfaces.

6. **GitHub handle is identity.** Detected from `gh auth status`.

7. **One-click setup target:** `amp distro init` creates everything.
   Setup website provides machine-readable instructions for agent-
   driven setup.

8. **Build order:** distro.yaml schema -> base bundle -> validation ->
   pre-flight -> handoffs -> adapter -> interface fixes -> setup tool
   -> workflows.

---

## Key Design Decisions (Open / Needs Discussion)

1. **Where does `amp distro` live?** Options: CLI subcommand in
   amplifier-app-cli, standalone tool, recipe-based.

2. **Does the Interface Adapter need core changes?** Ideally not.
   Design to work with current session API. If SESSION_END event
   is needed for handoffs, that's a small core PR.

3. **How do we handle the memory migration?** Brian's memory is at
   `~/amplifier-dev-memory/`, Sam's at the same place. Moving to
   `~/.amplifier/memory/` needs a migration path.

4. **Voice + TUI interface adapter scope.** Full rewrite, or shim
   first? TUI has a sys.path hack. Voice has hardcoded values.
   Pragmatic answer: shim first (read distro.yaml, use existing
   session creation), full adapter later.

5. **Idea funnel design.** Nothing exists yet. Needs: capture source,
   scoring model, surfacing mechanism. Could be a recipe + agent, or
   a dedicated tool module.

---

## Documents in This Repo

### /planning/ (Research and Analysis)

| File | Contents |
|------|----------|
| `00-research-index.md` | Navigation and overview of all research |
| `01-friction-analysis.md` | 45% of Amplifier time is friction (91 sessions analyzed) |
| `02-current-landscape.md` | Full inventory of tools, interfaces, configs |
| `03-architecture-vision.md` | Three-ring model design |
| `04-pieces-and-priorities.md` | Component maturity ranking |
| `05-self-improving-loop.md` | Meta-system for continuous improvement |
| `06-anthropic-patterns.md` | Lessons from parallel-Claude compiler project |
| `07-ring1-deep-dive.md` | Foundation gaps, path to hands-off (~4 weeks) |
| `08-ring2-deep-dive.md` | Interface gaps, path to hands-off (~5-6 weeks) |
| `09-setup-tool.md` | Setup tool UX specification |
| `10-project-structure.md` | How to execute this project |
| `11-task-list.md` | 25 tasks across 6 tiers with dependencies |
| `12-nexus-synthesis.md` | amplifier-nexus analysis: distro vs product, reconciliation |
| `research-anthropic-compiler.md` | Raw article from Anthropic (reference) |

### / (Root)

| File | Contents |
|------|----------|
| `OPINIONS.md` | The 10 shared conventions every distro tool agrees to |
| `ROADMAP.md` | Firm roadmap: phases 0-4, existing pieces, gaps, success metrics |

---

## Current Status

**Phase:** Pre-Phase-0. Research and design complete. Ready to
start building.

**What's done:**
- Research: 14 planning documents covering friction, architecture,
  gaps, task lists, and Nexus analysis
- Design: OPINIONS.md (shared conventions), ROADMAP.md (firm plan)
- Repos: amplifier-distro created and structured

**What's next (Phase 0, ~1 week):**
1. Define distro.yaml JSON schema
2. Create the distro base bundle (compose existing behaviors)
3. PR to amplifier-foundation: bundle validation strict mode
4. PR to amplifier-foundation: basic pre-flight checks
5. Get one team member (Sam) running on strict validation

**What's after that (Phase 1, ~1 week):**
1. Session handoff hook (auto-summary at session end)
2. Handoff injection on session start
3. Memory location standardization

---

## How to Continue This Work

1. **Read this file first.** It has the full picture.
2. **Read OPINIONS.md** for the shared conventions.
3. **Read ROADMAP.md** for the build plan with phases and tasks.
4. **For deeper research**, read files in planning/ as needed.
5. **For Nexus context**, see planning/12-nexus-synthesis.md.

To pick up a specific task:
- Check ROADMAP.md Phase 0 tasks
- Each task has clear scope and exit criteria
- Work in the relevant repo (PRs to foundation, core, or this repo)
- Update this context file when decisions change

---

## Related Prior Work

### Level 4 Self-Improving Vision (Jan 22, 2026)
In `ramparte/amplifier-planning` (root, not environment/), there's
earlier brainstorming about a self-improving system. The distro IS
the realization of that vision:
- Level 4's "shared memory" = Ring 1's session handoffs + memory
- Level 4's "monitoring" = Ring 1's health checks + friction detection
- Level 4's "visibility dashboard" = Ring 2's interfaces
- Level 4's "self-improving loop" = Ring 3's friction -> fix -> measure

### Nexus Product Vision
In `marklicata/amplifier-nexus`, there's an 850KB product vision
for a multi-interface platform targeting knowledge workers. The
distro is the foundation layer that Nexus would build on. See
planning/12-nexus-synthesis.md for full analysis.

Key takeaway: Nexus is a valid product layer on Ring 3. It needs
the distro (Rings 1-2) to exist first. No conflict, just sequencing.

---

## Implementation Design (Added Feb 6, Session 2)

The full implementation design is in `IMPLEMENTATION.md` at repo root.
It covers:

### Interface Inventory (Concrete Details)

| Interface | Stack | Session Creation | Distro Fix |
|-----------|-------|-----------------|------------|
| **CLI** | Python/Click/Rich | `resolve_config()` golden path | Produces artifacts CLI consumes |
| **TUI** | Python/Textual | sys.path hack into CLI internals | Proper pip dependency + distro.yaml reader |
| **Web** | FastAPI + React/TS | Direct amplifier-core/foundation | Already does it right; add distro.yaml defaults |
| **Desktop** | Unknown (private repo) | Unknown | TBD |
| **Voice** | Python/OpenAI Realtime | Hardcoded values | Config extraction + distro.yaml |

### Machine Independence

- Backup: private GitHub repo (`<gh_handle>/amplifier-backup`)
- Backed up: distro.yaml, memory/, settings.yaml, bundle-registry.yaml
- NOT backed up: keys.env (security), cache (rebuilds), projects (team tracking handles)
- Restore: clone backup, apply config, prompt for keys, run init --restore
- Container: Dockerfile + devcontainer.json, `amp-distro init --non-interactive`
- Does NOT require Docker for basic setup

### Update Model

- `amp-distro update`: CLI + cache + base bundle + interfaces + pre-flight + rollback
- Auto-cache-refresh on stale (TTL-based, during pre-flight)
- Auto-retry on load failure (clear cache entry, re-clone, retry once)
- Version pinning opt-in via distro.yaml
- Rollback: snapshot before update, restore if pre-flight fails after

### The `amp-distro` Tool

Standalone CLI tool in this repo. NOT a plugin to amplifier-app-cli.
Commands: init, status, update, install, backup, restore, doctor, version.

### Open Design Questions (Decided)

- Q1 TUI dependency: use amplifier-app-cli as pip dependency (quick fix)
- Q3 Memory location: keep ~/amplifier-dev-memory/ as-is, record in distro.yaml
- Q4 Voice: lower priority installer, Phase 2+ 
- Q5 Team update coordination: float on @main for now, pin opt-in

### Open Design Questions (Still Open)

- Q2: Should `amp-distro` also be aliased as `amp distro`? (cosmetic)
