# Project Structure: How to Build This

## The Meta-Problem

This project is about reducing attentional load. The project itself
must not become an attentional load. That means:

1. No big-bang delivery (nothing works until everything works)
2. Each piece delivers value independently
3. Start/stop friendly (pick up any task, do it, put it down)
4. The project uses its own tools (dogfood the environment)
5. Progress is visible without status meetings

---

## Reconciling with Prior Thinking

The Jan 22 brainstorm produced a project-based 18-week plan that
was explicitly superseded. Brian proposed Level 4 (self-improving),
Sam agreed. The pivot was: don't pre-plan everything, let failures
drive construction.

This environment project IS the Level 4 vision, grounded in friction
data. Rather than "let Amplifier build itself" (aspirational), we
start with "make the environment stop wasting attention" (measurable).

**How they connect:**
- Level 4's "shared memory" = Ring 1's session handoffs + memory
- Level 4's "monitoring" = Ring 1's health checks + friction detection
- Level 4's "visibility dashboard" = Ring 2's interfaces
- Level 4's "self-improving loop" = Ring 3's friction -> fix -> measure cycle
- Level 4's "goal queue" = environment.yaml's workflows section

We're not abandoning Level 4. We're building its foundation with
concrete, measurable friction reduction.

---

## Repository Structure

Everything lives in `amplifier-planning` (brainstorming + design) and
eventually `amplifier-environment` (implementation).

### Phase 1: Planning (amplifier-planning repo - NOW)

```
amplifier-planning/
  environment/                    # This research + design
    00-research-index.md          # Navigation
    01-friction-analysis.md       # Data: where attention goes
    02-current-landscape.md       # What exists today
    03-architecture-vision.md     # Three-ring model
    04-pieces-and-priorities.md   # Maturity + effort mapping
    05-self-improving-loop.md     # The meta-system
    06-anthropic-patterns.md      # Lessons from parallel-Claude
    07-ring1-deep-dive.md         # Technical gaps in foundation
    08-ring2-deep-dive.md         # Technical gaps in interfaces
    09-setup-tool.md              # Installer specification
    10-project-structure.md       # This file
    11-task-list.md               # Ordered, start/stop friendly
    research-anthropic-compiler.md
  (existing brainstorm files)     # Jan 22 Level 4 thinking
  archive/                        # Superseded project-based plan
```

### Phase 2: Implementation (amplifier-environment repo - FUTURE)

```
amplifier-environment/
  bundle.md                       # Thin bundle: the environment behavior
  behaviors/
    environment.yaml              # Composes all Ring 1 behaviors
    preflight.yaml                # Pre-flight checks behavior
    handoff.yaml                  # Session handoff behavior
  agents/
    setup-agent.md                # Interactive setup assistant
    health-agent.md               # Environment health diagnostics
    friction-agent.md             # Friction detection + reporting
  context/
    environment-instructions.md   # How the environment works
  recipes/
    init.yaml                     # First-time setup
    validate.yaml                 # Deep validation
    install-voice.yaml            # Install voice interface
    install-tui.yaml              # Install TUI
    morning-brief.yaml            # Daily intelligence brief
    friction-report.yaml          # Weekly friction analysis
    health-check.yaml             # Periodic health monitoring
  scripts/
    preflight.py                  # Pre-flight check implementation
    handoff.py                    # Session handoff generation
    cache-manager.py              # Cache TTL + integrity checks
  docs/
    SETUP.md                      # User-facing setup guide
    ARCHITECTURE.md               # Ring 1/2/3 explained
```

### Where Changes Land

Not everything lives in amplifier-environment. Some fixes go to
existing repos:

| Change | Where It Goes | Why |
|--------|--------------|-----|
| Bundle validation (strict mode) | amplifier-foundation | Core mechanism |
| SESSION_END event | amplifier-core | Kernel event |
| Interface Adapter | amplifier-foundation | Shared library |
| `amp env` subcommands | amplifier-app-cli | CLI surface |
| Pre-flight checks | amplifier-environment | Policy |
| Handoff generation | amplifier-environment | Policy |
| Cache TTL / auto-refresh | amplifier-foundation | Mechanism |
| TUI session_manager rewrite | amplifier-tui | Interface fix |
| Voice hardcoded extraction | amplifier-voice | Interface fix |
| Morning brief recipe | amplifier-environment | Workflow |
| Friction detection recipe | amplifier-environment | Workflow |

**The pattern:** Mechanisms go to core/foundation. Policies go to
amplifier-environment. Interface fixes go to interface repos.

---

## Execution Model: Incremental Delivery

### The "One Task, One PR" Rule

Each task in the task list (11-task-list.md) is designed to be:
- Completable in one session (1-4 hours)
- Deliverable as one PR to one repo
- Independently valuable (delivers benefit even if nothing else ships)
- Testable (has a clear "did it work?" check)

This is the start/stop model: pick up a task, do it, ship it,
walk away. No multi-day state to maintain. No "phase 2 depends
on phase 1 depends on phase 0."

### Using Project Orchestrator

The task list could be fed to the project orchestrator as a feature
inventory. Each task becomes a "feature" with:
- Clear specification (from the deep-dive docs)
- Success criteria (from the task description)
- Dependencies (from the dependency column)

The orchestrator would then:
1. Pick the next unblocked task
2. Spawn a fresh session
3. Implement the task per spec
4. Validate via the success criteria
5. Create a PR
6. Move to the next task

This is dogfooding: using the project orchestrator to build the
environment that makes the project orchestrator better.

### Tracking Progress

Progress tracked in three places (pick one, not all three):

**Option A: Task list in this repo (simplest)**
- `11-task-list.md` with checkboxes
- Update on each PR
- Git log shows when each was completed

**Option B: GitHub Issues**
- One issue per task
- Labels for ring, priority, effort
- Project board for kanban view
- More overhead, better visibility for team

**Option C: Idea Funnel (dogfood)**
- Each task is an "idea" in the idea funnel
- Scored by impact x effort
- System surfaces top priority
- Most ambitious, most circular (building the tool to track building the tool)

**Recommendation:** Start with Option A (task list in this repo).
Graduate to Option B when team members start contributing.
Option C is the long-term vision but requires the idea funnel to exist.

---

## Work Allocation

Based on who built what and knows what:

| Area | Best Person(s) | Reason |
|------|---------------|--------|
| Bundle validation (foundation) | ramparte, bkrabach | Foundation maintainers |
| SESSION_END event (core) | ramparte | Core maintainer |
| Interface Adapter (foundation) | ramparte | Foundation architect |
| TUI rewrite | samschillace | TUI owner, knows the intent |
| Voice extraction | samschillace, bkrabach | Voice users, know the pain |
| Setup tool (CLI) | ramparte | CLI maintainer |
| Pre-flight checks | anyone | New code, clear spec |
| Session handoffs | anyone | New code, clear spec |
| Cache management | ramparte | Foundation cache owner |
| Morning brief recipe | samschillace | Knows the desired UX |
| Friction detection | samschillace, bkrabach | Session data owners |
| CarPlay consolidation | samschillace | CarPlay owner |

**Key insight:** The "anyone" items are great onboarding tasks for
new team members or for Amplifier itself (Level 4 goal: "build
pre-flight checks").

---

## How This Relates to the Self-Improving Loop

Once Phase 1 tasks are done (bundle validation, pre-flight, handoffs),
we have the foundation for the self-improving loop:

1. **Measure:** Friction detection recipe runs weekly
2. **Report:** Morning brief surfaces top friction source
3. **Fix:** Human picks a task from the friction report
4. **Verify:** Next week's friction report shows improvement

The task list in 11-task-list.md is the INITIAL set of tasks, driven
by the friction analysis in 01-friction-analysis.md. But after the
loop is running, the task list is generated by the friction detector,
not by human analysis.

That's the transition from "project management" to "self-improving
system": the system tells you what to fix next.

---

## Decision Log

| Decision | Rationale | Date |
|----------|-----------|------|
| Three-ring architecture | Separates set-once from pick-one from daily-use | 2026-02-06 |
| Separate environment.yaml from settings.yaml | Avoid conflicts with Amplifier CLI updates | 2026-02-06 |
| Hybrid setup tool (compiled + recipes) | init/status must work pre-bundle; validate/install extensible | 2026-02-06 |
| One task, one PR rule | Start/stop friendly, independently valuable | 2026-02-06 |
| Task list in repo (not GitHub Issues initially) | Simplest option, upgrade when team joins | 2026-02-06 |
| Mechanisms in core/foundation, policies in environment | Follows kernel philosophy (mechanism not policy) | 2026-02-06 |
