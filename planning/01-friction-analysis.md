# Friction Analysis: Where Human Attention Goes to Die

Source: Analysis of 91 user-facing sessions, ~3,320 total sessions (including
sub-agents), Jan 23 - Feb 6, 2026.

## The Headline

~45% of Amplifier time in this period was spent on friction rather than the
actual work intended. Six categories, ranked by severity.

---

## 1. SESSION CORRUPTION & REPAIR CYCLES [Critical]

**What happens:** Sessions break mid-flight (dangling tool calls, context
overflow, unproductive loops). New sessions must be launched just to diagnose
and repair the broken ones.

**Scale:** 9+ sessions dedicated entirely to repairing other sessions. Worst
case: one broken session required 3 separate repair sessions.

**Attentional cost:** Incident response - reactive, urgent, unplanned. Each
repair cycle is 10-30 minutes of pure plumbing.

**User workaround (invented manually):** "Can you start a fresh amplifier
session yourself and prompt it carefully to fix those issues?" - manually
orchestrating around a reliability gap.

**What a universal environment should do:**
- Auto-recovery from dangling tool calls
- Graceful degradation instead of corruption
- Session health monitoring that catches problems before they compound
- Never require a human to launch a "repair session"

---

## 2. SILENT BUNDLE CONFIGURATION FAILURES [Critical]

**What happens:** Bundle includes fail silently. The `_parse_include()`
function only recognizes `bundle:` key - using `behavior:` or `module:`
produces zero warnings but drops the entire include. Agents don't appear,
with no diagnostic information about why.

**Scale:** 9+ sessions, same errors recurring across days/weeks. Sessions on
Feb 3 and Feb 4 report identical errors. "I am still getting errors on
update. Invoke the bundle expert and FIX these bundles!"

**Recurring offenders:**
- memory-system-overview.md - invalid relative path
- session-discovery - self-referencing URI
- m365-collab - missing behaviors, circular tool reference
- amplifier-toolkit - missing root bundle.md for monorepo
- attention-firewall - wrong module reference syntax

**Root causes:** Stale git cache, untracked files not pushed to remote, no
validation at authorship time, monorepo subdirectory resolution confusion.

**What a universal environment should do:**
- Validate bundles at authorship time (pre-load diagnostic)
- Loud failure on invalid includes (never silent)
- Cache freshness verification at startup
- Bundle health dashboard showing what loaded, what failed, why

---

## 3. AGENT COMPETENCE / TRUST FAILURES [High]

**What happens:** AI makes architectural pronouncements without investigating,
hallucinates features, and requires repeated correction.

**Scale:** 58 user frustration signals across 28 sessions.

**Worst examples:**
- Agent invented `amplifier compose` - a CLI command that doesn't exist
- Agent claimed repo didn't exist when it did
- Agent reported project as "production ready" when text was white-on-white
- 9 consecutive "I apologize" messages before any real work happened

**What a universal environment should do:**
- Structural enforcement: investigate before claiming
- Pre-loaded project context so agents start informed
- Trust signals: show evidence for claims, not just conclusions
- Failure acknowledgment without apology spirals

---

## 4. CROSS-SESSION CONTEXT LOSS [High]

**What happens:** When work spans multiple sessions, critical context
evaporates. Architecture decisions, project goals, and what was already
tried must be re-explained.

**Scale:** 80 "repeat context" signals across 26 sessions.

**Examples:**
- "I thought we had built a word backend that would run on the server...
  Did I misunderstand what the project is?"
- User spent 6 turns rebuilding context. Response: "Ok, that's really
  superficial."
- "I asked session X to evaluate lifeline. I'm not entirely sure I trust
  it... Did it do the work? or just make it up?"

**What a universal environment should do:**
- Persistent project-level context files maintained automatically
- Architecture decisions, goals, and current state survive sessions
- "What happened last time" summary available at session start
- Handoff documents generated automatically on session end

---

## 5. BUILD RECOVERY MARATHONS [High]

**What happens:** Builds break catastrophically and require dedicated recovery
sessions, often in "STRICT MODE."

**Scale:** 5+ sessions dedicated to recovering broken builds in one project
alone. Error counts: 168 -> 572 in one recovery attempt.

**Friction density by project (signals per session):**
- lifeline: 129
- cascade: 113
- wordbs: 103
- word3: 49
- ANext: 31

**What a universal environment should do:**
- Incremental validation (the 3-file rule, but enforced, not advisory)
- Build state continuity across sessions
- Error context preservation: what was tried, what failed, what the
  hypothesis was

---

## 6. ENVIRONMENT & SANDBOX FRICTION [Medium]

**What happens:** Write path restrictions block cross-repo workflows. WSL
cross-filesystem I/O pain. Hardcoded developer defaults in shared tools.

**Scale:** 6+ sessions, plus friction embedded in many others.

**Examples:**
- Working from ~/dev/ANext/word3 but needing to edit a bundle repo
  elsewhere -> Access Denied
- 21-turn marathon migrating from /mnt/c/ANext to ~/dev/ANext
- Brian's bundle name hardcoded in amplifier-voice
- Invalid model names causing silent agent failures

**What a universal environment should do:**
- Workspace-aware write permissions (not just CWD)
- Developer identity/config separate from tool defaults
- Startup validation of API keys, model names, paths

---

## The Attention Cost Model

| Category | Type | Cost |
|----------|------|------|
| Session repair | Incident response | Reactive, urgent, unplanned |
| Bundle config | Groundhog Day | Re-solving already-solved problems |
| Agent competence | Babysitting | Monitoring and correcting AI |
| Context loss | Re-orientation | Rebuilding shared understanding |
| Build recovery | Janitorial | Cleaning up cascading messes |
| Environment | Plumbing | Fighting infrastructure |

The first two categories (session repair + bundle config) are the most
actionable because they're structural problems with structural fixes.
The agent competence and context loss categories are harder but have
higher long-term payoff.
