# Bundle Structure Drift: Intent vs Implementation

## The Original Plan: A Real Bundle

`planning/10-project-structure.md` (lines 66-96) — written Feb 6, the founding design document — lays out the implementation structure explicitly:

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
    morning-brief.yaml            # Daily intelligence brief
    friction-report.yaml          # Weekly friction analysis
  scripts/
    preflight.py                  # Pre-flight check implementation
    handoff.py                    # Session handoff generation
    cache-manager.py              # Cache TTL + integrity checks
  docs/
    SETUP.md                      # User-facing setup guide
    ARCHITECTURE.md               # Ring 1/2/3 explained
```

That's a **real bundle** — the same shape as `amplifier-foundation`, `my-amplifier`, or `amplifier-bundle-recipes`. It has `bundle.md`, `behaviors/`, `agents/`, `context/`, `recipes/`. It was explicitly called a **"thin bundle: the environment behavior"** — the same pattern foundation uses.

The plan even called out specific agents (`setup-agent`, `health-agent`, `friction-agent`), specific behaviors (`preflight.yaml`, `handoff.yaml`), and specific context files (`environment-instructions.md`). These are things that **require a directory structure** — you can't ship agents, behaviors, or context files from a single generated YAML file.

---

## What Actually Got Built

`bundle_composer.py` (line 1-4):

```python
"""Generate and modify the distro bundle YAML.

The bundle is a list of includes. This module adds/removes entries.
No templates, no complexity -- just list manipulation on a YAML file.
"""
```

The entire bundle model collapsed into: generate a flat YAML file at `~/.amplifier/bundles/distro.yaml` containing `bundle:` metadata and `includes:` list. No directory, no context, no agents, no behaviors, no recipes.

---

## When and Why It Diverged

The spec `DISTRO-004 Bundle Structure Finalization` (written later) is revealing. Despite its title suggesting it would finalize the bundle *structure*, it actually optimized within the single-file model:

- Added a `providers:` section to make the generated YAML more self-describing
- Fixed the bridge to load by convention file path instead of name lookup
- Added error handling for malformed YAML

The spec explicitly declares "What does NOT change" (line 510): `schema.py`, `features.py`, `install_wizard/`, `settings.yaml`, `keys.yaml`, `startup.py`. It treats the single-file approach as a given and improves it, rather than questioning whether it should be a directory.

And `IMPLEMENTATION.md` (line 628) cements this:

> **Bundle format** — No changes (distro base bundle is a standard bundle)

This statement is technically true (the YAML is valid bundle syntax that foundation can load) but misses the structural point — a "standard bundle" in the ecosystem is a *directory* with context, agents, and behaviors, not a lone YAML file.

---

## What Was Lost

Here's the mapping between original plan and what happened:

| Original Plan | What Got Built | Status |
|---------------|---------------|--------|
| `bundle.md` (thin bundle) | `bundles/distro.yaml` (generated YAML) | **Simplified** — file instead of directory |
| `behaviors/environment.yaml` | Nothing | **Lost** — preflight is Python code, not a composable behavior |
| `behaviors/preflight.yaml` | `preflight.py` (Python module) | **Moved** — works, but not composable by other bundles |
| `behaviors/handoff.yaml` | Blocked on core PR | **Blocked** |
| `agents/setup-agent.md` | `server/apps/install_wizard/` | **Moved** — web app, not an in-session agent |
| `agents/health-agent.md` | `doctor.py` (CLI command) | **Moved** — CLI tool, not an in-session agent |
| `agents/friction-agent.md` | Not built | **Lost** — Phase 4 |
| `context/environment-instructions.md` | Not built | **Lost** — no context injection into sessions |
| `recipes/init.yaml` | `cli.py init` command | **Moved** — imperative Python, not a declarative recipe |
| `recipes/morning-brief.yaml` | Not built | **Lost** — Phase 4 |
| `recipes/friction-report.yaml` | Not built | **Lost** — Phase 4 |

---

## Why It Happened

Reading the overnight build context (`context/OVERNIGHT-BUILD.md`) and the timeline, the picture is clear:

1. **Feb 6**: Planning documents written with the proper bundle-as-directory design
2. **Feb 8**: Architecture shifted to a central FastAPI server model (the "server-centric" pivot)
3. **Feb 9**: Overnight autonomous build session — implemented 9 tasks, jumped tests from 469 to 755
4. **Feb 10+**: Team PRs for Slack hardening, web chat, concurrency fixes

The server-centric pivot changed the gravity of the project. Instead of a bundle that composes behaviors and agents (the Amplifier-native pattern), the implementation became a **Python application** with a FastAPI server, CLI commands, and plugin apps. The bundle became an afterthought — just a pointer file to tell the bridge which foundation + provider to load.

The overnight build accelerated this. When you're autonomously building 9 tasks in one session, you reach for the simplest thing that works: generate a YAML file with `includes:`, write it to disk, load it by path. That's exactly what `bundle_composer.py` does. It works. But it doesn't match the original design.

---

## What This Costs

The original plan's agents, behaviors, and context files weren't just structural niceness — they represented **capabilities that would exist inside sessions**:

1. **No `context/environment-instructions.md`** means sessions started via the distro server have no awareness they're in a multi-surface environment. They don't know sessions might be resumed from Slack, or that handoffs matter, or that memory is shared across interfaces.

2. **No `agents/health-agent.md`** means you can't say "check my environment health" from inside a session. You have to exit, run `amp-distro doctor`, read the output, and come back. A proper in-session agent could do this inline.

3. **No `behaviors/preflight.yaml`** means preflight checks aren't composable. Another bundle can't include `distro:behaviors/preflight` to get the same checks. The logic is locked in Python code that only the bridge calls.

4. **No `recipes/`** means setup, validation, and diagnostics are imperative Python code instead of declarative workflows. You can't customize, extend, or inspect them the way you can with recipes.

---

## The Bottom Line

The intent was clearly captured. `planning/10-project-structure.md` describes exactly the right shape — a thin bundle with behaviors, agents, context, and recipes. The implementation diverged when the project pivoted to a server-centric model and the overnight build optimized for speed. The single-file bundle was the simplest thing that worked, and subsequent specs (DISTRO-004) refined within that model rather than returning to the original design.

The design document is still there. The question is whether to bring the implementation back to it.
