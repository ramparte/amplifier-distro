# Architecture Vision: The Amplifier Environment

## The Mental Model

Think of it as three concentric rings, from most stable to most fluid:

```
┌─────────────────────────────────────────────────────────┐
│                    RING 3: WORKFLOWS                     │
│  Ideas, tasks, projects, attention filtering, reviews    │
│  (fluid - changes daily, adapts to what you're doing)    │
│                                                          │
│   ┌─────────────────────────────────────────────────┐   │
│   │              RING 2: INTERFACES                  │   │
│   │  CLI, TUI, Voice, Web, CarPlay, Telegram         │   │
│   │  (stable - pick one, it works everywhere)        │   │
│   │                                                  │   │
│   │   ┌─────────────────────────────────────────┐   │   │
│   │   │        RING 1: FOUNDATION               │   │   │
│   │   │  Dev folder, git, identity, config,     │   │   │
│   │   │  memory, bundles, health checks         │   │   │
│   │   │  (set once, never think about again)    │   │   │
│   │   └─────────────────────────────────────────┘   │   │
│   │                                                  │   │
│   └─────────────────────────────────────────────────┘   │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Ring 1** is what you set up once. It should be boring and invisible.
**Ring 2** is how you access Amplifier. Pick your interface, it just works.
**Ring 3** is where actual work happens. This is where attention should go.

The goal: Ring 1 absorbs zero ongoing attention. Ring 2 absorbs minimal
attention (muscle memory). Ring 3 gets all the attention.

---

## Ring 1: Foundation (Set Once, Forget)

### What it contains

1. **Dev Folder Convention**
   - `~/dev/ANext/` (or configured equivalent) as the canonical workspace
   - All repos cloned here. All projects created here.
   - Amplifier knows this is the workspace root.

2. **Identity & Config**
   - GitHub handle, API keys, provider preferences
   - Stored once in `~/.amplifier/` with validation
   - Team membership (for team-tracking, shared repos)
   - No per-project config needed for common cases

3. **Bundle Composition (Validated)**
   - A personal bundle (like my-amplifier) but with guardrails:
     - `amp env validate` catches silent include failures
     - Cache freshness checked at startup
     - Loud errors on invalid syntax (never silent drops)
     - "What loaded, what didn't, why" diagnostic on demand

4. **Memory Layer**
   - Dev memory (facts, preferences, decisions) - already working
   - Project context (auto-maintained per-project state) - needs building
   - Session handoffs (auto-generated on session end) - partially exists

5. **Health Monitoring**
   - Pre-flight checks on session start (fast, <2 seconds):
     - API keys valid?
     - Bundle parsed correctly?
     - Model names exist?
     - Required tools available?
   - Periodic background health check (sessions healthy? builds ok?)

### Setup Experience

```
$ amp env init
Amplifier Environment Setup
============================
Dev folder: ~/dev/ANext/ [detected from AGENTS.md]
GitHub: samschillace [detected from gh auth]
Provider: anthropic (claude-opus-4-6) [detected from settings]
Bundle: my-amplifier [detected from settings]

Running health check...
  ✓ API key valid
  ✓ Bundle loaded (47 modules, 23 agents)
  ⚠ 2 includes failed:
    - textbook-factory: relative path ./bundle.md not found
    - exp-delegation: repo not accessible
  ✓ Memory system initialized
  ✓ Attention firewall connected

Fix warnings? [Y/n]
```

This runs ONCE. After that, Ring 1 is invisible.

---

## Ring 2: Interfaces (Pick One, It Works)

### The Interface Contract

Every interface (CLI, TUI, Voice, Web, CarPlay, Telegram) should:
1. Connect to the same Amplifier session infrastructure
2. Access the same bundles, agents, memory, and project state
3. Support the same commands (natural language, slash commands)
4. Work without interface-specific configuration

### Current State vs Target

| Interface | Today | Target |
|-----------|-------|--------|
| CLI | Works, production | Keep as reference, add `amp env` commands |
| TUI | POC, session save bug | Fix bug, add streaming, make it the "rich terminal" option |
| Voice | Moderate, needs frontend | Stabilize, make it the "hands-free" option |
| Web | Moderate, two forks | Consolidate, make it the "GUI" option |
| CarPlay | Design only | Implement as voice-bridge to home desktop |
| Telegram | Active | Keep as "async/mobile" option |

### The Key Insight

These aren't competing interfaces - they're access patterns:
- **Desk work:** CLI or TUI (keyboard-focused, fast)
- **Monitoring:** AmpDash or Web (visual, overview)
- **Hands-free:** Voice (VR glasses, cooking, walking)
- **Mobile:** CarPlay or Telegram (away from desk)
- **Collaborative:** Web (screen sharing, demos)

A universal environment lets you switch between these without
reconfiguring anything. Same session state, same project context,
same memory, different viewport.

---

## Ring 3: Workflows (Where Attention Lives)

### The Workflow Stack

```
┌──────────────────────────────────────────────────┐
│ ATTENTION MANAGEMENT                              │
│ Filter stimulus → Surface what matters            │
│ (attention firewall, topic tracking, digests)     │
├──────────────────────────────────────────────────┤
│ IDEA CAPTURE & PRIORITIZATION                     │
│ Capture ideas → Score → Rank → Surface top ones   │
│ (idea funnel, natural language priority scoring)   │
├──────────────────────────────────────────────────┤
│ PROJECT EXECUTION                                 │
│ Plan → Implement → Validate → Ship                │
│ (project orchestrator, deliberate-dev, recipes)    │
├──────────────────────────────────────────────────┤
│ KNOWLEDGE & COMMUNICATION                         │
│ Remember → Synthesize → Present                   │
│ (dev memory, stories, dashboards, team tracking)   │
└──────────────────────────────────────────────────┘
```

### Attention Management (Mostly Exists)
- Attention firewall: real-time notification triage [working]
- Topic tracking: thread extraction across groups [working]
- Missing: automation of Layer 2 (currently human-triggered)
- Missing: integration with Amplifier session start ("here's what
  happened while you were away")

### Idea Capture & Prioritization (Needs Building)
The biggest gap in the current ecosystem. Today:
- Ideas live in WhatsApp groups, sessions, memory, heads
- No systematic capture, no scoring, no ranking
- Project orchestrator assumes you already have a feature inventory

What's needed:
- "Remember this idea: X" -> captured with context
- Periodic scoring: impact × feasibility × urgency
- "What should I work on?" -> ranked list with reasoning
- Cross-project portfolio view
- Natural language adjustments ("this is more urgent now because Y")

### Project Execution (Partially Exists)
- Project orchestrator: phase-based, fresh-session-per-task [alpha]
- Deliberate development: planner/implementer/reviewer [moderate]
- Recipes: multi-step workflows with approval gates [working]
- Missing: lightweight "today" mode (5 things, not 287 features)
- Missing: build state continuity across sessions
- Missing: automatic project context at session start

### Knowledge & Communication (Mostly Exists)
- Dev memory: facts and preferences [working]
- Stories: presentations [working]
- Team tracking: session sync and dashboards [configured, disabled]
- Missing: auto-generated project summaries
- Missing: "what did I accomplish this week?"

---

## Cross-Cutting Concerns

### Self-Healing
Every layer should detect and report its own problems:
- Ring 1: bundle validation, cache health, session integrity
- Ring 2: interface connectivity, API availability
- Ring 3: workflow state consistency, stale tasks, abandoned projects

Ideal: Amplifier itself runs periodic health checks and surfaces
issues proactively. "Your bundle cache is 3 days stale. 2 includes
are failing. Want me to fix?"

### Transparency
Every automated action should be explainable:
- Why was this notification suppressed? (rationale field)
- Why is this idea ranked #3? (scoring breakdown)
- What happened in the last session? (auto-summary)
- Why did this agent fail? (investigation, not apology)

### Extensibility
Adding a new workflow/behavior should be:
1. Write a bundle (YAML + context files)
2. `amp env add <bundle>`
3. It works (validated, cached, connected to memory)

Not:
1. Write a bundle
2. Debug silent include failures
3. Manually clear cache
4. Re-debug
5. Realize branch name is wrong
6. Fix, retry, eventually works

---

## The North Star UX

Morning routine:
```
$ amp
Good morning. Since your last session:
  - 3 topics updated in WhatsApp groups (AI orchestration,
    voice pipeline, agent loops)
  - 2 ideas captured from conversations (auto-extracted)
  - Build for word3 is green, lifeline has 2 test failures

Your top priorities today (based on current scoring):
  1. Voice pipeline: WebRTC client missing [high impact, low effort]
  2. Bundle validation: fix silent include failures [high impact, med effort]
  3. CarPlay: implement basic voice bridge [medium impact, med effort]

What would you like to focus on?
```

That's the experience when Ring 1 and Ring 2 are invisible and
Ring 3 is doing its job.
