# Ring 2 Deep Dive: Path to Hands-Off Interfaces

## What Ring 2 Contains

Ring 2 is how you access Amplifier. Pick an interface, it just works.
Same session state, same project context, same memory, different viewport.

The goal: minimal attention (muscle memory). If you're debugging your
interface instead of using it, Ring 2 has failed.

---

## Current State: Four Interfaces, Four Integration Patterns

| Interface | Integration Pattern | Session Creation | Bundle Loading |
|-----------|-------------------|------------------|----------------|
| **CLI** | Is the reference impl | `create_initialized_session(SessionConfig)` | `resolve_bundle_config()` via AppSettings |
| **Voice** | Direct programmatic (best) | `bundle.prepare()` -> `prepared.create_session()` | `load_bundle(name)` from foundation |
| **TUI** | Parasitic on CLI (worst) | Imports from amplifier_app_cli via sys.path hack | Same as CLI via import |
| **CarPlay** | Subprocess + aspirational | `subprocess.run(["amplifier", "run", ...])` | CLI handles it |

**The core problem:** Each interface independently solved "how to create
an Amplifier session." The result is four different patterns, four
different dependency stories, and four different failure modes.

---

## Interface-by-Interface Gap Analysis

### CLI (Reference Implementation)

**Status:** Production quality. The thing that works.

**Gaps:**
- Installed via editable install from `/mnt/c/ANext/` path (machine-specific)
- `amplifier-foundation` not pinned in `[tool.uv.sources]` (transitive resolution)
- No `amp env` subcommand for environment management
- First-run wizard is minimal (just creates settings.yaml)

**Path to "just works":**
1. Publish to stable git URL (already done: `microsoft/amplifier`)
2. Pin foundation in uv.sources alongside core
3. Add `amp env init` / `amp env validate` subcommands
4. Enhanced first-run wizard (detect API keys, validate bundle, offer defaults)

**Effort:** 2-3 days (mostly the `amp env` subcommands).

---

### Voice Pipeline

**Status:** Architecture is solid. Hardcoded defaults are the blocker.

**Architecture (clean):**
```
Browser --WebRTC--> FastAPI --REST--> OpenAI Realtime API (voice I/O)
                       |
                       +--> AmplifierBridge (long-lived session)
                            +-- delegate tool -> specialist agents (Claude)
```

**What's hardcoded that shouldn't be:**

| Hardcoded Item | Location | Should Be |
|----------------|----------|-----------|
| Bundle name `exp-amplifier-dev` | config.py:13 | User's active bundle from settings.yaml |
| Working dir `~/amplifier-working` | config.py:14 | Ring 1's workspace setting |
| Anthropic provider config (git URL, model) | amplifier_bridge.py:127-135 | Bundle YAML config |
| `tool-delegate` module (full git URL) | amplifier_bridge.py:153-171 | Bundle YAML config |
| OpenAI model `gpt-realtime` | config.py:42 | Environment variable or config |
| Voice name `marin` | config.py:42 | Environment variable or config |
| Custom bundle path `bundles/voice.yaml` | config.py:164-166 | Standard bundle resolution |

**What blocks new team members:**
- Two runtimes needed (Python 3.11+ AND Node.js 18+) - neither auto-checked
- OpenAI Realtime API required ($1-2/minute!) - no fallback, no cost warning
- `.env` file must be manually created
- `~/amplifier-working` directory doesn't exist by default

**Path to "just works":**
1. Extract hardcoded provider/model injection into bundle YAML (biggest fix)
2. Read user's active bundle from `~/.amplifier/settings.yaml` instead of env var default
3. Read workspace from Ring 1 config instead of hardcoded path
4. Create `start.sh` that validates Python + Node + API keys
5. Add cost warning on first run

**Effort:** 1-2 weeks (mostly the provider extraction from Python to YAML).

---

### TUI

**Status:** Most promising UI, most broken integration.

**The sys.path hack (lines 14-41 of session_manager.py):**
```python
_amplifier_site_packages = Path.home() / ".local/share/uv/tools/amplifier/lib"
# ... walks directory tree, reads .pth files, injects into sys.path
```

Then imports `amplifier_app_cli.session_runner`, `amplifier_app_cli.runtime.config`,
`amplifier_app_cli.lib.settings` at runtime.

**Why this is catastrophic:**
- Undeclared dependency on `amplifier_app_cli` (not in pyproject.toml)
- Undeclared dependency on `amplifier-core` (used for HookResult, events)
- Path-walking through uv tool internals (breaks on any uv update)
- pyright errors are "expected" (type checking impossible)
- The only declared dependency is `textual>=0.47.0`

**The Session Save Bug:**
- Symptom: Last turn missing on quit+resume
- Root cause: Textual's `exit()` terminates event loop before async
  `SESSION_END` hooks and `session.cleanup()` complete
- Fix approaches documented but none implemented:
  blocking cleanup, atexit handler, Textual shutdown hooks

**Path to "just works":**
1. **Rewrite session_manager.py to use amplifier-foundation directly**
   (same pattern as Voice's amplifier_bridge.py). This is THE fix.
   - Replace: `from amplifier_app_cli.session_runner import create_initialized_session`
   - With: `from amplifier_foundation import load_bundle` + `bundle.prepare().create_session()`
2. Add `amplifier-core` and `amplifier-foundation` as proper pyproject.toml dependencies
3. Delete the sys.path hack entirely
4. Fix session save bug (Textual `on_unmount` lifecycle or synchronous shutdown)
5. Remove stale `amplifier_chic_poc.egg-info`

**Effort:** 1-2 weeks (mostly the session_manager.py rewrite + save bug).

---

### CarPlay / Voice Bridge

**Status:** Design complete, two competing implementations, neither production.

**Current state:**
- `amplifier_bridge.py`: Uses `subprocess.run(["amplifier", "run", ...])` - shells out to CLI
- `session_manager.py`: Uses programmatic `load_bundle()` - proper but incomplete
- Dependencies declared but without git URL sources (won't install)

**Infrastructure requirements:**
- Tailscale on both desktop (WSL2) and iPhone
- iOS Shortcuts app (manual shortcut creation, 4-step process)
- Server running 24/7 (or at least when driving)
- Two API keys

**Key insight:** CarPlay does NOT depend on amplifier-voice. They're
completely separate voice implementations:
- `amplifier-voice` = browser WebRTC + OpenAI Realtime (streaming speech-to-speech)
- `carplay` = iOS Siri STT -> HTTP POST -> Amplifier -> text -> iOS TTS

**Path to "just works":**
1. Kill subprocess approach (amplifier_bridge.py), keep programmatic (session_manager.py)
2. Add `[tool.uv.sources]` for amplifier-core/foundation
3. Tailscale setup validation script
4. iOS Shortcut distributed via iCloud link
5. Standalone mock mode (already exists) for testing without iPhone

**Effort:** 1 week.

---

## The Missing Piece: Interface Adapter

All four interfaces duplicate the same session lifecycle code.
A shared adapter would eliminate ~100 lines per interface and
ensure consistent behavior.

**What every interface does:**
1. Load a bundle (by name or config)
2. Prepare the bundle (resolve deps)
3. Create a session (with cwd)
4. Register hooks for output capture
5. Execute prompts in a loop
6. Clean up on exit

**Proposed adapter (lives in amplifier-foundation):**

```python
class InterfaceAdapter:
    """Common session lifecycle for all Ring 2 interfaces."""

    async def create_session(
        bundle_name: str,
        cwd: Path,
        provider_overrides: dict = None,
    ) -> ManagedSession:
        """Load bundle, prepare, create session - one call."""

    async def execute(session, prompt: str) -> InterfaceResponse:
        """Execute prompt, capture output via hooks, return structured result."""

    async def cleanup(session) -> None:
        """Emit SESSION_END, flush hooks, cleanup - guaranteed completion."""

    def register_output_hooks(session, callbacks: OutputCallbacks) -> None:
        """Standard hook registration for any interface's output needs."""
```

**This adapter answers the question:** "How do I add a new interface?"
Answer: Implement OutputCallbacks (how to display text, tool calls,
errors) and call InterfaceAdapter. Everything else is handled.

**Effort:** 2-3 days for the adapter, then 1-2 days per interface to adopt.

---

## The "amp env install" Experience

Target UX for installing any interface:

```
$ amp env install voice
Installing voice interface...

Checking prerequisites:
  [ok] Python 3.11+
  [ok] Node.js 18+
  [ok] OPENAI_API_KEY set
  [ok] ANTHROPIC_API_KEY set
  [warn] OpenAI Realtime API costs $1-2/minute

Installing voice-server... done
Installing voice-client... done
Writing config... done

Start with: amp voice
  or: cd ~/dev/ANext/amplifier-voice && ./start.sh
```

**What "amp env install" actually does:**
1. Check prerequisites (runtimes, API keys, disk space)
2. Clone/install the interface repo
3. Install dependencies (pip + npm if needed)
4. Create config files (.env, settings)
5. Run smoke test (can we create a session?)
6. Print start instructions

This could be a recipe (`install-interface.yaml`) rather than
compiled code, making it extensible without releases.

**Effort:** 1 week for the install recipe + per-interface configs.

---

## Total Path to Hands-Off Ring 2

| Component | Effort | Dependencies | Priority |
|-----------|--------|-------------|----------|
| Interface Adapter in foundation | 2-3 days | None | 1 (enables everything) |
| TUI: Rewrite session_manager.py | 1 week | Interface Adapter | 2 (most broken, most promising) |
| TUI: Fix session save bug | 2-3 days | TUI rewrite | 2 |
| Voice: Extract hardcoded configs | 1 week | None | 3 |
| Voice: Read user's bundle/workspace | 2-3 days | Ring 1 config schema | 3 |
| CarPlay: Consolidate on programmatic | 3-4 days | Interface Adapter | 4 |
| CLI: Add `amp env` subcommands | 2-3 days | Ring 1 components | 4 |
| Install recipe (`amp env install`) | 1 week | All above | 5 (after interfaces work) |

**Total estimated effort: ~5-6 weeks** (but heavy parallelism possible)

**Critical path: Interface Adapter -> TUI rewrite -> Install recipe**

The Interface Adapter is the enabler. Once it exists, each interface
can be fixed independently and in parallel.

---

## Reconciliation with Prior Thinking (Level 4 Architecture)

The Jan 22 LEVEL_4_ARCHITECTURE.md proposed a "Visibility Dashboard"
as component #6. Ring 2 IS that visibility dashboard, generalized:

- Level 4 Dashboard = read-only monitoring of autonomous agents
- Ring 2 Interfaces = any interaction mode with Amplifier

The key insight from Level 4 that applies: "File-based first, TUI later."
This maps to: get the Interface Adapter right (file/API based), then
each UI is just a viewport on top of it.

Brian's maturity ladder also maps:
- Level 0-1: CLI (human drives everything)
- Level 2: TUI + Voice (human submits goals, monitors progress)
- Level 3-4: Any interface (Amplifier works autonomously, human checks in)

Ring 2's job is to make the "check in" effortless from anywhere.
