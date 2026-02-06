# The Self-Improving Loop

The most important idea in this entire project: an environment that
detects its own friction and reduces it over time, with minimal
human attention.

## Why This Matters

Every other piece of this project is a point solution. Bundle validation
fixes bundle errors. Session handoffs fix context loss. But the *system*
keeps generating new friction sources because:

1. New tools get added (each brings config surface area)
2. Models change (new capabilities, new failure modes)
3. Team grows (more diverse setups, more edge cases)
4. Projects evolve (new patterns, new requirements)

A static solution decays. A self-improving loop adapts.

## The Loop

```
         ┌─────────────────────────────┐
         │                             │
         ▼                             │
┌─────────────────┐          ┌─────────┴─────────┐
│   1. OBSERVE    │          │   4. VERIFY       │
│                 │          │                    │
│ Analyze sessions│          │ Did friction go    │
│ for friction    │          │ down? Measure.     │
│ patterns        │          │                    │
└────────┬────────┘          └─────────▲─────────┘
         │                             │
         ▼                             │
┌─────────────────┐          ┌─────────┴─────────┐
│   2. DIAGNOSE   │          │   3. ACT          │
│                 │          │                    │
│ Classify root   │          │ Apply fix:         │
│ cause, estimate │          │ - config change    │
│ attention cost  │          │ - new recipe       │
│                 │          │ - behavior update  │
└────────┬────────┘          │ - documentation    │
         │                   │                    │
         └──────────────────►└────────────────────┘
```

## Layer 1: Session Friction Detection (Automated)

**What:** After each session (or weekly batch), analyze the session
transcript for friction signals.

**Friction signals to detect:**
- User frustration language ("still getting errors", "this is broken")
- Repeated context re-explanation (same info provided 3+ times)
- Repair session launches (session whose purpose is fixing another)
- Configuration debugging cycles (bundle errors, API key issues)
- Long stretches with no productive output
- Apology spirals (5+ "I apologize" without progress)

**How:** This could be a recipe that runs on the team-tracking
weekly schedule. The session-analyst agent already exists and can
read transcripts. Add a "friction scoring" prompt that classifies
each session's friction level and root causes.

**Output:** A friction report:
```json
{
  "week": "2026-W06",
  "sessions_analyzed": 45,
  "friction_score": 0.42,
  "top_friction_sources": [
    {"category": "bundle_config", "count": 8, "trend": "stable"},
    {"category": "context_loss", "count": 6, "trend": "improving"},
    {"category": "session_corruption", "count": 3, "trend": "worsening"}
  ],
  "suggested_actions": [
    "Bundle validation errors are stable at 8/week - the validation
     tool hasn't been adopted yet. Consider making it a startup hook.",
    "Context loss improved from 12 to 6 - handoff generation is working.
     Consider making it the default.",
    "Session corruption is worsening - investigate new orchestrator
     version for regression."
  ]
}
```

## Layer 2: Diagnostic Agent (Semi-Automated)

**What:** When a friction pattern is identified, a diagnostic agent
investigates the root cause and proposes a fix.

**Example flow:**

1. Friction detector flags: "bundle_config errors: 8 sessions this week"
2. Diagnostic agent:
   - Reads the 8 session transcripts for specific errors
   - Identifies: "5 of 8 are the same `memory-system-overview.md` path error"
   - Checks: "This was 'fixed' on Feb 3 but the fix wasn't pushed to remote"
   - Proposes: "Push the fix AND add a pre-commit hook that validates bundle syntax"
3. Human reviews proposal: "Yes, do it" (10 seconds of attention)
4. Agent executes the fix

**Key principle:** The diagnostic agent does the investigation. The human
only provides judgment ("yes, do that" or "no, try something else").
Investigation is cheap (inference). Judgment is expensive (attention).

## Layer 3: Proactive Health Monitoring (Aspirational)

**What:** The environment continuously monitors its own health and
surfaces problems before they cause friction.

**Examples:**
- "Your bundle cache is 5 days old. 3 upstream repos have new commits.
  Refresh? [Y/n]"
- "The attention firewall hasn't ingested any messages in 48 hours.
  The daemon may have stopped."
- "Session corruption rate increased 2x this week. This correlates
  with the orchestrator update on Tuesday. Consider rolling back."
- "You have 12 ideas captured but haven't reviewed priorities in
  2 weeks. Want to do a quick triage?"

**Implementation:** A background recipe (cron-triggered, like team-tracking)
that runs health checks and writes findings to a "health report" file.
The morning brief recipe reads this file.

## Layer 4: Pattern Library (Long-term)

**What:** As friction patterns are identified and solved, the solutions
become reusable patterns that the system applies automatically to
new situations.

**Example:**
- Pattern: "Silent include failure" -> Fix: "Validate on load, fail loud"
- This pattern gets encoded as a general rule: "Any configuration that
  can fail silently MUST have a validation step that fails loudly"
- When a new bundle is created, the system automatically checks: "Does
  this have silent failure modes?" and warns if so.

This is the longest-term aspiration - a system that accumulates
operational wisdom.

---

## Practical Starting Point

Don't try to build all four layers at once. Start with:

### Week 1: Manual Friction Review
- Run the friction analysis done in this research as a monthly review
- Track friction score over time in a simple file
- No automation, just awareness

### Week 2-3: Friction Detection Recipe
- Adapt the session analysis pattern into a recipe
- Runs weekly alongside team-tracking
- Outputs a friction report to a known location

### Week 4-6: Morning Brief Integration
- Morning brief recipe reads the friction report
- Surfaces "your top friction source this week was X"
- Suggests one action to reduce it

### Month 2+: Diagnostic Agent
- Semi-automated investigation of top friction patterns
- Human approves/rejects proposed fixes
- Track whether fixes actually reduce friction

### Month 3+: Proactive Monitoring
- Background health checks
- Proactive alerts (not just reactive detection)
- Pattern library starts accumulating

---

## The Meta-Point

This self-improving loop IS the project management strategy for
this entire effort. Instead of planning every feature upfront:

1. Build the loop (friction detection + measurement)
2. Let the loop tell you what to build next
3. Build it
4. Measure whether friction went down
5. Repeat

This is how you manage a large, evolving project without the project
management itself becoming an attentional burden. The system tells
you what hurts most, you fix that, and the system confirms it's
better. No Gantt charts, no sprint planning, no status meetings.
Just a feedback loop between measurement and action.

---

## Connection to Anthropic Compiler Patterns

The parallel-Claude compiler project (see 06-anthropic-patterns.md)
solved a related problem: how do you manage autonomous agents working
on a large codebase?

Their key insight: **Tests replace human oversight.** If the agent can
verify its own work against tests, it doesn't need a human watching.

Our equivalent: **Friction metrics replace project management.** If
the system can measure its own friction, it doesn't need a human
planning what to improve next. The metric IS the plan.

Their approach:
- Write tests first (oracle-driven)
- Let agents work autonomously
- Tests catch regressions
- Humans only intervene for design decisions

Our approach:
- Measure friction first (session analysis)
- Let the system suggest improvements
- Friction scores catch regressions
- Humans only intervene for judgment calls
