# Slack Session Working Directory Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Fix Issue #34 — make `SlackConfig.from_env()` actually read `default_working_dir` from distro.yaml, track `working_dir` on each `SessionMapping`, allow callers to override the working directory when creating sessions, and show users where their session landed.

**Architecture:** Four incremental changes across the Slack bridge layer. Task 1 wires the dead `default_working_dir` config field so it's actually populated from `distro.yaml` / env vars. Task 2 adds a `working_dir` field to `SessionMapping` and updates the manual `_save_sessions()` / `_load_sessions()` serialization methods (they enumerate fields by hand — adding a dataclass field alone is NOT sufficient). Task 3 adds an optional `working_dir` parameter to `SlackSessionManager.create_session()` so callers can override the config default. Task 4 modifies the `cmd_new` response to show the working directory and hint when the session lands in `~`. The resume path is already handled by `session-info.json` (PR #56) — this plan does not touch it.

**Tech Stack:** Python 3.11+, pytest, `SlackConfig` dataclass, `SessionMapping` dataclass, `MockBackend` for tests.

---

## Pre-flight

Before starting, create the feature branch:

```bash
cd /home/work/repo/amplifier-distro
git checkout main
git pull origin main
git checkout -b fix/34-slack-session-working-dir
```

Verify existing tests pass:

```bash
cd /home/work/repo/amplifier-distro
uv run python -m pytest tests/test_slack_bridge.py -v --tb=short
```

Expected: All tests pass (currently ~70+ tests in this file).

---

## Task 1: Wire `SlackConfig.from_env()` to read `default_working_dir`

The `default_working_dir` field exists on `SlackConfig` (line 115 of `config.py`) with a default of `"~"`, but `from_env()` (lines 127-149) never reads it from distro.yaml or env vars. A user who sets `slack.default_working_dir: ~/repo/my-project` in distro.yaml gets it silently ignored.

**Files:**
- Modify: `src/amplifier_distro/server/apps/slack/config.py:127-149`
- Test: `tests/test_slack_bridge.py`

### Step 1: Write failing tests

Add these tests to the `TestSlackConfigFile` class in `tests/test_slack_bridge.py` (after the `test_env_overrides_file` test at line 990):

```python
    def test_from_env_reads_default_working_dir(self, tmp_path):
        """default_working_dir is read from distro.yaml slack section."""
        from amplifier_distro.server.apps.slack import config as config_mod

        distro_file = tmp_path / "distro.yaml"
        distro_file.write_text(
            "slack:\n"
            "  default_working_dir: ~/repo/my-project\n"
        )

        original = config_mod._amplifier_home
        config_mod._amplifier_home = lambda: tmp_path
        try:
            env = {"SLACK_DEFAULT_WORKING_DIR": ""}
            with patch.dict(os.environ, env, clear=False):
                cfg = config_mod.SlackConfig.from_env()
                assert cfg.default_working_dir == "~/repo/my-project"
        finally:
            config_mod._amplifier_home = original

    def test_from_env_default_working_dir_env_override(self, tmp_path):
        """SLACK_DEFAULT_WORKING_DIR env var overrides distro.yaml."""
        from amplifier_distro.server.apps.slack import config as config_mod

        distro_file = tmp_path / "distro.yaml"
        distro_file.write_text(
            "slack:\n"
            "  default_working_dir: ~/repo/from-file\n"
        )

        original = config_mod._amplifier_home
        config_mod._amplifier_home = lambda: tmp_path
        try:
            env = {"SLACK_DEFAULT_WORKING_DIR": "/custom/from-env"}
            with patch.dict(os.environ, env, clear=False):
                cfg = config_mod.SlackConfig.from_env()
                assert cfg.default_working_dir == "/custom/from-env"
        finally:
            config_mod._amplifier_home = original

    def test_from_env_default_working_dir_defaults_to_tilde(self, tmp_path):
        """default_working_dir falls back to '~' when not configured."""
        from amplifier_distro.server.apps.slack import config as config_mod

        original = config_mod._amplifier_home
        config_mod._amplifier_home = lambda: tmp_path
        try:
            env = {"SLACK_DEFAULT_WORKING_DIR": ""}
            with patch.dict(os.environ, env, clear=False):
                cfg = config_mod.SlackConfig.from_env()
                assert cfg.default_working_dir == "~"
        finally:
            config_mod._amplifier_home = original
```

### Step 2: Run tests to verify they fail

```bash
cd /home/work/repo/amplifier-distro
uv run python -m pytest tests/test_slack_bridge.py::TestSlackConfigFile::test_from_env_reads_default_working_dir tests/test_slack_bridge.py::TestSlackConfigFile::test_from_env_default_working_dir_env_override tests/test_slack_bridge.py::TestSlackConfigFile::test_from_env_default_working_dir_defaults_to_tilde -v
```

Expected: `test_from_env_reads_default_working_dir` FAILS with `assert '~' == '~/repo/my-project'`. The env override test FAILS similarly. The defaults-to-tilde test may PASS (it's the current behavior).

### Step 3: Implement the fix

In `src/amplifier_distro/server/apps/slack/config.py`, modify the `from_env()` method. The current code (lines 135-149) is:

```python
        return cls(
            bot_token=_str("SLACK_BOT_TOKEN", keys, cfg, "bot_token"),
            app_token=_str("SLACK_APP_TOKEN", keys, cfg, "app_token"),
            signing_secret=_str("SLACK_SIGNING_SECRET", keys, cfg, "signing_secret"),
            hub_channel_id=_str("SLACK_HUB_CHANNEL_ID", {}, cfg, "hub_channel_id"),
            hub_channel_name=_str(
                "SLACK_HUB_CHANNEL_NAME",
                {},
                cfg,
                "hub_channel_name",
                "amplifier",
            ),
            simulator_mode=_bool("SLACK_SIMULATOR_MODE", cfg, "simulator_mode"),
            socket_mode=_bool("SLACK_SOCKET_MODE", cfg, "socket_mode"),
        )
```

Change it to:

```python
        config = cls(
            bot_token=_str("SLACK_BOT_TOKEN", keys, cfg, "bot_token"),
            app_token=_str("SLACK_APP_TOKEN", keys, cfg, "app_token"),
            signing_secret=_str("SLACK_SIGNING_SECRET", keys, cfg, "signing_secret"),
            hub_channel_id=_str("SLACK_HUB_CHANNEL_ID", {}, cfg, "hub_channel_id"),
            hub_channel_name=_str(
                "SLACK_HUB_CHANNEL_NAME",
                {},
                cfg,
                "hub_channel_name",
                "amplifier",
            ),
            default_working_dir=_str(
                "SLACK_DEFAULT_WORKING_DIR",
                {},
                cfg,
                "default_working_dir",
                "~",
            ),
            simulator_mode=_bool("SLACK_SIMULATOR_MODE", cfg, "simulator_mode"),
            socket_mode=_bool("SLACK_SOCKET_MODE", cfg, "socket_mode"),
        )
        logger.debug(
            "SlackConfig.from_env: default_working_dir=%s",
            config.default_working_dir,
        )
        return config
```

This follows the exact same pattern as `hub_channel_name` — uses `_str()` with an empty keys dict (not a secret), reads from the `cfg` dict using key `"default_working_dir"`, and defaults to `"~"`.

### Step 4: Run tests to verify they pass

```bash
cd /home/work/repo/amplifier-distro
uv run python -m pytest tests/test_slack_bridge.py::TestSlackConfigFile -v
```

Expected: All `TestSlackConfigFile` tests PASS, including the three new ones.

### Step 5: Run full test suite to check for regressions

```bash
cd /home/work/repo/amplifier-distro
uv run python -m pytest tests/test_slack_bridge.py -v --tb=short
```

Expected: All tests PASS.

### Step 6: Commit

```bash
cd /home/work/repo/amplifier-distro
git add src/amplifier_distro/server/apps/slack/config.py tests/test_slack_bridge.py
git commit -m "fix(slack): wire default_working_dir in SlackConfig.from_env()

The default_working_dir field existed on SlackConfig but from_env()
never read it from distro.yaml or env vars. Now reads from:
- SLACK_DEFAULT_WORKING_DIR env var (highest priority)
- slack.default_working_dir in distro.yaml
- Falls back to '~' (existing default)

Part of #34"
```

---

## Task 2: Add `working_dir` to `SessionMapping` and fix persistence

The backend already returns `info.working_dir` after creating a session (via `SessionInfo.working_dir`), but `SlackSessionManager.create_session()` discards it — it never stores it on the `SessionMapping`. This task adds the field and wires persistence.

**CRITICAL:** The `_save_sessions()` method (lines 108-119 of `sessions.py`) builds a dict literal with explicit field names. The `_load_sessions()` method (lines 83-93) constructs `SessionMapping` with explicit `.get()` calls. Adding a field to the dataclass without updating BOTH methods means the field is silently lost on restart.

**Files:**
- Modify: `src/amplifier_distro/server/apps/slack/models.py:66-89`
- Modify: `src/amplifier_distro/server/apps/slack/sessions.py:76-127,166-268`
- Test: `tests/test_slack_bridge.py`

### Step 1: Write failing tests

Add these tests to `tests/test_slack_bridge.py`. First, add a new test to the `TestSlackModels` class (after `test_session_mapping_defaults` at line 133):

```python
    def test_session_mapping_has_working_dir(self):
        """SessionMapping has a working_dir field that defaults to empty string."""
        from amplifier_distro.server.apps.slack.models import SessionMapping

        m = SessionMapping(session_id="s1", channel_id="C1", working_dir="~/repo/foo")
        assert m.working_dir == "~/repo/foo"

        m_default = SessionMapping(session_id="s2", channel_id="C2")
        assert m_default.working_dir == ""
```

Next, add these tests to the `TestSessionPersistence` class (after `test_persistence_handles_corrupt_file` at line 1621):

```python
    def test_save_load_round_trips_working_dir(
        self, slack_client, mock_backend, slack_config, tmp_path
    ):
        """working_dir survives save/load round trip."""
        from amplifier_distro.server.apps.slack.sessions import SlackSessionManager

        persist_path = tmp_path / "slack-sessions.json"
        mgr1 = SlackSessionManager(
            slack_client, mock_backend, slack_config, persistence_path=persist_path
        )
        asyncio.run(
            mgr1.create_session("C1", "t1", "U1", "wd test")
        )

        # Verify the JSON file contains working_dir
        data = json.loads(persist_path.read_text())
        assert "working_dir" in data[0], "working_dir must be in persisted JSON"

        # Load into a new manager and verify
        mgr2 = SlackSessionManager(
            slack_client, mock_backend, slack_config, persistence_path=persist_path
        )
        loaded = mgr2.get_mapping("C1", "t1")
        assert loaded is not None
        assert loaded.working_dir != "", "working_dir must survive round trip"

    def test_load_sessions_backward_compat_no_working_dir(
        self, slack_client, mock_backend, slack_config, tmp_path
    ):
        """Old JSON files without working_dir load without error."""
        from amplifier_distro.server.apps.slack.sessions import SlackSessionManager

        persist_path = tmp_path / "slack-sessions.json"
        # Write an old-format JSON without working_dir
        old_data = [
            {
                "session_id": "old-session-001",
                "channel_id": "C1",
                "thread_ts": "t1",
                "project_id": "proj",
                "description": "old session",
                "created_by": "U1",
                "created_at": "2026-01-01T00:00:00",
                "last_active": "2026-01-01T00:00:00",
                "is_active": True,
            }
        ]
        persist_path.write_text(json.dumps(old_data))

        # Must load without error
        mgr = SlackSessionManager(
            slack_client, mock_backend, slack_config, persistence_path=persist_path
        )
        loaded = mgr.get_mapping("C1", "t1")
        assert loaded is not None
        assert loaded.working_dir == ""  # Default for missing field

    def test_save_sessions_includes_all_dataclass_fields(
        self, slack_client, mock_backend, slack_config, tmp_path
    ):
        """_save_sessions output includes every SessionMapping dataclass field.

        This prevents future fields from being silently dropped by the manual
        serialization in _save_sessions().
        """
        from dataclasses import fields

        from amplifier_distro.server.apps.slack.models import SessionMapping
        from amplifier_distro.server.apps.slack.sessions import SlackSessionManager

        persist_path = tmp_path / "slack-sessions.json"
        mgr = SlackSessionManager(
            slack_client, mock_backend, slack_config, persistence_path=persist_path
        )
        asyncio.run(mgr.create_session("C1", "t1", "U1", "field check"))

        data = json.loads(persist_path.read_text())
        record = data[0]

        # Every dataclass field (except computed properties) must be in JSON
        dataclass_field_names = {f.name for f in fields(SessionMapping)}
        json_keys = set(record.keys())
        missing = dataclass_field_names - json_keys
        assert not missing, (
            f"_save_sessions() is missing fields: {missing}. "
            "Add them to the dict literal in _save_sessions()."
        )
```

Then add these tests to the `TestSlackSessionManager` class (after `test_get_mapping_thread_does_not_fall_back_to_bare_channel` at line 635):

```python
    def test_create_session_stores_working_dir_on_mapping(self, session_manager):
        """create_session populates working_dir from backend's SessionInfo."""
        mapping = asyncio.run(
            session_manager.create_session("C_HUB", "thread.1", "U1", "wd test")
        )
        # MockBackend.create_session returns info.working_dir = the working_dir
        # it was called with. SlackConfig defaults to "~".
        assert mapping.working_dir != "", "working_dir must be populated"

    def test_connect_session_stores_working_dir_on_mapping(
        self, session_manager, mock_backend
    ):
        """connect_session populates working_dir from backend's SessionInfo."""
        mapping = asyncio.run(
            session_manager.connect_session(
                "C_HUB", "thread.2", "U1",
                working_dir="~/repo/specific-project",
                description="connect wd test",
            )
        )
        assert mapping.working_dir == "~/repo/specific-project"
```

### Step 2: Run tests to verify they fail

```bash
cd /home/work/repo/amplifier-distro
uv run python -m pytest tests/test_slack_bridge.py::TestSlackModels::test_session_mapping_has_working_dir tests/test_slack_bridge.py::TestSessionPersistence::test_save_load_round_trips_working_dir tests/test_slack_bridge.py::TestSessionPersistence::test_load_sessions_backward_compat_no_working_dir tests/test_slack_bridge.py::TestSessionPersistence::test_save_sessions_includes_all_dataclass_fields tests/test_slack_bridge.py::TestSlackSessionManager::test_create_session_stores_working_dir_on_mapping tests/test_slack_bridge.py::TestSlackSessionManager::test_connect_session_stores_working_dir_on_mapping -v
```

Expected: Multiple failures — `SessionMapping` has no `working_dir` field, persistence tests fail because the field isn't in the JSON, and `test_save_sessions_includes_all_dataclass_fields` fails because `_save_sessions` doesn't include it.

### Step 3: Add `working_dir` field to `SessionMapping`

In `src/amplifier_distro/server/apps/slack/models.py`, add the `working_dir` field to the `SessionMapping` dataclass. Add it after `is_active` (line 82):

```python
    is_active: bool = True
    working_dir: str = ""  # Where this session operates (e.g., "~/repo/foo")
```

### Step 4: Update `_save_sessions()` in sessions.py

In `src/amplifier_distro/server/apps/slack/sessions.py`, update the dict literal in `_save_sessions()` (lines 108-119). Add `"working_dir": m.working_dir` to the dict. The updated code:

```python
            data = [
                {
                    "session_id": m.session_id,
                    "channel_id": m.channel_id,
                    "thread_ts": m.thread_ts,
                    "project_id": m.project_id,
                    "description": m.description,
                    "created_by": m.created_by,
                    "created_at": m.created_at,
                    "last_active": m.last_active,
                    "is_active": m.is_active,
                    "working_dir": m.working_dir,
                }
                for m in self._mappings.values()
            ]
```

### Step 5: Update `_load_sessions()` in sessions.py

In `src/amplifier_distro/server/apps/slack/sessions.py`, add `working_dir` to the `SessionMapping` constructor in `_load_sessions()` (lines 83-93). Use `.get()` with a default for backward compatibility with old JSON files:

```python
                mapping = SessionMapping(
                    session_id=entry["session_id"],
                    channel_id=entry["channel_id"],
                    thread_ts=entry.get("thread_ts"),
                    project_id=entry.get("project_id", ""),
                    description=entry.get("description", ""),
                    created_by=entry.get("created_by", ""),
                    created_at=entry.get("created_at", ""),
                    last_active=entry.get("last_active", ""),
                    is_active=entry.get("is_active", True),
                    working_dir=entry.get("working_dir", ""),
                )
```

### Step 6: Populate `working_dir` in `create_session()`

In `src/amplifier_distro/server/apps/slack/sessions.py`, update the `SessionMapping` constructor in `create_session()` (lines 201-210) to include `working_dir` from the backend's response. `info.working_dir` is already populated by `MockBackend.create_session()` (it echoes back the `working_dir` it was called with — see `session_backend.py` line 104).

Change the mapping construction from:

```python
        mapping = SessionMapping(
            session_id=info.session_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            project_id=info.project_id,
            description=description,
            created_by=user_id,
            created_at=now,
            last_active=now,
        )
```

To:

```python
        mapping = SessionMapping(
            session_id=info.session_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            project_id=info.project_id,
            description=description,
            created_by=user_id,
            created_at=now,
            last_active=now,
            working_dir=info.working_dir,
        )
```

### Step 7: Populate `working_dir` in `connect_session()`

In `src/amplifier_distro/server/apps/slack/sessions.py`, update the `SessionMapping` constructor in `connect_session()` (lines 252-260) the same way.

Change the mapping construction from:

```python
        mapping = SessionMapping(
            session_id=info.session_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            project_id=info.project_id,
            description=description,
            created_by=user_id,
            created_at=now,
            last_active=now,
        )
```

To:

```python
        mapping = SessionMapping(
            session_id=info.session_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            project_id=info.project_id,
            description=description,
            created_by=user_id,
            created_at=now,
            last_active=now,
            working_dir=info.working_dir,
        )
```

### Step 8: Run tests to verify they pass

```bash
cd /home/work/repo/amplifier-distro
uv run python -m pytest tests/test_slack_bridge.py::TestSlackModels::test_session_mapping_has_working_dir tests/test_slack_bridge.py::TestSessionPersistence::test_save_load_round_trips_working_dir tests/test_slack_bridge.py::TestSessionPersistence::test_load_sessions_backward_compat_no_working_dir tests/test_slack_bridge.py::TestSessionPersistence::test_save_sessions_includes_all_dataclass_fields tests/test_slack_bridge.py::TestSlackSessionManager::test_create_session_stores_working_dir_on_mapping tests/test_slack_bridge.py::TestSlackSessionManager::test_connect_session_stores_working_dir_on_mapping -v
```

Expected: All 6 new tests PASS.

### Step 9: Run full test suite

```bash
cd /home/work/repo/amplifier-distro
uv run python -m pytest tests/test_slack_bridge.py -v --tb=short
```

Expected: All tests PASS (existing + new).

### Step 10: Commit

```bash
cd /home/work/repo/amplifier-distro
git add src/amplifier_distro/server/apps/slack/models.py src/amplifier_distro/server/apps/slack/sessions.py tests/test_slack_bridge.py
git commit -m "feat(slack): add working_dir to SessionMapping with persistence

Add working_dir field to SessionMapping dataclass and update the manual
_save_sessions()/_load_sessions() serialization (they enumerate fields
by hand). Populate from info.working_dir in both create_session() and
connect_session(). Old JSON files without the field load safely with
empty string default.

Also add test_save_sessions_includes_all_dataclass_fields to catch
future fields being silently dropped by manual serialization.

Part of #34"
```

---

## Task 3: Add optional `working_dir` param to `create_session()`

Today `SlackSessionManager.create_session()` hardcodes `working_dir=self._config.default_working_dir` (line 192). This task makes it configurable so a caller can pass a different directory. The actual command parsing (how users specify a project in Slack) is being designed in a separate session — this task just lays the plumbing.

NOTE: `connect_session()` (line 221) already takes a `working_dir` parameter. This task only changes `create_session()`.

**Files:**
- Modify: `src/amplifier_distro/server/apps/slack/sessions.py:166-214`
- Test: `tests/test_slack_bridge.py`

### Step 1: Write failing tests

Add these tests to the `TestSlackSessionManager` class in `tests/test_slack_bridge.py`:

```python
    def test_create_session_uses_explicit_working_dir(
        self, session_manager, mock_backend
    ):
        """create_session passes explicit working_dir to backend."""
        asyncio.run(
            session_manager.create_session(
                "C1", "t1", "U1", "explicit wd",
                working_dir="~/repo/explicit",
            )
        )
        # Check what working_dir the backend was called with
        create_call = [
            c for c in mock_backend.calls if c["method"] == "create_session"
        ][-1]
        assert create_call["working_dir"] == "~/repo/explicit"

    def test_create_session_falls_back_to_config_default(
        self, session_manager, mock_backend, slack_config
    ):
        """create_session uses config default when no working_dir specified."""
        slack_config.default_working_dir = "~/repo/configured"
        asyncio.run(
            session_manager.create_session("C1", "t1", "U1", "default wd")
        )
        create_call = [
            c for c in mock_backend.calls if c["method"] == "create_session"
        ][-1]
        assert create_call["working_dir"] == "~/repo/configured"

    def test_create_session_none_working_dir_uses_default(
        self, session_manager, mock_backend, slack_config
    ):
        """Explicitly passing working_dir=None falls back to config default."""
        slack_config.default_working_dir = "~/repo/fallback"
        asyncio.run(
            session_manager.create_session(
                "C1", "t1", "U1", "none wd",
                working_dir=None,
            )
        )
        create_call = [
            c for c in mock_backend.calls if c["method"] == "create_session"
        ][-1]
        assert create_call["working_dir"] == "~/repo/fallback"
```

### Step 2: Run tests to verify they fail

```bash
cd /home/work/repo/amplifier-distro
uv run python -m pytest tests/test_slack_bridge.py::TestSlackSessionManager::test_create_session_uses_explicit_working_dir tests/test_slack_bridge.py::TestSlackSessionManager::test_create_session_falls_back_to_config_default tests/test_slack_bridge.py::TestSlackSessionManager::test_create_session_none_working_dir_uses_default -v
```

Expected: `test_create_session_uses_explicit_working_dir` FAILS with `TypeError: create_session() got an unexpected keyword argument 'working_dir'`.

### Step 3: Add the `working_dir` parameter

In `src/amplifier_distro/server/apps/slack/sessions.py`, modify `create_session()`. Change the signature from:

```python
    async def create_session(
        self,
        channel_id: str,
        thread_ts: str | None,
        user_id: str,
        description: str = "",
    ) -> SessionMapping:
```

To:

```python
    async def create_session(
        self,
        channel_id: str,
        thread_ts: str | None,
        user_id: str,
        description: str = "",
        working_dir: str | None = None,
    ) -> SessionMapping:
```

Then, replace the backend call section (the comment and lines 191-195) with:

```python
        # Resolve working directory: explicit param > config default
        effective_dir = working_dir or self._config.default_working_dir
        logger.info(
            "Creating session with working_dir=%s (source: %s)",
            effective_dir,
            "explicit" if working_dir else "config default",
        )

        # Create the backend session
        info = await self._backend.create_session(
            working_dir=effective_dir,
            bundle_name=self._config.default_bundle,
            description=description,
        )
```

### Step 4: Run tests to verify they pass

```bash
cd /home/work/repo/amplifier-distro
uv run python -m pytest tests/test_slack_bridge.py::TestSlackSessionManager -v
```

Expected: All `TestSlackSessionManager` tests PASS, including the three new ones.

### Step 5: Run full test suite

```bash
cd /home/work/repo/amplifier-distro
uv run python -m pytest tests/test_slack_bridge.py -v --tb=short
```

Expected: All tests PASS. Existing callers of `create_session()` that don't pass `working_dir` keep the current behavior (config default).

### Step 6: Commit

```bash
cd /home/work/repo/amplifier-distro
git add src/amplifier_distro/server/apps/slack/sessions.py tests/test_slack_bridge.py
git commit -m "feat(slack): add optional working_dir param to create_session()

SlackSessionManager.create_session() now accepts an optional working_dir
parameter. When provided, it overrides the config default. When None or
omitted, falls back to self._config.default_working_dir. Adds info-level
logging showing the effective directory and its source.

This lays plumbing for future command parsing that lets users specify
a project directory. connect_session() already had this parameter.

Part of #34"
```

---

## Task 4: Show working directory in session start message

Users currently see `Started new session `a3f2b1c0`` with no indication of where the session is operating. This task adds the directory to the response and shows a helpful hint when the session lands in `~` (the unconfigured default).

**Files:**
- Modify: `src/amplifier_distro/server/apps/slack/commands.py:194-217`
- Test: `tests/test_slack_bridge.py`

### Step 1: Write failing tests

Add these tests to the `TestCommandHandler` class in `tests/test_slack_bridge.py`:

```python
    def test_cmd_new_shows_working_dir_in_response(
        self, command_handler, slack_config
    ):
        """cmd_new response includes the working directory."""
        from amplifier_distro.server.apps.slack.commands import CommandContext

        slack_config.default_working_dir = "~/repo/my-project"
        ctx = CommandContext(channel_id="C_HUB", user_id="U1", thread_ts=None)
        result = asyncio.run(command_handler.handle("new", ["test"], ctx))
        assert "~/repo/my-project" in result.text

    def test_cmd_new_shows_hint_when_in_home_dir(
        self, command_handler, slack_config
    ):
        """cmd_new shows a tip when working directory is ~ (unconfigured)."""
        from amplifier_distro.server.apps.slack.commands import CommandContext

        slack_config.default_working_dir = "~"
        ctx = CommandContext(channel_id="C_HUB", user_id="U1", thread_ts=None)
        result = asyncio.run(command_handler.handle("new", ["test"], ctx))
        assert "~" in result.text
        assert "default_working_dir" in result.text

    def test_cmd_new_no_hint_when_working_dir_set(
        self, command_handler, slack_config
    ):
        """cmd_new does NOT show hint when working directory is configured."""
        from amplifier_distro.server.apps.slack.commands import CommandContext

        slack_config.default_working_dir = "~/repo/configured"
        ctx = CommandContext(channel_id="C_HUB", user_id="U1", thread_ts=None)
        result = asyncio.run(command_handler.handle("new", ["test"], ctx))
        assert "default_working_dir" not in result.text
```

### Step 2: Run tests to verify they fail

```bash
cd /home/work/repo/amplifier-distro
uv run python -m pytest tests/test_slack_bridge.py::TestCommandHandler::test_cmd_new_shows_working_dir_in_response tests/test_slack_bridge.py::TestCommandHandler::test_cmd_new_shows_hint_when_in_home_dir tests/test_slack_bridge.py::TestCommandHandler::test_cmd_new_no_hint_when_working_dir_set -v
```

Expected: All three FAIL because the current response text doesn't include the working directory or any hint.

### Step 3: Update `cmd_new` to show working directory

In `src/amplifier_distro/server/apps/slack/commands.py`, update the `cmd_new` method (lines 194-217). Replace the response text construction (lines 208-212).

Change from:

```python
        short_id = mapping.session_id[:8]
        text = f"Started new session `{short_id}`"
        if description:
            text += f": {description}"
        text += "\nReply in this thread to interact with the session."
```

To:

```python
        short_id = mapping.session_id[:8]
        text = f"Started new session `{short_id}` in `{mapping.working_dir}`"
        if description:
            text += f"\n_{description}_"
        text += "\nReply in this thread to interact with the session."

        # Show a hint if the session landed in the home directory (unconfigured)
        if mapping.working_dir in ("~", "", "~/"):
            text += (
                "\n_Tip: set `slack.default_working_dir` in distro.yaml"
                " to default to your project directory._"
            )
```

### Step 4: Run tests to verify they pass

```bash
cd /home/work/repo/amplifier-distro
uv run python -m pytest tests/test_slack_bridge.py::TestCommandHandler::test_cmd_new_shows_working_dir_in_response tests/test_slack_bridge.py::TestCommandHandler::test_cmd_new_shows_hint_when_in_home_dir tests/test_slack_bridge.py::TestCommandHandler::test_cmd_new_no_hint_when_working_dir_set -v
```

Expected: All 3 new tests PASS.

### Step 5: Run full test suite

```bash
cd /home/work/repo/amplifier-distro
uv run python -m pytest tests/test_slack_bridge.py -v --tb=short
```

Expected: All tests PASS. Note: the existing `test_cmd_new` test (line 676) asserts `"Started new session" in result.text` — the change still starts with that phrase, so it passes. Verify this explicitly.

### Step 6: Commit

```bash
cd /home/work/repo/amplifier-distro
git add src/amplifier_distro/server/apps/slack/commands.py tests/test_slack_bridge.py
git commit -m "feat(slack): show working directory in session start message

cmd_new response now shows where the session is operating:
  Started new session a3f2b1c0 in ~/repo/my-project

When the session lands in ~ (unconfigured default), a tip is shown:
  Tip: set slack.default_working_dir in distro.yaml to default to
  your project directory.

This gives users immediate feedback about session location and helps
them discover the configuration option.

Closes #34"
```

---

## Post-implementation

### Run the full test suite one final time

```bash
cd /home/work/repo/amplifier-distro
uv run python -m pytest tests/ -v --tb=short
```

Expected: All tests pass across the entire project.

### Run code quality checks

```bash
cd /home/work/repo/amplifier-distro
uv run ruff check src/amplifier_distro/server/apps/slack/config.py src/amplifier_distro/server/apps/slack/models.py src/amplifier_distro/server/apps/slack/sessions.py src/amplifier_distro/server/apps/slack/commands.py
uv run ruff format --check src/amplifier_distro/server/apps/slack/config.py src/amplifier_distro/server/apps/slack/models.py src/amplifier_distro/server/apps/slack/sessions.py src/amplifier_distro/server/apps/slack/commands.py
```

Expected: No lint errors, formatting clean.

---

## Files Changed Summary

| File | Task | Changes |
|------|------|---------|
| `src/amplifier_distro/server/apps/slack/config.py` | 1 | Wire `default_working_dir` in `from_env()` via `_str()` helper, add debug log |
| `src/amplifier_distro/server/apps/slack/models.py` | 2 | Add `working_dir: str = ""` field to `SessionMapping` |
| `src/amplifier_distro/server/apps/slack/sessions.py` | 2, 3 | Update `_save/_load` serialization, populate `working_dir` on mappings, add optional `working_dir` param to `create_session()` with logging |
| `src/amplifier_distro/server/apps/slack/commands.py` | 4 | Show `working_dir` in `cmd_new` response, hint when in `~` |
| `tests/test_slack_bridge.py` | 1-4 | 15 new test cases across 4 test classes |

## Out of Scope

- **Command argument parsing** for how users specify project/directory in `@amp new` — separate design session in progress
- **Project name resolution** (resolving project names to paths) — separate design session
- **Changes to `session-info.json` or the resume path** — already fixed by PR #56
- **PR #49 (SurfaceSessionRegistry)** — if it merges first, `SessionMapping` moves to `surface_registry.py` and `sessions.py` gets rewritten. The conflicts are mechanical: same `working_dir` additions go on the new types instead. Tasks 1 and 4 are unaffected.
