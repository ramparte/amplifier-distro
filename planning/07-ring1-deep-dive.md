# Ring 1 Deep Dive: Path to Hands-Off Foundation

## What Ring 1 Contains

Ring 1 is everything you set up once and never think about again:
dev folder, identity, validated bundles, memory, health checks,
session handoffs, cache management.

The goal: zero ongoing attention. If Ring 1 requires attention,
it has failed.

---

## Gap Analysis: What Exists vs What's Needed

### 1. Bundle Validation

**Today:** Validation exists in three places but none prevent the
pain the user actually feels.

| Layer | What It Checks | What It Misses |
|-------|---------------|----------------|
| `BundleValidator` (foundation) | Name exists, module lists shaped right, context paths | Silent include drops, env var resolution, module source resolution |
| `_validate_module_list()` (bundle.py) | Items are dicts with `module` key | Source URIs actually resolvable |
| `amplifier-core validate` CLI | Provider/Tool/Hook structural + behavioral | Only works on already-loaded modules |

**The core problem:** When `_compose_includes()` in the registry hits
a broken include, it logs a warning and continues. Agents silently
disappear. The user discovers this 30 minutes into a session when
they try to use an agent that isn't there.

**What's needed (a "loud failure" validation pass):**

| Check | Current State | Fix |
|-------|--------------|-----|
| Include URIs resolve | Warning on failure | Error on failure |
| Agent .md files exist and parse | Exception swallowed with logger.warning | Error on failure |
| Context paths exist | Warning only | Error (or at least prominent warning) |
| Module sources resolvable | Not checked until prepare() | Pre-check at validate time |
| Env vars in provider config set | Not checked until first API call | Check at validate: regex `${VAR}`, verify os.environ |
| No namespace collisions | Not checked | Check composed bundle for duplicate agent names |
| Git sources have valid refs | Checked but not surfaced | Include in validation report |

**Implementation path:** Extend `BundleValidator.validate()` with a
`strict=True` mode that promotes warnings to errors and adds the
missing checks. Expose as `amp env validate` (or recipe).

**Effort estimate:** 2-3 days for validation. 1 day for CLI exposure.

---

### 2. Pre-Flight Health Checks

**Today:** The CLI startup flow is:
1. Load keys from `keys.env`
2. Check if settings.yaml exists (first-run only)
3. Async update check (prints dim message, never blocks)
4. Load bundle (warnings swallowed)
5. Prepare bundle (install deps, resolve paths)
6. Create session (orchestrator/context hard-fail, everything else soft)

**The gap:** Steps 4-6 have soft failures that produce no user-visible
output. You can start a session with broken tools, missing agents,
and invalid API keys without knowing.

**Proposed pre-flight check (runs between steps 3 and 4):**

```
Pre-flight checks:
  [ok] API key: ANTHROPIC_API_KEY set
  [ok] API key: valid (claude-opus-4-6 accessible)
  [ok] Bundle: my-amplifier loaded (47 modules)
  [FAIL] Bundle: 2 includes failed:
    - textbook-factory: ./bundle.md not found
    - exp-delegation: git clone failed (404)
  [ok] Cache: all sources <7 days old
  [ok] Memory: ~/amplifier-dev-memory/ accessible
  [warn] Session: no handoff from yesterday

2 failures, 1 warning. Continue anyway? [Y/n]
```

**Hook point identified:** Between bundle load and bundle.prepare().
At this point we have the fully composed Bundle object with all
includes resolved (or failed) but haven't started installing deps.

**Implementation path:**
- New module: `preflight.py` in amplifier-foundation
- Called from CLI startup flow (app-layer policy wraps foundation mechanism)
- Config in settings.yaml `environment.preflight` section
- Fast (<2 seconds for basic checks, <10 seconds with API validation)

**Effort estimate:** 3-4 days.

---

### 3. Session Handoffs (Auto-Context Continuity)

**Today:** Sessions write to `~/.amplifier/projects/<slug>/sessions/<id>/`:
- `events.jsonl` - raw kernel events
- `transcript.jsonl` - user/assistant messages
- `metadata.json` - session metadata
- `profile.md` - bundle config snapshot

**What's missing:** No auto-summary. No handoff document. No
SESSION_END event in the kernel's event taxonomy. Sessions just stop.

**The result:** Next session starts cold. User must re-explain project
goals, architecture decisions, and current state. This was the #4
friction category (80 "repeat context" signals across 26 sessions).

**What auto-handoff needs:**

1. **SESSION_END event** - Add to `amplifier_core/events.py`. Emit
   from `AmplifierSession.cleanup()` or the REPL exit handler.

2. **Summary generation hook** - On SESSION_END, invoke a lightweight
   LLM call to generate:
   - What was accomplished (files changed, decisions made)
   - What's in progress / blocked
   - Key context for next session
   - Suggested next steps

3. **Handoff file** - Write to either:
   - `~/.amplifier/projects/<slug>/handoff.md` (project-level, latest)
   - `~/.amplifier/projects/<slug>/sessions/<id>/handoff.md` (per-session)

4. **Resume integration** - When starting a new session in the same
   project directory, inject handoff content as context.

**Technical concern:** Summary generation at session end adds latency
to exit. Options:
- Fire-and-forget (async, may not complete)
- Blocking but fast (use haiku, ~2 seconds)
- Background post-exit (write event, daemon processes later)

**Effort estimate:** 1 week (SESSION_END event + hook + integration).

---

### 4. Cache Management (Stop the Groundhog Day)

**Today:**
- Cache is permanent until manual `amplifier update`
- Shallow clones (`--depth 1`) can't be updated, only nuked + recloned
- Update check runs every 4 hours, prints dim message, never auto-applies
- No cache invalidation on error (broken cache persists between sessions)
- No integrity check beyond "does .git dir exist?"

**The "same error daily" root cause chain:**
1. Bundle has bug on @main
2. Cache is a shallow clone of that bug
3. Update checker tells you updates available (dim text)
4. You don't notice or don't run `amplifier update`
5. Same broken cache loads every session
6. You debug the same error again

**Fixes needed:**

| Fix | Mechanism | Effort |
|-----|-----------|--------|
| Auto-refresh on error | If module activation fails, re-clone that source | 1 day |
| Deep integrity check | Parse bundle.md/pyproject.toml, not just check existence | 1 day |
| TTL-based freshness | `max_age_hours` in cache metadata, check at load | 1 day |
| Atomic cache replacement | Clone to temp dir, swap, instead of rmtree+clone | 0.5 day |
| CLI cache management | `amp cache clean`, `amp cache refresh` commands | 1 day |

**Effort estimate:** 3-4 days for all fixes.

---

### 5. Config Schema and Environment Section

**Today:** `settings.yaml` has no schema validation. Any YAML that
parses is accepted. The structure is app-layer convention.

**Proposed `environment:` section:**

```yaml
environment:
  workspace: ~/dev/ANext        # Canonical dev folder
  
  preflight:
    enabled: true
    check_api_keys: true
    check_model_names: true
    check_bundle_integrity: true
    fail_on_warning: false

  cache:
    max_age_hours: 168          # 1 week
    auto_refresh_on_error: true
    verify_integrity: deep      # shallow | deep

  session:
    auto_handoff: true
    handoff_format: markdown
    handoff_location: project   # project | session

  health:
    startup_checks: true
    periodic_interval_hours: 0  # 0 = disabled
```

**Implementation path:**
1. Extend `settings_manager.py:DEFAULT_SETTINGS` with environment section
2. Add `get_environment_settings()` convenience function
3. Optional: Pydantic/dataclass schema for validation
4. Wire into startup flow

**Effort estimate:** 1-2 days.

---

### 6. Dev Memory Improvements

**Today:** File-based at `~/amplifier-dev-memory/`, 15 memories, work
log, read-delegation pattern. Simple and working.

**Gaps for Ring 1:**
- No automatic memory capture from sessions (manual "remember this:" only)
- No project-level memory (only global)
- No integration with session handoffs
- No cross-machine sync (local files only)

**What Ring 1 needs (v1):**
- Session handoffs auto-stored as project memories
- Architecture decisions tagged and searchable
- "What did I decide about X?" query across all sessions

**Effort estimate:** 1 week for v1 (handoffs to memory integration).

---

## Total Path to Hands-Off Ring 1

| Component | Effort | Dependencies | Priority |
|-----------|--------|-------------|----------|
| Bundle validation (loud failures) | 3-4 days | None | 1 (highest) |
| Pre-flight health checks | 3-4 days | Bundle validation | 2 |
| Config schema + environment section | 1-2 days | None | 3 |
| Cache management fixes | 3-4 days | None | 3 |
| Session handoffs | 5 days | SESSION_END event (core change) | 4 |
| Memory integration | 5 days | Session handoffs | 5 |

**Total estimated effort: ~4 weeks** (but many can parallel)

**Critical path: Bundle validation -> Pre-flight -> Handoffs**

The first two together would eliminate the #1 and #2 friction
categories (session corruption triggered by bad config, and silent
bundle failures). That alone would recover ~20% of currently
wasted attention.
