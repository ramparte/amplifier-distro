# Lean Experience Server

**Branch:** `lean-experience-server`
**Date:** 2026-02-23
**Status:** Implementation complete, pending foundation wiring for session resume

## Context

The amplifier-distro repository originally served as an opinionated distribution
that bundled together configuration management, health checks, bundle composition,
a provider catalog, and an experience server (web chat, Slack, voice). Over time,
the core value of distro — the opinions, the CLI experience, the directory
conventions — was extracted into proper homes:

- **amplifier-app-cli** absorbed `amplifier doctor`, `amplifier init`, and the
  `session:preflight` event
- **amplifier-foundation** absorbed the `~/.amplifier/` directory contract,
  cache TTL support, and strict bundle validation
- **amplifier-start** (new bundle) absorbed the 11 opinions, environment
  awareness, handoff hooks, preflight hooks, and specialized agents

What remained in distro was the experience server and a large amount of code
that duplicated or reimplemented functionality now living in those three repos.

## Decision

Cut amplifier-distro down to **only the experience server** — the thing it
does that nothing else does. Everything that has been solved elsewhere gets
deleted. The three-part install becomes:

```
amplifier CLI          → the tool (commands, doctor, init, sessions)
amplifier-start bundle → the opinions (conventions, context, agents, hooks)
amplifier-distro       → the experiences (web chat, Slack, voice, etc.)
```

## What Was Removed

### Bridge layer (bridge.py, bridge_protocols.py) — ~1,090 lines

The bridge was a distro-era abstraction that reimplemented foundation's session
lifecycle with distro-specific config injection bolted on. It predated
foundation's current `load_bundle()` → `prepare()` → `create_session()` API.
The server apps now use foundation directly via `FoundationBackend` in
`session_backend.py`.

### Configuration system — ~435 lines

| File | Replacement |
|------|-------------|
| `config.py` (distro.yaml loader) | `settings.yaml` via foundation |
| `schema.py` (Pydantic models for distro.yaml) | Not needed |
| `conventions.py` (trimmed from 137 → 55 lines) | Server-relevant constants only; shared conventions live in foundation's DIRECTORY_CONTRACT.md |

### Feature catalog and bundle composition — ~475 lines

| File | Replacement |
|------|-------------|
| `features.py` (hardcoded provider catalog) | Provider config via `settings.yaml` |
| `bundle_composer.py` (generated bundle YAML) | Real bundle directories (amplifier-start) |
| `docs_config.py` (documentation pointers) | Inline or removed |

### CLI commands — ~570 lines

Commands moved to `amplifier` CLI or dropped:

| Command | Disposition |
|---------|------------|
| `amp-distro init` | → `amplifier init` |
| `amp-distro doctor` | → `amplifier doctor` |
| `amp-distro status` | → `amplifier doctor` |
| `amp-distro validate` | Dropped (validated distro.yaml, which no longer exists) |
| `amp-distro version` | Dropped (`uv` handles package versions) |
| `amp-distro update` | Dropped (`uv tool install --upgrade`) |
| `amp-distro install` | Dropped (interfaces install independently) |
| `amp-distro interfaces` | Dropped |

Remaining CLI: `amp-distro server`, `amp-distro backup/restore`, `amp-distro service`.

### Diagnostics — ~678 lines

| File | Replacement |
|------|-------------|
| `doctor.py` (13-check diagnostic) | `amplifier doctor` in app-cli (9 checks; 4 dropped were server-specific) |
| `preflight.py` (pre-session health) | `session:preflight` event + hook in amplifier-start |

### Other removed modules — ~1,289 lines

| File | Reason |
|------|--------|
| `deploy.py` | Cloud deploy targets, never production-ready |
| `migrate.py` | One-time legacy memory migration |
| `update_check.py` | SHA-based self-update, replaced by `uv` |
| `provider_api.py` | Provider test endpoint, inlined into server/app.py |

### Settings and install wizard apps — ~3,339 lines (including HTML)

These were deeply coupled to the feature-catalog/bundle-composer system. The
install wizard composed bundles from a tier system and provider catalog — all
replaced by real bundle directories. The settings app managed features, tiers,
and provider switching through the same system.

These can be rebuilt later as a simple API-key-setup flow if needed.

### Test files — ~5,558 lines

15 test files deleted (tested removed code), 5 refactored to match new APIs.

## What Remains

### Core utilities

| File | Purpose |
|------|---------|
| `conventions.py` | Server-relevant path constants (55 lines) |
| `cli.py` | `server`, `backup/restore`, `service` commands |
| `backup.py` | GitHub backup/restore (standalone, no config deps) |
| `service.py` | systemd/launchd registration |
| `fileutil.py` | Atomic file writes |
| `tailscale.py` | HTTPS reverse proxy setup |
| `transcript_persistence.py` | Session transcript hook |

### Server framework

| File | Purpose |
|------|---------|
| `server/app.py` | FastAPI core, health/session/memory routes |
| `server/cli.py` | Server start/stop/restart/status, watchdog |
| `server/startup.py` | Structured logging, key export from keys.yaml |
| `server/daemon.py` | Background daemon management |
| `server/services.py` | Shared service singleton (FoundationBackend or MockBackend) |
| `server/session_backend.py` | SessionBackend protocol + FoundationBackend + MockBackend |
| `server/memory.py` | Cross-interface memory storage |
| `server/watchdog.py` | Health monitoring with auto-restart |
| `server/stub.py` | Canned data for UI development |

### Experience apps

| App | Status |
|-----|--------|
| `apps/slack/` | Unchanged (full Slack bridge, ~10 files) |
| `apps/web_chat/` | Unchanged (browser chat UI) |
| `apps/voice/` | Refactored (config via env vars instead of distro.yaml) |
| `apps/routines/` | Unchanged (scheduled execution) |

## Key Architectural Changes

### 1. No bridge — foundation-direct sessions

`FoundationBackend` in `session_backend.py` calls foundation's API directly:

```python
from amplifier_foundation import load_bundle

bundle = load_bundle(bundle_name)
prepared = bundle.prepare()
session = prepared.create_session(working_dir=str(wd))
```

All the valuable queue/worker/tombstone infrastructure from the old
`BridgeBackend` was preserved — only the 4 bridge-touching methods were
replaced.

### 2. No distro.yaml — environment-driven config

| Setting | Source |
|---------|--------|
| Voice model/voice/instructions | `AMPLIFIER_VOICE_*` env vars |
| Server API key | `AMPLIFIER_SERVER_API_KEY` env var |
| API keys (providers) | `keys.yaml` → exported to env at startup |
| Bundle selection | `settings.yaml` via foundation |

### 3. Backup simplified

`backup()` and `restore()` now take simple arguments (`amplifier_home`,
`gh_handle`, `repo_name`) instead of requiring a `BackupConfig` Pydantic model
loaded from `distro.yaml`. GitHub handle is detected directly via `gh api user`.

### 4. Root redirect simplified

The old root route checked `compute_phase()` (which inspected filesystem state
via the feature catalog) to decide whether to show the install wizard or landing
page. Now it just serves the landing page.

## Remaining Work

### Session resume (TODO in FoundationBackend._reconnect)

The `_reconnect()` method raises `NotImplementedError`. Session resume after
server restart requires:

1. Loading the transcript from `transcript.jsonl`
2. Sanitizing orphaned tool calls
3. Restoring messages into the session context

Both the old bridge and amplifier-app-cli independently implemented inferior
versions of this logic. Foundation already has `find_orphaned_tool_calls()` in
`slice.py`. The right fix is a `restore_transcript()` utility in foundation
that both consumers use. This is tracked separately.

### Install flow documentation

The new three-step install should be documented:

```bash
uv tool install amplifier                    # 1. the CLI
amplifier init                               # 2. creates ~/.amplifier/
amplifier bundle add amplifier-start         # 3. registers the opinions
amp-distro server start                      # 4. starts the experiences
```

### Optional: simple API key setup UI

If a web-based key setup flow is wanted, a minimal version can be rebuilt
without the feature-catalog/bundle-composer coupling. It would just write to
`keys.yaml` and export to env.

## Metrics

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Source files | 46 | 33 | -28% |
| Source lines (Python) | ~12,800 | ~4,600 | -64% |
| Test files | 36 | 21 | -42% |
| HTML files | 5 | 2 | -60% |
| Dependencies on deleted modules | 13 internal modules | 0 | Clean |
