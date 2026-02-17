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

import logging
from dataclasses import dataclass
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

    def __init__(self) -> None:
        from amplifier_distro.bridge import LocalBridge

        self._bridge = LocalBridge()
        self._sessions: dict[str, Any] = {}  # session_id -> SessionHandle

    async def create_session(
        self,
        working_dir: str = "~",
        bundle_name: str | None = None,
        description: str = "",
        surface: str = "",
    ) -> SessionInfo:
        from pathlib import Path

        from amplifier_distro.bridge import BridgeConfig

        config = BridgeConfig(
            working_dir=Path(working_dir).expanduser(),
            bundle_name=bundle_name,
            run_preflight=False,  # Server already validated
            surface=surface,
        )
        handle = await self._bridge.create_session(config)
        self._sessions[handle.session_id] = handle

        return SessionInfo(
            session_id=handle.session_id,
            project_id=handle.project_id,
            working_dir=str(handle.working_dir),
            is_active=True,
            description=description,
            created_by_app=surface,
        )

    async def send_message(self, session_id: str, message: str) -> str:
        handle = self._sessions.get(session_id)
        if handle is None:
            # Session handle lost (server restart). Try to reconnect.
            handle = await self._reconnect(session_id)
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
            logger.info(f"Reconnected session {session_id}")
            return handle
        except (FileNotFoundError, ValueError, RuntimeError, OSError) as err:
            logger.warning(f"Failed to reconnect session {session_id}", exc_info=True)
            raise ValueError(f"Unknown session: {session_id}") from err

    async def end_session(self, session_id: str) -> None:
        handle = self._sessions.pop(session_id, None)
        if handle:
            await self._bridge.end_session(handle)

    async def get_session_info(self, session_id: str) -> SessionInfo | None:
        handle = self._sessions.get(session_id)
        if handle is None:
            return None
        return SessionInfo(
            session_id=handle.session_id,
            project_id=handle.project_id,
            working_dir=str(handle.working_dir),
        )

    def list_active_sessions(self) -> list[SessionInfo]:
        return [
            SessionInfo(
                session_id=h.session_id,
                project_id=h.project_id,
                working_dir=str(h.working_dir),
            )
            for h in self._sessions.values()
        ]
