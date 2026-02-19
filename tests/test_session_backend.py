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
    target = "amplifier_distro.server.session_backend.BridgeBackend.__init__"
    with patch(target) as mock_init:
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

        a_start = call_order.index("start:A")
        a_end = call_order.index("end:A")
        b_start = call_order.index("start:B")
        b_end = call_order.index("end:B")
        assert a_end < b_start or b_end < a_start, f"Calls interleaved: {call_order}"

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
