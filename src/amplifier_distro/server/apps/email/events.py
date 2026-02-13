"""Email event handler.

Dispatches incoming emails to the appropriate handler:
commands, existing sessions, or new session creation.
"""

from __future__ import annotations

import logging

from .client import EmailClient
from .commands import CommandHandler
from .config import EmailConfig
from .formatter import format_response
from .models import EmailMessage
from .sessions import EmailSessionManager

logger = logging.getLogger(__name__)


class EmailEventHandler:
    """Handles incoming email events."""

    def __init__(
        self,
        client: EmailClient,
        session_manager: EmailSessionManager,
        command_handler: CommandHandler,
        config: EmailConfig,
    ) -> None:
        self._client = client
        self._session_manager = session_manager
        self._command_handler = command_handler
        self._config = config

    async def handle_incoming_email(self, message: EmailMessage) -> None:
        """Process an incoming email message.

        Flow:
        1. Skip if from agent (loop prevention)
        2. If command -> handle command -> reply
        3. If existing session -> route message -> reply
        4. Else -> create session -> route first message -> reply
        """
        agent_address = self._client.get_agent_address()

        # Loop prevention: skip emails from the agent itself
        if message.from_addr.address == agent_address:
            logger.debug("Skipping self-sent message: %s", message.message_id)
            return

        sender = message.from_addr
        body = message.body_text.strip()

        # Check for commands
        if self._command_handler.is_command(body):
            command, args = self._command_handler.parse_command(body)
            response_text = await self._command_handler.handle(
                command, args, sender.address, message.thread_id
            )
            html = format_response(response_text, self._config)
            await self._client.send_email(
                to=sender,
                subject=f"Re: {message.subject}",
                body_html=html,
                body_text=response_text,
                in_reply_to=message.message_id,
                thread_id=message.thread_id,
            )
            return

        # Check for existing session
        existing = self._session_manager.get_session(message.thread_id)
        if existing is not None:
            response_text = await self._session_manager.route_message(
                message.thread_id, body
            )
            html = format_response(response_text, self._config)
            await self._client.send_email(
                to=sender,
                subject=f"Re: {message.subject}",
                body_html=html,
                body_text=response_text,
                in_reply_to=message.message_id,
                thread_id=message.thread_id,
            )
            return

        # New session
        try:
            await self._session_manager.create_session(
                sender_address=sender.address,
                subject=message.subject,
                thread_id=message.thread_id,
            )
            response_text = await self._session_manager.route_message(
                message.thread_id, body
            )
            html = format_response(response_text, self._config)
            await self._client.send_email(
                to=sender,
                subject=f"Re: {message.subject}",
                body_html=html,
                body_text=response_text,
                in_reply_to=message.message_id,
                thread_id=message.thread_id,
            )
        except ValueError:
            logger.warning(
                "Failed to create session for %s", sender.address, exc_info=True
            )
