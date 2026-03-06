"""Bridge Protocol Adapters

Minimal implementations of the display, approval, and streaming protocols
for headless server usage. These satisfy the amplifier-core contracts
without requiring a specific transport (WebSocket, SSE, etc.).

For interactive use, callers can provide their own implementations via
BridgeConfig.display and BridgeConfig.on_stream.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any, Literal

logger = logging.getLogger(__name__)


class BridgeDisplaySystem:
    """Minimal display system that logs messages.

    Can be wrapped by a real UI (web, TUI, etc.) by providing
    a callback.
    """

    def __init__(
        self,
        on_message: Callable[[str, str, str], Any] | None = None,
        nesting_depth: int = 0,
    ) -> None:
        self._on_message = on_message
        self._nesting_depth = nesting_depth

    async def show_message(
        self,
        message: str,
        level: Literal["info", "warning", "error"] = "info",
        source: str = "hook",
    ) -> None:
        if self._on_message:
            result = self._on_message(message, level, source)
            if inspect.isawaitable(result):
                await result
        else:
            log_level = {
                "info": logging.INFO,
                "warning": logging.WARNING,
                "error": logging.ERROR,
            }.get(level, logging.INFO)
            logger.log(log_level, "[%s] %s", source, message)

    def push_nesting(self) -> BridgeDisplaySystem:
        return BridgeDisplaySystem(
            on_message=self._on_message,
            nesting_depth=self._nesting_depth + 1,
        )

    def pop_nesting(self) -> BridgeDisplaySystem:
        return BridgeDisplaySystem(
            on_message=self._on_message,
            nesting_depth=max(0, self._nesting_depth - 1),
        )

    @property
    def nesting_depth(self) -> int:
        return self._nesting_depth


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
        default: str = "deny",
    ) -> str:
        if self._auto_approve:
            return options[0] if options else "allow"

        import uuid

        request_id = str(uuid.uuid4())
        event = asyncio.Event()
        self._pending[request_id] = event

        try:
            if self._on_approval_request:
                result = self._on_approval_request(
                    request_id, prompt, options, timeout, default
                )
                if inspect.isawaitable(result):
                    await result
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return self._responses.pop(request_id, default)
        except TimeoutError:
            return default
        finally:
            self._pending.pop(request_id, None)
            self._responses.pop(request_id, None)  # defensive cleanup

    def handle_response(self, request_id: str, choice: str) -> bool:
        """Unblock a waiting request_approval().

        Returns True if found and not already resolved.
        """
        event = self._pending.get(request_id)
        if event is None:
            return False
        if event.is_set():
            # Already resolved (either by a prior handle_response call, or
            # timeout has fired and the event was set by the timeout path).
            return False
        self._responses[request_id] = choice
        event.set()
        return True


class BridgeStreamingHook:
    """Hook that captures streaming events.

    Can forward events to a callback (for SSE, WebSocket, etc.)
    or just log them.
    """

    name = "bridge-streaming"
    priority = 100

    def __init__(
        self,
        on_event: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self._on_event = on_event

    async def __call__(self, event: str, data: dict[str, Any]) -> Any:
        if self._on_event:
            result = self._on_event(event, data)
            if inspect.isawaitable(result):
                await result

        # Import here to avoid hard dependency at module level
        try:
            from amplifier_core.models import (  # type: ignore[import-not-found]
                HookResult,
            )

            return HookResult(action="continue")
        except ImportError:
            return {"action": "continue"}
