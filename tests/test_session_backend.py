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
            BridgeBackend._session_worker(bridge_backend, session_id)  # type: ignore[attr-defined]
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
            BridgeBackend._session_worker(bridge_backend, session_id)  # type: ignore[attr-defined]
        )

        try:
            with pytest.raises(RuntimeError, match="LLM exploded"):
                await BridgeBackend.send_message(bridge_backend, session_id, "hi")
        finally:
            bridge_backend._worker_tasks[session_id].cancel()


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


class TestBridgeBackendCancellation:
    """Verify that cancelling the worker during handle.run() is clean."""

    async def test_no_double_task_done_on_cancel_during_run(self, bridge_backend):
        """Cancelling the worker during handle.run() must not raise ValueError."""
        session_id = "sess-cancel-run-001"
        handle = _make_mock_handle(session_id)
        bridge_backend._sessions[session_id] = handle

        run_started = asyncio.Event()

        async def slow_run(message):
            run_started.set()
            await asyncio.sleep(10)  # long enough to cancel
            return "never"

        handle.run = slow_run

        from amplifier_distro.server.session_backend import BridgeBackend

        queue = asyncio.Queue()
        bridge_backend._session_queues[session_id] = queue
        worker = asyncio.create_task(
            BridgeBackend._session_worker(bridge_backend, session_id)
        )
        bridge_backend._worker_tasks[session_id] = worker

        # Enqueue a message and wait for run() to start
        fut = asyncio.get_event_loop().create_future()
        await queue.put(("cancel-me", fut))
        await run_started.wait()

        # Cancel worker while handle.run() is in-flight
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

        # fut should be cancelled, queue should be consistent (no ValueError raised)
        assert fut.cancelled() or fut.done()
        # If we get here without ValueError, the bug is fixed


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


class TestBridgeBackendStop:
    """stop() sends sentinels to all workers and awaits them."""

    async def test_stop_signals_all_workers(self, bridge_backend):
        """stop() sends None sentinel to every active queue."""
        from amplifier_distro.server.session_backend import BridgeBackend

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
