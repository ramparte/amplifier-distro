# Amplifier Distro: Implementation Design

Full technical design for the distro. Covers interface integration,
machine independence, update model, and phased implementation roadmap.

---

## Interface Inventory (Current State)

### CLI (amplifier-app-cli) - Production, Well-Factored

**Repo:** microsoft/amplifier-app-cli (local: ~/dev/ANext/Inactive/amplifier-app-cli/)
**Stack:** Python, Click, Rich
**Install:** `uv tool install git+https://github.com/microsoft/amplifier`
**Entry point:** `amplifier` command

**How it creates sessions:**
- Single path: `session_runner.py:create_initialized_session()`
- Config resolution: `runtime/config.py:resolve_config()` - the golden path
- Bundle loading: `lib/bundle_loader/` - discovery, preparation, caching
- Settings: 4-scope YAML (session > local > project > global)
- Providers: env vars + bundle config, with `${VAR}` expansion
- Keys: `~/.amplifier/keys.env` loaded on startup

**Key insight:** The CLI's `resolve_config()` is the de facto standard
for how a session gets configured. Every other interface either imports
it (TUI) or reimplements parts of it (Web). The distro should formalize
this path, not replace it.

**CLI subcommand structure:**
```
amplifier                     # Interactive chat
amplifier run "prompt"        # Single-shot
amplifier init                # First-time setup
amplifier bundle {use,list,show,add,remove}
amplifier session {list,show,resume,delete}
amplifier update              # Self-update
amplifier reset               # Reset configuration
```

**What distro adds:** `amp distro init`, `amp distro status`,
`amp distro install <interface>`, `amp distro backup`, `amp distro restore`.
This is a SEPARATE tool in this repo, not a CLI plugin. It produces
artifacts (distro.yaml, base bundle) that the CLI already knows how
to consume.

---

### TUI (amplifier-tui) - Working Prototype, Fragile

**Repo:** ramparte/amplifier-tui (local: ~/dev/ANext/amplifier-tui/)
**Stack:** Python, Textual
**Install:** Manual (`uv pip install -e .` + global amplifier install)
**Entry point:** `amplifier-tui`

**How it creates sessions:**
- sys.path hack: manually adds `~/.local/share/uv/tools/amplifier/lib/`
  python site-packages to sys.path at runtime
- Then imports CLI internals: `session_runner.SessionConfig`,
  `create_initialized_session`, `resolve_bundle_config`, `AppSettings`
- Also imports amplifier-core: `AmplifierSession`, `HookResult`, events

**What works:** Chat, session resume, session sidebar, streaming,
thinking blocks, tool display, multiline input, lazy loading.

**What's broken:**
- The sys.path hack (hardcodes uv tool path, processes .pth files manually)
- Session save on quit (Textual kills event loop before async cleanup)
- Test file imports old package name (`amplifier_chic`)
- Session list path reconstruction (hyphens -> slashes, breaks on dashes in paths)
- No bundle/provider selection UI
- No config of its own

**Key insight for distro:** The TUI needs amplifier's session creation
API. Today it gets there via a fragile path hack. The distro fix is NOT
to rewrite the TUI's session code - it's to make amplifier properly
importable. If amplifier-app-cli declares its session_runner as a
stable API (or we extract a thin library), the sys.path hack disappears.
The distro's `amp distro install tui` handles making this work.

---

### Web (amplifier-web / amplifier-web-unified) - Working Prototype, ~80%

**Repo:** bkrabach/amplifier-web (upstream), ramparte/amplifier-web (unified fork)
**Stack:** Python/FastAPI backend + React/TypeScript/Vite frontend
**Install:** Manual (backend: `uv sync && uv run`, frontend: `npm install && npm run dev`)
**Entry point:** localhost:4000 (backend) + localhost:4100 (frontend)

**How it creates sessions:**
- DIRECT amplifier-core integration (NOT subprocess, NOT CLI import hack)
- `bundle_manager.py` uses `amplifier_foundation.load_bundle()` directly
- `session_manager.py` calls `prepared.create_session()` with web-specific
  display/approval/streaming implementations
- WebSocket for real-time streaming
- REST API for config, sessions, health

**What works:** Full text chat, bundle selection, behavior composition,
tool execution with approvals, session persistence/resume, agent delegation,
cancellation, auth tokens, working directory support, custom bundle
registration with validation.

**What's missing:** Voice frontend (backend WebRTC endpoints exist),
mobile, no tests beyond security, no production deployment.

**Key insight for distro:** The web app already does things "right" -
it uses amplifier-core/foundation directly. Its `BundleManager` is
essentially what the Interface Adapter would look like. The distro's
job is to (1) make it read distro.yaml for defaults, and (2) make
`amp distro install web` handle the backend+frontend setup.

---

### Desktop (amplifier-desktop) - Unknown

**Repo:** michaeljabbour/amplifier-desktop (private)
**Stack:** Unknown (likely Tauri or Electron wrapping amplifier-web)
**Status:** Can't inspect, private repo. Created Jan 12, 2026.

---

### Voice (amplifier-voice) - In Development

**Repo:** bkrabach/amplifier-voice
**Stack:** Python, OpenAI Realtime API, WebRTC
**Status:** Working for Brian's specific setup (tmux + wezterm + VR).
Seven hardcoded values need extraction.

---

### CarPlay - Prototype

**Repo:** samschillace/carplay
**Stack:** Two competing approaches (subprocess bridge vs programmatic)
**Status:** Neither works cleanly.

---

## Machine Independence

### The Goal

Install the distro on machine A. Work for weeks. Machine A dies.
Spin up machine B (desktop, VM, container, codespace). Restore.
Continue working with context intact.

### What Needs to Be Portable

```
~/.amplifier/
  distro.yaml              # Central config
  memory/
    memory-store.yaml      # Facts, preferences, learnings
    work-log.yaml          # Active work, pending decisions
  keys.env                 # API keys (EXCLUDED from backup by default)
  settings.yaml            # Global settings
  bundle-registry.yaml     # User-added bundles
  projects/                # Session data (large, selectively backed up)

~/dev/                     # Workspace (git repos - already backed up via git)

~/amplifier-dev-memory/    # Sam's current memory location (migrate or symlink)
```

### What's Already Backed Up

- **Git repos** in workspace: Already on GitHub. `git clone` restores them.
- **Team tracking sessions**: Already synced to amplifier-shared repo.
- **Bundle sources**: Already on GitHub. Cache rebuilds automatically.

### What's NOT Backed Up (The Gap)

- **distro.yaml** - Machine-specific paths but transferable conventions
- **memory/** - Unique, irreplaceable, small (KB-MB)
- **settings.yaml** - User preferences
- **bundle-registry.yaml** - Custom bundle registrations
- **API keys** - Sensitive, must be re-entered or stored in vault

### Backup Design

**Mechanism:** Git repo (private). Simple, transparent, already understood.

```bash
# Backup target
amp distro backup
  # Creates/updates a private GitHub repo: <gh_handle>/amplifier-backup
  # Commits: distro.yaml, memory/*, settings.yaml, bundle-registry.yaml
  # Does NOT commit: keys.env (security), projects/ (too large, already tracked)
  # Does NOT commit: cache/ (rebuilds automatically)

amp distro restore
  # Clones <gh_handle>/amplifier-backup
  # Applies: distro.yaml, memory/*, settings.yaml, bundle-registry.yaml
  # Prompts for: API keys
  # Runs: amp distro init --restore to rebuild cache, verify env
```

**Schedule:** Backup can run on a cron/timer, or as part of the weekly
team tracking sync. Or manually anytime.

**What gets backed up:**

| Item | Backed Up | Why |
|------|-----------|-----|
| distro.yaml | Yes | Machine config (paths adjusted on restore) |
| memory/*.yaml | Yes | Irreplaceable knowledge |
| settings.yaml | Yes | User preferences |
| bundle-registry.yaml | Yes | Custom bundle list |
| keys.env | NO | Security - re-enter on new machine |
| cache/ | NO | Rebuilds automatically from git sources |
| projects/ | NO | Large, sessions already tracked via team tracking |
| Workspace repos | NO | Already on GitHub |

### Container / VM Compatibility

**The distro does NOT require Docker for basic setup.** Vanilla desktop
(Linux, macOS, WSL) is the primary target.

Docker support means: you can run `amp distro init` inside a container
and get a working environment. What this requires:

1. **No GUI dependencies.** CLI + TUI work in any terminal. Web works
   if ports are exposed. Voice needs audio (not in containers).
2. **No hardcoded paths.** `~/dev/` not `/home/samschillace/dev/ANext/`.
   distro.yaml uses `~` expansion.
3. **Pre-built image (future).** A Dockerfile that includes Python, Node,
   uv, gh CLI, and runs `amp distro init --non-interactive`. For
   codespaces, devcontainers, or cloud VMs.
4. **Restore into container.** `amp distro restore` pulls backup,
   user provides API keys, environment is live.

### Restore Flow

```
New Machine / Container
  |
  v
Install prerequisites (Python, Node, uv, gh)
  |
  v
amp distro restore
  |
  +-- Clone <gh_handle>/amplifier-backup
  +-- Apply distro.yaml (adjust paths for new machine)
  +-- Apply memory/*, settings.yaml, bundle-registry.yaml
  +-- Prompt for API keys
  +-- Run amp distro init --restore
  |     +-- Install amplifier CLI
  |     +-- Rebuild bundle cache
  |     +-- Verify providers
  |     +-- Run pre-flight
  |
  v
Working environment (minus workspace repos)
  |
  v
Clone workspace repos (git clone from GitHub)
  |
  v
Full restore complete
```

The only manual steps: provide API keys, clone workspace repos.
Everything else is automated.

---

## Update Model

### What Needs Updating

| Component | Current Update Method | Frequency |
|-----------|----------------------|-----------|
| amplifier CLI | `amplifier update` (uv tool upgrade) | When user runs it |
| Bundle cache | Manual clear or wait for breakage | Never (or on error) |
| Module versions | Pinned in bundle, no auto-update | Never |
| Distro base bundle | Not applicable (doesn't exist yet) | N/A |
| Interfaces (TUI, Web) | Manual git pull | When user remembers |
| Memory | N/A (user data) | N/A |

### The Problem

Today, updates are manual and scattered. You have to:
1. Remember to run `amplifier update`
2. Remember to clear cache when bundles change
3. Remember to git pull each interface
4. Hope nothing breaks when versions drift

This is attentional load. The distro should make it zero.

### Distro Update Design

**Principle:** Updates happen. You don't think about them. If something
breaks, it tells you and rolls back.

```bash
amp distro update
  # 1. Update amplifier CLI (uv tool upgrade)
  # 2. Refresh bundle cache (force re-clone of all cached sources)
  # 3. Update distro base bundle (git pull this repo)
  # 4. Update installed interfaces (git pull each)
  # 5. Run pre-flight to verify everything still works
  # 6. If pre-flight fails: roll back, notify user
```

**Automatic vs manual:**

| Trigger | What Happens |
|---------|--------------|
| `amp distro update` | Full update: CLI + cache + base bundle + interfaces |
| Session start (pre-flight) | Check cache freshness. If stale, refresh silently. |
| Bundle load fails | Clear that cache entry, re-clone, retry once. |
| Weekly (optional cron) | `amp distro update` runs automatically |

**Rollback:** Before updating, snapshot the current state:
- Copy distro.yaml -> distro.yaml.bak
- Record current CLI version
- Record current bundle cache hashes

If pre-flight fails after update, restore from snapshot and notify.

**Version pinning (opt-in):**

```yaml
# ~/.amplifier/distro.yaml
updates:
  auto_cache_refresh: true       # Refresh stale cache entries on session start
  auto_retry_on_error: true      # Clear and re-clone failed cache entries
  pin_cli_version: null           # null = latest, or "1.2.3" = pinned
  pin_bundle_versions: false      # If true, bundles use @tag not @main
```

By default, everything floats on `@main`. Teams that need stability
can pin to tags. The distro doesn't have an opinion about this beyond
"floating is the default, pinning is available."

---

## `amp distro` - The Tool

### What It Is

A standalone CLI tool that lives in this repo. NOT a plugin to
amplifier-app-cli. It produces artifacts the CLI and other interfaces
consume.

**Install:**
```bash
uv tool install git+https://github.com/ramparte/amplifier-distro
```

**Entry point:** `amp-distro` (or `amp distro` if we add a shim)

### Commands

```
amp-distro init              # First-time setup
amp-distro init --restore    # Setup from backup
amp-distro status            # Health check dashboard
amp-distro update            # Update everything
amp-distro install <iface>   # Install an interface (tui, web, voice)
amp-distro backup            # Backup config + memory to GitHub
amp-distro restore           # Restore from GitHub backup
amp-distro doctor            # Diagnose and fix common problems
amp-distro version           # Show versions of all components
```

### `amp-distro init` Flow

```
$ amp-distro init

Amplifier Distro Setup
======================

Detecting environment...
  Platform: linux (WSL2)
  Python: 3.12.1
  Node: v20.11.0
  uv: 0.5.14
  gh: 2.43.1

  GitHub identity: samschillace (Sam Schillace)
  Git email: sam@example.com

Workspace directory [~/dev]: ~/dev
  Created: ~/dev/

Installing Amplifier CLI...
  uv tool install git+https://github.com/microsoft/amplifier
  Installed: amplifier 0.9.2

API Keys:
  ANTHROPIC_API_KEY [enter to skip]: sk-ant-...
  OPENAI_API_KEY [enter to skip]: sk-...
  Saved to: ~/.amplifier/keys.env

Creating personal bundle...
  Base: amplifier-distro base bundle
  Your bundle: ~/.amplifier/bundles/my-amplifier.md
  Includes: agents, memory, streaming, redaction

Running pre-flight...
  Bundle: OK (12 modules loaded)
  Anthropic: OK (claude-sonnet-4-20250514)
  OpenAI: OK (gpt-4o)
  Memory: OK (initialized at ~/amplifier-dev-memory/)
  Sessions: OK (~/.amplifier/projects/)

Writing config...
  ~/.amplifier/distro.yaml

Done. Run 'amplifier' to start a session.

Optional interfaces:
  amp-distro install tui     # Terminal UI
  amp-distro install web     # Web interface
  amp-distro install voice   # Voice interface
```

### `amp-distro status` Output

```
$ amp-distro status

Amplifier Distro Status
=======================

Core:
  CLI version:     0.9.2 (latest)
  Python:          3.12.1
  Platform:        linux (WSL2)

Identity:
  GitHub:          samschillace
  Git email:       sam@example.com

Workspace:         ~/dev/ (47 repos)

Bundle:            my-amplifier (valid)
  Base:            distro-base v1.0
  Behaviors:       agents, memory, team-tracking, streaming, redaction
  Providers:       anthropic (OK), openai (OK)
  Agents:          16 available

Memory:            ~/amplifier-dev-memory/ (23 memories, 4 work items)

Cache:             ~/.amplifier/cache/ (12 entries, oldest: 3 days)

Sessions:          ~/.amplifier/projects/ (91 sessions, 14 projects)
  Last session:    2 hours ago (amplifier-distro)

Interfaces:
  CLI:             installed (amplifier 0.9.2)
  TUI:             installed (~/dev/amplifier-tui/)
  Web:             not installed
  Voice:           not installed

Backup:            last backup 1 day ago (ramparte/amplifier-backup)

Health: ALL GREEN
```

---

## Implementation Roadmap (Detailed)

### Phase 0: The Config File and the Tool (Week 1)

**Deliverable:** `amp-distro init` works and produces distro.yaml.

| # | Task | What Specifically | Where |
|---|------|-------------------|-------|
| 0.1 | Create Python package in this repo | pyproject.toml, click CLI, entry point `amp-distro` | amplifier-distro/ |
| 0.2 | Define distro.yaml schema | Pydantic model: workspace, identity, bundle, cache, interfaces, updates, backup | amplifier-distro/ |
| 0.3 | Implement `amp-distro init` | Detect platform, identity, install CLI, prompt for keys, create personal bundle, write distro.yaml | amplifier-distro/ |
| 0.4 | Implement `amp-distro status` | Read distro.yaml, check CLI version, validate bundle, check providers, show memory stats | amplifier-distro/ |
| 0.5 | Create distro base bundle | YAML that composes: foundation agents, memory, streaming, redaction | amplifier-distro/ |
| 0.6 | Implement pre-flight check | Run on `amp-distro status` and as callable library for interfaces | amplifier-distro/ |

**Exit criteria:**
- `uv tool install git+https://github.com/ramparte/amplifier-distro` works
- `amp-distro init` produces a working distro.yaml and personal bundle
- `amp-distro status` shows all-green for a properly configured machine
- Starting `amplifier` with the generated personal bundle works

### Phase 1: Bundle Validation and Session Handoffs (Week 2-3)

**Deliverable:** Sessions carry context forward. Bundle errors are loud.

| # | Task | What Specifically | Where |
|---|------|-------------------|-------|
| 1.1 | Bundle validation strict mode | PR: when `strict: true` in settings, promote include warnings to errors | amplifier-foundation |
| 1.2 | Pre-flight hook | Hook that runs on session start, calls amp-distro pre-flight library | amplifier-distro/ |
| 1.3 | Session handoff hook | Hook: on session end, write handoff.md summarizing what happened | amplifier-distro/ |
| 1.4 | Handoff injection | On session start, if handoff.md exists for this project, inject as system context | amplifier-distro/ |
| 1.5 | Distro base bundle v2 | Add pre-flight and handoff hooks to the base bundle | amplifier-distro/ |

**Exit criteria:**
- Starting a session with a broken bundle gives a clear error (not silent)
- End a session, start a new one in same project, it "knows" what happened
- Pre-flight catches: missing API keys, broken includes, stale cache

### Phase 2: Interface Installers (Week 3-4)

**Deliverable:** `amp-distro install tui` gives you a working TUI.

| # | Task | What Specifically | Where |
|---|------|-------------------|-------|
| 2.1 | Interface installer framework | Installer that: clones repo, installs deps, registers in distro.yaml, runs smoke test | amplifier-distro/ |
| 2.2 | TUI installer | Clone amplifier-tui, create venv, install with amplifier as dependency, smoke test | amplifier-distro/ |
| 2.3 | TUI dependency fix | Make amplifier-tui properly declare amplifier-app-cli as dependency (eliminate sys.path hack) | amplifier-tui PR |
| 2.4 | TUI distro.yaml reader | TUI reads distro.yaml for workspace_root, identity, active bundle | amplifier-tui PR |
| 2.5 | Web installer | Clone amplifier-web-unified, install backend deps + frontend deps, configure ports, smoke test | amplifier-distro/ |
| 2.6 | Web distro.yaml reader | Web backend reads distro.yaml for defaults (bundle, workspace, identity) | amplifier-web PR |

**Exit criteria:**
- `amp-distro install tui` on a fresh machine with distro installed -> working TUI
- `amp-distro install web` -> working web interface
- Both interfaces show sessions from the same project
- `amp-distro status` shows installed interfaces

### Phase 3: Backup, Restore, and Updates (Week 4-5)

**Deliverable:** Machine portability. Painless updates.

| # | Task | What Specifically | Where |
|---|------|-------------------|-------|
| 3.1 | Implement `amp-distro backup` | Create/update private repo with distro.yaml, memory/, settings, bundle-registry | amplifier-distro/ |
| 3.2 | Implement `amp-distro restore` | Clone backup, apply config (adjust paths), prompt for keys, run init --restore | amplifier-distro/ |
| 3.3 | Implement `amp-distro update` | Update CLI, refresh cache, update base bundle, update interfaces, run pre-flight, rollback on failure | amplifier-distro/ |
| 3.4 | Implement `amp-distro doctor` | Diagnose common problems: stale cache, broken bundles, missing keys, version mismatches | amplifier-distro/ |
| 3.5 | Auto-cache-refresh | On session start pre-flight, if cache entry older than TTL, refresh silently | amplifier-distro/ or foundation PR |

**Exit criteria:**
- `amp-distro backup` + new machine + `amp-distro restore` -> working environment
- `amp-distro update` updates everything, rolls back if pre-flight fails
- `amp-distro doctor` identifies and offers to fix common problems

### Phase 4: Setup Website + Container Support (Week 5-6)

**Deliverable:** Agent-driven setup. Docker support.

| # | Task | What Specifically | Where |
|---|------|-------------------|-------|
| 4.1 | Setup website (GitHub Pages) | Static page with machine-readable setup instructions | amplifier-distro/ |
| 4.2 | Agent-driven setup recipe | Recipe that reads setup URL and executes steps | amplifier-distro/ |
| 4.3 | Dockerfile | Base image with prerequisites, runs `amp-distro init --non-interactive` | amplifier-distro/ |
| 4.4 | Devcontainer config | .devcontainer.json for codespaces/VSCode | amplifier-distro/ |
| 4.5 | Non-interactive init mode | `amp-distro init --non-interactive --keys-from-env` for CI/container use | amplifier-distro/ |

**Exit criteria:**
- "Point an agent at this URL" -> agent sets up environment
- `docker build . && docker run` -> working amplifier environment
- GitHub Codespace with devcontainer -> working environment

### Phase 5: Workflows (Week 6+)

**Deliverable:** The system starts working FOR you.

| # | Task | What Specifically | Where |
|---|------|-------------------|-------|
| 5.1 | Morning brief | On session start, summarize: last session handoff + memory work-log + recent git activity | amplifier-distro/ |
| 5.2 | Attention firewall integration | Read firewall config from distro.yaml, share filtered notifications with morning brief | amplifier-distro/ |
| 5.3 | Friction detection | Weekly: analyze recent sessions, identify top 3 attention drains, suggest fixes | amplifier-distro/ |
| 5.4 | Auto-fix proposals | When friction detection finds a pattern (e.g., repeated cache clears), propose a distro change | amplifier-distro/ |

**Exit criteria:**
- Starting a session gives context without asking
- Weekly friction report identifies real issues
- At least one auto-fix has been proposed and applied

---

## Dependency Graph

```
Phase 0: Tool + Config
  [0.1 Package] -> [0.2 Schema] -> [0.3 Init] -> [0.5 Base Bundle]
                                 -> [0.4 Status]
                                                -> [0.6 Pre-flight]

Phase 1: Validation + Handoffs (depends on 0.5, 0.6)
  [1.1 Strict Mode] -> [1.2 Pre-flight Hook]
  [1.3 Handoff Hook] -> [1.4 Handoff Injection] -> [1.5 Bundle v2]

Phase 2: Interfaces (depends on 0.3, 0.5)
  [2.1 Installer Framework] -> [2.2 TUI Installer]
                             -> [2.5 Web Installer]
  [2.3 TUI Dep Fix] -> [2.4 TUI distro.yaml]
  [2.6 Web distro.yaml]

Phase 3: Portability (depends on 0.2, 0.3)
  [3.1 Backup] -> [3.2 Restore]
  [3.3 Update] -> [3.5 Auto-refresh]
  [3.4 Doctor]

Phase 4: Automation (depends on 0.3, 3.2)
  [4.1 Website] -> [4.2 Agent Setup]
  [4.3 Dockerfile] -> [4.5 Non-interactive]
  [4.4 Devcontainer]

Phase 5: Workflows (depends on 1.3, 1.4)
  [5.1 Morning Brief]
  [5.2 Attention Firewall]
  [5.3 Friction Detection] -> [5.4 Auto-fix]
```

**Critical path:** 0.1 -> 0.2 -> 0.3 -> 0.5 -> 1.2 -> 1.3 -> 1.4

The critical path delivers: installable tool, config file, personal
bundle, pre-flight, and session handoffs. Everything else can proceed
in parallel once the config schema (0.2) is defined.

---

## What Does NOT Need To Change

The distro is built ON TOP of the existing ecosystem. These stay as-is:

- **amplifier-core** - No kernel changes needed
- **amplifier-foundation** - Small PR for strict validation (1.1), rest untouched
- **Provider modules** - No changes
- **Tool modules** - No changes
- **Recipes system** - No changes
- **Team tracking** - No changes (reads distro.yaml for config if present)
- **Agent system** - No changes
- **Bundle format** - No changes (distro base bundle is a standard bundle)

The distro is ~95% new code in this repo + small PRs to TUI and Web
for distro.yaml reading. That's it.

---

## How Project Orchestrator Fits

This project is well-suited for project orchestrator (start/stop friendly):

- Each task in the roadmap is scoped to one session of work
- Dependencies are explicit (see graph above)
- No task requires holding state across sessions (the context file handles that)
- The task list can be loaded at session start to know where we are
- Progress is tracked by what files exist and what PRs are merged

A project orchestrator recipe could:
1. Read this IMPLEMENTATION.md for task list
2. Check which tasks are done (files exist, PRs merged)
3. Identify the next unblocked task
4. Present it with full context
5. Execute or delegate

But we don't NEED project orchestrator to start. The task list is
clear enough to work from directly.

---

## Open Design Questions

### Q1: How does the TUI properly depend on amplifier?

**Options:**
a. TUI depends on `amplifier-app-cli` as a pip package (quick, maintains coupling)
b. Extract a `amplifier-session-api` thin library from CLI (clean, more work)
c. TUI uses amplifier-core + foundation directly like the web app (most correct, most rewrite)

**Recommendation:** (a) for now. The sys.path hack exists because
amplifier-app-cli isn't pip-installable from the TUI's perspective.
Making it a proper dependency (via uv sources pointing to git) solves
the immediate problem. Option (b) or (c) is better long-term but
isn't needed to ship the distro.

### Q2: Should `amp-distro` also be available as `amp distro`?

A shell alias or shim script could make `amp distro init` work as
a shorthand for `amp-distro init`. This is cosmetic but nice UX.
Decision: add an alias during `amp-distro init`.

### Q3: How do we handle the memory location?

Sam's memory is at `~/amplifier-dev-memory/`. The dev-memory bundle
hardcodes this path. Options:
a. Keep it there (distro.yaml records it, all tools read the config)
b. Move to `~/.amplifier/memory/` (cleaner, requires migration)
c. Symlink `~/.amplifier/memory/` -> `~/amplifier-dev-memory/`

**Recommendation:** (a). Keep the current location. Record it in
distro.yaml. Don't move things that are working. The distro.yaml
becomes the source of truth for "where is memory?", not the path itself.

### Q4: Voice installer scope?

Voice (amplifier-voice) is tied to Brian's specific hardware setup
(tmux + wezterm + VR). An installer would need to handle:
- OpenAI Realtime API dependencies
- Audio input/output configuration
- tmux integration (optional)

**Recommendation:** Voice installer is Phase 2+ but lower priority
than TUI and Web. Start with `amp-distro install voice` that clones
and installs deps, but doesn't configure hardware-specific audio.

### Q5: How do updates interact with team coordination?

When `amp-distro update` runs, it might pull breaking changes.
For a team, updates should be coordinated. Options:
a. Everyone floats on @main (current)
b. Distro pins to release tags, manual version bumps
c. Distro checks for "team-recommended version" in a shared config

**Recommendation:** (a) for now. Pin versions is opt-in via
distro.yaml `pin_cli_version` and `pin_bundle_versions`. Team
coordination is a Phase 5+ concern.
