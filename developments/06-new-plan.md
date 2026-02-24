# Amplifier Distro: Lean Experience Server Completion Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Branch:** `lean-experience-server` (already checked out)
**Starting point:** The heavy lifting is done. 14,508 lines removed across 52 files in 3 commits. What remains is a 4,674-line experience server with a clean architecture but a few known gaps.

**Goal:** Fix known issues, harden the codebase for server extraction, implement session resume, and merge to main.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, pytest (async via pytest-asyncio), uv for package management.

**Test runner:** `uv run python -m pytest tests/ -q`

---

## Pre-work: Establish Baseline

Before any changes, establish the test baseline.

**Step 1: Run the full test suite**

```bash
cd amplifier-distro
uv run python -m pytest tests/ -q 2>&1 | tee /tmp/baseline.txt
```

Record the pass/fail/error counts. Some tests may fail because:
- The `bridge_backend` fixture in `test_session_backend.py` references `_bridge` (the old bridge attribute) which no longer exists on `FoundationBackend`
- The reconnect lock tests in `test_services.py` expect `_bridge.resume_session` which is never called
- Tests requiring `amplifier-foundation` installed will fail if it's not in the environment

**Step 2: Categorize failures**

| Category | Action |
|----------|--------|
| Tests referencing `_bridge` | Fix in Phase 1 |
| Tests requiring foundation installed | Expected -- they pass in CI with deps |
| Pre-existing failures from main | Ignore (document) |

---

## Phase 1: Fix Known Issues

Pure cleanup. No new features. Gets the test suite honest.

### Task 1.1: Fix version mismatch

`pyproject.toml` says `version = "0.2.0"`. `src/amplifier_distro/__init__.py` says `__version__ = "0.1.0"`.

**Files:**
- Modify: `src/amplifier_distro/__init__.py`

**Step 1:** Change `__init__.py` line 3:
```python
__version__ = "0.2.0"
```

**Step 2:** Commit
```
git add -A && git commit -m "fix: align __version__ with pyproject.toml (0.2.0)"
```

---

### Task 1.2: Fix stale `bridge_backend` fixture in test_session_backend.py

The `bridge_backend` fixture at `tests/test_session_backend.py:32-46` sets `backend._bridge = AsyncMock()`, but `FoundationBackend` no longer has a `_bridge` attribute. It calls `self._load_bundle()` directly.

**Files:**
- Modify: `tests/test_session_backend.py`

**Step 1: Update the fixture**

Replace the `bridge_backend` fixture (lines 32-46) with one that sets the correct attributes:

```python
@pytest.fixture
def bridge_backend():
    """FoundationBackend with mocked _load_bundle."""
    from amplifier_distro.server.session_backend import FoundationBackend

    backend = FoundationBackend.__new__(FoundationBackend)
    backend._bundle_name = "test-bundle"
    backend._sessions = {}
    backend._reconnect_locks = {}
    backend._session_queues = {}
    backend._worker_tasks = {}
    backend._ended_sessions = set()
    return backend
```

Key change: no `_bridge`, added `_bundle_name`.

**Step 2: Fix `test_create_session_starts_worker_task`**

The current test mocks `bridge_backend._bridge.create_session`. Replace with mocking `_load_bundle`:

```python
async def test_create_session_starts_worker_task(self, bridge_backend):
    """create_session() must pre-start a session worker."""
    mock_session = MagicMock()
    mock_session.session_id = "sess-0001"

    mock_prepared = MagicMock()
    mock_prepared.create_session.return_value = mock_session

    bridge_backend._load_bundle = MagicMock(return_value=mock_prepared)

    from amplifier_distro.server.session_backend import FoundationBackend

    await FoundationBackend.create_session(
        bridge_backend,
        working_dir="/tmp",
        description="test",
    )

    assert "sess-0001" in bridge_backend._worker_tasks
    worker = bridge_backend._worker_tasks["sess-0001"]
    assert not worker.done(), "Worker task should still be running"
    # Cleanup
    worker.cancel()
    with pytest.raises((asyncio.CancelledError, Exception)):
        await worker
```

**Step 3: Run test_session_backend.py**

```bash
uv run python -m pytest tests/test_session_backend.py -v
```

All tests that don't require actual foundation imports should pass.

**Step 4:** Commit
```
git add -A && git commit -m "fix: update test_session_backend fixture for foundation-direct architecture"
```

---

### Task 1.3: Fix stale reconnect lock tests in test_services.py

The `TestFoundationBackendReconnectLock` class (lines ~260-507 of `tests/test_services.py`) tests concurrency properties of `_reconnect`. These tests reference `backend._bridge.resume_session` which no longer exists. Since `_reconnect` currently raises `NotImplementedError`, these tests cannot pass.

**Files:**
- Modify: `tests/test_services.py`

**Step 1: Skip the reconnect lock tests**

Add a skip decorator to the entire class:

```python
@pytest.mark.skip(reason="Pending session resume implementation (Phase 3)")
class TestFoundationBackendReconnectLock:
    ...
```

Do NOT delete these tests. They test important concurrency properties that will be needed once session resume is implemented in Phase 3.

**Step 2: Run test_services.py**

```bash
uv run python -m pytest tests/test_services.py -v
```

All non-skipped tests should pass.

**Step 3: Run the full suite**

```bash
uv run python -m pytest tests/ -q
```

Record the new baseline. This is the "clean" baseline for Phases 2-4.

**Step 4:** Commit
```
git add -A && git commit -m "test: skip reconnect lock tests pending session resume implementation"
```

---

## Phase 2: Harden

Small improvements identified by comparing the lean branch against the proposed refactor plan. Prepares the server for future extraction.

### Task 2.1: Define public API surface in `__init__.py`

The server currently imports from non-server distro modules via direct paths (`amplifier_distro.conventions`, `amplifier_distro.fileutil`). Define a public API so the server-extraction boundary is explicit.

**Files:**
- Modify: `src/amplifier_distro/__init__.py`

**Step 1: Read all server-to-non-server imports**

The complete list of cross-boundary imports (already verified):

| Non-server module | Used by server files | What's imported |
|---|---|---|
| `conventions` | `app.py`, `startup.py`, `web_chat`, `slack/sessions`, `slack/setup`, `slack/config` | Path constants |
| `fileutil` | `memory.py`, `web_chat/session_store`, `slack/sessions` | `atomic_write` |
| `transcript_persistence` | (registered as hook by `FoundationBackend`) | Hook functions |
| `backup` | `cli.py` (not server, but CLI) | `backup()`, `restore()` |
| `service` | `cli.py` (not server, but CLI) | `install_service()`, etc. |
| `tailscale` | `server/cli.py` | `get_dns_name()` |

**Step 2: Write the public API**

Replace `src/amplifier_distro/__init__.py`:

```python
"""Amplifier Distro - The Amplifier Experience Server.

Public API Surface
------------------
These are the modules and symbols that the server, apps, and CLI
are allowed to import. This surface defines the extraction boundary:
when the server becomes its own package, these are its dependencies.
"""

__version__ = "0.2.0"

# --- Constants (immutable, zero-cost) ---
from amplifier_distro import conventions  # noqa: F401

# --- Utilities ---
from amplifier_distro.fileutil import atomic_write  # noqa: F401

__all__ = [
    "__version__",
    "conventions",
    "atomic_write",
]
```

Keep it minimal. Only export what the server actually uses across the boundary. The CLI commands (`backup`, `service`, `tailscale`) use lazy imports inside their Click handlers -- they don't need to be in the public API.

**Step 3: Run the full test suite**

```bash
uv run python -m pytest tests/ -q
```

Adding exports should not break anything.

**Step 4:** Commit
```
git add -A && git commit -m "refactor: define public API surface in __init__.py for server extraction"
```

---

### Task 2.2: Add startup health check

The server boots fine even if `amplifier-foundation` isn't installed, then fails opaquely on the first session request. Add a startup probe.

**Files:**
- Modify: `src/amplifier_distro/server/startup.py`

**Step 1: Add a `check_foundation` function**

Add after the existing imports in `startup.py` (after line ~10):

```python
def check_foundation_available() -> bool:
    """Verify amplifier-foundation is importable at server startup.

    Returns True if foundation is available, False otherwise.
    Logs a clear error message on failure so operators know what to fix.
    """
    logger = logging.getLogger(__name__)
    try:
        from amplifier_foundation import load_bundle  # noqa: F401
        logger.info("amplifier-foundation: available")
        return True
    except ImportError:
        logger.error(
            "amplifier-foundation is not installed. "
            "The server will not be able to create sessions. "
            "Install with: uv pip install amplifier-foundation"
        )
        return False
```

**Step 2: Call it from `log_startup_info`**

In the existing `log_startup_info()` function (around line 170), add after the version/address logging:

```python
check_foundation_available()
```

This is informational, not blocking. The server still boots (dev mode uses `MockBackend`), but operators get a clear log message.

**Step 3: Write a test**

Add to an existing test file or create `tests/test_startup.py` if one doesn't exist:

```python
def test_check_foundation_available_returns_bool():
    from amplifier_distro.server.startup import check_foundation_available
    result = check_foundation_available()
    assert isinstance(result, bool)
```

**Step 4: Run tests and commit**

```bash
uv run python -m pytest tests/ -q
git add -A && git commit -m "feat: add foundation availability check at server startup"
```

---

### Task 2.3: Add migration breadcrumb for old distro.yaml

Users upgrading from the old distro may have `~/.amplifier/distro.yaml` sitting around doing nothing. Log a one-line notice.

**Files:**
- Modify: `src/amplifier_distro/server/startup.py`

**Step 1: Add a migration check**

Add after the `check_foundation_available` function:

```python
def check_legacy_config() -> None:
    """Log a notice if the old distro.yaml config file exists."""
    legacy = Path(conventions.AMPLIFIER_HOME).expanduser() / "distro.yaml"
    if legacy.exists():
        logging.getLogger(__name__).info(
            "Found legacy distro.yaml at %s. "
            "This file is no longer used -- configuration is now via "
            "environment variables and foundation's settings.yaml. "
            "You can safely delete it.",
            legacy,
        )
```

**Step 2: Call it from `log_startup_info`**

```python
check_legacy_config()
```

**Step 3: Run tests and commit**

```bash
uv run python -m pytest tests/ -q
git add -A && git commit -m "feat: log notice when legacy distro.yaml is found"
```

---

### Task 2.4: Add FoundationBackend.create_session test

The existing `test_session_backend.py` tests queue/worker infrastructure well, but the `create_session` happy path (mocking foundation's `load_bundle`) needs a proper test.

**Files:**
- Modify: `tests/test_session_backend.py`

**Step 1: Add a test class for the create_session flow**

```python
class TestFoundationBackendCreateSession:
    """Verify FoundationBackend.create_session calls foundation correctly."""

    async def test_create_session_calls_load_bundle(self, bridge_backend):
        """create_session must call _load_bundle and prepared.create_session."""
        mock_session = MagicMock()
        mock_session.session_id = "sess-create-001"

        mock_prepared = MagicMock()
        mock_prepared.create_session.return_value = mock_session

        bridge_backend._load_bundle = MagicMock(return_value=mock_prepared)

        from amplifier_distro.server.session_backend import FoundationBackend

        info = await FoundationBackend.create_session(
            bridge_backend,
            working_dir="/home/user/project",
            description="test session",
        )

        bridge_backend._load_bundle.assert_called_once()
        mock_prepared.create_session.assert_called_once()
        assert info.session_id == "sess-create-001"
        assert info.working_dir == "/home/user/project"
        assert info.description == "test session"
        assert info.is_active is True

        # Cleanup worker
        if "sess-create-001" in bridge_backend._worker_tasks:
            bridge_backend._worker_tasks["sess-create-001"].cancel()

    async def test_create_session_with_custom_bundle(self, bridge_backend):
        """create_session accepts an optional bundle_name override."""
        mock_session = MagicMock()
        mock_session.session_id = "sess-custom-001"

        mock_prepared = MagicMock()
        mock_prepared.create_session.return_value = mock_session

        bridge_backend._load_bundle = MagicMock(return_value=mock_prepared)

        from amplifier_distro.server.session_backend import FoundationBackend

        await FoundationBackend.create_session(
            bridge_backend,
            working_dir="/tmp",
            bundle_name="custom-bundle",
        )

        bridge_backend._load_bundle.assert_called_once_with("custom-bundle")

        # Cleanup worker
        if "sess-custom-001" in bridge_backend._worker_tasks:
            bridge_backend._worker_tasks["sess-custom-001"].cancel()

    async def test_create_session_returns_session_info(self, bridge_backend):
        """create_session returns a SessionInfo with correct fields."""
        mock_session = MagicMock()
        mock_session.session_id = "sess-info-001"

        mock_prepared = MagicMock()
        mock_prepared.create_session.return_value = mock_session

        bridge_backend._load_bundle = MagicMock(return_value=mock_prepared)

        from amplifier_distro.server.session_backend import (
            FoundationBackend,
            SessionInfo,
        )

        info = await FoundationBackend.create_session(
            bridge_backend,
            working_dir="~",
        )

        assert isinstance(info, SessionInfo)
        assert info.session_id == "sess-info-001"

        # Cleanup worker
        if "sess-info-001" in bridge_backend._worker_tasks:
            bridge_backend._worker_tasks["sess-info-001"].cancel()
```

**Step 2: Run tests**

```bash
uv run python -m pytest tests/test_session_backend.py -v
```

**Step 3:** Commit
```
git add -A && git commit -m "test: add FoundationBackend.create_session happy-path tests"
```

---

## Phase 3: Session Resume

The critical missing feature. `FoundationBackend._reconnect()` currently raises `NotImplementedError`. Both web_chat and Slack call `backend.resume_session()` which delegates to `_reconnect()`. Implementing this enables session persistence across server restarts.

### Task 3.1: Explore foundation's session and transcript APIs

Before writing code, understand what foundation provides.

**Step 1: Find foundation's session storage**

```bash
# In the amplifier-foundation repo (or wherever it's checked out):
grep -rn "session_id\|session_dir\|find_session\|projects_dir" src/amplifier_foundation/ --include="*.py" | head -40
grep -rn "transcript\|set_messages\|restore" src/amplifier_foundation/ --include="*.py" | head -40
grep -rn "find_orphaned_tool_calls\|orphan\|sanitize" src/amplifier_foundation/ --include="*.py" | head -20
```

**What you're looking for:**
- How foundation resolves `session_id` to a directory path
- Whether `prepared.create_session()` accepts `session_id` and `is_resumed` parameters
- Where `transcript.jsonl` lives relative to session directory
- Whether foundation exposes `find_orphaned_tool_calls()` or `sanitize_message()`
- How to inject a transcript into a new session (likely `session.context.set_messages()`)

**Step 2: Read the existing plan doc's notes on this**

`docs/plans/2026-02-23-lean-experience-server.md` says:
> Foundation already has `find_orphaned_tool_calls()` in `slice.py`. The right fix is a `restore_transcript()` utility in foundation that both consumers use.

Check whether that utility now exists:
```bash
grep -rn "restore_transcript" src/amplifier_foundation/ --include="*.py"
```

**Step 3: Check how amplifier-app-cli implements resume**

The CLI already has session resume. Find it and understand the pattern:
```bash
grep -rn "resume\|restore\|reconnect\|set_messages" ../amplifier-app-cli/src/ --include="*.py" | head -30
```

This is the reference implementation. The distro's `_reconnect` should follow the same pattern.

**Step 4: Document findings**

Write a brief note (in comments or scratch file) of:
- The exact foundation API calls needed
- Whether any foundation changes are required
- The sequence: find dir → load transcript → strip orphans → create session → inject messages

---

### Task 3.2: Implement `_reconnect` in FoundationBackend

**Files:**
- Modify: `src/amplifier_distro/server/session_backend.py`

**Step 1: Update `resume_session` to pass `working_dir` through**

Current code at line 472-475:
```python
async def resume_session(self, session_id: str, working_dir: str) -> None:
    if self._sessions.get(session_id) is None:
        await self._reconnect(session_id)
```

Change to:
```python
async def resume_session(self, session_id: str, working_dir: str) -> None:
    if self._sessions.get(session_id) is None:
        await self._reconnect(session_id, working_dir=working_dir)
```

**Step 2: Update `_reconnect` signature and implement**

Replace the current stub at lines 310-332. The implementation should follow this sequence (adapt based on findings from Task 3.1):

```python
async def _reconnect(
    self, session_id: str, *, working_dir: str = "~"
) -> _SessionHandle:
    """Resume a session whose handle was lost (e.g. after server restart).

    Loads the transcript from disk, strips orphaned tool calls, creates
    a fresh session with the same bundle, and injects the transcript.
    """
    if session_id in self._ended_sessions:
        raise ValueError(
            f"Session {session_id} was intentionally ended"
            " and cannot be reconnected"
        )

    logger.info("Reconnecting session %s", session_id)

    # 1. Find the session directory
    #    (Use foundation's session discovery -- adapt to actual API)
    from amplifier_foundation import find_session, load_bundle

    session_dir = find_session(session_id)
    if session_dir is None:
        raise ValueError(f"Session directory not found for {session_id}")

    # 2. Load transcript
    transcript_path = session_dir / "transcript.jsonl"
    if not transcript_path.exists():
        raise ValueError(f"No transcript for session {session_id}")

    import json
    messages = []
    for line in transcript_path.read_text().splitlines():
        if line.strip():
            messages.append(json.loads(line))

    # 3. Strip orphaned tool calls
    #    (Use foundation's utility -- adapt to actual API)
    from amplifier_foundation.slice import find_orphaned_tool_calls
    orphan_ids = find_orphaned_tool_calls(messages)
    if orphan_ids:
        messages = [
            m for m in messages
            if m.get("tool_call_id") not in orphan_ids
            and not any(
                tc.get("id") in orphan_ids
                for tc in m.get("tool_calls", [])
            )
        ]
        logger.info(
            "Stripped %d orphaned tool calls from session %s",
            len(orphan_ids), session_id,
        )

    # 4. Create a new session with the same bundle
    wd = Path(working_dir).expanduser()
    prepared = self._load_bundle()
    session = prepared.create_session(
        working_dir=str(wd),
        session_id=session_id,
        is_resumed=True,
    )

    # 5. Inject the transcript
    session.context.set_messages(messages)

    # 6. Build handle and worker infrastructure
    handle = _SessionHandle(
        session_id=session_id,
        project_id="",
        working_dir=wd,
        session=session,
    )
    self._sessions[session_id] = handle

    queue: asyncio.Queue = asyncio.Queue()
    self._session_queues[session_id] = queue
    self._worker_tasks[session_id] = asyncio.create_task(
        self._session_worker(session_id)
    )

    logger.info("Session %s reconnected successfully", session_id)
    return handle
```

**IMPORTANT:** The exact foundation API calls (`find_session`, `find_orphaned_tool_calls`, `session.context.set_messages`) must be verified against Task 3.1 findings. The above is the structure -- adapt the imports and method names to match foundation's actual API.

**Step 3: Also update `send_message`'s reconnect path**

The `send_message` method at lines 277-308 calls `_reconnect(session_id)` without `working_dir`. Check whether `send_message` can infer `working_dir` from session metadata, or whether it should use a default:

```python
handle = await self._reconnect(session_id, working_dir="~")
```

Using `"~"` as a fallback is reasonable -- the session directory already has the real working_dir in its metadata. The `working_dir` parameter is a hint, not the source of truth.

**Step 4: Run tests**

```bash
uv run python -m pytest tests/test_session_backend.py -v
```

**Step 5:** Commit
```
git add -A && git commit -m "feat: implement session resume in FoundationBackend._reconnect"
```

---

### Task 3.3: Un-skip and fix reconnect lock tests

Now that `_reconnect` is implemented, the reconnect lock tests from Phase 1 can be re-enabled.

**Files:**
- Modify: `tests/test_services.py`

**Step 1: Remove the `@pytest.mark.skip` from `TestFoundationBackendReconnectLock`**

**Step 2: Update the test fixture to mock the new `_reconnect` internals**

The old tests mocked `backend._bridge.resume_session`. The new tests need to mock `_reconnect`'s internals (foundation imports). The cleanest approach: mock `_reconnect` itself for the lock tests, since they're testing the LOCK behavior, not the reconnect logic:

```python
class TestFoundationBackendReconnectLock:
    """Verify concurrent reconnects are serialized per-session."""

    @pytest.mark.asyncio
    async def test_concurrent_reconnect_calls_resume_once(self):
        """Two concurrent send_message to missing session = one reconnect."""
        from amplifier_distro.server.session_backend import FoundationBackend

        backend = FoundationBackend.__new__(FoundationBackend)
        backend._bundle_name = "test-bundle"
        backend._sessions = {}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()

        reconnect_count = 0

        async def fake_reconnect(session_id, *, working_dir="~"):
            nonlocal reconnect_count
            reconnect_count += 1
            await asyncio.sleep(0.05)
            # Simulate successful reconnect
            mock_session = MagicMock()
            mock_session.session_id = session_id
            mock_session.execute = AsyncMock(return_value="response")
            handle = _SessionHandle(
                session_id=session_id,
                project_id="test",
                working_dir=Path(working_dir),
                session=mock_session,
            )
            backend._sessions[session_id] = handle
            queue = asyncio.Queue()
            backend._session_queues[session_id] = queue
            backend._worker_tasks[session_id] = asyncio.create_task(
                backend._session_worker(session_id)
            )
            return handle

        backend._reconnect = fake_reconnect

        r1, r2 = await asyncio.gather(
            backend.send_message("sess-123", "hello"),
            backend.send_message("sess-123", "world"),
        )

        assert reconnect_count == 1, (
            f"Expected 1 reconnect, got {reconnect_count}"
        )
```

Apply the same pattern to all tests in the class: mock `_reconnect` as a method on the instance, not `_bridge.resume_session`.

**Step 3: Run tests**

```bash
uv run python -m pytest tests/test_services.py -v -k "ReconnectLock"
```

**Step 4: Run full suite**

```bash
uv run python -m pytest tests/ -q
```

**Step 5:** Commit
```
git add -A && git commit -m "test: re-enable and fix reconnect lock tests for foundation-direct architecture"
```

---

### Task 3.4: Add session resume integration tests

**Files:**
- Modify: `tests/test_session_backend.py`

**Step 1: Add tests for `_reconnect`**

```python
class TestFoundationBackendReconnect:
    """Verify _reconnect loads transcript and creates session."""

    async def test_reconnect_raises_for_ended_session(self, bridge_backend):
        """_reconnect must refuse tombstoned sessions."""
        bridge_backend._ended_sessions.add("sess-ended")

        from amplifier_distro.server.session_backend import FoundationBackend

        with pytest.raises(ValueError, match="intentionally ended"):
            await FoundationBackend._reconnect(
                bridge_backend, "sess-ended", working_dir="~"
            )

    async def test_reconnect_not_implemented_documents_gap(self, bridge_backend):
        """If foundation is unavailable, _reconnect raises clearly."""
        from amplifier_distro.server.session_backend import FoundationBackend

        # Without foundation installed, _reconnect should raise ImportError
        # or NotImplementedError with a clear message
        with pytest.raises((ImportError, NotImplementedError, ValueError)):
            await FoundationBackend._reconnect(
                bridge_backend, "sess-missing", working_dir="~"
            )

    async def test_resume_session_delegates_to_reconnect(self, bridge_backend):
        """resume_session calls _reconnect with working_dir."""
        from amplifier_distro.server.session_backend import FoundationBackend

        reconnect_called_with = {}

        async def fake_reconnect(session_id, *, working_dir="~"):
            reconnect_called_with["session_id"] = session_id
            reconnect_called_with["working_dir"] = working_dir

        bridge_backend._reconnect = fake_reconnect

        await FoundationBackend.resume_session(
            bridge_backend, "sess-resume", "/home/user/project"
        )

        assert reconnect_called_with["session_id"] == "sess-resume"
        assert reconnect_called_with["working_dir"] == "/home/user/project"

    async def test_resume_session_skips_if_already_cached(self, bridge_backend):
        """resume_session is a no-op if the session handle exists."""
        from amplifier_distro.server.session_backend import FoundationBackend

        bridge_backend._sessions["sess-cached"] = MagicMock()

        reconnect_called = False

        async def fake_reconnect(session_id, *, working_dir="~"):
            nonlocal reconnect_called
            reconnect_called = True

        bridge_backend._reconnect = fake_reconnect

        await FoundationBackend.resume_session(
            bridge_backend, "sess-cached", "~"
        )

        assert not reconnect_called
```

**Step 2: Run tests**

```bash
uv run python -m pytest tests/test_session_backend.py -v
```

**Step 3:** Commit
```
git add -A && git commit -m "test: add session resume tests for FoundationBackend"
```

---

### Task 3.5: Verify web_chat and Slack resume paths

Both web_chat and Slack call `backend.resume_session()`. Verify the integration isn't broken.

**Files:**
- Read: `src/amplifier_distro/server/apps/web_chat/__init__.py` (line 234: `resume_session`)
- Read: `src/amplifier_distro/server/apps/slack/sessions.py` (line 237: `resume_session`)

**Step 1: Check web_chat resume**

At `web_chat/__init__.py:234`, `WebChatSessionManager.resume_session()` calls:
```python
await self._backend.resume_session(session_id, working_dir)
```

Verify that the `working_dir` argument is correctly sourced (from the session store or a default).

**Step 2: Check Slack resume**

At `slack/sessions.py:237`, `SlackSessionManager.get_or_create_session()` calls:
```python
await self._backend.resume_session(session_id, working_dir)
```

Verify the same.

**Step 3: Run the web_chat and Slack tests**

```bash
uv run python -m pytest tests/test_web_chat.py tests/test_web_chat_store.py tests/test_slack_bridge.py -v
```

These tests use `MockBackend`, so they should pass regardless. But verify no import errors or signature mismatches.

**Step 4:** If any fixes needed, commit:
```
git add -A && git commit -m "fix: align web_chat and Slack resume paths with updated backend API"
```

---

## Phase 4: Merge

### Task 4.1: Final validation

**Step 1: Run the full test suite**

```bash
uv run python -m pytest tests/ -q
```

**Expected:** All tests pass except any that require `amplifier-foundation` to be installed (which pass in CI). Zero new failures compared to the Phase 1 baseline.

**Step 2: Verify line counts**

```bash
find src/amplifier_distro -name "*.py" -not -path "*__pycache__*" | xargs wc -l | tail -1
```

Should be ~4,700-4,800 lines (original 4,674 + startup probe + `__init__.py` expansion + `_reconnect` implementation).

**Step 3: Review git log**

```bash
git log main..HEAD --oneline
```

Verify commits are clean and well-described.

**Step 4:** Commit if any final cleanup needed.

---

### Task 4.2: Merge to main

**Option A: Squash merge** (recommended if the 3 original commits are too coarse)

```bash
git checkout main
git merge --squash lean-experience-server
git commit -m "refactor: slim distro to lean experience server

Remove bridge layer, config system, feature catalog, diagnostics,
install wizard, and settings app. Replace with FoundationBackend
calling amplifier-foundation directly. Environment-driven config
replaces distro.yaml.

What was removed:
- bridge.py, bridge_protocols.py (~1,090 lines)
- config.py, schema.py (~435 lines)
- features.py, bundle_composer.py, docs_config.py (~475 lines)
- doctor.py, preflight.py (~678 lines)
- deploy.py, migrate.py, update_check.py, provider_api.py (~1,289 lines)
- install_wizard, settings, example apps (~3,339 lines)
- 15 test files (~5,558 lines)

What remains:
- Experience server (web chat, Slack, voice, routines)
- CLI: server, backup/restore, service commands
- FoundationBackend with session resume support
- Public API surface for future server extraction

Total: -14,508 lines removed, ~4,800 lines remaining."
```

**Option B: Merge commit** (preserves branch history)

```bash
git checkout main
git merge lean-experience-server --no-ff -m "Merge lean-experience-server: slim distro to experience server only"
```

**Step 2: Push**

```bash
git push origin main
```

**Step 3: Clean up branch**

```bash
git branch -d lean-experience-server
git push origin --delete lean-experience-server
```

---

## Summary

| Phase | Tasks | Key Changes |
|-------|-------|-------------|
| 1. Fix Known Issues | 3 tasks | Version mismatch, stale test fixtures, skip broken reconnect tests |
| 2. Harden | 4 tasks | Public API surface, startup probe, migration breadcrumb, create_session tests |
| 3. Session Resume | 5 tasks | Explore foundation API, implement `_reconnect`, fix reconnect lock tests, integration tests |
| 4. Merge | 2 tasks | Final validation, merge to main |
| **Total** | **14 tasks** | |

**Dependency note:** Phase 3 depends on `amplifier-foundation` providing session discovery and transcript loading utilities. If foundation doesn't yet expose these (Task 3.1 will reveal this), the implementation approach has two options:

1. **Foundation has what we need** — implement `_reconnect` using foundation's API directly.
2. **Foundation needs a new utility** — contribute a `restore_transcript()` function to foundation first (coordinated change: foundation PR first, then distro PR). The amplifier-app-cli's existing resume logic is the reference implementation to extract from.

**Success Criteria:**
- [ ] All tests pass (no new failures vs main)
- [ ] `FoundationBackend.create_session` has unit tests
- [ ] `FoundationBackend._reconnect` is implemented (no more `NotImplementedError`)
- [ ] Reconnect lock tests pass (concurrency properties verified)
- [ ] `__init__.py` defines public API surface with `__all__`
- [ ] Server logs clear message if foundation unavailable
- [ ] Server logs notice if legacy `distro.yaml` found
- [ ] Version string consistent between `pyproject.toml` and `__init__.py`
- [ ] Branch merged to main
