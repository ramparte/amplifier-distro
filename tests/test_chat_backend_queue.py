"""Tests for event queue wiring in FoundationBackend."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amplifier_distro.server.session_backend import FoundationBackend, MockBackend


class TestMockBackendQueueIgnored:
    """MockBackend gracefully ignores event_queue (it doesn't stream)."""

    @pytest.mark.asyncio
    async def test_create_session_accepts_event_queue(self):
        backend = MockBackend()
        q: asyncio.Queue = asyncio.Queue()
        info = await backend.create_session(working_dir="~", event_queue=q)
        assert info.session_id is not None


class TestFoundationBackendQueueWiring:
    """FoundationBackend wires event_queue via _wire_event_queue."""

    @pytest.fixture()
    def bare_backend(self) -> FoundationBackend:
        """FoundationBackend with __init__ bypassed (no foundation required)."""
        backend = FoundationBackend.__new__(FoundationBackend)
        backend._bundle_name = "test-bundle"
        backend._sessions = {}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()
        backend._approval_systems = {}
        return backend

    def _mock_session(self, session_id: str = "test-session-001") -> MagicMock:
        """Create a mock foundation session with coordinator and hooks."""
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.project_id = "test-project"
        mock_session.coordinator = MagicMock()
        mock_session.coordinator.hooks = MagicMock()
        return mock_session

    @pytest.mark.asyncio
    async def test_create_session_wires_on_stream_when_queue_provided(
        self, bare_backend
    ):
        """When event_queue is provided, hooks.register is called for streaming."""
        mock_session = self._mock_session("test-session-001")
        mock_prepared = MagicMock()
        mock_prepared.create_session = AsyncMock(return_value=mock_session)
        bare_backend._load_bundle = AsyncMock(return_value=mock_prepared)

        q: asyncio.Queue = asyncio.Queue()

        with patch("asyncio.create_task"):
            await bare_backend.create_session(working_dir="~", event_queue=q)

        # hooks.register should have been called (for streaming wiring)
        mock_session.coordinator.hooks.register.assert_called()

    @pytest.mark.asyncio
    async def test_create_session_no_queue_skips_wiring(self, bare_backend):
        """Without event_queue, _wire_event_queue is not called."""
        mock_session = self._mock_session("test-session-002")
        mock_prepared = MagicMock()
        mock_prepared.create_session = AsyncMock(return_value=mock_session)
        bare_backend._load_bundle = AsyncMock(return_value=mock_prepared)

        with patch("asyncio.create_task"):
            await bare_backend.create_session(working_dir="~")

        # Without event_queue, hooks.register should NOT be called
        mock_session.coordinator.hooks.register.assert_not_called()

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
