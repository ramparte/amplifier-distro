# Amplifier Distro: Vision Document (Reverse-Engineered from Source Artifacts)

> This document reconstructs the intended objectives of amplifier-distro from
> its planning documents, opinions, architecture vision, friction analysis, task
> lists, and implementation spec. Every claim is traceable to a specific source
> file. The goal is to separate "what the project was meant to do" from "what
> metaphor we use to describe it."

---

## The Problem (with data)

Analysis of 91 user-facing sessions (Jan 23 - Feb 6, 2026) found that **~45%
of Amplifier time was spent on friction rather than actual work.** Six specific
friction categories were identified and ranked by severity.

Source: `planning/01-friction-analysis.md`

| # | Friction Category | Severity | Scale | Specific Evidence |
|---|-------------------|----------|-------|-------------------|
| 1 | **Session corruption & repair** | Critical | 9+ sessions dedicated to repairing other sessions; worst case: 1 broken session required 3 repair sessions | Users manually launching "repair sessions" to fix dangling tool calls, context overflow, unproductive loops |
| 2 | **Silent bundle config failures** | Critical | 9+ sessions, same errors recurring across days/weeks | `_parse_include()` only recognizes `bundle:` key; using `behavior:` or `module:` silently drops the include. Agents disappear with no diagnostic. 5 specific bundles identified as recurring offenders. |
| 3 | **Agent competence / trust failures** | High | 58 frustration signals across 28 sessions | Agent invented CLI commands that don't exist, claimed repos didn't exist when they did, reported code as "production ready" with white-on-white text |
| 4 | **Cross-session context loss** | High | 80 "repeat context" signals across 26 sessions | Architecture decisions, project goals, and what was already tried evaporate between sessions. Users spend 6+ turns rebuilding context. |
| 5 | **Build recovery marathons** | High | 5+ sessions recovering broken builds in one project; error counts: 168 -> 572 in one attempt | Cascading failures requiring dedicated "strict mode" recovery sessions |
| 6 | **Environment & sandbox friction** | Medium | 6+ sessions | Write path restrictions blocking cross-repo workflows, hardcoded developer defaults in shared tools, WSL cross-filesystem pain |

---

## The Six Intended Objectives

Each objective maps directly to one or more friction categories above. These
are the concrete things the project is supposed to accomplish.

### Objective 1: Eliminate silent configuration failures

**Friction addressed:** #2 (silent bundle config failures), #6 (environment friction)

**Intended behavior:**
- Bundle includes that fail to resolve produce an error, never a silent drop
- Pre-flight health checks run before every session start (API keys valid? Bundle parsed? Model names exist? Required tools available?)
- Pre-flight completes in <2 seconds for basic checks, <10 seconds with API validation
- `amp distro validate` performs deep validation on demand
- `amp distro doctor --fix` auto-repairs known issues (stale cache, broken includes, debris directories)
- A broken include is an error the user sees immediately, with the specific include name and failure reason

**Specific contracts:**
- `BundleValidator.validate(strict=True)` in amplifier-foundation: promotes warnings to errors for include URI resolution, agent file parsing, context path existence, module source resolvability, env var presence
- Pre-flight runs between bundle load and `bundle.prepare()`, prints pass/warn/fail per check, prompts `Continue anyway? [Y/n]` on failures

Sources: `planning/07-ring1-deep-dive.md:44-81`, `planning/03-architecture-vision.md:54-59`, `OPINIONS.md` Section 5, Section 9

### Objective 2: Eliminate cross-session context loss

**Friction addressed:** #4 (context loss), #1 (session corruption requiring re-explanation)

**Intended behavior:**
- When a session ends, a lightweight LLM call (~2 seconds, haiku-class model) generates a structured summary: what was accomplished (files changed, decisions made), what's in progress/blocked, key context for next session, suggested next steps
- Summary is written to `~/.amplifier/projects/<slug>/handoff.md`
- When a new session starts in the same project directory, the handoff content is automatically injected as system context
- Sessions start "warm" -- the assistant already knows what happened last time
- Session handoffs are also stored as project memories, making architecture decisions searchable: "What did I decide about X?"

**Specific contracts:**
- Requires `SESSION_END` event in amplifier-core (emitted from `AmplifierSession.cleanup()` with metadata: duration, turn count, tools used)
- A hook in the distro bundle fires on `SESSION_END`, reads last N messages, calls haiku for summary, writes `handoff.md`
- On session start, system detects `handoff.md` and injects as system context

Sources: `planning/07-ring1-deep-dive.md:97-138`, `planning/11-task-list.md:133-171`, `OPINIONS.md` Section 4

### Objective 3: Make all interfaces interchangeable viewports

**Friction addressed:** #6 (environment friction), #4 (context loss between interfaces)

**Intended behavior:**
- Start a session in CLI, continue in TUI, review in voice. Same session files, same state.
- Every interface reads the same `distro.yaml` for workspace, identity, and bundle config
- Every interface creates sessions through the same Interface Adapter -- no interface implements session lifecycle itself
- Installing an interface is one command: `amp distro install voice` clones the repo, installs deps, links config, runs a smoke test, prints start instructions
- No hardcoded paths, provider configs, or bundle names in interface code. The 7 specific hardcoded items in amplifier-voice are listed in `planning/08-ring2-deep-dive.md` with exact file:line references.
- The TUI's `sys.path` hack importing from `amplifier_app_cli` is replaced with direct `amplifier_foundation` usage

**Specific contracts:**
- `InterfaceAdapter` class in amplifier-foundation with 4 methods: `create_session()`, `execute()`, `cleanup()`, `register_output_hooks()`
- Each interface implements `OutputCallbacks` (how to display text, tool calls, errors) and calls InterfaceAdapter for everything else
- Eliminates ~100 lines of duplicated session lifecycle code per interface
- All interfaces write sessions to `~/.amplifier/projects/<slug>/sessions/<id>/` with the same file format (`transcript.jsonl`, `events.jsonl`, `session-info.json`, `handoff.md`)

Sources: `planning/08-ring2-deep-dive.md:177-203`, `OPINIONS.md` Section 4, Section 6

### Objective 4: One-time setup, then invisible

**Friction addressed:** #2 (recurring config errors), #6 (environment friction)

**Intended behavior:**
- `amp distro init` detects platform, identity (from `gh auth status`), workspace (from common paths), provider keys, and existing bundle -- then writes a validated config
- After init, Ring 1 (foundation) requires zero ongoing attention. Workspace root, identity, API keys, bundle composition, cache management, memory location -- all set once.
- Cache auto-refreshes on TTL (default 7 days) and on module load failure. No "have you tried clearing your cache?" debugging.
- Auto-refresh uses atomic replacement: clone to temp dir, swap via rename. No partial states.
- A setup website at a known URL contains machine-parseable instructions so an agent can execute setup for a new team member: "point an agent at this URL"

**Specific config contract:**
- One config file: `~/.amplifier/distro.yaml` with sections for workspace, identity, bundle, cache, memory, preflight, interfaces, server, backup, integrations
- One secrets file: `~/.amplifier/keys.yaml` (chmod 600, excluded from backup, never restored)
- Every distro-aware tool reads `distro.yaml`. Period.

Sources: `planning/03-architecture-vision.md:74-97`, `planning/09-setup-tool.md:18-70`, `OPINIONS.md` Sections 1-2, 7-8, 10-11

### Objective 5: Self-healing environment with diagnostics

**Friction addressed:** #1 (session corruption), #2 (silent failures), #5 (build recovery)

**Intended behavior:**
- `amp distro doctor` runs 13+ diagnostic checks with `--fix` auto-repair and `--json` output
- Pre-flight on every session start catches problems before they waste time
- Cache entries that fail to load are automatically invalidated and re-cloned (once, then hard error)
- Session health monitoring catches corruption before it compounds -- never require a human to launch a "repair session"
- Graceful degradation instead of corruption: if a module fails, the session can proceed without it (with a warning) rather than crashing entirely

**Specific contracts:**
- Pre-flight is non-optional. You can make it non-blocking (`preflight: warn`), but you can't disable it entirely. "The whole point is that things work reliably." (`OPINIONS.md` Section 9)
- Cache TTL, auto-refresh, and integrity checking are configurable per `distro.yaml`

Sources: `planning/07-ring1-deep-dive.md:141-168`, `OPINIONS.md` Section 8, Section 9, `planning/01-friction-analysis.md:29-33`

### Objective 6: Self-improving friction detection (the meta-objective)

**Friction addressed:** All categories, over time

**Intended behavior:**
- Weekly friction detection recipe analyzes all sessions from the past week
- Classifies friction signals: user frustration language, repeated context re-explanation, repair session launches, configuration debugging cycles, apology spirals (5+ "I apologize" without progress)
- Produces a friction report: score, top 3 sources, trends, suggested actions
- When a pattern matches a known fix category (broken include, stale cache, missing config): generates a proposed fix, presents to human for approval, applies on approval
- Morning brief at session start: "Here's what happened since last session, here's what's hot, what would you like to focus on?" -- takes <15 seconds to read
- Friction metrics replace project management. The system tells you what hurts most. You fix that. The system confirms it's better. No Gantt charts, no sprint planning, no status meetings.

**The self-improving loop:**
```
OBSERVE (analyze sessions for friction patterns)
    -> DIAGNOSE (classify root cause, estimate attention cost)
        -> ACT (apply fix: config change, new recipe, behavior update)
            -> VERIFY (did friction go down? measure.)
                -> back to OBSERVE
```

Sources: `planning/05-self-improving-loop.md` (entire document), `planning/03-architecture-vision.md:233-253`, `planning/11-task-list.md:310-373`

---

## The North Star User Experience

Source: `planning/03-architecture-vision.md:233-253`

```
$ amp
Good morning. Since your last session:
  - 3 topics updated in WhatsApp groups (AI orchestration,
    voice pipeline, agent loops)
  - 2 ideas captured from conversations (auto-extracted)
  - Build for word3 is green, lifeline has 2 test failures

Your top priorities today (based on current scoring):
  1. Voice pipeline: WebRTC client missing [high impact, low effort]
  2. Bundle validation: fix silent include failures [high impact, med effort]
  3. CarPlay: implement basic voice bridge [medium impact, med effort]

What would you like to focus on?
```

This experience requires: Ring 1 (foundation) is invisible, Ring 2 (interfaces)
is muscle memory, and Ring 3 (workflows) gets all the attention. The user's
~4 hours of daily deep focus goes to judgment, creativity, and decisions --
not to plumbing, re-explaining context, or debugging configuration.

---

## The Three Rings (structural model)

This is NOT a metaphor about Linux distros. It's an attention allocation model
that determines what gets built where:

| Ring | Attention Budget | Changes | Contains |
|------|-----------------|---------|----------|
| **Ring 1: Foundation** | Zero ongoing attention (set once, forget) | Rarely (setup, repair) | Workspace, identity, config, keys, bundle, cache, memory, health checks, session handoffs |
| **Ring 2: Interfaces** | Minimal attention (muscle memory) | Per-interaction (pick an interface) | CLI, TUI, Voice, Web, CarPlay -- all viewports into the same system |
| **Ring 3: Workflows** | All attention (this is where work happens) | Daily (adapts to context) | Morning brief, idea capture, friction detection, project execution, knowledge synthesis |

Source: `planning/03-architecture-vision.md:1-35`

---

## What Changes Where (mechanism vs policy)

The project was designed to make targeted changes across the ecosystem, not to
be a standalone monolith.

| Change | Target Repo | Rationale |
|--------|------------|-----------|
| `SESSION_END` event | amplifier-core | Kernel event (mechanism) |
| Bundle validation strict mode | amplifier-foundation | Shared validation (mechanism) |
| InterfaceAdapter class | amplifier-foundation | Shared library (mechanism) |
| Cache TTL + auto-refresh | amplifier-foundation | Shared infrastructure (mechanism) |
| Pre-flight checks | amplifier-distro (bundle) | Policy decision |
| Session handoff generation | amplifier-distro (bundle) | Policy decision |
| Morning brief recipe | amplifier-distro (bundle) | Workflow |
| Friction detection recipe | amplifier-distro (bundle) | Workflow |
| `amp env` subcommands | amplifier-app-cli | CLI surface |
| TUI session_manager rewrite | amplifier-tui | Interface fix |
| Voice hardcoded extraction | amplifier-voice | Interface fix |

Source: `planning/10-project-structure.md:103-116`

---

## 11 Settled Conventions

Each convention eliminates a decision that would otherwise cost human attention.

| # | Convention | What It Eliminates | Source |
|---|-----------|-------------------|--------|
| 1 | All projects under `workspace_root` (default `~/dev/`) | "Where did I clone that?" / per-tool path config | `OPINIONS.md` Section 1 |
| 2 | GitHub handle is identity everywhere | Scattered identity config across tools | `OPINIONS.md` Section 2 |
| 3 | One memory location (`~/.amplifier/memory/`), YAML format | Per-tool memory stores, format confusion | `OPINIONS.md` Section 3 |
| 4 | Sessions are files at `~/.amplifier/projects/`, any interface can resume | Interface-specific session isolation | `OPINIONS.md` Section 4 |
| 5 | One bundle per user, validated before every session, errors loud | Silent failures, recurring config debugging | `OPINIONS.md` Section 5 |
| 6 | Interfaces are viewports into the same system | Per-interface worlds with separate state | `OPINIONS.md` Section 6 |
| 7 | API keys in env vars or `keys.yaml`, multi-provider assumed | Scattered key storage, single-provider assumption | `OPINIONS.md` Section 7 |
| 8 | Git-based updates, TTL cache, auto-refresh on error | Manual cache clearing, "have you tried..." debugging | `OPINIONS.md` Section 8 |
| 9 | Pre-flight on every session start, doctor for diagnostics | Problems discovered mid-session after wasting time | `OPINIONS.md` Section 9 |
| 10 | Static setup page with machine-parseable instructions | Tribal knowledge onboarding | `OPINIONS.md` Section 10 |
| 11 | All secrets in `keys.yaml`, all config in `distro.yaml` | Per-integration config files, scattered secrets | `OPINIONS.md` Section 11 |

---

## What This Document Does NOT Cover

- **How well the implementation matches these objectives.** That's a separate
  analysis. (See `responses/bundle-drift.md` for one example of drift.)
- **Whether these objectives are the right ones.** This document reconstructs
  intent, not evaluates it.
- **Current implementation status.** See `ROADMAP.md` and `TASKS.md` for that.
- **The server architecture.** The FastAPI server, plugin system, and bridge
  pattern are implementation choices. The objectives above are what those
  choices are supposed to serve.
