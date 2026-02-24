# Review: Distro Refactor Plan vs lean-experience-server Branch

## What the Plan Gets Right

**Phase 1 (Delete Dead Weight) is spot-on.** The plan correctly identifies `deploy.py`, `provider_api.py`, `update_check.py`, and `migrate.py` as dead modules. All four were deleted on the lean branch. The task ordering, verification steps, and commit granularity are solid.

**Phase 1.5 (Clean conventions.py)** -- Correct. The lean branch pared `conventions.py` from ~137 to 57 lines for the same reasons.

**The philosophical direction is right** -- the plan's goal statement ("slim the distro to only what's genuinely unique, eliminate duplication with foundation and CLI") matches the lean branch's actual outcome.

**The test discipline is good.** Running the full suite after every change, tracking pre-existing failures, verifying before committing -- all sound.

---

## What the Plan Gets Wrong

### 1. It preserves the Bridge -- the lean branch deleted it entirely

This is the biggest divergence. The plan's **Phase 4** proposes refactoring `bridge.py` by extracting `_prepare_session()` and cleaning `SessionHandle`. But the lean branch proved the bridge is entirely redundant -- it reimplements foundation's `load_bundle()` -> `prepare()` -> `create_session()` pipeline. The lean branch deleted both `bridge.py` (~1,090 lines) and `bridge_protocols.py` and replaced them with a `FoundationBackend` in `session_backend.py` that calls foundation directly.

The plan's approach polishes an abstraction layer that shouldn't exist. Phase 4's 3 tasks (~200 lines of plan) are wasted effort.

### 2. It preserves `schema.py`, `config.py`, and `distro.yaml` -- the lean branch deleted all three

The plan's **Phase 2** carefully slims `DistroConfig` field by field, keeping 7 config sections (interfaces, server, backup, preflight, slack, voice, watchdog). The lean branch made a more radical decision: **`distro.yaml` doesn't need to exist at all.** Everything moved to environment variables (`AMPLIFIER_VOICE_*`, `AMPLIFIER_SERVER_API_KEY`) and foundation's `settings.yaml`. The plan's 5 Phase 2 tasks are unnecessary if you accept this.

### 3. It preserves `features.py` and `bundle_composer.py` -- the lean branch deleted both

The plan's **Task 5.1** even adds `amplifier-start` as an include in `bundle_composer.py`. But the lean branch deleted the composer entirely -- real bundle directories (`amplifier-start`) replace the feature catalog and generated bundles. Task 5.1 adds code to a file that should be deleted.

### 4. It preserves `doctor.py` and `preflight.py` (slimmed) -- the lean branch deleted both

The plan's **Phase 3** carefully removes individual checks. The lean branch concluded these modules are wholly redundant: `amplifier doctor` lives in app-cli, and preflight events live in amplifier-start. No slimming needed -- just deletion.

### 5. It preserves `install_wizard`, `settings`, and `example` server apps -- the lean branch deleted all three

These apps are tightly coupled to the dead feature-catalog system (`features.py`, `bundle_composer.py`). The lean branch deleted them entirely. The plan doesn't mention them at all.

---

## What the Plan is Missing

| Missing Item | What the lean branch did |
|---|---|
| **Delete the Bridge entirely** | Replaced with `FoundationBackend` calling foundation directly |
| **Delete `distro.yaml` / schema / config** | Config via environment variables + foundation's `settings.yaml` |
| **Delete `features.py` and `bundle_composer.py`** | Real bundle dirs replace generated bundles |
| **Delete `install_wizard`, `settings`, `example` apps** | Too coupled to dead feature-catalog |
| **Delete `docs_config.py`** | No longer needed |
| **Strip CLI to 3 commands** | Only `server`, `backup/restore`, `service` remain; `init`, `doctor`, `status`, `validate`, `version`, `update`, `install`, `interfaces` all removed |
| **Rewrite `session_backend.py`** | New `SessionBackend` protocol + `FoundationBackend` + `MockBackend` |
| **Environment-driven config** | Voice uses `AMPLIFIER_VOICE_*`, server uses env vars, `keys.yaml` -> env at startup |
| **Session resume gap** | `FoundationBackend._reconnect()` raises `NotImplementedError` -- needs `restore_transcript()` in foundation |

---

## The Core Disagreement

The plan treats distro as a **coordination layer to be slimmed** -- keep the architecture, remove dead weight.

The lean branch treats distro as an **experience server only** -- delete the coordination layer entirely, since foundation and app-cli already provide it.

The plan would leave ~60-70% of the code that the lean branch deleted. If the lean branch's architectural insight is correct (and the session analyst confirmed it was a deliberate, well-reasoned decision), then most of Phases 2-6 in the plan are working on code that should just be deleted.

---

## Recommendation

The plan is good work -- the analysis is thorough and the task decomposition is careful. But it was written without awareness of the lean branch's more radical insight: **the bridge, schema, config, features, and diagnostics layers are wholly redundant with foundation, not just partially redundant.**

The plan's Phase 1 can be executed as-is. Phases 2-6 should be replaced with the lean branch's approach: delete the bridge/schema/config/features/doctor/preflight/install-wizard/settings wholesale, write `FoundationBackend`, and move config to environment variables.
