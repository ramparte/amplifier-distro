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
        assert item == (
            "display_message",
            {
                "message": "Hello from display",
                "level": "info",
                "source": "test",
            },
        )

    @pytest.mark.asyncio
    async def test_no_queue_leaves_display_none(self):
        """Without event_queue, config.display stays None."""
        from amplifier_distro.server.session_backend import BridgeBackend

        captured_display = {}

        async def fake_bridge_create(config):
            captured_display["system"] = config.display
            handle = MagicMock()
            handle.session_id = "display-test-002"
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

        with patch("asyncio.create_task"):
            await backend.create_session(working_dir="~")  # no event_queue

        assert captured_display.get("system") is None
