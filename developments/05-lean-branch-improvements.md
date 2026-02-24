# What lean-experience-server Should Learn from the Proposed Refactor

## Worth Adopting from the Plan

### 1. Public API surface for the server boundary (Phase 6 concept)

The lean branch deleted a lot of code but didn't establish a clean import contract between the server and the remaining distro modules. Right now on the lean branch, server files reach directly into `conventions`, `backup`, `fileutil`, `transcript_persistence`, `tailscale` -- no defined boundary.

The plan's Phase 6 idea is sound even for the reduced codebase: define what the server is allowed to import from the distro package. This matters because the plan's goal statement says "prepare the server for extraction" -- and the lean branch's plan doc says the same thing. If the server eventually becomes its own package, a clean `__init__.py` with `__all__` makes that extraction trivial.

**What to do:** Create a lean `__init__.py` that exports only what the server actually uses from the 6-7 remaining non-server modules. Much smaller than the plan's version (no bridge, schema, config, features, doctor, preflight to export), but the discipline is the same.

### 2. Server startup health check (Phase 3 kernel)

The lean branch deleted `preflight.py` entirely. That's correct -- the old 8-check preflight was mostly CLI-domain concerns. But the experience server has its own startup question: "can I actually create sessions?" If foundation isn't installed, or the bundle can't be loaded, the server will boot fine and then fail on the first session request with an opaque error.

The plan's slimmed preflight ("does distro.yaml exist?") isn't the right check. But the concept of a server-specific startup probe has merit.

**What to do:** Add a lightweight startup validation in `server/startup.py` -- not a separate module, just a function: try to import foundation, try to resolve the bundle, log a clear error if either fails. 5-10 lines, not a module. This is something neither the plan nor the lean branch currently does well.

### 3. Migration breadcrumb for `distro.yaml`

The plan's Task 2.5 adds `extra="ignore"` to handle old `distro.yaml` files gracefully. The lean branch deleted the config system entirely -- but users with existing `distro.yaml` files get zero feedback. The file just sits there doing nothing.

**What to do:** At server startup, if `~/.amplifier/distro.yaml` exists, log a one-line info message: "distro.yaml is no longer used; configuration is now via environment variables. See README." No migration code, no compat layer -- just a signpost so users aren't confused.

### 4. Commit granularity

The lean branch's 3 commits are honest about what happened -- one massive surgical commit, one docs commit, one README commit. But the plan's 23-task decomposition with individual commits is much better for reviewability and `git bisect`. If the lean branch ever needs to be cherry-picked or partially reverted, the monolithic commit is painful.

**What to do:** This ship has sailed for the existing branch. But if you're going to do more work on the branch (session resume, startup probe, API surface), commit them individually. And consider whether the branch is destined for a squash-merge anyway, in which case this is moot.

---

## Not Worth Bringing Back

| Plan idea | Why it stays deleted |
|---|---|
| **Bridge refactoring (Phase 4)** | `FoundationBackend` is the right replacement. Polishing an abstraction that shouldn't exist wastes effort. |
| **Schema slimming (Phase 2)** | Deleting `distro.yaml` entirely is cleaner than slimming it to 7 fields. Environment variables + foundation's `settings.yaml` cover everything. |
| **`features.py` / `bundle_composer.py` (Phase 5)** | Real bundle directories replace generated bundles. The feature catalog was an intermediate step that's no longer needed. |
| **`doctor.py` (Phase 3.2)** | Lives in `amplifier doctor` via app-cli now. Distro doesn't need its own diagnostic system. |
| **`install_wizard` / `settings` apps** | Too coupled to the dead feature-catalog. Can be rebuilt simply if needed, but shouldn't be resurrected from the old code. |

---

## Worth Creating (neither plan nor lean branch has this)

### Test coverage for `FoundationBackend`

The plan's emphasis on characterization tests before refactoring (Task 4.1) reveals a gap: the lean branch deleted 15 test files and refactored 5, but `FoundationBackend` -- the central new abstraction -- needs its own focused tests. The old bridge tests tested the old bridge; they don't automatically validate the new thing.

Specifically, `FoundationBackend._reconnect()` raising `NotImplementedError` should have a test that documents this as a known gap, not a surprise.

**What to do:** Write a small test file (`test_foundation_backend.py`) covering: session creation happy path (mocking foundation), reconnect raises `NotImplementedError` explicitly, and the `SessionBackend` protocol contract. This is the highest-value testing work for the lean branch right now.

---

## Summary

| Action | Source | Effort |
|---|---|---|
| Define `__init__.py` public API for server extraction | Plan Phase 6 | Small |
| Add startup validation in `server/startup.py` | Plan Phase 3 (kernel of the idea) | Tiny |
| Migration breadcrumb for old `distro.yaml` | Plan Task 2.5 (spirit, not letter) | Tiny |
| `test_foundation_backend.py` | Gap revealed by plan's test discipline | Medium |

Four small things. Everything else in the plan is either already obsolete or correctly deleted on the lean branch.
