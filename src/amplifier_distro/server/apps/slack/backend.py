"""Session backend - abstracts Amplifier session interaction.

The backend protocol separates Slack message routing from Amplifier
session management, making the bridge fully testable without a real
Amplifier runtime.

Implementations:
- MockBackend: Echo/canned responses (testing, simulator)
- BridgeBackend: Real sessions via LocalBridge (production)
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


@runtime_checkable
class SessionBackend(Protocol):
    """Protocol for Amplifier session interaction."""

    async def create_session(
        self,
        working_dir: str = "~",
        bundle_name: str | None = None,
        description: str = "",
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
    ) -> SessionInfo:
        self._session_counter += 1
        session_id = f"mock-session-{self._session_counter:04d}"
        info = SessionInfo(
            session_id=session_id,
            project_id=f"mock-project-{self._session_counter}",
            working_dir=working_dir,
            is_active=True,
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
    The LocalBridge integration is still being wired up in the distro,
    so this backend will grow as that integration lands.
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
    ) -> SessionInfo:
        from pathlib import Path

        from amplifier_distro.bridge import BridgeConfig

        config = BridgeConfig(
            working_dir=Path(working_dir).expanduser(),
            bundle_name=bundle_name,
            run_preflight=False,  # Server already validated
        )
        handle = await self._bridge.create_session(config)
        self._sessions[handle.session_id] = handle

        return SessionInfo(
            session_id=handle.session_id,
            project_id=handle.project_id,
            working_dir=str(handle.working_dir),
            is_active=True,
        )

    async def send_message(self, session_id: str, message: str) -> str:
        handle = self._sessions.get(session_id)
        if handle is None:
            raise ValueError(f"Unknown session: {session_id}")
        return await handle.run(message)

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
