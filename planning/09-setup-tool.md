# Setup Tool / Installer Specification

## Design Philosophy

The setup tool is the user's first experience with the Amplifier
environment. It should embody the core principle: **minimize
attentional load.** That means:

1. Detect everything possible (don't ask what you can infer)
2. Opinionated defaults (don't ask 20 questions)
3. Validate immediately (don't let bad config survive)
4. Explain what it did (transparency, not magic)

---

## What It Does

### `amp env init` - First-Time Setup

Runs once per machine. Creates a complete, validated, working
Amplifier environment.

```
$ amp env init

Amplifier Environment Setup
============================

Detecting your environment...
  Platform: WSL2 (Ubuntu 24.04)
  Shell: zsh
  Python: 3.12.3
  Node.js: 20.11.0
  Git: 2.43.0

Identity:
  GitHub: samschillace (detected from `gh auth status`)
  Email: sam@example.com (detected from `git config`)

Workspace:
  Dev folder: ~/dev/ANext/ (detected from AGENTS.md)
  Memory: ~/amplifier-dev-memory/ (exists, 15 memories)
  Sessions: ~/.amplifier/projects/ (89 projects)

Providers:
  [ok] ANTHROPIC_API_KEY set (valid, claude-opus-4-6 accessible)
  [ok] OPENAI_API_KEY set (valid)
  [--] AZURE_OPENAI_KEY not set (skip)

Bundle:
  Active: my-amplifier (loaded, 47 modules, 23 agents)
  [FAIL] 2 includes broken:
    - textbook-factory: ./bundle.md not found
    - exp-delegation: repo not accessible
  [ok] 45 modules loaded successfully

Writing configuration...
  ~/.amplifier/settings.yaml updated with environment section
  Health checks enabled
  Auto-handoff enabled
  Cache TTL set to 7 days

Fix the 2 broken includes? [Y/n] y
  Removing textbook-factory (path doesn't exist)
  Removing exp-delegation (repo 404)
  Bundle re-validated: 45 modules, 23 agents, 0 errors

Setup complete. Your environment is ready.
Run `amp env status` anytime to check health.
```

### `amp env status` - Health Check

Quick environment health report. Fast enough to run at every
session start if enabled.

```
$ amp env status

Amplifier Environment Status
==============================
  [ok] Identity: samschillace
  [ok] Providers: anthropic (valid), openai (valid)
  [ok] Bundle: my-amplifier (45 modules, 23 agents, 0 errors)
  [ok] Cache: all sources < 7 days old
  [ok] Memory: 15 memories, work log current
  [warn] Last session: 6 hours ago, no handoff generated
  [ok] Team tracking: enabled, last sync 2 days ago

1 warning. Environment healthy.
```

### `amp env validate` - Deep Validation

Thorough bundle + config validation. Slower, runs on demand.

```
$ amp env validate

Validating bundle: my-amplifier
================================

Include resolution:
  [ok] amplifier-dev (foundation) -> 32 modules
  [ok] dev-memory-behavior -> 3 modules
  [ok] deliberate-development -> 4 agents
  [ok] amplifier-stories -> 2 agents
  [ok] project-orchestration -> 1 agent
  Total: 45 modules, 23 agents

Module source check:
  [ok] 45/45 module sources resolvable
  [ok] 0 env vars unset
  [ok] 0 namespace collisions

Agent file check:
  [ok] 23/23 agent .md files parse correctly
  [ok] All frontmatter valid

Context path check:
  [ok] 67/67 context paths exist

Cache freshness:
  [ok] 12 cached sources, newest: 2 hours ago, oldest: 3 days

Validation passed. 0 errors, 0 warnings.
```

### `amp env install <interface>` - Interface Installation

Install and configure an Amplifier interface.

```
$ amp env install voice

Installing voice interface
============================

Prerequisites:
  [ok] Python 3.12.3
  [ok] Node.js 20.11.0
  [ok] OPENAI_API_KEY set
  [ok] ANTHROPIC_API_KEY set
  [warn] OpenAI Realtime API costs ~$1-2/minute

Installing:
  Cloning amplifier-voice... done
  Installing voice-server (Python)... done
  Installing voice-client (Node)... done
  Writing .env from your environment... done
  Linking to your active bundle (my-amplifier)... done

Smoke test:
  [ok] Server starts
  [ok] Amplifier session created
  [ok] Client builds

Start with:
  amp voice
  # or: cd ~/dev/ANext/amplifier-voice && ./start.sh

Cost reminder: OpenAI Realtime API is ~$1-2/minute.
```

### `amp env fix` - Auto-Repair

Attempt to fix detected issues automatically.

```
$ amp env fix

Detected issues:
  1. Cache stale: amplifier-foundation (9 days old)
  2. Bundle include broken: textbook-factory
  3. 66 test-agent-* debris dirs in memory

Fixing:
  1. Refreshing amplifier-foundation cache... done
  2. Removing broken include (textbook-factory)... done
  3. Cleaning 66 test-agent-* directories (4.2MB)... done

3 issues fixed. Run `amp env status` to verify.
```

---

## Implementation Options

### Option A: CLI Subcommands (Compiled)

Add `amp env` as a subcommand group in `amplifier-app-cli`.

**Pros:** Native, fast, always available, can run before bundle loads.
**Cons:** Requires CLI release for every change. Compiled = slow to iterate.

### Option B: Recipes (Declarative)

Each `amp env` command is a recipe YAML file.

**Pros:** Extensible, no CLI release needed, community can add interfaces.
**Cons:** Requires bundle to be loaded (chicken-egg for init), slower.

### Option C: Hybrid (Recommended)

- `amp env init` and `amp env status` = compiled (must work before bundles load)
- `amp env validate`, `amp env install`, `amp env fix` = recipes (extensible)
- `amp env` CLI is a thin dispatcher that can call recipes

```python
# In amplifier-app-cli
@cli.group()
def env():
    """Environment management"""

@env.command()
def init():
    """First-time setup (compiled, no bundle needed)"""
    # Detect, configure, validate

@env.command()
def status():
    """Quick health check (compiled, fast)"""
    # Check providers, bundle, cache

@env.command()
def validate():
    """Deep validation (runs recipe)"""
    run_recipe("@environment:recipes/validate.yaml")

@env.command()
@click.argument("interface")
def install(interface):
    """Install interface (runs recipe)"""
    run_recipe(f"@environment:recipes/install-{interface}.yaml")

@env.command()
def fix():
    """Auto-repair (runs recipe)"""
    run_recipe("@environment:recipes/fix.yaml")
```

**Effort:** 1 week for compiled (init + status), 1 week for recipes.

---

## What the Installer Produces

After `amp env init`, the user's machine has:

```
~/.amplifier/
  settings.yaml          # With environment: section
  keys.env               # API keys
  cache/                 # Validated bundle cache
  projects/              # Session storage

~/dev/ANext/             # Workspace (or configured equivalent)
  (repos cloned here)

~/amplifier-dev-memory/  # Persistent memory
  memory-store.yaml
  work-log.yaml

~/.amplifier/AGENTS.md   # Global agent instructions
```

Plus optionally:
```
~/dev/ANext/amplifier-voice/    # If `amp env install voice`
~/dev/ANext/amplifier-tui/      # If `amp env install tui`
~/dev/ANext/carplay/            # If `amp env install carplay`
```

---

## Configuration File: `~/.amplifier/environment.yaml`

Separate from settings.yaml to avoid conflicts with Amplifier updates.

```yaml
# ~/.amplifier/environment.yaml
version: "1.0"

# Ring 1: Foundation
workspace: ~/dev/ANext
identity:
  github_handle: samschillace
  team: microsoft-amplifier

preflight:
  enabled: true
  check_api_keys: true
  check_model_names: true
  check_bundle_integrity: true
  timeout_seconds: 10

cache:
  max_age_hours: 168
  auto_refresh_on_error: true
  integrity_check: deep

session:
  auto_handoff: true
  handoff_model: claude-haiku    # Fast + cheap for summaries
  handoff_location: project

health:
  startup_check: true
  periodic_hours: 0              # 0 = disabled

# Ring 2: Installed interfaces
interfaces:
  cli:
    installed: true
    version: "0.1.0"
  voice:
    installed: true
    path: ~/dev/ANext/amplifier-voice
    version: "0.2.0"
  tui:
    installed: false

# Ring 3: Active workflows
workflows:
  attention_firewall:
    enabled: true
    db_path: /mnt/c/Users/samschillace/.attention-firewall/notifications.db
  team_tracking:
    enabled: true
    target_repo: microsoft-amplifier/amplifier-shared
  idea_funnel:
    enabled: false               # Future
  morning_brief:
    enabled: false               # Future
```

---

## Reconciliation with Level 4 Architecture

The Level 4 spec proposed Day 1: "Sam creates goal queue."
The setup tool IS the goal queue setup mechanism, generalized:

- Level 4 goal queue = "what should Amplifier work on autonomously?"
- Setup tool = "what should the environment track and manage?"

The `workflows:` section of environment.yaml is the declarative
equivalent of Level 4's goal queue. Each enabled workflow is a
"standing goal" that the environment pursues continuously.

The Level 4 spec also proposed "file-based status exporter" (Day 4).
`amp env status` is exactly that, made interactive. The file-based
version would be a health report written by a periodic recipe.
