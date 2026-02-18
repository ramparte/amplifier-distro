"""Shared Surface Session Registry.

Provides a reusable session-mapping service that any surface (Slack,
Web Chat, Voice, etc.) can take as a constructor dependency.

The registry owns:
- Mapping storage (routing_key -> SessionMapping)
- Persistence (JSON via atomic_write)
- Per-user session limits
- Activity tracking and lifecycle (active/inactive)
- Queries (by routing key, session ID, user, active status)

Surfaces own:
- Routing key construction (surface-specific)
- Backend interaction (create_session, send_message, end_session)
- Surface-specific API calls (Slack threads, web sockets, etc.)

Design: Composition, not inheritance. Surfaces hold a registry
instance — they do NOT extend it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SessionMapping:
    """Maps a surface-specific routing key to an Amplifier session.

    Universal fields live as typed attributes. Surface-specific fields
    (e.g. Slack's channel_id, thread_ts) go in ``extra``.
    """

    routing_key: str
    session_id: str
    surface: str = ""
    project_id: str = ""
    description: str = ""
    created_by: str = ""
    created_at: str = ""
    last_active: str = ""
    is_active: bool = True
    extra: dict = field(default_factory=dict)


class SurfaceSessionRegistry:
    """Shared session-mapping service.

    Surfaces take this as a constructor dependency and delegate
    persistence, limits, and queries to it.

    Args:
        surface_name: Identifier for the surface ("slack", "web-chat").
        persistence_path: JSON file for persistence. None disables persistence.
        max_per_user: Maximum active sessions per user_id.
    """

    def __init__(
        self,
        surface_name: str,
        persistence_path: Path | None,
        max_per_user: int = 10,
    ) -> None:
        self._surface = surface_name
        self._persistence_path = persistence_path
        self._max_per_user = max_per_user
        self._mappings: dict[str, SessionMapping] = {}
        self._load()

    # --- Persistence ---

    def _load(self) -> None:
        """Load session mappings from the persistence file."""
        if self._persistence_path is None or not self._persistence_path.exists():
            return
        try:
            data = json.loads(self._persistence_path.read_text())
            for entry in data:
                # Handle old Slack format: has channel_id but no routing_key
                if "routing_key" not in entry and "channel_id" in entry:
                    channel_id = entry["channel_id"]
                    thread_ts = entry.get("thread_ts")
                    if thread_ts:
                        routing_key = f"{channel_id}:{thread_ts}"
                    else:
                        routing_key = channel_id
                    extra = {
                        "channel_id": channel_id,
                        "thread_ts": thread_ts or "",
                    }
                    mapping = SessionMapping(
                        routing_key=routing_key,
                        session_id=entry["session_id"],
                        surface=entry.get("surface", self._surface),
                        project_id=entry.get("project_id", ""),
                        description=entry.get("description", ""),
                        created_by=entry.get("created_by", ""),
                        created_at=entry.get("created_at", ""),
                        last_active=entry.get("last_active", ""),
                        is_active=entry.get("is_active", True),
                        extra=extra,
                    )
                else:
                    mapping = SessionMapping(
                        routing_key=entry["routing_key"],
                        session_id=entry["session_id"],
                        surface=entry.get("surface", self._surface),
                        project_id=entry.get("project_id", ""),
                        description=entry.get("description", ""),
                        created_by=entry.get("created_by", ""),
                        created_at=entry.get("created_at", ""),
                        last_active=entry.get("last_active", ""),
                        is_active=entry.get("is_active", True),
                        extra=entry.get("extra", {}),
                    )
                self._mappings[mapping.routing_key] = mapping
            logger.info(
                f"Loaded {len(data)} session mappings from {self._persistence_path}"
            )
        except (json.JSONDecodeError, KeyError, OSError):
            logger.warning("Failed to load session mappings", exc_info=True)

    def _save(self) -> None:
        """Save session mappings to the persistence file via atomic_write."""
        if self._persistence_path is None:
            return
        try:
            from amplifier_distro.fileutil import atomic_write

            data = [
                {
                    "routing_key": m.routing_key,
                    "session_id": m.session_id,
                    "surface": m.surface,
                    "project_id": m.project_id,
                    "description": m.description,
                    "created_by": m.created_by,
                    "created_at": m.created_at,
                    "last_active": m.last_active,
                    "is_active": m.is_active,
                    "extra": m.extra,
                }
                for m in self._mappings.values()
            ]
            atomic_write(self._persistence_path, json.dumps(data, indent=2))
        except OSError:
            logger.warning("Failed to save session mappings", exc_info=True)

    # --- Registration ---

    def register(
        self,
        routing_key: str,
        session_id: str,
        user_id: str,
        project_id: str = "",
        description: str = "",
        **extra: str,
    ) -> SessionMapping:
        """Register a new session mapping.

        Any keyword arguments beyond the named parameters are stored
        in ``mapping.extra`` for surface-specific fields.
        """
        now = datetime.now(UTC).isoformat()
        mapping = SessionMapping(
            routing_key=routing_key,
            session_id=session_id,
            surface=self._surface,
            project_id=project_id,
            description=description,
            created_by=user_id,
            created_at=now,
            last_active=now,
            extra=dict(extra),
        )
        self._mappings[routing_key] = mapping
        self._save()
        return mapping

    # --- Lookup ---

    def lookup(self, routing_key: str) -> SessionMapping | None:
        """Find a mapping by routing key."""
        return self._mappings.get(routing_key)

    def lookup_by_session_id(self, session_id: str) -> SessionMapping | None:
        """Find a mapping by Amplifier session ID (linear scan)."""
        for mapping in self._mappings.values():
            if mapping.session_id == session_id:
                return mapping
        return None

    # --- Lifecycle ---

    def update_activity(self, routing_key: str) -> None:
        """Update the last_active timestamp for a mapping."""
        mapping = self._mappings.get(routing_key)
        if mapping is None:
            return
        mapping.last_active = datetime.now(UTC).isoformat()
        self._save()

    def deactivate(self, routing_key: str) -> None:
        """Mark a mapping as inactive."""
        mapping = self._mappings.get(routing_key)
        if mapping is None:
            return
        mapping.is_active = False
        self._save()

    def remove(self, routing_key: str) -> SessionMapping | None:
        """Remove a mapping entirely. Returns the removed mapping or None."""
        mapping = self._mappings.pop(routing_key, None)
        if mapping is not None:
            self._save()
        return mapping

    # --- Queries ---

    def list_active(self) -> list[SessionMapping]:
        """List all active mappings."""
        return [m for m in self._mappings.values() if m.is_active]

    def list_for_user(self, user_id: str) -> list[SessionMapping]:
        """List active mappings for a specific user."""
        return [
            m
            for m in self._mappings.values()
            if m.created_by == user_id and m.is_active
        ]

    # --- Limits ---

    def check_limit(self, user_id: str) -> None:
        """Raise ValueError if the user has reached the session limit."""
        active = self.list_for_user(user_id)
        if len(active) >= self._max_per_user:
            raise ValueError(
                f"Session limit reached ({self._max_per_user}). "
                "End an existing session first."
            )

    # --- Properties ---

    @property
    def mappings(self) -> dict[str, SessionMapping]:
        """Current mappings (read-only copy)."""
        return dict(self._mappings)
