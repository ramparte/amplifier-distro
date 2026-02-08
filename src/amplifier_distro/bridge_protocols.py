"""Bridge Protocol Adapters

Minimal implementations of the display, approval, and streaming protocols
for headless server usage. These satisfy the amplifier-core contracts
without requiring a specific transport (WebSocket, SSE, etc.).

For interactive use, callers can provide their own implementations via
BridgeConfig.display and BridgeConfig.on_stream.
"""

from __future__ import annotations

import asyncio
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
            if asyncio.iscoroutine(result):
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
    """Approval system for headless usage.

    Default: auto-approve everything (headless mode).
    Can be configured with a callback for interactive approval.
    """

    def __init__(
        self,
        on_approval: Callable[[str, list[str]], Any] | None = None,
        auto_approve: bool = True,
    ) -> None:
        self._on_approval = on_approval
        self._auto_approve = auto_approve
        self._pending: dict[str, asyncio.Future[str]] = {}

    async def request_approval(
        self,
        prompt: str,
        options: list[str],
        timeout: float = 300.0,
        default: Literal["allow", "deny"] = "deny",
    ) -> str:
        if self._auto_approve:
            return options[0] if options else "allow"

        if self._on_approval:
            result = self._on_approval(prompt, options)
            if asyncio.iscoroutine(result):
                return await result  # type: ignore[return-value]
            return result  # type: ignore[return-value]

        return default

    def handle_response(self, request_id: str, choice: str) -> bool:
        future = self._pending.pop(request_id, None)
        if future and not future.done():
            future.set_result(choice)
            return True
        return False


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
            if asyncio.iscoroutine(result):
                await result

        # Import here to avoid hard dependency at module level
        try:
            from amplifier_core.models import (  # type: ignore[import-not-found]
                HookResult,
            )

            return HookResult(action="continue")
        except ImportError:
            return {"action": "continue"}
