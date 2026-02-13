"""Command handler for the email bridge.

Handles /amp commands embedded in email body text.
Mirrors the Slack bridge command set for consistency across surfaces.

Commands:
    /amp help       - Show available commands
    /amp list       - List active email sessions
    /amp new [desc] - Start a new session in this thread
    /amp status     - Show current session info
    /amp end        - End the current session
    /amp sessions   - List all your active sessions
    /amp connect <id> - Connect this thread to an existing session
    /amp disconnect - Disconnect thread without ending the session
    /amp config     - Show bridge configuration
"""

from __future__ import annotations

import logging
from typing import Any

from .config import EmailConfig

logger = logging.getLogger(__name__)

# Command aliases (matches Slack bridge)
ALIASES: dict[str, str] = {
    "ls": "list",
    "quit": "end",
    "close": "end",
    "stop": "end",
    "info": "status",
    "link": "connect",
    "unlink": "disconnect",
    "detach": "disconnect",
}


class CommandHandler:
    """Handles /amp commands in email messages.

    Follows the same command syntax as the Slack bridge for
    cross-surface consistency.
    """

    def __init__(self, session_manager: Any, config: EmailConfig) -> None:
        self._session_manager = session_manager
        self._config = config

    def is_command(self, text: str) -> bool:
        """Check if text starts with /amp (as a distinct token).

        Looks for /amp at the start of the email body, ignoring
        any quoted reply text (lines starting with >).
        """
        # Get the first non-quote, non-empty line
        for line in text.strip().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(">"):
                continue
            return stripped == "/amp" or stripped.startswith("/amp ")

        return False

    def extract_command_text(self, text: str) -> str:
        """Extract the /amp command line from email body.

        Skips blank lines and quoted reply text (> prefixed).
        """
        for line in text.strip().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(">"):
                continue
            if stripped.startswith("/amp"):
                return stripped
            break
        return ""

    def parse_command(self, text: str) -> tuple[str, list[str]]:
        """Parse '/amp <command> [args...]' into (command, args).

        Returns (command, args) tuple. If no command after /amp,
        returns ('help', []).
        """
        cmd_line = self.extract_command_text(text)
        if not cmd_line:
            return ("help", [])

        parts = cmd_line.split()
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
        # Resolve aliases again (in case called directly)
        command = ALIASES.get(command, command)

        handlers: dict[str, Any] = {
            "help": self._help,
            "list": self._list,
            "sessions": self._sessions,
            "new": lambda: self._new(args, sender_address, thread_id),
            "status": lambda: self._status(thread_id),
            "end": lambda: self._end(thread_id),
            "connect": lambda: self._connect(args, sender_address, thread_id),
            "disconnect": lambda: self._disconnect(thread_id),
            "config": self._show_config,
        }

        handler = handlers.get(command)
        if handler is None:
            return (
                f"Unknown command: {command}\n\nType /amp help for available commands."
            )

        result = handler()
        # Handle both sync and async handlers
        if hasattr(result, "__await__"):
            return await result
        return result

    # --- Command Implementations ---

    def _help(self) -> str:
        return (
            "Amplifier Email Bridge Commands\n"
            "================================\n"
            "\n"
            "Session Management:\n"
            "  /amp new [description]  - Start a new session\n"
            "  /amp end                - End the current session\n"
            "  /amp status             - Show current session info\n"
            "\n"
            "Session Navigation:\n"
            "  /amp list               - List sessions in this thread\n"
            "  /amp sessions           - List all your active sessions\n"
            "  /amp connect <id>       - Connect thread to existing session\n"
            "  /amp disconnect         - Disconnect thread (keeps session)\n"
            "\n"
            "Info:\n"
            "  /amp config             - Show bridge configuration\n"
            "  /amp help               - Show this help\n"
            "\n"
            "Aliases: ls=list, quit/close/stop=end, info=status, "
            "link=connect, unlink/detach=disconnect\n"
            "\n"
            "Any email that doesn't start with /amp is sent to your "
            "active Amplifier session as a message."
        )

    def _list(self) -> str:
        """List sessions (same thread context)."""
        sessions = self._session_manager.list_active()
        if not sessions:
            return "No active email sessions."

        lines = [f"Active sessions ({len(sessions)}):"]
        for m in sessions:
            status = f"msgs: {m.message_count}"
            lines.append(f"  [{m.session_id[:8]}] {m.subject} ({status})")
        return "\n".join(lines)

    def _sessions(self) -> str:
        """List all sessions for display. Same as list for email."""
        return self._list()

    async def _new(self, args: list[str], sender_address: str, thread_id: str) -> str:
        """Start a new session."""
        description = " ".join(args) if args else "New Email Session"

        # If there's already a session on this thread, end it first
        existing = self._session_manager.get_by_thread(thread_id)
        if existing is not None:
            await self._session_manager.end_session(thread_id)

        from .models import EmailAddress, EmailMessage

        # Create a synthetic message to drive session creation
        msg = EmailMessage(
            message_id="",
            thread_id=thread_id,
            from_addr=EmailAddress(address=sender_address),
            to_addrs=[],
            subject=description,
            body_text="",
        )
        mapping = await self._session_manager.get_or_create_session(msg)
        return (
            f"Session started: {mapping.session_id[:8]}\n"
            f"Subject: {description}\n"
            f"\n"
            f"Send messages in this thread to interact with Amplifier.\n"
            f"Use /amp end when done."
        )

    def _status(self, thread_id: str) -> str:
        """Show current session status."""
        mapping = self._session_manager.get_by_thread(thread_id)
        if mapping is None:
            return (
                "No active session for this email thread.\n"
                "Use /amp new to start one, or /amp connect <id> "
                "to connect to an existing session."
            )

        return (
            f"Session: {mapping.session_id[:8]}\n"
            f"Subject: {mapping.subject}\n"
            f"Messages: {mapping.message_count}\n"
            f"Sender: {mapping.sender_address}\n"
            f"Created: {mapping.created_at}\n"
            f"Last activity: {mapping.last_activity}"
        )

    async def _end(self, thread_id: str) -> str:
        """End the current session."""
        mapping = self._session_manager.get_by_thread(thread_id)
        if mapping is None:
            return "No active session for this thread."

        session_id = mapping.session_id[:8]
        ended = await self._session_manager.end_session(thread_id)
        if ended:
            return f"Session {session_id} ended."
        return "Failed to end session."

    async def _connect(
        self, args: list[str], sender_address: str, thread_id: str
    ) -> str:
        """Connect this thread to an existing session."""
        if not args:
            return (
                "Usage: /amp connect <session_id>\n"
                "Connect this email thread to an existing Amplifier session.\n"
                "The session can be from CLI, Slack, or another email thread."
            )

        session_id_prefix = args[0]

        # Look up the session - check if it's a known session
        # Try connecting with the provided ID
        try:
            mapping = await self._session_manager.connect_session(
                thread_id=thread_id,
                session_id=session_id_prefix,
                sender_address=sender_address,
            )
            return (
                f"Connected to session: {mapping.session_id[:8]}\n"
                f"Messages in this thread will go to that session."
            )
        except (ValueError, RuntimeError) as e:
            return f"Could not connect: {e}"

    async def _disconnect(self, thread_id: str) -> str:
        """Disconnect thread from session without ending it."""
        mapping = self._session_manager.get_by_thread(thread_id)
        if mapping is None:
            return "No session connected to this thread."

        session_id = mapping.session_id[:8]
        # Remove the mapping but don't end the backend session
        self._session_manager._sessions.pop(thread_id, None)
        self._session_manager._persist()
        return (
            f"Disconnected from session {session_id}.\n"
            f"The Amplifier session is still running - you can reconnect "
            f"with /amp connect {session_id}"
        )

    def _show_config(self) -> str:
        """Show bridge configuration."""
        cfg = self._config
        return (
            f"Email Bridge Configuration\n"
            f"==========================\n"
            f"Mode: {cfg.mode}\n"
            f"Agent address: {cfg.agent_address or '(not set)'}\n"
            f"Send as: {cfg.effective_send_as or '(not set)'}\n"
            f"Agent name: {cfg.agent_name}\n"
            f"Poll interval: {cfg.poll_interval_seconds}s\n"
            f"Max sessions/user: {cfg.max_sessions_per_user}\n"
            f"Response timeout: {cfg.response_timeout}s\n"
            f"Configured: {cfg.is_configured}"
        )
