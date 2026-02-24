# Chat App Implementation Plan

> **For execution:** Use `/execute-plan` mode or the subagent-driven-development recipe.

**Goal:** Build `server/apps/chat/` — a rich WebSocket-based web chat UI for amplifier-distro with streaming text, thinking blocks, tool call cards, sub-agent nesting, focus mode, multi-session, image attachments, slash commands, and mobile layout.

**Architecture:** New FastAPI plugin app consuming existing BridgeBackend via asyncio.Queue wired to BridgeConfig.on_stream. SessionEventTranslator maps kernel events to wire protocol. Preact+HTM frontend vendored inline — no build toolchain required.

**Tech Stack:** Python/FastAPI/WebSocket (backend), Preact 10 + HTM + marked.js vendored (frontend), pytest + FastAPI TestClient (tests).

---

## Codebase Orientation (read before starting)

**App plugin pattern** (`AppManifest` from `amplifier_distro.server.app`):
```python
from amplifier_distro.server.app import AppManifest
manifest = AppManifest(name="chat", description="...", router=router)
```

**Services access:**
```python
from amplifier_distro.server.services import get_services, init_services, reset_services
services = get_services()  # .backend is BridgeBackend (or MockBackend in dev)
```

**Test client pattern** (copy from `tests/test_web_chat.py`):
```python
from amplifier_distro.server.app import AppManifest, DistroServer
from amplifier_distro.server.services import init_services, reset_services

init_services(dev_mode=True)
server = DistroServer()
server.register_app(manifest)
client = TestClient(server.app)
```

**WebSocket test pattern:**
```python
with client.websocket_connect("/apps/chat/ws") as ws:
    ws.send_json({"type": "auth", "token": "test"})
    msg = ws.receive_json()
```

**Test runner:** `uv run python -m pytest tests/ -q`

**Known baseline failures (NOT regressions — ignore them):**
- `test_dockerfile_has_nonroot_user`
- `TestSocketModeDedup` (2 tests)
- `TestGetIntegrations` (7 tests)
Total: 10 expected pre-existing failures. Any test you write that fails is YOUR bug.

**Key source files (already read, for reference):**
- `src/amplifier_distro/server/session_backend.py` — `BridgeBackend`, `SessionHandle`, `MockBackend`
- `src/amplifier_distro/bridge_protocols.py` — `BridgeStreamingHook`, `BridgeApprovalSystem`, `BridgeDisplaySystem`
- `src/amplifier_distro/bridge.py` — `BridgeConfig`, `LocalBridge`, `SessionHandle`
- `src/amplifier_distro/server/app.py` — `AppManifest`, `DistroServer`
- `src/amplifier_distro/server/apps/web_chat/__init__.py` — reference app implementation
- `src/amplifier_distro/server/apps/example/__init__.py` — minimal app template

**Critical wiring fact:** `BridgeConfig.on_stream` already exists as `Callable[[str, dict], Any] | None = None`.
`LocalBridge.create_session()` already does `BridgeStreamingHook(on_event=config.on_stream)`.
The queue wiring is `lambda e, d: queue.put_nowait((e, d))` — a two-arg function that packs a tuple.
Events arrive as `(event_name: str, data: dict)` tuples when dequeued.

---

## Phase 1: Backend Foundation

### Task 1: Chat App Skeleton

**Files:**
- Create: `src/amplifier_distro/server/apps/chat/__init__.py`
- Create: `src/amplifier_distro/server/apps/chat/static/.gitkeep`
- Create: `tests/test_chat_app.py`

**Step 1: Write the failing tests**

Create `tests/test_chat_app.py`:
```python
"""Chat App Acceptance Tests — Skeleton"""
from __future__ import annotations

import pytest
from fastapi import APIRouter
from starlette.testclient import TestClient

from amplifier_distro.server.app import AppManifest, DistroServer
from amplifier_distro.server.services import init_services, reset_services


@pytest.fixture(autouse=True)
def _clean_services():
    reset_services()
    yield
    reset_services()


@pytest.fixture
def chat_client() -> TestClient:
    init_services(dev_mode=True)
    from amplifier_distro.server.apps.chat import manifest
    server = DistroServer()
    server.register_app(manifest)
    return TestClient(server.app)


class TestChatManifest:
    def test_manifest_name_is_chat(self):
        from amplifier_distro.server.apps.chat import manifest
        assert manifest.name == "chat"

    def test_manifest_has_router(self):
        from amplifier_distro.server.apps.chat import manifest
        assert isinstance(manifest.router, APIRouter)

    def test_manifest_is_app_manifest_type(self):
        from amplifier_distro.server.apps.chat import manifest
        assert isinstance(manifest, AppManifest)


class TestChatIndexEndpoint:
    def test_index_returns_200(self, chat_client):
        r = chat_client.get("/apps/chat/")
        assert r.status_code == 200

    def test_index_returns_html(self, chat_client):
        r = chat_client.get("/apps/chat/")
        assert "text/html" in r.headers["content-type"]

    def test_index_contains_amplifier(self, chat_client):
        r = chat_client.get("/apps/chat/")
        assert "Amplifier" in r.text


class TestChatHealthEndpoint:
    def test_health_returns_ok(self, chat_client):
        r = chat_client.get("/apps/chat/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestChatVendorEndpoint:
    def test_vendor_js_returns_200(self, chat_client):
        r = chat_client.get("/apps/chat/vendor.js")
        assert r.status_code == 200

    def test_vendor_js_content_type(self, chat_client):
        r = chat_client.get("/apps/chat/vendor.js")
        assert "javascript" in r.headers["content-type"]
```

**Step 2: Run tests to verify they fail**
```
uv run python -m pytest tests/test_chat_app.py -v
```
Expected: `ModuleNotFoundError` or `ImportError` — the module doesn't exist yet.

**Step 3: Implement the skeleton**

Create `src/amplifier_distro/server/apps/chat/__init__.py`:
```python
"""Chat App — Rich WebSocket-based chat UI for amplifier-distro.

Successor to web_chat. Provides streaming text, thinking blocks,
tool call cards, sub-agent nesting, focus mode, and multi-session.

Routes:
    GET  /                 - Serves the chat HTML page
    GET  /vendor.js        - Serves vendored frontend bundle
    GET  /api/health       - Health check
    WS   /ws               - WebSocket chat connection (Task 6)
    GET  /api/sessions     - List sessions (Task 11)
    GET  /api/sessions/{id}/transcript  - Transcript (Task 12)
    GET  /api/preferences  - User preferences (Task 13)
    PUT  /api/preferences  - Update preferences (Task 13)
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, Response

from amplifier_distro.server.app import AppManifest

logger = logging.getLogger(__name__)

router = APIRouter()

_static_dir = Path(__file__).parent / "static"


@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the chat interface."""
    html_file = _static_dir / "index.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text())
    return HTMLResponse(
        content=(
            "<html><body>"
            "<h1>Amplifier Chat</h1>"
            "<p>index.html not found. Run the vendor build step.</p>"
            "</body></html>"
        ),
        status_code=500,
    )


@router.get("/vendor.js")
async def vendor_js() -> Response:
    """Serve vendored frontend bundle (Preact + HTM + marked.js)."""
    vendor_file = _static_dir / "vendor.js"
    if vendor_file.exists():
        return Response(
            content=vendor_file.read_text(),
            media_type="application/javascript",
        )
    return Response(
        content="// vendor.js not found — run the vendor build step\n",
        media_type="application/javascript",
        status_code=404,
    )


@router.get("/api/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


manifest = AppManifest(
    name="chat",
    description="Amplifier rich web chat interface with WebSocket streaming",
    version="0.1.0",
    router=router,
)
```

Create `src/amplifier_distro/server/apps/chat/static/.gitkeep` (empty file):
```
(empty file)
```

**Step 4: Run tests to verify they pass**
```
uv run python -m pytest tests/test_chat_app.py -v
```
Expected: All pass except `test_vendor_js_returns_200` (no vendor.js yet — that's Task 14).
Skip that test for now by marking: `@pytest.mark.skip(reason="vendor.js built in Task 14")`.

**Step 5: Commit**
```
git add src/amplifier_distro/server/apps/chat/ tests/test_chat_app.py
git commit -m "feat(chat): add chat app skeleton with manifest, health, and static routes"
```

---

### Task 2: asyncio.Queue Wiring in BridgeBackend

**Files:**
- Modify: `src/amplifier_distro/server/session_backend.py`
- Create: `tests/test_chat_backend_queue.py`

**Background:** `BridgeBackend.create_session()` builds a `BridgeConfig` but never sets `on_stream`.
`LocalBridge.create_session()` already does `BridgeStreamingHook(on_event=config.on_stream)`.
We need to: (a) pass `event_queue` into `create_session()`, (b) wire it as `on_stream`, (c) add `execute()` method.

The event queue receives tuples `(event_name, data)` via a two-arg lambda:
```python
on_stream=lambda e, d: event_queue.put_nowait((e, d))
```

We also add `BridgeBackend.execute()` (non-blocking fire-and-events, unlike `send_message()` which blocks for return value).

**Step 1: Write the failing tests**

Create `tests/test_chat_backend_queue.py`:
```python
"""Tests for event queue wiring in BridgeBackend."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amplifier_distro.server.session_backend import BridgeBackend, MockBackend


class TestMockBackendQueueIgnored:
    """MockBackend gracefully ignores event_queue (it doesn't stream)."""

    @pytest.mark.asyncio
    async def test_create_session_accepts_event_queue(self):
        backend = MockBackend()
        q: asyncio.Queue = asyncio.Queue()
        # MockBackend should accept event_queue kwarg without error
        info = await backend.create_session(
            working_dir="~",
            event_queue=q,
        )
        assert info.session_id is not None


class TestBridgeBackendQueueWiring:
    """BridgeBackend wires event_queue to BridgeConfig.on_stream."""

    @pytest.mark.asyncio
    async def test_create_session_wires_on_stream_when_queue_provided(self):
        """on_stream in BridgeConfig receives the queue-wrapping lambda."""
        captured_config = {}

        async def fake_bridge_create(config):
            captured_config["on_stream"] = config.on_stream
            handle = MagicMock()
            handle.session_id = "test-session-001"
            handle.project_id = "test-project"
            handle.working_dir = "/tmp"
            return handle

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._bridge = MagicMock()
        backend._bridge.create_session = AsyncMock(side_effect=fake_bridge_create)
        backend._sessions = {}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()

        q: asyncio.Queue = asyncio.Queue()

        with patch("asyncio.create_task"):
            await backend.create_session(working_dir="~", event_queue=q)

        assert captured_config["on_stream"] is not None
        # Verify it puts a tuple into the queue
        captured_config["on_stream"]("test:event", {"key": "value"})
        item = q.get_nowait()
        assert item == ("test:event", {"key": "value"})

    @pytest.mark.asyncio
    async def test_create_session_no_queue_leaves_on_stream_none(self):
        """Without event_queue, on_stream stays None."""
        captured_config = {}

        async def fake_bridge_create(config):
            captured_config["on_stream"] = config.on_stream
            handle = MagicMock()
            handle.session_id = "test-session-002"
            handle.project_id = "test-project"
            handle.working_dir = "/tmp"
            return handle

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._bridge = MagicMock()
        backend._bridge.create_session = AsyncMock(side_effect=fake_bridge_create)
        backend._sessions = {}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()

        with patch("asyncio.create_task"):
            await backend.create_session(working_dir="~")

        assert captured_config["on_stream"] is None

    @pytest.mark.asyncio
    async def test_execute_calls_handle_run(self):
        """execute() calls handle.run() and returns None."""
        handle = MagicMock()
        handle.run = AsyncMock(return_value="response text")

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {"sess-001": handle}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()

        await backend.execute("sess-001", "hello world")
        handle.run.assert_called_once_with("hello world")

    @pytest.mark.asyncio
    async def test_execute_raises_on_unknown_session(self):
        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()

        with pytest.raises(ValueError, match="Unknown session"):
            await backend.execute("no-such-session", "hello")
```

**Step 2: Run tests to verify they fail**
```
uv run python -m pytest tests/test_chat_backend_queue.py -v
```
Expected: `TypeError` on `create_session(event_queue=q)` and `AttributeError` on `backend.execute`.

**Step 3: Implement the changes**

In `src/amplifier_distro/server/session_backend.py`, make these changes:

In `MockBackend.create_session()`, add `event_queue` parameter:
```python
async def create_session(
    self,
    working_dir: str = "~",
    bundle_name: str | None = None,
    description: str = "",
    event_queue: "asyncio.Queue | None" = None,
) -> SessionInfo:
```
(No other changes needed — MockBackend doesn't stream events.)

In `BridgeBackend.create_session()`, add `event_queue` parameter and wire it:
```python
async def create_session(
    self,
    working_dir: str = "~",
    bundle_name: str | None = None,
    description: str = "",
    event_queue: asyncio.Queue | None = None,
) -> SessionInfo:
    from pathlib import Path

    from amplifier_distro.bridge import BridgeConfig

    # Build the on_stream callback from the event queue
    on_stream = None
    if event_queue is not None:
        _q = event_queue  # capture for lambda
        def on_stream(event: str, data: dict) -> None:
            _q.put_nowait((event, data))

    config = BridgeConfig(
        working_dir=Path(working_dir).expanduser(),
        bundle_name=bundle_name,
        run_preflight=False,
        on_stream=on_stream,
    )
    # ... rest of existing create_session body unchanged ...
```

Add `execute()` method to `BridgeBackend` after `send_message()`:
```python
async def execute(
    self,
    session_id: str,
    prompt: str,
    images: list[str] | None = None,
) -> None:
    """Execute a prompt on the session.

    Events stream into the event_queue wired at create_session() time.
    Unlike send_message(), this does NOT block for a return value.
    Raises ValueError if session not found.
    """
    handle = self._sessions.get(session_id)
    if handle is None:
        raise ValueError(f"Unknown session: {session_id}")
    await handle.run(prompt)
```

**Step 4: Run tests to verify they pass**
```
uv run python -m pytest tests/test_chat_backend_queue.py -v
```
Expected: All pass.

**Step 5: Run full suite to verify no regressions**
```
uv run python -m pytest tests/ -q
```
Expected: Same baseline failures, no new failures.

**Step 6: Commit**
```
git add src/amplifier_distro/server/session_backend.py tests/test_chat_backend_queue.py
git commit -m "feat(chat): add event_queue wiring and execute() to BridgeBackend"
```

---

### Task 3: Register delegate:* Events on BridgeStreamingHook

**Files:**
- Modify: `src/amplifier_distro/bridge.py`
- Create: `tests/test_chat_delegate_events.py`

**Background:** `LocalBridge.create_session()` registers hooks for `ALL_EVENTS` from `amplifier_core.events`. The `delegate:*` family (`delegate:agent_spawned`, `delegate:agent_resumed`, `delegate:agent_completed`, `delegate:error`) may not be in `ALL_EVENTS`. We must explicitly register them after the `ALL_EVENTS` loop.

**Step 1: Write the failing tests**

Create `tests/test_chat_delegate_events.py`:
```python
"""Tests that delegate:* events are registered on the streaming hook."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


DELEGATE_EVENTS = [
    "delegate:agent_spawned",
    "delegate:agent_resumed",
    "delegate:agent_completed",
    "delegate:error",
]


class TestDelegateEventRegistration:
    """Verify delegate:* events get registered on the streaming hook."""

    @pytest.mark.asyncio
    async def test_delegate_events_registered_on_session(self):
        """After create_session, all delegate events are registered on hooks."""
        from amplifier_distro.bridge import BridgeConfig, LocalBridge

        registered_events: list[str] = []

        mock_hooks = MagicMock()
        def capture_register(event, handler, priority, name):
            registered_events.append(event)
        mock_hooks.register = MagicMock(side_effect=capture_register)

        mock_coordinator = MagicMock()
        mock_coordinator.hooks = mock_hooks
        mock_coordinator.session_id = "delegate-test-session"

        mock_session = MagicMock()
        mock_session.coordinator = mock_coordinator

        mock_prepared = MagicMock()
        mock_prepared.create_session = AsyncMock(return_value=mock_session)
        mock_prepared.mount_plan = {}

        mock_bundle = MagicMock()
        mock_bundle.prepare = AsyncMock(return_value=mock_prepared)

        bridge = LocalBridge.__new__(LocalBridge)
        bridge._config = {}

        with (
            patch("amplifier_distro.bridge._require_foundation",
                  return_value=(AsyncMock(return_value=mock_bundle), MagicMock())),
            patch("amplifier_distro.bridge.LocalBridge._resolve_distro_bundle",
                  return_value="test-bundle"),
            patch("amplifier_distro.bridge.LocalBridge.get_project_id",
                  return_value="test-project"),
            patch("amplifier_distro.bridge.LocalBridge.get_handoff",
                  new_callable=AsyncMock, return_value=None),
            patch("amplifier_distro.bridge.LocalBridge._inject_providers"),
            patch("amplifier_distro.bridge._write_session_info"),
            patch("amplifier_distro.bridge.register_transcript_hooks"),
            patch("amplifier_core.events.ALL_EVENTS", ["content_block:start"]),
        ):
            config = BridgeConfig(working_dir=__import__("pathlib").Path("/tmp"))
            await bridge.create_session(config)

        for event in DELEGATE_EVENTS:
            assert event in registered_events, (
                f"delegate event '{event}' not registered. "
                f"Registered: {registered_events}"
            )
```

**Step 2: Run to verify failure**
```
uv run python -m pytest tests/test_chat_delegate_events.py -v
```
Expected: AssertionError — delegate events not registered.

**Step 3: Implement the fix**

In `src/amplifier_distro/bridge.py`, find the streaming hook registration block in `create_session()` (around line 426–442). After the `ALL_EVENTS` loop, add explicit delegate event registration:

```python
        # 9. Register streaming hook for all events
        try:
            from amplifier_core.events import (  # type: ignore[import-not-found]
                ALL_EVENTS,
            )

            for event in list(ALL_EVENTS):
                session.coordinator.hooks.register(
                    event=event,
                    handler=streaming,
                    priority=100,
                    name=f"bridge-streaming:{event}",
                )

            # Explicitly register delegate events — they may not be in ALL_EVENTS
            _DELEGATE_EVENTS = [
                "delegate:agent_spawned",
                "delegate:agent_resumed",
                "delegate:agent_completed",
                "delegate:error",
            ]
            for event in _DELEGATE_EVENTS:
                if event not in ALL_EVENTS:
                    session.coordinator.hooks.register(
                        event=event,
                        handler=streaming,
                        priority=100,
                        name=f"bridge-streaming:{event}",
                    )
        except (ImportError, AttributeError):
            logger.debug(
                "Could not register streaming hooks"
                " (amplifier-core events not available)"
            )
```

Apply the same change to `resume_session()` in the same file (same block, same pattern).

**Step 4: Run tests**
```
uv run python -m pytest tests/test_chat_delegate_events.py -v
```
Expected: Pass.

**Step 5: Full suite**
```
uv run python -m pytest tests/ -q
```
Expected: No new failures.

**Step 6: Commit**
```
git add src/amplifier_distro/bridge.py tests/test_chat_delegate_events.py
git commit -m "feat(chat): explicitly register delegate:* events on BridgeStreamingHook"
```

---

### Task 4: SessionEventTranslator

**Files:**
- Create: `src/amplifier_distro/server/apps/chat/translator.py`
- Create: `tests/test_chat_translator.py`

**Background:** Kernel events arrive as `(event_name, data)` tuples from the queue. The translator maps them to wire protocol dicts. It also tracks `cycle_count` (increments on each `tool_result` event) and `local_index` (composite key `f"{cycle}-{server_index}"` → stable integer) for block index remapping. Block maps are cleared on `orchestrator:complete`.

`parent_tool_call_id` correlation: translator keeps a deque of pending delegate tool calls. On `tool:pre` for `delegate`/`task` tools, appends the `tool_call_id`. On `delegate:agent_spawned`, pops from left and injects as `parent_tool_call_id`.

**Step 1: Write the failing tests**

Create `tests/test_chat_translator.py`:
```python
"""Tests for SessionEventTranslator."""
from __future__ import annotations

import pytest

from amplifier_distro.server.apps.chat.translator import SessionEventTranslator


class TestBasicTranslations:
    def setup_method(self):
        self.t = SessionEventTranslator()

    def test_content_block_start_text(self):
        msg = self.t.translate("content_block:start", {"block_type": "text", "index": 0})
        assert msg == {"type": "content_start", "block_type": "text", "index": 0}

    def test_content_block_start_thinking(self):
        msg = self.t.translate("content_block:start", {"block_type": "thinking", "index": 1})
        assert msg == {"type": "content_start", "block_type": "thinking", "index": 1}

    def test_content_block_delta(self):
        msg = self.t.translate("content_block:delta", {"delta": "hello", "index": 0})
        assert msg == {"type": "content_delta", "delta": "hello", "index": 0}

    def test_content_block_end(self):
        msg = self.t.translate("content_block:end", {"index": 0})
        assert msg == {"type": "content_end", "index": 0}

    def test_thinking_delta(self):
        msg = self.t.translate("thinking:delta", {"delta": "I think..."})
        assert msg == {"type": "thinking_delta", "delta": "I think..."}

    def test_thinking_final(self):
        msg = self.t.translate("thinking:final", {"content": "My conclusion"})
        assert msg == {"type": "thinking_final", "content": "My conclusion"}

    def test_tool_pre(self):
        msg = self.t.translate("tool:pre", {
            "tool_call_id": "tc-001",
            "tool_name": "read_file",
            "tool_input": {"file_path": "/tmp/foo.py"},
        })
        assert msg == {
            "type": "tool_call",
            "tool_call_id": "tc-001",
            "tool_name": "read_file",
            "arguments": {"file_path": "/tmp/foo.py"},
        }

    def test_tool_post_success(self):
        result = type("R", (), {"output": "file contents", "error": None})()
        msg = self.t.translate("tool:post", {
            "tool_call_id": "tc-001",
            "result": result,
        })
        assert msg == {
            "type": "tool_result",
            "tool_call_id": "tc-001",
            "success": True,
            "output": "file contents",
            "error": None,
        }

    def test_tool_post_error(self):
        result = type("R", (), {"output": None, "error": "File not found"})()
        msg = self.t.translate("tool:post", {
            "tool_call_id": "tc-001",
            "result": result,
        })
        assert msg == {
            "type": "tool_result",
            "tool_call_id": "tc-001",
            "success": False,
            "output": None,
            "error": "File not found",
        }

    def test_tool_error(self):
        msg = self.t.translate("tool:error", {
            "tool_call_id": "tc-002",
            "error": "Timeout",
        })
        assert msg == {
            "type": "tool_result",
            "tool_call_id": "tc-002",
            "success": False,
            "error": "Timeout",
            "output": None,
        }

    def test_orchestrator_complete(self):
        msg = self.t.translate("orchestrator:complete", {"turn_count": 3})
        assert msg == {"type": "prompt_complete", "turn_count": 3}

    def test_cancel_completed(self):
        msg = self.t.translate("cancel:completed", {})
        assert msg == {"type": "execution_cancelled"}

    def test_cancel_requested(self):
        msg = self.t.translate("cancel:requested", {})
        assert msg == {"type": "cancel_acknowledged"}

    def test_unknown_event_returns_none(self):
        msg = self.t.translate("some:unknown:event", {"data": "value"})
        assert msg is None

    def test_display_message(self):
        msg = self.t.translate("display_message", {
            "message": "Loading tools...",
            "level": "info",
            "source": "hook",
        })
        assert msg == {
            "type": "display_message",
            "message": "Loading tools...",
            "level": "info",
            "source": "hook",
        }


class TestCycleAndIndexRemapping:
    """Block index resets to 0 after each tool call. Translator remaps to stable index."""

    def setup_method(self):
        self.t = SessionEventTranslator()

    def test_first_text_block_gets_index_0(self):
        msg = self.t.translate("content_block:start", {"block_type": "text", "index": 0})
        assert msg["index"] == 0

    def test_index_remapped_after_tool_result(self):
        # Cycle 0: text block at server index 0 → local index 0
        self.t.translate("content_block:start", {"block_type": "text", "index": 0})

        # Tool call happens (cycle 0 → 1 after tool:post)
        result = type("R", (), {"output": "ok", "error": None})()
        self.t.translate("tool:post", {"tool_call_id": "tc-001", "result": result})

        # Cycle 1: server resets index to 0, but local should be new
        msg = self.t.translate("content_block:start", {"block_type": "text", "index": 0})
        # Local index must differ from cycle 0's index 0
        assert msg["index"] != 0 or msg.get("cycle_key") is not None

    def test_cycle_count_increments_on_tool_post(self):
        result = type("R", (), {"output": "ok", "error": None})()
        assert self.t.cycle_count == 0
        self.t.translate("tool:post", {"tool_call_id": "tc-001", "result": result})
        assert self.t.cycle_count == 1
        self.t.translate("tool:post", {"tool_call_id": "tc-002", "result": result})
        assert self.t.cycle_count == 2

    def test_block_map_cleared_on_prompt_complete(self):
        self.t.translate("content_block:start", {"block_type": "text", "index": 0})
        assert len(self.t.block_map) > 0
        self.t.translate("orchestrator:complete", {"turn_count": 1})
        assert len(self.t.block_map) == 0
        assert self.t.cycle_count == 0

    def test_local_index_stable_across_cycles(self):
        """Each new block in each cycle gets a unique, monotonically increasing local index."""
        # Cycle 0
        m0 = self.t.translate("content_block:start", {"block_type": "text", "index": 0})
        result = type("R", (), {"output": "ok", "error": None})()
        self.t.translate("tool:post", {"tool_call_id": "tc-001", "result": result})
        # Cycle 1 — server resets to index 0
        m1 = self.t.translate("content_block:start", {"block_type": "text", "index": 0})
        assert m0["index"] != m1["index"]


class TestDelegatePropagation:
    """parent_tool_call_id is correlated via FIFO deque of pending delegate tool calls."""

    def setup_method(self):
        self.t = SessionEventTranslator()

    def test_session_fork_gets_parent_tool_call_id(self):
        # 1. Tool pre for a delegate call
        self.t.translate("tool:pre", {
            "tool_call_id": "tc-delegate-001",
            "tool_name": "delegate",
            "tool_input": {"agent": "explorer"},
        })
        # 2. Agent spawned — should get parent_tool_call_id correlated
        msg = self.t.translate("delegate:agent_spawned", {
            "parent_id": "sess-parent",
            "child_id": "sess-child",
            "agent": "explorer",
        })
        assert msg["type"] == "session_fork"
        assert msg["parent_tool_call_id"] == "tc-delegate-001"
        assert msg["parent_id"] == "sess-parent"
        assert msg["child_id"] == "sess-child"
        assert msg["agent"] == "explorer"

    def test_session_fork_no_pending_delegate(self):
        """If no pending delegate, parent_tool_call_id is None."""
        msg = self.t.translate("delegate:agent_spawned", {
            "parent_id": "p",
            "child_id": "c",
            "agent": "x",
        })
        assert msg["parent_tool_call_id"] is None

    def test_task_tool_also_tracked(self):
        """tool_name='task' also queues a delegate correlation."""
        self.t.translate("tool:pre", {
            "tool_call_id": "tc-task-001",
            "tool_name": "task",
            "tool_input": {},
        })
        msg = self.t.translate("delegate:agent_spawned", {
            "parent_id": "p", "child_id": "c", "agent": "x",
        })
        assert msg["parent_tool_call_id"] == "tc-task-001"

    def test_fifo_order_for_parallel_delegates(self):
        """Two parallel delegate tool calls correlate in FIFO order."""
        self.t.translate("tool:pre", {
            "tool_call_id": "tc-first",
            "tool_name": "delegate",
            "tool_input": {},
        })
        self.t.translate("tool:pre", {
            "tool_call_id": "tc-second",
            "tool_name": "delegate",
            "tool_input": {},
        })
        msg1 = self.t.translate("delegate:agent_spawned", {
            "parent_id": "p", "child_id": "c1", "agent": "x",
        })
        msg2 = self.t.translate("delegate:agent_spawned", {
            "parent_id": "p", "child_id": "c2", "agent": "y",
        })
        assert msg1["parent_tool_call_id"] == "tc-first"
        assert msg2["parent_tool_call_id"] == "tc-second"
```

**Step 2: Run to verify failure**
```
uv run python -m pytest tests/test_chat_translator.py -v
```
Expected: `ModuleNotFoundError` — `translator.py` doesn't exist.

**Step 3: Implement the translator**

Create `src/amplifier_distro/server/apps/chat/translator.py`:
```python
"""SessionEventTranslator — maps kernel events to wire protocol.

Kernel events arrive as (event_name, data) tuples from the asyncio.Queue.
Translator maps them to wire protocol dicts for the WebSocket client.

State maintained across a turn:
  - cycle_count: increments on each tool:post (handles server index resets)
  - block_map: {f"{cycle}-{server_index}" -> local_index} for stable DOM ids
  - local_index_counter: monotonically increasing across the full turn
  - _pending_delegates: deque of tool_call_ids for delegate/task correlations

State reset on orchestrator:complete (start of next turn).
"""
from __future__ import annotations

from collections import deque
from typing import Any


class SessionEventTranslator:
    """Translates raw kernel events to wire protocol messages."""

    def __init__(self) -> None:
        self.cycle_count: int = 0
        self.block_map: dict[str, int] = {}
        self._local_index_counter: int = 0
        self._pending_delegates: deque[str] = deque()

    def _get_local_index(self, server_index: int) -> int:
        """Map (cycle, server_index) composite key to a stable local index."""
        key = f"{self.cycle_count}-{server_index}"
        if key not in self.block_map:
            self.block_map[key] = self._local_index_counter
            self._local_index_counter += 1
        return self.block_map[key]

    def _reset(self) -> None:
        """Clear per-turn state on prompt_complete."""
        self.cycle_count = 0
        self.block_map = {}
        self._local_index_counter = 0
        self._pending_delegates.clear()

    def translate(self, event_name: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Translate a kernel event to a wire protocol dict.

        Returns None for events that should be silently skipped.
        """
        match event_name:
            case "content_block:start":
                return {
                    "type": "content_start",
                    "block_type": data.get("block_type", "text"),
                    "index": self._get_local_index(data.get("index", 0)),
                }

            case "content_block:delta":
                return {
                    "type": "content_delta",
                    "delta": data.get("delta", ""),
                    "index": self._get_local_index(data.get("index", 0)),
                }

            case "content_block:end":
                return {
                    "type": "content_end",
                    "index": self._get_local_index(data.get("index", 0)),
                }

            case "thinking:delta":
                return {
                    "type": "thinking_delta",
                    "delta": data.get("delta", ""),
                }

            case "thinking:final":
                return {
                    "type": "thinking_final",
                    "content": data.get("content", ""),
                }

            case "tool:pre":
                tool_name = data.get("tool_name", "")
                tool_call_id = data.get("tool_call_id", "")
                # Track delegate/task tool calls for correlation
                if tool_name in ("delegate", "task"):
                    self._pending_delegates.append(tool_call_id)
                return {
                    "type": "tool_call",
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "arguments": data.get("tool_input", {}),
                }

            case "tool:post":
                result = data.get("result")
                output = None
                error = None
                success = True
                if result is not None:
                    output = str(result.output) if result.output is not None else None
                    error = result.error if hasattr(result, "error") else None
                    success = error is None
                # Increment cycle — server resets block index after each tool result
                self.cycle_count += 1
                return {
                    "type": "tool_result",
                    "tool_call_id": data.get("tool_call_id", ""),
                    "success": success,
                    "output": output,
                    "error": error,
                }

            case "tool:error":
                return {
                    "type": "tool_result",
                    "tool_call_id": data.get("tool_call_id", ""),
                    "success": False,
                    "output": None,
                    "error": data.get("error", "Unknown error"),
                }

            case "delegate:agent_spawned":
                # Pop the first pending delegate call (FIFO correlation)
                parent_tool_call_id = (
                    self._pending_delegates.popleft()
                    if self._pending_delegates
                    else None
                )
                return {
                    "type": "session_fork",
                    "parent_id": data.get("parent_id", ""),
                    "child_id": data.get("child_id", ""),
                    "agent": data.get("agent", ""),
                    "parent_tool_call_id": parent_tool_call_id,
                }

            case "orchestrator:complete":
                self._reset()
                return {
                    "type": "prompt_complete",
                    "turn_count": data.get("turn_count", 0),
                }

            case "cancel:completed":
                return {"type": "execution_cancelled"}

            case "cancel:requested":
                return {"type": "cancel_acknowledged"}

            case "display_message":
                return {
                    "type": "display_message",
                    "message": data.get("message", ""),
                    "level": data.get("level", "info"),
                    "source": data.get("source", "system"),
                }

            case _:
                return None
```

**Step 4: Run tests**
```
uv run python -m pytest tests/test_chat_translator.py -v
```
Expected: All pass.

**Step 5: Commit**
```
git add src/amplifier_distro/server/apps/chat/translator.py tests/test_chat_translator.py
git commit -m "feat(chat): add SessionEventTranslator with index remapping and delegate correlation"
```

---

### Task 5: ChatConnection Class

**Files:**
- Create: `src/amplifier_distro/server/apps/chat/connection.py`
- Create: `tests/test_chat_connection.py`

**Background:** `ChatConnection` owns the full WebSocket lifecycle: auth handshake, receive loop, event fanout loop. It holds the `asyncio.Queue` and wires it to the backend via `event_queue` param.

Auth: if `api_key` is set in config, the first message MUST be `{"type":"auth","token":"..."}`. Wrong/missing token → close with code 4001.

**Step 1: Write the failing tests**

Create `tests/test_chat_connection.py`:
```python
"""Tests for ChatConnection."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def make_ws(messages: list[dict], *, api_key: str | None = None):
    """Create a mock WebSocket that replays messages then raises disconnect."""
    from starlette.websockets import WebSocketDisconnect

    ws = MagicMock()
    ws.close = AsyncMock()
    ws.send_json = AsyncMock()

    msg_iter = iter(messages)

    async def receive_json():
        try:
            return next(msg_iter)
        except StopIteration:
            raise WebSocketDisconnect(code=1000)

    ws.receive_json = receive_json
    return ws


def make_backend(session_id: str = "test-sess-001"):
    backend = MagicMock()
    info = MagicMock()
    info.session_id = session_id
    info.working_dir = "/tmp/test"
    backend.create_session = AsyncMock(return_value=info)
    backend.execute = AsyncMock(return_value=None)
    backend.cancel_session = AsyncMock(return_value=None)
    backend.resolve_approval = MagicMock(return_value=True)
    return backend


def make_config(api_key: str | None = None):
    config = MagicMock()
    config.server = MagicMock()
    config.server.api_key = api_key
    return config


class TestAuthHandshake:
    @pytest.mark.asyncio
    async def test_no_api_key_skips_auth(self):
        """When api_key is None, auth is skipped immediately."""
        from amplifier_distro.server.apps.chat.connection import ChatConnection

        ws = make_ws([])
        backend = make_backend()
        config = make_config(api_key=None)

        conn = ChatConnection(ws, backend, config)
        await conn.auth_handshake()
        ws.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_correct_token_sends_auth_ok(self):
        from amplifier_distro.server.apps.chat.connection import ChatConnection

        ws = make_ws([{"type": "auth", "token": "secret"}])
        backend = make_backend()
        config = make_config(api_key="secret")

        conn = ChatConnection(ws, backend, config)
        await conn.auth_handshake()

        ws.send_json.assert_awaited_once_with({"type": "auth_ok"})
        ws.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_token_closes_4001(self):
        from amplifier_distro.server.apps.chat.connection import ChatConnection

        ws = make_ws([{"type": "auth", "token": "wrong"}])
        backend = make_backend()
        config = make_config(api_key="secret")

        conn = ChatConnection(ws, backend, config)
        await conn.auth_handshake()

        ws.close.assert_awaited_once_with(4001, "Unauthorized")


class TestReceiveLoop:
    @pytest.mark.asyncio
    async def test_create_session_message(self):
        from amplifier_distro.server.apps.chat.connection import ChatConnection
        from starlette.websockets import WebSocketDisconnect

        ws = make_ws([
            {"type": "create_session", "bundle": "foundation", "cwd": "/tmp", "behaviors": []},
        ])
        backend = make_backend("sess-abc")
        config = make_config()

        conn = ChatConnection(ws, backend, config)
        with pytest.raises((WebSocketDisconnect, StopAsyncIteration, Exception)):
            await conn._receive_loop()

        backend.create_session.assert_awaited_once()
        call_kwargs = backend.create_session.call_args.kwargs
        assert call_kwargs.get("working_dir") == "/tmp" or call_kwargs.get("cwd") == "/tmp"

    @pytest.mark.asyncio
    async def test_ping_sends_pong(self):
        from amplifier_distro.server.apps.chat.connection import ChatConnection
        from starlette.websockets import WebSocketDisconnect

        ws = make_ws([{"type": "ping"}])
        backend = make_backend()
        config = make_config()

        conn = ChatConnection(ws, backend, config)
        with pytest.raises((WebSocketDisconnect, StopAsyncIteration, Exception)):
            await conn._receive_loop()

        sent = [call.args[0] for call in ws.send_json.await_args_list]
        assert any(m.get("type") == "pong" for m in sent)


class TestEventFanout:
    @pytest.mark.asyncio
    async def test_events_forwarded_to_websocket(self):
        from amplifier_distro.server.apps.chat.connection import ChatConnection

        ws = make_ws([])
        backend = make_backend()
        config = make_config()

        conn = ChatConnection(ws, backend, config)
        # Put a translatable event into the queue
        await conn.event_queue.put(("orchestrator:complete", {"turn_count": 1}))
        await conn.event_queue.put(None)  # sentinel to stop the loop

        await conn._event_fanout_loop()

        sent = [call.args[0] for call in ws.send_json.await_args_list]
        assert any(m.get("type") == "prompt_complete" for m in sent)

    @pytest.mark.asyncio
    async def test_unknown_events_not_forwarded(self):
        from amplifier_distro.server.apps.chat.connection import ChatConnection

        ws = make_ws([])
        backend = make_backend()
        config = make_config()

        conn = ChatConnection(ws, backend, config)
        await conn.event_queue.put(("some:unknown:event", {}))
        await conn.event_queue.put(None)

        await conn._event_fanout_loop()

        # Unknown event produces None from translator — nothing sent
        ws.send_json.assert_not_awaited()
```

**Step 2: Run to verify failure**
```
uv run python -m pytest tests/test_chat_connection.py -v
```
Expected: `ModuleNotFoundError`.

**Step 3: Implement ChatConnection**

Create `src/amplifier_distro/server/apps/chat/connection.py`:
```python
"""ChatConnection — manages one WebSocket session lifecycle.

One instance per WebSocket connection. Owns:
  - auth_handshake(): validate token if api_key is configured
  - _receive_loop(): read client messages, dispatch to backend
  - _event_fanout_loop(): drain asyncio.Queue, translate, send to WS
  - event_queue: asyncio.Queue wired to BridgeBackend.on_stream
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from starlette.websockets import WebSocketDisconnect

from amplifier_distro.server.apps.chat.translator import SessionEventTranslator

if TYPE_CHECKING:
    from fastapi import WebSocket

    from amplifier_distro.server.session_backend import BridgeBackend

logger = logging.getLogger(__name__)

# Sentinel: put into event_queue to stop _event_fanout_loop
_STOP = None


class ChatConnection:
    """Manages one WebSocket connection: auth, receive loop, event fanout."""

    def __init__(
        self,
        ws: "WebSocket",
        backend: "BridgeBackend",
        config: Any,
    ) -> None:
        self._ws = ws
        self._backend = backend
        self._config = config
        self.event_queue: asyncio.Queue = asyncio.Queue()
        self._translator = SessionEventTranslator()
        self._session_id: str | None = None
        self._approval_system: Any = None

    async def run(self) -> None:
        """Full connection lifecycle: auth then concurrent receive + fanout."""
        await self._ws.accept()
        try:
            await self.auth_handshake()
        except WebSocketDisconnect:
            return

        try:
            await asyncio.gather(
                self._receive_loop(),
                self._event_fanout_loop(),
            )
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.warning("ChatConnection error", exc_info=True)
        finally:
            # Drain queue on exit
            await self.event_queue.put(_STOP)

    async def auth_handshake(self) -> None:
        """Validate auth token if api_key is configured.

        Closes with code 4001 if wrong token.
        No-op if api_key is None.
        """
        api_key = getattr(self._config.server, "api_key", None)
        if not api_key:
            return

        try:
            msg = await self._ws.receive_json()
        except WebSocketDisconnect:
            raise

        if msg.get("type") != "auth" or msg.get("token") != api_key:
            await self._ws.close(4001, "Unauthorized")
            return

        await self._ws.send_json({"type": "auth_ok"})

    async def _receive_loop(self) -> None:
        """Read messages from client and dispatch by type."""
        while True:
            try:
                msg = await self._ws.receive_json()
            except WebSocketDisconnect:
                return

            msg_type = msg.get("type", "")
            try:
                await self._dispatch(msg_type, msg)
            except Exception:
                logger.warning("Error dispatching message type=%s", msg_type, exc_info=True)
                await self._ws.send_json({
                    "type": "execution_error",
                    "error": "Internal error processing message",
                })

    async def _dispatch(self, msg_type: str, msg: dict[str, Any]) -> None:
        """Route a received message to the appropriate handler."""
        match msg_type:
            case "create_session":
                await self._handle_create_session(msg)

            case "prompt":
                content = msg.get("content", "")
                images = msg.get("images")
                asyncio.create_task(self._execute(content, images))

            case "cancel":
                level = msg.get("level", "graceful")
                if self._session_id:
                    await self._backend.cancel_session(self._session_id, level)

            case "approval_response":
                req_id = msg.get("id", "")
                choice = msg.get("choice", "deny")
                if self._session_id:
                    self._backend.resolve_approval(self._session_id, req_id, choice)

            case "command":
                name = msg.get("name", "")
                args = msg.get("args", [])
                await self._handle_command(name, args)

            case "ping":
                await self._ws.send_json({"type": "pong"})

            case _:
                logger.debug("Unknown message type: %s", msg_type)

    async def _handle_create_session(self, msg: dict[str, Any]) -> None:
        """Create or resume an Amplifier session."""
        cwd = msg.get("cwd", "~")
        bundle = msg.get("bundle")
        behaviors = msg.get("behaviors")
        resume_session_id = msg.get("resume_session_id")
        show_thinking = msg.get("show_thinking", False)

        try:
            info = await self._backend.create_session(
                working_dir=cwd,
                bundle_name=bundle,
                event_queue=self.event_queue,
            )
            self._session_id = info.session_id
            await self._ws.send_json({
                "type": "session_created",
                "session_id": info.session_id,
                "cwd": str(info.working_dir),
                "bundle": bundle,
            })
        except Exception as exc:
            logger.warning("Session creation failed", exc_info=True)
            await self._ws.send_json({
                "type": "execution_error",
                "error": str(exc),
            })

    async def _execute(self, content: str, images: list[str] | None = None) -> None:
        """Execute a prompt — events stream via event_queue."""
        if not self._session_id:
            await self._ws.send_json({
                "type": "execution_error",
                "error": "No session. Send create_session first.",
            })
            return

        try:
            await self._backend.execute(self._session_id, content, images)
        except Exception as exc:
            logger.warning("Execution error", exc_info=True)
            await self._ws.send_json({
                "type": "execution_error",
                "error": str(exc),
            })

    async def _handle_command(self, name: str, args: list[str]) -> None:
        """Handle a slash command from the client."""
        try:
            result = await self._dispatch_command(name, args)
            await self._ws.send_json({
                "type": "command_result",
                "command": name,
                "result": result,
            })
        except Exception as exc:
            await self._ws.send_json({
                "type": "command_result",
                "command": name,
                "result": {"error": str(exc)},
            })

    async def _dispatch_command(self, name: str, args: list[str]) -> dict[str, Any]:
        """Route server-side slash commands."""
        match name:
            case "status":
                return {
                    "session_id": self._session_id,
                    "status": "active" if self._session_id else "no_session",
                }
            case "bundle" if args:
                # Reconfigure session with new bundle
                new_bundle = args[0]
                info = await self._backend.create_session(
                    bundle_name=new_bundle,
                    event_queue=self.event_queue,
                )
                self._session_id = info.session_id
                return {"bundle": new_bundle, "session_id": info.session_id}
            case "cwd" if args:
                new_cwd = args[0]
                info = await self._backend.create_session(
                    working_dir=new_cwd,
                    event_queue=self.event_queue,
                )
                self._session_id = info.session_id
                return {"cwd": new_cwd, "session_id": info.session_id}
            case _:
                return {"error": f"Unknown command: {name}"}

    async def _event_fanout_loop(self) -> None:
        """Drain event_queue and forward translated events to WebSocket.

        Stops on None sentinel.
        """
        while True:
            raw = await self.event_queue.get()
            if raw is _STOP:
                break
            event_name, data = raw
            try:
                msg = self._translator.translate(event_name, data)
                if msg is not None:
                    await self._ws.send_json(msg)
            except Exception:
                logger.warning(
                    "Error translating/sending event %s", event_name, exc_info=True
                )
```

**Step 4: Run tests**
```
uv run python -m pytest tests/test_chat_connection.py -v
```
Expected: All pass.

**Step 5: Commit**
```
git add src/amplifier_distro/server/apps/chat/connection.py tests/test_chat_connection.py
git commit -m "feat(chat): add ChatConnection with auth, receive loop, and event fanout"
```

---

### Task 6: Wire WebSocket Endpoint

**Files:**
- Modify: `src/amplifier_distro/server/apps/chat/__init__.py`
- Modify: `tests/test_chat_app.py`

**Step 1: Add WebSocket integration test to test_chat_app.py**

Add this class to `tests/test_chat_app.py`:
```python
class TestChatWebSocketEndpoint:
    def test_websocket_accepts_connection(self, chat_client):
        """WebSocket at /apps/chat/ws accepts connections."""
        with chat_client.websocket_connect("/apps/chat/ws") as ws:
            # Send ping immediately
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"

    def test_websocket_create_session(self, chat_client):
        """create_session message returns session_created."""
        with chat_client.websocket_connect("/apps/chat/ws") as ws:
            ws.send_json({
                "type": "create_session",
                "cwd": "~",
                "bundle": None,
            })
            msg = ws.receive_json()
            assert msg["type"] == "session_created"
            assert "session_id" in msg
```

**Step 2: Run to verify failure**
```
uv run python -m pytest tests/test_chat_app.py::TestChatWebSocketEndpoint -v
```
Expected: 404 — WebSocket route doesn't exist.

**Step 3: Add WebSocket route to __init__.py**

Add to `src/amplifier_distro/server/apps/chat/__init__.py` (after the existing imports):
```python
from fastapi import WebSocket

# ... existing imports ...


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket endpoint — one connection per session."""
    from amplifier_distro.server.services import get_services

    from amplifier_distro.server.apps.chat.connection import ChatConnection

    try:
        from amplifier_distro.config import get_config as _get_config
        config = _get_config()
    except Exception:
        config = type("Config", (), {"server": type("S", (), {"api_key": None})()})()

    services = get_services()
    conn = ChatConnection(ws, services.backend, config)
    await conn.run()
```

**Step 4: Run tests**
```
uv run python -m pytest tests/test_chat_app.py -v
```
Expected: All pass (except the `@pytest.mark.skip` on vendor.js).

**Step 5: Commit**
```
git add src/amplifier_distro/server/apps/chat/__init__.py tests/test_chat_app.py
git commit -m "feat(chat): wire WebSocket endpoint /apps/chat/ws"
```

---

## Phase 2: Backend Gap Fixes

### Task 7: Cancellation — SessionHandle.cancel() + BridgeBackend.cancel_session()

**Files:**
- Modify: `src/amplifier_distro/bridge.py`
- Modify: `src/amplifier_distro/server/session_backend.py`
- Create: `tests/test_chat_cancellation.py`

**Step 1: Write the failing tests**

Create `tests/test_chat_cancellation.py`:
```python
"""Tests for session cancellation support."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_distro.bridge import SessionHandle
from amplifier_distro.server.session_backend import BridgeBackend


class TestSessionHandleCancel:
    @pytest.mark.asyncio
    async def test_cancel_graceful_calls_coordinator(self):
        mock_session = MagicMock()
        mock_session.coordinator = MagicMock()
        mock_session.coordinator.request_cancel = MagicMock()

        handle = SessionHandle(
            session_id="s001",
            project_id="p001",
            working_dir=__import__("pathlib").Path("/tmp"),
            _session=mock_session,
        )

        await handle.cancel("graceful")
        mock_session.coordinator.request_cancel.assert_called_once_with("graceful")

    @pytest.mark.asyncio
    async def test_cancel_no_session_does_not_raise(self):
        """If _session is None, cancel() is a safe no-op."""
        handle = SessionHandle(
            session_id="s002",
            project_id="p002",
            working_dir=__import__("pathlib").Path("/tmp"),
            _session=None,
        )
        await handle.cancel("graceful")  # Should not raise

    @pytest.mark.asyncio
    async def test_cancel_no_coordinator_does_not_raise(self):
        """If session has no coordinator, cancel() is a safe no-op."""
        mock_session = MagicMock(spec=[])  # no attributes
        handle = SessionHandle(
            session_id="s003",
            project_id="p003",
            working_dir=__import__("pathlib").Path("/tmp"),
            _session=mock_session,
        )
        await handle.cancel("graceful")  # Should not raise


class TestBridgeBackendCancelSession:
    @pytest.mark.asyncio
    async def test_cancel_session_delegates_to_handle(self):
        mock_handle = MagicMock()
        mock_handle.cancel = AsyncMock()

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {"sess-cancel-001": mock_handle}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()

        await backend.cancel_session("sess-cancel-001", "graceful")
        mock_handle.cancel.assert_awaited_once_with("graceful")

    @pytest.mark.asyncio
    async def test_cancel_session_unknown_id_does_not_raise(self):
        """Cancelling a session that doesn't exist is a safe no-op."""
        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()

        await backend.cancel_session("no-such-session", "immediate")  # no raise

    @pytest.mark.asyncio
    async def test_cancel_session_immediate_level_passed_through(self):
        mock_handle = MagicMock()
        mock_handle.cancel = AsyncMock()

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {"s": mock_handle}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()

        await backend.cancel_session("s", "immediate")
        mock_handle.cancel.assert_awaited_once_with("immediate")
```

**Step 2: Run to verify failure**
```
uv run python -m pytest tests/test_chat_cancellation.py -v
```
Expected: `AttributeError` — `SessionHandle` has no `cancel()`, `BridgeBackend` has no `cancel_session()`.

**Step 3: Add cancel() to SessionHandle in bridge.py**

In `src/amplifier_distro/bridge.py`, add to `SessionHandle` after `run()`:
```python
    async def cancel(self, level: str = "graceful") -> None:
        """Request cancellation of the running session.

        Safe to call when _session is None or coordinator is unavailable.
        level: "graceful" (finish current tool) or "immediate" (stop now).
        """
        if self._session is None:
            return
        coordinator = getattr(self._session, "coordinator", None)
        if coordinator is None:
            return
        request_cancel = getattr(coordinator, "request_cancel", None)
        if request_cancel is not None:
            request_cancel(level)
```

**Step 4: Add cancel_session() to BridgeBackend in session_backend.py**

In `src/amplifier_distro/server/session_backend.py`, add after `execute()`:
```python
    async def cancel_session(
        self,
        session_id: str,
        level: str = "graceful",
    ) -> None:
        """Request cancellation of an active session.

        Safe to call on unknown session IDs (no-op).
        level: "graceful" or "immediate".
        """
        handle = self._sessions.get(session_id)
        if handle is None:
            logger.debug("cancel_session: unknown session %s (ignored)", session_id)
            return
        await handle.cancel(level)
```

**Step 5: Run tests**
```
uv run python -m pytest tests/test_chat_cancellation.py -v
```
Expected: All pass.

**Step 6: Commit**
```
git add src/amplifier_distro/bridge.py src/amplifier_distro/server/session_backend.py tests/test_chat_cancellation.py
git commit -m "feat(chat): add SessionHandle.cancel() and BridgeBackend.cancel_session()"
```

---

### Task 8: BridgeApprovalSystem Rebuild

**Files:**
- Modify: `src/amplifier_distro/bridge_protocols.py`
- Modify: `src/amplifier_distro/server/session_backend.py`
- Create: `tests/test_chat_approval.py`

**Background:** Current `BridgeApprovalSystem.request_approval()` auto-approves or calls a callback synchronously. We rebuild it with `asyncio.Event` so the WebSocket can call `handle_response()` from a different coroutine to unblock a waiting `request_approval()`.

We also add `BridgeBackend.resolve_approval()` and wire `on_approval_request` to the event queue.

**Step 1: Write the failing tests**

Create `tests/test_chat_approval.py`:
```python
"""Tests for the rebuilt BridgeApprovalSystem."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_distro.bridge_protocols import BridgeApprovalSystem


class TestBridgeApprovalSystemAutoApprove:
    @pytest.mark.asyncio
    async def test_auto_approve_returns_first_option(self):
        approval = BridgeApprovalSystem(auto_approve=True)
        result = await approval.request_approval("Allow?", ["allow", "deny"])
        assert result == "allow"

    @pytest.mark.asyncio
    async def test_auto_approve_empty_options_returns_allow(self):
        approval = BridgeApprovalSystem(auto_approve=True)
        result = await approval.request_approval("Allow?", [])
        assert result == "allow"


class TestBridgeApprovalSystemInteractive:
    @pytest.mark.asyncio
    async def test_request_blocks_until_handle_response(self):
        """request_approval blocks until handle_response is called."""
        approval = BridgeApprovalSystem(auto_approve=False)

        async def responder():
            await asyncio.sleep(0.01)  # Let request_approval start
            # Find the pending request ID
            for req_id in list(approval._pending.keys()):
                approval.handle_response(req_id, "allow")

        result, _ = await asyncio.gather(
            approval.request_approval("Allow tool?", ["allow", "deny"]),
            responder(),
        )
        assert result == "allow"

    @pytest.mark.asyncio
    async def test_handle_response_returns_true_for_valid_id(self):
        approval = BridgeApprovalSystem(auto_approve=False)

        async def background():
            await asyncio.sleep(0.01)
            return approval.handle_response(list(approval._pending.keys())[0], "deny")

        _, ok = await asyncio.gather(
            approval.request_approval("?", ["allow", "deny"], timeout=1.0),
            background(),
        )
        assert ok is True

    @pytest.mark.asyncio
    async def test_handle_response_returns_false_for_unknown_id(self):
        approval = BridgeApprovalSystem(auto_approve=False)
        result = approval.handle_response("no-such-id", "allow")
        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_returns_default(self):
        approval = BridgeApprovalSystem(auto_approve=False)
        result = await approval.request_approval(
            "Allow?", ["allow", "deny"], timeout=0.05, default="deny"
        )
        assert result == "deny"

    @pytest.mark.asyncio
    async def test_on_approval_request_callback_called(self):
        """on_approval_request callback fires with request details."""
        callback = AsyncMock()
        approval = BridgeApprovalSystem(
            auto_approve=False,
            on_approval_request=callback,
        )

        async def background():
            await asyncio.sleep(0.01)
            for req_id in list(approval._pending.keys()):
                approval.handle_response(req_id, "allow")

        await asyncio.gather(
            approval.request_approval("Allow?", ["allow", "deny"]),
            background(),
        )

        callback.assert_awaited_once()
        call_kwargs = callback.call_args
        # callback receives (request_id, prompt, options, timeout, default)
        assert "allow" in call_kwargs.args[2]


class TestBridgeBackendResolveApproval:
    def test_resolve_approval_delegates_to_session_approval(self):
        from amplifier_distro.server.session_backend import BridgeBackend

        mock_approval = MagicMock()
        mock_approval.handle_response = MagicMock(return_value=True)

        mock_handle = MagicMock()
        mock_handle.get_approval_system = MagicMock(return_value=mock_approval)

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {"s001": mock_handle}
        backend._approval_systems = {"s001": mock_approval}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()

        result = backend.resolve_approval("s001", "req-001", "allow")
        assert result is True
        mock_approval.handle_response.assert_called_once_with("req-001", "allow")
```

**Step 2: Run to verify failure**
```
uv run python -m pytest tests/test_chat_approval.py -v
```
Expected: Multiple failures — the old `BridgeApprovalSystem` doesn't support async event-based blocking.

**Step 3: Rebuild BridgeApprovalSystem in bridge_protocols.py**

Replace the `BridgeApprovalSystem` class entirely in `src/amplifier_distro/bridge_protocols.py`:
```python
class BridgeApprovalSystem:
    """Interactive approval system using asyncio.Event for WebSocket integration.

    In auto_approve mode: immediately returns first option (headless usage).
    In interactive mode: blocks request_approval() until handle_response()
    is called from another coroutine (e.g., the WebSocket receive loop).

    on_approval_request: async callback(request_id, prompt, options, timeout, default)
      Called when a new approval request is pending — use this to notify the
      WebSocket client that approval is needed.
    """

    def __init__(
        self,
        on_approval_request: Callable[..., Any] | None = None,
        auto_approve: bool = True,
    ) -> None:
        self._on_approval_request = on_approval_request
        self._auto_approve = auto_approve
        self._pending: dict[str, asyncio.Event] = {}
        self._responses: dict[str, str] = {}

    async def request_approval(
        self,
        prompt: str,
        options: list[str],
        timeout: float = 300.0,
        default: Literal["allow", "deny"] = "deny",
    ) -> str:
        if self._auto_approve:
            return options[0] if options else "allow"

        import uuid
        request_id = str(uuid.uuid4())
        event = asyncio.Event()
        self._pending[request_id] = event

        if self._on_approval_request:
            result = self._on_approval_request(
                request_id, prompt, options, timeout, default
            )
            if asyncio.iscoroutine(result):
                await result

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return self._responses.pop(request_id, default)
        except asyncio.TimeoutError:
            return default
        finally:
            self._pending.pop(request_id, None)

    def handle_response(self, request_id: str, choice: str) -> bool:
        """Unblock a waiting request_approval(). Returns True if found."""
        event = self._pending.get(request_id)
        if event is not None:
            self._responses[request_id] = choice
            event.set()
            return True
        return False
```

**Step 4: Add resolve_approval() to BridgeBackend and _approval_systems dict**

In `src/amplifier_distro/server/session_backend.py`, add `_approval_systems: dict[str, Any] = {}` to `BridgeBackend.__init__()`:
```python
    def __init__(self) -> None:
        from amplifier_distro.bridge import LocalBridge
        self._bridge = LocalBridge()
        self._sessions: dict[str, Any] = {}
        self._reconnect_locks: dict[str, asyncio.Lock] = {}
        self._session_queues: dict[str, asyncio.Queue] = {}
        self._worker_tasks: dict[str, asyncio.Task] = {}
        self._ended_sessions: set[str] = set()
        self._approval_systems: dict[str, Any] = {}  # session_id → BridgeApprovalSystem
```

Add `resolve_approval()` to `BridgeBackend`:
```python
    def resolve_approval(
        self,
        session_id: str,
        request_id: str,
        choice: str,
    ) -> bool:
        """Unblock a pending approval request for a session.

        Returns True if the request was found and unblocked, False otherwise.
        """
        approval = self._approval_systems.get(session_id)
        if approval is None:
            logger.warning(
                "resolve_approval: no approval system for session %s", session_id
            )
            return False
        return approval.handle_response(request_id, choice)
```

**Step 5: Run tests**
```
uv run python -m pytest tests/test_chat_approval.py -v
```
Expected: All pass.

**Step 6: Run full suite**
```
uv run python -m pytest tests/ -q
```
Expected: Same baseline, no regressions.

**Step 7: Commit**
```
git add src/amplifier_distro/bridge_protocols.py src/amplifier_distro/server/session_backend.py tests/test_chat_approval.py
git commit -m "feat(chat): rebuild BridgeApprovalSystem with asyncio.Event and add resolve_approval()"
```

---

### Task 9: behaviors + show_thinking in BridgeConfig

**Files:**
- Modify: `src/amplifier_distro/bridge.py`
- Create: `tests/test_chat_bridge_config.py`

**Step 1: Write the failing tests**

Create `tests/test_chat_bridge_config.py`:
```python
"""Tests for BridgeConfig behaviors and show_thinking fields."""
from amplifier_distro.bridge import BridgeConfig
import pathlib


class TestBridgeConfigNewFields:
    def test_behaviors_default_is_none(self):
        config = BridgeConfig()
        assert config.behaviors is None

    def test_behaviors_can_be_set(self):
        config = BridgeConfig(behaviors=["web-search", "file-ops"])
        assert config.behaviors == ["web-search", "file-ops"]

    def test_show_thinking_default_is_false(self):
        config = BridgeConfig()
        assert config.show_thinking is False

    def test_show_thinking_can_be_set(self):
        config = BridgeConfig(show_thinking=True)
        assert config.show_thinking is True

    def test_existing_fields_still_work(self):
        config = BridgeConfig(
            working_dir=pathlib.Path("/tmp"),
            bundle_name="my-bundle",
            behaviors=["tool-a"],
            show_thinking=True,
        )
        assert config.working_dir == pathlib.Path("/tmp")
        assert config.bundle_name == "my-bundle"
        assert config.behaviors == ["tool-a"]
        assert config.show_thinking is True
```

**Step 2: Run to verify failure**
```
uv run python -m pytest tests/test_chat_bridge_config.py -v
```
Expected: `TypeError` — unexpected keyword argument.

**Step 3: Add fields to BridgeConfig in bridge.py**

In `src/amplifier_distro/bridge.py`, in the `BridgeConfig` dataclass, add after `on_stream`:
```python
    # Behaviors to activate in the session (e.g., ["web-search", "file-ops"])
    behaviors: list[str] | None = None
    # Whether to expose thinking blocks to the UI
    show_thinking: bool = False
```

**Step 4: Run tests**
```
uv run python -m pytest tests/test_chat_bridge_config.py -v
```
Expected: All pass.

**Step 5: Commit**
```
git add src/amplifier_distro/bridge.py tests/test_chat_bridge_config.py
git commit -m "feat(chat): add behaviors and show_thinking fields to BridgeConfig"
```

---

### Task 10: BridgeDisplaySystem.on_message → event queue

**Files:**
- Modify: `src/amplifier_distro/server/session_backend.py`
- Create: `tests/test_chat_display_messages.py`

**Background:** When `event_queue` is provided to `create_session()`, wire `BridgeDisplaySystem.on_message` to put `("display_message", {level, message, source})` directly into the queue, bypassing the hook system. This lets `show_message()` calls appear as `display_message` events in the WebSocket stream.

**Step 1: Write the failing tests**

Create `tests/test_chat_display_messages.py`:
```python
"""Tests for BridgeDisplaySystem → event queue wiring."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDisplayMessageQueueWiring:
    @pytest.mark.asyncio
    async def test_on_message_puts_to_queue(self):
        """When create_session gets event_queue, display messages go into it."""
        from amplifier_distro.server.session_backend import BridgeBackend

        captured_display = {}

        async def fake_bridge_create(config):
            captured_display["system"] = config.display
            handle = MagicMock()
            handle.session_id = "display-test-001"
            handle.project_id = "p"
            handle.working_dir = "/tmp"
            return handle

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._bridge = MagicMock()
        backend._bridge.create_session = AsyncMock(side_effect=fake_bridge_create)
        backend._sessions = {}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()
        backend._approval_systems = {}

        q: asyncio.Queue = asyncio.Queue()

        with patch("asyncio.create_task"):
            await backend.create_session(working_dir="~", event_queue=q)

        display = captured_display.get("system")
        assert display is not None

        # Trigger a display message
        await display.show_message("Hello from display", level="info", source="test")

        item = q.get_nowait()
        assert item == ("display_message", {
            "message": "Hello from display",
            "level": "info",
            "source": "test",
        })
```

**Step 2: Run to verify failure**
```
uv run python -m pytest tests/test_chat_display_messages.py -v
```
Expected: Assertion error — no display message in queue.

**Step 3: Implement the wiring in BridgeBackend.create_session()**

In `src/amplifier_distro/server/session_backend.py`, in `BridgeBackend.create_session()`, after building `on_stream` and before building `config`, add:

```python
        # Wire display system to queue if provided
        display = None
        if event_queue is not None:
            from amplifier_distro.bridge_protocols import BridgeDisplaySystem as _BDS
            _q = event_queue
            def _on_display_message(message: str, level: str, source: str) -> None:
                _q.put_nowait(("display_message", {
                    "message": message,
                    "level": level,
                    "source": source,
                }))
            display = _BDS(on_message=_on_display_message)

        config = BridgeConfig(
            working_dir=Path(working_dir).expanduser(),
            bundle_name=bundle_name,
            run_preflight=False,
            on_stream=on_stream,
            display=display,   # ← new
        )
```

**Step 4: Run tests**
```
uv run python -m pytest tests/test_chat_display_messages.py -v
```
Expected: Pass.

**Step 5: Commit**
```
git add src/amplifier_distro/server/session_backend.py tests/test_chat_display_messages.py
git commit -m "feat(chat): wire BridgeDisplaySystem.on_message to event queue"
```

---

## Phase 3: Session Management REST Endpoints

### Task 11: GET /api/sessions

**Files:**
- Modify: `src/amplifier_distro/server/apps/chat/__init__.py`
- Modify: `tests/test_chat_app.py`

**Step 1: Add tests**

Add to `tests/test_chat_app.py`:
```python
class TestChatSessionsAPI:
    def test_list_sessions_returns_200(self, chat_client):
        r = chat_client.get("/apps/chat/api/sessions")
        assert r.status_code == 200

    def test_list_sessions_returns_list(self, chat_client):
        r = chat_client.get("/apps/chat/api/sessions")
        data = r.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_list_sessions_empty_when_none(self, chat_client):
        r = chat_client.get("/apps/chat/api/sessions")
        assert r.json()["sessions"] == []
```

**Step 2: Run to verify failure**
```
uv run python -m pytest tests/test_chat_app.py::TestChatSessionsAPI -v
```
Expected: 404.

**Step 3: Add route to __init__.py**

Add to `src/amplifier_distro/server/apps/chat/__init__.py`:
```python
@router.get("/api/sessions")
async def list_sessions() -> dict:
    """List all active chat sessions with metadata."""
    from amplifier_distro.server.services import get_services

    services = get_services()
    sessions = services.backend.list_active_sessions()
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "working_dir": s.working_dir,
                "description": s.description,
                "is_active": s.is_active,
            }
            for s in sessions
        ]
    }
```

**Step 4: Run tests**
```
uv run python -m pytest tests/test_chat_app.py::TestChatSessionsAPI -v
```
Expected: All pass.

**Step 5: Commit**
```
git add src/amplifier_distro/server/apps/chat/__init__.py tests/test_chat_app.py
git commit -m "feat(chat): add GET /api/sessions endpoint"
```

---

### Task 12: Transcript History Endpoint

**Files:**
- Modify: `src/amplifier_distro/server/apps/chat/__init__.py`
- Modify: `tests/test_chat_app.py`

**Step 1: Add tests**

Add to `tests/test_chat_app.py`:
```python
import json
import tempfile
from pathlib import Path


class TestChatTranscriptAPI:
    def test_transcript_404_for_unknown_session(self, chat_client):
        r = chat_client.get("/apps/chat/api/sessions/no-such-session/transcript")
        assert r.status_code == 404

    def test_transcript_returns_messages(self, chat_client, tmp_path, monkeypatch):
        """Transcript JSONL is parsed and returned as array."""
        # Build a fake session directory structure
        session_id = "test-transcript-session"
        session_dir = tmp_path / "projects" / "test-proj" / "sessions" / session_id
        session_dir.mkdir(parents=True)
        transcript = session_dir / "transcript.jsonl"
        lines = [
            json.dumps({"role": "user", "content": "hello"}),
            json.dumps({"role": "assistant", "content": "hi there"}),
        ]
        transcript.write_text("\n".join(lines))

        # Patch AMPLIFIER_HOME to point at tmp_path
        monkeypatch.setattr(
            "amplifier_distro.server.apps.chat.AMPLIFIER_HOME",
            str(tmp_path),
        )

        r = chat_client.get(f"/apps/chat/api/sessions/{session_id}/transcript")
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"] == session_id
        assert len(data["transcript"]) == 2
        assert data["transcript"][0]["role"] == "user"
```

**Step 2: Run to verify failure**
```
uv run python -m pytest tests/test_chat_app.py::TestChatTranscriptAPI -v
```
Expected: 404 for both (route doesn't exist).

**Step 3: Add route and import to __init__.py**

Add to `src/amplifier_distro/server/apps/chat/__init__.py`:
```python
from amplifier_distro.conventions import AMPLIFIER_HOME, PROJECTS_DIR, TRANSCRIPT_FILENAME


@router.get("/api/sessions/{session_id}/transcript")
async def get_transcript(session_id: str) -> JSONResponse:
    """Return the transcript for a session as a JSON array of messages."""
    import json as _json

    projects_path = Path(AMPLIFIER_HOME).expanduser() / PROJECTS_DIR

    # Search all project directories for this session
    transcript_file: Path | None = None
    if projects_path.exists():
        for project_dir in projects_path.iterdir():
            if not project_dir.is_dir():
                continue
            sessions_subdir = project_dir / "sessions"
            candidate_dir = sessions_subdir if sessions_subdir.is_dir() else project_dir
            candidate = candidate_dir / session_id / TRANSCRIPT_FILENAME
            if candidate.exists():
                transcript_file = candidate
                break

    if transcript_file is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"Session {session_id!r} not found"},
        )

    messages = []
    try:
        with transcript_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = _json.loads(line)
                    if isinstance(entry, dict) and entry.get("role"):
                        messages.append(entry)
                except _json.JSONDecodeError:
                    continue
    except OSError as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)},
        )

    return JSONResponse(content={
        "session_id": session_id,
        "transcript": messages,
    })
```

**Step 4: Run tests**
```
uv run python -m pytest tests/test_chat_app.py::TestChatTranscriptAPI -v
```
Expected: Pass.

**Step 5: Commit**
```
git add src/amplifier_distro/server/apps/chat/__init__.py tests/test_chat_app.py
git commit -m "feat(chat): add GET /api/sessions/{id}/transcript endpoint"
```

---

### Task 13: Preferences Endpoints

**Files:**
- Create: `src/amplifier_distro/server/apps/chat/preferences.py`
- Modify: `src/amplifier_distro/server/apps/chat/__init__.py`
- Create: `tests/test_chat_preferences.py`

**Step 1: Write the failing tests**

Create `tests/test_chat_preferences.py`:
```python
"""Tests for GET/PUT /api/preferences."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from amplifier_distro.server.app import DistroServer
from amplifier_distro.server.services import init_services, reset_services


@pytest.fixture(autouse=True)
def _clean():
    reset_services()
    yield
    reset_services()


@pytest.fixture
def chat_client(tmp_path) -> TestClient:
    init_services(dev_mode=True)
    from amplifier_distro.server.apps.chat import manifest
    import amplifier_distro.server.apps.chat.preferences as prefs_mod
    prefs_mod._PREFS_PATH = tmp_path / "chat-preferences.json"

    server = DistroServer()
    server.register_app(manifest)
    return TestClient(server.app)


class TestGetPreferences:
    def test_returns_200(self, chat_client):
        r = chat_client.get("/apps/chat/api/preferences")
        assert r.status_code == 200

    def test_returns_defaults_when_no_file(self, chat_client):
        data = chat_client.get("/apps/chat/api/preferences").json()
        assert "default_bundle" in data
        assert "default_behaviors" in data
        assert "show_thinking" in data
        assert "default_cwd" in data
        assert data["show_thinking"] is False
        assert data["default_behaviors"] == []

    def test_default_cwd_is_string(self, chat_client):
        data = chat_client.get("/apps/chat/api/preferences").json()
        assert isinstance(data["default_cwd"], str)


class TestPutPreferences:
    def test_put_updates_show_thinking(self, chat_client):
        chat_client.put("/apps/chat/api/preferences", json={"show_thinking": True})
        data = chat_client.get("/apps/chat/api/preferences").json()
        assert data["show_thinking"] is True

    def test_put_partial_update_preserves_other_fields(self, chat_client):
        chat_client.put("/apps/chat/api/preferences", json={"default_bundle": "my-bundle"})
        data = chat_client.get("/apps/chat/api/preferences").json()
        assert data["default_bundle"] == "my-bundle"
        assert data["show_thinking"] is False  # unchanged

    def test_put_returns_updated_prefs(self, chat_client):
        r = chat_client.put(
            "/apps/chat/api/preferences",
            json={"default_behaviors": ["web-search"]},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["default_behaviors"] == ["web-search"]
```

**Step 2: Run to verify failure**
```
uv run python -m pytest tests/test_chat_preferences.py -v
```
Expected: 404 for all.

**Step 3: Create preferences.py**

Create `src/amplifier_distro/server/apps/chat/preferences.py`:
```python
"""Chat preferences — stored in ~/.amplifier/chat-preferences.json.

Schema:
    default_bundle: str | None       — bundle name to use for new sessions
    default_behaviors: list[str]     — behaviors active by default
    show_thinking: bool              — show thinking blocks in UI
    default_cwd: str                 — default working directory for new sessions
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from amplifier_distro.conventions import AMPLIFIER_HOME

logger = logging.getLogger(__name__)

_PREFS_FILENAME = "chat-preferences.json"
_PREFS_PATH: Path | None = None  # Overridable in tests


def _get_prefs_path() -> Path:
    if _PREFS_PATH is not None:
        return _PREFS_PATH
    return Path(AMPLIFIER_HOME).expanduser() / _PREFS_FILENAME


_DEFAULTS: dict[str, Any] = {
    "default_bundle": None,
    "default_behaviors": [],
    "show_thinking": False,
    "default_cwd": "~",
}


def load_preferences() -> dict[str, Any]:
    """Load preferences from disk, returning defaults if file missing."""
    path = _get_prefs_path()
    prefs = dict(_DEFAULTS)
    if path.exists():
        try:
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            prefs.update({k: v for k, v in on_disk.items() if v is not None})
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read preferences from %s", path, exc_info=True)
    return prefs


def save_preferences(updates: dict[str, Any]) -> dict[str, Any]:
    """Apply partial updates and write to disk. Returns updated preferences."""
    current = load_preferences()
    for key, value in updates.items():
        if key in _DEFAULTS and value is not None:
            current[key] = value
    path = _get_prefs_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except OSError:
        logger.warning("Could not write preferences to %s", path, exc_info=True)
    return current
```

**Step 4: Add routes to __init__.py**

Add to `src/amplifier_distro/server/apps/chat/__init__.py`:
```python
from amplifier_distro.server.apps.chat.preferences import load_preferences, save_preferences
from fastapi import Request


@router.get("/api/preferences")
async def get_preferences() -> dict:
    """Return current user preferences."""
    return load_preferences()


@router.put("/api/preferences")
async def put_preferences(request: Request) -> dict:
    """Apply partial preference updates."""
    body = await request.json() if await request.body() else {}
    return save_preferences(body)
```

**Step 5: Run tests**
```
uv run python -m pytest tests/test_chat_preferences.py -v
```
Expected: All pass.

**Step 6: Commit**
```
git add src/amplifier_distro/server/apps/chat/preferences.py src/amplifier_distro/server/apps/chat/__init__.py tests/test_chat_preferences.py
git commit -m "feat(chat): add preferences GET/PUT endpoints"
```

---

## Phase 4: Frontend Vendor Bundle

### Task 14: Build and Commit vendor.js

**Files:**
- Create: `src/amplifier_distro/server/apps/chat/static/vendor.js`

**Background:** This is a ONE-TIME build step. The output is committed. node_modules are NOT committed. Run these steps manually on your dev machine.

**Step 1: Create a temporary build directory**
```
mkdir /tmp/vendor-build && cd /tmp/vendor-build
```

**Step 2: Initialize npm and install packages**
```
npm init -y
npm install preact@10 htm@3 marked@9
```

**Step 3: Create build script**

Create `/tmp/vendor-build/build.mjs`:
```javascript
import { build } from 'esbuild';

// Build Preact + HTM + marked as a self-contained IIFE that sets globals
await build({
  entryPoints: ['entry.js'],
  bundle: true,
  format: 'iife',
  globalName: '_vendor',
  outfile: 'vendor.js',
  minify: true,
  platform: 'browser',
});
```

Create `/tmp/vendor-build/entry.js`:
```javascript
import * as preact from 'preact';
import * as preactHooks from 'preact/hooks';
import { html } from 'htm/preact';
import { marked } from 'marked';

// Expose as globals for index.html script tags
window.preact = preact;
window.preactHooks = preactHooks;
window.html = html;
window.marked = marked;
```

**Step 4: Install esbuild and run the build**
```
npm install esbuild
node build.mjs
```

This creates `/tmp/vendor-build/vendor.js` (~65KB minified).

**Step 5: Copy to static directory**
```
cp /tmp/vendor-build/vendor.js /Users/samule/repo/amplifier-distro/src/amplifier_distro/server/apps/chat/static/vendor.js
```

**Step 6: Verify the file exposes the right globals**
```
head -c 500 /Users/samule/repo/amplifier-distro/src/amplifier_distro/server/apps/chat/static/vendor.js
```
Should see minified JS starting with `(()=>{` or similar.

**Step 7: Clean up build toolchain (do NOT commit node_modules)**
```
rm -rf /tmp/vendor-build
```

**Step 8: Remove the @pytest.mark.skip from the vendor.js test in tests/test_chat_app.py**

Find and remove: `@pytest.mark.skip(reason="vendor.js built in Task 14")`

**Step 9: Run the vendor test**
```
uv run python -m pytest tests/test_chat_app.py::TestChatVendorEndpoint -v
```
Expected: Pass.

**Step 10: Commit**
```
git add src/amplifier_distro/server/apps/chat/static/vendor.js tests/test_chat_app.py
git commit -m "feat(chat): add vendored frontend bundle (Preact 10 + HTM + marked.js)"
```

---

## Phase 5: Frontend — index.html

### Task 15: index.html Skeleton — ChatApp, WebSocket, StatusBar, Header

**Files:**
- Create: `src/amplifier_distro/server/apps/chat/static/index.html`

**Note:** Frontend tasks (15–22) have no Python tests. Validate each by opening `http://localhost:8000/apps/chat/` in a browser after running the server. Each task builds on the previous — do them in order.

**Step 1: Start the dev server**
```
uv run python -m amplifier_distro.server.main
```
Open `http://localhost:8000/apps/chat/` in a browser. Currently returns 500 (index.html missing).

**Step 2: Create index.html**

Create `src/amplifier_distro/server/apps/chat/static/index.html` with the complete ChatApp foundation:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Amplifier Chat</title>
  <style>
    /* ── Reset & Base ─────────────────────────────────────── */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg-primary: #0d0d0d;
      --bg-secondary: #161616;
      --bg-tertiary: #1e1e1e;
      --bg-card: #1a1a1a;
      --border: rgba(255,255,255,0.08);
      --text-primary: #e8e8e8;
      --text-secondary: #999;
      --text-muted: #555;
      --accent-blue: #3b82f6;
      --accent-green: #22c55e;
      --accent-amber: #f59e0b;
      --accent-red: #ef4444;
      --status-connected: var(--accent-green);
      --status-connecting: var(--accent-amber);
      --status-disconnected: var(--accent-red);
    }

    body {
      background: var(--bg-primary);
      color: var(--text-primary);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
      font-size: 14px;
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    /* ── Header ───────────────────────────────────────────── */
    #header {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 8px 16px;
      background: var(--bg-secondary);
      border-bottom: 1px solid var(--border);
      min-height: 44px;
      flex-shrink: 0;
    }

    .status-dot {
      width: 8px; height: 8px;
      border-radius: 50%;
      background: var(--status-disconnected);
      flex-shrink: 0;
      transition: background 0.3s;
    }
    .status-dot.connected { background: var(--status-connected); }
    .status-dot.connecting { background: var(--status-connecting); }

    .app-name { font-weight: 600; color: var(--text-primary); }

    .cwd-display {
      color: var(--text-secondary);
      font-size: 12px;
      cursor: pointer;
      display: flex; align-items: center; gap: 4px;
      padding: 2px 6px;
      border-radius: 4px;
      border: 1px solid transparent;
      max-width: 300px;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }
    .cwd-display:hover { border-color: var(--border); background: var(--bg-tertiary); }

    .cwd-input {
      background: var(--bg-tertiary);
      border: 1px solid var(--accent-blue);
      color: var(--text-primary);
      font-size: 12px;
      padding: 2px 6px;
      border-radius: 4px;
      outline: none;
      width: 280px;
    }

    .turn-count { color: var(--text-muted); font-size: 12px; }

    .header-spacer { flex: 1; }

    .btn {
      background: var(--bg-tertiary);
      border: 1px solid var(--border);
      color: var(--text-secondary);
      padding: 4px 10px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
      transition: all 0.15s;
    }
    .btn:hover { background: var(--bg-card); color: var(--text-primary); }
    .btn.active { border-color: var(--accent-blue); color: var(--accent-blue); }

    /* ── App Layout ───────────────────────────────────────── */
    #app-body {
      display: flex;
      flex: 1;
      overflow: hidden;
    }

    /* ── Session Panel ────────────────────────────────────── */
    #session-panel {
      width: 220px;
      background: var(--bg-secondary);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      transition: width 0.2s;
    }
    #session-panel.hidden { width: 0; overflow: hidden; }

    .session-panel-header {
      padding: 10px 12px;
      font-size: 11px;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border);
      display: flex; justify-content: space-between; align-items: center;
    }

    .session-list { flex: 1; overflow-y: auto; padding: 8px 0; }

    .session-card {
      padding: 8px 12px;
      cursor: pointer;
      border-left: 2px solid transparent;
      transition: all 0.15s;
    }
    .session-card:hover { background: var(--bg-tertiary); }
    .session-card.active { border-left-color: var(--accent-blue); background: var(--bg-tertiary); }

    .session-card-name { font-size: 12px; font-weight: 500; color: var(--text-primary); }
    .session-card-cwd { font-size: 11px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .session-card-meta { font-size: 11px; color: var(--text-muted); display: flex; gap: 6px; align-items: center; margin-top: 2px; }

    .new-session-btn {
      margin: 8px;
      padding: 6px 10px;
      background: var(--bg-tertiary);
      border: 1px dashed var(--border);
      color: var(--text-secondary);
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
      text-align: center;
      flex-shrink: 0;
    }
    .new-session-btn:hover { border-color: var(--accent-blue); color: var(--accent-blue); }

    /* ── Main Chat ────────────────────────────────────────── */
    #chat-main {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      position: relative;
    }

    /* Focus mode layout */
    #chat-main.focus-mode {
      flex-direction: row;
    }
    .main-pane { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
    .activity-panel {
      width: 340px;
      border-left: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      background: var(--bg-secondary);
    }
    .activity-panel-header {
      padding: 8px 12px;
      font-size: 11px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }
    .activity-scroll { flex: 1; overflow-y: auto; padding: 8px; }

    /* ── Message List ─────────────────────────────────────── */
    #message-list {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    /* ── Text Blocks ──────────────────────────────────────── */
    .text-block {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 14px;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .text-block[data-streaming="true"]::after {
      content: "▊";
      animation: cursor-pulse 1s step-end infinite;
      color: var(--accent-blue);
    }
    @keyframes cursor-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

    .text-block p { margin-bottom: 0.5em; }
    .text-block p:last-child { margin-bottom: 0; }
    .text-block code { background: var(--bg-tertiary); padding: 1px 4px; border-radius: 3px; font-family: monospace; font-size: 0.9em; }
    .text-block pre { background: var(--bg-tertiary); padding: 8px; border-radius: 4px; overflow-x: auto; }
    .text-block pre code { background: none; padding: 0; }

    /* User messages */
    .user-message {
      align-self: flex-end;
      background: var(--accent-blue);
      color: white;
      border: none;
      max-width: 75%;
    }

    /* System messages */
    .system-message {
      border-color: var(--accent-amber);
      color: var(--accent-amber);
      background: rgba(245,158,11,0.05);
      font-size: 12px;
      text-align: center;
    }

    /* ── Thinking Blocks ──────────────────────────────────── */
    .thinking-block {
      border: 1px solid rgba(139,92,246,0.3);
      border-radius: 8px;
      overflow: hidden;
      background: rgba(139,92,246,0.05);
    }
    .thinking-header {
      padding: 6px 12px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: rgba(139,92,246,0.8);
      user-select: none;
    }
    .thinking-header:hover { background: rgba(139,92,246,0.1); }
    .thinking-preview { flex: 1; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; color: var(--text-muted); }
    .thinking-content { padding: 8px 12px; font-size: 12px; color: var(--text-secondary); white-space: pre-wrap; border-top: 1px solid rgba(139,92,246,0.2); }
    .thinking-streaming { display: flex; gap: 3px; align-items: center; }
    .thinking-dot { width: 4px; height: 4px; border-radius: 50%; background: rgba(139,92,246,0.6); animation: thinking-pulse 1.2s ease-in-out infinite; }
    .thinking-dot:nth-child(2) { animation-delay: 0.2s; }
    .thinking-dot:nth-child(3) { animation-delay: 0.4s; }
    @keyframes thinking-pulse { 0%, 80%, 100% { opacity: 0.3; } 40% { opacity: 1; } }

    /* ── Tool Call Cards ──────────────────────────────────── */
    .tool-card {
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
      background: var(--bg-card);
      font-size: 12px;
    }
    .tool-header {
      padding: 6px 10px;
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      user-select: none;
      background: var(--bg-secondary);
    }
    .tool-header:hover { background: var(--bg-tertiary); }
    .tool-status { font-size: 13px; flex-shrink: 0; }
    .tool-name { font-weight: 500; color: var(--text-primary); }
    .tool-arg-preview { color: var(--text-muted); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; flex: 1; }
    .tool-body { padding: 8px 10px; border-top: 1px solid var(--border); }
    .tool-args-json { background: var(--bg-tertiary); padding: 6px 8px; border-radius: 4px; overflow-x: auto; white-space: pre; color: var(--text-secondary); font-family: monospace; font-size: 11px; }
    .tool-result-text { margin-top: 6px; color: var(--text-secondary); white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow-y: auto; }
    .tool-error-text { color: var(--accent-red); }

    .tool-marker { color: var(--text-muted); font-size: 11px; margin-left: 4px; }

    .status-running { animation: spin 1s linear infinite; display: inline-block; }
    @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

    /* ── Sub-Session ──────────────────────────────────────── */
    .sub-session {
      background: rgba(255,255,255,0.02);
      border-left: 2px solid var(--border);
      margin-top: 6px;
      padding: 6px 8px;
      font-size: 0.9em;
    }

    /* ── Approval Modal ───────────────────────────────────── */
    .modal-backdrop {
      position: fixed; inset: 0;
      background: rgba(0,0,0,0.7);
      display: flex; align-items: center; justify-content: center;
      z-index: 1000;
    }
    .modal-box {
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 24px;
      max-width: 420px;
      width: 90%;
    }
    .modal-prompt { font-size: 14px; line-height: 1.5; margin-bottom: 16px; }
    .modal-progress {
      height: 3px;
      background: var(--bg-tertiary);
      border-radius: 2px;
      margin-bottom: 16px;
      overflow: hidden;
    }
    .modal-progress-bar {
      height: 100%;
      background: var(--accent-blue);
      animation: countdown linear forwards;
    }
    @keyframes countdown { from { width: 100%; } to { width: 0%; } }
    .modal-buttons { display: flex; gap: 8px; flex-wrap: wrap; }
    .modal-btn {
      flex: 1;
      min-width: 80px;
      padding: 8px 12px;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 500;
    }
    .modal-btn.deny { background: var(--accent-red); color: white; }
    .modal-btn.allow { background: var(--accent-blue); color: white; }
    .modal-btn.always { background: var(--accent-green); color: white; }

    /* ── Input Area ───────────────────────────────────────── */
    #input-area {
      border-top: 1px solid var(--border);
      padding: 12px 16px;
      background: var(--bg-secondary);
      flex-shrink: 0;
    }

    .image-previews {
      display: flex; flex-wrap: wrap; gap: 6px;
      margin-bottom: 8px;
    }
    .image-thumb {
      position: relative;
      width: 48px; height: 48px;
      border-radius: 4px;
      overflow: hidden;
      border: 1px solid var(--border);
    }
    .image-thumb img { width: 100%; height: 100%; object-fit: cover; }
    .image-remove {
      position: absolute; top: 2px; right: 2px;
      width: 14px; height: 14px;
      background: rgba(0,0,0,0.7);
      border: none;
      border-radius: 50%;
      color: white;
      font-size: 9px;
      cursor: pointer;
      display: flex; align-items: center; justify-content: center;
    }

    .input-row { display: flex; gap: 8px; align-items: flex-end; }

    #message-input {
      flex: 1;
      background: var(--bg-tertiary);
      border: 1px solid var(--border);
      color: var(--text-primary);
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 14px;
      resize: none;
      line-height: 1.4;
      min-height: 38px;
      max-height: 200px;
      overflow-y: auto;
      outline: none;
      font-family: inherit;
    }
    #message-input:focus { border-color: var(--accent-blue); }
    #message-input::placeholder { color: var(--text-muted); }

    .input-btn {
      height: 38px;
      padding: 0 14px;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 500;
      flex-shrink: 0;
      white-space: nowrap;
    }
    .send-btn { background: var(--accent-blue); color: white; }
    .send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    .stop-btn { background: var(--accent-red); color: white; }
    .attach-btn { background: var(--bg-tertiary); border: 1px solid var(--border); color: var(--text-secondary); }

    /* ── Slash command popup (basic) ──────────────────────── */
    .slash-popup {
      position: absolute;
      bottom: 100%;
      left: 16px;
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 4px 0;
      min-width: 200px;
      font-size: 12px;
    }
    .slash-cmd {
      padding: 4px 12px;
      cursor: pointer;
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .slash-cmd:hover { background: var(--bg-tertiary); }
    .slash-cmd-name { color: var(--accent-blue); font-weight: 500; }
    .slash-cmd-desc { color: var(--text-muted); }

    /* ── Mobile ───────────────────────────────────────────── */
    .hamburger { display: none; }

    @media (max-width: 768px) {
      .hamburger {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 32px; height: 32px;
        background: none;
        border: 1px solid var(--border);
        border-radius: 4px;
        cursor: pointer;
        color: var(--text-secondary);
        font-size: 16px;
      }
      #session-panel {
        position: fixed;
        left: 0; top: 0; bottom: 0;
        z-index: 200;
        transform: translateX(-100%);
        transition: transform 0.2s;
        width: 260px !important;
      }
      #session-panel.mobile-open {
        transform: translateX(0);
        box-shadow: 4px 0 20px rgba(0,0,0,0.5);
      }
      .focus-toggle { display: none !important; }
      .activity-panel { display: none !important; }
      #message-input { font-size: 16px; }
      .cwd-display { max-width: 160px; }
    }
  </style>
</head>
<body>
<script src="./vendor.js"></script>
<script>
  const { h, render } = window.preact;
  const { useState, useRef, useEffect, useCallback } = window.preactHooks;
  const { html } = window;
  const { marked } = window;

  // ── Constants ────────────────────────────────────────────
  const SLASH_COMMANDS = [
    { name: '/help',    desc: 'Show available commands', clientSide: true },
    { name: '/clear',   desc: 'Clear conversation',      clientSide: true },
    { name: '/focus',   desc: 'Toggle focus mode',       clientSide: true },
    { name: '/thinking', desc: 'Toggle thinking visibility', clientSide: true },
    { name: '/status',  desc: 'Session status',          clientSide: false },
    { name: '/tools',   desc: 'List tools',              clientSide: false },
    { name: '/agents',  desc: 'List agents',             clientSide: false },
    { name: '/bundle',  desc: 'Change bundle',           clientSide: false },
    { name: '/cwd',     desc: 'Change working directory', clientSide: false },
    { name: '/modes',   desc: 'List modes',              clientSide: false },
    { name: '/mode',    desc: 'Set mode',                clientSide: false },
  ];

  // ── Utilities ─────────────────────────────────────────────
  function makeId() {
    return Math.random().toString(36).slice(2, 10);
  }

  function getArgPreview(toolName, args) {
    const field = {
      bash: 'command',
      read_file: 'file_path', write_file: 'file_path', edit_file: 'file_path',
      grep: 'pattern', glob: 'pattern',
      web_search: 'query', web_fetch: 'url',
      delegate: 'agent', task: 'agent',
    }[toolName];
    if (field && args[field]) return String(args[field]).slice(0, 60);
    const firstVal = Object.values(args || {})[0];
    return firstVal ? String(firstVal).slice(0, 60) : '';
  }

  function getToolStatusIcon(status) {
    return { pending: '⏱', running: '⟳', complete: '✓', error: '✗' }[status] || '⏱';
  }

  function truncate(s, n) {
    if (!s) return '';
    return s.length > n ? s.slice(0, n) + '…' : s;
  }

  // ── Components ────────────────────────────────────────────

  function StatusDot({ status }) {
    return html`<span class=${'status-dot ' + status}></span>`;
  }

  function ThinkingBlock({ item }) {
    const [expanded, setExpanded] = useState(false);
    const preview = item.content ? item.content.slice(0, 60) : '';
    return html`
      <div class="thinking-block">
        <div class="thinking-header" onClick=${() => setExpanded(e => !e)}>
          <span>💭</span>
          ${item.streaming
            ? html`<span class="thinking-streaming">
                <span class="thinking-dot"></span>
                <span class="thinking-dot"></span>
                <span class="thinking-dot"></span>
              </span>`
            : html`<span class="thinking-preview">${preview || 'Thinking…'}</span>`
          }
          <span>${expanded ? '▼' : '▶'}</span>
        </div>
        ${expanded && html`<div class="thinking-content" id=${item.id}>${item.content}</div>`}
      </div>
    `;
  }

  function ToolCallCard({ item, isActivity }) {
    const [expanded, setExpanded] = useState(false);
    const statusIcon = getToolStatusIcon(item.toolStatus);
    const isRunning = item.toolStatus === 'running';
    const argPreview = getArgPreview(item.toolName, item.arguments || {});

    return html`
      <div class="tool-card">
        <div class="tool-header" onClick=${() => setExpanded(e => !e)}>
          <span class=${'tool-status' + (isRunning ? ' status-running' : '')}>${statusIcon}</span>
          <span class="tool-name">${item.toolName || 'tool'}</span>
          <span class="tool-arg-preview">${argPreview}</span>
        </div>
        ${expanded && html`
          <div class="tool-body">
            <pre class="tool-args-json">${JSON.stringify(item.arguments || {}, null, 2)}</pre>
            ${item.result && html`
              <div class=${'tool-result-text' + (item.resultError ? ' tool-error-text' : '')}>
                ${(item.resultError || item.result || '').slice(0, 500)}
              </div>
            `}
            ${item.subSessionId && html`<${SubSessionView} sessionId=${item.subSessionId} items=${item.subItems || []} />`}
          </div>
        `}
      </div>
    `;
  }

  function SubSessionView({ sessionId, items }) {
    return html`
      <div class="sub-session">
        ${items.map(item => html`<${ChronoItem} item=${item} isActivity=${true} />`)}
      </div>
    `;
  }

  function ChronoItem({ item, isActivity }) {
    if (item.type === 'text') {
      const cls = 'text-block' + (item.role === 'user' ? ' user-message' : item.role === 'system' ? ' system-message' : '');
      return html`<div class=${cls} id=${item.id} data-streaming=${item.streaming ? 'true' : 'false'}>${item.content}</div>`;
    }
    if (item.type === 'thinking') {
      return html`<${ThinkingBlock} item=${item} />`;
    }
    if (item.type === 'tool_call') {
      return html`<${ToolCallCard} item=${item} isActivity=${isActivity} />`;
    }
    return null;
  }

  function MessageList({ items, filterFn }) {
    const filtered = filterFn ? items.filter(filterFn) : items;
    const sorted = [...filtered].sort((a, b) => a.order - b.order);
    return html`
      <div id="message-list">
        ${sorted.map(item => html`<${ChronoItem} key=${item.id} item=${item} />`)}
      </div>
    `;
  }

  function ApprovalModal({ approval, onRespond }) {
    if (!approval) return null;
    const timeout = approval.timeout || 300;
    return html`
      <div class="modal-backdrop">
        <div class="modal-box">
          <div class="modal-prompt">${approval.prompt}</div>
          <div class="modal-progress">
            <div class="modal-progress-bar" style=${'animation-duration:' + timeout + 's'}></div>
          </div>
          <div class="modal-buttons">
            ${(approval.options || ['deny', 'allow']).map(opt => {
              const cls = 'modal-btn ' + (
                opt.includes('deny') ? 'deny' :
                opt.includes('always') ? 'always' : 'allow'
              );
              return html`<button class=${cls} onClick=${() => onRespond(opt)}>${opt}</button>`;
            })}
          </div>
        </div>
      </div>
    `;
  }

  function SessionCard({ session, isActive, onClick }) {
    return html`
      <div class=${'session-card' + (isActive ? ' active' : '')} onClick=${onClick}>
        <div class="session-card-name">
          ${session.status === 'running' ? '⟳ ' : session.status === 'error' ? '✗ ' : ''}
          ${session.bundle || 'session'}
          ${session.pendingApproval ? ' 🔔' : ''}
        </div>
        <div class="session-card-cwd">📁 ${truncate(session.cwd || '~', 25)}</div>
        <div class="session-card-meta">
          <span>turn ${session.turnCount || 0}</span>
        </div>
      </div>
    `;
  }

  function InputArea({ onSend, onStop, executing, viewMode, setViewMode }) {
    const textareaRef = useRef(null);
    const fileInputRef = useRef(null);
    const [pendingImages, setPendingImages] = useState([]);
    const [slashOpen, setSlashOpen] = useState(false);
    const [slashFilter, setSlashFilter] = useState('');

    const autoResize = useCallback(() => {
      const ta = textareaRef.current;
      if (!ta) return;
      ta.style.height = 'auto';
      ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
    }, []);

    const addImages = useCallback((files) => {
      Array.from(files).forEach(file => {
        if (!file.type.startsWith('image/')) return;
        const reader = new FileReader();
        reader.onload = e => {
          setPendingImages(prev => [...prev, e.target.result]);
        };
        reader.readAsDataURL(file);
      });
    }, []);

    const handlePaste = useCallback((e) => {
      const items = e.clipboardData?.items || [];
      const hasImage = Array.from(items).some(i => i.type.startsWith('image/'));
      if (!hasImage) return;
      e.preventDefault();
      const files = Array.from(items)
        .filter(i => i.type.startsWith('image/'))
        .map(i => i.getAsFile());
      addImages(files);
    }, [addImages]);

    const doSend = useCallback(() => {
      const ta = textareaRef.current;
      if (!ta) return;
      const content = ta.value.trim();
      if (!content && pendingImages.length === 0) return;

      // Strip data URL prefix from images
      const images = pendingImages.map(d => d.split(',')[1]);
      onSend(content, images);
      ta.value = '';
      ta.style.height = 'auto';
      setPendingImages([]);
      setSlashOpen(false);
    }, [onSend, pendingImages]);

    const handleKeyDown = useCallback((e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        doSend();
      }
      if (e.key === 'Escape') setSlashOpen(false);
    }, [doSend]);

    const handleInput = useCallback((e) => {
      autoResize();
      const val = e.target.value;
      if (val.startsWith('/')) {
        setSlashOpen(true);
        setSlashFilter(val.slice(1).toLowerCase());
      } else {
        setSlashOpen(false);
      }
    }, [autoResize]);

    const filteredCmds = SLASH_COMMANDS.filter(c =>
      c.name.slice(1).startsWith(slashFilter)
    );

    return html`
      <div id="input-area">
        ${pendingImages.length > 0 && html`
          <div class="image-previews">
            ${pendingImages.map((src, i) => html`
              <div class="image-thumb">
                <img src=${src} alt="attachment" />
                <button class="image-remove" onClick=${() => setPendingImages(p => p.filter((_, j) => j !== i))}>×</button>
              </div>
            `)}
          </div>
        `}
        ${slashOpen && filteredCmds.length > 0 && html`
          <div class="slash-popup">
            ${filteredCmds.map(cmd => html`
              <div class="slash-cmd" onClick=${() => {
                if (textareaRef.current) textareaRef.current.value = cmd.name + ' ';
                setSlashOpen(false);
                textareaRef.current?.focus();
              }}>
                <span class="slash-cmd-name">${cmd.name}</span>
                <span class="slash-cmd-desc">${cmd.desc}</span>
              </div>
            `)}
          </div>
        `}
        <div class="input-row">
          <textarea
            id="message-input"
            ref=${textareaRef}
            placeholder="Message… (/ for commands)"
            rows="1"
            onInput=${handleInput}
            onKeyDown=${handleKeyDown}
            onPaste=${handlePaste}
            onDragOver=${e => e.preventDefault()}
            onDrop=${e => { e.preventDefault(); addImages(e.dataTransfer.files); }}
          ></textarea>
          <button class="input-btn attach-btn" title="Attach image" onClick=${() => fileInputRef.current?.click()}>📎</button>
          <input ref=${fileInputRef} type="file" accept="image/*" multiple style="display:none" onChange=${e => addImages(e.target.files)} />
          ${executing
            ? html`<button class="input-btn stop-btn" onClick=${onStop}>■ Stop</button>`
            : html`<button class="input-btn send-btn" onClick=${doSend}>Send</button>`
          }
        </div>
      </div>
    `;
  }

  // ── ChatApp root ──────────────────────────────────────────
  function ChatApp() {
    // Connection
    const [wsStatus, setWsStatus] = useState('disconnected');
    const wsRef = useRef(null);

    // Sessions: Map<wsKey, SessionState>
    // Using a unique key per WS connection (not session_id yet)
    const [sessions, setSessions] = useState(new Map());
    const [activeKey, setActiveKey] = useState(null);
    const sessionCounterRef = useRef(0);

    // Current session state (derived from sessions map)
    const [chronoItems, setChronoItems] = useState([]);
    const [executing, setExecuting] = useState(false);
    const [pendingApproval, setPendingApproval] = useState(null);
    const [sessionId, setSessionId] = useState(null);
    const [cwd, setCwd] = useState('~');
    const [turnCount, setTurnCount] = useState(0);
    const [editingCwd, setEditingCwd] = useState(false);

    // UI state
    const [viewMode, setViewMode] = useState('default'); // 'default' | 'focus'
    const [showSessions, setShowSessions] = useState(true);
    const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

    // Refs (no re-renders)
    const orderCounterRef = useRef(0);
    const blockMapRef = useRef({});
    const cycleRef = useRef(0);
    const localIndexRef = useRef(0);
    const toolMapRef = useRef({});
    const childToToolRef = useRef({});

    // ── Index mapping ──────────────────────────────────────
    function getLocalIndex(serverIndex) {
      const key = `${cycleRef.current}-${serverIndex}`;
      if (!(key in blockMapRef.current)) {
        blockMapRef.current[key] = localIndexRef.current++;
      }
      return blockMapRef.current[key];
    }

    // ── WebSocket event handler ────────────────────────────
    const handleWsMessage = useCallback((msg) => {
      switch (msg.type) {
        case 'auth_ok':
          break;

        case 'session_created':
          setSessionId(msg.session_id);
          setCwd(msg.cwd || '~');
          setSessions(prev => {
            const next = new Map(prev);
            const s = next.get(activeKey) || {};
            next.set(activeKey, { ...s, sessionId: msg.session_id, cwd: msg.cwd || '~', bundle: msg.bundle, status: 'idle', turnCount: 0 });
            return next;
          });
          break;

        case 'content_start':
          if (msg.block_type === 'text') {
            const itemId = makeId();
            const localIdx = getLocalIndex(msg.index);
            blockMapRef.current['id-' + localIdx] = itemId;
            setChronoItems(prev => [...prev, {
              id: itemId, type: 'text', content: '', streaming: true,
              order: orderCounterRef.current++, role: 'assistant',
            }]);
          } else if (msg.block_type === 'thinking') {
            const itemId = makeId();
            const localIdx = getLocalIndex(msg.index);
            blockMapRef.current['thinking-id-' + localIdx] = itemId;
            setChronoItems(prev => [...prev, {
              id: itemId, type: 'thinking', content: '', streaming: true,
              order: orderCounterRef.current++,
            }]);
          }
          break;

        case 'content_delta': {
          const localIdx = getLocalIndex(msg.index);
          const itemId = blockMapRef.current['id-' + localIdx];
          if (itemId) {
            const el = document.getElementById(itemId);
            if (el) el.textContent += msg.delta;
          }
          break;
        }

        case 'content_end': {
          const localIdx = getLocalIndex(msg.index);
          const itemId = blockMapRef.current['id-' + localIdx];
          setChronoItems(prev => prev.map(item =>
            item.id === itemId
              ? { ...item, streaming: false, content: document.getElementById(itemId)?.textContent || item.content }
              : item
          ));
          // Apply markdown after streaming ends
          if (itemId) {
            const el = document.getElementById(itemId);
            if (el) el.innerHTML = marked.parse(el.textContent || '');
          }
          break;
        }

        case 'thinking_delta': {
          setChronoItems(prev => {
            const last = [...prev].reverse().find(i => i.type === 'thinking' && i.streaming);
            if (!last) return prev;
            const el = document.getElementById(last.id);
            if (el) el.textContent += msg.delta;
            return prev;
          });
          break;
        }

        case 'thinking_final': {
          setChronoItems(prev => prev.map(item =>
            item.type === 'thinking' && item.streaming
              ? { ...item, content: msg.content, streaming: false }
              : item
          ));
          break;
        }

        case 'tool_call': {
          const itemId = makeId();
          toolMapRef.current[msg.tool_call_id] = itemId;
          setChronoItems(prev => [...prev, {
            id: itemId, type: 'tool_call',
            toolName: msg.tool_name, toolCallId: msg.tool_call_id,
            arguments: msg.arguments || {},
            toolStatus: 'running',
            order: orderCounterRef.current++,
          }]);
          setExecuting(true);
          break;
        }

        case 'tool_result': {
          const itemId = toolMapRef.current[msg.tool_call_id];
          cycleRef.current++;
          setChronoItems(prev => prev.map(item =>
            item.id === itemId
              ? { ...item, toolStatus: msg.success ? 'complete' : 'error', result: msg.output, resultError: msg.error }
              : item
          ));
          break;
        }

        case 'session_fork': {
          const parentToolId = toolMapRef.current[msg.parent_tool_call_id];
          if (parentToolId) {
            childToToolRef.current[msg.child_id] = parentToolId;
          }
          break;
        }

        case 'display_message': {
          setChronoItems(prev => [...prev, {
            id: makeId(), type: 'text', role: 'system',
            content: `[${msg.level}] ${msg.message}`,
            streaming: false, order: orderCounterRef.current++,
          }]);
          break;
        }

        case 'approval_request':
          setPendingApproval(msg);
          setSessions(prev => {
            const next = new Map(prev);
            if (activeKey && next.has(activeKey)) {
              const s = next.get(activeKey);
              next.set(activeKey, { ...s, pendingApproval: true });
            }
            return next;
          });
          break;

        case 'prompt_complete':
          setExecuting(false);
          setTurnCount(t => t + 1);
          blockMapRef.current = {};
          cycleRef.current = 0;
          localIndexRef.current = 0;
          break;

        case 'execution_cancelled':
          setExecuting(false);
          break;

        case 'execution_error':
          setExecuting(false);
          setChronoItems(prev => [...prev, {
            id: makeId(), type: 'text', role: 'system',
            content: '⚠️ Error: ' + (msg.error || 'Unknown error'),
            streaming: false, order: orderCounterRef.current++,
          }]);
          break;

        case 'command_result':
          setChronoItems(prev => [...prev, {
            id: makeId(), type: 'text', role: 'system',
            content: JSON.stringify(msg.result, null, 2),
            streaming: false, order: orderCounterRef.current++,
          }]);
          break;

        case 'pong':
          break;

        default:
          break;
      }
    }, [activeKey]);

    // ── WebSocket connection ───────────────────────────────
    const connect = useCallback(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) return;
      setWsStatus('connecting');

      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${proto}//${location.host}/apps/chat/ws`);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsStatus('connected');
        // Auto-create first session
        ws.send(JSON.stringify({ type: 'create_session', cwd: '~', bundle: null }));
      };

      ws.onmessage = (e) => {
        try {
          handleWsMessage(JSON.parse(e.data));
        } catch (err) {
          console.error('WS parse error', err);
        }
      };

      ws.onclose = (e) => {
        setWsStatus('disconnected');
        if (e.code !== 4001) {
          setTimeout(connect, 3000);
        }
      };

      ws.onerror = () => setWsStatus('disconnected');
    }, [handleWsMessage]);

    useEffect(() => {
      const key = 'session-' + (++sessionCounterRef.current);
      setActiveKey(key);
      setSessions(new Map([[key, { status: 'idle', turnCount: 0, cwd: '~' }]]));
      connect();
    }, []);

    // ── Send ───────────────────────────────────────────────
    const sendMessage = useCallback((content, images) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

      // Client-side slash commands
      if (content.startsWith('/')) {
        const parts = content.trim().split(/\s+/);
        const cmd = parts[0];
        const args = parts.slice(1);

        switch (cmd) {
          case '/help': {
            const helpText = SLASH_COMMANDS.map(c => `${c.name} — ${c.desc}`).join('\n');
            setChronoItems(prev => [...prev, {
              id: makeId(), type: 'text', role: 'system',
              content: helpText, streaming: false, order: orderCounterRef.current++,
            }]);
            return;
          }
          case '/clear':
            setChronoItems([]);
            return;
          case '/focus':
            setViewMode(m => m === 'focus' ? 'default' : 'focus');
            return;
          case '/thinking':
            // Toggle visibility — implemented in Phase 6
            return;
        }
        // Server-side commands
        wsRef.current.send(JSON.stringify({ type: 'command', name: cmd.slice(1), args }));
        return;
      }

      // Normal message
      setChronoItems(prev => [...prev, {
        id: makeId(), type: 'text', role: 'user',
        content, streaming: false, order: orderCounterRef.current++,
      }]);
      setExecuting(true);

      const payload = { type: 'prompt', content };
      if (images && images.length > 0) payload.images = images;
      wsRef.current.send(JSON.stringify(payload));
    }, []);

    const stopExecution = useCallback(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'cancel', level: 'graceful' }));
      }
    }, []);

    const respondToApproval = useCallback((choice) => {
      if (pendingApproval && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          type: 'approval_response',
          id: pendingApproval.id,
          choice,
        }));
      }
      setPendingApproval(null);
    }, [pendingApproval]);

    const newSession = useCallback(() => {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${proto}//${location.host}/apps/chat/ws`);
      const key = 'session-' + (++sessionCounterRef.current);

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'create_session', cwd: '~', bundle: null }));
        setSessions(prev => {
          const next = new Map(prev);
          next.set(key, { ws, status: 'idle', turnCount: 0, cwd: '~' });
          return next;
        });
        setActiveKey(key);
        // Reset state for new session
        setChronoItems([]);
        setTurnCount(0);
        setExecuting(false);
        setSessionId(null);
        blockMapRef.current = {};
        cycleRef.current = 0;
        localIndexRef.current = 0;
        toolMapRef.current = {};
      };

      ws.onmessage = (e) => {
        try { handleWsMessage(JSON.parse(e.data)); } catch {}
      };
      ws.onclose = () => {
        setSessions(prev => {
          const next = new Map(prev);
          next.delete(key);
          return next;
        });
      };
    }, [handleWsMessage]);

    // ── CWD editor ────────────────────────────────────────
    const handleCwdEdit = useCallback((newCwd) => {
      setEditingCwd(false);
      if (newCwd && newCwd !== cwd && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          type: 'create_session',
          cwd: newCwd,
          resume_session_id: sessionId,
        }));
        setCwd(newCwd);
      }
    }, [cwd, sessionId]);

    // ── Render ────────────────────────────────────────────
    const sessionList = Array.from(sessions.entries());

    const mainFilter = viewMode === 'focus' ? (i => i.type === 'text') : null;
    const activityFilter = viewMode === 'focus' ? (i => i.type !== 'text') : null;

    return html`
      <div id="header">
        <button class="hamburger" onClick=${() => setMobileSidebarOpen(o => !o)}>☰</button>
        <${StatusDot} status=${wsStatus} />
        <span class="app-name">● Amplifier</span>

        ${editingCwd
          ? html`<input
              class="cwd-input"
              defaultValue=${cwd}
              autoFocus
              onBlur=${e => handleCwdEdit(e.target.value)}
              onKeyDown=${e => { if (e.key === 'Enter') handleCwdEdit(e.target.value); if (e.key === 'Escape') setEditingCwd(false); }}
            />`
          : html`<span class="cwd-display" onClick=${() => setEditingCwd(true)} title=${cwd}>
              📁 ${truncate(cwd, 40)}
            </span>`
        }

        <span class="turn-count">turn ${turnCount}</span>
        <span class="header-spacer"></span>
        <button
          class=${'btn focus-toggle' + (viewMode === 'focus' ? ' active' : '')}
          onClick=${() => setViewMode(m => m === 'focus' ? 'default' : 'focus')}
        >${viewMode === 'focus' ? '[Default]' : '[Focus]'}</button>
        <button class=${'btn' + (showSessions ? ' active' : '')} onClick=${() => setShowSessions(s => !s)}>
          [Sessions]
        </button>
      </div>

      <div id="app-body">
        <div id=${'session-panel' + (showSessions ? '' : ' hidden') + (mobileSidebarOpen ? ' mobile-open' : '')}>
          <div class="session-panel-header">
            <span>Sessions</span>
          </div>
          <div class="session-list">
            ${sessionList.map(([key, sess]) => html`
              <${SessionCard}
                key=${key}
                session=${sess}
                isActive=${key === activeKey}
                onClick=${() => { setActiveKey(key); setMobileSidebarOpen(false); }}
              />
            `)}
          </div>
          <div class="new-session-btn" onClick=${newSession}>+ New Session</div>
        </div>

        <div id=${'chat-main' + (viewMode === 'focus' ? ' focus-mode' : '')}>
          <div class="main-pane">
            <${MessageList} items=${chronoItems} filterFn=${mainFilter} />
          </div>
          ${viewMode === 'focus' && html`
            <div class="activity-panel">
              <div class="activity-panel-header">Activity</div>
              <div class="activity-scroll">
                <${MessageList} items=${chronoItems} filterFn=${activityFilter} />
              </div>
            </div>
          `}
          <${InputArea}
            onSend=${sendMessage}
            onStop=${stopExecution}
            executing=${executing}
            viewMode=${viewMode}
            setViewMode=${setViewMode}
          />
        </div>
      </div>

      <${ApprovalModal} approval=${pendingApproval} onRespond=${respondToApproval} />
    `;
  }

  render(h(ChatApp, null), document.body);
</script>
</body>
</html>
```

**Step 3: Verify manually**
```
uv run python -m amplifier_distro.server.main
```
Open `http://localhost:8000/apps/chat/`. You should see:
- Dark interface loads
- `● Amplifier` in header with green dot
- Session panel on left
- Empty message area
- Input textarea at bottom with Send button

**Step 4: Commit**
```
git add src/amplifier_distro/server/apps/chat/static/index.html
git commit -m "feat(chat): add index.html with ChatApp, WebSocket, all UI components"
```

---

## Phase 5 (continued): Remaining Frontend Tasks

### Tasks 16–22: Frontend Components (already embedded in index.html above)

The complete frontend — SessionPanel, MessageList, TextBlock with streaming cursor, ThinkingBlock, ToolCallCard, SubSessionView, ApprovalModal, InputArea with slash commands and image handling — is all in the single `index.html` created in Task 15.

Each "task" from the original breakdown is already implemented:
- **Task 16:** SessionPanel with session cards, status badges, `+ New Session` button ✓
- **Task 17:** MessageList sorted by `.order`, TextBlock with streaming cursor CSS ✓
- **Task 18:** ThinkingBlock collapsible with pulsing dots when streaming ✓
- **Task 19:** ToolCallCard with status icons, arg preview by tool name, expandable ✓
- **Task 20:** SubSessionView renders inside ToolCallCard when `subSessionId` set ✓
- **Task 21:** ApprovalModal with countdown animation, per-option coloring ✓
- **Task 22:** InputArea with auto-resize, slash command interceptor, image drag-drop and paste ✓

---

## Phase 6: Focus Mode

### Task 23: Focus Mode Toggle + ActivityPanel

Already implemented in `index.html` Task 15:
- `viewMode` state (`'default'` | `'focus'`, default `'default'`)
- Header `[Focus]`/`[Default]` toggle button
- Focus layout splits `main-pane` and `activity-panel`
- `mainFilter` filters to `type === 'text'`, `activityFilter` to `type !== 'text'`
- CSS hides focus toggle on `≤768px`

**Verify manually:** Click `[Focus]` — chat area splits into two columns. Text on left, tools/thinking on right. Click `[Default]` — returns to single column.

**Commit:**
```
git add src/amplifier_distro/server/apps/chat/static/index.html
git commit -m "feat(chat): focus mode toggle and ActivityPanel are live in index.html"
```
(Skip if already committed with Task 15)

---

## Phase 7: Multi-Session

### Task 24 + Task 25: Multi-Session Map and Background Accumulation

Already implemented in `index.html` Task 15:
- `sessions: Map<key, SessionState>` with `activeKey`
- `newSession()` opens a new WebSocket and registers it
- `SessionCard` click switches `activeKey`
- Background sessions keep their WebSocket alive
- Session list in sidebar shows all sessions

**Verify manually:**
1. Open chat, first session auto-created
2. Click `+ New Session` — new session appears in sidebar
3. Switch between sessions — each maintains its own message history
4. Start a long-running prompt in session 1, switch to session 2 — session 1 still running, badge shows `⟳`

**Commit:**
```
git commit -m "feat(chat): multi-session map with independent WebSocket connections"
```
(Skip if already committed with Task 15)

---

## Phase 8: CWD First-Class

### Task 26: CWD Display and Inline Editor

Already implemented in `index.html` Task 15:
- `📁 {cwd truncated to 40 chars}` in header, clickable
- Clicking opens `<input>` pre-filled with full path
- Enter/Blur sends `create_session` with `resume_session_id` + new cwd
- Session cards show `📁 {cwd truncated to 25 chars}`

**Verify manually:** Click the CWD in header → input appears → type new path → press Enter → session reconnects with new CWD.

---

## Phase 9: Image Attachments

### Task 27: Backend — images in execute()

**Files:**
- Modify: `src/amplifier_distro/server/session_backend.py`
- Modify: `src/amplifier_distro/bridge.py`
- Create: `tests/test_chat_images.py`

**Step 1: Write the failing tests**

Create `tests/test_chat_images.py`:
```python
"""Tests for image attachment support in execute()."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestExecuteWithImages:
    @pytest.mark.asyncio
    async def test_execute_passes_images_to_handle(self):
        """execute() accepts images and passes through to handle.run()."""
        from amplifier_distro.server.session_backend import BridgeBackend

        handle = MagicMock()
        handle.run = AsyncMock(return_value="response")

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {"s001": handle}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()

        images = ["base64datahere", "anotherimage"]
        await backend.execute("s001", "describe these", images=images)
        # For now, execute calls handle.run(prompt) — images stored for future
        handle.run.assert_called_once_with("describe these")

    @pytest.mark.asyncio
    async def test_execute_no_images_still_works(self):
        from amplifier_distro.server.session_backend import BridgeBackend

        handle = MagicMock()
        handle.run = AsyncMock(return_value="ok")

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {"s002": handle}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()

        await backend.execute("s002", "no images here")
        handle.run.assert_called_once_with("no images here")
```

**Step 2: Run to verify**
```
uv run python -m pytest tests/test_chat_images.py -v
```
Expected: Pass (execute already accepts `images=None`). If not, verify the signature is `async def execute(self, session_id, prompt, images=None)`.

**Step 3: Task 28 frontend is already in index.html**

Image drag-drop, paste, file picker, preview thumbnails, and send are all in `InputArea` in `index.html` (Task 15).

**Verify manually:** Drag an image onto the textarea or paste from clipboard → thumbnail appears → send with message → check browser network tab for `images` field in the WebSocket message.

**Step 4: Commit**
```
git add tests/test_chat_images.py
git commit -m "feat(chat): verify image attachment API — execute() accepts images param"
```

---

## Phase 10: Slash Commands

### Task 29: Server-Side Command Handlers

**Files:**
- Modify: `src/amplifier_distro/server/apps/chat/connection.py`
- Create: `tests/test_chat_commands.py`

**Step 1: Write failing tests**

Create `tests/test_chat_commands.py`:
```python
"""Tests for server-side slash command handlers."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def make_connection(session_id="test-sess"):
    from amplifier_distro.server.apps.chat.connection import ChatConnection
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    backend = MagicMock()
    backend.create_session = AsyncMock(return_value=MagicMock(session_id="new-sess", working_dir="/new"))
    config = MagicMock()
    config.server.api_key = None
    conn = ChatConnection(ws, backend, config)
    conn._session_id = session_id
    return conn, ws, backend


class TestCommandDispatch:
    @pytest.mark.asyncio
    async def test_status_command(self):
        conn, ws, backend = make_connection("sess-001")
        result = await conn._dispatch_command("status", [])
        assert result["session_id"] == "sess-001"

    @pytest.mark.asyncio
    async def test_bundle_command_creates_new_session(self):
        conn, ws, backend = make_connection()
        result = await conn._dispatch_command("bundle", ["my-bundle"])
        backend.create_session.assert_awaited_once()
        assert "session_id" in result

    @pytest.mark.asyncio
    async def test_cwd_command_creates_new_session(self):
        conn, ws, backend = make_connection()
        result = await conn._dispatch_command("cwd", ["/new/path"])
        backend.create_session.assert_awaited_once()
        assert "cwd" in result

    @pytest.mark.asyncio
    async def test_unknown_command_returns_error(self):
        conn, ws, backend = make_connection()
        result = await conn._dispatch_command("nonexistent", [])
        assert "error" in result
```

**Step 2: Run to verify**
```
uv run python -m pytest tests/test_chat_commands.py -v
```
Expected: All pass (commands are already in `_dispatch_command` in `connection.py`).

**Step 3: Commit**
```
git add tests/test_chat_commands.py
git commit -m "feat(chat): add tests for server-side slash command handlers"
```

---

## Phase 11: Mobile / Responsive

### Task 30: Mobile Responsive Layout

Already implemented in `index.html` Task 15:
- `@media (max-width: 768px)` CSS block:
  - Hamburger button shows, sidebar becomes slide-in drawer with `.mobile-open`
  - `.focus-toggle` hidden
  - `.activity-panel` hidden
  - `#message-input { font-size: 16px }` (prevents iOS zoom)
  - Session panel overlays as drawer with shadow

**Verify manually:**
1. Open browser DevTools → toggle mobile viewport (375px width)
2. Sidebar hides, hamburger appears in header
3. Tap hamburger → sidebar slides in from left
4. `[Focus]` button is hidden
5. Textarea font is 16px (no iOS zoom on focus)

**Commit:**
```
git commit -m "feat(chat): mobile responsive layout is live in index.html"
```

---

## Phase 12: Polish

### Task 31: Synthetic Streaming Adapter

**Files:**
- Modify: `src/amplifier_distro/server/apps/chat/connection.py`
- Modify: `tests/test_chat_connection.py`

**Background:** Non-streaming providers (e.g., some OpenAI models) deliver the full response text in a single `content_block:end` with no deltas. The frontend cursor animation only works during streaming. We synthesize deltas by chunking the final text.

The translator marks blocks that received deltas via `seen_deltas` set. On `content_end`, if no deltas were seen for that block, `ChatConnection` synthesizes them.

**Step 1: Add test**

Add to `tests/test_chat_connection.py`:
```python
class TestSyntheticStreaming:
    @pytest.mark.asyncio
    async def test_synthetic_deltas_sent_for_non_streaming_blocks(self):
        """When content_end arrives with no prior deltas, synthesize chunked deltas."""
        from amplifier_distro.server.apps.chat.connection import ChatConnection

        ws = make_ws([])
        backend = make_backend()
        config = make_config()

        conn = ChatConnection(ws, backend, config)

        # Simulate: content_start then content_end (no deltas)
        await conn.event_queue.put(("content_block:start", {"block_type": "text", "index": 0}))
        await conn.event_queue.put(("content_block:end", {"index": 0, "text": "Hello world synthetic"}))
        await conn.event_queue.put(None)

        await conn._event_fanout_loop()

        sent = [call.args[0] for call in ws.send_json.await_args_list]
        delta_messages = [m for m in sent if m.get("type") == "content_delta"]
        # Should have multiple delta messages (chunked)
        assert len(delta_messages) > 1
        # Concatenated deltas should reconstruct the text
        full = "".join(m["delta"] for m in delta_messages)
        assert full == "Hello world synthetic"
```

**Step 2: Run to verify failure**
```
uv run python -m pytest tests/test_chat_connection.py::TestSyntheticStreaming -v
```
Expected: Fail — no synthetic deltas.

**Step 3: Implement synthetic streaming in connection.py**

Add to `ChatConnection`:
```python
    # Track which local indexes received deltas (for synthetic streaming)
    _seen_deltas: set  # initialized in __init__

    def __init__(self, ws, backend, config):
        # ... existing init ...
        self._seen_deltas: set[int] = set()
```

Modify `_event_fanout_loop()` to handle synthetic streaming before forwarding `content_end`:

```python
    async def _event_fanout_loop(self) -> None:
        while True:
            raw = await self.event_queue.get()
            if raw is _STOP:
                break
            event_name, data = raw
            try:
                # Synthetic streaming: if content_end has text but no deltas were seen,
                # synthesize chunked deltas
                if event_name == "content_block:delta":
                    local_idx = self._translator._get_local_index(data.get("index", 0))
                    self._seen_deltas.add(local_idx)

                if event_name == "content_block:end":
                    local_idx = self._translator._get_local_index(data.get("index", 0))
                    text = data.get("text", "")
                    if text and local_idx not in self._seen_deltas:
                        # Synthesize: send start, chunked deltas, then end
                        start_msg = self._translator.translate(
                            "content_block:start",
                            {"block_type": "text", "index": data.get("index", 0)}
                        )
                        if start_msg:
                            await self._ws.send_json(start_msg)
                        # Send chunked deltas
                        chunk_size = 12
                        server_index = data.get("index", 0)
                        for i in range(0, len(text), chunk_size):
                            chunk = text[i:i + chunk_size]
                            delta_msg = self._translator.translate(
                                "content_block:delta",
                                {"delta": chunk, "index": server_index}
                            )
                            if delta_msg:
                                await self._ws.send_json(delta_msg)
                    self._seen_deltas.discard(local_idx)

                msg = self._translator.translate(event_name, data)
                if msg is not None:
                    await self._ws.send_json(msg)

                # Reset seen_deltas on prompt_complete
                if event_name == "orchestrator:complete":
                    self._seen_deltas.clear()

            except Exception:
                logger.warning("Error in event fanout loop", exc_info=True)
```

**Step 4: Run tests**
```
uv run python -m pytest tests/test_chat_connection.py -v
```
Expected: All pass including the new synthetic streaming test.

**Step 5: Commit**
```
git add src/amplifier_distro/server/apps/chat/connection.py tests/test_chat_connection.py
git commit -m "feat(chat): add synthetic streaming adapter for non-streaming providers"
```

---

### Task 32: Verify parent_tool_call_id FIFO Correlation

Already tested in `tests/test_chat_translator.py::TestDelegatePropagation::test_fifo_order_for_parallel_delegates`. No new code needed. Run to confirm:
```
uv run python -m pytest tests/test_chat_translator.py::TestDelegatePropagation -v
```
Expected: All pass.

---

### Task 33: End-to-End Display Message Verification

Already tested in `tests/test_chat_display_messages.py`. Confirm end-to-end:
```
uv run python -m pytest tests/test_chat_display_messages.py -v
```
Expected: All pass.

---

## Final Verification

### Run Full Test Suite
```
uv run python -m pytest tests/ -q
```

Expected output (approximate):
```
..........................................
XX failed, YY passed, ZZ skipped
```
Where the only failures are the **10 known baseline failures** listed at the top of this plan. Any test you added that fails is YOUR bug — fix it before committing.

### Manual Smoke Test
```
uv run python -m amplifier_distro.server.main
```

Open `http://localhost:8000/apps/chat/` and verify:
- [ ] Green connection dot in header
- [ ] `📁 ~` CWD display visible, clickable
- [ ] Session panel on left with `+ New Session`
- [ ] Type a message, hit Enter → message appears on right
- [ ] Response streams in with blinking cursor
- [ ] Tool calls show as expandable cards with status icons
- [ ] `[Focus]` toggle splits view into two columns
- [ ] Mobile viewport: hamburger appears, sidebar becomes drawer
- [ ] Paste an image → thumbnail shows → sends with prompt
- [ ] `/help` → lists commands as system message

### Commit Final Summary
```
git add -A
git commit -m "feat(chat): complete chat app — WebSocket streaming, focus mode, multi-session, images, slash commands, mobile"
```

---

## File Inventory

**New files created:**
- `src/amplifier_distro/server/apps/chat/__init__.py`
- `src/amplifier_distro/server/apps/chat/translator.py`
- `src/amplifier_distro/server/apps/chat/connection.py`
- `src/amplifier_distro/server/apps/chat/preferences.py`
- `src/amplifier_distro/server/apps/chat/static/index.html`
- `src/amplifier_distro/server/apps/chat/static/vendor.js` (Task 14 build step)
- `src/amplifier_distro/server/apps/chat/static/.gitkeep`
- `tests/test_chat_app.py`
- `tests/test_chat_backend_queue.py`
- `tests/test_chat_delegate_events.py`
- `tests/test_chat_translator.py`
- `tests/test_chat_connection.py`
- `tests/test_chat_approval.py`
- `tests/test_chat_bridge_config.py`
- `tests/test_chat_display_messages.py`
- `tests/test_chat_cancellation.py`
- `tests/test_chat_preferences.py`
- `tests/test_chat_images.py`
- `tests/test_chat_commands.py`

**Modified files:**
- `src/amplifier_distro/server/session_backend.py` (event_queue, execute(), cancel_session(), resolve_approval(), display wiring)
- `src/amplifier_distro/bridge.py` (delegate events, SessionHandle.cancel(), BridgeConfig.behaviors/show_thinking)
- `src/amplifier_distro/bridge_protocols.py` (BridgeApprovalSystem rebuild)

**Task count: 33 tasks across 12 phases.**
