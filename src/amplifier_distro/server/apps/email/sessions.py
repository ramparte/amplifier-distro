"""Email session manager.

Maps email threads to Amplifier sessions and routes messages.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import EmailConfig
from .models import SessionMapping

logger = logging.getLogger(__name__)


class EmailSessionManager:
    """Manages email thread -> Amplifier session mappings."""

    def __init__(
        self,
        client: Any,
        backend: Any,
        config: EmailConfig,
    ) -> None:
        self._client = client
        self._backend = backend
        self._config = config
        self._sessions: dict[str, SessionMapping] = {}  # thread_id -> mapping

    async def create_session(
        self,
        sender_address: str,
        subject: str,
        thread_id: str,
    ) -> SessionMapping:
        """Create a new Amplifier session for an email thread.

        Raises ValueError if the sender has too many active sessions.
        """
        # Check per-sender limit
        sender_count = sum(
            1 for m in self._sessions.values() if m.sender_address == sender_address
        )
        if sender_count >= self._config.max_sessions_per_sender:
            raise ValueError(
                f"Maximum sessions ({self._config.max_sessions_per_sender}) "
                f"reached for {sender_address}"
            )

        # Create backend session
        info = await self._backend.create_session(
            working_dir=self._config.default_working_dir,
            bundle_name=self._config.default_bundle,
            description=f"Email: {subject}",
        )

        mapping = SessionMapping(
            session_id=info.session_id,
            thread_id=thread_id,
            sender_address=sender_address,
            subject=subject,
        )
        self._sessions[thread_id] = mapping
        return mapping

    async def route_message(self, thread_id: str, text: str) -> str:
        """Route a message to the session for a thread. Returns response."""
        mapping = self._sessions.get(thread_id)
        if mapping is None:
            raise ValueError(f"No session for thread: {thread_id}")

        mapping.message_count += 1
        mapping.last_activity = datetime.now(UTC).isoformat()

        response = await self._backend.send_message(mapping.session_id, text)
        return response

    async def end_session(self, thread_id: str) -> None:
        """End the session for a thread."""
        mapping = self._sessions.pop(thread_id, None)
        if mapping is not None:
            await self._backend.end_session(mapping.session_id)

    def get_session(self, thread_id: str) -> SessionMapping | None:
        """Get the session mapping for a thread."""
        return self._sessions.get(thread_id)

    def list_active(self) -> list[SessionMapping]:
        """List all active session mappings."""
        return list(self._sessions.values())

    def save(self, path: str | Path) -> None:
        """Save session mappings to a JSON file."""
        path = Path(path)
        data = []
        for mapping in self._sessions.values():
            data.append(
                {
                    "session_id": mapping.session_id,
                    "thread_id": mapping.thread_id,
                    "sender_address": mapping.sender_address,
                    "subject": mapping.subject,
                    "created_at": mapping.created_at,
                    "last_activity": mapping.last_activity,
                    "message_count": mapping.message_count,
                }
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    def load(self, path: str | Path) -> None:
        """Load session mappings from a JSON file."""
        path = Path(path)
        if not path.exists():
            return
        data = json.loads(path.read_text())
        for item in data:
            mapping = SessionMapping(
                session_id=item["session_id"],
                thread_id=item["thread_id"],
                sender_address=item["sender_address"],
                subject=item["subject"],
                created_at=item.get("created_at"),
                last_activity=item.get("last_activity"),
                message_count=item.get("message_count", 0),
            )
            self._sessions[mapping.thread_id] = mapping
