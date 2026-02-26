"""Tests for voice protocol event streaming hook.

Verifies EventStreamingHook maps Amplifier canonical events to SSE wire dicts.

Exit criteria:
1. tool:pre maps to tool_call with status='pending'
2. tool:post maps to tool_result with output
3. content_block:start tracks block_type in _current_blocks
4. content_block:delta uses tracked block_type
5. content_block:end removes from _current_blocks
6. cancel:requested maps correctly with level
7. session:fork maps correctly with agent
8. large base64 data (>1000 chars) is stripped to '[image data omitted]'
9. small base64 data (<1000 chars) passes through unchanged
"""

from __future__ import annotations

import asyncio

import pytest

from amplifier_distro.server.apps.voice.protocols.event_streaming import (
    EventStreamingHook,
)


class TestEventStreamingHook:
    """Verify EventStreamingHook maps canonical events to SSE wire dicts."""

    def _make_hook(self) -> tuple[EventStreamingHook, asyncio.Queue]:
        queue: asyncio.Queue = asyncio.Queue()
        hook = EventStreamingHook(queue)
        return hook, queue

    # ------------------------------------------------------------------ #
    #  Tool Events                                                         #
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_tool_pre_maps_to_tool_call_with_pending_status(self) -> None:
        """tool:pre event maps to {type:'tool_call', status:'pending'}."""
        hook, queue = self._make_hook()
        data = {
            "tool_name": "read_file",
            "tool_call_id": "call_abc123",
            "arguments": {"path": "/tmp/test.txt"},
        }

        await hook("tool:pre", data)

        msg = queue.get_nowait()
        assert msg["type"] == "tool_call"
        assert msg["status"] == "pending"
        assert msg["tool_name"] == "read_file"
        assert msg["tool_call_id"] == "call_abc123"
        assert msg["arguments"] == {"path": "/tmp/test.txt"}

    @pytest.mark.asyncio
    async def test_tool_post_maps_to_tool_result_with_output(self) -> None:
        """tool:post event maps to {type:'tool_result', output, success}."""
        hook, queue = self._make_hook()
        data = {
            "tool_name": "read_file",
            "tool_call_id": "call_abc123",
            "output": "file contents here",
            "success": True,
            "error": None,
        }

        await hook("tool:post", data)

        msg = queue.get_nowait()
        assert msg["type"] == "tool_result"
        assert msg["tool_name"] == "read_file"
        assert msg["tool_call_id"] == "call_abc123"
        assert msg["output"] == "file contents here"
        assert msg["success"] is True

    # ------------------------------------------------------------------ #
    #  Content Block Events                                               #
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_content_block_start_tracks_block_type(self) -> None:
        """content_block:start maps to content_start and tracks block_type."""
        hook, queue = self._make_hook()
        data = {"block_type": "text", "index": 0}

        await hook("content_block:start", data)

        msg = queue.get_nowait()
        assert msg["type"] == "content_start"
        assert msg["block_type"] == "text"
        assert msg["index"] == 0
        # Block type is tracked internally
        assert hook._current_blocks[0] == "text"

    @pytest.mark.asyncio
    async def test_content_block_delta_uses_tracked_block_type(self) -> None:
        """content_block:delta uses block_type from _current_blocks."""
        hook, queue = self._make_hook()
        # First set up the block
        hook._current_blocks[1] = "text"

        data = {"index": 1, "delta": {"text": "Hello world"}}

        await hook("content_block:delta", data)

        msg = queue.get_nowait()
        assert msg["type"] == "content_delta"
        assert msg["index"] == 1
        assert msg["delta"] == "Hello world"
        assert msg["block_type"] == "text"

    @pytest.mark.asyncio
    async def test_content_block_end_removes_from_current_blocks(self) -> None:
        """content_block:end removes block from _current_blocks."""
        hook, queue = self._make_hook()
        # Set up block first
        hook._current_blocks[2] = "text"

        data = {"index": 2, "content": "Final content"}

        await hook("content_block:end", data)

        msg = queue.get_nowait()
        assert msg["type"] == "content_end"
        assert msg["index"] == 2
        assert msg["content"] == "Final content"
        assert msg["block_type"] == "text"
        # Block should be removed
        assert 2 not in hook._current_blocks

    # ------------------------------------------------------------------ #
    #  Cancel Events                                                       #
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_cancel_requested_maps_correctly_with_level(self) -> None:
        """cancel:requested maps to {type:'cancel_requested', level, running_tools}."""
        hook, queue = self._make_hook()
        data = {"level": "turn", "running_tools": ["read_file", "write_file"]}

        await hook("cancel:requested", data)

        msg = queue.get_nowait()
        assert msg["type"] == "cancel_requested"
        assert msg["level"] == "turn"
        assert msg["running_tools"] == ["read_file", "write_file"]

    # ------------------------------------------------------------------ #
    #  Session Events                                                      #
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_session_fork_maps_correctly_with_agent(self) -> None:
        """session:fork maps to {type:'session_fork', child_session_id, agent}."""
        hook, queue = self._make_hook()
        data = {"child_session_id": "child-session-xyz", "agent": "sub-agent-name"}

        await hook("session:fork", data)

        msg = queue.get_nowait()
        assert msg["type"] == "session_fork"
        assert msg["child_session_id"] == "child-session-xyz"
        assert msg["agent"] == "sub-agent-name"

    # ------------------------------------------------------------------ #
    #  Data Sanitization                                                   #
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_large_base64_data_stripped_to_placeholder(self) -> None:
        """Base64 data > 1000 chars is replaced with '[image data omitted]'."""
        hook, queue = self._make_hook()
        # Create a base64 string > 1000 chars
        large_base64 = "A" * 1001
        data = {
            "tool_name": "read_file",
            "tool_call_id": "call_xyz",
            "output": large_base64,
            "success": True,
            "error": None,
        }

        await hook("tool:post", data)

        msg = queue.get_nowait()
        assert msg["output"] == "[image data omitted]"

    @pytest.mark.asyncio
    async def test_small_base64_data_passes_through_unchanged(self) -> None:
        """Base64 data <= 1000 chars passes through unchanged."""
        hook, queue = self._make_hook()
        # Create a base64 string <= 1000 chars
        small_base64 = "A" * 999
        data = {
            "tool_name": "read_file",
            "tool_call_id": "call_xyz",
            "output": small_base64,
            "success": True,
            "error": None,
        }

        await hook("tool:post", data)

        msg = queue.get_nowait()
        assert msg["output"] == small_base64
