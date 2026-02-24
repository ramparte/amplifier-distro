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
        """Map (cycle, server_index) composite key to a stable local index.

        Uses max(server_index, counter) so that cycle-0 blocks pass through
        unchanged (local == server), while post-cycle blocks always get indices
        beyond any previously assigned ones.
        """
        key = f"{self.cycle_count}-{server_index}"
        if key not in self.block_map:
            local = max(server_index, self._local_index_counter)
            self.block_map[key] = local
            self._local_index_counter = local + 1
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
