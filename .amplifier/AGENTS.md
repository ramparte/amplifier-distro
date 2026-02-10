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
Sam's local `~/.amplifier/` is NEVER touched by test activities.

| Environment | Purpose | Infrastructure |
|-------------|---------|----------------|
| **Docker Compose on WSL2** | Primary dev/test. Daily use. | Docker Desktop on WIN-DLPODL2CIJB |
| **DGX cluster (spark-1, spark-2)** | Headless CI/integration tests | NVIDIA DGX, local network, no monitors |
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

### DGX Machines

- **spark-1**: Primary headless test host
- **spark-2**: Overflow/parallel testing
- Access via `docker context create spark-1 --docker "host=ssh://sam@spark-1"`
- Code sync via rsync, SSH tunnels for web UIs
- Potential GitHub Actions self-hosted runner

### WSL2 LAN Exposure (for DGX access)

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

## Build Order (from ROADMAP.md)

Phase 0: ✅ distro.yaml schema -> base bundle -> amp-distro init/status -> pre-flight
Phase 1: ⚡ Memory standardization done. Handoff hooks need core PR.
Phase 2: ⚡ Bridge built in distro. Voice built as server app. TUI adapter pending.
Phase 3: ✅ Backup/restore/update/doctor/version all implemented.
Phase 4: ⏳ Setup website, containers, workflows

---

## Development Patterns

### Testing
- **836 tests**, all passing in ~13s
- Test runner: `uv run python -m pytest tests/ -x -q`
- Each new module gets a corresponding `tests/test_<name>.py`
- FastAPI apps tested via `TestClient` (no real server needed)
- Mocking pattern: `unittest.mock.patch` for external dependencies (git, gh, subprocess)

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
