# Pieces and Priorities

Every component mapped by maturity, effort, and attentional payoff.

## Maturity Assessment

### Already Working (Preserve, Don't Reinvent)

| Component | What It Does | Owner | Notes |
|-----------|-------------|-------|-------|
| CLI | Reference Amplifier interface | Microsoft | Production quality |
| Bundle composition | Compose modules into configs | Microsoft | Works when syntax is right |
| Dev memory | Persistent facts across sessions | ramparte | Simple, local, token-efficient |
| Attention firewall L1 | Real-time notification triage | sam/brian | 534 msgs triaged, works well |
| Deliberate development | Plan/implement/review/debug cycle | ramparte | Moderate maturity |
| Stories/presentations | HTML decks from natural language | ramparte | 11 forks, actively used |
| Session isolation | Fresh session per task | Amplifier | Core architecture strength |
| Agent delegation | Specialist agents with domains | Amplifier | Core architecture strength |
| Recipes | Multi-step workflows with gates | Microsoft | Working, used regularly |

### Partially Working (Fix and Extend)

| Component | What It Does | Gap | Effort |
|-----------|-------------|-----|--------|
| Voice pipeline | Speech-to-speech via Realtime API | Missing WebRTC client, Brian-specific defaults | Medium |
| TUI | Rich terminal interface | Session save bug, no streaming | Low-Medium |
| Web interface | Browser-based GUI | Two forks need consolidation | Low |
| Attention firewall L2 | Topic extraction from groups | Human-triggered only, no automation | Low |
| Project orchestrator | Phase-based project management | Alpha, Word3-specific, no idea funnel | High |
| Team tracking | Session sync and dashboards | Configured but disabled | Low |
| Bundle validation | Catch config errors | Silent failures, no pre-load check | Medium |
| Project context | Per-project state across sessions | Handoffs exist but not auto-generated | Medium |

### Needs Building (New Capabilities)

| Component | What It Would Do | Priority | Effort |
|-----------|-----------------|----------|--------|
| `amp env init` | One-time setup with validation | HIGH | Medium |
| `amp env validate` | Bundle + config health check | HIGH | Low-Medium |
| Idea funnel | Capture -> triage -> score -> rank | HIGH | Medium |
| Session morning brief | "What happened since last time" | HIGH | Medium |
| Auto-handoffs | Generate session handoff on exit | MEDIUM | Low |
| Pre-flight checks | Validate APIs/models/bundles at start | MEDIUM | Low |
| Cross-project portfolio | "What's most important across all?" | MEDIUM | Medium |
| Self-healing diagnostics | Detect and fix own problems | MEDIUM | High |
| Interface switcher | Same session, different viewport | LOW | High |
| CarPlay bridge | Voice from car to home desktop | LOW | Medium |

---

## Priority Framework

Rank by: (Attention saved per week) x (Inverse of effort)

### Tier 1: High Impact, Achievable Now

These are the "early wins" - things that would immediately reduce
attentional load with relatively low effort.

**1. Bundle Validation Tool** (effort: days)
- `amp env validate` or equivalent
- Catches silent include failures BEFORE session start
- Shows what loaded, what failed, why
- Eliminates the #2 friction category entirely
- Could be a recipe or a simple script initially

**2. Pre-Flight Health Checks** (effort: days)
- Run at session start, fast (<2 seconds)
- API key valid? Bundle parsed? Model names exist?
- Eliminates "30 minutes in before discovering config is broken"
- Could be a hook that runs on session:start

**3. Auto-Generate Session Handoffs** (effort: days)
- On session end, write a handoff doc to `.project/handoffs/`
- Summary of what was done, decisions made, current state
- Next session can read it automatically
- Reduces cross-session context loss (#4 friction category)

**4. Morning Brief Recipe** (effort: 1-2 weeks)
- Recipe that runs on first session of the day:
  - Check attention firewall for updates since last session
  - Check build status of active projects
  - Surface top ideas/priorities
  - Show session handoffs from yesterday
- The "North Star UX" described in architecture vision

**5. Activate Team Tracking** (effort: hours)
- Already configured, just disabled
- Turn it on, start getting team dashboards
- Low effort, immediate team visibility

### Tier 2: High Impact, More Effort

**6. Idea Funnel System** (effort: 2-4 weeks)
- Capture ideas from any source (voice, chat, WhatsApp extraction)
- Natural language scoring: impact x feasibility x urgency
- "What should I work on?" query
- Could start as a memory-store extension with scoring fields
- Could evolve into a proper tool module

**7. Session Resilience** (effort: 2-4 weeks)
- Auto-recovery from dangling tool calls
- Graceful degradation instead of corruption
- Requires changes to orchestrator/session code
- Eliminates #1 friction category

**8. Persistent Project Context** (effort: 2-4 weeks)
- Auto-maintained `.project/context.md` per project
- Updated after each session with architecture decisions, goals, state
- Loaded automatically at session start
- Reduces context loss dramatically

**9. Voice Pipeline Stabilization** (effort: 2-3 weeks)
- Fix WebRTC client (may need to clone/build separately)
- Remove hardcoded defaults (Brian's bundle name, etc.)
- Make it "install and use" for any team member
- Enables hands-free and VR access patterns

### Tier 3: Aspirational / Long-term

**10. Self-Improving Diagnostics** (effort: months)
- Amplifier periodically analyzes its own sessions for friction
- Surfaces patterns, suggests fixes, auto-applies some
- The "meta-system" described in self-improving-loop.md

**11. Universal Interface Layer** (effort: months)
- Same session accessible from any interface
- Switch from CLI to Voice to Web mid-conversation
- Requires session sharing infrastructure

**12. Autonomous Attention Firewall** (effort: months)
- Layer 2 runs automatically (not human-triggered)
- Topic extraction happens on schedule
- Cross-references with idea funnel
- "This conversation is relevant to your #3 priority"

**13. Large Project Management** (effort: months)
- Project orchestrator generalized beyond Word3
- Domain-agnostic (not just web apps)
- Portfolio view across projects
- Lightweight "today" mode alongside "287 features" mode

---

## Suggested Execution Order

### Phase 1: "Stop the Bleeding" (Week 1-2)
- Bundle validation tool
- Pre-flight health checks
- Activate team tracking
- Clean up known config issues (HTTP->HTTPS, stale refs, debris)

### Phase 2: "Context Continuity" (Week 3-4)
- Auto-generate session handoffs
- Morning brief recipe (v1: simple, manual trigger)
- Persistent project context (v1: template-based)

### Phase 3: "Idea Flow" (Week 5-8)
- Idea funnel system (v1: capture + simple scoring)
- Attention firewall L2 automation
- Voice pipeline stabilization

### Phase 4: "Self-Improvement" (Ongoing)
- Session resilience improvements
- Self-diagnosing health checks
- Friction pattern detection
- Continuous refinement based on actual usage data

---

## What's Aspirational vs What's Mostly Working

### Mostly Working (80%+ there)
- Bundle composition (needs validation, not replacement)
- Attention firewall Layer 1 (real-time triage)
- Dev memory system
- CLI interface
- Deliberate development cycle
- Stories/presentations
- Team tracking (just needs enabling)

### Partially Working (40-60% there)
- Voice pipeline (architecture solid, needs polish)
- TUI (POC works, needs bug fixes)
- Web interface (works, needs consolidation)
- Project orchestrator (ideas good, implementation narrow)
- Session handoffs (concept exists, not automated)

### Aspirational (<20% there)
- Idea funnel and priority scoring
- Self-healing diagnostics
- Universal interface switching
- CarPlay/mobile access
- Autonomous attention management
- Large project portfolio management
- Morning brief / proactive intelligence

### Key Insight

The gap between "partially working" and "mostly working" is often
quite small - a validation tool, a bug fix, enabling a flag. The
highest ROI is in closing those small gaps, not building new
aspirational features from scratch.
