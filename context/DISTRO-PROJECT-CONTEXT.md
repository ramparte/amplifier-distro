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

## Current Status (Updated Feb 9, 2026)

**Phase:** Overnight build COMPLETE. Server fully operational with all bridges,
memory, backup, diagnostics, and CLI tooling. 755 tests passing.

### Architecture Shift (Feb 8)

Sam's new vision: the distro is oriented around a **central server**. The
server hosts the web UI, config UI, installation wizard, and serves as the
Tailscale endpoint for backend services (Slack bridge, voice bridge). All
interfaces talk through the **Bridge API** to create sessions.

```
                     Tailscale
                        |
    +---------+   +-----v------+   +----------+
    | CLI/TUI |-->|            |<--| Slack    |
    +---------+   |  Distro    |   | Bridge   |
    +---------+   |  Server    |   +----------+
    | Voice   |-->|  (FastAPI) |   +----------+
    +---------+   |            |<--| Voice    |
    +---------+   |  /apps/    |   | Bridge   |
    | CarPlay |-->|  plugin    |   +----------+
    +---------+   |  system    |
                  +-----+------+
                        |
                  Bridge API
                        |
                  amplifier-foundation
```

Three foundational pieces were built (Feb 8):

1. **conventions.py** - The ONE immutable file. Defines every filename,
   path, and naming standard. This can never change (major version bump +
   migration required). Everything reads this.

2. **bridge.py** - The Bridge API (Interface Adapter). Protocol definition
   + LocalBridge implementation. The single interface through which ALL
   surfaces create and manage Amplifier sessions.

3. **server/** - FastAPI server with app/plugin system. Apps register
   routers and get mounted at `/apps/{name}/`. Example plugin included.
   Built-in routes: `/api/health`, `/api/config`, `/api/status`, `/api/apps`.

### What's done:

**Phase 0 (complete):**
- `distro.yaml` schema, config I/O, pre-flight checks (8), CLI (init/status/validate)
- Distro base bundle, Docker test environment, INSTRUCTIONS.md

**Phase 1 (complete):**
- Memory standardization to `~/.amplifier/memory/` with migration helper
- Acceptance tests: 46 tests (Phase 0 + Phase 1)

**Foundational Architecture (complete):**
- `conventions.py`: Immutable naming standards (filenames, paths, ports)
- `bridge.py`: AmplifierBridge protocol + LocalBridge implementation
- `server/app.py`: DistroServer with app/plugin discovery and registration
- `server/apps/example/`: Example app demonstrating plugin pattern
- `server/cli.py`: `amp-distro-server` entry point (host/port/reload)
- `pyproject.toml`: FastAPI + uvicorn deps, server entry point

**Overnight Build (Feb 9) - 9 tasks completed:**

- **T1: Server Robustness** - `daemon.py` (PID management, daemonize/stop),
  `startup.py` (structured JSON logging, key export, startup checks),
  systemd service file, CLI converted to click.Group with subcommands (+34 tests)
- **T2: Slack Bridge Fix** - Command routing fixed, session persistence
  added, Slack config module, setup module with guided onboarding (+29 tests)
- **T3: Dev Memory Integration** - `server/memory.py` MemoryService with
  remember/recall/work-status, memory API endpoints, web chat memory
  commands, Slack `/amp remember` and `/amp recall` commands (+69 tests)
- **T4: Voice Bridge** - `server/apps/voice/` with OpenAI Realtime API,
  WebRTC support, voice.html UI, full server app plugin (+28 tests)
- **T5: Settings UI** - Config editor API (`/api/config` POST),
  `/api/integrations` status endpoint, `/api/test-provider` connectivity
  test, settings web interface (+20 tests)
- **T6: Backup System** - `backup.py` with GitHub repo backup/restore,
  configurable backup repo, auto-backup support, CLI `backup` and
  `restore` commands (+41 tests)
- **T7: Doctor Command** - `doctor.py` with 13 diagnostic checks
  (config, memory, keys permissions, server, bundle cache, git, gh auth,
  Slack, voice, amplifier install, identity, workspace), auto-fix mode,
  JSON output, CLI `doctor` command (+46 tests)
- **T8: Docker Polish** - Healthcheck endpoint, non-root user, production
  entrypoint, deploy configuration (+5 tests)
- **T9: CLI Enhancements** - `update_check.py` (version detection, PyPI
  update check, self-update), `version` command with full environment
  info, `update` command, improved help with epilog (+31 tests)

Total: **836 tests passing** (up from 469 pre-build, then 755 after overnight build)

**PR #68** (bundle validation strict mode) was closed by upstream. The
branch and code exist at `ramparte/amplifier-foundation` on branch
`feat/bundle-validation-strict-mode`. May resubmit or discuss with robotdad.

### Server API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/health` | GET | Health check |
| `/api/config` | GET | Read distro config |
| `/api/config` | POST | Update distro config |
| `/api/status` | GET | Server status (uptime, apps, bridge) |
| `/api/apps` | GET | List registered app plugins |
| `/api/integrations` | GET | Integration status (Slack, voice, keys) |
| `/api/test-provider` | POST | Test provider API key connectivity |
| `/api/sessions` | GET | List sessions |
| `/api/sessions/create` | POST | Create new session |
| `/api/sessions/execute` | POST | Execute prompt in session |
| `/api/memory/remember` | POST | Store a memory entry |
| `/api/memory/recall` | GET | Query memory by text |
| `/api/memory/work-status` | GET | Get work log status |
| `/api/memory/work-log` | POST | Update work log |

### CLI Commands

| Command | Purpose |
|---------|---------|
| `amp-distro init` | Initialize distro (create config, bundle, workspace) |
| `amp-distro status` | Show environment health status |
| `amp-distro validate` | Validate distro config and bundle |
| `amp-distro doctor` | Run 13 diagnostic checks (--fix for auto-fix, --json) |
| `amp-distro backup` | Backup config to GitHub repo |
| `amp-distro restore` | Restore config from GitHub backup |
| `amp-distro version` | Show version info (distro, amplifier, Python, OS) |
| `amp-distro update` | Check for updates and self-update |

### Server App Plugins

| App | Path | Purpose |
|-----|------|---------|
| `example` | `/apps/example/` | Example plugin demonstrating the pattern |
| `install_wizard` | `/apps/install_wizard/` | Guided setup wizard |
| `slack` | `/apps/slack/` | Slack bridge (Socket Mode, commands, events, sessions) |
| `voice` | `/apps/voice/` | Voice bridge (OpenAI Realtime API, WebRTC) |
| `web_chat` | `/apps/web_chat/` | Web chat interface with polished UI |

### What's done (Feb 10):
1. **Bridge fully wired** - LocalBridge.create_session() integrates with
   amplifier-foundation (load_bundle + prepare + create_session).
2. **Session resume** - resume_session() finds sessions by ID/prefix,
   loads transcript history, and injects into new session context.
3. **Session handoffs** - end_session() writes handoff.md with session
   metadata. create_session() reads and injects previous handoff.
4. **Server auth** - Bearer token auth via distro.yaml `server.api_key`.
   Mutation endpoints protected; read-only endpoints open.
5. **Async safety** - Global mutable state protected with locks
   (asyncio.Lock for web_chat, threading.Lock for sync singletons).
6. **Exception handling** - Blind `except Exception: pass` reduced from
   52 to 14 instances. All remaining have proper logging.

### What's next:
1. **Setup website** - Static page with machine-readable instructions for
   agent-driven setup.
2. **Interface installers** - `amp distro install tui|voice|gui`
3. **Voice bridge session integration** - Wire voice bridge to real
   Amplifier sessions via the Bridge API.

### Open items:
- PR #68 closed - need to discuss with upstream or re-approach
- Setup website not built yet
- TUI adapter pending

---

## How to Continue This Work

1. **Read this file first.** It has the full picture.
2. **Read conventions.py** for the immutable naming standards.
3. **Read bridge.py** for the session creation API contract.
4. **Read server/app.py** for the plugin system.
5. **Read OPINIONS.md** for shared conventions.
6. **Read ROADMAP.md** for the phase-level plan.

### Development workflow:
- **Docker test env**: `docker compose --profile cli up -d` then `docker compose exec cli bash`
- **Run tests**: `uv run python -m pytest tests/ -x -q` (836 tests, ~13s)
- **Start server**: `amp-distro-server --port 8400 --reload`
- **amp-distro CLI**: Install with `uv pip install -e .` in a venv
- **Add a server app**: Create `server/apps/myapp/__init__.py` with a `manifest`

### File map (key source files):
```
src/amplifier_distro/
  conventions.py       # IMMUTABLE naming standards
  bridge.py            # Session creation API (AmplifierBridge protocol)
  bridge_protocols.py  # Bridge protocol definitions
  schema.py            # distro.yaml Pydantic models
  config.py            # Config load/save
  preflight.py         # Health checks (pre-flight)
  migrate.py           # Memory migration helper
  cli.py               # amp-distro CLI (init, status, validate, doctor, backup, restore, version, update)
  backup.py            # Backup/restore to GitHub repo
  doctor.py            # 13 diagnostic checks with auto-fix
  update_check.py      # Version detection, PyPI update check, self-update
  bundle_composer.py   # Bundle composition helpers
  features.py          # Feature flags
  deploy.py            # Cloud deployment configuration
  docs_config.py       # Documentation configuration
  server/
    app.py             # DistroServer + plugin system + all API routes
    cli.py             # amp-distro-server CLI
    daemon.py          # PID file management, daemonize, stop process
    startup.py         # Structured logging, key export, startup checks
    memory.py          # MemoryService (remember, recall, work status)
    services.py        # Shared server services layer
    session_backend.py # Session backend for bridges
    apps/
      example/         # Example plugin app
      install_wizard/  # Guided setup wizard
      slack/           # Slack bridge (Socket Mode, commands, events, sessions, setup)
      voice/           # Voice bridge (OpenAI Realtime API, WebRTC)
      web_chat/        # Web chat interface
```

To pick up a specific task:
- Check this file's "What's next" section
- Check ROADMAP.md for phase-level tasks
- Each task has clear scope and exit criteria
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
- Q3 Memory location: MOVE to ~/.amplifier/memory/ (canonical). Migration helper
  created in migrate.py. Creates symlink from old location for backward compat.
  (Updated Feb 7 - reversed earlier decision to keep in place)
- Q4 Voice: lower priority installer, Phase 2+ 
- Q5 Team update coordination: float on @main for now, pin opt-in

### Open Design Questions (Still Open)

- Q2: Should `amp-distro` also be aliased as `amp distro`? (cosmetic)
- Q6: Session handoffs - what approach? Lighter (orchestrator:complete hook) or
  heavier (SESSION_END core PR)? Deferred to next session for discussion.
