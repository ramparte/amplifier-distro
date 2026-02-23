# Amplifier Distro: Team Structure and Architecture

Last updated: 2026-02-23

This document defines the amplifier-distro architecture, component ownership, and team responsibilities. If you are a team member, find your name in Section 5 for your specific guidance. Point amplifier at this file and tell it who you are for personalized direction.

---

## Section 1: Architecture Overview

The distro is a **registry of discoverable decisions**. It is not an application. It defines how amplifier is configured, where sessions live, what bundles are used, and how components find each other. Any amplifier-aware app can discover the distro, read its decisions, and use them. If no distro is present, apps configure themselves independently.

The architecture has three layers:

### Layer 1 -- The Distro (the registry)

Defined by three things:

- **`distro.yaml`** -- the config file at `~/.amplifier/distro.yaml`. Contains all decisions: workspace root, identity, session paths, memory configuration, server URL, installed apps.
- **`conventions.py`** -- immutable naming standards. Path patterns, file names, directory structures that all components agree on.
- **The Bridge API** -- a library (not a gatekeeper) for distro-aware session lifecycle. Handles bundle resolution, provider injection, transcript persistence, handoff injection, and session resume with crash recovery.

### Layer 2 -- Mandatory Components

Two components are always installed by the distro:

- **The `amplifier` CLI** (`microsoft/amplifier-app-cli`) -- manages the amplifier install, updates, sessions, and bundles.
- **The distro server** (to be extracted into its own repo) -- hosts the setup/config UX, provides the plugin platform for server modules.

### Layer 3 -- Optional Components

Apps and server modules installed independently, registered with the distro:

- **Apps** (standalone processes): TUI, Kepler
- **Server modules** (plugins hosted by the server): Slack bridge, Voice bridge, Web chat
- Each is its own repo. Each provides config/install UX via the server's plugin contract.

### Key Principles

- All apps work with or without the distro. Each looks for the distro first, falls back to its own config.
- Under a distro install, all apps share sessions, memory, and common state.
- The distro is also a user experience -- a user launches it, gets walked through a friendly install process. Step 1 is getting LLM keys, then getting amplifier installed. After that the server's install wizard provides a friendlier guided experience.

---

## Section 2: Component Inventory and Ownership

### Team

| Person | GitHub | Role |
|--------|--------|------|
| Sam Schillace | `ramparte` | Architect / Lead -- reviews contracts, unblocks, no component ownership |
| Marc Goodner | `robotdad` | Distro Core + CLI |
| Samuel Lee | `samueljklee` | Server Platform + Voice Bridge |
| MJ Jabbour | `michaeljabbour` | Kepler |
| Paul Payne | `payneio` | TUI + Slack Bridge + In-Session Experience |

### Platform Components (contracts that others depend on)

| Component | Repo | Owner | Responsibility |
|-----------|------|-------|----------------|
| Distro Core | `ramparte/amplifier-distro` | Marc Goodner (`robotdad`) | Conventions, schema, config, Bridge library, preflight, doctor. Evolves the registry. Defines the contracts that apps and modules consume. |
| Server Platform | New repo (to be extracted) | Samuel Lee (`samueljklee`) | FastAPI host, plugin contract (`AppManifest`), settings UI, install wizard. Defines the contract that server modules implement. |

### Mandatory Installs (separate repos, installed by distro)

| Component | Repo | Owner |
|-----------|------|-------|
| `amplifier` CLI | `microsoft/amplifier-app-cli` | Marc Goodner (`robotdad`) |

### Optional -- Standalone Apps

| Component | Repo | Owner |
|-----------|------|-------|
| TUI | `ramparte/amplifier-tui` | Paul Payne (`payneio`) |
| Kepler | MJ's repo | MJ Jabbour (`michaeljabbour`) |

### Optional -- Server Modules (plugins, each its own repo)

| Component | Repo | Owner |
|-----------|------|-------|
| Slack Bridge | Separate repo (to be extracted) | Paul Payne (`payneio`) |
| Voice Bridge | Separate repo (to be extracted) | Samuel Lee (`samueljklee`) |
| Web Chat | Separate repo (to be extracted, or stays in server initially) | Samuel Lee (`samueljklee`) |

### In-Session Experience

| Component | Repo | Owner |
|-----------|------|-------|
| `amplifier-start` | `payneio/amplifier-start` | Paul Payne (`payneio`) |

The distro includes `amplifier-start` in every bundle it generates. This is THE in-session behavior layer -- conventions-as-context, handoff hooks, friction detection, morning briefs.

### What "Ownership" Means

- You make design decisions for your component without needing approval (within the contracts).
- You review and merge PRs to your repo.
- You are responsible for tests passing and the component working.
- You are NOT blocked by other owners -- if you need a contract change, you propose it; the platform owner decides.
- Sam reviews contract-level changes (anything that affects how components talk to each other).

---

## Section 3: Contracts, Libraries, and Boundaries

### Contract 1: Distro Discovery

Any app discovers the distro by looking for `~/.amplifier/distro.yaml`. If present, read it for decisions (workspace root, identity, session paths, memory, server URL, installed apps). If absent, configure independently. The schema is owned by Marc and is the single source of truth for what decisions exist.

### Contract 2: Server Plugin Contract

Server modules implement `AppManifest` -- declare name, URL prefix, version, routes, and a config/install UX endpoint. The server discovers, mounts, and presents them. Samuel owns this contract. Modules provide their own config/install UX at a known endpoint -- the server discovers it and integrates it into the setup flow. It should be documented well enough that someone can write a new module without reading the server source.

### Contract 3: In-Session Behavior Boundary

The distro includes `amplifier-start` in every bundle it generates. If it's in-session behavior (conventions-as-context, handoff hooks, friction detection, morning briefs), it lives in `amplifier-start`. If it's infrastructure (install, config, serving), it lives in the distro. The distro MUST NOT duplicate in-session behaviors.

### Library: The Bridge API

The Bridge (`bridge.py`) handles the distro-aware session lifecycle -- bundle resolution with 3-level fallback (explicit override -> distro.yaml default -> convention path), provider injection, transcript persistence, handoff injection, resume with crash recovery. The Bridge wraps 8 additional steps around the 2 foundation calls (`load_bundle()` + `create_session()`). Apps SHOULD use it because it handles all the distro-aware complexity. But it's a library, not a gatekeeper -- apps that follow the APPLICATION_INTEGRATION_GUIDE directly work fine without it, they just don't get distro-aware features for free.

### Upstream: Application Integration Guide

All apps follow `amplifier-foundation`'s APPLICATION_INTEGRATION_GUIDE (https://github.com/microsoft/amplifier-foundation/blob/main/docs/APPLICATION_INTEGRATION_GUIDE.md). This is the canonical reference for how to embed amplifier in an app. Every app owner is responsible for knowing it.

### Communication Rule

Contract changes (distro schema, server plugin contract, in-session behavior boundary) require a PR against the contract owner's repo. Everything else, you own and ship independently.

---

## Section 4: Current State to Target State

### Marc -- Distro Core + CLI

| Area | Current State | Target State | Work Required |
|------|--------------|--------------|---------------|
| Distro registry | `distro.yaml` + `conventions.py` + `schema.py` + `config.py` -- solid, working | Same, but schema documented as the public API surface | Document the schema as a contract other apps consume |
| Bridge API | `bridge.py` -- 944 lines, working but create/resume share ~60% duplicated logic | Refactored, published as the library apps import | Refactor shared logic, clean up SessionHandle facade |
| Pre-flight / Doctor | Working CLI commands | Same | Stable, maintain |
| `amplifier` CLI | Separate repo (`microsoft/amplifier-app-cli`), working | Same, ensure it follows APPLICATION_INTEGRATION_GUIDE | Audit and align |
| Server extraction | Server code lives in `amplifier-distro` today | Server is its own repo, distro installs it as a dependency | Coordinate with Samuel on the split |

### Samuel -- Server Platform + Voice

| Area | Current State | Target State | Work Required |
|------|--------------|--------------|---------------|
| Server | Baked into `amplifier-distro`, `amp-distro-server` entry point | Own repo, own package, depends on distro core as a library | Extract into new repo, preserve plugin architecture |
| Plugin contract | `AppManifest` + `discover_apps()` exists but apps are discovered from local directories | Documented contract, plugins installable from separate packages | Formalize AppManifest, add package-based plugin discovery |
| Settings + Install Wizard | Working server apps | Stay in server repo as core server functionality | Move with the server extraction |
| Voice bridge | Working server plugin in `server/apps/voice/` | Own repo, installable as a server module | Extract after plugin contract is formalized |
| Web chat | Working server plugin in `server/apps/web_chat/` | Own repo or stays in server initially | Lower priority, extract when it makes sense |

### Paul -- TUI + Slack + In-Session Experience

| Area | Current State | Target State | Work Required |
|------|--------------|--------------|---------------|
| `amplifier-start` | Working bundle with hooks, agents, recipes at `payneio/amplifier-start` | Distro includes it in all generated bundles; it's THE in-session behavior layer | Marc adds the include in `bundle_composer.py` |
| TUI | Exists at `ramparte/amplifier-tui`, Sam authored | Paul takes ownership, ensures it discovers and uses the distro | Handoff from Sam, audit distro integration |
| Slack bridge | Working server plugin in `amplifier-distro/server/apps/slack/` (13 modules, heavily hardened) | Own repo, installable as a server module | Extract after Samuel formalizes plugin contract |
| Conventions reconciliation | `amplifier-start` conventions and distro's `conventions.py` came from same source but are maintained independently | Single source of truth, no drift possible | Ensure `amplifier-start` references match distro conventions exactly |

### MJ -- Kepler

| Area | Current State | Target State | Work Required |
|------|--------------|--------------|---------------|
| Kepler | MJ's repo, has `kepler` section in `distro.yaml` | Standalone app that discovers distro, uses Bridge library, follows APPLICATION_INTEGRATION_GUIDE | Audit distro integration, ensure Bridge usage |

### Sequencing

The server extraction is the critical path -- Samuel can't formalize the plugin contract until the server is its own repo, and Paul can't extract the Slack bridge until the plugin contract is formalized. Marc's distro core work (Bridge refactor, schema docs) and Paul's `amplifier-start` reconciliation can happen in parallel.

---

## Section 5: Owner Guides

### Marc Goodner (`robotdad`) -- Distro Core + CLI

**What you own:** The `amplifier-distro` repo (the registry: conventions, schema, config, Bridge library, pre-flight, doctor, backup/restore, the `amp-distro` CLI) and the `amplifier` CLI (`microsoft/amplifier-app-cli`).

**What depends on you:** Everything. The distro schema is the source of truth that all apps and modules consume. The Bridge library is what surfaces use to create sessions. If you break a convention or change the schema without coordination, downstream breaks.

**What you depend on:** `amplifier-foundation` (upstream, you consume its APIs). `amplifier-start` (Paul's bundle, which the distro should include in generated bundles).

**Immediate priorities:**

1. Coordinate with Samuel on server extraction -- define what stays in distro vs what moves to server repo. The Bridge library stays with you. The FastAPI code, plugins, and server entry point move to Samuel.
2. Add `amplifier-start` as an include in `bundle_composer.py` so generated bundles carry Paul's in-session behaviors.
3. Document the `distro.yaml` schema as a public API surface -- other apps need to know it's stable and what each field means.
4. Refactor Bridge (`bridge.py`) -- create/resume share ~60% duplicated code. Extract shared logic.

**How to stay in your lane:** You don't write server plugins. You don't write in-session behaviors (that's Paul's `amplifier-start`). You don't decide how Kepler works. You own the contracts and the infrastructure. When someone needs a new field in `distro.yaml` or a new capability in the Bridge, that comes through you.

---

### Samuel Lee (`samueljklee`) -- Server Platform + Voice

**What you own:** The distro server (to be extracted into its own repo) and the voice bridge module (to be extracted into its own repo after the plugin contract is formalized).

**What depends on you:** Every server module author (Paul for Slack, anyone who writes a future module) depends on your plugin contract (`AppManifest`). The install wizard and settings UI are core to the setup experience. Web chat depends on you until it's extracted.

**What you depend on:** Marc's distro core (the Bridge library, distro config). `amplifier-foundation` (upstream).

**Immediate priorities:**

1. Extract the server into its own repo. This is the critical path -- nothing else can be cleanly extracted until this is done. Work with Marc to define the cut line (Bridge stays in distro, FastAPI + plugins + server entry point move to you).
2. Formalize the plugin contract. Document `AppManifest` so that module authors know: how to declare routes, how to expose config/install UX, how to access shared services (session backend, memory, config). This must be documented well enough that Paul can extract Slack without reading your source.
3. Extract voice bridge into its own repo as the first proof that the plugin contract works for external modules.

**How to stay in your lane:** You own the server platform and its contract. You don't change the distro schema (that's Marc). You don't write in-session behaviors (that's Paul). You don't decide what modules exist -- you make it possible for others to write them.

---

### Paul Payne (`payneio`) -- TUI + Slack Bridge + In-Session Experience

**What you own:** `amplifier-start` (the in-session experience bundle: conventions-as-context, handoff hooks, friction detection, morning brief), `amplifier-tui` (the terminal interface), and the Slack bridge (to be extracted into its own repo).

**What depends on you:** The distro depends on `amplifier-start` -- it's included in every generated bundle. Anyone using the distro gets your handoff hooks, your friction detection, your morning brief. The Slack bridge is how the distro connects to Slack.

**What you depend on:** Marc's distro core (the conventions and config your bundle references must match). Samuel's server plugin contract (the Slack bridge needs to implement `AppManifest` once extracted).

**Immediate priorities:**

1. Reconcile `amplifier-start` conventions with the distro's `conventions.py` and `distro.yaml`. They came from the same source (the 91-session friction analysis) but must not drift. Ensure your context file references the same paths and config keys Marc's code uses.
2. Take ownership of `amplifier-tui` from Sam. Audit it for distro integration -- does it discover `distro.yaml`? Does it use the Bridge library? Does it follow the APPLICATION_INTEGRATION_GUIDE?
3. Wait for Samuel's plugin contract, then extract the Slack bridge from `amplifier-distro/server/apps/slack/` into its own repo implementing that contract.

**How to stay in your lane:** You don't change the distro schema (propose changes to Marc). You don't modify the server platform (propose changes to Samuel). You own the user-facing experience layers: what happens inside a session, what the TUI looks like, how Slack connects.

---

### MJ Jabbour (`michaeljabbour`) -- Kepler

**What you own:** Kepler, the desktop GUI app.

**What depends on you:** Nothing in the distro depends on Kepler -- it's a standalone optional app.

**What you depend on:** Marc's distro core (Kepler should discover `distro.yaml` and use the Bridge library for session creation). The `kepler` section in `distro.yaml` is your config surface -- propose schema changes to Marc if you need new fields.

**Immediate priorities:**

1. Ensure Kepler discovers the distro and uses the Bridge library. This means Kepler gets bundle resolution, provider injection, transcript persistence, and session resume for free.
2. Follow the APPLICATION_INTEGRATION_GUIDE for how Kepler embeds amplifier.
3. Ensure Kepler works standalone (no distro installed) with its own configuration as a fallback.

**How to stay in your lane:** You own Kepler end-to-end. You don't need to coordinate with anyone except Marc for schema changes. Ship independently.

---

### Sam Schillace (`ramparte`) -- Architect / Lead

**What you own:** No component. You review contract-level changes (distro schema changes, server plugin contract changes, in-session behavior boundaries). You unblock people. You make architectural calls when owners disagree.

**When you're needed:** When a contract change affects multiple owners. When two owners disagree on a boundary. When someone wants to add a new "decision" to the distro. When a new component needs to be created.

**When you're NOT needed:** Implementation within a component. Bug fixes. Feature work that stays within one owner's boundary. Anything that doesn't change a contract.

---

## Section 6: Decision Record -- Paul's `lean-experience-server` Branch

Paul Payne created a branch (`lean-experience-server`) that proposes an alternative architecture: delete the registry layer entirely and redefine the distro as just the experience server. This section documents the team's decision and how to use Paul's work constructively.

### The Proposal

Paul's branch deletes ~14,500 lines and redefines the three-part Amplifier install as:

| Component | Role |
|-----------|------|
| `amplifier` CLI | The tool (commands, doctor, init, sessions) |
| `amplifier-start` | The opinions (conventions, context, agents, hooks) |
| `amplifier-distro` | The experiences (web chat, Slack, voice, etc.) |

Specifically deleted: the Bridge (`bridge.py`), `distro.yaml` and its config/schema system, the feature catalog and bundle composer, doctor, preflight, settings UI, install wizard, and most CLI commands.

### The Decision: Keep Vision A (the distro as a registry + coordination layer)

The distro is a distro -- a coordination mechanism for distributing and configuring a series of tools and components, akin to a Linux distribution. Deleting the coordination layer creates a fragility: with no single source of truth (`distro.yaml`), the CLI, `amplifier-start`, and the experience server can silently disagree about paths, identity, and configuration. That's the exact friction the distro was designed to eliminate.

### What Paul Correctly Identified (use as simplification guide)

Paul's branch is a valuable inventory of what's over-engineered. The following action items are derived from his analysis:

**Action 1: Simplify `distro.yaml` schema.** The current schema carries 13 sections including app-specific config (Slack, Voice, Kepler, Watchdog). Consider a pattern where apps register their own config sections rather than core carrying all of them. Reduce the core schema to the decisions that are truly common: workspace root, identity, memory, bundle, cache, preflight, interfaces, server location.

**Action 2: Simplify the Bridge.** The Bridge wraps 8 steps around 2 foundation calls. That's justified. But `create_session` and `resume_session` share ~60% duplicated code and `SessionHandle` is a leaky facade. Refactor the shared logic and decide whether `SessionHandle` is a real abstraction or a convenience type.

**Action 3: Let `amplifier-start` own in-session behavior.** This is already in our plan (Contract 3). The distro generates bundles that include `amplifier-start`. The distro MUST NOT independently implement handoff hooks, friction detection, or conventions-as-context. Paul's bundle handles that layer.

**Action 4: Let the CLI own its health commands.** The distro's `doctor.py` (529 lines) and `preflight.py` overlap with what the `amplifier` CLI can provide. Consider whether preflight and doctor should migrate to the CLI (where they'd serve all users, not just distro users) or remain in the distro as distro-specific health checks. Either way, avoid maintaining parallel implementations.

**Action 5: Keep the registry as the single source of truth.** This is the core architectural decision. `distro.yaml` is what makes distributed components behave as one system. Without it, every app is its own system integrator. The schema should be simplified (Action 1) but not eliminated.

### What NOT to Merge

- Do not merge the `FoundationBackend` replacement for `BridgeBackend` as-is. It raises `NotImplementedError` on session resume, which is a production regression for the Slack and Voice bridges.
- Do not delete the settings UI or install wizard. They're part of the distro's user experience (the friendly install flow). They may need refactoring but not removal.
- Do not delete `distro.yaml`. See Action 5.

---

## Section 7: Pre-Handoff Refactor (Big Bang)

Before handing off components to their owners, Sam will do a focused refactor to clean up boundaries. This ensures each owner starts with a clean codebase rather than spending their first month on structural cleanup.

### Why a Big Bang

- Sam knows the codebase best (wrote most of it). Structural moves that take Sam hours would take new owners days of context-building.
- Handing off clean is 10x better than handing off messy with instructions to clean up.
- The test suite (1,158 tests, 99.65% passing, 17 seconds) provides a strong safety net for aggressive refactoring.
- It removes the "coordinate the extraction" problem -- Marc and Samuel start with clean repos.

### Scope

The entanglement is narrow but deep: 9 core modules, concentrated in 3 server files (`app.py`, `cli.py`, `session_backend.py`). It's a star topology centered on `config`, `conventions`, `bridge`, and `schema`. Estimated effort: 1-2 focused sessions with AI.

**Current numbers:**

| Area | Files | Lines |
|------|------:|------:|
| Core distro | 21 | 6,084 |
| Server | 32 | 9,681 |
| Tests | 36 | 15,318 |
| Total | 89 | 31,083 |

24 of 32 server files import from core distro modules (75% coupling). But the coupling runs through only 9 core modules: `config`, `conventions`, `schema`, `bridge`, `features`, `docs_config`, `fileutil`, `preflight`, `backup`.

### Refactor Tasks

1. **Define the public API surface for core distro.** Create clean `__init__.py` re-exports that define what server (and future external consumers) are allowed to import. Replace the 24 entangled import paths in server/ with imports from this surface.

2. **Refactor Bridge.** Extract shared logic between `create_session` and `resume_session` into a `_prepare_session()` method. Clean up `SessionHandle` -- decide if it's a real abstraction boundary (remove coordinator reach-through) or a thin convenience type (stop pretending it hides internals).

3. **Slim the schema.** Move app-specific config sections (Slack, Voice, Kepler, Watchdog) to a pattern where apps can register config sections with the distro, rather than core hardcoding every app's schema. Core keeps: workspace, identity, bundle, cache, preflight, interfaces, memory, server, backup.

4. **Add `amplifier-start` include.** Update `bundle_composer.py` to include `amplifier-start` in generated bundles.

5. **Prepare server for extraction.** Ensure all server imports go through the public API surface (Task 1). Verify that the server directory could be moved to a separate repo by only changing import paths. Don't actually extract yet -- that's Samuel's job -- but make it ready.

### Sequencing After the Big Bang

Once the refactor is complete, the handoff order is:

1. **Marc** receives a clean `amplifier-distro` with clear boundaries and documented public API. Starts owning distro core + CLI immediately.
2. **Samuel** receives a server directory that imports only through the public API surface. Extracts it into its own repo and formalizes the plugin contract.
3. **Paul** receives `amplifier-tui` handoff from Sam. Begins `amplifier-start` reconciliation with distro conventions. Waits for Samuel's plugin contract before extracting Slack.
4. **MJ** continues Kepler work independently, auditing distro integration.

### Success Criteria

- All 1,158 tests still pass (or a reasonable subset if tests are reorganized).
- Server directory imports only through the distro's public API surface.
- Bridge `create_session` and `resume_session` share a common `_prepare_session()` method.
- `bundle_composer.py` includes `amplifier-start` in generated bundles.
- Schema has a clear separation between core decisions and app-specific config.
