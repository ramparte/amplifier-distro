# Amplifier Distro - Agent Notes

## Project Summary

Building an opinionated Amplifier distribution (Linux distro sense). All planning
docs are in `planning/`, design decisions in `OPINIONS.md`, roadmap in `ROADMAP.md`,
full implementation spec in `IMPLEMENTATION.md`, and session-resumption context in
`context/DISTRO-PROJECT-CONTEXT.md`. Read that context file first.

**Status:** Overnight build COMPLETE (Feb 9). Server fully operational with Slack bridge,
voice bridge, memory, backup, diagnostics, and CLI tooling. **836 tests pass.**
Session resume, handoff generation, server auth, and async safety added (Feb 10).

---

## Development & Testing Environment

### Strategy: Three Environments

We use Docker Compose as the primary mechanism for isolated development and testing.
Your local `~/.amplifier/` is NEVER touched by test activities.

| Environment | Purpose | Infrastructure |
|-------------|---------|----------------|
| **Docker Compose on WSL2** | Primary dev/test. Daily use. | Windows host with Docker Desktop |
| **Headless CI hosts** | Headless CI/integration tests | NVIDIA DGX or equivalent, local network, no monitors |
| **Win32 test tenant** | Windows-native testing (Phase 2+) | Admin access available |

### Docker Compose Profiles

```bash
docker compose --profile cli up           # Just CLI surface
docker compose --profile gui up           # Web GUI surface
docker compose --profile all up           # All surfaces
docker compose --profile agent-test up    # Automated agent tests
docker compose --profile human-test up    # Interactive testing with noVNC
```

### Insulation Model

- **Source code**: Bind-mounted (live editing)
- **~/.amplifier/**: Named Docker volume (isolated, ephemeral)
- **API keys**: `.env.test` (committed, fake) + `.env.local` (gitignored, real)
- **Teardown**: `docker compose down -v` wipes all state cleanly

### Human Interactive Testing

- CLI/TUI: `docker compose exec cli bash` for direct terminal access
- GUI: Port-forwarded to `localhost:8080`, open in Windows browser
- Voice: noVNC container at `localhost:6901` for full Linux desktop in-browser
- PulseAudio forwarding from WSLg for real microphone testing

### Agent Automated Testing

- Playwright in Docker for browser automation (headless Chromium)
- Chrome `--use-fake-device-for-media-stream` for voice/WebRTC testing
- Testcontainers-Python for programmatic container management
- Textual Pilot API for TUI headless testing

### Secondary Test Hosts (optional)

- Headless hosts can be added via `docker context create <host> --docker "host=ssh://user@host"`
- Code sync via rsync, SSH tunnels for web UIs
- Can be configured as GitHub Actions self-hosted runners

### WSL2 LAN Exposure (for remote host access)

Use PowerShell port forwarding to make container services accessible on LAN:
```bash
# scripts/expose-to-lan.sh handles this
```

---

## Testing Tools

### amplifier-bundle-browser (ramparte/amplifier-bundle-browser)

**Token-efficient browser automation for AI agents.** Wraps Vercel Labs' `agent-browser`
CLI. 93% token reduction vs raw Playwright MCP (Snapshot + Refs system: ~700 tokens/page
vs ~10,000).

- **Install**: `npm install -g agent-browser && agent-browser install --with-deps`
- **Key capability**: `snapshot -i --json` returns compact interactive element refs (`@e1`, `@e2`)
- **Commands**: open, click, fill, type, screenshot, pdf, trace, wait, get text/value/html
- **Sessions**: `--session <name>` for isolated browser instances
- **Headed mode**: `--headed` for visual debugging
- **CDP attach**: `connect <port>` to attach to running Chrome
- **10 workflow patterns**: UX testing, multi-page forms, auth, scraping, visual regression, etc.
- **Docker**: Needs Node.js + Chromium. Headless default (no X server needed).
- **Best for**: GUI/Web surface testing. NOT for CLI, TUI (native), or Voice.

### amplifier-ux-analyzer (ramparte/amplifier-ux-analyzer)

**Computer vision tool for UI screenshot analysis.** Uses OpenCV, scikit-learn, EasyOCR
to produce structured JSON descriptions of what's on screen.

- **Install**: `./setup-ux-analyzer.sh` (handles system deps + Python venv)
- **CLI**: `python ux-analyzer.py screenshot.png -o analysis.json -v annotated.png`
- **Outputs**: Color palettes, layout regions, UI element detection, OCR text extraction
- **Performance**: ~3-6s per screenshot (CPU), GPU accelerates OCR 10-50x
- **Docker**: All deps headless-compatible. Pre-bake EasyOCR models (~100MB).
- **Best for**: GUI visual regression, TUI screenshot analysis (with Xvfb), design validation.

### Combined Workflow

```
1. CAPTURE  -> agent-browser screenshot app.png
2. ANALYZE  -> python ux-analyzer.py app.png -o analysis.json
3. VALIDATE -> compare analysis.json against expected-spec.json
4. INTERACT -> agent-browser click @e1 (fix/retry using refs)
```

---

## Testing Pyramid

```
         /\
        /  \     E2E (agent-browser + ux-analyzer, real browsers)
       /    \    - GUI workflows, voice bridge, visual regression
      /------\
     /        \   Integration (Testcontainers, Docker Compose)
    /          \  - Session handoff, cross-surface state, config propagation
   /------------\
  /              \  Component (Textual Pilot, FastAPI TestClient)
 /                \ - TUI interactions, API endpoints, bundle loading
/------------------\
        Unit         - Core logic, distro.yaml parsing, pre-flight checks
```

---

## Key Files

| File | Purpose |
|------|---------|
| `Dockerfile.dev` | Development image (Ubuntu + uv + tools) |
| `docker-compose.yml` | All services and profiles |
| `.devcontainer/devcontainer.json` | VS Code dev container config |
| `scripts/test-env.sh` | Environment lifecycle (up/down/reset/snapshot) |
| `.env.test` | Safe test env vars (committed) |
| `.env.local` | Real API keys (gitignored) |

---

## Source Modules

### Core (`src/amplifier_distro/`)

| Module | Purpose |
|--------|---------|
| `conventions.py` | IMMUTABLE naming standards (filenames, paths, ports) |
| `schema.py` | distro.yaml Pydantic models |
| `config.py` | Config load/save |
| `preflight.py` | Pre-flight health checks (8 checks) |
| `bridge.py` | AmplifierBridge protocol + LocalBridge implementation |
| `bridge_protocols.py` | Bridge protocol type definitions |
| `cli.py` | CLI commands: init, status, validate, doctor, backup, restore, version, update |
| `backup.py` | Backup/restore to GitHub repo with auto-backup |
| `doctor.py` | 13 diagnostic checks with auto-fix mode |
| `update_check.py` | Version detection, PyPI update check, self-update |
| `migrate.py` | Memory location migration helper |
| `bundle_composer.py` | Bundle composition helpers |
| `features.py` | Feature flags |
| `deploy.py` | Cloud deployment configuration |
| `docs_config.py` | Documentation configuration |

### Server (`src/amplifier_distro/server/`)

| Module | Purpose |
|--------|---------|
| `app.py` | DistroServer + plugin system + all API routes |
| `cli.py` | `amp-distro-server` entry point (host/port/reload) |
| `daemon.py` | PID file management, daemonize, stop process |
| `startup.py` | Structured JSON logging, key export, startup checks |
| `memory.py` | MemoryService (remember, recall, work-status) |
| `services.py` | Shared server services layer |
| `session_backend.py` | Session backend for bridges |

### Server Apps (`src/amplifier_distro/server/apps/`)

| App | Purpose |
|-----|---------|
| `example/` | Example plugin demonstrating the app pattern |
| `install_wizard/` | Guided setup wizard |
| `slack/` | Slack bridge (Socket Mode, commands, events, sessions, setup, simulator) |
| `voice/` | Voice bridge (OpenAI Realtime API, WebRTC, voice.html UI) |
| `web_chat/` | Web chat interface with polished UI |

---

## Local Dev: Install & Run

```bash
# Editable install with ALL extras (Slack, email, aiohttp — never omit [all]):
uv tool install -e ".[all]" path/to/amplifier-distro

# Start server (auto-loads .env from project root):
amp-distro-server --port 8400
```

**Never use** `uv tool install .` (non-editable) or `uv tool install -e .` (misses extras — Slack won't connect).

### Environment

Tokens live in `.env` at the project root. The server auto-loads this on startup — no `source`, no `keys.yaml` needed.

For Socket Mode to activate, `~/.amplifier/distro.yaml` must have:
```yaml
slack:
  socket_mode: true
```
Without this, the server always falls back to simulator mode regardless of tokens being present.

If server shows **"simulator mode"**: check `socket_mode: true` in `distro.yaml` first, then confirm `.env` is present and populated.

---

## Development Workflow

Work in structured mode cycles — always follow this sequence:

1. **`/brainstorm`** — root cause analysis, issue scoping, PR/issue overlap check before any code
2. **`/write-plan`** — task breakdown, TDD plan saved to `docs/plans/YYYY-MM-DD-<slug>.md`
3. **`/execute-plan`** — subagent TDD: implement → spec-review → code-quality-review (parallel) → next task
4. **`/verify`** — full test suite (`pytest -q`, no `-x`), static analysis, compare against pre-existing failure baseline
5. **`/finish`** — summary, squash merge via `foundation:git-ops`, delete branch

**Mode transitions:** Switch modes manually. Never call the `mode` tool from within a mode — it will be blocked. Say "switch to X with `/mode X`" instead.

**PRs:** Always squash merge. Delegate all git/PR work to `foundation:git-ops`.

---

## Slack Bridge Architecture (key facts)

- Session routing key: `channel_id:thread_ts` (NOT bare `channel_id` — see issue #54)
- `SlackSessionManager` → `server/apps/slack/sessions.py`
- Thread routing wired in `server/apps/slack/events.py` via `_handle_command_message()`
- `rekey_mapping()` called after `post_message()` returns thread `ts`
- Open issues: #31 (zombie mappings), #49 (SurfaceSessionRegistry refactor — will need `rekey_mapping()` translation), #53 (resume CWD)

---

## Build Order (from ROADMAP.md)

Phase 0: ✅ distro.yaml schema -> base bundle -> amp-distro init/status -> pre-flight
Phase 1: ⚡ Memory standardization done. Handoff hooks need core PR.
Phase 2: ⚡ Bridge built in distro. Voice built as server app. TUI adapter pending.
Phase 3: ✅ Backup/restore/update/doctor/version all implemented.
Phase 4: ⏳ Setup website, containers, workflows

---

## Development Patterns

### Testing
- **1000+ tests** (~10s)
- Test runner: `uv run python -m pytest tests/ -q` (no `-x` — always run full suite to see complete failure set)
- Use `-x` only during active development to fail fast, never for final verify pass
- Each new module gets a corresponding `tests/test_<name>.py`
- FastAPI apps tested via `TestClient` (no real server needed)
- Mocking pattern: `unittest.mock.patch` for external dependencies (git, gh, subprocess)

**Known pre-existing failures (not regressions — as of 2026-02-19):**
- `test_dockerfile_has_nonroot_user` — Dockerfile intentionally runs as root
- `TestSocketModeDedup` (2 tests) — require `aiohttp`; only present if installed with `[all]`
- `TestGetIntegrations` (7 tests) — `AttributeError` in `app.py:334`, pre-existing bug

Baseline: **8 failures expected** on clean `main`. Compare against this before investigating.

### Server App Plugin Pattern
New server apps follow this pattern:
1. Create `server/apps/<name>/__init__.py`
2. Define a `manifest` (AppManifest) with name, prefix, version, description
3. Create a FastAPI router
4. The server auto-discovers and mounts at `/apps/<name>/`

### CLI Command Pattern
CLI uses `click.Group` with individual commands. Each command:
1. Reads config via `config.py`
2. Performs its action
3. Outputs via `click.echo()` with Rich formatting where appropriate
4. Returns exit code 0 on success, 1 on failure

---

## Markdown Document Catalog

44 markdown files across the project. Quick reference for what lives where.

### Root (`/`) — 6 files

| File | Contents |
|------|----------|
| `README.md` | Project overview: 4 commands, install methods, Ring 1/2/3 orientation |
| `OPINIONS.md` | 11 opinionated conventions the distro enforces, with rationale for each |
| `ROADMAP.md` | 5-phase build plan, component inventory, risk register, success metrics |
| `IMPLEMENTATION.md` | Deep technical design: all interfaces, machine-independence, update model, UX flows |
| `INSTRUCTIONS.md` | Contributor guide: `src/` boundary, Docker Compose, API keys, commit conventions |
| `TASKS.md` | Task tracker: DISTRO-001–018, ownership map, backlog, completed history |

### `.amplifier/` — 2 files

| File | Contents |
|------|----------|
| `AGENTS.md` | This file. Agent notes, dev environment, module inventory, workflow, architecture |
| `recipes/README.md` | E2E browser-test recipe system: pattern, available recipes, approval gates |

### `context/` — 5 files

| File | Contents |
|------|----------|
| `DISTRO-PROJECT-CONTEXT.md` | **Primary session-resumption file** — team roster, repos, architecture, build status, what to work on next |
| `OVERNIGHT-BUILD.md` | Orchestrator instructions for the Feb 9 autonomous build (tasks T1–T9) |
| `OVERNIGHT-BUILD-STATUS.md` | Live log from that build — all 10 tasks DONE, test count 469→755, commit hashes |
| `OVERNIGHT-BUILD-RESUME.md` | Auto-generated resume instructions after restart #3 at 03:53 AM |
| `SLACK-BRIDGE-CONTEXT.md` | Slack bridge reference: 3 operating modes, architecture diagram, all 13 source files, open issues |

### `docs/` — 1 file

| File | Contents |
|------|----------|
| `SLACK_SETUP.md` | Step-by-step guide for creating and configuring a Slack app |

### `docs/plans/` — 11 files

All TDD implementation plans (failing-test-first, exact file paths, verification commands):

| File | Contents |
|------|----------|
| `2026-02-23-distro-refactor.md` | Slim the distro: delete dead modules, shrink `distro.yaml`, clean public API |
| `2026-02-19-web-chat-session-list.md` | Add session list & resume to web chat UI |
| `2026-02-19-web-chat-resume-llm-context.md` | Fix session resume so LLM gets full transcript after restart |
| `2026-02-19-server-concurrency.md` | Fix 3 concurrency hazards (issue #57): lock narrowing, ACK-before-task, per-session queues |
| `2026-02-18-slack-session-working-dir.md` | Wire `default_working_dir` from `distro.yaml` into Slack sessions (issue #34) |
| `2026-02-18-session-cwd-persistence.md` | Persist `working_dir` in `session-info.json` to prevent duplicate dirs on resume (issue #53) |
| `2026-02-18-fix-zombie-sessions-and-test-gaps.md` | Fix Slack zombie session bug (issue #31) |
| `2026-02-18-fix-thread-routing-issue-54.md` | Fix thread routing cross-contamination with `rekey_mapping()` (issue #54) |
| `2026-02-17-transcript-persistence.md` | Write `transcript.jsonl` incrementally for session resume after restart |

### `notes/` — 1 file

| File | Contents |
|------|----------|
| `2026-02-06-workflow-techniques.md` | Field notes from AI practitioner groups: durable specs, commit-time review, multi-agent patterns |

### `planning/` — 14 files

Original Feb 6 research corpus plus later strategic documents:

| File | Contents |
|------|----------|
| `00-research-index.md` | Navigation index for the series; core thesis, key numbers |
| `01-friction-analysis.md` | 91-session analysis: 6 friction categories ranked by severity |
| `02-current-landscape.md` | Team inventory (17 accounts), all 8 interfaces, maturity assessments |
| `03-architecture-vision.md` | Three-ring architecture: Ring 1 (Foundation), Ring 2 (Interfaces), Ring 3 (Workflows) |
| `04-pieces-and-priorities.md` | Component maturity matrix: working vs. partial vs. needs building |
| `05-self-improving-loop.md` | Observe→Diagnose→Act→Verify loop for self-improving environment |
| `06-anthropic-patterns.md` | Lessons from Carlini's parallel-Claude C compiler: harness loop, task locking, etc. |
| `07-ring1-deep-dive.md` | Technical gap analysis for Ring 1: bundle validation, memory, session handoff, pre-flight |
| `08-ring2-deep-dive.md` | Technical gap analysis for Ring 2: per-interface session creation gaps |
| `09-setup-tool.md` | UX spec for `amp env init` / `amp env validate` with terminal mockups |
| `10-project-structure.md` | How to structure the project itself; original bundle directory design intent |
| `11-task-list.md` | Full ordered task list: Tier 0–3, status, effort, owner for each |
| `12-nexus-synthesis.md` | Reconciliation of `amplifier-nexus` vision with the distro model |
| `13-agent-shaped-os.md` | Strategic essay: "Agent-Shaped OS" — a parallel OS layer optimized for LLM agents |
| `TEAM-AND-ARCHITECTURE.md` | Living team/arch doc: 3-layer architecture, component inventory, decision record, per-member guidance |
| `contents.md` | Early scratchpad of what the distro should contain |
| `research-anthropic-compiler.md` | Raw saved text of the Anthropic engineering blog post about parallel Claudes |

### `responses/` — 2 files

| File | Contents |
|------|----------|
| `going-forward.md` | Post-analysis redesign: monolithic server → 3 ecosystem-native deliverables (decisions confirmed Feb 20) |
| `bundle-drift.md` | Precise analysis of how implementation drifted from the original bundle design intent |

### `specs/` — 1 file

| File | Contents |
|------|----------|
| `watchdog-and-service-spec.md` | 2,463-line TDD spec for Watchdog (process monitor/restart) and Platform Service (systemd/launchd boot services) |
