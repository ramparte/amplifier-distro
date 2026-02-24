# Amplifier Distro Big Bang Refactor

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Slim the distro to only what's genuinely unique (system inventory, setup experience, cross-app coordination), eliminate duplication with foundation and CLI, and prepare the server for extraction.

**Architecture:** The distro remains a coordination layer (Vision A) but stops reimplementing what foundation's `settings.yaml` and the CLI already handle. `distro.yaml` shrinks to system inventory only. Dead modules are deleted. The Bridge's create/resume duplication is extracted. Server imports are channeled through a public API surface.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, pytest (async via pytest-asyncio), uv for package management.

**Test runner:** `uv run python -m pytest tests/ -q`

**Pre-existing test failures (NOT regressions -- do not fix):**
- `test_deploy.py::TestDockerContainerPolish::test_dockerfile_has_nonroot_user`
- `test_settings_api.py::TestGetIntegrations::test_slack_not_configured_by_default`
- `test_settings_api.py::TestGetIntegrations::test_voice_not_configured_by_default`
- `test_slack_bridge.py::TestSlackSetup::test_channels_no_token`

---

## Phase 1: Delete Dead Weight

Delete modules that are genuinely dead or superseded. This is safe, mechanical work.

### Task 1.1: Delete `deploy.py` and its tests

**Files:**
- Delete: `src/amplifier_distro/deploy.py` (302 lines)
- Delete: `tests/test_deploy.py` (188 lines, 25 tests)

**Step 1: Verify no imports of deploy exist outside test**

Run:
```bash
grep -rn "from.*deploy\|import.*deploy" src/amplifier_distro/ tests/ --include="*.py" | grep -v __pycache__ | grep -v test_deploy | grep -v deploy.py
```
Expected: No matches (already verified: `deploy.py` is standalone, no other module imports it).

**Step 2: Delete the files**

```bash
rm src/amplifier_distro/deploy.py
rm tests/test_deploy.py
```

**Step 3: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: Same pass/fail count as baseline (minus the 25 deleted deploy tests and 1 pre-existing deploy failure). All other tests pass.

**Step 4: Commit**
```
git add -A && git commit -m "refactor: delete deploy.py (dead module, never production-ready)"
```

---

### Task 1.2: Delete `provider_api.py` and its tests

**Files:**
- Delete: `src/amplifier_distro/provider_api.py` (572 lines)
- Delete: `tests/test_provider_api.py` (399 lines, 20 tests)

**Step 1: Verify no imports of provider_api exist outside test**

Run:
```bash
grep -rn "from.*provider_api\|import.*provider_api" src/ tests/ --include="*.py" | grep -v __pycache__ | grep -v test_provider_api | grep -v provider_api.py
```
Expected: No matches. The server's `/test-provider` endpoint in `server/app.py:358-399` has its own inline implementation -- it does NOT import `provider_api.py`.

**Step 2: Delete the files**

```bash
rm src/amplifier_distro/provider_api.py
rm tests/test_provider_api.py
```

**Step 3: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: Same pass count, minus the 20 deleted provider_api tests.

**Step 4: Commit**
```
git add -A && git commit -m "refactor: delete provider_api.py (server has inline test-provider endpoint)"
```

---

### Task 1.3: Delete `update_check.py` and remove imports from `cli.py`

This is slightly more involved because `cli.py` imports from `update_check`.

**Files:**
- Delete: `src/amplifier_distro/update_check.py` (338 lines)
- Modify: `src/amplifier_distro/cli.py` (lines 23-29 imports, plus usage at lines 160, 185, 579, 614, 689-693)

**Step 1: Read cli.py to understand all update_check usage**

The imports at `cli.py:23-29`:
```python
from .update_check import (
    _get_distro_version,
    _get_package_status,
    _is_editable_install,
    get_version_info,
    run_self_update,
)
```

Usage locations in `cli.py`:
- Line 185: `install_mode = "editable" if _is_editable_install() else "installed"`
- Line 579: `info = get_version_info()` (in a `version` command)
- Line 614: `success, message = run_self_update()` (in an `update` command)
- Lines 689-693: `_is_editable_install()`, `_get_package_status()`, `_get_distro_version()` (in a status command)

**Step 2: Remove the import block from cli.py**

In `src/amplifier_distro/cli.py`, remove lines 23-29:
```python
from .update_check import (
    _get_distro_version,
    _get_package_status,
    _is_editable_install,
    get_version_info,
    run_self_update,
)
```

**Step 3: Replace all usage in cli.py with stubs**

For each function call site, replace with a simple inline message directing users to `uv`:

- Where `_is_editable_install()` is called: replace with a check using `importlib.metadata`:
  ```python
  def _is_editable_install() -> bool:
      """Check if amplifier-distro is installed in editable mode."""
      try:
          from importlib.metadata import packages_distributions
          return True  # Rough check; uv handles updates now
      except Exception:
          return False
  ```

- Where `get_version_info()` is called (the `version` command): simplify to just print the package version:
  ```python
  from importlib.metadata import version as pkg_version, PackageNotFoundError
  try:
      ver = pkg_version("amplifier-distro")
  except PackageNotFoundError:
      ver = "unknown"
  click.echo(f"amplifier-distro {ver}")
  ```

- Where `run_self_update()` is called (the `update` command): replace with guidance:
  ```python
  click.echo("Self-update has been removed. Use uv to update:")
  click.echo("  uv tool upgrade amplifier-distro")
  ```

- Where `_get_package_status()` and `_get_distro_version()` are called (status command): simplify to just show the installed version.

Read the full `cli.py` file to identify the exact click commands and replace them precisely. The goal is: delete update_check.py entirely, keep the CLI commands working but simplified.

**Step 4: Delete update_check.py**

```bash
rm src/amplifier_distro/update_check.py
```

Note: There is no `tests/test_update_check.py` file -- the update_check functions are tested through the CLI tests.

**Step 5: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass.

**Step 6: Commit**
```
git add -A && git commit -m "refactor: delete update_check.py (replaced by uv tooling)"
```

---

### Task 1.4: Delete `migrate.py` and remove import from `cli.py`

**Files:**
- Delete: `src/amplifier_distro/migrate.py` (78 lines)
- Modify: `src/amplifier_distro/cli.py` (line 20 import, line 160 usage)

**Step 1: Remove the import from cli.py**

In `src/amplifier_distro/cli.py`, remove line 20:
```python
from .migrate import migrate_memory
```

**Step 2: Find and update the migrate_memory() call site**

At `cli.py:160`, `migrate_memory()` is called during the `init` command. Read the surrounding context to understand the flow. Replace the migration call with a simple directory creation:

```python
# Ensure memory directory exists (migration from legacy paths no longer needed)
memory_dir = Path(config.memory.path).expanduser()
memory_dir.mkdir(parents=True, exist_ok=True)
```

**Step 3: Delete migrate.py**

```bash
rm src/amplifier_distro/migrate.py
```

Note: There is no `tests/test_migrate.py` file.

**Step 4: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass.

**Step 5: Commit**
```
git add -A && git commit -m "refactor: delete migrate.py (one-time migration, already run)"
```

---

### Task 1.5: Clean conventions.py of dead references

**Files:**
- Modify: `src/amplifier_distro/conventions.py`

After deleting `update_check.py` and `deploy.py`, some constants in `conventions.py` are now unused:

**Step 1: Identify unused constants**

Run:
```bash
grep -rn "UPDATE_CHECK_CACHE_FILENAME\|UPDATE_CHECK_TTL_HOURS\|PYPI_PACKAGE_NAME\|GITHUB_REPO\b\|GITHUB_REPO_URL\|PACKAGE_REPOS" src/amplifier_distro/ --include="*.py" | grep -v __pycache__ | grep -v conventions.py
```

For each constant with zero matches outside `conventions.py`, it's dead.

**Step 2: Remove dead constants from conventions.py**

Remove the `--- Update Check ---` section (lines 108-121 in `conventions.py`) if no other module references those constants:
```python
# --- Update Check ---
UPDATE_CHECK_CACHE_FILENAME = "update-check.json"  # relative to CACHE_DIR
# Full path: ~/.amplifier/cache/update-check.json
UPDATE_CHECK_TTL_HOURS = 24  # Don't re-check more than once per day
PYPI_PACKAGE_NAME = "amplifier-distro"
GITHUB_REPO = "ramparte/amplifier-distro"
GITHUB_REPO_URL = "https://github.com/ramparte/amplifier-distro"

# Package-to-repo mapping for version/update checks
PACKAGE_REPOS: dict[str, str] = {
    "amplifier-distro": GITHUB_REPO,
    "amplifier-app-cli": "microsoft/amplifier",
    "amplifier-tui": "ramparte/amplifier-tui",
}
```

Also check if `LEGACY_MEMORY_DIR` (line 39) is still referenced after `migrate.py` deletion. If not, remove it too.

**Step 3: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass.

**Step 4: Commit**
```
git add -A && git commit -m "refactor: remove dead conventions for deleted modules"
```

---

## Phase 2: Slim the Schema

Audit `distro.yaml` field by field. Remove fields that duplicate `settings.yaml`. Keep only distro-specific system inventory.

### Task 2.1: Audit and document the field-by-field plan

Before writing code, study the current `DistroConfig` (in `src/amplifier_distro/schema.py:182-197`) and decide what stays vs goes:

**Keep in `distro.yaml` (system inventory -- genuinely unique to distro):**

| Field | Why it stays |
|-------|-------------|
| `interfaces: InterfacesConfig` | System inventory: what's installed, where |
| `server: ServerConfig` | Server-specific: API key, location |
| `backup: BackupConfig` | Distro-specific: backup repo, auto-backup |
| `preflight: PreflightConfig` | Distro-specific: enabled, mode |
| `slack: SlackConfig` | App-specific config (moves to Slack's own config eventually, but stays for now) |
| `voice: VoiceConfig` | App-specific config (same reasoning) |
| `watchdog: WatchdogConfig` | Server-specific: health monitoring |

**Remove from `distro.yaml` (already in foundation's settings.yaml or env):**

| Field | Where it goes |
|-------|---------------|
| `workspace_root: str` | Foundation's `settings.yaml` -- the CLI and foundation already know this |
| `identity: IdentityConfig` | Foundation's `settings.yaml` / `gh` CLI detection |
| `bundle: BundleConfig` | Foundation's bundle registry / `settings.yaml` |
| `cache: CacheConfig` | Foundation's cache management |
| `memory: MemoryConfig` | Foundation's `settings.yaml` |
| `kepler: KeplerConfig` | Kepler's own config (never belonged in distro) |

**This is a documentation/analysis step -- no code changes yet.** Write the above table as a comment in your working notes so you reference it during implementation.

---

### Task 2.2: Remove `KeplerConfig` from schema

`KeplerConfig` is the easiest removal -- it's app-specific config that should live in Kepler's own repo.

**Files:**
- Modify: `src/amplifier_distro/schema.py` (remove `KeplerConfig` class at lines 158-175 and field at line 197)
- Modify: `src/amplifier_distro/bridge.py` (line 890-892 reads `kepler.default_provider` as a fallback -- replace with a hardcoded default or env var)

**Step 1: Search for all references to `kepler` in the codebase**

Run:
```bash
grep -rn "kepler\|KeplerConfig" src/amplifier_distro/ --include="*.py" | grep -v __pycache__
```

Document every reference. Common ones:
- `schema.py:158-175` -- the class definition
- `schema.py:197` -- the field on `DistroConfig`
- `bridge.py:889-892` -- fallback provider resolution from `kepler.default_provider`
- Possibly `server/apps/settings/` -- the settings UI may display Kepler config

**Step 2: Remove KeplerConfig from schema.py**

Delete the `KeplerConfig` class (lines 158-175) and remove the `kepler` field from `DistroConfig` (line 197).

**Step 3: Fix bridge.py fallback**

In `bridge.py:_inject_providers()` (around line 889), the code does:
```python
kepler = distro.get("kepler", {})
default_provider = kepler.get("default_provider", "anthropic")
default_model = kepler.get("default_model", "")
```

Replace with:
```python
default_provider = "anthropic"
default_model = ""
```

This hardcoded default is fine -- the provider preferences should come from the calling app via `BridgeConfig.provider_preferences`, not from distro.yaml's Kepler section.

**Step 4: Fix any other references found in Step 1**

If the settings UI references Kepler config, update those endpoints to not crash when `kepler` is missing from distro.yaml. The safest approach is to handle the missing field gracefully (return empty/defaults).

**Step 5: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass. Some test fixtures may create `DistroConfig` with `kepler=...` -- if those tests fail, update them to remove the kepler field.

**Step 6: Commit**
```
git add -A && git commit -m "refactor: remove KeplerConfig from distro schema (belongs in Kepler's own config)"
```

---

### Task 2.3: Remove `workspace_root` and `identity` from schema

**Files:**
- Modify: `src/amplifier_distro/schema.py` (remove `IdentityConfig` class, `workspace_root` field, and `workspace_root_must_look_like_path` validator)
- Modify: `src/amplifier_distro/config.py` (remove `detect_workspace_root` and `detect_github_identity`)
- Modify: `src/amplifier_distro/cli.py` (imports and uses of removed config fields)
- Modify: `src/amplifier_distro/bridge.py` (line 854 reads `workspace_root` for `get_project_id`)
- Modify: `src/amplifier_distro/doctor.py` (lines 406-435: `_check_identity` and `_check_workspace` read these fields)
- Update: various test files that create `DistroConfig` with these fields

**Step 1: Search for all references**

Run:
```bash
grep -rn "workspace_root\|IdentityConfig\|identity\.\|github_handle\|git_email\|detect_workspace_root\|detect_github_identity" src/amplifier_distro/ --include="*.py" | grep -v __pycache__
```

This will be a substantial list. Each reference needs to be updated:
- References in `bridge.py:get_project_id()` (line 854) need to get `workspace_root` from environment or foundation's settings instead of distro.yaml.
- References in `doctor.py` checks need to be removed or redirected.
- References in `cli.py`'s `init` command need to stop writing these to distro.yaml.

**Step 2: Remove from schema.py**

- Delete `IdentityConfig` class (lines 54-56)
- Remove `workspace_root` field and its validator (lines 185, 199-216)
- Remove `identity` field (line 186)

**Step 3: Update bridge.py:get_project_id()**

Currently reads `workspace_root` from distro config:
```python
distro = self._load_distro_config()
workspace = Path(distro.get("workspace_root", "~/dev")).expanduser()
```

Replace with environment variable or a reasonable default:
```python
import os
workspace_str = os.environ.get("AMPLIFIER_WORKSPACE_ROOT", "~/dev")
workspace = Path(workspace_str).expanduser()
```

**Step 4: Update doctor.py**

Remove `_check_identity()` (lines 405-418) and `_check_workspace()` (lines 421-435). Remove their calls from `run_diagnostics()` (lines 457-458). These checks duplicate what the CLI already does during `init`.

**Step 5: Update config.py**

Remove `detect_workspace_root()` (lines 90-107) and `detect_github_identity()` (lines 59-87). These are only used by `cli.py`'s `init` command. If `cli.py` still needs them, keep them in `cli.py` directly as local functions.

**Step 6: Update cli.py**

The `init` command currently writes `workspace_root` and `identity` to distro.yaml. Remove those writes. If the init flow still needs to detect these values (e.g., to write them to foundation's `settings.yaml` instead), move the detection logic into cli.py as local helpers.

**Step 7: Update tests**

Search for test files creating `DistroConfig(workspace_root=..., identity=...)` and remove those fields from the constructor calls.

Run:
```bash
grep -rn "workspace_root\|identity\|IdentityConfig" tests/ --include="*.py" | grep -v __pycache__
```

**Step 8: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass.

**Step 9: Commit**
```
git add -A && git commit -m "refactor: remove workspace_root and identity from distro schema (defer to foundation)"
```

---

### Task 2.4: Remove `bundle`, `cache`, and `memory` from schema

**Files:**
- Modify: `src/amplifier_distro/schema.py` (remove `BundleConfig`, `CacheConfig`, `MemoryConfig` classes and fields)
- Modify: `src/amplifier_distro/bridge.py` (bundle resolution at lines 326-337 reads `config.bundle.active`)
- Modify: `src/amplifier_distro/preflight.py` (line 109 reads `config.memory.path`)
- Update: test files

**Step 1: Search for all references**

Run:
```bash
grep -rn "BundleConfig\|CacheConfig\|MemoryConfig\|\.bundle\.\|\.cache\.\|\.memory\." src/amplifier_distro/ --include="*.py" | grep -v __pycache__
```

**Step 2: Remove from schema.py**

Delete:
- `BundleConfig` class (lines 59-62)
- `CacheConfig` class (lines 65-68)
- `MemoryConfig` class (lines 71-76)
- Fields from `DistroConfig`: `bundle` (line 187), `cache` (line 188), `memory` (line 191)

**Step 3: Update bridge.py bundle resolution**

In `_resolve_distro_bundle()` (line 326-337), the code reads `config.bundle.active`:
```python
config = load_config()
active = config.bundle.active
```

Replace with reading from foundation's `settings.yaml` or environment:
```python
import os
active = os.environ.get("AMPLIFIER_BUNDLE", "")
```

Or better, read from the bundle registry file directly:
```python
from amplifier_distro.conventions import AMPLIFIER_HOME, SETTINGS_FILENAME
settings_path = Path(AMPLIFIER_HOME).expanduser() / SETTINGS_FILENAME
if settings_path.exists():
    import yaml
    settings = yaml.safe_load(settings_path.read_text()) or {}
    active = settings.get("bundle", {}).get("active", "")
```

However, the simplest approach: keep the convention-path fallback (lines 341-352) as the primary resolution, since the install wizard generates a bundle at that path. The `bundle.active` override from config was a secondary path. Remove the config-based lookup, keep only: explicit override -> convention path -> error.

**Step 4: Update preflight.py**

Line 109 reads `config.memory.path`. Replace with the convention default:
```python
from .conventions import AMPLIFIER_HOME, MEMORY_DIR
memory_path = Path(AMPLIFIER_HOME).expanduser() / MEMORY_DIR
```

**Step 5: Update tests and run suite**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass.

**Step 6: Commit**
```
git add -A && git commit -m "refactor: remove bundle/cache/memory from distro schema (defer to foundation)"
```

---

### Task 2.5: Update config.py to match slimmed schema

After removing fields from `DistroConfig`, `config.py`'s `save_config` serializes the full model. Verify it still works correctly with the slimmed schema.

**Files:**
- Modify: `src/amplifier_distro/config.py` (if needed)
- Verify: `load_config()` gracefully handles old distro.yaml files that still have the removed fields (Pydantic's `model_config = ConfigDict(validate_assignment=True)` should ignore unknown fields if we add `extra = "ignore"`)

**Step 1: Add `extra = "ignore"` to DistroConfig**

In `src/amplifier_distro/schema.py`, update the model config:
```python
class DistroConfig(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="ignore")
```

This ensures that existing distro.yaml files with old fields (workspace_root, identity, etc.) load without errors -- the unknown fields are silently ignored.

**Step 2: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass.

**Step 3: Commit**
```
git add -A && git commit -m "refactor: add extra=ignore to DistroConfig for backward compat with old distro.yaml files"
```

---

## Phase 3: Slim Preflight and Doctor

Remove checks that duplicate what the CLI already handles. Keep only distro-specific checks.

### Task 3.1: Slim preflight.py

**Files:**
- Modify: `src/amplifier_distro/preflight.py`
- Modify: `tests/test_phase0.py` or `tests/test_phase1.py` (if they test preflight checks)

**Current checks in `preflight.py:run_preflight()` (lines 34-134):**

| Check | Distro-specific? | Action |
|-------|-----------------|--------|
| 1. distro.yaml exists | YES | Keep |
| 2. GitHub CLI authenticated | NO (CLI handles) | Remove |
| 3. Identity configured | Removed in Phase 2 | Remove |
| 4. ANTHROPIC_API_KEY set | NO (env/CLI handles) | Remove |
| 5. OPENAI_API_KEY set | NO (env/CLI handles) | Remove |
| 6. Workspace root exists | Removed in Phase 2 | Remove |
| 7. Memory store location | NO (convention) | Remove |
| 8. Amplifier CLI installed | NO (CLI is self-aware) | Remove |

**Step 1: Reduce preflight.py to distro-specific checks only**

Rewrite `run_preflight()` to keep only Check 1 (distro.yaml exists). Add a new check: "server reachable" (if server URL is configured). The function body should shrink from ~100 lines to ~20 lines.

```python
def run_preflight() -> PreflightReport:
    """Run distro-specific pre-flight checks."""
    report = PreflightReport()

    # Check: distro.yaml exists and is valid
    path = config_path()
    if path.exists():
        report.checks.append(CheckResult("distro.yaml", True, f"Found at {path}"))
    else:
        report.checks.append(
            CheckResult(
                "distro.yaml", False, f"Not found at {path}. Run 'amp-distro init'"
            )
        )

    return report
```

Also remove the `_check_api_key` helper (lines 137-149) since no checks use it anymore.

Remove the unused imports: `os`, `shutil`, `subprocess`, and the schema imports (`looks_like_path`, `normalize_path`) that were used by the removed checks.

**Step 2: Update tests**

Run:
```bash
grep -rn "run_preflight\|PreflightReport\|CheckResult" tests/ --include="*.py" | grep -v __pycache__
```

Update any tests that assert on the removed checks (GitHub CLI, API keys, etc.).

**Step 3: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass.

**Step 4: Commit**
```
git add -A && git commit -m "refactor: slim preflight to distro-specific checks only"
```

---

### Task 3.2: Slim doctor.py

**Files:**
- Modify: `src/amplifier_distro/doctor.py`
- Modify: `tests/test_doctor.py`

**Current checks in `doctor.py:run_diagnostics()` (lines 443-477):**

| Check | Distro-specific? | Action |
|-------|-----------------|--------|
| `_check_config_exists` | YES | Keep |
| `_check_identity` | Removed in Phase 2 | Remove |
| `_check_workspace` | Removed in Phase 2 | Remove |
| `_check_amplifier_installed` | NO (CLI self-check) | Remove |
| `_check_memory_dir` | YES (distro manages memory path) | Keep |
| `_check_keys_permissions` | YES (security check) | Keep |
| `_check_bundle_cache` | YES (distro cache dir) | Keep |
| `_check_server_dir` | YES (server infrastructure) | Keep |
| `_check_server_running` | YES (server infrastructure) | Keep |
| `_check_git_configured` | NO (CLI handles) | Remove |
| `_check_gh_authenticated` | NO (CLI handles) | Remove |
| `_check_slack_configured` | Marginal (app-specific) | Remove |
| `_check_voice_configured` | Marginal (app-specific) | Remove |

**Step 1: Remove non-distro-specific check functions**

Delete these functions from `doctor.py`:
- `_check_identity()` (lines 405-418) -- already gone from Phase 2
- `_check_workspace()` (lines 421-435) -- already gone from Phase 2
- `_check_amplifier_installed()` (lines 390-402)
- `_check_git_configured()` (lines 251-295)
- `_check_gh_authenticated()` (lines 298-329)
- `_check_slack_configured()` (lines 332-358)
- `_check_voice_configured()` (lines 361-387)

**Step 2: Update run_diagnostics() to remove calls to deleted checks**

Remove lines 457-458 (identity, workspace), 459 (amplifier_installed), 471-476 (git, gh, slack, voice) from `run_diagnostics()`.

The remaining checks should be:
```python
report.checks.append(_check_config_exists(amplifier_home))
report.checks.append(_check_memory_dir(amplifier_home))
report.checks.append(_check_keys_permissions(amplifier_home))
report.checks.append(_check_bundle_cache(amplifier_home))
report.checks.append(_check_server_dir(amplifier_home))
report.checks.append(_check_server_running(amplifier_home))
```

**Step 3: Clean up unused imports**

Remove `shutil`, `subprocess` from doctor.py imports since the deleted checks were the only users.

**Step 4: Also clean up run_fixes() if it references deleted checks**

`run_fixes()` at lines 481-528 matches on check names. Verify that no deleted check names appear in the fix logic.

**Step 5: Update tests/test_doctor.py**

Run:
```bash
grep -rn "git_configured\|gh_authenticated\|amplifier_installed\|slack_configured\|voice_configured\|_check_identity\|_check_workspace" tests/test_doctor.py
```

Remove test methods that test the deleted checks.

**Step 6: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass.

**Step 7: Commit**
```
git add -A && git commit -m "refactor: slim doctor to distro-specific checks only (remove CLI-duplicated checks)"
```

---

## Phase 4: Refactor Bridge

Extract the ~60% duplicated code between `create_session` and `resume_session` into `_prepare_session()`.

### Task 4.1: Write characterization test for Bridge create/resume

Before refactoring, ensure the existing behavior is captured by tests.

**Files:**
- Read: `tests/test_bridge.py` and `tests/test_bridge_resume.py`
- Possibly modify: `tests/test_bridge.py`

**Step 1: Read existing bridge tests**

Read `tests/test_bridge.py` and `tests/test_bridge_resume.py` to understand what's already tested. The key behaviors to verify are preserved:

1. Bundle resolution: override -> config -> convention path
2. Provider injection when bundle has no providers
3. Handoff injection on create
4. Transcript loading and orphan stripping on resume
5. session-info.json write on create, read on resume
6. Streaming hook registration
7. Transcript persistence hook registration

**Step 2: If any of the above behaviors are NOT tested, write a characterization test**

Add tests to `tests/test_bridge.py` that exercise the specific behaviors. Use mocking since the Bridge imports `amplifier-foundation` and `amplifier-core` (which may not be available in the test environment).

**Step 3: Run the tests**

Run: `uv run python -m pytest tests/test_bridge.py tests/test_bridge_resume.py -v`
Expected: All pass.

**Step 4: Commit**
```
git add -A && git commit -m "test: add characterization tests for Bridge before refactor"
```

---

### Task 4.2: Extract `_prepare_session()` from Bridge

**Files:**
- Modify: `src/amplifier_distro/bridge.py`

**Step 1: Identify the duplicated code**

Comparing `create_session` (lines 360-493) and `resume_session` (lines 495-722):

**Shared steps (the ~60% that's duplicated):**
1. Load foundation imports (`_require_foundation()`)
2. Resolve bundle (`_resolve_distro_bundle()`)
3. Load and prepare bundle (`load_bundle()` + `prepare()`)
4. Inject providers (`_inject_providers()`)
5. Create protocol adapters (BridgeApprovalSystem, BridgeDisplaySystem, BridgeStreamingHook)
6. Register streaming hooks (ALL_EVENTS loop)
7. Register transcript persistence hooks
8. Build and return SessionHandle

**Unique to create_session:**
- Load distro config (for preflight)
- Run preflight checks
- Look up handoff from previous session
- Inject handoff as context
- Write session-info.json
- `create_session` passes `session_cwd=config.working_dir`

**Unique to resume_session:**
- Find session directory by ID
- Read session-info.json for working_dir recovery
- Pass `session_id` and `is_resumed=True` to `prepared.create_session()`
- Load and clean transcript (orphan stripping)
- Inject transcript as context via `set_messages()`

**Step 2: Define _prepare_session signature**

```python
@dataclass
class _PreparedSession:
    """Intermediate result from _prepare_session."""
    session: Any  # AmplifierSession
    session_dir: Path
    bundle_ref: str

async def _prepare_session(
    self,
    config: BridgeConfig,
    *,
    session_id: str | None = None,
    is_resumed: bool = False,
    session_cwd: Path | None = None,
) -> _PreparedSession:
```

**Step 3: Implement _prepare_session**

Move the shared steps into `_prepare_session()`. The method should:

1. Import foundation (`_require_foundation()`)
2. Resolve bundle (`_resolve_distro_bundle(config.bundle_name)`)
3. Load and prepare bundle
4. Inject providers
5. Create protocol adapters
6. Call `prepared.create_session()` with the appropriate kwargs:
   - If `session_id` and `is_resumed`: pass them through
   - Always pass `session_cwd`, `approval_system`, `display_system`
7. Register streaming hooks
8. Register transcript persistence hooks
9. Return `_PreparedSession`

**Step 4: Rewrite create_session to use _prepare_session**

```python
async def create_session(self, config: BridgeConfig | None = None) -> SessionHandle:
    if config is None:
        config = BridgeConfig()

    # 1. Preflight (unique to create)
    distro = self._load_distro_config()
    if config.run_preflight and distro.get("preflight", {}).get("enabled", True):
        from amplifier_distro.preflight import run_preflight
        report = run_preflight()
        if not report.passed and distro.get("preflight", {}).get("mode") == "block":
            failures = [c.message for c in report.checks if not c.passed]
            raise RuntimeError(f"Preflight failed: {'; '.join(failures)}")

    # 2. Handoff injection (unique to create)
    project_id = self.get_project_id(config.working_dir)
    handoff = await self.get_handoff(project_id)
    inject = list(config.inject_context or [])
    if handoff:
        inject.append(f"Previous session context:\n{handoff.summary}")

    # 3. Shared preparation
    prepared = await self._prepare_session(config, session_cwd=config.working_dir)

    # 4. Inject context (unique to create)
    if inject:
        # ... existing context injection code ...

    # 5. Write session-info.json (unique to create)
    _write_session_info(prepared.session_dir, config.working_dir)

    return SessionHandle(
        session_id=prepared.session.coordinator.session_id,
        project_id=project_id,
        working_dir=config.working_dir,
        _session=prepared.session,
        _session_dir=prepared.session_dir,
    )
```

**Step 5: Rewrite resume_session to use _prepare_session**

```python
async def resume_session(self, session_id: str, config: BridgeConfig | None = None) -> SessionHandle:
    if config is None:
        config = BridgeConfig()

    # 1. Find session directory (unique to resume)
    project_id, session_dir = self._find_session(session_id)

    # 2. Recover working_dir (unique to resume)
    persisted_cwd = _read_session_info_working_dir(session_dir)
    effective_cwd = persisted_cwd if persisted_cwd is not None else config.working_dir
    if persisted_cwd is None:
        _write_session_info(session_dir, effective_cwd)

    # 3. Shared preparation (with resume flags)
    prepared = await self._prepare_session(
        config,
        session_id=session_id,
        is_resumed=True,
        session_cwd=effective_cwd,
    )

    # 4. Load and inject transcript (unique to resume)
    # ... existing transcript loading code (lines 642-702) ...

    return SessionHandle(
        session_id=prepared.session.coordinator.session_id,
        project_id=project_id,
        working_dir=effective_cwd,
        _session=prepared.session,
        _session_dir=session_dir,
    )
```

**Step 6: Extract _find_session helper**

The session directory search logic (lines 509-546) is resume-specific but long. Extract it as:

```python
def _find_session(self, session_id: str) -> tuple[str, Path]:
    """Find session directory by ID or prefix. Returns (project_id, session_dir)."""
    # ... existing search logic ...
```

**Step 7: Run bridge tests**

Run: `uv run python -m pytest tests/test_bridge.py tests/test_bridge_resume.py -v`
Expected: All pass.

**Step 8: Run full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass.

**Step 9: Commit**
```
git add -A && git commit -m "refactor: extract _prepare_session() from Bridge (eliminate create/resume duplication)"
```

---

### Task 4.3: Clean up SessionHandle

**Files:**
- Modify: `src/amplifier_distro/bridge.py` (SessionHandle class, lines 169-209)

**Step 1: Evaluate SessionHandle's coordinator reach-through**

`SessionHandle` has two methods that reach through to `coordinator`:
- `set_approval_system()` (line 200-203): directly sets `self._session.coordinator.approval_system`
- `get_mounted()` (line 205-209): calls `self._session.coordinator.get_mounted()`

These are convenience methods used by server apps. Check if they're used:

```bash
grep -rn "set_approval_system\|get_mounted" src/amplifier_distro/ tests/ --include="*.py" | grep -v __pycache__
```

**Step 2: If used, keep them. If not, remove them.**

If they're only used in tests or not at all, remove them to shrink the API surface. If they're used by server apps, keep them but add a TODO comment noting they should be removed when the Bridge protocol is simplified.

**Step 3: Run tests and commit**

Run: `uv run python -m pytest tests/ -q`

```
git add -A && git commit -m "refactor: clean up SessionHandle API surface"
```

---

## Phase 5: Add `amplifier-start` Include + Clean Bundle Composer

### Task 5.1: Add `amplifier-start` as an include in generated bundles

**Files:**
- Modify: `src/amplifier_distro/bundle_composer.py` (the `generate()` function, lines 30-51)
- Modify: `tests/test_bundle_composer.py`

**Step 1: Read bundle_composer.py and its tests**

The `generate()` function (lines 30-51) builds a list of includes:
```python
includes: list[dict[str, str]] = [
    {"bundle": FOUNDATION_INCLUDE},
    {"bundle": provider.include},
]
for fid in feature_ids or []:
    feature = FEATURES[fid]
    includes.extend({"bundle": inc} for inc in feature.includes)
```

**Step 2: Add the amplifier-start include**

Add a constant at the top of `bundle_composer.py`:
```python
AMPLIFIER_START_INCLUDE = "git+https://github.com/payneio/amplifier-start@main"
```

In `generate()`, add it after foundation but before features:
```python
includes: list[dict[str, str]] = [
    {"bundle": FOUNDATION_INCLUDE},
    {"bundle": AMPLIFIER_START_INCLUDE},
    {"bundle": provider.include},
]
```

**Step 3: Write a test**

In `tests/test_bundle_composer.py`, add a test:
```python
def test_generate_includes_amplifier_start():
    """Generated bundles should include amplifier-start."""
    yaml_str = bundle_composer.generate("anthropic")
    data = yaml.safe_load(yaml_str)
    includes = [
        entry["bundle"] if isinstance(entry, dict) else entry
        for entry in data.get("includes", [])
    ]
    assert any("amplifier-start" in inc for inc in includes)
```

**Step 4: Run the test to verify it fails**

Run: `uv run python -m pytest tests/test_bundle_composer.py::test_generate_includes_amplifier_start -v`
Expected: FAIL (amplifier-start not in includes yet).

**Step 5: Apply the code change from Step 2**

**Step 6: Run the test to verify it passes**

Run: `uv run python -m pytest tests/test_bundle_composer.py -v`
Expected: All pass including the new test.

**Step 7: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass. Note: some existing tests may assert on the exact number of includes or their order -- fix those to account for the new amplifier-start include.

**Step 8: Commit**
```
git add -A && git commit -m "feat: include amplifier-start in all generated bundles"
```

---

### Task 5.2: Evaluate features.py after schema slim

**Files:**
- Read: `src/amplifier_distro/features.py` (237 lines)
- Possibly modify: `src/amplifier_distro/features.py`

**Step 1: Check what still uses features.py**

Run:
```bash
grep -rn "from.*features import\|import.*features" src/amplifier_distro/ --include="*.py" | grep -v __pycache__
```

Expected consumers:
- `bundle_composer.py` -- uses `FEATURES`, `PROVIDERS`, `TIERS`, `features_for_tier`
- `bridge.py` -- uses `PROVIDERS`, `resolve_provider`
- `server/apps/settings/` -- uses `FEATURES`, `PROVIDERS`, `detect_provider`
- `server/apps/install_wizard/` -- uses `PROVIDERS`, `detect_provider`

**Step 2: Decide what to keep**

`features.py` is still actively used by the bundle composer (which builds bundles from feature selections) and the install wizard. It stays. But evaluate if the `TIERS` system is still needed -- if tiers are only used by `bundle_composer.py`'s `set_tier()` and `get_current_tier()`, and those are only used by the install wizard, then they're still useful.

**Step 3: If no changes needed, skip this task**

If `features.py` is still fully used, no changes needed. Move on.

**Step 4: If simplification is possible, make it**

If any functions or classes are unused after the schema slim, remove them. Run tests after each removal.

**Step 5: Commit if changes were made**
```
git add -A && git commit -m "refactor: simplify features.py after schema slim"
```

---

## Phase 6: Clean Server Boundary

Define a public API surface and funnel all server imports through it.

### Task 6.1: Define the public API surface in `__init__.py`

**Files:**
- Modify: `src/amplifier_distro/__init__.py`

**Step 1: Catalog what the server actually imports from core**

Based on the grep results, the server imports from these core modules:

| Core Module | What's Imported | Server Files Using It |
|-------------|----------------|----------------------|
| `config` | `load_config`, `save_config`, `config_path` | `app.py`, `cli.py`, `install_wizard`, `voice` |
| `schema` | `DistroConfig`, `IdentityConfig` | `cli.py` |
| `conventions` | Many constants | `cli.py`, `memory.py`, `daemon.py`, `watchdog.py`, `startup.py`, `slack/`, `web_chat/`, `settings/`, `install_wizard/` |
| `preflight` | `run_preflight` | `app.py`, `startup.py` |
| `bridge` | `LocalBridge`, `BridgeConfig` | `session_backend.py` |
| `features` | `FEATURES`, `PROVIDERS`, `detect_provider` | `install_wizard`, `settings` |
| `bundle_composer` | module-level | `install_wizard`, `settings` |
| `fileutil` | `atomic_write` | `memory.py`, `slack/sessions.py`, `web_chat/session_store.py` |
| `docs_config` | `DOC_POINTERS`, `get_docs_for_category` | `settings` |
| `backup` | `run_auto_backup` | `cli.py` |
| `tailscale` | module-level | `cli.py` |

**Step 2: Define the public API**

In `src/amplifier_distro/__init__.py`, export the modules that the server is allowed to use:

```python
"""Amplifier Distro - An opinionated Amplifier distribution.

Public API Surface
------------------
These are the modules and symbols that external consumers (the server,
apps, tests) are allowed to import. Internal modules should not be
imported directly by code outside this package.
"""

__version__ = "0.1.0"

# --- Public API ---
# Configuration
from amplifier_distro.config import config_path, load_config, save_config
from amplifier_distro.schema import DistroConfig

# Conventions (immutable constants)
from amplifier_distro import conventions

# Bridge (session lifecycle)
from amplifier_distro.bridge import (
    BridgeConfig,
    LocalBridge,
    SessionHandle,
)

# Features and bundle composition
from amplifier_distro import bundle_composer
from amplifier_distro.features import (
    FEATURES,
    PROVIDERS,
    detect_provider,
    resolve_provider,
)

# Diagnostics
from amplifier_distro.preflight import PreflightReport, run_preflight
from amplifier_distro.doctor import DoctorReport, run_diagnostics, run_fixes

# Utilities
from amplifier_distro.fileutil import atomic_write

__all__ = [
    "__version__",
    # Config
    "config_path",
    "load_config",
    "save_config",
    "DistroConfig",
    # Conventions
    "conventions",
    # Bridge
    "BridgeConfig",
    "LocalBridge",
    "SessionHandle",
    # Features
    "bundle_composer",
    "FEATURES",
    "PROVIDERS",
    "detect_provider",
    "resolve_provider",
    # Diagnostics
    "PreflightReport",
    "run_preflight",
    "DoctorReport",
    "run_diagnostics",
    "run_fixes",
    # Utilities
    "atomic_write",
]
```

**Step 3: Run the full test suite (don't change imports yet)**

Adding exports to `__init__.py` should not break anything.

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass.

**Step 4: Commit**
```
git add -A && git commit -m "refactor: define public API surface in __init__.py"
```

---

### Task 6.2: Migrate server/app.py imports to public API

**Files:**
- Modify: `src/amplifier_distro/server/app.py`

`server/app.py` has the most imports from core (17 import lines). Most are lazy (inside functions), which is fine -- but they should go through the public API.

**Step 1: List all core imports in app.py**

From the grep results, app.py imports:
- `from amplifier_distro.config import load_config` (lines 48, 233, 284)
- `from amplifier_distro.config import save_config` (line 284)
- `from amplifier_distro.preflight import run_preflight` (line 246)
- `from amplifier_distro.conventions import ...` (line 322)
- `from amplifier_distro.server.*` (various -- these are fine, they're within the server package)

**Step 2: Change core imports to use the public API**

Replace:
```python
from amplifier_distro.config import load_config
```
With:
```python
from amplifier_distro import load_config
```

Replace:
```python
from amplifier_distro.config import load_config, save_config
```
With:
```python
from amplifier_distro import load_config, save_config
```

Replace:
```python
from amplifier_distro.preflight import run_preflight
```
With:
```python
from amplifier_distro import run_preflight
```

Leave `from amplifier_distro.conventions import ...` as-is -- `conventions` is already a public module.

Leave `from amplifier_distro.server.*` imports as-is -- those are intra-server imports.

**Step 3: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass.

**Step 4: Commit**
```
git add -A && git commit -m "refactor: migrate server/app.py to use distro public API"
```

---

### Task 6.3: Migrate server/cli.py imports to public API

**Files:**
- Modify: `src/amplifier_distro/server/cli.py`

**Step 1: List all core imports in server/cli.py**

From the grep results:
- `from amplifier_distro import conventions` (line 22) -- already fine
- `from amplifier_distro.config import config_path, load_config` (line 429)
- `from amplifier_distro.config import save_config` (line 531)
- `from amplifier_distro.schema import DistroConfig, IdentityConfig` (line 532) -- `IdentityConfig` may be gone after Phase 2
- `from amplifier_distro.backup import run_auto_backup` (line 496) -- not in public API yet
- `from amplifier_distro import tailscale` (line 519) -- not in public API, may need to be added or left as a direct import with a TODO

**Step 2: Change imports to use the public API where possible**

Replace direct `config`, `schema`, `preflight` imports with `from amplifier_distro import ...`.

For `backup` and `tailscale`: these are used only by `server/cli.py`. Add them to the public API if they're part of the server's legitimate needs, or leave them as direct imports with a TODO comment noting they should move when the server is extracted.

**Step 3: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass.

**Step 4: Commit**
```
git add -A && git commit -m "refactor: migrate server/cli.py to use distro public API"
```

---

### Task 6.4: Migrate server/session_backend.py imports to public API

**Files:**
- Modify: `src/amplifier_distro/server/session_backend.py`

**Step 1: Change imports**

Replace:
```python
from amplifier_distro.bridge import LocalBridge  # line 187
from amplifier_distro.bridge import BridgeConfig  # line 207
```
With:
```python
from amplifier_distro import LocalBridge  # line 187
from amplifier_distro import BridgeConfig  # line 207
```

**Step 2: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass.

**Step 3: Commit**
```
git add -A && git commit -m "refactor: migrate server/session_backend.py to use distro public API"
```

---

### Task 6.5: Migrate remaining server files to public API

**Files:**
- Modify: `src/amplifier_distro/server/memory.py`
- Modify: `src/amplifier_distro/server/startup.py`
- Modify: `src/amplifier_distro/server/apps/install_wizard/__init__.py`
- Modify: `src/amplifier_distro/server/apps/settings/__init__.py`
- Modify: `src/amplifier_distro/server/apps/slack/sessions.py`
- Modify: `src/amplifier_distro/server/apps/slack/config.py`
- Modify: `src/amplifier_distro/server/apps/slack/setup.py`
- Modify: `src/amplifier_distro/server/apps/slack/backend.py`
- Modify: `src/amplifier_distro/server/apps/web_chat/__init__.py`
- Modify: `src/amplifier_distro/server/apps/web_chat/session_store.py`
- Modify: `src/amplifier_distro/server/apps/voice/__init__.py`

This is mechanical work. For each file:

**Step 1: Replace `from amplifier_distro.X import Y` with `from amplifier_distro import Y`** where Y is in the public API.

Common replacements:
- `from amplifier_distro.conventions import X` -> `from amplifier_distro.conventions import X` (already fine -- conventions is a public module)
- `from amplifier_distro.fileutil import atomic_write` -> `from amplifier_distro import atomic_write`
- `from amplifier_distro.features import PROVIDERS, detect_provider` -> `from amplifier_distro import PROVIDERS, detect_provider`
- `from amplifier_distro import bundle_composer` -> already fine
- `from amplifier_distro.config import load_config, save_config` -> `from amplifier_distro import load_config, save_config`
- `from amplifier_distro.docs_config import ...` -> add to public API or leave with TODO

**Step 2: Run the full test suite after every 3 files changed**

Run: `uv run python -m pytest tests/ -q`
Expected: All previously-passing tests still pass.

**Step 3: Commit**
```
git add -A && git commit -m "refactor: migrate all server app imports to use distro public API"
```

---

### Task 6.6: Final validation

**Step 1: Verify all server imports go through the public API**

Run:
```bash
grep -rn "from amplifier_distro\." src/amplifier_distro/server/ --include="*.py" | grep -v __pycache__ | grep -v "from amplifier_distro\.server\." | grep -v "from amplifier_distro\.conventions" | grep -v "from amplifier_distro import"
```

Expected: The only remaining direct imports should be:
- `from amplifier_distro.server.*` (intra-server imports -- fine)
- `from amplifier_distro.conventions import *` (public module -- fine)
- Any that were intentionally left with TODOs (backup, tailscale, docs_config)

**Step 2: Run the full test suite one final time**

Run: `uv run python -m pytest tests/ -q`
Expected: All 1,154 previously-passing tests still pass (the 4 pre-existing failures remain).

**Step 3: Verify line count reduction**

Run:
```bash
find src/amplifier_distro -name "*.py" | xargs wc -l | tail -1
```

Expected: Significant reduction from the original ~15,765 lines (core 6,084 + server 9,681). The dead weight deletions alone remove ~1,290 source lines.

**Step 4: Commit**
```
git add -A && git commit -m "refactor: final validation -- all server imports through public API"
```

---

## Summary

| Phase | Tasks | Key Changes |
|-------|-------|-------------|
| 1. Delete Dead Weight | 5 tasks | Remove deploy.py, provider_api.py, update_check.py, migrate.py, clean conventions.py |
| 2. Slim Schema | 5 tasks | Remove kepler, workspace_root, identity, bundle, cache, memory from DistroConfig |
| 3. Slim Diagnostics | 2 tasks | Remove CLI-duplicated checks from preflight.py and doctor.py |
| 4. Refactor Bridge | 3 tasks | Extract _prepare_session(), clean SessionHandle |
| 5. Bundle Composer | 2 tasks | Add amplifier-start include, evaluate features.py |
| 6. Server Boundary | 6 tasks | Define public API, migrate all server imports |
| **Total** | **23 tasks** | |

**Success Criteria:**
- [ ] All 1,154 pre-existing passing tests still pass
- [ ] No new test failures introduced
- [ ] `distro.yaml` schema contains only: interfaces, server, backup, preflight, slack, voice, watchdog
- [ ] Bridge `create_session` and `resume_session` share a `_prepare_session()` method
- [ ] `bundle_composer.py` includes `amplifier-start` in generated bundles
- [ ] All server imports go through the public API surface
- [ ] Dead modules deleted: deploy.py, migrate.py, update_check.py, provider_api.py
- [ ] Preflight/doctor contain only distro-specific checks