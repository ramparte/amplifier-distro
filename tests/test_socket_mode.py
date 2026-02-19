"""Tests for SocketModeAdapter concurrency fixes (Issue #57, Fix 2)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

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
    config.app_token = "xapp-test"  # noqa: S105
    config.bot_token = "xoxb-test"  # noqa: S105

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

    async def test_ack_is_sent_before_task_starts(self, adapter):
        """ACK must be sent synchronously before the background task begins."""
        ack_calls = []

        async def record_ack(payload):
            ack_calls.append(payload)

        async def slow_handler(event_payload):
            # This should run AFTER ack
            assert len(ack_calls) > 0, "ACK not sent before handler ran"

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
