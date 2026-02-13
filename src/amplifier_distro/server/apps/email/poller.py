"""Email poller.

Periodically checks for new emails and dispatches them to the event handler.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .config import EmailConfig

logger = logging.getLogger(__name__)


class EmailPoller:
    """Polls for new emails on a configurable interval."""

    def __init__(
        self,
        client: Any,
        event_handler: Any,
        config: EmailConfig,
    ) -> None:
        self._client = client
        self._event_handler = event_handler
        self._config = config
        self._task: asyncio.Task[None] | None = None
        self._last_message_id: str = ""
        self._running = False

    @property
    def is_running(self) -> bool:
        """Whether the poller is currently running."""
        return self._running

    def start(self) -> None:
        """Start the background polling task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._poll_loop())

    def stop(self) -> None:
        """Stop the background polling task."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def poll_once(self) -> int:
        """Fetch new emails, handle each, mark read. Returns count processed."""
        try:
            messages = await self._client.fetch_new_emails(
                since_message_id=self._last_message_id
            )
        except Exception:
            logger.exception("Error fetching emails")
            return 0

        count = 0
        for message in messages:
            try:
                await self._event_handler.handle_incoming_email(message)
                await self._client.mark_read(message.message_id)
                self._last_message_id = message.message_id
                count += 1
            except Exception:
                logger.exception("Error handling email %s", message.message_id)

        return count

    async def _poll_loop(self) -> None:
        """Background polling loop."""
        while self._running:
            try:
                await self.poll_once()
            except Exception:
                logger.exception("Error in poll loop")
            await asyncio.sleep(self._config.poll_interval_seconds)
