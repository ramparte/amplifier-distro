# Current Landscape: What Exists Today

## The Team

17 GitHub accounts across 3 sub-teams:
- **Sam's team:** marklicata, michaeljabbour, dluc
- **Brian's team:** bkrabach, robotdad, payneio, DavidKoleczek, momuno
- **Chris's team:** cpark4x, samueljklee, anderlpz, singh2, johannao76,
  kenotron (2 accounts), manojp99, sadlilas

Key builders for this effort: Sam, Brian (bkrabach), Mark Goodner (robotdad),
Michael Jabbour (michaeljabbour), Mark Licata (ramparte/marklicata).

---

## Interfaces (How Humans Talk to Amplifier)

| Interface | Owner | Maturity | Tech | Key Strength |
|-----------|-------|----------|------|--------------|
| **CLI** | Microsoft | Production | Python | Reference impl, most stable |
| **Voice** | robotdad | Moderate (18 commits) | FastAPI + OpenAI Realtime + WebRTC | Real-time speech-to-speech |
| **TUI** | ramparte | Early POC (7 commits) | Python Textual | Rich terminal, session sidebar |
| **Web** | team | Moderate | FastAPI + React/TS | WebSocket streaming, approvals |
| **Web-Unified** | team | Moderate | Fork of Web + voice | Web + voice integration |
| **CarPlay** | samschillace | Design only (1 commit) | FastAPI + Siri Shortcuts + Tailscale | Mobile/driving access |
| **Telegram** | ramparte | Active | Bot API hooks + polling | Messaging app interface |
| **AmpDash** | team | Early (5 commits) | Python Textual | Read-only session monitoring |

**Notable:** No single interface is "complete." Each solves a different
access pattern (desk, terminal, car, VR glasses, phone). The voice pipeline
is the most architecturally interesting - it uses OpenAI Realtime for voice
I/O and routes all real work to Amplifier/Claude via a single `delegate` tool.

**Brian's VR setup:** Uses tmux + wezterm on VR glasses. The voice pipeline
was built for this use case - hands-free interaction while wearing a headset.

**Gap:** No unified "start here" for new team members. Each interface is a
separate repo with separate setup steps.

---

## Bundles & Behaviors (What Amplifier Can Do)

### Sam's my-amplifier bundle (v1.11.0)

Inherits from amplifier-dev and composes 7 sub-bundles:

```
my-amplifier
├── amplifier-dev (from amplifier-foundation)
│   └── foundation (all the core behaviors, agents, tools)
├── dev-memory-behavior (persistent memory across sessions)
├── agent-memory (vector/qdrant-based memory)
├── session-discovery
├── deliberate-development (planner/implementer/reviewer/debugger)
├── made-support
├── amplifier-stories (presentation creation)
└── project-orchestration (large project management)
```

Plus custom tools (attention-firewall) and context files (user-habits).

**Known fragility points:**
- `behavior:` vs `bundle:` include syntax confusion (silent failures)
- `@master` vs `@main` branch inconsistency
- HTTP vs HTTPS in one URL
- Broken relative paths (textbook-factory)
- Two bundles that never load (textbook-factory, exp-delegation)
- 66 test-agent-* directories in memory (4.2MB of debris)
- Foundation included redundantly by multiple sub-bundles

### Key Ecosystem Bundles

| Bundle | Owner | Purpose | Maturity |
|--------|-------|---------|----------|
| **Design Intelligence** | Microsoft | 7 design agents | Published |
| **Project Orchestrator** | ramparte | Phase-based project mgmt (100-300+ features) | Alpha (5 commits) |
| **Deliberate Development** | ramparte | Planner/implementer/reviewer/debugger cycle | Moderate |
| **Stories** | ramparte | HTML presentation creation (11 forks) | Moderate |
| **PR Review** | robotdad | PR review workflow | Active |
| **Modes** | Microsoft | plan/careful/explore mode switching | Published |
| **Vibe Tools** | ramparte | 6 behaviors + 6 recipes from practitioner community | Active |
| **Module Builder Skill** | michaeljabbour | Meta-tool for building Amplifier modules | Active |

---

## Attention Management (The Firewall)

Two-layer architecture at `/mnt/c/Users/samschillace/.attention-firewall/`:

**Layer 1: Real-time Triage** (autonomous)
- Intercepts Windows notifications (WhatsApp=515, Camera=8, etc.)
- Decision hierarchy: Suppress patterns > VIP sender > Priority keywords > App default
- Outputs: surface (56), processed (431), digest (41), suppressed (6)
- Auto-refreshing HTML dashboard
- 4 daily digest windows (morning, midday, afternoon, EOD)

**Layer 2: Topic Extraction** (human-triggered)
- "Update me on the WhatsApp groups" -> Amplifier session
- AI extracts/clusters conversational threads
- TopicTracker persists to SQLite (16 threads, 19 updates currently)
- Supports watching/tracking specific topics

**Missing pieces:**
- No ingestion engine in the directory (lives elsewhere)
- No digest/dashboard generators visible
- Teams configured but zero messages ingested
- No automation of Layer 2 (always human-triggered)

---

## Project State & Memory

### Dev Memory System
- File-based at `~/amplifier-dev-memory/`
- 15 memories stored (team structure, tool locations, preferences, principles)
- Work log for active task tracking
- Read delegation pattern (sub-agent absorbs token cost)

### Project Orchestrator State
- File-based JSON at `.project/state.json` (v2) or `.longbuilder/state/` (v1)
- Tracks: phases, tasks, features, handoffs, session logs
- **Missing:** Idea capture, priority scoring, cross-project view, backlog funnel

### Session Data
- 89 project directories in `~/.amplifier/projects/`
- ~20GB of session data
- Session index for discovery
- Team tracking configured but disabled

---

## Configuration Pain Points (Specific Issues Found)

| Issue | Location | Impact |
|-------|----------|--------|
| `behavior:` includes silently dropped | Foundation registry | Critical - agents disappear |
| Stale git cache | `~/.amplifier/cache/` | Same errors recurring daily |
| `@master` vs `@main` | amplifier-stories | Will break on branch rename |
| HTTP not HTTPS | project-orchestrator URL | Insecure, may fail |
| Broken relative path | textbook-factory | Never loads |
| 66 test-agent-* dirs | `~/.amplifier/memory/` | 4.2MB debris |
| Foundation included 3x | deliberate-dev, made-support | Composition overhead |
| Dual state paths | project-orchestrator | v1 vs v2 schema confusion |

---

## What's Actually Working Well

Not everything is friction. Things that work and should be preserved:

1. **The bundle composition model itself** - when it works, it's elegant
2. **The attention firewall concept** - real-time triage saves significant attention
3. **Voice pipeline architecture** - clean separation of voice I/O from intelligence
4. **Dev memory system** - simple, local, human-readable, token-efficient
5. **Deliberate development cycle** - planner/implementer/reviewer pattern is sound
6. **Session-based isolation** - fresh session per task prevents context pollution
7. **Stories/presentations** - polished output from a simple command
8. **The agent delegation model** - specialist agents with domain expertise

These should be first-class capabilities in any universal environment.
