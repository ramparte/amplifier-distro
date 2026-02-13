# Implementation Specification: DISTRO-004 Bundle Structure Finalization

## Overview

The distro bundle is currently a list of includes with no local configuration.
The user's provider and model choice are invisible -- hidden inside the include
chain (`foundation:providers/anthropic-sonnet`). The bridge compensates with a
runtime fallback (`_inject_providers()`) that adds providers when the bundle
doesn't have them.

This spec makes the generated bundle self-describing by adding an explicit
`providers:` section as a configuration overlay on top of the include chain.
The include provides infrastructure (module source URL, base config). The local
section provides user preferences (model choice). Both coexist -- foundation's
merge-by-module-ID semantics mean the local config wins for any overlapping
fields.

The spec also fixes the bridge to load the distro bundle by convention file
path instead of looking up a name through the CLI registry.

**Working directory**: `/Users/samule/repo/amplifier-distro`
**Test command**: `uv run python -m pytest tests/ -x -q --ignore=tests/test_services.py`

---

## Design

### Include chain = infrastructure. Local section = preferences.

```yaml
# The generated bundle after this spec:

bundle:
  name: amplifier-distro
  version: 0.1.0

includes:
  - bundle: foundation
  - bundle: foundation:providers/anthropic-sonnet     # infrastructure: module source + base config

providers:
  - module: provider-anthropic                        # preferences: user's model choice
    config:
      default_model: claude-sonnet-4-5
```

At runtime, foundation merges providers by module ID. The include delivers the
`source:` URL and base config (`debug: true`, etc.). The local `providers:`
section delivers the user's `default_model`. Local wins for overlapping keys.

**What the user sees when they `cat` their bundle**: their provider, their model,
their features. No tracing include chains.

**What happens on foundation upgrade**: module bug fixes flow through the include.
The user's model pin holds. They upgrade the model when they choose to, by
editing one line.

### Bridge loads bundle by convention path

The bridge previously resolved bundles by name through the CLI registry
(`load_bundle("my-amplifier", ...)`), which was indirect and fragile. The
install wizard generates `~/.amplifier/bundles/distro.yaml` with provider
includes, but the bridge never loaded it directly.

**Root cause**: The install wizard writes `bundle.active` to `settings.yaml`,
but the bridge reads from `distro.yaml` -- which has no `bundle:` section at
all. So the bridge falls back to `"my-amplifier"`, a name that doesn't exist
in the registry. `_inject_providers()` is the only thing keeping sessions alive.

**Fix**: A `_resolve_distro_bundle()` helper that loads from the convention
path `~/.amplifier/bundles/distro.yaml` directly. Override via
`BridgeConfig.bundle_name` still works for programmatic callers.

---

## Implementation Order

1. `src/amplifier_distro/bundle_composer.py` (modify -- add providers to generated output)
2. `src/amplifier_distro/bridge.py` (modify -- add helper, update 2 methods) **DONE**
3. `tests/test_bundle_composer.py` (modify -- update assertions for new output format)
4. `tests/test_bridge.py` (modify -- update test helper for convention path) **DONE**
5. Run `uv run python -m pytest tests/ -x -q --ignore=tests/test_services.py` -- all existing + new must pass

---

## File 1: `src/amplifier_distro/bundle_composer.py` (MODIFY)

**What to change**: `generate()` function (lines 30-51). Add a `providers:`
section to the generated dict using the selected provider's `module_id` and
`default_model` from `features.py`.

**Current text (lines 30-51):**

```python
def generate(provider_id: str, feature_ids: list[str] | None = None) -> str:
    """Generate bundle YAML string."""
    provider = PROVIDERS[provider_id]
    includes: list[dict[str, str]] = [
        {"bundle": FOUNDATION_INCLUDE},
        {"bundle": provider.include},
    ]

    for fid in feature_ids or []:
        feature = FEATURES[fid]
        includes.extend({"bundle": inc} for inc in feature.includes)

    data = {
        "bundle": {
            "name": BUNDLE_NAME,
            "version": BUNDLE_VERSION,
            "description": "Amplifier Distribution",
        },
        "includes": includes,
    }

    return yaml.dump(data, default_flow_style=False, sort_keys=False)
```

**Replace with:**

```python
def generate(provider_id: str, feature_ids: list[str] | None = None) -> str:
    """Generate bundle YAML string.

    The generated bundle has three sections:
    - bundle: metadata (name, version)
    - includes: infrastructure (foundation + provider module + features)
    - providers: user preferences (model choice as a config overlay)

    The include chain delivers the provider module source URL and base
    config.  The local providers section pins the user's model choice.
    Foundation merges by module ID -- local config wins for overlapping keys.
    """
    provider = PROVIDERS[provider_id]
    includes: list[dict[str, str]] = [
        {"bundle": FOUNDATION_INCLUDE},
        {"bundle": provider.include},
    ]

    for fid in feature_ids or []:
        feature = FEATURES[fid]
        includes.extend({"bundle": inc} for inc in feature.includes)

    # Provider config overlay -- pins the user's model choice.
    # The include chain provides the module source URL and base config.
    provider_config: dict[str, Any] = {
        "module": provider.module_id,
        "config": {"default_model": provider.default_model},
    }
    if provider.base_url:
        provider_config["config"]["base_url"] = provider.base_url

    data: dict[str, Any] = {
        "bundle": {
            "name": BUNDLE_NAME,
            "version": BUNDLE_VERSION,
            "description": "Amplifier Distribution",
        },
        "includes": includes,
        "providers": [provider_config],
    }

    return yaml.dump(data, default_flow_style=False, sort_keys=False)
```

**Add import**: At the top of the file (line 10), add `Any` to the typing import.

**Current import (line 10):**

```python
from typing import Any
```

Already present -- no change needed.

**Result**: Generated bundle now has a `providers:` section with the user's
module and model. The include chain still provides the source URL and base
config. Both coexist via merge-by-module-ID.

---

## File 2: `src/amplifier_distro/bridge.py` (MODIFY) -- DONE

Three changes: add imports, add `_resolve_distro_bundle()` helper, update
both `create_session()` and `resume_session()`.

### Change 2a: Add imports (lines 35-40)

**Current import:**

```python
from amplifier_distro.conventions import (
    AMPLIFIER_HOME,
    HANDOFF_FILENAME,
    PROJECTS_DIR,
    TRANSCRIPT_FILENAME,
)
```

**Replace with:**

```python
from amplifier_distro.conventions import (
    AMPLIFIER_HOME,
    DISTRO_BUNDLE_DIR,
    DISTRO_BUNDLE_FILENAME,
    HANDOFF_FILENAME,
    PROJECTS_DIR,
    TRANSCRIPT_FILENAME,
)
```

### Change 2b: Add `_resolve_distro_bundle()` helper to `LocalBridge`

Add after `__init__`:

```python
    @staticmethod
    def _resolve_distro_bundle(bundle_name_override: str | None) -> str:
        """Resolve the bundle reference to load.

        If *bundle_name_override* is set (e.g. from BridgeConfig.bundle_name),
        use it as-is -- it flows through foundation's normal name/path resolution.

        Otherwise, load from the convention path that the install wizard
        generates: ``~/.amplifier/bundles/distro.yaml``.
        """
        if bundle_name_override:
            return bundle_name_override
        path = (
            Path(AMPLIFIER_HOME).expanduser()
            / DISTRO_BUNDLE_DIR
            / DISTRO_BUNDLE_FILENAME
        )
        if not path.exists():
            raise RuntimeError(
                f"No distro bundle found at {path}. "
                "Run the install wizard or 'amp distro init' to set up."
            )
        return str(path)
```

**Why a helper**: The resolution logic is identical for `create_session()` and
`resume_session()`. Extracting it avoids a 10-line copy-paste in a 700+ line
file and gives tests a single target for the missing-bundle error path.

### Change 2c: `create_session()` bundle resolution + error wrapping

**Current text:**

```python
        # 4. Determine bundle
        bundle_name = config.bundle_name or distro.get("bundle", {}).get(
            "active", "my-amplifier"
        )

        # ...

        # 6. Load and prepare bundle
        registry = BundleRegistry()
        bundle = await load_bundle(bundle_name, registry=registry)
        prepared = await bundle.prepare()

        # ...

        logger.info(
            "Session created: id=%s project=%s bundle=%s",
            sid,
            project_id,
            bundle_name,
        )
```

**Replace with:**

```python
        # 4. Determine bundle
        bundle_ref = self._resolve_distro_bundle(config.bundle_name)

        # ...

        # 6. Load and prepare bundle
        registry = BundleRegistry()
        try:
            bundle = await load_bundle(bundle_ref, registry=registry)
        except Exception as e:
            raise RuntimeError(
                f"Failed to load distro bundle at {bundle_ref}: {e}\n"
                "If you edited this file manually, check for YAML syntax errors.\n"
                "To regenerate: amp distro init"
            ) from e
        prepared = await bundle.prepare()

        # ...

        logger.info(
            "Session created: id=%s project=%s bundle=%s",
            sid,
            project_id,
            bundle_ref,
        )
```

**Three fixes in one**:
1. Convention path via helper (replaces name-based registry lookup)
2. `try/except` around `load_bundle()` (catches malformed YAML, permission
   errors, and other load failures with an actionable message)
3. `bundle_name` -> `bundle_ref` in logger (the old spec had a NameError
   bug here -- the variable was renamed but the logging line was not)

### Change 2d: `resume_session()` -- same three fixes

**Current text:**

```python
        # 3. Determine bundle from distro config
        distro = self._load_distro_config()
        bundle_name = config.bundle_name or distro.get("bundle", {}).get(
            "active", "my-amplifier"
        )

        # 4. Load and prepare bundle
        registry = BundleRegistry()
        bundle = await load_bundle(bundle_name, registry=registry)
        prepared = await bundle.prepare()

        # ...

        logger.info(
            "Session resumed: id=%s project=%s bundle=%s",
            session.coordinator.session_id,
            project_id,
            bundle_name,
        )
```

**Replace with:**

```python
        # 3. Determine bundle
        bundle_ref = self._resolve_distro_bundle(config.bundle_name)

        # 4. Load and prepare bundle
        registry = BundleRegistry()
        try:
            bundle = await load_bundle(bundle_ref, registry=registry)
        except Exception as e:
            raise RuntimeError(
                f"Failed to load distro bundle at {bundle_ref}: {e}\n"
                "If you edited this file manually, check for YAML syntax errors.\n"
                "To regenerate: amp distro init"
            ) from e
        prepared = await bundle.prepare()

        # ...

        logger.info(
            "Session resumed: id=%s project=%s bundle=%s",
            session.coordinator.session_id,
            project_id,
            bundle_ref,
        )
```

**Note**: The `distro = self._load_distro_config()` call is removed from step 3.
It was only used for `bundle.active` lookup. `_inject_providers()` does its own
`_load_distro_config()` call internally (cached), so there is no lost read.

---

## File 3: `tests/test_bundle_composer.py` (MODIFY)

**What to change**: Tests that assert on `generate()` output need to verify
the new `providers:` section exists.

Find the test that checks the output has only `bundle:` and `includes:` keys
(e.g., `test_without_features_has_only_foundation_and_provider` or similar).
Add assertions:

```python
    # Verify providers section exists
    assert "providers" in data
    assert len(data["providers"]) == 1
    assert data["providers"][0]["module"] == "provider-anthropic"
    assert data["providers"][0]["config"]["default_model"] == "claude-sonnet-4-5"
```

If no existing test checks the full output structure, add a new test:

```python
def test_generate_includes_provider_config(self):
    """Generated bundle has a providers section with model config."""
    content = generate("anthropic")
    data = yaml.safe_load(content)
    assert "providers" in data
    providers = data["providers"]
    assert len(providers) == 1
    assert providers[0]["module"] == "provider-anthropic"
    assert providers[0]["config"]["default_model"] == "claude-sonnet-4-5"


def test_generate_openai_provider_config(self):
    """OpenAI provider generates correct module and model."""
    content = generate("openai")
    data = yaml.safe_load(content)
    providers = data["providers"]
    assert providers[0]["module"] == "provider-openai"
    assert providers[0]["config"]["default_model"] == "gpt-4o"
```

---

## File 4: `tests/test_bridge.py` (MODIFY) -- DONE

**What changed**: The test helper `_make_bridge_and_config()` now passes
`bundle_name="test-bundle"` explicitly in `BridgeConfig`. Previously it relied
on `bundle.active` being read from the mocked distro config. Since the bridge
no longer reads that field (it uses the convention path), tests that exercise
bridge behavior (not bundle resolution) must use the explicit override.

**Current text:**

```python
        config = BridgeConfig(
            working_dir=Path("~/dev/test-project").expanduser(),
            run_preflight=False,
        )
```

**Replace with:**

```python
        config = BridgeConfig(
            working_dir=Path("~/dev/test-project").expanduser(),
            bundle_name="test-bundle",
            run_preflight=False,
        )
```

---

## Swarm Evaluation Findings

This spec was evaluated by 9 agents across 8 providers (Anthropic opus/sonnet,
OpenAI codex/o3, Gemini, GitHub Copilot). Key findings below. Items marked
DONE were addressed in the bridge implementation. Items marked FOLLOW-UP
need separate work.

### Unanimous: core design is correct

All 9 agents agreed convention-path loading is the right architecture.
Foundation's `load_bundle()` handles file paths natively. The indirection
through the CLI registry name resolution adds a failure mode with zero benefit.

### DONE: NameError bug in original spec

The original spec renamed `bundle_name` to `bundle_ref` but did not update
the logging statements at lines 322 and 479. This would have crashed every
session create/resume on the happy path. Fixed by using `bundle_ref`
throughout and extracting `_resolve_distro_bundle()` to avoid duplication.

### DONE: no error handling for malformed YAML

The most common user-triggered failure (bad manual edit, truncated save,
editor crash) produced a raw `yaml.ScannerError` traceback with no actionable
guidance. Fixed with `try/except` around `load_bundle()` in both methods.

### FOLLOW-UP: `bundle.active` is now a dead config field

After this change, `bundle.active` in `distro.yaml` is read by nothing.
Users who set it to a custom value get silently ignored. This violates
OPINIONS.md Section 5 ("errors are loud, not silent").

**Recommended fix (Option D from evaluation):** Add a Pydantic
`model_validator` that emits a `DeprecationWarning` when the field is
present. Remove the field entirely in the next release.

**Documentation that needs updating:**
- OPINIONS.md Section 5 (shows `bundle.active: my-amplifier` as example)
- conventions.py lines 8-9 (lists "which bundle is active" as configurable)
- ROADMAP.md line 88 (shows `active bundle` in dependency tree)

### FOLLOW-UP: info disclosure in error messages

The `RuntimeError` includes the full expanded filesystem path (e.g.
`/Users/samule/.amplifier/bundles/distro.yaml`). The web_chat app catches
`RuntimeError` and returns `str(e)` in a 503 response. This leaks the
server's filesystem layout to HTTP clients.

**Fix:** Sanitize paths in errors returned to HTTP surfaces, or use
`~/.amplifier/...` (unexpanded) in error messages.

### FOLLOW-UP: `_inject_providers()` should log WARNING, not INFO

When the safety net fires (bundle has no providers, fallback injects them),
it currently logs at INFO level. In a system where "errors are loud," this
should be WARNING with an actionable message pointing to `amp distro doctor`.

### FOLLOW-UP: root cause of the bug this spec fixes

The install wizard writes `bundle.active` to `settings.yaml`, but the bridge
reads from `distro.yaml` -- which has no `bundle:` section. So the bridge
falls back to `"my-amplifier"`, a name that doesn't exist in the registry.
`_inject_providers()` is the only thing keeping sessions alive today. This
spec fixes the symptom (bridge loads by path). The root cause (settings.yaml
vs distro.yaml split) should be audited separately.

---

## What does NOT change

- `schema.py` -- `BundleConfig.active` default stays `"my-amplifier"` for now.
  The field is effectively dead for the bridge (nothing reads it). A follow-up
  should either deprecate it with a warning or remove it entirely.
- `features.py` -- no changes (already has `module_id`, `default_model`, `source_url`).
- `_inject_providers()` -- kept as safety net, becomes no-op when bundle has providers.
- `install_wizard/` -- no changes.
- `settings.yaml` -- keeps CLI bundle registry role.
- `keys.yaml` / secrets -- unchanged.
- `startup.py` -- unchanged.

---

## Risks

| Risk | Mitigation |
|------|------------|
| User hasn't run install wizard | Actionable RuntimeError with setup instructions |
| Bundle file exists but is malformed YAML | `try/except` around `load_bundle()` with "check syntax" message |
| Include chain fails (network, missing cache) | `_inject_providers()` remains as fallback |
| `generate()` adds providers but `add_feature()`/`set_tier()` might lose them | Verified: those methods use read-merge-write (read full dict, modify includes only, write back). Providers survive. |
| `config.bundle_name` override from surfaces | Honored when set; convention path is only the default |
| `bundle.active` set by user, now ignored | Follow-up: add deprecation warning or remove the field |

---

## Follow-up (separate tasks)

- **Deprecate `bundle.active`**: The bridge no longer reads it. Either add a
  `model_validator` that emits a deprecation warning when the field is set,
  or remove the field entirely. Update OPINIONS.md Section 5 and
  conventions.py lines 8-9 accordingly.
- Remove `_inject_providers()` once convention path is confirmed stable.
- Fix `write()` / `change_provider()` read-merge-write so user sections survive provider changes.
- Address xAI/OpenAI include collision (`get_current_provider()` bug).
- Add missing foundation provider bundles (gemini-pro, ollama, azure-openai).
- Deprecate `KeplerConfig.default_provider` in favor of bundle providers.

---

## Success Criteria

1. `cat ~/.amplifier/bundles/distro.yaml` shows the user's provider and model.
2. User runs install wizard, starts server, `@Distro new session` works.
3. Bridge loads bundle from convention path by default.
4. Missing bundle produces: `RuntimeError: No distro bundle found at ...`
5. Malformed bundle produces: `RuntimeError: Failed to load ... check YAML syntax`
6. `_inject_providers()` is never triggered when bundle is loaded by path.
7. All existing tests pass + new tests pass.
