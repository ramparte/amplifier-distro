"""Session store for web chat.

Provides WebChatSession (dataclass) and WebChatSessionStore (in-memory dict
with optional atomic JSON persistence).

Mirrors the pattern used by SlackSessionManager in server/apps/slack/sessions.py
but stripped of all Slack-specific routing complexity.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class WebChatSession:
    """One entry in the web chat session registry.

    created_at / last_active are ISO-format UTC strings.
    extra holds arbitrary metadata (e.g. project_id) for forward compatibility.
    """

    session_id: str
    description: str
    created_at: str
    last_active: str
    is_active: bool = True
    extra: dict = field(default_factory=dict)


class WebChatSessionStore:
    """In-memory dict of WebChatSession, optionally persisted to JSON.

    Pass persistence_path=None to disable disk I/O (useful in tests).
    On every mutation (add, deactivate, reactivate) the store is saved.

    Thread safety: single-threaded writes assumed (web chat is single-user).
    """

    def __init__(self, persistence_path: Path | None = None) -> None:
        self._sessions: dict[str, WebChatSession] = {}
        self._persistence_path = persistence_path
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        session_id: str,
        description: str,
        extra: dict | None = None,
    ) -> WebChatSession:
        """Register a new session. Raises ValueError if session_id already exists."""
        if session_id in self._sessions:
            raise ValueError(f"Session {session_id!r} already exists")
        now = datetime.now(UTC).isoformat()
        session = WebChatSession(
            session_id=session_id,
            description=description,
            created_at=now,
            last_active=now,
            is_active=True,
            extra=dict(extra) if extra else {},
        )
        self._sessions[session_id] = session
        self._save()
        return session

    def deactivate(self, session_id: str) -> None:
        """Mark session as inactive. No-op if session_id not found."""
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.is_active = False
        self._save()

    def reactivate(self, session_id: str) -> WebChatSession:
        """Mark session as active again. Raises ValueError if not found."""
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session {session_id!r} not found")
        session.is_active = True
        session.last_active = datetime.now(UTC).isoformat()
        self._save()
        return session

    def get(self, session_id: str) -> WebChatSession | None:
        """Return the session or None."""
        return self._sessions.get(session_id)

    def list_all(self) -> list[WebChatSession]:
        """All sessions, sorted by last_active descending (most recent first)."""
        return sorted(
            self._sessions.values(),
            key=lambda s: s.last_active,
            reverse=True,
        )

    def active_session(self) -> WebChatSession | None:
        """Return the first active session, or None."""
        for session in self._sessions.values():
            if session.is_active:
                return session
        return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Atomically write all sessions to the persistence file."""
        if self._persistence_path is None:
            return
        try:
            from amplifier_distro.fileutil import atomic_write

            data = [asdict(s) for s in self._sessions.values()]
            atomic_write(self._persistence_path, json.dumps(data, indent=2))
        except OSError:
            logger.warning("Failed to save web chat sessions", exc_info=True)

    def _load(self) -> None:
        """Load sessions from persistence file. Silently ignores missing/corrupt."""
        if self._persistence_path is None or not self._persistence_path.exists():
            return
        try:
            data = json.loads(self._persistence_path.read_text())
            for entry in data:
                session = WebChatSession(
                    session_id=entry["session_id"],
                    description=entry.get("description", ""),
                    created_at=entry.get("created_at", ""),
                    last_active=entry.get("last_active", ""),
                    is_active=entry.get("is_active", True),
                    extra=entry.get("extra", {}),
                )
                self._sessions[session.session_id] = session
            logger.info(
                "Loaded %d web chat sessions from %s",
                len(data),
                self._persistence_path,
            )
        except (json.JSONDecodeError, KeyError, OSError):
            logger.warning("Failed to load web chat sessions", exc_info=True)
