# Amplifier Distro: Roadmap

A firm accounting of what exists, what's missing, and what we
build in what order to get to "one click install."

---

## What Exists Today (Inventory)

### Working and Stable

| Piece | Where | Status | Distro Role |
|-------|-------|--------|-------------|
| amplifier-core | microsoft/amplifier-core | Production | Engine (don't touch) |
| amplifier-foundation | microsoft/amplifier-foundation | Production | Bundle composition, utilities |
| amplifier-app-cli | microsoft/amplifier-app-cli | Production | Reference interface |
| Bundle system | foundation | Production | Config + composition |
| Agent system | foundation | Production | 16+ specialized agents |
| Session files | core | Production | transcript.jsonl, events.jsonl |
| Provider modules | microsoft/amplifier-module-* | Production | anthropic, openai, azure, etc |
| Tool modules | microsoft/amplifier-module-* | Production | bash, filesystem, web, etc |
| Team tracking | marklicata/amplifier-bundle-team-tracking | Production | Session sync + indexes |
| Recipes | microsoft/amplifier-bundle-recipes | Production | Multi-step workflows |
| GitHub CLI (gh) | External | Production | Identity + repo access |
| Memory system | community (dev-memory bundle) | Working | YAML-based persistent memory |

### Working but Fragile

| Piece | Where | Issue | Fix Needed |
|-------|-------|-------|------------|
| Personal bundles (my-amplifier) | Per-user | Silent include failures, syntax errors | Bundle validation strict mode |
| Bundle cache | ~/.amplifier/cache/ | Goes stale, no auto-refresh, manual clear needed | TTL + auto-refresh |
| amplifier-tui | samschillace/amplifier-tui | sys.path hack, session save bug, imports CLI internals | Rewrite on Interface Adapter |
| amplifier-voice | bkrabach/amplifier-voice | 7 hardcoded values, only works on one machine | Extract config to bundle |
| CarPlay | samschillace/carplay | Two competing implementations, neither works cleanly | Consolidate on programmatic API |
| Session continuity | N/A | Sessions start cold, no handoff between sessions | Auto-handoff generation |
| Attention firewall | bkrabach + samschillace | Works for WhatsApp, manual setup, no shared config | Integrate with distro config |

### Missing (Gaps)

| Piece | What It Does | Priority | Blocks |
|-------|-------------|----------|--------|
| **distro.yaml** | Central config file all tools read | Critical | Everything |
| **Interface Adapter** | One API for creating sessions from any interface | Critical | TUI, Voice, CarPlay fixes |
| **Bundle validation strict mode** | Errors not warnings for broken configs | Critical | Reliable startup |
| **Pre-flight checks** | Verify env, keys, bundle before session start | Critical | "It just works" |
| **Session handoffs** | Auto-summary at end, auto-inject at start | High | Session continuity |
| **`amp distro init`** | One-command setup | High | Onboarding |
| **`amp distro status`** | Health check dashboard | High | Self-diagnosis |
| **`amp distro install <interface>`** | Per-interface installer | Medium | Interface onboarding |
| **Setup website** | Machine-readable setup instructions | Medium | Agent-driven setup |
| **Idea funnel** | Capture, score, surface ideas | Medium | Task prioritization |
| **Friction detection** | Auto-analyze sessions for attention drains | Low (later) | Self-improvement loop |
| **Morning brief** | Daily context summary on session start | Low (later) | Proactive context |

---

## The Path to One-Click Install

### What "One Click" Actually Means

A new team member runs one command and gets:
1. Amplifier CLI installed
2. Identity detected (GitHub handle)
3. Workspace directory set
4. Personal bundle created (inheriting distro base)
5. API keys prompted and verified
6. Memory system initialized
7. Pre-flight passing
8. First session works

Then optionally:
9. `amp distro install tui` - TUI interface
10. `amp distro install voice` - Voice interface
11. Team tracking enabled

### What Must Be True

For one-click to work, each of these must be independently solid:

```
One-Click Install
  |
  +-- distro.yaml schema (config everything reads)
  |     |
  |     +-- workspace_root
  |     +-- identity (github_handle, git_email)
  |     +-- bundle config (active bundle, strict mode)
  |     +-- cache config (TTL, auto-refresh)
  |     +-- preflight config
  |
  +-- distro base bundle (what you get by default)
  |     |
  |     +-- agents (zen-architect, explorer, bug-hunter, etc)
  |     +-- memory behavior
  |     +-- team tracking behavior (opt-in)
  |     +-- session handoff behavior
  |     +-- providers (anthropic + openai, user configures keys)
  |
  +-- pre-flight system
  |     |
  |     +-- env var check
  |     +-- bundle validation
  |     +-- provider key verification
  |     +-- cache freshness check
  |
  +-- Interface Adapter
  |     |
  |     +-- create_session(bundle, cwd, overrides)
  |     +-- cleanup(session) with handoff generation
  |     +-- config reader (reads distro.yaml)
  |
  +-- interface installers
        |
        +-- amp distro install tui
        +-- amp distro install voice
        +-- amp distro install gui
```

---

## Build Phases

### Phase 0: Ground Truth (Week 1) ✅ COMPLETE
**Goal:** One config file. One base bundle. Validated startup.

| Task | What | Effort | Delivered By | Status |
|------|------|--------|-------------|--------|
| Define distro.yaml schema | YAML schema for central config | 1 day | This repo | ✅ Done |
| Create distro base bundle | Bundle that includes standard agents, memory, handoffs | 2 days | This repo | ✅ Done |
| Bundle validation strict mode | Promote include warnings to errors in foundation | 2-3 days | amplifier-foundation PR | ⚠️ PR #68 closed by upstream |
| Pre-flight check (basic) | Check env vars + bundle health before session start | 2-3 days | This repo | ✅ Done (8 checks) |

**Exit criteria:** Starting a session with a broken bundle gives
a clear error. Starting with a valid bundle and valid keys works
every time. distro.yaml exists and is read by pre-flight.

### Phase 1: Session Continuity (Week 2-3) - PARTIAL
**Goal:** Sessions carry context forward automatically.

| Task | What | Effort | Delivered By | Status |
|------|------|--------|-------------|--------|
| SESSION_END kernel event | Emit event on session cleanup | 1-2 days | amplifier-core PR | ⏳ Not started (requires core PR) |
| Auto-handoff generation | Hook writes handoff.md on SESSION_END | 3-4 days | This repo or foundation | ⏳ Not started (depends on SESSION_END) |
| Handoff injection on start | Inject previous handoff as system context | 2-3 days | This repo or foundation | ⏳ Not started |
| Memory location standardization | Move to ~/.amplifier/memory/, update all references | 1 day | Config change | ✅ Done (migrate.py + MemoryService) |

**Exit criteria:** End a session, start a new one in same project,
the new session "knows" what happened in the previous one without
being told.

### Phase 2: Interface Adapter (Week 3-4) - PARTIALLY BYPASSED
**Goal:** One way to create sessions from any interface.

| Task | What | Effort | Delivered By | Status |
|------|------|--------|-------------|--------|
| Interface Adapter library | create_session(), cleanup(), config reader in foundation | 2-3 days | amplifier-foundation PR | ✅ Done (bridge.py in distro) |
| TUI rewrite on adapter | Replace sys.path hack with adapter usage | 1 week | amplifier-tui PR | ⏳ Not started |
| Voice config extraction | Move hardcoded values to bundle, use adapter | 1 week | amplifier-voice PR | ✅ Bypassed: voice bridge built as server app plugin |
| CarPlay consolidation | Delete subprocess bridge, use adapter | 3-4 days | carplay PR | ⏳ Not started |

**Note:** The server-centric architecture shift (Feb 8) changed the approach.
Voice is now a server app plugin (`server/apps/voice/`) using the OpenAI
Realtime API with WebRTC, rather than a standalone interface needing adapter
integration. The same pattern applies to Slack (`server/apps/slack/`).

**Exit criteria:** TUI, Voice, and CarPlay all create sessions
through the same adapter. No sys.path hacks, no hardcoded configs.
`uv pip install -e .` works for all three.

### Phase 3: Setup Tool (Week 4-5) - MOSTLY COMPLETE
**Goal:** One-command setup for new users.

| Task | What | Effort | Delivered By | Status |
|------|------|--------|-------------|--------|
| `amp distro init` | Detect platform, identity, providers; create distro.yaml and personal bundle | 3-4 days | This repo | ✅ Done |
| `amp distro status` | Health report: identity, providers, bundle, cache | 2-3 days | This repo | ✅ Done |
| `amp distro doctor` | 13 diagnostic checks with auto-fix | 2-3 days | This repo | ✅ Done (overnight build T7) |
| `amp distro backup/restore` | Config backup to GitHub, restore from backup | 2-3 days | This repo | ✅ Done (overnight build T6) |
| `amp distro version/update` | Version info, update check, self-update | 1-2 days | This repo | ✅ Done (overnight build T9) |
| `amp distro install <interface>` | Per-interface installer (clone, deps, config, smoke test) | 1 week | This repo (recipes) | ⏳ Not started |
| Setup website (v1) | Static page with machine-readable instructions | 2-3 days | GitHub Pages | ⏳ Not started |

**Exit criteria:** A new team member runs `amp distro init`,
answers 3 questions (workspace, anthropic key, openai key),
and has a working environment. `amp distro install tui` gives
them the TUI. The setup website exists and an agent can read it.

### Phase 4: Workflows (Week 6+)
**Goal:** The system starts working FOR you, not just WITH you.

| Task | What | Effort | Delivered By |
|------|------|--------|-------------|
| Morning brief recipe | Context summary on session start | 3-4 days | This repo |
| Idea funnel | Capture, score, surface ideas | 1 week | This repo |
| Friction detection | Analyze sessions for attention drains | 1 week | This repo |
| Attention firewall integration | Read firewall config from distro.yaml | 2-3 days | Attention firewall repo |

**Exit criteria:** Starting a session shows what happened since
last time. "idea: X" captures and scores ideas. Weekly friction
report identifies top 3 attention drains.

---

## Overnight Build (Feb 9) - Accelerated Delivery

The overnight autonomous build completed 9 tasks in a single session,
jumping ahead on Phase 2-3 items and adding new capabilities not in
the original roadmap. 755 tests passing (up from 469).

| Task | What Was Built | Tests Added |
|------|---------------|-------------|
| T1: Server Robustness | daemon.py, startup.py, systemd service, structured logging | +34 |
| T2: Slack Bridge Fix | Command routing, session persistence, config module, setup | +29 |
| T3: Dev Memory | MemoryService, memory API, web chat + Slack memory commands | +69 |
| T4: Voice Bridge | OpenAI Realtime API, WebRTC, voice.html UI, server app | +28 |
| T5: Settings UI | Config editor API, integrations status, provider testing | +20 |
| T6: Backup System | GitHub repo backup/restore, auto-backup, CLI commands | +41 |
| T7: Doctor Command | 13 diagnostic checks, auto-fix, JSON output | +46 |
| T8: Docker Polish | Healthcheck, non-root user, production entrypoint | +5 |
| T9: CLI Enhancements | Version info, PyPI update check, self-update | +31 |

New modules added: `backup.py`, `doctor.py`, `update_check.py`,
`server/daemon.py`, `server/startup.py`, `server/memory.py`

---

## Existing Pieces -> Distro Component Mapping

Where each existing piece lands in the distro:

```
DISTRO BASE BUNDLE
  includes:
    # From amplifier-foundation (already exist)
    - foundation:behaviors/agents          # 16+ agents
    - foundation:behaviors/streaming-ui    # Streaming output
    - foundation:behaviors/redaction       # Secret redaction

    # From community/ecosystem (already exist)
    - dev-memory:behaviors/memory          # Persistent memory
    - team-tracking:behaviors/tracking     # Team sync (opt-in)

    # NEW - built for distro
    - distro:behaviors/preflight           # Pre-flight checks
    - distro:behaviors/handoff             # Session handoffs
    - distro:behaviors/health              # Health monitoring

  providers:
    - provider-anthropic                   # Already exists
    - provider-openai                      # Already exists

  tools:
    - tool-bash                            # Already exists
    - tool-filesystem                      # Already exists
    - tool-web                             # Already exists
    - tool-task                            # Already exists (agent delegation)
    - tool-recipes                         # Already exists
    - tool-skills                          # Already exists
```

The distro base bundle is primarily COMPOSITION of existing pieces,
plus 3 new behaviors (preflight, handoff, health). Most of the work
is not building new things - it's wiring existing things together
reliably.

---

## The Interface Awareness Model

How interfaces stay aware of each other (without tight coupling):

```
~/.amplifier/
  distro.yaml              # The one config file
    workspace_root: ~/dev
    identity: { github_handle, git_email }
    bundle: { active, strict }
    cache: { max_age_hours }
    interfaces:
      cli: { installed: true }
      tui: { installed: true, path: ~/dev/amplifier-tui }
      voice: { installed: true, path: ~/dev/amplifier-voice }
      gui: { installed: false }

  memory/
    memory-store.yaml       # Shared across all interfaces
    work-log.yaml

  projects/
    <project>/
      <session>/            # Sessions from ANY interface
        transcript.jsonl
        session-info.json   # Includes: which interface created it
        handoff.md          # Read by ANY interface on next start
```

Interfaces are aware of each other through:
1. **distro.yaml** - lists installed interfaces
2. **Shared sessions** - any interface can see/resume any session
3. **Shared memory** - any interface can read/write memory
4. **Shared handoffs** - any interface benefits from handoff context

They are NOT coupled to each other. The TUI doesn't import from
Voice. Voice doesn't import from CLI. They share state through
the filesystem, mediated by the conventions in OPINIONS.md.

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Interface Adapter requires core changes | High - slows everything | Design adapter to work with current core API first |
| Bundle validation breaks existing bundles | Medium - annoys users | Strict mode is opt-in initially, default later |
| Memory location migration breaks existing stores | Low - one-time | Migration script in `amp distro init` |
| Interface authors don't adopt adapter | High - fragmentation continues | Make adapter so much easier that not using it is harder |
| Setup website content goes stale | Medium - bad onboarding | Generate from distro.yaml schema + test in CI |
| Phase 2 (interfaces) takes longer than planned | Medium - delays setup tool | Setup tool can work with CLI-only initially |

---

## Success Metrics

### Phase 0 (end of week 1) ✅
- [x] Zero silent bundle failures in any team member's config
- [x] distro.yaml exists and is read by at least one tool

### Phase 1 (end of week 3) - Partial
- [ ] Session handoffs work end-to-end (end -> file -> inject -> awareness)
- [x] Memory location is standardized (migrate.py + MemoryService)

### Phase 2 (end of week 4) - Partial
- [ ] TUI creates sessions without sys.path hacks
- [x] Voice starts with any user's bundle config (via server app plugin)
- [ ] At least 2 interfaces can resume the same session

### Phase 3 (end of week 5) - Mostly Done
- [x] New team member setup: <10 minutes, <5 manual steps (init + install wizard)
- [x] `amp distro status` shows green for all core components
- [x] `amp distro doctor` runs 13 diagnostic checks with auto-fix
- [x] `amp distro backup/restore` works with GitHub repos
- [x] `amp distro version/update` detects and applies updates

### Phase 4 (end of week 8)
- [ ] Morning brief runs without manual trigger
- [ ] Friction report identifies real issues
- [ ] At least one auto-fix has been proposed and applied

### North Star
**Time from "I want to use Amplifier" to "working session with
my preferred interface" < 10 minutes, with zero tribal knowledge
required.**
