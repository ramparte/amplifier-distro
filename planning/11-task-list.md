# Task List: Amplifier Environment

Ordered by priority and dependency. Each task is designed to be
completable in one session (1-4 hours), deliverable as one PR,
and independently valuable.

Status key: [ ] todo, [~] in progress, [x] done, [>] blocked

---

## Tier 0: Immediate Wins (This Week)

These require no architecture changes. Just fixing known issues
and enabling existing features.

### T0.1: Fix known bundle include errors
- [ ] **Status:** Todo
- **Repo:** my-amplifier bundle (personal config)
- **What:** Remove broken includes (textbook-factory, exp-delegation,
  any `./` paths that don't resolve). Fix HTTP->HTTPS in source URIs.
- **Why:** Eliminates 9+ sessions/2wk of silent config failures.
- **Success:** `amp env validate` (or manual bundle load) shows 0 errors.
- **Effort:** 1 hour
- **Dependencies:** None
- **Who:** samschillace

### T0.2: Clean test-agent debris from memory store
- [ ] **Status:** Todo
- **Repo:** ~/amplifier-dev-memory/
- **What:** Remove 66 `test-agent-*` directories created during
  testing. They waste disk and clutter listings.
- **Why:** Removes noise from environment.
- **Success:** `ls ~/amplifier-dev-memory/ | grep test-agent | wc -l` = 0
- **Effort:** 15 minutes
- **Dependencies:** None
- **Who:** samschillace

### T0.3: Enable team tracking
- [ ] **Status:** Todo
- **Repo:** ~/.amplifier/team-tracking.yaml
- **What:** Set `enabled: true`, verify `gh_handle`, run
  `check-sync-setup.yaml` recipe.
- **Why:** Provides data for friction analysis and team visibility.
- **Success:** `weekly-team-tracking-sync.yaml` runs without errors.
- **Effort:** 30 minutes
- **Dependencies:** None
- **Who:** samschillace, bkrabach

### T0.4: Document the current setup for team members
- [ ] **Status:** Todo
- **Repo:** amplifier-planning
- **What:** Write a QUICKSTART.md that captures today's manual setup
  steps: install CLI, set API keys, choose bundle, common gotchas.
- **Why:** Until the setup tool exists, new team members need a
  runbook. Also serves as the spec for what to automate.
- **Success:** A new team member can follow the doc and get working.
- **Effort:** 2 hours
- **Dependencies:** None
- **Who:** anyone

---

## Tier 1: Foundation Fixes (Weeks 1-2)

These fix the mechanisms that cause the most friction. Each is
a standalone PR to an existing repo.

### T1.1: Bundle validation strict mode
- [ ] **Status:** Todo
- **Repo:** amplifier-foundation
- **What:** Extend `BundleValidator.validate()` with `strict=True`:
  - Promote include resolution warnings to errors
  - Promote agent file load warnings to errors
  - Promote context path warnings to errors
  - Add env var detection (regex `${VAR}`, check os.environ)
  - Add module source pre-resolution check
- **Why:** #1 and #2 friction sources are silent failures.
- **Success:** Loading a bundle with a broken include raises an error
  instead of silently dropping the include.
- **Effort:** 2-3 days
- **Dependencies:** None
- **Who:** ramparte or anyone familiar with foundation

### T1.2: Cache auto-refresh on error
- [ ] **Status:** Todo
- **Repo:** amplifier-foundation
- **What:** In `session.py:initialize()` catch blocks, when a module
  fails to load, invalidate its cache entry and retry once.
  Also: add `max_age_hours` to `.amplifier_cache_meta.json`.
- **Why:** Breaks the "same error every day" groundhog loop.
- **Success:** A stale cached bundle that fails to load is
  automatically re-cloned on next session start.
- **Effort:** 2-3 days
- **Dependencies:** None
- **Who:** ramparte or foundation maintainer

### T1.3: Pre-flight health check (basic)
- [ ] **Status:** Todo
- **Repo:** amplifier-foundation + amplifier-app-cli
- **What:** After bundle load, before prepare():
  - Check env vars referenced in provider configs are set
  - Check bundle includes all resolved
  - Check at least one provider configured
  - Print clear pass/fail report
- **Why:** Catches config problems before you're 30 minutes into
  a session.
- **Success:** Starting a session with a missing API key shows
  a clear error with the specific key name, not a cryptic
  provider error 10 minutes later.
- **Effort:** 3-4 days
- **Dependencies:** T1.1 (validation strict mode provides checks)
- **Who:** anyone

### T1.4: Environment config section
- [ ] **Status:** Todo
- **Repo:** amplifier-app-cli
- **What:** Add `environment:` section to settings.yaml with:
  workspace, preflight.enabled, cache.max_age_hours,
  session.auto_handoff. Create `get_environment_settings()`.
- **Why:** Ring 1 components need a configuration home.
- **Success:** `settings.yaml` accepts environment section without
  errors. Pre-flight checks read from it.
- **Effort:** 1-2 days
- **Dependencies:** None
- **Who:** anyone

---

## Tier 2: Session Continuity (Weeks 2-4)

These fix the context loss problem - the #4 friction source.

### T2.1: SESSION_END kernel event
- [ ] **Status:** Todo
- **Repo:** amplifier-core
- **What:** Add `SESSION_END` to events taxonomy. Emit from
  `AmplifierSession.cleanup()` with session metadata
  (duration, turn count, tools used).
- **Why:** Prerequisite for handoff generation and clean shutdown.
- **Success:** `events.jsonl` contains a SESSION_END event at the
  end of every session.
- **Effort:** 1-2 days
- **Dependencies:** None (core change, coordinate with ramparte)
- **Who:** ramparte (core maintainer)

### T2.2: Auto-handoff generation
- [ ] **Status:** Todo
- **Repo:** amplifier-environment (new) or amplifier-foundation
- **What:** Hook that fires on SESSION_END:
  - Reads last N messages from context
  - Calls haiku to generate summary (fast, cheap)
  - Writes `handoff.md` to project directory
  - Includes: accomplishments, in-progress, decisions, next steps
- **Why:** Next session starts warm instead of cold.
- **Success:** After ending a session, `~/.amplifier/projects/<slug>/handoff.md`
  exists with a useful summary.
- **Effort:** 3-4 days
- **Dependencies:** T2.1 (SESSION_END event)
- **Who:** anyone

### T2.3: Handoff injection on session start
- [ ] **Status:** Todo
- **Repo:** amplifier-app-cli or amplifier-environment
- **What:** On session start, if a `handoff.md` exists for the
  current project directory, inject it as system context.
- **Why:** Completes the continuity loop: end -> handoff -> start.
- **Success:** Starting a new session in a project where a previous
  session ran shows "Continuing from: [handoff summary]" awareness.
- **Effort:** 2-3 days
- **Dependencies:** T2.2 (handoff generation)
- **Who:** anyone

---

## Tier 3: Interface Layer (Weeks 3-5)

These make Ring 2 interfaces work reliably. Can parallel with Tier 2.

### T3.1: Interface Adapter in foundation
- [ ] **Status:** Todo
- **Repo:** amplifier-foundation
- **What:** Create `amplifier_foundation.interface` module with:
  - `create_session(bundle_name, cwd, overrides)` - one-call session creation
  - `cleanup(session)` - guaranteed-completion shutdown
  - `OutputCallbacks` protocol for interface-specific rendering
- **Why:** Eliminates duplicated session lifecycle code across interfaces.
- **Success:** Voice and TUI can both use the adapter to create sessions
  with <10 lines of integration code.
- **Effort:** 2-3 days
- **Dependencies:** None
- **Who:** ramparte (foundation architect)

### T3.2: TUI - Rewrite session_manager.py
- [ ] **Status:** Todo
- **Repo:** amplifier-tui
- **What:** Replace sys.path hack + amplifier_app_cli imports with
  direct amplifier-foundation usage (Interface Adapter from T3.1).
  Add amplifier-core and amplifier-foundation as proper deps.
  Delete the sys.path walking code.
- **Why:** TUI is currently un-installable by anyone else.
- **Success:** `uv pip install -e .` works. No sys.path hacks.
  Session creates successfully using foundation API.
- **Effort:** 1 week
- **Dependencies:** T3.1 (Interface Adapter)
- **Who:** samschillace

### T3.3: TUI - Fix session save bug
- [ ] **Status:** Todo
- **Repo:** amplifier-tui
- **What:** Ensure SESSION_END and cleanup() complete before Textual
  exits. Options: Textual `on_unmount`, atexit handler, or
  synchronous cleanup in the quit handler.
- **Why:** Last turn lost on every quit+resume cycle.
- **Success:** Quit TUI, resume, last turn is present.
- **Effort:** 2-3 days
- **Dependencies:** T2.1 (SESSION_END event), T3.2 (rewrite)
- **Who:** samschillace

### T3.4: Voice - Extract hardcoded configs
- [ ] **Status:** Todo
- **Repo:** amplifier-voice
- **What:** Move hardcoded provider injection (Anthropic config,
  tool-delegate, model names) from amplifier_bridge.py into
  bundle YAML. Read user's active bundle from settings.yaml.
  Read workspace from environment config.
- **Why:** Currently only works on Sam's machine with Sam's paths.
- **Success:** Voice pipeline starts with any user's bundle config.
  No hardcoded paths or model names in Python code.
- **Effort:** 1 week
- **Dependencies:** T1.4 (environment config for workspace path)
- **Who:** samschillace or bkrabach

### T3.5: CarPlay - Consolidate on programmatic API
- [ ] **Status:** Todo
- **Repo:** carplay
- **What:** Delete subprocess-based amplifier_bridge.py. Make
  session_manager.py (programmatic) the only path. Add proper
  uv.sources for amplifier-core/foundation. Test with mock mode.
- **Why:** Two competing implementations, neither production.
- **Success:** `uv pip install -e .` works. Server starts and
  creates Amplifier session programmatically.
- **Effort:** 3-4 days
- **Dependencies:** T3.1 (Interface Adapter, optional but ideal)
- **Who:** samschillace

---

## Tier 4: Setup Tool (Weeks 4-6)

These compose Ring 1 and Ring 2 into the installer experience.

### T4.1: `amp env init` command (compiled)
- [ ] **Status:** Todo
- **Repo:** amplifier-app-cli
- **What:** Add `amp env` CLI group. `amp env init` detects
  platform, identity, providers, workspace, bundle health.
  Creates environment.yaml. Prints report.
- **Why:** First-run experience for any team member.
- **Success:** Running `amp env init` on a fresh machine produces
  a working configuration in <60 seconds.
- **Effort:** 3-4 days
- **Dependencies:** T1.3 (pre-flight), T1.4 (environment config)
- **Who:** ramparte or CLI maintainer

### T4.2: `amp env status` command (compiled)
- [ ] **Status:** Todo
- **Repo:** amplifier-app-cli
- **What:** Quick health report: identity, providers, bundle,
  cache freshness, last handoff, team tracking status.
- **Why:** "Is my environment healthy?" in 2 seconds.
- **Success:** `amp env status` runs in <3 seconds, shows clear
  pass/warn/fail for each component.
- **Effort:** 2-3 days
- **Dependencies:** T4.1 (init creates the config to check)
- **Who:** anyone

### T4.3: `amp env validate` recipe
- [ ] **Status:** Todo
- **Repo:** amplifier-environment
- **What:** Deep validation recipe: all include resolution,
  all module sources, all agent files, all context paths,
  env vars, model names, cache integrity. Full report.
- **Why:** Pre-commit or pre-deploy validation for bundle authors.
- **Success:** Running validate on a bundle with known errors
  catches all of them with clear messages.
- **Effort:** 2-3 days
- **Dependencies:** T1.1 (validation strict mode)
- **Who:** anyone

### T4.4: `amp env install <interface>` recipe
- [ ] **Status:** Todo
- **Repo:** amplifier-environment
- **What:** Per-interface install recipe that checks prerequisites,
  clones repo, installs deps, creates config, runs smoke test.
  One recipe per interface (install-voice.yaml, install-tui.yaml).
- **Why:** "How do I install voice?" -> one command.
- **Success:** `amp env install voice` on a machine with Python+Node
  produces a working voice interface.
- **Effort:** 1 week (all interfaces)
- **Dependencies:** T3.2-T3.5 (interfaces must be installable first)
- **Who:** anyone

---

## Tier 5: Workflows (Weeks 5-8+)

These are Ring 3 - where attention actually lives. Build these
after the foundation is solid.

### T5.1: Morning brief recipe
- [ ] **Status:** Todo
- **Repo:** amplifier-environment
- **What:** Recipe that runs at session start (or on demand):
  - Reads last handoff
  - Checks team tracking updates
  - Reads attention firewall L2 extractions
  - Reads idea funnel top priorities
  - Presents: "Here's what happened, here's what's hot, what
    would you like to focus on?"
- **Why:** North Star UX from the architecture vision.
- **Success:** Starting a session shows a useful, concise brief
  that takes <15 seconds to read.
- **Effort:** 3-4 days
- **Dependencies:** T2.2 (handoffs), T0.3 (team tracking)
- **Who:** samschillace

### T5.2: Idea funnel (capture + score)
- [ ] **Status:** Todo
- **Repo:** amplifier-environment or separate
- **What:** System for capturing ideas and scoring them:
  - Capture: "idea: [text]" natural language command
  - Store: YAML file (like memory store)
  - Score: LLM-based scoring on dimensions:
    impact, effort, urgency, dependency-count, attention-reduction
  - Surface: Top 5 ideas in morning brief
- **Why:** Currently ideas live in chat, memory, brainstorm docs.
  No single place to see "what should we work on next?"
- **Success:** "idea: bundle validation should auto-fix" stores and
  scores the idea. "show top ideas" shows ranked list.
- **Effort:** 1 week
- **Dependencies:** None (but more useful after T5.1)
- **Who:** samschillace

### T5.3: Friction detection recipe
- [ ] **Status:** Todo
- **Repo:** amplifier-environment
- **What:** Weekly recipe (alongside team-tracking) that:
  - Reads all sessions from the past week
  - Classifies friction signals (frustration, repetition, repair)
  - Produces friction report (score, top sources, trends)
  - Stores in `~/.amplifier/environment/friction-reports/`
- **Why:** Closes the self-improving loop: measure -> report -> fix.
- **Success:** Weekly friction report identifies the top 3 attention
  drains with actionable suggested fixes.
- **Effort:** 1 week
- **Dependencies:** Session analyst agent, team tracking data
- **Who:** anyone

### T5.4: Auto-fix proposals
- [ ] **Status:** Todo
- **Repo:** amplifier-environment
- **What:** When friction detection identifies a pattern that
  matches a known fix category (broken include, stale cache,
  missing config), automatically propose the fix:
  - Generate a PR or config change
  - Present to human for approval
  - Apply on approval
- **Why:** Level 4: the system fixes itself with human judgment only.
- **Success:** "Your top friction source was stale cache. I've
  proposed setting max_age_hours=168. Approve? [Y/n]"
- **Effort:** 2 weeks
- **Dependencies:** T5.3 (friction detection), T1.1-T1.3 (the fixes)
- **Who:** senior team member

---

## Dependency Graph

```
T0.1-T0.4 (immediate, no deps)
  |
  v
T1.1 (validation) -----> T1.3 (pre-flight) ----> T4.1 (init)
T1.2 (cache)              T1.4 (config)     \     T4.2 (status)
T1.4 (config) -----------> T3.4 (voice)      \--> T4.3 (validate)
  |                                                T4.4 (install)
  v
T2.1 (SESSION_END) --> T2.2 (handoff) --> T2.3 (inject) --> T5.1 (brief)
  |
  v
T3.1 (adapter) --> T3.2 (TUI rewrite) --> T3.3 (TUI save bug)
                   T3.5 (CarPlay)

T5.2 (idea funnel) - independent
T5.3 (friction) --> T5.4 (auto-fix)
```

---

## Estimated Timeline

| Week | Tasks | Milestone |
|------|-------|-----------|
| 1 | T0.1-T0.4, T1.1, T1.4 | Clean config, validation exists |
| 2 | T1.2, T1.3, T2.1 | Pre-flight works, SESSION_END in core |
| 3 | T2.2, T2.3, T3.1 | Session continuity, Interface Adapter |
| 4 | T3.2, T3.3 | TUI works properly |
| 5 | T3.4, T3.5, T4.1 | Voice/CarPlay fixed, init command |
| 6 | T4.2, T4.3, T4.4 | Setup tool complete |
| 7 | T5.1, T5.2 | Morning brief, idea funnel |
| 8 | T5.3, T5.4 | Self-improving loop running |

**Reality check:** This assumes ~50% of a person's time on environment
work. With 2-3 people contributing, compress to 4-5 weeks for Tiers 0-3.

---

## How to Use This List

1. **Pick a task** from the lowest incomplete tier
2. **Check dependencies** are done
3. **Read the referenced deep-dive doc** for technical details
4. **Do the task** in one session
5. **Ship the PR**
6. **Mark it done** here (check the box, add date)
7. **Pick the next task**

No planning meetings. No status updates. The list IS the plan.
The checkboxes ARE the status.
