"""Email session manager.

Maps email threads to Amplifier sessions and routes messages.
Mirrors the Slack bridge session management patterns with:
- Persistent session mappings (email-sessions.json)
- Discovery integration (connect to existing local sessions)
- Per-sender session limits
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amplifier_distro.conventions import AMPLIFIER_HOME, EMAIL_SESSIONS_FILENAME

from .config import EmailConfig
from .models import EmailMessage, SessionMapping

logger = logging.getLogger(__name__)


class EmailSessionManager:
    """Manages email thread <-> Amplifier session mappings.

    Thread model: Each email thread maps to one Amplifier session.
    New subjects start new sessions. Replies continue existing ones.
    """

    def __init__(
        self,
        client: Any,  # EmailClient protocol
        backend: Any,  # SessionBackend protocol
        config: EmailConfig,
    ) -> None:
        self._client = client
        self._backend = backend
        self._config = config
        # thread_id -> SessionMapping
        self._sessions: dict[str, SessionMapping] = {}
        self._load_persisted()

    # --- Persistence (matches Slack pattern) ---

    def _sessions_path(self) -> Path:
        """Path to persisted session mappings file."""
        server_dir = Path(AMPLIFIER_HOME).expanduser() / "server"
        server_dir.mkdir(parents=True, exist_ok=True)
        return server_dir / EMAIL_SESSIONS_FILENAME

    def _load_persisted(self) -> None:
        """Load session mappings from disk."""
        path = self._sessions_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            for entry in data.get("sessions", []):
                mapping = SessionMapping(
                    session_id=entry["session_id"],
                    thread_id=entry["thread_id"],
                    sender_address=entry.get("sender_address", ""),
                    subject=entry.get("subject", ""),
                    project_id=entry.get("project_id", ""),
                    description=entry.get("description", ""),
                    created_at=entry.get("created_at", ""),
                    last_activity=entry.get("last_activity", ""),
                    message_count=entry.get("message_count", 0),
                    is_active=entry.get("is_active", True),
                )
                if mapping.is_active:
                    self._sessions[mapping.thread_id] = mapping
            logger.info("Loaded %d persisted email session(s)", len(self._sessions))
        except (json.JSONDecodeError, KeyError, OSError):
            logger.warning("Failed to load email sessions", exc_info=True)

    def _persist(self) -> None:
        """Save session mappings to disk."""
        entries = [
            {
                "session_id": mapping.session_id,
                "thread_id": mapping.thread_id,
                "sender_address": mapping.sender_address,
                "subject": mapping.subject,
                "project_id": mapping.project_id,
                "description": mapping.description,
                "created_at": mapping.created_at,
                "last_activity": mapping.last_activity,
                "message_count": mapping.message_count,
                "is_active": mapping.is_active,
            }
            for mapping in self._sessions.values()
        ]
        try:
            path = self._sessions_path()
            path.write_text(
                json.dumps(
                    {"sessions": entries, "updated_at": datetime.now(UTC).isoformat()},
                    indent=2,
                )
            )
        except OSError:
            logger.warning("Failed to persist email sessions", exc_info=True)

    # --- Session Lifecycle ---

    async def get_or_create_session(self, message: EmailMessage) -> SessionMapping:
        """Get existing session for thread or create a new one."""
        thread_id = message.thread_id

        # Check for existing mapping
        if thread_id in self._sessions:
            mapping = self._sessions[thread_id]
            mapping.last_activity = datetime.now(UTC).isoformat()
            mapping.message_count += 1
            self._persist()
            return mapping

        # Check per-sender limit
        sender = message.from_addr.address
        sender_sessions = [
            m
            for m in self._sessions.values()
            if m.sender_address == sender and m.is_active
        ]
        if len(sender_sessions) >= self._config.max_sessions_per_user:
            # End oldest session to make room
            oldest = min(sender_sessions, key=lambda m: m.last_activity)
            await self.end_session(oldest.thread_id)

        # Create new Amplifier session
        session_info = await self._backend.create_session(
            working_dir=self._config.default_working_dir,
            bundle_name=self._config.default_bundle,
            description=f"Email: {message.subject}",
        )

        mapping = SessionMapping(
            session_id=session_info.session_id,
            thread_id=thread_id,
            sender_address=sender,
            subject=message.subject,
            description=f"Email: {message.subject}",
            message_count=1,
        )
        self._sessions[thread_id] = mapping
        self._persist()

        logger.info(
            "Created email session %s for thread %s from %s",
            mapping.session_id,
            thread_id,
            sender,
        )
        return mapping

    async def send_message(self, session_id: str, text: str) -> str:
        """Send a message to an Amplifier session and get response."""
        response = await self._backend.send_message(session_id, text)
        return response

    async def end_session(self, thread_id: str) -> bool:
        """End a session and remove its mapping."""
        mapping = self._sessions.get(thread_id)
        if mapping is None:
            return False

        try:
            await self._backend.end_session(mapping.session_id)
        except (RuntimeError, ValueError, ConnectionError, OSError):
            logger.warning(
                "Error ending backend session %s", mapping.session_id, exc_info=True
            )

        mapping.is_active = False
        del self._sessions[thread_id]
        self._persist()
        logger.info("Ended email session %s (thread %s)", mapping.session_id, thread_id)
        return True

    async def connect_session(
        self,
        thread_id: str,
        session_id: str,
        sender_address: str,
        subject: str = "",
    ) -> SessionMapping:
        """Connect an email thread to an existing Amplifier session.

        This allows attaching to a session that was started from
        CLI, Slack, or another interface.
        """
        mapping = SessionMapping(
            session_id=session_id,
            thread_id=thread_id,
            sender_address=sender_address,
            subject=subject or f"Connected: {session_id[:8]}",
            description=f"Connected to existing session {session_id[:8]}",
        )
        self._sessions[thread_id] = mapping
        self._persist()
        logger.info("Connected thread %s to existing session %s", thread_id, session_id)
        return mapping

    # --- Query ---

    def get_by_thread(self, thread_id: str) -> SessionMapping | None:
        """Look up session mapping by email thread ID."""
        return self._sessions.get(thread_id)

    def get_by_session_id(self, session_id: str) -> SessionMapping | None:
        """Look up session mapping by Amplifier session ID."""
        for mapping in self._sessions.values():
            if mapping.session_id == session_id:
                return mapping
        return None

    def list_active(self) -> list[SessionMapping]:
        """List all active session mappings."""
        return list(self._sessions.values())

    def list_for_sender(self, sender_address: str) -> list[SessionMapping]:
        """List active sessions for a specific sender."""
        return [
            m
            for m in self._sessions.values()
            if m.sender_address == sender_address and m.is_active
        ]
