# Overnight Build: Amplifier Distro v1.0

You are an orchestrator session tasked with building a complete, working
Amplifier distribution. You have all night. Work methodically through the
task list, delegating to sub-agents for implementation, and validating
each piece before moving on.

**Owner**: Sam Schillace (samschillace)
**Repo**: /home/samschillace/dev/ANext/amplifier-distro
**Branch**: main (commit directly)
**Test command**: `uv run python -m pytest tests/ -x -q`
**Current test count**: 469 passing
**Server command**: `cd /home/samschillace/dev/ANext/amplifier-distro && uv run amp-distro-server --port 8400 --dev`

---

## Orchestrator Operating Rules

YOU ARE THE ORCHESTRATOR. Your job is to preserve context, hand out tasks,
monitor progress, persist state to files, and commit. Follow these rules:

### Rule 1: Don't do implementation work yourself
Delegate ALL implementation to sub-agents. Your context is precious --
it's the thread that ties the whole night together. If you burn it on
file reads and code edits, you'll get confused and lose track.

### Rule 2: Use separate verification sessions
After each task's implementation sub-agent finishes, start a SECOND
sub-agent session to verify the work. The verifier should:
- Run the full test suite
- Check that new tests were added
- Spot-check the implementation against the task spec
- Report pass/fail back to you

### Rule 3: Don't get stuck
If a particular task isn't completing:
- Sub-agent fails repeatedly (2+ attempts)
- Sub-agent runs for an unusually long time and seems stuck
- The task turns out to be underdefined or blocked on something external

Then: **Mark that task as problematic, write a note about WHY it's stuck
into context/OVERNIGHT-BUILD-STATUS.md, and MOVE ON to the next task.**

The goal is to get as much done overnight as possible. A task that takes
3 hours and still fails is worse than skipping it and finishing 4 other
tasks in that time.

### Rule 4: Persist your state
After each task (pass or fail), update `context/OVERNIGHT-BUILD-STATUS.md`
with:
- Task ID and name
- Status: DONE / FAILED / SKIPPED / PARTIAL
- What was accomplished
- What's left (if anything)
- Test count after this task

This file is your insurance policy. If you get compacted or confused,
read it to recover your place.

### Rule 5: Commit after each task
After each successful task:
1. Run ALL tests (must pass)
2. Commit with a clear message: `feat: T<N> - <description>`
3. Update OVERNIGHT-BUILD-STATUS.md
4. Move to next task

### Rule 6: Don't get confused
- Keep your messages short and focused
- Don't try to hold implementation details in your head
- If you're unsure what's been done, read OVERNIGHT-BUILD-STATUS.md
- If a sub-agent returns a confusing result, start a fresh one rather
  than trying to untangle it
- When in doubt, run the test suite -- green tests = progress

### Rule 7: Time budget
You have roughly 8 hours. Budget approximately:
- T1 (server robustness): 60 min
- T2 (Slack fix): 45 min
- T3 (memory): 45 min
- T4 (voice): 90 min
- T5 (settings UI): 45 min
- T6 (backup): 45 min
- T7 (doctor): 30 min
- T8 (Docker): 30 min
- T9 (CLI): 45 min
- T10 (docs): 15 min

If any task exceeds 2x its budget, it's stuck. Move on.

---

## Goal

By morning, Sam should be able to:

1. `amp-distro init` on a fresh machine and get a working environment
2. `amp-distro-server` starts a server with web chat, Slack bridge, settings UI
3. The server survives reboots (systemd service)
4. Dev memory works from any interface
5. Slack bridge is fully functional (all commands work, real Amplifier sessions)
6. Voice bridge has real STT/TTS pipeline via OpenAI Realtime API
7. Settings page lets you configure behaviors, see environment, manage integrations
8. Non-git state (config, memory, bundle registry) backs up to a configurable git repo
9. Docker container provides a clean test/demo environment
10. `amp-distro status` gives a complete health report
11. `amp-distro doctor` diagnoses and fixes common issues

---

## Architecture Reference

```
~/.amplifier/                     # AMPLIFIER_HOME
  distro.yaml                     # Central config (schema.py)
  keys.yaml                       # All secrets (chmod 600)
  settings.yaml                   # Amplifier CLI settings
  bundle-registry.yaml            # Registered bundles
  bundles/
    distro.yaml                   # The distro base bundle
  memory/
    memory-store.yaml             # Persistent memory
    work-log.yaml                 # Work tracking
  cache/                          # Bundle cache (auto-managed)
  projects/                       # Session storage
    <project>/
      <session>/
        transcript.jsonl
        events.jsonl
        session-info.json
        handoff.md                # Auto-generated on session end
  server/
    server.pid                    # PID file for daemon
```

```
Distro Server (FastAPI, port 8400)
  /api/health           - Health check
  /api/config           - Current config
  /api/status           - Full status report
  /api/apps             - List installed apps
  /api/sessions         - Session management
  /apps/install-wizard/ - Setup flow
  /apps/web-chat/       - Web chat interface
  /apps/slack/          - Slack bridge
  /apps/voice/          - Voice bridge
  /static/              - Static pages (quickstart, settings, wizard, slack-setup)
```

### Session Backend Architecture (ALREADY WORKING)

The session backend is fully implemented. DO NOT rewrite it.

```
Interface (Slack, Web Chat, Voice, CLI)
  -> SessionBackend protocol (server/session_backend.py)
    -> BridgeBackend (production: real Amplifier sessions)
       -> LocalBridge (bridge.py)
         -> amplifier-foundation (load_bundle, prepare, create_session)
    -> MockBackend (dev mode: canned responses for testing)
```

- `--dev` flag on server → MockBackend (for testing without API keys)
- No `--dev` flag → BridgeBackend → real Amplifier sessions
- The `services.py` singleton holds the backend, shared across all apps
- `BridgeBackend` is fully implemented in `server/session_backend.py`
- `LocalBridge` is fully implemented in `bridge.py`

---

## What Exists (Working)

| Component | Status | Files | Tests |
|-----------|--------|-------|-------|
| Schema (distro.yaml) | Complete | schema.py | test_phase0.py |
| Conventions | Complete, immutable | conventions.py | test_conventions.py (53) |
| Config I/O | Complete | config.py | test_phase0.py |
| Pre-flight checks | Complete (8 checks) | preflight.py | test_phase0.py |
| CLI (init/status/validate) | Complete | cli.py | test_phase0.py |
| Memory migration | Complete | migrate.py | test_phase1.py |
| Bridge protocol | Complete | bridge.py, bridge_protocols.py | test_bridge.py (28) |
| Server + app plugin system | Complete | server/app.py | test_server.py (37) |
| Install wizard (quickstart) | Complete | server/apps/install_wizard/ | test_install_wizard.py (32) |
| Web chat | Complete | server/apps/web_chat/ | test_web_chat.py (27) |
| Bundle composer | Complete | bundle_composer.py | test_bundle_composer.py (34) |
| Features/tiers system | Complete | features.py | test_features.py (27) |
| Deploy targets | Complete | deploy.py | test_deploy.py (21) |
| Static pages | Complete | quickstart.html, wizard.html, settings.html | test_server_static.py (9) |
| Slack bridge (core) | Working | server/apps/slack/ (13 files) | test_slack_bridge.py (96) |
| Slack setup page | Complete | slack-setup.html, setup.py | test_slack_bridge.py |
| Session backend | Complete | server/session_backend.py | test_services.py (22) |
| Server services | Complete | server/services.py | test_services.py |
| Voice app | Placeholder only | server/apps/voice/ | test_voice.py (17) |
| Docker (dev + prod) | Basic | Dockerfile.dev, Dockerfile.prod, docker-compose.yml | - |

---

## TASK LIST

### T1: Server Robustness (Foundation for everything)

**Goal**: Server starts reliably, survives reboots, has clean logging.

**T1.1: Server lifecycle management**
- Add `amp-distro-server start` (daemonize, write PID to conventions.SERVER_PID_FILE)
- Add `amp-distro-server stop` (read PID, send SIGTERM, clean up PID file)
- Add `amp-distro-server restart` (stop + start)
- Add `amp-distro-server status` (check PID, check port, report health)
- The existing `amp-distro-server` (no subcommand) should keep working as foreground mode
- Write PID file to `~/.amplifier/server/server.pid`
- Clean up PID file on graceful shutdown (signal handlers)

**T1.2: Systemd service file**
- Create `scripts/amplifier-distro.service` (systemd unit file)
- Create `scripts/install-service.sh` that copies service file, enables, starts
- Service should auto-restart on crash (Restart=on-failure)
- Service should start after network (After=network.target)
- ExecStart should use the full path to amp-distro-server

**T1.3: Server startup improvements**
- On boot, run pre-flight checks and log results
- If keys.yaml exists, export its values as environment variables so Amplifier
  sessions pick them up without requiring the user to set them in .bashrc
- Log server version, port, Tailscale URL (if available), loaded apps
- Structured logging (JSON to file, human-readable to console)

**T1.4: Tests**
- Test PID file creation/cleanup
- Test start/stop/restart commands
- Test service file is valid systemd syntax
- Target: +15 tests

**Files to create/modify**:
- `src/amplifier_distro/server/cli.py` (add start/stop/restart/status subcommands)
- `src/amplifier_distro/server/daemon.py` (new - PID file management, daemonization)
- `scripts/amplifier-distro.service` (new)
- `scripts/install-service.sh` (new)
- `tests/test_server.py` (add lifecycle tests)

---

### T2: Slack Bridge - Fix Command Routing

**Goal**: All 9 Slack commands work. Bridge is production-ready.

**Current issue**: `@SlackBridge list` doesn't respond, though `help` works.
The command parsing likely has a bug in how it extracts command names from
mentions.

**IMPORTANT**: The session backend (BridgeBackend, LocalBridge) is ALREADY
fully implemented and working. Real Amplifier sessions are created in
production mode (without --dev). DO NOT rewrite the backend. Just fix
the command routing.

**T2.1: Debug and fix command routing**
- Read `commands.py` and `events.py` carefully
- The issue is likely in `events.py:_dispatch_event()` or `commands.py:CommandHandler.handle()`
- When a message mentions the bot, it should extract the command text AFTER the mention
- The mention format in Slack is `<@U12345>` - make sure the regex strips this correctly
- Test all 9 commands: help, list, new, connect, disconnect, status, sessions, discover, config
- Add integration tests for each command through the event handler

**T2.2: Session persistence**
- SlackSessionManager currently uses in-memory dict (lost on restart)
- Add persistence to a JSON file at `~/.amplifier/server/slack-sessions.json`
- Load on startup, save on change
- Include session_id, channel_id, thread_ts, project, created_at, last_active

**T2.3: Tests**
- Integration tests for each command through the full event pipeline
- Test session persistence (save/load round-trip)
- Target: +20 tests

**Files to modify**:
- `src/amplifier_distro/server/apps/slack/events.py`
- `src/amplifier_distro/server/apps/slack/commands.py`
- `src/amplifier_distro/server/apps/slack/sessions.py`
- `tests/test_slack_bridge.py`

---

### T3: Dev Memory Integration

**Goal**: Memory works from any interface (web chat, Slack, CLI).

**T3.1: Memory service in server**
- Create `src/amplifier_distro/server/memory.py`
- Reads/writes `~/.amplifier/memory/memory-store.yaml` and `work-log.yaml`
- API: `remember(text)`, `recall(query)`, `work_status()`, `update_work_log(items)`
- Uses the same YAML format as the dev-memory bundle
- Auto-categorize memories (architecture, workflow, preference, etc.)
- Search by content, tags, and category

**T3.2: Memory API endpoints**
- `POST /api/memory/remember` - Store a memory
- `GET /api/memory/recall?q=<query>` - Search memories
- `GET /api/memory/work-status` - Current work log
- `POST /api/memory/work-log` - Update work log

**T3.3: Memory in web chat**
- Web chat should recognize "remember this: ..." and "what do you remember about ..."
- Route these through the memory service
- Display memory results inline in chat

**T3.4: Memory in Slack**
- Add `@amp remember <text>` command
- Add `@amp recall <query>` command
- Add `@amp work-status` command
- Route through the same memory service

**T3.5: Tests**
- Test memory CRUD operations
- Test API endpoints
- Test Slack commands for memory
- Target: +20 tests

**Files to create/modify**:
- `src/amplifier_distro/server/memory.py` (new)
- `src/amplifier_distro/server/app.py` (add memory routes)
- `src/amplifier_distro/server/apps/slack/commands.py` (add memory commands)
- `tests/test_memory.py` (new)

---

### T4: Voice Bridge - OpenAI Realtime API

**Goal**: Working voice interface using OpenAI Realtime API with WebRTC.

**Reference implementation**: ~/dev/ANext/amplifier-voice/
Brian's voice repo has a working implementation with the exact architecture
we want. Study it for patterns but implement within the distro server's
app plugin structure.

**Architecture**:
```
Browser (React-free, vanilla JS)
  -> WebRTC audio (24kHz PCM, Opus codec)
  -> OpenAI Realtime API (gpt-realtime model)
    -> Native speech-to-speech (no separate STT/TTS pipeline)
    -> Function calling for tools
  <- Audio response streamed back via WebRTC

Backend (FastAPI app plugin):
  GET  /session  - Creates ephemeral client_secret from OpenAI
  POST /sdp      - Exchanges WebRTC SDP offer/answer via OpenAI
  GET  /          - Voice UI page
  GET  /api/status - Voice service status
```

**Key insight**: The browser connects DIRECTLY to OpenAI via WebRTC for audio.
The backend only brokers the session creation (ephemeral token) and SDP
exchange. There is NO audio flowing through our server. This is much simpler
than a WebSocket relay approach.

**T4.1: Backend endpoints**
- `GET /session`: Call OpenAI `/v1/realtime/client_secrets` to get ephemeral token
  - Configure: model=gpt-realtime, voice from distro.yaml, tools from Amplifier
  - Return: `{client_secret: "ek_...", session_id: "..."}`
- `POST /sdp`: Relay SDP offer to OpenAI `/v1/realtime/calls`, return SDP answer
- Read OPENAI_API_KEY from keys.yaml (via environment)
- Tools: expose `delegate` tool so voice can use Amplifier agents

**T4.2: Voice UI page**
- Single HTML page (match existing design: dark theme, same CSS vars as quickstart.html)
- Microphone access via getUserMedia
- "Start Conversation" / "End Conversation" button
- WebRTC connection to OpenAI using ephemeral token
- Visual feedback: recording indicator, "thinking" state, response playing
- Text transcript display (OpenAI sends transcript events alongside audio)
- No React, no npm build step - vanilla JS only

**T4.3: Voice configuration**
- Add VoiceConfig to schema.py:
  ```python
  class VoiceConfig(BaseModel):
      voice: str = "ash"  # OpenAI voice: alloy, ash, ballad, coral, sage, verse
      model: str = "gpt-realtime"
  ```
- Read from distro.yaml `voice:` section
- OPENAI_API_KEY from keys.yaml

**T4.4: Tests**
- Test /session endpoint (mock OpenAI API)
- Test /sdp endpoint (mock OpenAI API)
- Test /api/status
- Test configuration loading
- Target: +15 tests

**Files to modify**:
- `src/amplifier_distro/server/apps/voice/__init__.py` (major rewrite)
- `src/amplifier_distro/schema.py` (add VoiceConfig)
- `tests/test_voice.py` (expand significantly)

**Dependencies to add to pyproject.toml**:
```toml
voice = [
    "httpx>=0.24.0",  # already a dep, but needed for OpenAI REST calls
]
```

**Fallback**: If OpenAI Realtime API integration proves too complex in one
pass, implement a status page that explains what's needed (API key, model
access) and provides a "test connection" button that validates the key works.
The key is making PROGRESS, not achieving perfection.

---

### T5: Settings & Configuration UI

**Goal**: Settings page is a real configuration tool, not just a status display.

**T5.1: Behavior management API**
- `GET /apps/install-wizard/features` already exists
- `PUT /apps/install-wizard/features/<id>` already exists to enable/disable
- The bundle_composer.py already handles adding/removing includes
- Verify the full flow: toggle in UI -> API call -> bundle YAML updated -> reflected on reload

**T5.2: Enhanced settings page**
- Show current distro.yaml values (workspace_root, identity, etc.)
- Editable fields for workspace_root, identity.github_handle
- Provider status with "Test Connection" buttons (hit provider API with a minimal request)
- Bundle contents viewer (show what behaviors are included)
- Memory stats (number of memories, last work log update)
- Server uptime and version

**T5.3: Integration management**
- Current: just a link to slack-setup.html
- Add: status indicators for each integration (configured/not configured/error)
- Show: Slack bridge status (connected/disconnected, session count)
- Show: Voice bridge status (configured/not configured)
- Each integration links to its setup page

**T5.4: Tests**
- Test settings API endpoints
- Test behavior toggle round-trip
- Target: +10 tests

**Files to modify**:
- `src/amplifier_distro/server/static/settings.html` (enhance significantly)
- `src/amplifier_distro/server/apps/install_wizard/__init__.py` (add config endpoints)
- `tests/test_install_wizard.py` (expand)

---

### T6: Backup System

**Goal**: Non-git state backs up to a configurable private GitHub repo.

**T6.1: Backup configuration**
- Add to schema.py:
  ```python
  class BackupConfig(BaseModel):
      repo_name: str = "amplifier-backup"  # configurable name
      repo_owner: str | None = None  # defaults to gh_handle
      auto: bool = False  # auto-backup on server shutdown
  ```
- User can configure different repo names (e.g., "my-amp-backup") in case
  "amplifier-backup" is already taken or they want multiple named backups
- Read from distro.yaml `backup:` section

**T6.2: Backup command**
- `amp-distro backup` creates/updates `<repo_owner>/<repo_name>` (private)
- `amp-distro backup --name <name>` overrides repo_name for one-off
- Uses `gh` CLI for repo creation and git operations
- Backs up (per conventions.py BACKUP_INCLUDE):
  - distro.yaml
  - memory/ (all files)
  - settings.yaml
  - bundle-registry.yaml
  - bundles/ (custom bundles)
- Does NOT back up (per conventions.py BACKUP_EXCLUDE):
  - keys.yaml (security - contains secrets)
  - cache/ (rebuilds automatically)
  - projects/ (team tracking handles this)
  - server/ (PID files, runtime state)

**T6.3: Restore command**
- `amp-distro restore` clones the backup repo and applies config
- `amp-distro restore --name <name>` to restore from a specific backup
- Prompts for keys.yaml values (since those aren't backed up)
- Runs `amp-distro init --restore` to set up from backup

**T6.4: Auto-backup**
- If `backup.auto: true` in distro.yaml, backup runs on server shutdown
- Simple: just git add + commit + push to the backup repo

**T6.5: Tests**
- Test backup file selection (includes/excludes)
- Test backup repo creation (mock gh CLI)
- Test restore flow
- Test configurable repo names
- Target: +15 tests

**Files to create/modify**:
- `src/amplifier_distro/backup.py` (new)
- `src/amplifier_distro/cli.py` (add backup/restore commands)
- `src/amplifier_distro/schema.py` (add BackupConfig)
- `tests/test_backup.py` (new)

---

### T7: Doctor Command

**Goal**: `amp-distro doctor` diagnoses and auto-fixes common problems.

**T7.1: Diagnostic checks**
- All pre-flight checks (already exist in preflight.py)
- Server running? (check PID file + port)
- Bundle cache stale? (check modification times vs TTL)
- Memory directory exists and is writable?
- Keys.yaml permissions correct (chmod 600)?
- Git configured? (git config user.name/email)
- GitHub CLI authenticated? (gh auth status)
- Slack bridge configured? (tokens in keys.yaml)
- Voice configured? (OPENAI_API_KEY in keys.yaml)
- Server apps all loading? (hit /api/apps if server running)

**T7.2: Auto-fix capabilities**
- Fix memory directory permissions
- Fix keys.yaml permissions (chmod 600)
- Clear and rebuild stale cache
- Create missing directories
- Restart server if crashed
- Re-run init if config missing

**T7.3: Report format**
- Green/yellow/red status for each check
- Auto-fix suggestions with `--fix` flag to apply
- Machine-readable JSON output with `--json`

**T7.4: Tests**
- Test each diagnostic check
- Test auto-fix actions
- Target: +15 tests

**Files to create/modify**:
- `src/amplifier_distro/doctor.py` (new)
- `src/amplifier_distro/cli.py` (add doctor command)
- `tests/test_doctor.py` (new)

---

### T8: Docker Container Polish

**Goal**: `docker compose up` gives a working demo environment.

**T8.1: Update docker-compose.yml**
- Ensure the `gui` profile starts the distro server on port 8400
- Server should auto-run `amp-distro init --non-interactive` on first boot
- Pre-populate with test API keys from `.env.local` (gitignored)
- Health check on /api/health

**T8.2: Update Dockerfile.prod**
- Multi-stage build is already there
- Add: health check instruction
- Add: non-root user
- Add: proper signal handling (exec form CMD)
- Install optional dependencies (slack, amplifier)

**T8.3: Docker entrypoint script**
- `scripts/docker-entrypoint.sh`
- Runs init if not already initialized
- Exports keys from environment
- Starts server in foreground
- Handles SIGTERM gracefully

**T8.4: Tests**
- Dockerfile builds successfully
- Container starts and passes health check
- Target: +5 tests (in test_deploy.py)

**Files to modify**:
- `docker-compose.yml`
- `Dockerfile.prod`
- `scripts/docker-entrypoint.sh` (new)
- `tests/test_deploy.py` (expand)

---

### T9: CLI Enhancements

**Goal**: `amp-distro` is the single tool for managing the distro.

**T9.1: Init improvements**
- `amp-distro init` should:
  1. Detect GitHub identity (gh auth status)
  2. Set workspace_root (default ~/dev, prompt to confirm)
  3. Check for API keys in environment, prompt if missing
  4. Save keys to keys.yaml
  5. Create distro.yaml with detected values
  6. Create the distro base bundle
  7. Initialize memory directory
  8. Run pre-flight
  9. Report success with next steps

- `amp-distro init --non-interactive` skips prompts (for Docker/CI)
- `amp-distro init --restore` restores from backup repo

**T9.2: Status improvements**
- `amp-distro status` should show:
  - Identity (GitHub handle)
  - Workspace root
  - Active bundle + included behaviors
  - Provider status (configured? key valid?)
  - Server status (running? port? uptime?)
  - Memory stats
  - Integration status (Slack connected? Voice configured?)
  - Last backup timestamp
  - Pre-flight report

**T9.3: New commands**
- `amp-distro server start/stop/restart/status` (delegates to server CLI)
- `amp-distro backup` / `amp-distro restore` (see T6)
- `amp-distro doctor` (see T7)
- `amp-distro logs` (tail server logs)
- `amp-distro config get/set <key> <value>` (read/write distro.yaml values)

**T9.4: Tests**
- Test init flow (with mock gh)
- Test status output format
- Test config get/set
- Target: +20 tests

**Files to modify**:
- `src/amplifier_distro/cli.py` (significant expansion)
- `tests/test_phase0.py` (expand)

---

### T10: Update Context Files

**Goal**: All context files reflect the new state.

**T10.1: Update DISTRO-PROJECT-CONTEXT.md**
- Update "Current Status" section
- Update "What's done" and "What's next"
- Update file map

**T10.2: Update ROADMAP.md**
- Check off completed items
- Update timeline estimates

**T10.3: Update .amplifier/AGENTS.md**
- Update project summary
- Update key files section
- Add any new conventions or patterns

---

## Implementation Guidelines

### Commit strategy
- Commit after each major task (T1, T2, etc.)
- Use conventional commit format: `feat:`, `fix:`, `docs:`
- Include Amplifier co-author trailer
- Run ALL tests before each commit (must stay at 469+ passing)

### Code patterns
- Follow existing patterns in the codebase
- All new modules get docstrings explaining purpose
- All public functions get type hints
- All new features get tests
- Use Pydantic for data models (matches schema.py pattern)
- Use conventions.py for ALL path/filename constants
- No hardcoded paths ever

### Testing patterns
- Tests go in `tests/test_<module>.py`
- Use pytest fixtures from `tests/conftest.py`
- Mock external services (Slack API, OpenAI, gh CLI)
- Test both happy path and error cases
- Run: `uv run python -m pytest tests/ -x -q`

### Key files to understand before modifying
- `src/amplifier_distro/conventions.py` - ALL path constants live here. NEVER hardcode a path.
- `src/amplifier_distro/schema.py` - ALL config models. Add new sections here.
- `src/amplifier_distro/server/app.py` - App plugin system. New apps go in `server/apps/`.
- `src/amplifier_distro/server/services.py` - Shared services singleton. Backend lives here.
- `src/amplifier_distro/server/session_backend.py` - Session backend (ALREADY COMPLETE).
- `src/amplifier_distro/bridge.py` - LocalBridge (ALREADY COMPLETE).
- `src/amplifier_distro/features.py` - Feature/behavior definitions. Add new features here.

### Things NOT to do
- Do NOT modify conventions.py constants (it's immutable by design)
- Do NOT add dependencies without updating pyproject.toml
- Do NOT create new config files (everything goes in distro.yaml or keys.yaml per Opinion #11)
- Do NOT rewrite the session backend (BridgeBackend + LocalBridge are complete and working)
- Do NOT require Docker for any user-facing feature
- Do NOT write placeholder/stub code that doesn't actually work
- Do NOT spend more than 2x the time budget on any single task

### Opinion #11 pattern (for all new integrations)
- Secrets -> keys.yaml (e.g., OPENAI_API_KEY, SLACK_BOT_TOKEN)
- Config -> distro.yaml under a named section (e.g., `voice:`, `slack:`, `backup:`)
- Setup page -> `/static/<name>-setup.html`
- Setup API -> `/apps/<name>/setup/*`

---

## Execution Order

Work through tasks T1-T10 in order. Each task should be:
1. Delegated to an implementation sub-agent (with full task spec)
2. Verified by a separate verification sub-agent
3. Committed (if tests pass)
4. Status recorded in OVERNIGHT-BUILD-STATUS.md

If a task is blocked or stuck:
1. Mark it as SKIPPED or PARTIAL in status file
2. Leave a clear TODO comment in the code
3. Note what's blocking it
4. Move to the next task immediately

**All tasks are important. No task is worth getting stuck on.**

---

## Verification Checklist

Before declaring victory, verify (use a verification sub-agent):

- [ ] `uv run python -m pytest tests/ -x -q` -- all tests pass (should be 550+)
- [ ] `uv run amp-distro init` works (creates distro.yaml, keys.yaml, bundle, memory dir)
- [ ] `uv run amp-distro status` shows comprehensive health report
- [ ] `uv run amp-distro doctor` runs all checks
- [ ] `uv run amp-distro-server --dev` starts and serves:
  - [ ] /api/health returns 200
  - [ ] /api/status returns full status
  - [ ] /static/quickstart.html loads
  - [ ] /static/settings.html shows config + integrations
  - [ ] /apps/web-chat/ works (can send messages, get responses)
  - [ ] /apps/slack/setup/status returns configuration state
  - [ ] /apps/voice/api/status returns voice service status
- [ ] Server can be started as daemon (`amp-distro-server start`)
- [ ] Server can be stopped cleanly (`amp-distro-server stop`)
- [ ] `amp-distro backup` runs (with mock gh or real)
- [ ] `amp-distro doctor --fix` auto-fixes common issues
- [ ] Git status is clean (all changes committed)
- [ ] DISTRO-PROJECT-CONTEXT.md is updated
- [ ] OVERNIGHT-BUILD-STATUS.md has final summary
