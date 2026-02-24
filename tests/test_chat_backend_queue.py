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
        info = await backend.create_session(working_dir="~", event_queue=q)
        assert info.session_id is not None


class TestBridgeBackendQueueWiring:
    """BridgeBackend wires event_queue to BridgeConfig.on_stream."""

    @pytest.fixture()
    def bare_backend(self) -> BridgeBackend:
        """BridgeBackend with __init__ bypassed (no LocalBridge required)."""
        backend = BridgeBackend.__new__(BridgeBackend)
        backend._bridge = MagicMock()
        backend._sessions = {}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()
        backend._approval_systems = {}
        return backend

    @pytest.mark.asyncio
    async def test_create_session_wires_on_stream_when_queue_provided(
        self, bare_backend
    ):
        """on_stream in BridgeConfig receives the queue-wrapping callable."""
        captured_config = {}

        async def fake_bridge_create(config):
            captured_config["on_stream"] = config.on_stream
            handle = MagicMock()
            handle.session_id = "test-session-001"
            handle.project_id = "test-project"
            handle.working_dir = "/tmp"
            return handle

        bare_backend._bridge.create_session = AsyncMock(side_effect=fake_bridge_create)

        q: asyncio.Queue = asyncio.Queue()

        with patch("asyncio.create_task"):
            await bare_backend.create_session(working_dir="~", event_queue=q)

        assert captured_config["on_stream"] is not None
        # Verify it puts a (event_name, data) tuple into the queue
        captured_config["on_stream"]("test:event", {"key": "value"})
        item = q.get_nowait()
        assert item == ("test:event", {"key": "value"})

    @pytest.mark.asyncio
    async def test_create_session_no_queue_leaves_on_stream_none(self, bare_backend):
        """Without event_queue, on_stream stays None."""
        captured_config = {}

        async def fake_bridge_create(config):
            captured_config["on_stream"] = config.on_stream
            handle = MagicMock()
            handle.session_id = "test-session-002"
            handle.project_id = "test-project"
            handle.working_dir = "/tmp"
            return handle

        bare_backend._bridge.create_session = AsyncMock(side_effect=fake_bridge_create)

        with patch("asyncio.create_task"):
            await bare_backend.create_session(working_dir="~")

        assert captured_config["on_stream"] is None

    @pytest.mark.asyncio
    async def test_execute_calls_handle_run(self, bare_backend):
        """execute() calls handle.run() and returns None."""
        handle = MagicMock()
        handle.run = AsyncMock(return_value="response text")
        bare_backend._sessions = {"sess-001": handle}

        await bare_backend.execute("sess-001", "hello world")
        handle.run.assert_called_once_with("hello world")

    @pytest.mark.asyncio
    async def test_execute_raises_on_unknown_session(self, bare_backend):
        with pytest.raises(ValueError, match="Unknown session"):
            await bare_backend.execute("no-such-session", "hello")
