"""Email event handler.

Dispatches incoming emails to the appropriate handler:
commands, existing sessions, or new session creation.
Mirrors the Slack bridge event handling pattern.
"""

from __future__ import annotations

import logging

from .client import EmailClient
from .commands import CommandHandler
from .config import EmailConfig
from .formatter import format_response, split_message
from .models import EmailMessage
from .sessions import EmailSessionManager

logger = logging.getLogger(__name__)


class EmailEventHandler:
    """Handles incoming email events.

    Flow:
    1. Skip self-sent emails (loop prevention)
    2. Check for /amp commands -> handle command -> reply
    3. Check for existing session -> route message -> reply
    4. Create new session -> route first message -> reply
    """

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
        self._warned_open_access = False

    async def handle_incoming_email(self, message: EmailMessage) -> None:
        """Process an incoming email message."""
        agent_address = self._client.get_agent_address()

        # Loop prevention: skip emails from the agent itself
        if message.from_addr.address == agent_address:
            logger.debug("Skipping self-sent message: %s", message.message_id)
            return

        # Sender allowlist: only process emails from configured senders
        allowed = self._config.allowed_senders
        sender_addr = message.from_addr.address.lower()
        if allowed:
            if sender_addr not in [a.lower() for a in allowed]:
                logger.warning(
                    "Rejecting email from unauthorized sender %s (message %s)",
                    sender_addr,
                    message.message_id,
                )
                return
        elif not self._warned_open_access:
            logger.warning(
                "No allowed_senders configured — accepting email from ANY sender. "
                "Set email.allowed_senders in distro.yaml to restrict access."
            )
            self._warned_open_access = True

        sender = message.from_addr
        body = message.body_text.strip()

        if not body:
            logger.debug("Skipping empty message: %s", message.message_id)
            return

        # Truncate oversized messages
        if len(body) > self._config.max_message_length:
            body = body[: self._config.max_message_length]
            body += "\n\n[Message truncated due to length]"

        # Check for /amp commands
        if self._command_handler.is_command(body):
            command, args = self._command_handler.parse_command(body)
            response_text = await self._command_handler.handle(
                command, args, sender.address, message.thread_id
            )
            # Commands may or may not have an associated session
            mapping = self._session_manager.get_by_thread(message.thread_id)
            session_id = mapping.session_id if mapping else ""
            await self._send_reply(message, response_text, session_id=session_id)
            return

        # Route to session (get existing or create new)
        session_id = ""
        try:
            mapping = await self._session_manager.get_or_create_session(message)
            session_id = mapping.session_id
            response_text = await self._session_manager.send_message(
                mapping.session_id, body
            )
        except Exception:
            logger.exception(
                "Error processing email from %s (thread %s)",
                sender.address,
                message.thread_id,
            )
            response_text = (
                "I encountered an error processing your message. "
                "Please try again or use /amp help for available commands."
            )

        await self._send_reply(message, response_text, session_id=session_id)

    async def _send_reply(
        self, original: EmailMessage, response_text: str, session_id: str = ""
    ) -> None:
        """Send a reply to an email, splitting if needed.

        Args:
            original: The original email message being replied to
            response_text: The response text to send
            session_id: Optional session ID to include in footer for reply threading
        """
        sender = original.from_addr

        # Split long responses into multiple emails
        chunks = split_message(response_text, self._config.max_message_length)

        for i, chunk in enumerate(chunks):
            subject = f"Re: {original.subject}"
            if len(chunks) > 1:
                subject = f"Re: {original.subject} ({i + 1}/{len(chunks)})"

            html = format_response(chunk, self._config, session_id=session_id)
            try:
                await self._client.send_email(
                    to=sender,
                    subject=subject,
                    body_html=html,
                    body_text=chunk,
                    in_reply_to=original.message_id,
                    thread_id=original.thread_id,
                )
            except Exception:
                logger.exception("Failed to send reply to %s", sender.address)
