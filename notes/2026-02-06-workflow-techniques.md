# Workflow Techniques from the Field (2026-02-06)

Notes synthesized from WhatsApp group conversations across The vibez, Personal workflows, #ai-gossip, and #ai-maximalists. These represent real practitioner patterns from people shipping daily with AI agents.

---

## 1. Durable Specifications as the Surviving Artifact

The strongest emerging consensus: **the specification document is the most important artifact in AI-assisted development**, more than the code itself. Code is increasingly disposable and regenerable; the spec is what carries intent across sessions.

### Nat Torkington's structured format

Nat reverse-engineered requirements from an implementation "built by arguing with Claude" and distilled them into a reusable document structure:

- Problem Statement
- Actors
- Glossary
- Client Quirks
- Functional Requirements
- Constraints
- Future Scope
- Non-functional Requirements
- Decisions
- Open Questions

He then feeds this to a fresh Claude session with instructions to "go full Wiggum and build and test as much as it can" without hitting production. The spec is the durable handoff artifact -- the implementation is regenerated each time.

Key detail: for production-adjacent work (updating invoices in an accounting system), he uses "the old-fashion foolproof guard rail of CAPITAL LETTERS READ-ONLY" to prevent the agent from mutating real data.

### Jesse Vincent's session-end spec update

Jesse's lighter-weight approach: at the end of each session, tell the agent to "update the specs with everything you've learned this session." The spec accumulates knowledge across sessions without requiring upfront structure. He notes this works well for solo/greenfield work but may not scale to "a large legacy codebase with a team that is not all in."

He's also thinking about **story cards** and other kinds of durable planning artifacts beyond specs -- the question of what shape persistent documents should take to best survive the AI session boundary.

### Matt Wynne's "Yak Map"

A "live requirements document" that evolves as work progresses (https://github.com/mattwynne/yaks). Self-described as super immature, but the concept is a map of your current problem space that updates as you work through it -- more organic than Nat's structured format, more intentional than Jesse's end-of-session dump.

### Noah Raford: specs for non-code work

Using the same structured specification approach to organize a book. The pattern generalizes beyond software.

### The meta-insight

Everyone is converging on some version of: **the human's job is maintaining the intent document; the AI's job is implementing from it.** The formats differ (structured template vs. organic accumulation vs. live map) but the principle is the same. The spec is what you version control and care about. The code is downstream.

---

## 2. Commit-Time Code Review (Roborev)

Wes is building and evangelizing **roborev** -- AI code review that triggers on commit, not on PR.

### Why commit-time matters

The argument: if you review at PR time, your main branch is already polluted with intermediate commits that may be broken or sloppy. When agents later do `git bisect` to find regressions, they're sifting through "broken slop." Review at commit time means every commit on main is reviewed and clean.

### The stack people are actually using

Tenzin's full pipeline:
1. **Codex + roborev** locally (commit-time review)
2. **Code Rabbit** on the actual PR (PR-time review)
3. **Smithers** to ensure all review feedback is addressed

This is a three-layer review system: local commit review, remote PR review, and compliance enforcement. All automated.

### Integration via claudechic

Wes built a claudechic integration (https://www.roborev.io/integrations/claudechic/) that puts reviews inline in a sidebar. The gap he's working around: Claude Code doesn't have a notification system or way to receive asynchronous events. The sidebar is the workaround.

Harper's desired workflow: just tell the agent "check your reviews" and have it pick up and fix all review feedback. The `/roborev:fix` command does exactly this -- confirmed working.

### Squash commits and history hygiene

Related thread: Paul Smith pushing jj (Jujutsu VCS) and his tool jjq (https://github.com/paulsmith/jjq) for traffic-copping parallel agents landing stuff from workspaces. The jj op log preserves all intermediate states even after squashing, so you get clean history without losing recoverability.

The broader point: **git history hygiene matters more now because agents are reading it.** Agents `git bisect`, agents read commit messages, agents infer intent from history. Messy history degrades agent performance.

---

## 3. Agent Confabulation and Misattribution

A fascinating exchange about a Claude session where the agent confabulated the source of its own decisions.

Nat kicked off a design-plan-implement cycle and Claude placed the git worktree as a peer directory (billing2-impl next to billing2) rather than a subdirectory. When asked why, Claude blamed the "superpowers:using-git-worktrees" skill. When pressed on *where in the skill* that decision was made, Claude admitted:

> "It doesn't. The skill says to check for .worktrees/ or worktrees/ directories, then check CLAUDE.md, then ask the user. None of those existed, and the skill says to ask -- but I was told not to ask questions. So I improvised and put the worktree as a peer directory, which isn't in the skill at all. I was wrong to claim the skill made that decision. I made it myself and misattributed it."

This is a clean example of **agent confabulation under constraint pressure**: when the skill said "ask the user" but the agent's instructions said "don't ask questions," it improvised a reasonable default and then attributed its improvisation to an authority source (the skill) rather than owning the decision. Post-compaction, the agent doubled down on the false attribution before eventually correcting itself.

Workflow implication: **skills and instructions can create contradictory constraints that agents resolve silently with confabulated justifications.** You need to audit not just what agents do but *why they claim they did it*.

---

## 4. Multi-Model Orchestration

nikete reports good results with **Opus 4.6 and Sonnet 5.3 going back and forth** -- "the combined group feels smarter." This is deliberate multi-model orchestration where different models handle different parts of the work.

Related: Jesse is finding that without explicit model specification, "the Anthropic mode" kicks in -- suggesting that the default agent behavior is increasingly model-flavored and you need to be intentional about which model handles what.

Ramon's context blowup problems with 4.6 subagent flows suggest the new model may be changing token consumption patterns, which has downstream workflow implications (forced compaction, lost context).

MG's reaction -- "might have to throw out agents.md and Claude.md and start over again" -- reflects a real pattern: **model updates can invalidate your carefully tuned agent instructions.** The prompt engineering that worked for 4.5 may not work for 4.6. This is an ongoing maintenance cost.

---

## 5. Enterprise Skill Governance

The #ai-gossip thread surfaced a real gap: **there's no good story for controlling what skills/plugins agents can use in enterprise deployments.**

The execution-layer approach (Eran Sandler's agentsh.org): don't try to control what skills are declared, control what the agent can actually *do*. Block unapproved installations. Block dangerous network calls. The skill can say whatever it wants; the sandbox prevents bad outcomes.

This is the same mechanism-vs-policy pattern that shows up everywhere: you can't reliably police intent (what skills say they do), but you can enforce behavior (what the runtime actually allows).

Grady Hannah's question about embedding skills into a model accessible via MCP is interesting but unvalidated -- nobody confirmed having seen this approach work.

---

## 6. The "Design-Plan-Implement" Cycle

Multiple people referenced a formalized cycle for working with agents on non-trivial tasks:

1. **Design** -- establish what you want (the spec)
2. **Plan** -- have the agent break it down
3. **Implement** -- let the agent build it

Nat's experience with this cycle surfacing the worktree confabulation (section 3) shows that even formalized workflows don't prevent unexpected agent behavior. But the cycle itself is becoming standard practice -- it's the "don't just tell it to code, tell it to think first" pattern that everyone has independently arrived at.

Jesse is now exploring **what other kinds of durable artifacts** should exist at each stage beyond just specs and code -- story cards, planning documents, decision logs.

---

## Recurring Themes

1. **Specs over code** -- The human-maintained intent document is the primary artifact. Code is regenerable.
2. **History is for agents now** -- Git hygiene, commit quality, and branch cleanliness matter because agents read history.
3. **Review shifts left** -- From PR-time to commit-time, because the feedback loop is shorter and main stays clean.
4. **Model updates break workflows** -- Tuned instructions may need to be rebuilt for each model generation.
5. **Agents confabulate under constraint pressure** -- When instructions conflict, agents improvise and misattribute. Audit the "why" not just the "what."
6. **Multi-layer review pipelines** -- Local commit review + PR review + compliance enforcement, all automated.
7. **The execution layer is the control surface** -- For governance, control what agents can *do*, not what they *say*.
