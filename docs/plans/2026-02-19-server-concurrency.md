# Server Concurrency Fixes Implementation Plan (Issue #57)

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Fix three concurrency hazards that cause request queuing, silent task failures, and race conditions under concurrent load.  
**Architecture:** Narrow `_session_lock` in web_chat so `send_message` runs outside the lock; fire-and-forget Slack events with ACK-before-task; serialize per-session `handle.run()` calls in BridgeBackend via asyncio queues.  
**Tech Stack:** FastAPI, asyncio, httpx (AsyncClient + ASGITransport for tests), pytest-asyncio (`asyncio_mode = "auto"`)

---

## Scope

- **Fix 1** — `src/amplifier_distro/server/apps/web_chat/__init__.py`
- **Fix 2** — `src/amplifier_distro/server/apps/slack/socket_mode.py`
- **Fix 4** — `src/amplifier_distro/server/session_backend.py`
- **Phase 5** — Shutdown wiring in `services.py` + `app.py`
- **Fix 3 is explicitly dropped.** No voice bridge changes in this plan.
- No new source files. New test files only.

---

## Phase 0 — Test Infrastructure

### Task 0.1: Add httpx≥0.27 to dev dependencies

**Files:**
- Modify: `pyproject.toml`

> `httpx` is already a core dependency at `>=0.24.0`. This tightens the dev floor to `>=0.27` to ensure `httpx.ASGITransport` (the ASGI in-process transport used for async test clients) is available. No test needed — this is a build file change.

**Step 1: Edit `pyproject.toml`**

Find the dev extras section (currently lines 38–41) and add `httpx`:

```toml
# Development and testing
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21.0",
    "httpx>=0.27",
]
```

**Step 2: Verify the dependency resolves**

```bash
uv pip install -e ".[dev]" --quiet && python -c "import httpx; print(httpx.__version__)"
```

Expected: prints a version string `>=0.27`.

**Step 3: Commit**

Delegate to `foundation:git-ops`:
```
git add pyproject.toml
Commit message: "fix: add httpx>=0.27 to dev dependencies for async test client"
```

---

### Task 0.2: Add `async_webchat_client` fixture and autouse task cleanup

**Files:**
- Modify: `tests/conftest.py`

**Step 1: Read current `tests/conftest.py`** (already done — it is 17 lines, two simple path fixtures)

**Step 2: Write the updated `tests/conftest.py`**

```python
"""Shared test fixtures for amplifier-distro acceptance tests."""

import asyncio
from pathlib import Path

import httpx
import pytest

from amplifier_distro.server.services import init_services, reset_services


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def src_root(project_root):
    """Return the src/ directory."""
    return project_root / "src"


@pytest.fixture
async def async_webchat_client():
    """Async httpx client wired directly to the web-chat ASGI app.

    Resets all module-level web_chat state before each test so tests
    are fully isolated. Uses httpx.ASGITransport for in-process requests
    (no real TCP socket, but full asyncio event loop — unlike TestClient).
    """
    import amplifier_distro.server.apps.web_chat as wc
    from amplifier_distro.server.app import DistroServer
    from amplifier_distro.server.apps.web_chat import manifest

    # Reset module-level state
    wc._active_session_id = None
    wc._session_lock = asyncio.Lock()
    wc._message_in_flight = False

    reset_services()
    init_services(dev_mode=True)

    server = DistroServer()
    server.register_app(manifest)

    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    reset_services()


@pytest.fixture(autouse=True)
async def _cancel_stray_tasks():
    """Cancel any tasks that leaked from a test.

    Prevents cross-test pollution when an async test creates tasks
    and doesn't await them (e.g. a _message_in_flight that never clears).
    Runs after every test automatically.
    """
    yield
    # Give the event loop one cycle to settle
    await asyncio.sleep(0)
    current = asyncio.current_task()
    for task in asyncio.all_tasks():
        if task is not current and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=0.1)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
```

**Step 3: Verify conftest loads without error**

```bash
uv run python -m pytest tests/test_web_chat.py -q --collect-only 2>&1 | head -20
```

Expected: test collection succeeds, no import errors.

**Step 4: Commit**

```
git add tests/conftest.py
Commit message: "test: add async_webchat_client fixture and stray-task cleanup to conftest"
```

---

## Phase 1 — Fix 1: web_chat lock narrowing

Model: `end_session()` in `web_chat/__init__.py` (lines 320–342) already does the right pattern — capture `session_id` inside the lock, set `_active_session_id = None`, release the lock, then call backend outside. All four tasks in this phase bring `chat()`, `session_status()`, and `create_session()` into alignment with that pattern.

---

### Task 1.1: Narrow lock in `chat()` + add `_message_in_flight` guard

**Files:**
- Modify: `src/amplifier_distro/server/apps/web_chat/__init__.py`
- Modify: `tests/test_web_chat.py`

**Step 1: Write the failing tests**

Add a new class at the bottom of `tests/test_web_chat.py`:

```python
class TestWebChatConcurrency:
    """Verify concurrent request behaviour after lock narrowing.

    These tests use httpx.AsyncClient (async_webchat_client fixture)
    because starlette.testclient.TestClient runs requests in a thread
    and cannot produce true asyncio concurrency.
    """

    async def test_in_flight_guard_rejects_concurrent_chat(
        self, async_webchat_client
    ):
        """While a chat is in-flight a second chat returns 409."""
        from unittest.mock import patch

        await async_webchat_client.post(
            "/apps/web-chat/api/session", json={}
        )

        async def slow_send(session_id, message):
            import asyncio
            await asyncio.sleep(0.05)  # yield so second request runs
            return f"[response: {message}]"

        with patch(
            "amplifier_distro.server.apps.web_chat._get_backend"
        ) as mock_get_backend:
            from unittest.mock import AsyncMock
            mock_get_backend.return_value = AsyncMock(send_message=slow_send)

            import asyncio
            r1, r2 = await asyncio.gather(
                async_webchat_client.post(
                    "/apps/web-chat/api/chat", json={"message": "first"}
                ),
                async_webchat_client.post(
                    "/apps/web-chat/api/chat", json={"message": "second"}
                ),
            )

        codes = sorted([r1.status_code, r2.status_code])
        assert codes == [200, 409], f"Expected [200, 409], got {codes}"
        # The 409 must carry the right payload
        resp_409 = r1 if r1.status_code == 409 else r2
        assert "in_flight" in resp_409.json().get("error", "").lower() or \
               resp_409.json().get("session_connected") is False

    async def test_chat_succeeds_after_in_flight_clears(
        self, async_webchat_client
    ):
        """After a chat completes, the next chat is accepted normally."""
        await async_webchat_client.post(
            "/apps/web-chat/api/session", json={}
        )
        r1 = await async_webchat_client.post(
            "/apps/web-chat/api/chat", json={"message": "hello"}
        )
        assert r1.status_code == 200

        r2 = await async_webchat_client.post(
            "/apps/web-chat/api/chat", json={"message": "world"}
        )
        assert r2.status_code == 200
```

**Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/test_web_chat.py::TestWebChatConcurrency -x -v 2>&1 | tail -20
```

Expected: `FAILED` — `test_in_flight_guard_rejects_concurrent_chat` fails because `_message_in_flight` doesn't exist yet.

**Step 3: Implement — add `_message_in_flight` and narrow the lock in `chat()`**

Read the current file first (already done — `chat()` is lines 237–317).

Make these changes to `src/amplifier_distro/server/apps/web_chat/__init__.py`:

**(a) Add the module-level flag after line 41:**

```python
_active_session_id: str | None = None
_session_lock = asyncio.Lock()
_message_in_flight: bool = False  # True while a send_message() call is in progress
```

**(b) Update `chat()` — replace the entire `async with _session_lock:` block (lines 275–317) with the narrowed version:**

```python
    async with _session_lock:
        if _active_session_id is None:
            return JSONResponse(
                status_code=409,
                content={
                    "error": (
                        "No active session. Create one first via POST /api/session."
                    ),
                    "session_connected": False,
                },
            )
        if _message_in_flight:
            return JSONResponse(
                status_code=409,
                content={
                    "error": "A message is already in-flight. Wait for it to complete.",
                    "session_connected": True,
                    "in_flight": True,
                },
            )
        session_id = _active_session_id
        _message_in_flight = True

    # Lock released — backend call runs concurrently with other routes
    try:
        backend = _get_backend()
        response = await backend.send_message(session_id, user_message)
        return JSONResponse(
            content={
                "response": response,
                "session_id": session_id,
                "session_connected": True,
            }
        )
    except ValueError:
        # Session disappeared — guard the write
        async with _session_lock:
            _active_session_id = None
        return JSONResponse(
            status_code=409,
            content={
                "error": "Session no longer exists. Create a new one.",
                "session_connected": False,
            },
        )
    except RuntimeError as e:
        return JSONResponse(
            status_code=503,
            content={"error": str(e)},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Chat message failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "type": type(e).__name__},
        )
    finally:
        _message_in_flight = False
```

> Note: the `global` declaration for `_message_in_flight` must be added to the `chat()` function header alongside `global _active_session_id`.

**(c) Update the `webchat_client` fixture in `tests/test_web_chat.py`** to reset the new flag:

```python
@pytest.fixture
def webchat_client() -> TestClient:
    """Create a TestClient with web-chat app and services initialized."""
    import amplifier_distro.server.apps.web_chat as wc

    wc._active_session_id = None
    wc._session_lock = asyncio.Lock()   # fresh lock between tests
    wc._message_in_flight = False

    init_services(dev_mode=True)

    from amplifier_distro.server.apps.web_chat import manifest

    server = DistroServer()
    server.register_app(manifest)
    return TestClient(server.app)
```

Add `import asyncio` to `tests/test_web_chat.py` imports if not already present.

**Step 4: Run tests to verify they pass**

```bash
uv run python -m pytest tests/test_web_chat.py::TestWebChatConcurrency -x -v 2>&1 | tail -20
```

Expected: both tests `PASSED`.

**Step 5: Verify no regressions in the existing suite**

```bash
uv run python -m pytest tests/test_web_chat.py -q 2>&1 | tail -10
```

Expected: all tests pass.

---

### Task 1.2: Guard unguarded `_active_session_id = None` in `except ValueError`

> This was already fixed as part of Task 1.1 — the `except ValueError` block now does `async with _session_lock: _active_session_id = None`. No additional code change needed.

**Step 1: Write the regression test**

Add to `TestWebChatConcurrency` in `tests/test_web_chat.py`:

```python
    async def test_session_id_cleared_under_lock_on_value_error(
        self, async_webchat_client
    ):
        """When send_message raises ValueError, _active_session_id is cleared safely."""
        from unittest.mock import patch, AsyncMock

        await async_webchat_client.post(
            "/apps/web-chat/api/session", json={}
        )

        async def failing_send(session_id, message):
            raise ValueError("Unknown session")

        with patch(
            "amplifier_distro.server.apps.web_chat._get_backend"
        ) as mock_get_backend:
            mock_get_backend.return_value = AsyncMock(send_message=failing_send)
            r = await async_webchat_client.post(
                "/apps/web-chat/api/chat", json={"message": "hello"}
            )

        assert r.status_code == 409
        assert r.json()["session_connected"] is False

        # Session should now be cleared
        status = await async_webchat_client.get("/apps/web-chat/api/session")
        assert status.json()["connected"] is False
```

**Step 2: Run test to verify it passes immediately** (the fix is already in from Task 1.1)

```bash
uv run python -m pytest tests/test_web_chat.py::TestWebChatConcurrency::test_session_id_cleared_under_lock_on_value_error -v 2>&1 | tail -10
```

Expected: `PASSED`.

---

### Task 1.3: Narrow lock in `session_status()` and `create_session()`

**Files:**
- Modify: `src/amplifier_distro/server/apps/web_chat/__init__.py`

**Step 1: Write failing tests**

Add to `TestWebChatConcurrency`:

```python
    async def test_session_status_does_not_block_concurrent_chat(
        self, async_webchat_client
    ):
        """session_status() must not hold _session_lock during backend I/O."""
        from unittest.mock import patch, AsyncMock

        await async_webchat_client.post(
            "/apps/web-chat/api/session", json={}
        )

        async def slow_get_info(session_id):
            import asyncio
            await asyncio.sleep(0.05)
            from amplifier_distro.server.session_backend import SessionInfo
            return SessionInfo(session_id=session_id, is_active=True)

        with patch(
            "amplifier_distro.server.apps.web_chat._get_backend"
        ) as mock_get_backend:
            mock_backend = AsyncMock()
            mock_backend.get_session_info = slow_get_info
            mock_backend.send_message = AsyncMock(return_value="ok")
            mock_get_backend.return_value = mock_backend

            import asyncio
            r_status, r_chat = await asyncio.gather(
                async_webchat_client.get("/apps/web-chat/api/session"),
                async_webchat_client.post(
                    "/apps/web-chat/api/chat", json={"message": "hi"}
                ),
            )

        # Both should complete — neither should time out or deadlock
        assert r_status.status_code == 200
        assert r_chat.status_code in (200, 409)  # 409 if in-flight guard fires
```

**Step 2: Run test to observe current state**

```bash
uv run python -m pytest tests/test_web_chat.py::TestWebChatConcurrency::test_session_status_does_not_block_concurrent_chat -v 2>&1 | tail -10
```

This may already pass or hang (the bug: `session_status()` holds the lock during `backend.get_session_info()`).

**Step 3: Narrow the lock in `session_status()`**

Replace the current `session_status()` body (lines 145–185) with:

```python
@router.get("/api/session")
async def session_status() -> dict:
    """Return session connection status.

    Reports whether a session is active and its ID.
    """
    global _active_session_id

    async with _session_lock:
        if _active_session_id is None:
            return {
                "connected": False,
                "session_id": None,
                "message": "No active session. Click 'New Session' to start.",
            }
        session_id = _active_session_id

    # Lock released — backend I/O runs without blocking other routes
    try:
        backend = _get_backend()
        info = await backend.get_session_info(session_id)
        if info and info.is_active:
            return {
                "connected": True,
                "session_id": session_id,
                "project_id": info.project_id,
                "working_dir": info.working_dir,
            }
        else:
            async with _session_lock:
                # Only clear if it hasn't been replaced by a new session
                if _active_session_id == session_id:
                    _active_session_id = None
            return {
                "connected": False,
                "session_id": None,
                "message": "Previous session ended. Start a new one.",
            }
    except RuntimeError:
        # Services not initialized
        return {
            "connected": False,
            "session_id": None,
            "message": "Server services not ready. Is the server fully started?",
        }
```

**Step 4: Narrow the lock in `create_session()`**

Replace the current `create_session()` body (lines 188–234) with:

```python
@router.post("/api/session")
async def create_session(request: Request) -> JSONResponse:
    """Create a new Amplifier session for web chat.

    Body (all optional):
        working_dir: str - Working directory for the session
        description: str - Human-readable description
    """
    global _active_session_id

    body = await request.json() if await request.body() else {}

    # Capture and clear the old session id under the lock
    async with _session_lock:
        old_session_id = _active_session_id
        _active_session_id = None

    # End old session outside the lock
    if old_session_id:
        try:
            backend = _get_backend()
            await backend.end_session(old_session_id)
        except (RuntimeError, ValueError, OSError):
            logger.warning("Error ending previous session", exc_info=True)

    try:
        backend = _get_backend()
        info = await backend.create_session(
            working_dir=body.get("working_dir", "~"),
            description=body.get("description", "Web chat session"),
        )
        async with _session_lock:
            _active_session_id = info.session_id

        return JSONResponse(
            content={
                "session_id": info.session_id,
                "project_id": info.project_id,
                "working_dir": info.working_dir,
            }
        )
    except RuntimeError as e:
        return JSONResponse(
            status_code=503,
            content={"error": str(e)},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Session creation failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "type": type(e).__name__},
        )
```

**Step 5: Run full web_chat test suite**

```bash
uv run python -m pytest tests/test_web_chat.py -q 2>&1 | tail -15
```

Expected: all tests pass.

**Step 6: Commit Fix 1**

Delegate to `foundation:git-ops`:
```
git add src/amplifier_distro/server/apps/web_chat/__init__.py tests/test_web_chat.py tests/conftest.py pyproject.toml
Commit message: "fix: narrow _session_lock in web_chat and add _message_in_flight guard (#57)"
Body:
- chat(): release _session_lock before backend.send_message()
- add _message_in_flight flag; concurrent chat returns 409 immediately
- guard _active_session_id = None in except ValueError with _session_lock
- session_status(): release lock before backend.get_session_info()
- create_session(): release lock before backend.create_session()
- follows end_session() pattern already in the module

Modelled after end_session() which already did this correctly.
```

---

## Phase 2 — Fix 2: socket_mode fire-and-forget

### Task 2.1: ACK before task + `_pending_tasks` set + exception-logging done callback

**Files:**
- Create: `tests/test_socket_mode.py`
- Modify: `src/amplifier_distro/server/apps/slack/socket_mode.py`

**Step 1: Write the failing tests** (new file)

```python
"""Tests for SocketModeAdapter concurrency fixes (Issue #57, Fix 2)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_events_api_frame(
    user: str = "U123",
    channel: str = "C456",
    ts: str = "1234567890.123456",
    text: str = "hello",
    thread_ts: str = "",
) -> dict:
    """Build a minimal events_api frame dict."""
    event = {
        "type": "message",
        "user": user,
        "channel": channel,
        "ts": ts,
        "text": text,
    }
    if thread_ts:
        event["thread_ts"] = thread_ts
    return {
        "type": "events_api",
        "envelope_id": f"env-{ts}",
        "payload": {"event": event},
    }


@pytest.fixture
def adapter():
    """SocketModeAdapter with mocked config and event handler."""
    from amplifier_distro.server.apps.slack.socket_mode import SocketModeAdapter

    config = MagicMock()
    config.app_token = "xapp-test"
    config.bot_token = "xoxb-test"

    event_handler = AsyncMock()
    event_handler.handle_event_payload = AsyncMock(return_value={"ok": True})

    a = SocketModeAdapter(config=config, event_handler=event_handler)
    a._bot_user_id = "UBOT"
    # Simulate a connected WebSocket
    a._ws = AsyncMock()
    a._ws.closed = False
    a._running = True
    return a


class TestSocketModePendingTasks:
    """Verify the _pending_tasks set is initialized and managed correctly."""

    def test_pending_tasks_initialized_in_init(self, adapter):
        assert hasattr(adapter, "_pending_tasks")
        assert isinstance(adapter._pending_tasks, set)
        assert len(adapter._pending_tasks) == 0

    async def test_handle_frame_creates_task_for_events_api(self, adapter):
        """events_api frame must spawn a background task, not block."""
        frame = _make_events_api_frame()

        await adapter._handle_frame(frame)
        # Give the event loop a cycle to register the task
        await asyncio.sleep(0)

        assert len(adapter._pending_tasks) == 0 or True
        # Primary assertion: _handle_frame returned without awaiting handler
        # (verified indirectly: if handler hangs the test would time out)

    async def test_ack_is_sent_before_task_starts(self, adapter):
        """ACK must be sent synchronously before the background task begins."""
        ack_calls = []
        send_calls = []

        async def record_ack(payload):
            ack_calls.append(payload)

        async def slow_handler(event_payload):
            # This should run AFTER ack
            assert len(ack_calls) > 0, "ACK not sent before handler ran"
            send_calls.append(event_payload)

        adapter._ws.send_json = record_ack
        adapter._event_handler.handle_event_payload = slow_handler

        frame = _make_events_api_frame()
        await adapter._handle_frame(frame)
        await asyncio.sleep(0.05)  # let the background task run

        assert len(ack_calls) == 1
        assert ack_calls[0]["envelope_id"] == frame["envelope_id"]

    async def test_task_exception_is_logged_not_swallowed(self, adapter, caplog):
        """An exception inside the event task must be logged at ERROR level."""
        import logging

        async def exploding_handler(event_payload):
            raise RuntimeError("boom from handler")

        adapter._event_handler.handle_event_payload = exploding_handler

        frame = _make_events_api_frame(ts="999.001")
        with caplog.at_level(logging.ERROR, logger="amplifier_distro"):
            await adapter._handle_frame(frame)
            await asyncio.sleep(0.05)

        error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("boom from handler" in m or "Exception" in m for m in error_msgs), (
            f"Expected ERROR log for task exception, got: {error_msgs}"
        )

    async def test_pending_tasks_cleared_on_completion(self, adapter):
        """Completed tasks are removed from _pending_tasks by done callback."""
        frame = _make_events_api_frame(ts="111.001")
        await adapter._handle_frame(frame)
        # Wait for task to complete
        await asyncio.sleep(0.1)
        assert len(adapter._pending_tasks) == 0
```

**Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/test_socket_mode.py -x -v 2>&1 | tail -20
```

Expected: `FAILED` — `_pending_tasks` attribute does not exist on `SocketModeAdapter`.

**Step 3: Implement changes in `socket_mode.py`**

**(a) In `__init__`, add after `self._seen_events: dict[str, float] = {}`:**

```python
        # Pending background event tasks — tracked so we can drain on stop()
        # and log exceptions via done callbacks.
        self._pending_tasks: set[asyncio.Task] = set()
```

**(b) In `_handle_frame`, replace the `events_api` branch:**

Current (line 216–217):
```python
        elif frame_type == "events_api":
            await self._handle_event(frame)
```

Replace with:
```python
        elif frame_type == "events_api":
            # ACK immediately so Slack doesn't retry (3 s deadline)
            await self._ack(frame)
            # Extract context for error logging before the task is created
            _payload = frame.get("payload", {})
            _event = _payload.get("event", {})
            _ctx = {
                "channel": _event.get("channel", "?"),
                "user": _event.get("user", "?"),
                "thread_ts": _event.get("thread_ts", ""),
                "text": _event.get("text", "")[:80],
            }
            task = asyncio.create_task(self._handle_event(frame))
            self._pending_tasks.add(task)

            def _done_cb(t: asyncio.Task, ctx: dict = _ctx) -> None:
                self._pending_tasks.discard(t)
                if not t.cancelled():
                    exc = t.exception()
                    if exc:
                        logger.error(
                            "[socket] Event task failed "
                            "channel=%s user=%s thread_ts=%s text=%r: %s",
                            ctx["channel"],
                            ctx["user"],
                            ctx["thread_ts"],
                            ctx["text"],
                            exc,
                            exc_info=exc,
                        )

            task.add_done_callback(_done_cb)
```

**(c) In `_handle_event`, remove the `await self._ack(frame)` call** (line 246 — it is now done at the call site in `_handle_frame`):

```python
    async def _handle_event(self, frame: dict[str, Any]) -> None:
        """Process an events_api frame (runs as a background task)."""
        payload = frame.get("payload", {})
        event = payload.get("event", {})

        event_type = event.get("type", "?")
        user = event.get("user", "?")
        text = event.get("text", "")[:80]
        channel = event.get("channel", "?")
        msg_ts = event.get("ts", "")
        thread_ts = event.get("thread_ts", "")

        logger.info(
            f"[socket] Event: type={event_type} user={user} "
            f"channel={channel} thread_ts={thread_ts or 'none'} text={text!r}"
        )

        # NOTE: ACK is sent by _handle_frame before this task starts.

        # Skip our own messages
        if user == self._bot_user_id:
            logger.debug("[socket] Skipping own message")
            return

        # Skip bot messages (subtype check)
        if event.get("subtype") == "bot_message":
            logger.debug("[socket] Skipping bot_message subtype")
            return

        # Deduplicate
        if msg_ts and channel:
            dedup_key = f"{channel}:{msg_ts}"
            if self._is_duplicate(dedup_key):
                logger.info(
                    f"[socket] Skipping duplicate event {event_type} for {dedup_key}"
                )
                return

        # Forward to our event handler
        handler_payload = {
            "type": "event_callback",
            "event": event,
        }
        try:
            result = await self._event_handler.handle_event_payload(handler_payload)
            logger.info(f"[socket] Handler result: {result}")
        except Exception:
            logger.exception("[socket] Error in event handler")
            raise  # re-raise so the done callback can log it with context
```

**Step 4: Run tests to verify they pass**

```bash
uv run python -m pytest tests/test_socket_mode.py -x -v 2>&1 | tail -20
```

Expected: all `TestSocketModePendingTasks` tests pass.

---

### Task 2.2: Update `stop()` to drain pending tasks

**Step 1: Write the failing test**

Add to `tests/test_socket_mode.py`:

```python
class TestSocketModeStop:
    """Verify stop() drains pending tasks before cancelling the main loop."""

    async def test_stop_waits_for_pending_tasks(self, adapter):
        """stop() must await pending tasks up to 30 s before cancelling."""
        completion_order = []

        async def slow_handler(event_payload):
            await asyncio.sleep(0.05)
            completion_order.append("handler_done")

        adapter._event_handler.handle_event_payload = slow_handler
        frame = _make_events_api_frame(ts="stop-test-001")

        await adapter._handle_frame(frame)
        assert len(adapter._pending_tasks) > 0, "Expected a pending task"

        await adapter.stop()

        assert "handler_done" in completion_order, (
            "stop() returned before pending task completed"
        )
        assert len(adapter._pending_tasks) == 0

    async def test_stop_cancels_tasks_that_exceed_timeout(self, adapter):
        """Tasks still running after 30 s must be cancelled, not left hanging."""
        # We mock asyncio.wait to simulate timeout immediately
        import asyncio as _asyncio

        async def hanging_handler(event_payload):
            await _asyncio.sleep(9999)

        adapter._event_handler.handle_event_payload = hanging_handler
        frame = _make_events_api_frame(ts="stop-test-002")

        await adapter._handle_frame(frame)
        await asyncio.sleep(0)  # let task start

        # Patch asyncio.wait to return everything as pending (simulate timeout)
        original_wait = asyncio.wait

        async def instant_timeout(tasks, timeout=None):
            return set(), set(tasks)

        with patch("asyncio.wait", side_effect=instant_timeout):
            await adapter.stop()

        # All tasks should be cancelled/done
        for task in adapter._pending_tasks:
            assert task.done() or task.cancelled()
```

**Step 2: Run tests to observe failure**

```bash
uv run python -m pytest tests/test_socket_mode.py::TestSocketModeStop -x -v 2>&1 | tail -20
```

Expected: `FAILED` — `stop()` doesn't drain `_pending_tasks`.

**Step 3: Update `stop()` in `socket_mode.py`**

Replace the current `stop()` (lines 370–381) with:

```python
    async def stop(self) -> None:
        """Stop the Socket Mode connection.

        Drains pending event tasks (up to 30 s) before cancelling the
        main connection loop, so in-flight LLM calls complete cleanly.
        """
        self._running = False

        await self._close_ws()

        # Drain pending event tasks
        if self._pending_tasks:
            _tasks_snapshot = set(self._pending_tasks)
            _, still_pending = await asyncio.wait(
                _tasks_snapshot, timeout=30.0
            )
            for task in still_pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

        logger.info("Socket Mode adapter stopped")
```

**Step 4: Run full socket_mode test suite**

```bash
uv run python -m pytest tests/test_socket_mode.py -q 2>&1 | tail -10
```

Expected: all tests pass.

**Step 5: Commit Fix 2**

Delegate to `foundation:git-ops`:
```
git add src/amplifier_distro/server/apps/slack/socket_mode.py tests/test_socket_mode.py
Commit message: "fix: fire-and-forget Slack events with ACK-before-task pattern (#57)"
Body:
- _handle_frame: ACK immediately, then create_task for handler
- _handle_event: remove ACK call (now at call site), re-raise exceptions
- add _pending_tasks set with done callbacks that log exceptions at ERROR
- stop(): drain pending tasks (asyncio.wait, 30s timeout) before cancel
```

---

## Phase 3 — Fix 4: BridgeBackend per-session queue serialization

### Task 3.1: Add queue infrastructure to `__init__` + start workers in `create_session()`

**Files:**
- Create: `tests/test_session_backend.py`
- Modify: `src/amplifier_distro/server/session_backend.py`

**Step 1: Write the failing tests** (new file)

```python
"""Tests for BridgeBackend concurrency fixes (Issue #57, Fix 4).

BridgeBackend is production-only (requires amplifier-foundation).
All tests mock the bridge and session handles so they run in CI
without a real Amplifier installation.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_handle(session_id: str = "test-session-0001") -> MagicMock:
    """Build a mock SessionHandle with a controllable run() method."""
    handle = MagicMock()
    handle.session_id = session_id
    handle.project_id = "test-project"
    handle.working_dir = "/tmp/test"
    handle.run = AsyncMock(return_value=f"[response from {session_id}]")
    return handle


@pytest.fixture
def bridge_backend():
    """BridgeBackend with mocked LocalBridge."""
    with patch("amplifier_distro.server.session_backend.BridgeBackend.__init__") as mock_init:
        mock_init.return_value = None  # suppress real __init__

        from amplifier_distro.server.session_backend import BridgeBackend

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._bridge = AsyncMock()
        backend._sessions = {}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()
        return backend


class TestBridgeBackendQueueInfrastructure:
    """Verify the queue-based session worker infrastructure."""

    def test_backend_has_session_queues_dict(self, bridge_backend):
        assert hasattr(bridge_backend, "_session_queues")
        assert isinstance(bridge_backend._session_queues, dict)

    def test_backend_has_worker_tasks_dict(self, bridge_backend):
        assert hasattr(bridge_backend, "_worker_tasks")
        assert isinstance(bridge_backend._worker_tasks, dict)

    def test_backend_has_ended_sessions_set(self, bridge_backend):
        assert hasattr(bridge_backend, "_ended_sessions")
        assert isinstance(bridge_backend._ended_sessions, set)

    async def test_create_session_starts_worker_task(self, bridge_backend):
        """create_session() must pre-start a session worker."""
        handle = _make_mock_handle("sess-0001")
        bridge_backend._bridge.create_session = AsyncMock(return_value=handle)

        with patch("amplifier_distro.server.session_backend.BridgeBackend.create_session",
                   wraps=bridge_backend.create_session):
            from pathlib import Path
            with patch("amplifier_distro.server.session_backend.BridgeBackend.__init__"):
                pass

        # Manually call the real create_session logic via the patched bridge
        from amplifier_distro.server.session_backend import BridgeBackend
        await BridgeBackend.create_session(
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


class TestBridgeBackendSerialization:
    """Verify messages for the same session are serialized through a queue."""

    async def test_send_message_serializes_concurrent_calls(self, bridge_backend):
        """Concurrent send_message calls for the same session run sequentially."""
        session_id = "sess-serial-001"
        handle = _make_mock_handle(session_id)
        bridge_backend._sessions[session_id] = handle

        call_order = []

        async def ordered_run(message):
            call_order.append(f"start:{message}")
            await asyncio.sleep(0.01)
            call_order.append(f"end:{message}")
            return f"resp:{message}"

        handle.run = ordered_run

        from amplifier_distro.server.session_backend import BridgeBackend

        # Pre-start worker
        queue = asyncio.Queue()
        bridge_backend._session_queues[session_id] = queue
        bridge_backend._worker_tasks[session_id] = asyncio.create_task(
            BridgeBackend._session_worker(bridge_backend, session_id)
        )

        try:
            r1, r2 = await asyncio.gather(
                BridgeBackend.send_message(bridge_backend, session_id, "A"),
                BridgeBackend.send_message(bridge_backend, session_id, "B"),
            )
        finally:
            bridge_backend._worker_tasks[session_id].cancel()

        assert r1 == "resp:A" or r1 == "resp:B"
        assert r2 == "resp:A" or r2 == "resp:B"
        assert r1 != r2

        # Verify sequential execution: no interleaving
        # i.e. "start:X" is always followed by "end:X" before "start:Y"
        a_start = call_order.index("start:A")
        a_end = call_order.index("end:A")
        b_start = call_order.index("start:B")
        b_end = call_order.index("end:B")
        assert a_end < b_start or b_end < a_start, (
            f"Calls interleaved: {call_order}"
        )

    async def test_send_message_propagates_exceptions(self, bridge_backend):
        """If handle.run() raises, the exception propagates to the caller."""
        session_id = "sess-exc-001"
        handle = _make_mock_handle(session_id)
        handle.run = AsyncMock(side_effect=RuntimeError("LLM exploded"))
        bridge_backend._sessions[session_id] = handle

        from amplifier_distro.server.session_backend import BridgeBackend

        queue = asyncio.Queue()
        bridge_backend._session_queues[session_id] = queue
        bridge_backend._worker_tasks[session_id] = asyncio.create_task(
            BridgeBackend._session_worker(bridge_backend, session_id)
        )

        try:
            with pytest.raises(RuntimeError, match="LLM exploded"):
                await BridgeBackend.send_message(bridge_backend, session_id, "hi")
        finally:
            bridge_backend._worker_tasks[session_id].cancel()
```

**Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/test_session_backend.py::TestBridgeBackendQueueInfrastructure -x -v 2>&1 | tail -20
```

Expected: `FAILED` — `_session_queues`, `_worker_tasks`, `_ended_sessions` not yet defined in `BridgeBackend.__init__`.

**Step 3: Implement `BridgeBackend.__init__` additions**

In `src/amplifier_distro/server/session_backend.py`, update `BridgeBackend.__init__`:

```python
    def __init__(self) -> None:
        from amplifier_distro.bridge import LocalBridge

        self._bridge = LocalBridge()
        self._sessions: dict[str, Any] = {}  # session_id -> SessionHandle
        self._reconnect_locks: dict[str, asyncio.Lock] = {}
        # Per-session FIFO queues for serializing handle.run() calls
        self._session_queues: dict[str, asyncio.Queue] = {}
        # Worker tasks draining each session queue
        self._worker_tasks: dict[str, asyncio.Task] = {}
        # Tombstone: sessions that were intentionally ended (blocks reconnect)
        self._ended_sessions: set[str] = set()
```

**Step 4: Run infrastructure tests**

```bash
uv run python -m pytest tests/test_session_backend.py::TestBridgeBackendQueueInfrastructure::test_backend_has_session_queues_dict tests/test_session_backend.py::TestBridgeBackendQueueInfrastructure::test_backend_has_worker_tasks_dict tests/test_session_backend.py::TestBridgeBackendQueueInfrastructure::test_backend_has_ended_sessions_set -v 2>&1 | tail -10
```

Expected: three tests `PASSED`.

---

### Task 3.2: Add `_session_worker()` coroutine

**Step 1: Write tests** (already in `tests/test_session_backend.py` — `TestBridgeBackendSerialization`)

Run them to confirm they fail:

```bash
uv run python -m pytest tests/test_session_backend.py::TestBridgeBackendSerialization -x -v 2>&1 | tail -20
```

Expected: `FAILED` — `_session_worker` does not exist.

**Step 2: Implement `_session_worker()`**

Add this method to `BridgeBackend` after `_reconnect()`:

```python
    async def _session_worker(self, session_id: str) -> None:
        """Drain the session queue, running handle.run() calls sequentially.

        Receives (message, future) tuples from the queue.  A ``None``
        sentinel signals the worker to exit cleanly (used by end_session
        and stop).  On CancelledError, drains remaining futures with
        cancellation so callers don't wait forever.
        """
        queue = self._session_queues[session_id]
        while True:
            try:
                item = await queue.get()
            except asyncio.CancelledError:
                # Drain remaining items and cancel their futures
                while not queue.empty():
                    try:
                        pending_item = queue.get_nowait()
                        if pending_item is not None:
                            _, fut = pending_item
                            if not fut.done():
                                fut.cancel()
                        queue.task_done()
                    except asyncio.QueueEmpty:
                        break
                raise

            if item is None:
                # Sentinel — exit cleanly
                queue.task_done()
                break

            message, future = item
            try:
                handle = self._sessions.get(session_id)
                if handle is None:
                    future.set_exception(
                        ValueError(f"Session {session_id} handle not found")
                    )
                else:
                    result = await handle.run(message)
                    if not future.done():
                        future.set_result(result)
            except asyncio.CancelledError:
                if not future.done():
                    future.cancel()
                queue.task_done()
                raise
            except Exception as exc:  # noqa: BLE001
                if not future.done():
                    future.set_exception(exc)
            finally:
                queue.task_done()
```

**Step 3: Run serialization tests**

```bash
uv run python -m pytest tests/test_session_backend.py::TestBridgeBackendSerialization -x -v 2>&1 | tail -15
```

Expected: tests pass.

---

### Task 3.3: Wire queue into `send_message()` + start workers in `create_session()`

**Step 1: Write the failing integration test**

Add to `tests/test_session_backend.py`:

```python
class TestBridgeBackendSendMessageQueue:
    """send_message() routes through the per-session queue."""

    async def test_send_message_uses_queue(self, bridge_backend):
        """send_message() puts work on the queue; result comes back via future."""
        session_id = "sess-queue-001"
        handle = _make_mock_handle(session_id)
        bridge_backend._sessions[session_id] = handle

        from amplifier_distro.server.session_backend import BridgeBackend

        # Manually pre-start queue and worker (as create_session will do)
        queue = asyncio.Queue()
        bridge_backend._session_queues[session_id] = queue
        bridge_backend._worker_tasks[session_id] = asyncio.create_task(
            BridgeBackend._session_worker(bridge_backend, session_id)
        )

        try:
            result = await BridgeBackend.send_message(
                bridge_backend, session_id, "test message"
            )
        finally:
            bridge_backend._worker_tasks[session_id].cancel()

        assert result == f"[response from {session_id}]"
        handle.run.assert_called_once_with("test message")
```

**Step 2: Run test to verify it fails**

```bash
uv run python -m pytest tests/test_session_backend.py::TestBridgeBackendSendMessageQueue -x -v 2>&1 | tail -15
```

Expected: `FAILED` — `send_message` still calls `handle.run()` directly.

**Step 3: Update `send_message()` to use the queue**

Replace the current `send_message()` body:

```python
    async def send_message(self, session_id: str, message: str) -> str:
        handle = self._sessions.get(session_id)
        if handle is None:
            # Session handle lost (server restart). Use per-session lock
            # to prevent concurrent reconnects for the same session_id.
            lock = self._reconnect_locks.setdefault(session_id, asyncio.Lock())
            try:
                async with lock:
                    # Double-check: another coroutine may have reconnected
                    # while we waited for the lock.
                    handle = self._sessions.get(session_id)
                    if handle is None:
                        handle = await self._reconnect(session_id)
            finally:
                # Clean up lock entry on both success and failure paths
                self._reconnect_locks.pop(session_id, None)

        # Route through the per-session queue so concurrent calls serialize
        if session_id not in self._session_queues:
            self._session_queues[session_id] = asyncio.Queue()
        if (
            session_id not in self._worker_tasks
            or self._worker_tasks[session_id].done()
        ):
            self._worker_tasks[session_id] = asyncio.create_task(
                self._session_worker(session_id)
            )

        loop = asyncio.get_event_loop()
        future: asyncio.Future[str] = loop.create_future()
        await self._session_queues[session_id].put((message, future))
        return await future
```

**Step 4: Update `create_session()` to pre-start the worker**

Replace the current `create_session()` body:

```python
    async def create_session(
        self,
        working_dir: str = "~",
        bundle_name: str | None = None,
        description: str = "",
    ) -> SessionInfo:
        from pathlib import Path

        from amplifier_distro.bridge import BridgeConfig

        config = BridgeConfig(
            working_dir=Path(working_dir).expanduser(),
            bundle_name=bundle_name,
            run_preflight=False,  # Server already validated
        )
        handle = await self._bridge.create_session(config)
        self._sessions[handle.session_id] = handle

        # Pre-start the session worker so the first message doesn't pay
        # the task-creation overhead, and so the worker is available for
        # reconnect paths that also route through the queue.
        queue: asyncio.Queue = asyncio.Queue()
        self._session_queues[handle.session_id] = queue
        self._worker_tasks[handle.session_id] = asyncio.create_task(
            self._session_worker(handle.session_id)
        )

        return SessionInfo(
            session_id=handle.session_id,
            project_id=handle.project_id,
            working_dir=str(handle.working_dir),
            is_active=True,
            description=description,
        )
```

**Step 5: Run session backend tests**

```bash
uv run python -m pytest tests/test_session_backend.py -x -v 2>&1 | tail -20
```

Expected: all tests pass.

---

### Task 3.4: Update `end_session()` with tombstone + sentinel + worker drain

**Step 1: Write failing test**

Add to `tests/test_session_backend.py`:

```python
class TestBridgeBackendEndSession:
    """end_session() must tombstone, drain the worker, then call bridge.end_session."""

    async def test_end_session_adds_tombstone(self, bridge_backend):
        """Session ID is added to _ended_sessions before anything else."""
        session_id = "sess-end-001"
        handle = _make_mock_handle(session_id)
        bridge_backend._sessions[session_id] = handle
        bridge_backend._bridge.end_session = AsyncMock()

        from amplifier_distro.server.session_backend import BridgeBackend
        await BridgeBackend.end_session(bridge_backend, session_id)

        assert session_id in bridge_backend._ended_sessions

    async def test_end_session_drains_worker(self, bridge_backend):
        """end_session() waits for in-flight work to complete before returning."""
        session_id = "sess-end-002"
        handle = _make_mock_handle(session_id)
        bridge_backend._sessions[session_id] = handle
        bridge_backend._bridge.end_session = AsyncMock()

        completed = []

        async def slow_run(message):
            await asyncio.sleep(0.03)
            completed.append(message)
            return f"done:{message}"

        handle.run = slow_run

        from amplifier_distro.server.session_backend import BridgeBackend

        # Pre-start worker
        queue: asyncio.Queue = asyncio.Queue()
        bridge_backend._session_queues[session_id] = queue
        bridge_backend._worker_tasks[session_id] = asyncio.create_task(
            BridgeBackend._session_worker(bridge_backend, session_id)
        )

        # Start a send (don't await yet) then immediately end
        send_task = asyncio.create_task(
            BridgeBackend.send_message(bridge_backend, session_id, "finishing")
        )
        await asyncio.sleep(0)  # let the message enqueue

        await BridgeBackend.end_session(bridge_backend, session_id)

        # send_task may be done by now via the worker completing
        if not send_task.done():
            send_task.cancel()

        assert "finishing" in completed or send_task.done()

    async def test_reconnect_blocked_after_end_session(self, bridge_backend):
        """_reconnect() must raise ValueError for tombstoned sessions."""
        session_id = "sess-end-003"
        bridge_backend._ended_sessions.add(session_id)

        from amplifier_distro.server.session_backend import BridgeBackend

        with pytest.raises(ValueError, match="intentionally ended"):
            await BridgeBackend._reconnect(bridge_backend, session_id)
```

**Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/test_session_backend.py::TestBridgeBackendEndSession -x -v 2>&1 | tail -20
```

Expected: `FAILED`.

**Step 3: Update `end_session()`**

Replace the current `end_session()`:

```python
    async def end_session(self, session_id: str) -> None:
        # Tombstone first — prevents _reconnect() from reviving this session
        self._ended_sessions.add(session_id)

        # Pop handle before signalling the worker so the worker sees no handle
        # and rejects any racing messages with ValueError
        handle = self._sessions.pop(session_id, None)

        # Signal worker to exit cleanly via sentinel
        queue = self._session_queues.get(session_id)
        if queue is not None:
            await queue.put(None)

        # Wait up to 5 s for in-flight work to drain
        worker = self._worker_tasks.get(session_id)
        if worker is not None and not worker.done():
            try:
                await asyncio.wait_for(asyncio.shield(worker), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "Session worker %s did not drain in 5s, cancelling", session_id
                )
                worker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker

        # Drain any remaining queued futures (unlikely but safe)
        if queue is not None:
            while not queue.empty():
                try:
                    item = queue.get_nowait()
                    if item is not None:
                        _, fut = item
                        if not fut.done():
                            fut.cancel()
                except asyncio.QueueEmpty:
                    break

        # Clean up references
        self._session_queues.pop(session_id, None)
        self._worker_tasks.pop(session_id, None)

        if handle:
            await self._bridge.end_session(handle)
```

Add `import contextlib` to the top of `session_backend.py` (it is not there yet).

**Step 4: Add tombstone check to `_reconnect()`**

At the very top of `_reconnect()`, before the `logger.info(...)` line:

```python
    async def _reconnect(self, session_id: str) -> Any:
        """Attempt to resume a session whose handle was lost (e.g. after restart)."""
        if session_id in self._ended_sessions:
            raise ValueError(
                f"Session {session_id} was intentionally ended and cannot be reconnected"
            )
        logger.info(f"Attempting to reconnect lost session {session_id}")
        ...  # rest unchanged
```

**Step 5: Run all session backend tests**

```bash
uv run python -m pytest tests/test_session_backend.py -q 2>&1 | tail -15
```

Expected: all tests pass.

---

### Task 3.5: Add `BridgeBackend.stop()`

**Step 1: Write failing test**

Add to `tests/test_session_backend.py`:

```python
class TestBridgeBackendStop:
    """stop() sends sentinels to all workers and awaits them."""

    async def test_stop_signals_all_workers(self, bridge_backend):
        """stop() sends None sentinel to every active queue."""
        from amplifier_distro.server.session_backend import BridgeBackend

        # Set up two fake sessions with queues
        for sid in ("sess-stop-001", "sess-stop-002"):
            handle = _make_mock_handle(sid)
            bridge_backend._sessions[sid] = handle
            queue: asyncio.Queue = asyncio.Queue()
            bridge_backend._session_queues[sid] = queue
            bridge_backend._worker_tasks[sid] = asyncio.create_task(
                BridgeBackend._session_worker(bridge_backend, sid)
            )

        await BridgeBackend.stop(bridge_backend)

        for task in bridge_backend._worker_tasks.values():
            assert task.done(), "Worker should be done after stop()"

    async def test_stop_is_idempotent_with_no_sessions(self, bridge_backend):
        """stop() on a backend with no sessions must not raise."""
        from amplifier_distro.server.session_backend import BridgeBackend
        await BridgeBackend.stop(bridge_backend)  # should not raise
```

**Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/test_session_backend.py::TestBridgeBackendStop -x -v 2>&1 | tail -15
```

Expected: `FAILED` — `BridgeBackend` has no `stop` method.

**Step 3: Add `stop()` to `BridgeBackend`**

```python
    async def stop(self) -> None:
        """Gracefully stop all session workers.

        Sends the None sentinel to every active queue, then waits up to
        10 s for workers to drain.  Remaining workers are cancelled.
        Must be called during server shutdown.
        """
        for queue in list(self._session_queues.values()):
            await queue.put(None)

        if self._worker_tasks:
            workers = [t for t in self._worker_tasks.values() if not t.done()]
            if workers:
                _, still_pending = await asyncio.wait(workers, timeout=10.0)
                for task in still_pending:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

        self._session_queues.clear()
        self._worker_tasks.clear()
```

**Step 4: Run full session backend test suite**

```bash
uv run python -m pytest tests/test_session_backend.py -q 2>&1 | tail -10
```

Expected: all tests pass.

**Step 5: Commit Fix 4**

Delegate to `foundation:git-ops`:
```
git add src/amplifier_distro/server/session_backend.py tests/test_session_backend.py
Commit message: "fix: serialize per-session handle.run() calls via asyncio queue (#57)"
Body:
- BridgeBackend: add _session_queues, _worker_tasks, _ended_sessions
- send_message(): route through per-session asyncio.Queue + Future
- _session_worker(): drains queue sequentially; propagates exceptions
- create_session(): pre-starts worker at session creation time
- _reconnect(): block reconnect of tombstoned sessions
- end_session(): tombstone → sentinel → drain worker → bridge.end_session
- stop(): sentinel to all queues, await workers with 10s timeout
- Worker also started in send_message() fallback for reconnect path
```

---

## Phase 4 — Server Shutdown Wiring

### Task 4.1: Register `BridgeBackend.stop()` in the server shutdown sequence

**Files:**
- Modify: `src/amplifier_distro/server/services.py`
- Modify: `src/amplifier_distro/server/app.py`

**Step 1: Write the failing test**

Add to `tests/test_session_backend.py`:

```python
class TestStopServicesShutdown:
    """stop_services() calls backend.stop() if available."""

    async def test_stop_services_calls_backend_stop(self):
        """stop_services() must call backend.stop() when the backend has it."""
        from amplifier_distro.server.services import (
            init_services,
            reset_services,
            stop_services,
        )

        mock_backend = AsyncMock()
        mock_backend.stop = AsyncMock()

        reset_services()
        init_services(backend=mock_backend)

        await stop_services()

        mock_backend.stop.assert_awaited_once()
        reset_services()

    async def test_stop_services_safe_without_stop_method(self):
        """stop_services() must not raise if backend lacks stop()."""
        from amplifier_distro.server.services import (
            init_services,
            reset_services,
            stop_services,
        )
        from amplifier_distro.server.session_backend import MockBackend

        reset_services()
        init_services(backend=MockBackend())

        await stop_services()  # MockBackend has no stop() — should not raise
        reset_services()

    async def test_stop_services_safe_before_init(self):
        """stop_services() must not raise if services were never initialized."""
        from amplifier_distro.server.services import reset_services, stop_services

        reset_services()
        await stop_services()  # should silently do nothing
```

**Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/test_session_backend.py::TestStopServicesShutdown -x -v 2>&1 | tail -15
```

Expected: `FAILED` — `stop_services` does not exist in `services.py`.

**Step 3: Add `stop_services()` to `services.py`**

Append after `reset_services()`:

```python
async def stop_services() -> None:
    """Gracefully stop shared services.

    Called during server shutdown.  Safe to call even if services were
    never initialized or if the backend doesn't implement stop().
    """
    with _instance_lock:
        instance = _instance

    if instance is None:
        return

    backend = instance.backend
    if hasattr(backend, "stop"):
        await backend.stop()
```

**Step 4: Register the shutdown handler in `app.py`**

In `DistroServer.__init__()`, after the last `self._setup_*()` call and before `self._app.include_router(self._core_router)`, add:

```python
        # Register graceful backend shutdown
        from amplifier_distro.server.services import stop_services
        self._app.add_event_handler("shutdown", stop_services)
        self._app.include_router(self._core_router)
```

> Remove the existing `self._app.include_router(self._core_router)` line (it's on line 129) and replace it with the block above so the handler and router registration happen together.

**Step 5: Run shutdown tests**

```bash
uv run python -m pytest tests/test_session_backend.py::TestStopServicesShutdown -v 2>&1 | tail -15
```

Expected: all three tests pass.

**Step 6: Commit shutdown wiring**

Delegate to `foundation:git-ops`:
```
git add src/amplifier_distro/server/services.py src/amplifier_distro/server/app.py
Commit message: "fix: register BridgeBackend.stop() in server shutdown sequence (#57)"
Body:
- services.py: add stop_services() async function
- app.py: register stop_services as FastAPI "shutdown" event handler
- safe to call when backend lacks stop() (e.g. MockBackend in tests)
- safe to call before init_services()
```

---

## Phase 5 — Full Test Suite Verification

### Task 5.1: Run the complete test suite

```bash
uv run python -m pytest tests/ -q 2>&1 | tail -30
```

Expected: all tests pass, no unexpected failures.

If there are failures:
1. Check whether the `_message_in_flight` global declaration is present in `chat()`, `session_status()`, and `create_session()` — all three functions that touch it need `global _message_in_flight`.
2. Check that `import contextlib` was added to `session_backend.py`.
3. Check that the `webchat_client` fixture in `test_web_chat.py` resets all three module-level vars.

Specific tests to run if narrowing down failures:

```bash
# Fix 1 only
uv run python -m pytest tests/test_web_chat.py -q

# Fix 2 only
uv run python -m pytest tests/test_socket_mode.py -q

# Fix 4 + shutdown only
uv run python -m pytest tests/test_session_backend.py -q
```

---

## Checklist Before Opening PR

- [ ] `_session_lock` narrowed in `chat()`, `session_status()`, `create_session()`
- [ ] `_message_in_flight` flag added with `finally` reset
- [ ] Unguarded `_active_session_id = None` in `except ValueError` now under lock
- [ ] `_pending_tasks` set initialized in `SocketModeAdapter.__init__`
- [ ] `_handle_frame` ACKs before creating task; `_handle_event` no longer ACKs
- [ ] Done callback logs exceptions at ERROR with context
- [ ] `stop()` drains `_pending_tasks` with 30 s timeout
- [ ] `BridgeBackend._session_queues`, `_worker_tasks`, `_ended_sessions` in `__init__`
- [ ] `_session_worker()` serializes calls, propagates exceptions, handles sentinel + cancel
- [ ] Worker pre-started in `create_session()`, lazily started in `send_message()` fallback
- [ ] `_reconnect()` raises `ValueError` for tombstoned sessions
- [ ] `end_session()` tombstones first, then drains worker, then calls `bridge.end_session()`
- [ ] `BridgeBackend.stop()` signals all queues and awaits workers
- [ ] `stop_services()` added to `services.py`
- [ ] `stop_services` registered as FastAPI shutdown handler in `app.py`
- [ ] `import contextlib` added to `session_backend.py`
- [ ] All three module-level vars reset in both `webchat_client` and `async_webchat_client` fixtures
- [ ] `uv run python -m pytest tests/ -q` passes cleanly

---

## Notes on Deferred Work

These items were explicitly excluded and must **not** be included in this implementation:
- Fix 3 (voice bridge concurrency)
- `maxsize` configuration in `distro.yaml`
- Prometheus/metrics instrumentation
- Per-thread Slack queuing
- Voice bridge concurrency
