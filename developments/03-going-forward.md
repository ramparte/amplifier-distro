# Amplifier Distro: Going Forward

> Design document for restructuring amplifier-distro from a monolithic server
> application into ecosystem-native Amplifier artifacts. Converged through
> 24-turn deep analysis session (9c72e8a7, Feb 20 2026). All decisions
> confirmed by project owner.

---

## Executive Summary

The distro project's **value is its opinions and policies**, not its
infrastructure. The infrastructure it reimplements -- session creation, bundle
loading, config management, cache, CLI -- already exists in amplifier-foundation
and amplifier-app-cli. The path forward replaces the monolithic FastAPI server
with three focused deliverables:

| Deliverable | What | Ships As |
|-------------|------|----------|
| **A. The Distro Bundle** | The 11 opinions, policies, agents, and workflows expressed as composable Amplifier-native artifacts | `amplifier-bundle-distro` repo |
| **B. Ecosystem PRs** | Targeted improvements to foundation + CLI that make the platform better for everyone | PRs to amplifier-foundation and amplifier-app-cli |
| **C. Standalone Experiences** | Slack bridge, voice bridge, web chat -- extracted from the server plugin framework into independently runnable services | Restructured in this repo |

---

## Context: Why We're Here

### The Problem (data-driven)

Analysis of 91 sessions (Jan 23 - Feb 6, 2026) found ~45% of Amplifier time
spent on friction rather than work. Six friction categories were identified
and ranked. Full analysis in `responses/distro-one-pager.md`.

### What Was Built

An overnight autonomous build (Feb 9) produced a FastAPI server application
with CLI, plugin system, Slack bridge, voice bridge, web chat, backup/restore,
doctor diagnostics, and 836 tests. Subsequent team PRs hardened Slack, added
web chat features, and fixed concurrency issues. The current codebase is
substantial and working.

### What Drifted

The original plan (`planning/10-project-structure.md`) described a thin bundle
with behaviors, agents, context, and recipes -- the same shape as any proper
Amplifier bundle. The overnight build pivoted to a server-centric model that
reimplements capabilities the ecosystem already provides. Full drift analysis
in `responses/bundle-drift.md`.

### The Insight

Mapping the six objectives to what would actually deliver them reveals that
**five of six don't require a new application** -- they require making
foundation and the CLI better, plus a policy layer expressed as a standard
bundle. Only the standalone experiences (Slack/voice/web chat) justify
application code, and they don't need a shared server framework.

---

## Part A: The Distro Bundle

### What It Is

A proper Amplifier bundle directory -- the same shape as `amplifier-foundation`,
`my-amplifier`, or `amplifier-bundle-recipes`. It carries the 11 opinions and
6 objectives as composable, Amplifier-native artifacts that work inside
sessions.

### Directory Structure

```
amplifier-bundle-distro/
  bundle.md                        # Thin bundle manifest
  context/
    distro-conventions.md          # The 11 opinions as session context
    environment-awareness.md       # Multi-surface environment behavior
  agents/
    health-agent.md                # In-session diagnostics ("check my env")
    friction-agent.md              # Friction detection and reporting
  behaviors/
    preflight.yaml                 # Pre-flight checks (composable)
    handoff.yaml                   # Session handoff on SESSION_END
  recipes/
    morning-brief.yaml             # Daily intelligence brief
    friction-report.yaml           # Weekly friction analysis
  docs/
    SETUP.md                       # User-facing setup guide
    ARCHITECTURE.md                # Ring 1/2/3 explained
```

### What Each Artifact Does

**`context/distro-conventions.md`** -- The 11 opinions from `OPINIONS.md`,
formatted as session context. Every session started with the distro bundle
knows: where projects live, how sessions are stored, that handoffs exist,
that memory is shared, that interfaces are viewports. This is the single
most impactful artifact -- it gives sessions awareness of the environment
they're running in. (Addresses Objective 2: context loss, Objective 3:
interchangeable interfaces.)

**`context/environment-awareness.md`** -- Technical context for multi-surface
operation. Sessions know they might be resumed from Slack, that handoffs
are written at session end, that `session-info.json` tracks working directory.

**`agents/health-agent.md`** -- An in-session agent that runs diagnostic
checks. Instead of exiting a session to run `amp-distro doctor`, you say
"check my environment health" and get results inline. Absorbs the 13
diagnostic checks from `doctor.py` as agent capability. (Addresses
Objective 5: self-healing.)

**`agents/friction-agent.md`** -- The genuinely new capability. Analyzes
session transcripts for friction signals (frustration language, repeated
context re-explanation, repair session launches, apology spirals). Produces
friction scores and suggested actions. (Addresses Objective 6: self-improving
friction detection.)

**`behaviors/preflight.yaml`** -- Pre-flight checks as a composable behavior.
Other bundles can include `distro:behaviors/preflight` to get the same checks.
Unlike the current `preflight.py` (Python code only callable by the bridge),
this is a standard behavior any bundle can compose. (Addresses Objective 1:
silent config failures.)

**`behaviors/handoff.yaml`** -- Session handoff generation as a composable
behavior. Fires on `SESSION_END`, calls a haiku-class model to summarize
what happened, writes `handoff.md` to the project directory. On next session
start, handoff is injected as system context. (Addresses Objective 2: context
loss.)

**`recipes/morning-brief.yaml`** -- Daily intelligence brief recipe. Reads
memory, recent session handoffs, project status, and produces a concise
"here's what happened, here's what's hot" summary. The North Star UX from
`planning/03-architecture-vision.md`. (Addresses Objective 6.)

**`recipes/friction-report.yaml`** -- Weekly friction analysis recipe.
Scans all sessions from the past week, classifies friction signals, produces
a scored report with top sources and suggested actions. The self-improving
loop. (Addresses Objective 6.)

### Bundle Manifest (`bundle.md`)

```yaml
---
bundle:
  name: amplifier-distro
  version: 1.0.0
  description: >
    Opinionated Amplifier environment with conventions, health checks,
    session handoffs, and friction detection.

includes:
  # Foundation behaviors (standard)
  - bundle: foundation:behaviors/agents
  - bundle: foundation:behaviors/filesystem
  - bundle: foundation:behaviors/tools

  # Distro-specific
  - behavior: distro:behaviors/preflight
  - behavior: distro:behaviors/handoff

context:
  - distro:context/distro-conventions.md
  - distro:context/environment-awareness.md

agents:
  health-agent:
    source: distro:agents/health-agent.md
  friction-agent:
    source: distro:agents/friction-agent.md
---

# Amplifier Distro Bundle

An opinionated environment bundle that eliminates configuration friction,
preserves context across sessions, and continuously detects attention drains.
```

---

## Part B: Ecosystem PRs

These are improvements to the shared platform that benefit everyone, not
just distro users. Each is a standalone PR to the appropriate repo.

### To amplifier-foundation

**PR 1: Explicit `~/.amplifier/` directory contract**

Foundation is the natural home for the directory layout spec since it's the
shared library all interfaces import. This PR defines:

- `~/.amplifier/projects/<slug>/sessions/<id>/` -- session storage
- `~/.amplifier/projects/<slug>/handoff.md` -- session handoff
- `~/.amplifier/memory/` -- shared memory store
- `~/.amplifier/cache/` -- module/bundle cache
- `~/.amplifier/settings.yaml` -- user configuration

Currently these paths are implicitly assumed but not documented as a contract.
Making it explicit enables all interfaces to agree on layout without consulting
a separate config file.

**PR 2: Bundle validation strict mode**

`validate(strict=True)` promotes warnings to errors for:
- Include URI resolution failures
- Agent file parse errors
- Context path existence checks
- Module source resolvability
- Required environment variable presence

Currently, a broken include is silently dropped. This is the #2 friction
source from the 91-session analysis.

**PR 3: Cache auto-refresh**

- TTL-based staleness check (default 7 days, configurable)
- Auto-invalidation on module load failure (re-clone once, then hard error)
- Atomic replacement (clone to temp, rename swap, no partial states)

Eliminates "have you tried clearing your cache?" debugging.

### To amplifier-app-cli

**PR 4: `amplifier doctor` command**

Absorbs the 13 diagnostic checks from `amp-distro doctor`:
- `--fix` auto-repair mode
- `--json` machine-readable output
- Checks: config validity, cache health, bundle parsing, API key presence,
  disk space, session integrity, memory store format, git config, Python
  version, module compatibility, stale sessions, orphaned cache entries,
  network connectivity

This belongs in the main CLI, not a separate `amp-distro` binary.

**PR 5: Pre-flight hook point**

A hook point between bundle load and `bundle.prepare()` where pre-flight
checks can run. The distro bundle's `preflight.yaml` behavior wires into
this hook. Other bundles can too.

- Prints pass/warn/fail per check
- Prompts `Continue anyway? [Y/n]` on non-critical failures
- Completes in <2 seconds for basic checks, <10 seconds with API validation

**PR 6: Handoff injection**

On session start, detect `~/.amplifier/projects/<slug>/handoff.md`. If present,
inject its content as system context. Sessions start "warm" -- the assistant
already knows what happened last time.

**PR 7: Opinion-driven defaults in `amplifier init`**

`amplifier init` writes recommended defaults to `settings.yaml`:
- Detects platform, identity (from `gh auth status`), workspace
- Sets up provider keys from environment
- Configures cache TTL and auto-refresh
- Enables pre-flight checks

The 11 opinions become **recommended defaults that init writes**, plus
documentation in the distro bundle's context files. No separate
`distro.yaml` needed.

---

## Part C: Standalone Experiences

The Slack bridge (~2400 lines), voice bridge, and web chat are valuable
working code. They are preserved but restructured.

### What Changes

**Before (current):**
```
src/amplifier_distro/server/
  app.py                    # Central FastAPI server + plugin discovery
  daemon.py                 # PID management, daemonize
  startup.py                # Structured logging, key export
  memory.py                 # MemoryService
  services.py               # Shared services
  session_backend.py         # Session backend for bridges
  apps/
    slack/                   # Slack bridge as server plugin
    voice/                   # Voice bridge as server plugin
    web_chat/                # Web chat as server plugin
```

All three experiences share the server framework, plugin discovery, daemon
management, and bridge abstraction. They're mounted as FastAPI sub-apps.

**After:**
```
experiences/
  slack/                     # Standalone Slack bridge
    main.py                  # Entry point, uses foundation directly
    sessions.py              # Session management (from current)
    events.py                # Event handling (from current)
    commands.py              # Command routing (from current)
    ...
  voice/                     # Standalone voice bridge
    main.py                  # Entry point, uses foundation directly
    ...
  web_chat/                  # Standalone web chat
    main.py                  # Entry point, uses foundation directly
    ...
```

Each experience:
- Has its own entry point (`python -m experiences.slack`)
- Uses `amplifier-foundation` directly for session creation
- Reads `settings.yaml` for config (no `distro.yaml`)
- Has no dependency on the other experiences
- Has no shared server framework, no plugin system, no bridge abstraction

### What Gets Removed

These components are replaced by ecosystem capabilities and don't need
to exist in the distro:

| Component | Replacement | Why |
|-----------|-------------|-----|
| `server/app.py` (FastAPI server + plugin system) | Each experience is standalone | No shared server needed |
| `bridge.py` + `bridge_protocols.py` | Foundation session creation | Bridge was reimplementing foundation |
| `cli.py` (amp-distro CLI) | `amplifier` CLI + ecosystem PRs | `amplifier doctor`, `amplifier init` |
| `schema.py` + `config.py` (distro.yaml) | `settings.yaml` (already exists) | One config file, not two |
| `bundle_composer.py` | The distro bundle directory itself | A real bundle replaces a generated YAML file |
| `daemon.py` + `startup.py` | Per-experience process management | Each experience manages its own lifecycle |
| `conventions.py` | `context/distro-conventions.md` in bundle | Opinions as session context, not Python constants |
| `features.py` | Not needed | Feature flags for a monolith that no longer exists |
| `deploy.py` | Not needed (Phase 4) | Cloud deployment is future work |
| `docs_config.py` | Not needed | Docs config for a setup website |
| `server/apps/install_wizard/` | `amplifier init` improvements | CLI handles setup |
| `server/apps/example/` | Not needed | Plugin system being removed |
| `keys.yaml` | Environment variables + `settings.yaml` | Standard Amplifier key management |
| `migrate.py` | One-time migration, then remove | Transitional code |
| `update_check.py` | `amplifier` CLI handles updates | Already exists |
| `backup.py` | Recipe or CLI extension | Could move to a recipe |

### What Gets Preserved

| Component | New Home | Notes |
|-----------|----------|-------|
| Slack bridge code (~2400 lines) | `experiences/slack/` | Working, battle-tested |
| Voice bridge | `experiences/voice/` | Working |
| Web chat | `experiences/web_chat/` | Working, recently enhanced |
| 13 doctor diagnostic checks | `amplifier doctor` CLI PR | Logic preserved, new home |
| Pre-flight check logic | `behaviors/preflight.yaml` | Composable behavior |
| Session handoff concept | `behaviors/handoff.yaml` | Composable behavior |
| Memory service patterns | Foundation memory + bundle context | Patterns preserved |
| Backup/restore logic | Recipe or CLI extension | Useful, needs new home |
| The 11 opinions | `context/distro-conventions.md` | The core value of the project |

---

## Objective-to-Implementation Mapping

Every objective from the one-pager maps to a specific deliverable:

| Objective | Friction Addressed | Implemented By |
|-----------|--------------------|----------------|
| 1. Eliminate silent config failures | #2 (silent bundle failures) | **B:** Foundation PR (strict validation) + CLI PR (pre-flight hook) + **A:** Bundle behavior (preflight.yaml) |
| 2. Eliminate cross-session context loss | #4 (context loss), #1 (corruption) | **B:** CLI PR (handoff injection) + **A:** Bundle behavior (handoff.yaml) |
| 3. Interchangeable interface viewports | #6 (environment friction) | **B:** Foundation PR (directory contract) + **A:** Bundle context (environment-awareness.md) |
| 4. One-time setup, then invisible | #2 (recurring config), #6 (env friction) | **B:** CLI PR (opinion-driven `amplifier init`) + **A:** Bundle context (distro-conventions.md) |
| 5. Self-healing with diagnostics | #1 (corruption), #2 (silent failures) | **B:** CLI PR (`amplifier doctor`) + Foundation PR (cache auto-refresh) + **A:** Bundle agent (health-agent.md) |
| 6. Self-improving friction detection | All, over time | **A:** Bundle agent (friction-agent.md) + Bundle recipes (morning-brief.yaml, friction-report.yaml) |

---

## Config Consolidation

### Before (current state)

| File | Purpose | Read By |
|------|---------|---------|
| `~/.amplifier/settings.yaml` | Amplifier CLI config | CLI |
| `~/.amplifier/distro.yaml` | Distro config (workspace, identity, bundle, cache, interfaces, integrations) | amp-distro server, bridges |
| `~/.amplifier/keys.yaml` | API keys + integration secrets | amp-distro server |
| `~/.amplifier/bundles/distro.yaml` | Generated bundle YAML | bridge session creation |

Four files, two config schemas, two key stores, one generated bundle.

### After

| File | Purpose | Read By |
|------|---------|---------|
| `~/.amplifier/settings.yaml` | All Amplifier config (existing + distro opinions as defaults) | Everything |
| `amplifier-bundle-distro/` | Bundle directory (context, agents, behaviors, recipes) | Bundle loader |

One config file. One bundle directory. Environment variables for secrets
(standard practice). The 11 opinions become recommended defaults that
`amplifier init` writes to `settings.yaml`.

---

## Execution Strategy

### Phase 1: The Bundle (can start immediately)

Create `amplifier-bundle-distro` with:
- `context/distro-conventions.md` (port from OPINIONS.md)
- `context/environment-awareness.md` (new)
- `bundle.md` (thin manifest)

This is immediately usable. Anyone can `includes:` the distro bundle and
get the opinions as session context. No ecosystem PRs required.

### Phase 2: Ecosystem PRs (parallel with Phase 1)

Submit PRs in dependency order:
1. Foundation: directory contract + strict validation + cache auto-refresh
2. CLI: `amplifier doctor` + pre-flight hook + handoff injection + init defaults

Each PR is independently valuable. No PR depends on the bundle existing.

### Phase 3: Bundle Agents and Recipes

After ecosystem PRs land:
- `agents/health-agent.md` (uses `amplifier doctor` logic)
- `behaviors/preflight.yaml` (wires into pre-flight hook)
- `behaviors/handoff.yaml` (wires into SESSION_END)
- `recipes/morning-brief.yaml`
- `recipes/friction-report.yaml`
- `agents/friction-agent.md`

### Phase 4: Experience Extraction

Restructure Slack/voice/web chat as standalone:
- Extract from server plugin framework
- Wire directly to foundation for session creation
- Remove bridge abstraction, daemon, shared server
- Each experience gets its own entry point and process

### What Happens to This Repo

This repo (`amplifier-distro`) becomes:
- **`planning/`** -- preserved as historical record
- **`responses/`** -- analysis and design documents
- **`experiences/`** -- standalone Slack, voice, web chat
- **`tests/`** -- tests for the experiences
- **`src/amplifier_distro/`** -- gradually emptied as code moves to proper homes

The bundle itself lives in a new `amplifier-bundle-distro` repo (or as a
directory within this repo if preferred -- the bundle loader doesn't care
about repo boundaries).

---

## What This Design Preserves

1. **The 11 opinions.** Every settled convention survives, expressed as
   session context rather than Python constants.

2. **The 6 objectives.** Every objective maps to a concrete deliverable.
   Nothing is abandoned.

3. **The working code.** Slack bridge, voice bridge, web chat, doctor
   checks, pre-flight logic -- all preserved, moved to better homes.

4. **The 1000+ tests.** Tests move with their code. Experience tests stay
   here. Foundation/CLI tests accompany their PRs.

5. **The original plan.** `planning/10-project-structure.md` described
   exactly this shape. We're returning to the design that was right
   from the start.

## What This Design Eliminates

1. **Reimplemented infrastructure.** Session creation, bundle loading,
   config management, cache, CLI -- all duplicated from foundation/CLI.

2. **A second config system.** `distro.yaml` + `keys.yaml` alongside
   `settings.yaml` created confusion about which file to edit.

3. **A monolithic server.** Plugin discovery, shared services, daemon
   management -- complexity that served the plugin pattern, not the user.

4. **The bridge abstraction.** `bridge.py` + `bridge_protocols.py`
   reimplemented what foundation already provides for session lifecycle.

---

## Source Documents

| Document | Contains |
|----------|----------|
| `responses/distro-one-pager.md` | Reverse-engineered vision: 6 objectives with friction data and source citations |
| `responses/bundle-drift.md` | Analysis of how the bundle design drifted from directory to single YAML file |
| `OPINIONS.md` | The 11 settled conventions |
| `planning/10-project-structure.md` | Original implementation plan (the design we're returning to) |
| `planning/03-architecture-vision.md` | Three-ring architecture model |
| `planning/01-friction-analysis.md` | 91-session friction analysis (the data driving everything) |
| Session 9c72e8a7 | 24-turn convergence session where all decisions were confirmed |