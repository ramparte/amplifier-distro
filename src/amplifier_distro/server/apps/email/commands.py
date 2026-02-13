"""Command handler for email bridge.

Handles /amp commands embedded in email body text.
"""

from __future__ import annotations

import logging
from typing import Any

from .config import EmailConfig

logger = logging.getLogger(__name__)

# Command aliases
ALIASES: dict[str, str] = {
    "ls": "list",
    "quit": "end",
    "close": "end",
}


class CommandHandler:
    """Handles /amp commands in email messages."""

    def __init__(self, session_manager: Any, config: EmailConfig) -> None:
        self._session_manager = session_manager
        self._config = config

    def is_command(self, text: str) -> bool:
        """Check if text starts with /amp (as a distinct token)."""
        stripped = text.strip()
        if stripped == "/amp":
            return True
        return stripped.startswith("/amp ")

    def parse_command(self, text: str) -> tuple[str, list[str]]:
        """Parse '/amp <command> [args...]' into (command, args).

        Returns (command, args) tuple. If no command after /amp,
        returns ('help', []).
        """
        text = text.strip()
        if not text.startswith("/amp"):
            return ("help", [])

        parts = text.split()
        if len(parts) < 2:
            return ("help", [])

        command = parts[1].lower()
        args = parts[2:]

        # Resolve aliases
        command = ALIASES.get(command, command)

        return (command, args)

    async def handle(
        self,
        command: str,
        args: list[str],
        sender_address: str,
        thread_id: str,
    ) -> str:
        """Handle a command and return the response text."""
        # Resolve aliases
        command = ALIASES.get(command, command)

        if command == "help":
            return self._help()
        elif command == "list":
            return self._list()
        elif command == "new":
            return await self._new(args, sender_address, thread_id)
        elif command == "status":
            return self._status(thread_id)
        elif command == "end":
            return await self._end(thread_id)
        else:
            return f"Unknown command: {command}. Type /amp help for available commands."

    def _help(self) -> str:
        return (
            "Available commands:\n"
            "  /amp help - Show this help\n"
            "  /amp list - List active sessions\n"
            "  /amp new [subject] - Start a new session\n"
            "  /amp status - Show current session status\n"
            "  /amp end - End current session"
        )

    def _list(self) -> str:
        sessions = self._session_manager.list_active()
        if not sessions:
            return "No active sessions."
        lines = ["Active sessions:"]
        for m in sessions:
            lines.append(
                f"  - {m.subject} (thread: {m.thread_id}, messages: {m.message_count})"
            )
        return "\n".join(lines)

    async def _new(self, args: list[str], sender_address: str, thread_id: str) -> str:
        subject = " ".join(args) if args else "New Session"
        try:
            mapping = await self._session_manager.create_session(
                sender_address=sender_address,
                subject=subject,
                thread_id=thread_id,
            )
            return f"Session created: {mapping.session_id} ({subject})"
        except ValueError as e:
            return str(e)

    def _status(self, thread_id: str) -> str:
        mapping = self._session_manager.get_session(thread_id)
        if mapping is None:
            return "No active session for this thread."
        return (
            f"Session: {mapping.session_id}\n"
            f"Subject: {mapping.subject}\n"
            f"Messages: {mapping.message_count}\n"
            f"Sender: {mapping.sender_address}"
        )

    async def _end(self, thread_id: str) -> str:
        mapping = self._session_manager.get_session(thread_id)
        if mapping is None:
            return "No active session for this thread."
        await self._session_manager.end_session(thread_id)
        return f"Session {mapping.session_id} ended."
