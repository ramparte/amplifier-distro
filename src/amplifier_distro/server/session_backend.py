"""Server-level session backend - shared across all apps.

The SessionBackend protocol defines how any server app (web-chat, Slack,
voice, etc.) creates and interacts with Amplifier sessions. The server
owns ONE backend instance and shares it with all apps.

Implementations:
- MockBackend: Echo/canned responses (testing, dev/simulator mode)
- BridgeBackend: Real sessions via LocalBridge (production)

History: Originally lived in server/apps/slack/backend.py. Promoted to
server level so all apps share a single session pool.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class SessionInfo:
    """Information about a backend session."""

    session_id: str
    project_id: str = ""
    working_dir: str = ""
    is_active: bool = True
    # Which app created this session (e.g., "web-chat", "slack", "voice")
    created_by_app: str = ""
    description: str = ""
    # Metadata (populated by BridgeBackend when available)
    created_at: float = 0.0
    last_active: float = 0.0
    idle_seconds: float = 0.0


@dataclass
class SessionMeta:
    """Lifecycle metadata tracked alongside each session handle.

    Enables idle eviction, diagnostics, and admin dashboards.
    """

    created_by_surface: str = ""
    created_at: float = field(default_factory=time.monotonic)
    last_active: float = field(default_factory=time.monotonic)

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_active

    def touch(self) -> None:
        """Update last_active timestamp."""
        self.last_active = time.monotonic()


# Default limits (can be overridden via distro.yaml in the future)
DEFAULT_MAX_SESSIONS = 50
DEFAULT_IDLE_TIMEOUT_SECONDS = 3600  # 1 hour


@runtime_checkable
class SessionBackend(Protocol):
    """Protocol for Amplifier session interaction.

    This is the contract that all session backends implement.
    Apps get a backend instance from ServerServices and use it
    to create, message, and manage sessions.
    """

    async def create_session(
        self,
        working_dir: str = "~",
        bundle_name: str | None = None,
        description: str = "",
        surface: str = "",
    ) -> SessionInfo:
        """Create a new Amplifier session. Returns session info."""
        ...

    async def send_message(self, session_id: str, message: str) -> str:
        """Send a message to a session. Returns the response text."""
        ...

    async def end_session(self, session_id: str) -> None:
        """End a session and clean up."""
        ...

    async def get_session_info(self, session_id: str) -> SessionInfo | None:
        """Get info about an active session."""
        ...

    def list_active_sessions(self) -> list[SessionInfo]:
        """List all active sessions managed by this backend."""
        ...


class MockBackend:
    """Mock backend for testing and simulation.

    Returns echo responses or configurable canned responses.
    Tracks all interactions for test assertions.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._session_counter: int = 0
        self._message_history: dict[str, list[dict[str, str]]] = {}
        # Configurable response handler
        self._response_fn: Any = None
        # Recorded calls for test assertions
        self.calls: list[dict[str, Any]] = []

    def set_response_fn(self, fn: Any) -> None:
        """Set a custom response function: (session_id, message) -> response."""
        self._response_fn = fn

    async def create_session(
        self,
        working_dir: str = "~",
        bundle_name: str | None = None,
        description: str = "",
        surface: str = "",
    ) -> SessionInfo:
        self._session_counter += 1
        session_id = f"mock-session-{self._session_counter:04d}"
        info = SessionInfo(
            session_id=session_id,
            project_id=f"mock-project-{self._session_counter}",
            working_dir=working_dir,
            is_active=True,
            description=description,
            created_by_app=surface,
        )
        self._sessions[session_id] = info
        self._message_history[session_id] = []
        self.calls.append(
            {
                "method": "create_session",
                "working_dir": working_dir,
                "bundle_name": bundle_name,
                "description": description,
                "result": session_id,
            }
        )
        return info

    async def send_message(self, session_id: str, message: str) -> str:
        if session_id not in self._sessions:
            raise ValueError(f"Unknown session: {session_id}")

        self._message_history[session_id].append({"role": "user", "content": message})
        self.calls.append(
            {
                "method": "send_message",
                "session_id": session_id,
                "message": message,
            }
        )

        # Use custom response function if set
        if self._response_fn:
            response = self._response_fn(session_id, message)
        else:
            response = f"[Mock response to: {message}]"

        self._message_history[session_id].append(
            {"role": "assistant", "content": response}
        )
        return response

    async def end_session(self, session_id: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id].is_active = False
        self.calls.append({"method": "end_session", "session_id": session_id})

    async def get_session_info(self, session_id: str) -> SessionInfo | None:
        return self._sessions.get(session_id)

    def list_active_sessions(self) -> list[SessionInfo]:
        return [s for s in self._sessions.values() if s.is_active]

    def get_message_history(self, session_id: str) -> list[dict[str, str]]:
        """Get the full message history for a session (testing helper)."""
        return self._message_history.get(session_id, [])


class BridgeBackend:
    """Real backend using LocalBridge for Amplifier sessions.

    This connects to the actual Amplifier runtime via the distro bridge.
    Used in production mode.

    NOTE: Requires amplifier-foundation to be available at runtime.
    """

    def __init__(
        self,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
    ) -> None:
        if max_sessions < 1:
            raise ValueError(f"max_sessions must be >= 1, got {max_sessions}")
        if idle_timeout < 0:
            raise ValueError(f"idle_timeout must be >= 0, got {idle_timeout}")

        from amplifier_distro.bridge import LocalBridge

        self._bridge = LocalBridge()
        self._sessions: dict[str, Any] = {}  # session_id -> SessionHandle
        self._reconnect_locks: dict[str, asyncio.Lock] = {}
        self._meta: dict[str, SessionMeta] = {}  # session_id -> lifecycle metadata
        self._max_sessions = max_sessions
        self._idle_timeout = idle_timeout

    async def create_session(
        self,
        working_dir: str = "~",
        bundle_name: str | None = None,
        description: str = "",
        surface: str = "",
    ) -> SessionInfo:
        # Enforce global session cap
        if len(self._sessions) >= self._max_sessions:
            # Try evicting idle sessions first
            evicted = self._evict_idle()
            if len(self._sessions) >= self._max_sessions:
                msg = (
                    f"Session limit reached ({self._max_sessions} active). "
                    f"End an existing session before creating a new one."
                )
                if evicted:
                    msg += (
                        f" ({evicted} idle session(s) evicted but cap still reached.)"
                    )
                raise RuntimeError(msg)

        from pathlib import Path

        from amplifier_distro.bridge import BridgeConfig

        config = BridgeConfig(
            working_dir=Path(working_dir).expanduser(),
            bundle_name=bundle_name,
            run_preflight=False,  # Server already validated
        )
        handle = await self._bridge.create_session(config)
        self._sessions[handle.session_id] = handle
        self._meta[handle.session_id] = SessionMeta(created_by_surface=surface)

        return SessionInfo(
            session_id=handle.session_id,
            project_id=handle.project_id,
            working_dir=str(handle.working_dir),
            is_active=True,
            description=description,
            created_by_app=surface,
        )

    def _evict_idle(self) -> int:
        """Evict sessions that have been idle longer than the timeout.

        Returns the number of sessions evicted.  Called lazily from
        create_session when the pool is full.  Schedules async cleanup
        tasks for evicted handles so resources (hooks, context, bundle)
        are properly released.
        """
        import asyncio

        if self._idle_timeout <= 0:
            return 0

        to_evict = [
            sid
            for sid, meta in self._meta.items()
            if meta.idle_seconds > self._idle_timeout
        ]
        for sid in to_evict:
            handle = self._sessions.pop(sid, None)
            meta = self._meta.pop(sid, None)
            if handle:
                idle_secs = meta.idle_seconds if meta else 0.0
                surface = meta.created_by_surface if meta else "unknown"
                logger.warning(
                    "Evicting idle session %s (surface=%s, idle=%.0fs)",
                    sid,
                    surface,
                    idle_secs,
                )
                # Schedule async cleanup (writes handoff.md, flushes hooks).
                # Store ref to prevent GC before completion (RUF006).
                _task = asyncio.create_task(  # noqa: RUF006
                    self._safe_evict_cleanup(handle),
                    name=f"evict-cleanup-{sid}",
                )
        return len(to_evict)

    async def _safe_evict_cleanup(self, handle: Any) -> None:
        """Best-effort cleanup for evicted sessions.

        Routes through bridge.end_session() so handoff.md is written
        and session resources (hooks, coordinator, context) are released.
        """
        try:
            await self._bridge.end_session(handle)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Cleanup failed for evicted session %s",
                handle.session_id,
                exc_info=True,
            )

    async def send_message(self, session_id: str, message: str) -> str:
        handle = self._sessions.get(session_id)
        if handle is None:
            # Session handle lost (server restart). Use per-session lock
            # to prevent concurrent reconnects for the same session_id.
            lock = self._reconnect_locks.setdefault(session_id, asyncio.Lock())
            try:
                async with lock:
                    # Double-check: another coroutine may have reconnected
                    # while we waited for the lock.
                    handle = self._sessions.get(session_id)
                    if handle is None:
                        handle = await self._reconnect(session_id)
            finally:
                # Clean up lock entry on both success and failure paths
                self._reconnect_locks.pop(session_id, None)

        # Update activity timestamp
        meta = self._meta.get(session_id)
        if meta:
            meta.touch()

        return await handle.run(message)

    async def _reconnect(self, session_id: str) -> Any:
        """Attempt to resume a session whose handle was lost (e.g. after restart).

        On success the handle is cached so subsequent messages don't pay
        the resume cost again.  On failure the original ValueError is raised
        so callers see the same error they would have before.
        """
        logger.info(f"Attempting to reconnect lost session {session_id}")
        try:
            handle = await self._bridge.resume_session(session_id)
            self._sessions[session_id] = handle
            # Backfill metadata so the session is visible to eviction
            if session_id not in self._meta:
                self._meta[session_id] = SessionMeta(created_by_surface="reconnected")
            logger.info(f"Reconnected session {session_id}")
            return handle
        except (FileNotFoundError, ValueError, RuntimeError, OSError) as err:
            logger.warning(f"Failed to reconnect session {session_id}", exc_info=True)
            raise ValueError(f"Unknown session: {session_id}") from err

    async def end_session(self, session_id: str) -> None:
        handle = self._sessions.pop(session_id, None)
        self._meta.pop(session_id, None)
        if handle:
            await self._bridge.end_session(handle)

    async def get_session_info(self, session_id: str) -> SessionInfo | None:
        handle = self._sessions.get(session_id)
        if handle is None:
            return None
        meta = self._meta.get(session_id)
        return SessionInfo(
            session_id=handle.session_id,
            project_id=handle.project_id,
            working_dir=str(handle.working_dir),
            created_by_app=meta.created_by_surface if meta else "",
            created_at=meta.created_at if meta else 0.0,
            last_active=meta.last_active if meta else 0.0,
            idle_seconds=meta.idle_seconds if meta else 0.0,
        )

    def list_active_sessions(self) -> list[SessionInfo]:
        return [
            SessionInfo(
                session_id=h.session_id,
                project_id=h.project_id,
                working_dir=str(h.working_dir),
                created_by_app=self._meta[sid].created_by_surface
                if sid in self._meta
                else "",
                created_at=self._meta[sid].created_at if sid in self._meta else 0.0,
                last_active=self._meta[sid].last_active if sid in self._meta else 0.0,
                idle_seconds=self._meta[sid].idle_seconds if sid in self._meta else 0.0,
            )
            for sid, h in self._sessions.items()
        ]
