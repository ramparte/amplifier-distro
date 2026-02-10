# The Agent-Shaped OS

## The Observation

Some projects work remarkably well with agents. Others fight them at every turn.

The ones that work -- amplifier-stories, the TUI test system, this distro -- share a pattern that isn't about model quality or prompt engineering. It's structural. They give agents primitives that fit the way agents actually think: simple, orthogonal, text-native, composable. The ones that struggle do the opposite: they force agents through human-shaped interfaces -- visual tools, complex SDKs, binary formats, multi-step GUIs.

There's a useful analogy from linear algebra. **Eigenvectors** are the natural basis of a transformation -- the directions that don't fight the system, they align with it. The projects that work have discovered the eigenvectors of agent capability: primitives that don't fight the LLM's nature, they amplify it.

This document argues that these eigenvectors form something coherent: an **Agent-shaped Operating System**. Not a replacement for the human OS, but a parallel layer optimized for a fundamentally different kind of user. And the distro is the right place to build it.

---

## The Disease: Human as Integration Layer

Before getting into what agents need, it's worth naming what's broken today.

Every tool has its own interface. Every interface has its own rules. And you -- the human -- become the integration layer. You copy data from one app into another. You translate between formats. You remember what lives where. You are the glue between systems that don't talk to each other.

The interface evolution tells the story:

```
Command Line → GUI → Mobile → Voice → Intent
```

Each step reduced the distance between what you want and what you have to say to get it. Command lines required you to know the system's language. GUIs required you to navigate the system's spatial layout. Mobile required you to find the right app. Voice required you to speak the right command.

The next step -- **intent** -- eliminates the translation entirely. You say what you want: "organize my downloads," "find the PDF from last month," "show me what's eating disk space." The system figures out how to execute.

This is the Agent-shaped OS from the human's perspective. The human stops being the integration layer. The agent becomes the integration layer instead -- and unlike the human, the agent doesn't mind. Integration is what agents are good at: reading structured data, calling APIs, transforming formats, coordinating between systems. The human provides intent and judgment. The agent handles everything between intent and outcome.

The distro's One Rule -- minimize human attentional load -- is this same idea expressed as a design goal. The Agent OS is the architecture that makes the goal achievable.

---

## Why Agents Need Different Primitives

Traditional operating systems were designed around a core assumption: **the user is a human sitting at a screen.** Everything flows from that. Windows, icons, menus, pointers. Visual file managers. Interactive terminals with color and cursor positioning. Drag-and-drop. Undo buttons. Tooltips.

These are good design choices for humans. Humans are visual, associative, have limited working memory but extraordinary pattern recognition. We need redundant pathways to the same capability (menu + keyboard shortcut + right-click + toolbar button) because discoverability matters when you can't read the manual in 200ms.

LLMs are the inverse:

| Human Strength | Agent Strength |
|----------------|----------------|
| Visual pattern recognition | Text processing at scale |
| Spatial reasoning | Following precise contracts |
| Learning by exploration | Executing documented procedures |
| Associative memory | Perfect recall within context window |
| Handling ambiguity gracefully | Handling structured data precisely |

When we force agents through human-shaped interfaces -- clicking buttons via screenshot analysis, navigating GUIs pixel by pixel, parsing binary formats through libraries -- we're asking them to work against their grain. It works, sort of, the way a human can do arithmetic on paper. But it's slow, error-prone, and misses the point.

The emerging data confirms this. Computer-use agents (screenshot + click) run at ~87-94% reliability and cost 4-7x more in tokens than agents using structured APIs for the same tasks. Every major coding agent -- Devin, Codex, Cursor, Windsurf -- converges on the same three primitives: a shell, a text editor, and a browser. Not a GUI IDE. Not a visual debugger. Shell, editor, browser. Text in, text out.

The question isn't whether agents need different primitives. They do. The question is: **what's the minimal, complete, orthogonal set?**

---

## The Eigenvector Test

Before proposing the set, we need a way to evaluate candidates. A primitive is "agent-shaped" -- an eigenvector of agent capability -- when it satisfies these properties:

| Property | What It Means | Failure Mode |
|----------|---------------|-------------|
| **Text-native** | Can be read, written, and reasoned about as plain text | Binary formats, pixel data, audio streams |
| **Zero-SDK** | Usable without installing libraries or learning frameworks | React, python-pptx, complex ORMs |
| **Composable** | Combines with other primitives without special integration | Tightly-coupled APIs requiring orchestration |
| **Schema-describable** | Can be fully explained in a tool description | Tools requiring "feel" or visual judgment |
| **Deterministic shape** | Same kind of input always yields same shape of output | APIs with wildly varying response structures |
| **Append-friendly** | New state can be added without rewriting old state | Formats requiring full-file rewrite to modify |

These aren't arbitrary criteria. They map directly to LLM capabilities and constraints:

- **Text-native** because LLMs are text-in, text-out machines. Their training data is text. Their context window is text. Their output is text.
- **Zero-SDK** because every library is a dependency the agent must understand, install, and debug. The fewer moving parts, the fewer failure modes.
- **Composable** because agents build complex behavior by combining simple operations. If primitives require glue code to work together, the agent spends tokens on plumbing instead of work.
- **Schema-describable** because the agent's only interface to a tool is its description. If you can't explain it in a paragraph, the agent can't use it reliably.
- **Deterministic shape** because agents parse outputs programmatically. Varying shapes require branching logic that burns context and introduces errors.
- **Append-friendly** because agents work incrementally. They add commits, append log entries, write new files. Rewriting existing state is expensive and error-prone.

The stories bundle passes every test. Git is text-native (diffs are text), zero-SDK (bash commands), composable (branches + PRs + tags combine freely), schema-describable, deterministic, and append-friendly (commits are append-only). HTML is the same: the agent writes a `.html` file directly, opens it in a browser, iterates. No build step. No framework. No SDK.

The TUI's SVG test system passes too. Visual state captured as SVG gets parsed into structured YAML -- text-native, diffable, deterministic. The agent never needs to "see" anything. It reads structured data about what's on screen.

**An important distinction:** The eigenvector test applies to the **primitives**, not to the **world the primitives act on.** Agents frequently work with non-text artifacts -- images, audio, compiled binaries. The command `convert image.png -resize 50% image_small.png` is text-native. The image it operates on isn't. The shell command is the eigenvector; the image is the operand. This prevents the test from being read too narrowly. The Agent OS doesn't require a text-only world. It requires text-native _tools_ for interacting with whatever the world contains.

---

## The Seven Eigenvectors

Here's the proposed orthogonal basis for an Agent-shaped OS. Each primitive is independent -- knowing one tells you nothing about another. Together, they span the full space of what an agent needs to do.

### 1. Text Files on a Filesystem

**The atom. Everything reduces to this.**

The agent's native medium is text. Its context window is a text buffer. Its output is text. The filesystem provides namespace (paths), persistence, and the most universal API in computing (open, read, write, close).

**Formats that work:** Markdown, YAML, JSON, JSONL, HTML, CSS, SQL, shell scripts, SVG, TOML. All text. All in training data. All writable without libraries.

**What they replace:** Databases for configuration. GUIs for state management. Binary formats for data interchange. An agent can write a YAML config file as naturally as writing prose -- because to the agent, it IS prose.

**Evidence from our projects:**
- The distro stores everything as text: `distro.yaml`, `memory-store.yaml`, `work-log.yaml`, `keys.yaml`, `conventions.py`
- Stories outputs HTML, Markdown, CSS -- all text files that ARE the deliverable
- The TUI test system produces YAML analysis files from SVG captures
- The m365 platform defines safety policies as Python code (text)

The filesystem is not just storage. It's the agent's workspace, its scratchpad, its communication channel. When two agents need to share state, a file in a known location is often the simplest, most reliable mechanism.

---

### 2. Git

**The coordination layer.**

Git might be the most agent-shaped tool ever built, despite being designed 20 years before LLMs existed. It provides six capabilities that would otherwise require six separate systems:

| Capability | What Git Provides | What Humans Use Instead |
|------------|-------------------|------------------------|
| **Version control** | Every state is recoverable | Undo buttons, Time Machine, file copies |
| **Isolation** | Branches -- one per task, no interference | Separate folders, separate machines |
| **Review** | Diffs are text. PRs are structured review | Screen sharing, pair programming |
| **Approval gates** | PRs with required reviewers | Meeting sign-offs, email chains |
| **Publishing** | `git push` is deployment | FTP, deploy scripts, app stores |
| **Audit trail** | Commit history with timestamps and authorship | Spreadsheets, change logs, meeting notes |

For agents, git is even better. An agent can create a branch, make changes, commit with a meaningful message, and open a PR -- all through bash commands that produce text output. The entire collaboration model (propose, review, revise, approve, merge) maps directly onto git's existing workflow. No custom infrastructure needed.

**Evidence:**
- Stories mines git history as data (`git log`, `git tag`, `gh pr list`), stores generated content via commits, publishes via GitHub Pages, and gates releases via PRs
- The distro backs up to a git repo
- Every major coding agent uses git as its primary coordination mechanism: Devin creates branches, Codex produces patches, Copilot opens draft PRs
- SWE-bench's output format is literally a git diff

Block (Square) found that when building 60+ MCP servers, git remained the coordination backbone.

**The coordination spectrum.** Git is the right default, but coordination scales with context. For a single user running a single agent on a laptop, branches and PRs can be heavier ceremony than the task warrants. The Agent OS should work naturally across the full range:

| Scale | Natural Coordination |
|-------|---------------------|
| Single-user, single-agent | Shared filesystem + memory state |
| Single-user, multi-agent | SQLite + JSONL event streams |
| Multi-user / team | Git branches + PRs |
| Enterprise | Git + policy mesh + approval gates |

The distro defaults to git -- the benefits are real even at small scale (undo, audit, publishing). But the architecture shouldn't require a PR to save a memory.

---

### 3. Shell (Bash)

**The execution layer.**

Bash is the universal API. Every capability on a Unix system is reachable through a shell command. The pattern is: text in, text out, composable via pipes.

**Why it works for agents:**
- Thousands of tools with text interfaces, already documented in training data: `ls`, `grep`, `curl`, `git`, `docker`, `gh`, `jq`, `sed`, `awk`
- Pipes and redirects give agents compositional power: `git log --oneline | grep "feat:" | wc -l`
- Every new tool automatically becomes an agent capability just by being installed
- Error messages are text. Exit codes are simple. No exception hierarchies to navigate.

**The key insight from industry:** Block discovered that their 30-tool MCP server for Linear worked best when collapsed to 2 tools: `execute_readonly_query` and `execute_mutation_query`. Anthropic reports that Claude Code's most powerful tool is shell access. The pattern is clear: rather than wrapping every capability in a custom tool schema, **give the agent a shell and let it compose.**

This doesn't mean agents should ONLY have bash. Purpose-built tools with clear schemas reduce errors for common operations. But bash is the escape hatch, the universal adapter, the "everything else" primitive. When an agent needs to do something no one anticipated, bash is how it gets done.

**Evidence:**
- The distro's CLI (`amp-distro`) is a set of bash-invocable commands
- Stories' deploy workflow is a shell script
- The TUI test runner is invoked from shell
- The m365 platform's tools are all CLI-invocable

---

### 4. HTML

**The presentation layer.**

This is the most surprising eigenvector, and perhaps the most important insight for agent-native design. HTML is the agent's natural presentation format:

- **Zero build step.** Write a `.html` file, open it in a browser. No webpack, no npm, no framework, no compilation. The file IS the deliverable.
- **Self-contained.** A single file with inline CSS and JS works. No dependency tree. No `node_modules`. No broken imports.
- **Deeply in training data.** Every LLM knows HTML, CSS, and vanilla JS intimately. It's one of the most represented format families in existence.
- **Semantic structure.** The DOM is the content model. `<div class="slide">`, `<h1>`, `<table>` -- the agent reasons about structure, not pixels.
- **Universal viewer.** Every device on earth has a browser. HTML is the most portable rich-presentation format ever created.
- **Conversion source.** HTML can be mechanically converted to PowerPoint, PDF, images, Word docs. Write once in the canonical format, convert to others.

Contrast with the alternatives:
- **PowerPoint**: Binary format, requires python-pptx, can't be diffed, can't be previewed without Office
- **React/Vue**: Requires a build toolchain, framework knowledge, package management. The framework IS the complexity.
- **Native apps**: Platform SDKs, compilation, signing, distribution. Completely opaque to agents.
- **PDF**: Write-only from the agent's perspective. Can't be meaningfully edited or iterated on.

The stories bundle proves this. It produces all presentations as single-file HTML with inline CSS and ~50 lines of vanilla JS for navigation. The storyteller agent writes HTML directly. The `html2pptx.py` converter exists only for the human-side requirement of PowerPoint files -- the canonical format is HTML.

**Evidence:**
- Stories: all presentations as self-contained HTML files
- The distro: web chat, voice UI, install wizard, Slack simulator -- all HTML served by FastAPI
- The TUI: captures visual state as SVG (an HTML-adjacent structured format)
- Industry: every coding agent with a browser tool (Devin, Windsurf) can produce and preview HTML natively

---

### 5. SQLite

**The structured state layer.**

Text files work beautifully for configuration and simple state. But when an agent needs to **query** data -- not just read it, but ask questions across it -- it needs something more. SQLite is the agent-native database:

- **Single file.** No server, no connection string, no setup, no migrations. A `.db` file IS the database.
- **Text-native query language.** SQL is in every LLM's training data. Agents write SQL as naturally as prose.
- **Portable.** Copy the file, you've moved the database. Works anywhere, any platform.
- **Zero dependencies.** Built into Python's standard library. Built into most languages.
- **Extensible.** Vector search extensions for semantic queries. Full-text search built in.

Block's insight is instructive. They replaced individual API-wrapping tools for Google Calendar with a DuckDB-backed query tool. "Find a 1-hour slot where Alice, Bob, and Carol are all free" became a single SQL query against synced calendar data. The agent writes SQL, not API calls.

Turso's AgentFS takes this further: the **entire agent runtime** -- files, state, history, context -- stored in a single SQLite file. Portable, forkable, versionable.

The distro currently uses YAML for everything. That works for dozens of memories and a handful of config files. It won't work for thousands of memories, cross-session queries, or multi-agent shared state. SQLite is the natural next step -- and the attention firewall already demonstrates this pattern with `notifications.db` and `topics.db`.

---

### 6. HTTP/REST

**The communication layer.**

HTTP is the universal transport. It serves every communication need an agent has:

| Need | HTTP Pattern |
|------|-------------|
| Call an API | REST request (GET/POST/PUT/DELETE) |
| Discover tools | MCP (JSON-RPC over HTTP) |
| Talk to other agents | A2A protocol (HTTP + SSE) |
| Receive events | Webhooks (POST to callback URL) |
| Stream data | Server-Sent Events (SSE) or WebSocket |
| Serve content | Static file serving over HTTP |

The emerging protocol stack is clear: **MCP** for agent-to-tool communication (how an agent discovers and invokes capabilities), **A2A** for agent-to-agent communication (how agents exchange tasks and results). Both built on HTTP. Both JSON-based. Both schema-driven.

The important thing is not the specific protocols but the underlying primitive: **text-based messages over a universal transport**. Agents don't need new networking paradigms. They need clean, well-described HTTP endpoints.

**Evidence:**
- The distro: full REST API surface (`/api/health`, `/api/memory/*`, `/api/sessions`, `/api/bridge/*`)
- Slack bridge: HTTP webhooks for events, REST for API calls
- Voice bridge: HTTP for session creation and WebRTC signaling
- The m365 platform: Microsoft Graph API is REST over HTTP

---

### 7. JSONL (Append-Only Event Streams)

**The observability layer.**

The final eigenvector is the structured event stream. JSONL -- one JSON object per line, append-only -- is the agent-native format for everything that happens over time:

- **Append-only.** Write-optimized. No locking, no transactions, no full-file reads. Just append a line.
- **Streamable.** Process line by line. No need to parse the whole file. Tail it in real-time.
- **Structured.** Each line is a self-contained JSON object. Parseable, filterable, transformable.
- **Diffable.** Git can diff JSONL files meaningfully. New lines = new events.
- **Replayable.** An event stream is a complete record. You can reconstruct any past state by replaying events up to a point.

This enables: session replay, deterministic testing (replay a trace with stubs), audit trails, debugging (what did the agent do and when?), and inter-agent coordination through shared event streams.

Anthropic's guidance on agent testing explicitly recommends event traces as the foundation for evaluation. Their pattern: record all agent actions as structured events, replay them deterministically, grade outcomes not paths.

**Evidence:**
- Amplifier core: `events.jsonl` and `transcript.jsonl` for all session state
- Stories: mines session events for case studies and metrics
- Team tracking: analyzes event streams for team dashboards and productivity metrics
- Industry: every agent framework uses structured logging as the primary debugging mechanism

---

## The Completeness Argument

These seven primitives span the full space of agent capability. Any task an agent needs to perform can be expressed as a combination of them:

| Agent Task | Eigenvectors Used |
|------------|-------------------|
| Create a presentation | HTML + Git + Shell |
| Build and test software | Text files + Git + Shell + JSONL |
| Communicate with humans | HTTP + HTML + Text files |
| Remember across sessions | SQLite + Text files + Git |
| Execute safely in isolation | Shell (in sandbox) + JSONL (audit) + HTTP (policy) |
| Test and validate work | Text files (SVG to YAML) + Shell (run tests) + JSONL (results) |
| Coordinate with other agents | HTTP (MCP/A2A) + JSONL (shared state) + Git (shared workspace) |
| Manage enterprise systems | HTTP (APIs) + SQLite (local state) + JSONL (audit) + Git (versioning) |

And they're orthogonal. Git tells you nothing about HTML. SQL tells you nothing about Shell. JSONL tells you nothing about HTTP. Each operates independently, can be learned independently, and can be replaced independently.

---

## The Stack: An Agent-Shaped OS

These seven eigenvectors organize into a coherent stack. Each layer builds on the ones below, and each is constructed entirely from the seven primitives:

```
 Layer 8 : Intent            Natural language → structured dispatch (the intent kernel)
 Layer 7 : Workflows         Recipes, multi-agent pipelines, approval gates
 Layer 6 : Applications      Slack bridge, voice, web chat, vibe coder
 Layer 5 : Services          Memory, backup, diagnostics, policy, model routing
 Layer 4 : Presentation      HTML generation, SVG testing, dashboards
 Layer 3 : Coordination      Git (branches, PRs, diffs), MCP, A2A
 Layer 2 : State             SQLite (structured), YAML (config), JSONL (events)
 Layer 1 : Execution         Shell/Bash, sandboxes (Docker/microVM)
 Layer 0 : Foundation        Text files on a filesystem
```

Layer 8 is the newest idea and the most important from the human's perspective. Everything below it is infrastructure -- how agents work. Layer 8 is the interface -- how humans _use_ agents. The user says what they want. The intent kernel decides where it goes. The stack executes. The result comes back as HTML, a Slack message, a committed diff, or a voice response.

This is different from Layer 7 (Workflows). Workflows are multi-step orchestrated pipelines defined in advance. The intent kernel is single-turn dispatch: classify what the user wants, route to the right agent or tool, return the result. It's the thin reasoning layer between natural language and OS capability.

Some design questions the intent kernel raises:
- **Model sizing.** Classification doesn't need a frontier model. A small, fast model (~1B parameters, ~100ms) handles "is this a file question or a code question?" The execution agent behind it can use whatever model the task demands. Speed changes the feel of the system -- sub-second classification makes the OS feel responsive rather than deliberative.
- **Escape hatches.** Sometimes you know where you want to go. Slash commands (`/terminal`, `/memory`, `/voice`) should bypass classification entirely. The intent kernel should be the default path, not the only path.
- **Confidence routing.** Low classification confidence should trigger clarification, not a guess. "Did you mean X or Y?" is better than silently doing the wrong thing.

The traditional OS has the same layered structure -- kernel, drivers, system services, window manager, applications. The difference is what's natural at each layer:

| Layer | Human OS | Agent OS |
|-------|----------|----------|
| Foundation | Files, directories, permissions | Text files on a filesystem |
| Execution | Processes, threads, signals | Shell commands, sandboxed containers |
| State | RAM, virtual memory, databases | SQLite, YAML, JSONL |
| Coordination | IPC, sockets, shared memory | Git, MCP, A2A |
| Presentation | Pixels, windows, GPU rendering | HTML, SVG, Markdown |
| Services | System daemons, control panel | Memory, backup, policy, model routing |
| Applications | GUI apps with menus and windows | Bridges (Slack, voice, web) |
| Workflows | Cron, task scheduler, automations | Recipes, agent pipelines |
| Intent | App launcher, Spotlight, Start menu | LLM-as-router, natural language dispatch |

---

## Where the Distro Stands Today

The distro is already building large parts of this stack. Here's the honest assessment:

| Layer | Status | What Exists |
|-------|--------|-------------|
| **Foundation** | Solid | `distro.yaml`, `conventions.py`, memory files, all text-based |
| **Execution** | Solid | `amp-distro` CLI, Docker Compose for testing |
| **State** | Partial | YAML for config and memory. No SQLite yet. JSONL via amplifier-core. |
| **Coordination** | Partial | Git for backup only. No MCP/A2A. No git-as-workflow. |
| **Presentation** | Solid | Web chat, voice UI, install wizard, Slack simulator -- all HTML |
| **Services** | Solid | Memory, backup, preflight, doctor, watchdog, all working |
| **Applications** | Solid | Slack bridge, voice bridge, web chat, install wizard |
| **Workflows** | Early | Recipes exist but aren't deeply integrated into the distro |

The foundation is strong. The gaps are specific and addressable.

---

## The Plan: Completing the Agent OS

### Gap 1: SQLite as a First-Class Primitive

**The problem.** The distro uses YAML for memory (`memory-store.yaml`). This works for tens of memories. It won't scale to thousands, and it can't support queries like "what have I worked on in the last week that relates to authentication?" without loading everything into context.

**The plan.**

1. **Tiered memory architecture.** Not a flat table swap from YAML, but a system designed with retrieval tiers from the start:

    | Tier | Storage | Window | Access Pattern | Purpose |
    |------|---------|--------|----------------|---------|
    | **Hot** | In-memory | Current session + last ~20 interactions | O(1), instant | Immediate context |
    | **Warm** | SQLite with FTS | Last ~500 interactions | Temporal scan + full-text | Recent history, "what was I doing last week?" |
    | **Cold** | SQLite with vector extension | Unbounded | Semantic search | Long-term recall, "anything I've done related to auth?" |

    Every query hits both warm (last 5 entries for recency) and cold (top 3 matches for relevance) and injects both into the agent's context. This dual-retrieval -- temporal + semantic -- is simple but meaningfully better than either alone.

2. **Migrate the attention firewall pattern.** The `topic_tracker.py` + `notifications.db` pattern already works. The memory service should follow the same shape: SQLite for queries, Python helper for typed access. The YAML file becomes a human-readable export, not the source of truth.

3. **Agent-queryable memory.** Expose a `query_memory(sql)` tool that lets agents write SQL against their memory store. Block proved this pattern: agents are excellent at writing SQL. Don't force them through a fixed API when a query language is more expressive.

4. **Portable state.** Following Turso's AgentFS concept: one `.db` file per project context. Copy it to move the agent's memory. Back it up by copying a file.

5. **From database to relationship.** The deeper ambition beyond storage is **user modeling**. Over time, the memory layer should synthesize not just "what did I say?" (retrieval) but "what kind of user am I?" -- preferences, working patterns, vocabulary, project rhythms. That's the difference between a database and a relationship. The tiered architecture makes this possible because the cold tier accumulates enough history for pattern extraction.

**Effort:** Medium. The MemoryService abstraction already exists. The warm tier is a backend swap. The cold tier (vector search) adds a dependency but SQLite extensions like `sqlite-vec` keep it single-file.

---

### Gap 2: Git as the Coordination Backbone

**The problem.** Git is currently used only for backup (force-push to a private repo). That uses maybe 10% of its value. The real power is git as the coordination mechanism for agent work.

**The plan.**

1. **Branch-per-task pattern.** When the distro starts a multi-step workflow (recipe, long build), it creates a branch. Each step commits. The human can review progress as a series of commits, and the final result is a PR.

2. **Git as the resume mechanism.** If a session crashes mid-task, the branch contains all progress. Resume = checkout the branch and continue from the last commit. This replaces fragile session-state recovery with git's robust state management.

3. **PR as approval gate.** For high-stakes changes (m365 deployments, production code), the agent opens a draft PR. The human reviews the diff. Approval = merge. Rejection = agent revises. This is the most natural human-in-the-loop pattern that exists -- everyone already knows how to review a PR.

4. **Multi-agent coordination via branches.** When multiple agents work in parallel, each gets a branch. Integration happens through merge. Conflicts are structured problems agents can reason about (they're text diffs). This scales to dozens of concurrent agents without custom coordination infrastructure.

**Effort:** Medium. The git primitives exist. The work is defining conventions and integrating them into the recipe system.

---

### Gap 3: Managed Sandboxes

**The problem.** Agents need safe, isolated environments for execution -- especially for generated code, untrusted operations, and parallel experimentation. The distro has Docker Compose for testing but no first-class sandbox primitive.

**The plan.**

1. **`amp-distro sandbox create`** -- Create a sandboxed environment for an agent task. Returns a sandbox ID. The agent gets a shell inside the sandbox, isolated from the host filesystem and network.

2. **Leverage Docker's microVM API.** Docker Desktop 4.58+ ships an undocumented sandbox API that Claude Code, Codex, and Gemini CLI already use. Each sandbox gets its own Linux kernel, its own Docker daemon, and filtered network access. This is the right isolation level for agent-generated code.

3. **Forkable sandboxes.** Following Daytona's pattern: an agent can snapshot a sandbox mid-execution and fork it. Try approach A in one fork, approach B in another. Keep whichever works. This matches how agents naturally explore solution spaces.

4. **Sandbox lifecycle tied to git branches.** Create a sandbox, start a branch. Work happens in the sandbox on that branch. When the branch merges, the sandbox can be destroyed. Natural cleanup.

**Effort:** High. This requires container orchestration work. But the primitives exist (Docker microVMs, Daytona's model). The distro's Docker Compose infrastructure is a starting point.

---

### Gap 4: The Agent-Help Layer

**The problem.** Every tool in the distro needs to be discoverable and understandable by agents. `--help` was designed for humans scanning a terminal. Agents need something different: strategic guidance about when to use this tool vs. another, what it costs in tokens, what the anti-patterns are.

**The plan.**

1. **`--agent-help` for every CLI command.** Alongside `amp-distro doctor --help` (syntax for humans), provide `amp-distro doctor --agent-help` (strategy for agents). The agent-help output includes: when to use this, what it returns, what it costs, common mistakes, and how it composes with other commands.

2. **`llms.txt` at the project root.** Following the pattern adopted by 600+ sites (Anthropic, Stripe, Cloudflare): a flat text file at the root describing the project for LLM consumption. Not documentation -- strategic orientation.

3. **Tool descriptions as first-class artifacts.** Every MCP tool, every API endpoint, every CLI command has a description that passes the "schema-describable" test. These descriptions are versioned, tested (do agents actually use them correctly?), and iterated on. Anthropic proved that refining tool descriptions alone pushed Claude to state-of-the-art on SWE-bench.

4. **Eval-driven description refinement.** Following Anthropic's loop: write description, run evals, read agent transcripts to find rough edges, revise description, repeat. The descriptions aren't documentation -- they're an interface, and they need the same iterative refinement as any interface.

5. **Error-as-teacher pattern.** When a command fails, don't just return the error. Make a second LLM call to explain what went wrong and suggest a fix. This is cheap (error text is small, explanation is fast) and valuable at two levels: the agent explains the error to the human _now_, and the error + resolution gets stored in memory so the agent (or a future agent) avoids repeating it. Over time, the system learns from its own mistakes. The memory tier makes this practical -- errors go into the warm tier, solutions go into cold for semantic retrieval when similar errors recur.

**Effort:** Low to medium. Mostly writing and testing, not engineering. But the payoff is large: better tool descriptions measurably improve agent success rates.

---

### Gap 5: Policy Mesh as OS-Level Security

**The problem.** The m365 platform demonstrates what agent security looks like: 9 hooks forming a policy enforcement mesh (RBAC, cost control, compliance, audit, approval). But this is built as a one-off for m365. The distro should provide this as infrastructure.

**The plan.**

1. **`policy.yaml` as the security configuration.** A single file defining: budget limits per session/day/month, approval requirements for high-risk operations, access controls (which tools, which APIs, which file paths), and audit requirements.

2. **Structural enforcement, not advisory.** Following the m365 pattern: safety is implemented as hooks that intercept every operation. The agent literally cannot bypass a budget check or skip an approval gate. This is the agent equivalent of filesystem permissions -- structural, not a suggestion.

3. **Cost control as a first-class service.** The m365 platform's `CostControlHook` is elegant: it intercepts every LLM call, tracks spend against budgets, and can automatically degrade to cheaper models instead of blocking. This should be a distro-level service available to every surface, not just m365.

4. **Graduated trust.** New agents start with minimal permissions. As they demonstrate reliability (measured by audit trails in JSONL), permissions expand. This mirrors how organizations manage human access -- except it can be automated because agent behavior is fully observable.

**Effort:** Medium. The m365 hooks provide the implementation pattern. The work is generalizing them into configurable, composable policy primitives.

---

### Gap 6: Daemon Agents

**The problem.** The planning doc covers triggered workflows (recipes) and reactive tools. But there's a missing pattern: agents that **watch, decide, and act on their own schedule** without being asked. The distro's watchdog service is an early form of this. Cron jobs are an older form. But a daemon agent is neither -- it combines scheduled triggers with LLM reasoning.

"Check disk usage every 5 minutes, and if it's above 80%, identify the largest recent files and suggest cleanup" is not a cron job. A cron job can check disk usage. It can't reason about what to do. A daemon agent can.

**The plan.**

1. **Named daemon pattern.** A daemon agent is defined by: a trigger schedule (cron-like), an observation function (what to check), a reasoning step (what to do about it), and an action space (what it's allowed to do). All four are declarative -- YAML config, not custom code.

2. **JSONL trail for everything.** Every daemon cycle produces a JSONL event: what was observed, what was decided, what was done. This is non-negotiable. Proactive agents that act without being asked need the strongest audit trail. The human should be able to review "what did my agents do while I was asleep?" as a simple log query.

3. **Graduated autonomy.** Start with observe-and-report (no autonomous action). Graduate to observe-and-suggest (propose an action, wait for approval). Graduate to observe-and-act (execute autonomously within policy bounds). The policy mesh (Gap 5) controls which level a daemon agent operates at.

4. **Concrete first daemons.** Start with the obvious ones:
   - **Backup daemon** -- already exists as `amp-distro backup`, make it schedule-aware
   - **Health daemon** -- already exists as the watchdog, add reasoning about what to do when checks fail
   - **Tidy daemon** -- watch for accumulated temp files, stale branches, orphaned containers
   - **Update daemon** -- check for new versions of distro, modules, models; suggest or auto-apply

**This sits between Layer 5 (Services) and Layer 7 (Workflows)** and neither fully captures it today. It might deserve its own position in the stack, or it might be a pattern that uses both layers -- services for the scheduling and observation, workflows for the multi-step response when something needs action.

**Effort:** Medium. The scheduling infrastructure exists (cron, launchd). The reasoning pattern exists (agent sessions). The work is connecting them with the right abstraction and the right audit trail.

---

### Gap 7: Model Routing as an OS Concern

**The problem.** The Agent OS runs many different tasks with wildly different complexity. Intent classification takes ~100 tokens. Error explanation takes ~500 tokens. Multi-file code generation takes ~100,000 tokens. Using a frontier model for all of them is wasteful; using a small model for all of them is incapable. The OS needs a **model routing policy** -- the system-level decision of which model to use for which task.

This matters especially for latency. When responses arrive in under a second, the OS feels like part of the interface. When they take 5 seconds, it feels like a tool. Small models are fast. Fast changes behavior.

**The plan.**

1. **Task-to-model mapping.** Define categories of work and their model requirements:

    | Task Type | Model Size | Latency Target | Examples |
    |-----------|-----------|----------------|---------|
    | Classification / routing | Tiny (~1B) | <200ms | Intent kernel, error detection |
    | Structured extraction | Small (~3-7B) | <500ms | JSON parsing, index merging, date conversion |
    | Code generation | Medium-Large (~30-70B) | <5s | Feature implementation, bug fixes |
    | Complex reasoning | Frontier (cloud) | <30s | Architecture design, multi-file analysis |

2. **Provider cascade.** Try local first, fall back to cloud. For classification: local 1B model → if confidence too low → local 7B → if still too low → cloud API. For generation: local 30B if available → cloud if not. The policy is configurable per-user based on their hardware and preferences.

3. **GPU memory management.** On a single machine, you can't keep a 70B model loaded while also running a fast classifier. The model router needs to manage model loading and unloading, keeping hot models in GPU memory and cold models on disk. This is the agent equivalent of virtual memory -- the OS manages a scarce resource (GPU RAM) so applications don't have to.

4. **Integration with cost control.** The policy mesh (Gap 5) already tracks spend. Model routing is the mechanism that makes cost control intelligent -- instead of blocking when budget is low, route to cheaper models. Graceful degradation instead of hard stops.

**Effort:** Medium-high. The provider abstraction in amplifier-core already supports multiple backends. The routing logic and GPU memory management are new. But the local-model ecosystem (Ollama, vLLM, llama.cpp) provides the serving layer.

---

### Design Axis: Local-First vs. Cloud-Hybrid

The seven eigenvectors are neutral on where computation happens. But the deployment model has real architectural consequences that deserve acknowledgment.

**The spectrum:**

| Position | Characteristics | Who Wants This |
|----------|----------------|----------------|
| **100% local** | No API keys, no data leaves machine, constrained by local GPU | Privacy-maximizing users, air-gapped environments |
| **Local-first, cloud-fallback** | Local for most tasks, cloud for frontier capability | Most power users. Best balance of privacy and capability. |
| **Cloud-first, local-cache** | Cloud models primary, local for speed-sensitive tasks | Teams prioritizing capability over privacy |
| **100% cloud** | All computation remote, thin local client | Enterprise managed environments |

The distro should support the full spectrum, but **default to local-first, cloud-fallback.** This means:

- **Model routing (Gap 7) is essential**, not optional. Local-first requires knowing which tasks can run locally and which need cloud.
- **GPU memory is a managed resource.** The OS needs to know what's loaded, what can be loaded, and what requires eviction. This is analogous to virtual memory management.
- **Embedding models need local options.** The cold memory tier (Gap 1) uses vector search. If the embedding model requires a cloud API, every memory query leaks data. Local embeddings (all-MiniLM, nomic-embed) keep the memory system fully local.
- **The eigenvectors hold.** Text files, git, shell, HTML, SQLite, HTTP, JSONL -- all work identically whether the LLM is local or remote. The primitives don't care. Only the model routing layer changes.

The distro already supports Ollama for local models. Making local-first a design principle -- not just a supported option -- means testing with local models first, ensuring the full stack works without any API keys, and treating cloud as an enhancement rather than a requirement.

---

## The Philosophical Point

The human OS and the agent OS aren't in competition. They're **complementary layers over the same materials.**

The human sees HTML in a browser. The agent writes the HTML directly. Same artifact, different interfaces.

The human reviews a diff in a PR. The agent produced the diff through shell commands. Same diff, different tools.

The human chats in Slack. The agent posts via the Slack API. Same conversation, different channels.

This is why the seven eigenvectors work: they're **shared primitives** that both humans and agents can work with, each through their natural modality. The agent writes; the human reads. The agent commits; the human reviews. The agent structures; the human judges.

The Agent-shaped OS doesn't replace anything. It makes visible the layer that was always there -- the text-native, composable, orthogonal substrate underneath the visual interfaces we built for human eyes. Agents just happen to be the first users who prefer the substrate to the surface.

---

## What This Means for the Distro

The distro was conceived as "an opinionated Amplifier distribution that minimizes human attentional load." That's still right. But the Agent-shaped OS framing adds a second dimension: **the distro is also the system that installs, configures, and maintains the agent's operating environment.**

`amp distro init` doesn't just set up a config file. It provisions an agent OS: text-based state, git coordination, shell execution, HTML presentation, queryable memory, HTTP communication, and structured event logging. The preflight checks verify not just that API keys work, but that the agent's full operating environment is healthy.

The distro's One Rule -- minimize human attentional load -- aligns perfectly. The better the agent's OS, the less the human needs to intervene. Good primitives mean fewer errors, which means fewer interruptions, which means less attention spent on debugging and more on the work that actually matters.

This is the vision: **a system where agents have the right primitives to do sustained, high-quality, autonomous work, and humans engage only for the decisions that require human judgment.** The seven eigenvectors are the foundation. The distro is the installer.
