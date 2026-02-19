"""Web Chat App - Amplifier web chat interface.

Serves a self-contained chat UI and provides API endpoints for
session management and chat. Uses the shared server backend to
create and interact with Amplifier sessions.

Memory-aware: recognizes "remember this: ..." and "what do you remember
about ..." patterns and routes them through the memory service instead of
(or before) the Amplifier backend.

Routes:
    GET  /              - Serves the chat HTML page
    GET  /api/session   - Session connection status
    POST /api/session   - Create a new session
    POST /api/chat      - Send a message to active session
    POST /api/end       - End the active session
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from amplifier_distro.conventions import (
    AMPLIFIER_HOME,
    SERVER_DIR,
    WEB_CHAT_SESSIONS_FILENAME,
)
from amplifier_distro.server.app import AppManifest
from amplifier_distro.server.apps.web_chat.session_store import (
    WebChatSession,
    WebChatSessionStore,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_static_dir = Path(__file__).parent / "static"

# --- Memory pattern matching ---

# Patterns for "remember this: <text>" style messages
_REMEMBER_PATTERNS = [
    re.compile(r"^remember\s+this:\s*(.+)", re.IGNORECASE | re.DOTALL),
    re.compile(r"^remember\s+that\s+(.+)", re.IGNORECASE | re.DOTALL),
    re.compile(r"^remember:\s*(.+)", re.IGNORECASE | re.DOTALL),
]

# Patterns for "what do you remember about <query>" style messages
_RECALL_PATTERNS = [
    re.compile(r"^what\s+do\s+you\s+remember\s+about\s+(.+)", re.IGNORECASE),
    re.compile(r"^recall\s+(.+)", re.IGNORECASE),
    re.compile(r"^search\s+memory\s+(?:for\s+)?(.+)", re.IGNORECASE),
]


def check_memory_intent(message: str) -> tuple[str, str] | None:
    """Check if a message is a memory command.

    Returns:
        A (action, text) tuple if it's a memory command, or None.
        action is 'remember' or 'recall'.
    """
    stripped = message.strip()
    for pattern in _REMEMBER_PATTERNS:
        match = pattern.match(stripped)
        if match:
            return ("remember", match.group(1).strip())
    for pattern in _RECALL_PATTERNS:
        match = pattern.match(stripped)
        if match:
            return ("recall", match.group(1).strip())
    return None


def _handle_memory_command(action: str, text: str) -> dict[str, Any]:
    """Handle a memory command and return a chat-style response.

    Args:
        action: 'remember' or 'recall'.
        text: The memory content or search query.

    Returns:
        Dict with 'response' key suitable for chat response.
    """
    from amplifier_distro.server.memory import get_memory_service

    service = get_memory_service()

    if action == "remember":
        result = service.remember(text)
        return {
            "response": (
                f"Remembered! Stored as {result['id']} "
                f"(category: {result['category']}, "
                f"tags: {', '.join(result['tags'])})"
            ),
            "memory_action": "remember",
            "memory_result": result,
        }
    else:  # recall
        results = service.recall(text)
        if not results:
            return {
                "response": f"No memories found matching '{text}'.",
                "memory_action": "recall",
                "memory_result": [],
            }
        lines = [
            f"Found {len(results)} memory(ies):\n",
            *[f"- [{m['id']}] ({m['category']}) {m['content']}" for m in results],
        ]
        return {
            "response": "\n".join(lines),
            "memory_action": "recall",
            "memory_result": results,
        }


def _get_backend():
    """Get the shared session backend."""
    from amplifier_distro.server.services import get_services

    return get_services().backend


class WebChatSessionManager:
    """Manages web chat sessions: store registry + backend lifecycle.

    Replaces the module-level _active_session_id global and _session_lock.
    One active session at a time (single-user web chat).

    Pass persistence_path=None to disable disk persistence (test mode).
    In production, persistence_path is resolved at singleton creation time.
    """

    def __init__(
        self,
        backend: Any,
        persistence_path: Path | None = None,
    ) -> None:
        self._backend = backend
        self._store = WebChatSessionStore(persistence_path=persistence_path)

    @property
    def active_session_id(self) -> str | None:
        """ID of the current active session, or None."""
        session = self._store.active_session()
        return session.session_id if session else None

    async def create_session(
        self,
        working_dir: str = "~",
        description: str = "Web chat session",
    ):
        """Deactivate current session (store only), create a new one, register in store.

        The previous session is only deactivated in the store registry — the
        backend session stays alive so it can be resumed later via resume_session().
        Explicit termination on the backend only happens via end_session().

        Returns the SessionInfo from the backend.
        """
        # Deactivate existing session in store only (backend stays alive for resume)
        existing = self._store.active_session()
        if existing:
            self._store.deactivate(existing.session_id)

        info = await self._backend.create_session(
            working_dir=working_dir,
            description=description,
        )
        self._store.add(
            info.session_id,
            description,
            extra={"project_id": info.project_id},
        )
        return info

    async def send_message(self, message: str) -> str | None:
        """Send message to active session. Returns None if no session.

        Updates last_active on success.
        On backend ValueError (session died), deactivates store entry and re-raises.
        """
        session = self._store.active_session()
        if session is None:
            return None

        self._store.touch(session.session_id)

        try:
            return await self._backend.send_message(session.session_id, message)
        except ValueError:
            # Backend confirmed session is dead — deactivate in store
            self._store.deactivate(session.session_id)
            raise

    async def end_session(self) -> bool:
        """Deactivate and end the active session.

        Returns True if a session existed, False otherwise.
        """
        session = self._store.active_session()
        if session is None:
            return False
        await self._end_active(session.session_id)
        return True

    def list_sessions(self) -> list[WebChatSession]:
        """All sessions sorted by last_active desc."""
        return self._store.list_all()

    def resume_session(self, session_id: str) -> WebChatSession:
        """Switch active session to session_id.

        Deactivates the current active session (store only — backend stays alive).
        Raises ValueError if session_id is not found.
        """
        if self._store.get(session_id) is None:
            raise ValueError(f"Session {session_id!r} not found")

        # Deactivate current if it's a different session
        current = self._store.active_session()
        if current and current.session_id != session_id:
            self._store.deactivate(current.session_id)

        return self._store.reactivate(session_id)

    async def _end_active(self, session_id: str) -> None:
        """Deactivate in store and end on backend. Swallows backend errors."""
        self._store.deactivate(session_id)
        try:
            await self._backend.end_session(session_id)
        except (RuntimeError, ValueError, OSError):
            logger.warning("Error ending session %s", session_id, exc_info=True)


_manager: WebChatSessionManager | None = None


def _get_manager() -> WebChatSessionManager:
    """Return the module-level WebChatSessionManager singleton.

    Creates it on first call, wiring up the real persistence path.
    """
    global _manager
    if _manager is None:
        persistence_path = (
            Path(AMPLIFIER_HOME).expanduser() / SERVER_DIR / WEB_CHAT_SESSIONS_FILENAME
        )
        _manager = WebChatSessionManager(
            _get_backend(),
            persistence_path=persistence_path,
        )
    return _manager


@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the web chat interface."""
    html_file = _static_dir / "index.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text())
    return HTMLResponse(
        content=(
            "<h1>Amplifier Web Chat</h1>"
            "<p>index.html not found. Reinstall amplifier-distro.</p>"
        ),
        status_code=500,
    )


@router.get("/api/session")
async def session_status() -> dict:
    """Return session connection status.

    Reports whether a session is active and its ID.
    """
    manager = _get_manager()
    session_id = manager.active_session_id

    if session_id is None:
        return {
            "connected": False,
            "session_id": None,
            "message": "No active session. Click 'New Session' to start.",
        }

    try:
        info = await manager._backend.get_session_info(session_id)
        if info and info.is_active:
            return {
                "connected": True,
                "session_id": session_id,
                "project_id": info.project_id,
                "working_dir": info.working_dir,
            }
        else:
            await manager.end_session()
            return {
                "connected": False,
                "session_id": None,
                "message": "Previous session ended. Start a new one.",
            }
    except RuntimeError:
        return {
            "connected": False,
            "session_id": None,
            "message": "Server services not ready. Is the server fully started?",
        }


@router.post("/api/session")
async def create_session(request: Request) -> JSONResponse:
    """Create a new Amplifier session for web chat.

    Body (all optional):
        working_dir: str - Working directory for the session
        description: str - Human-readable description
    """
    body = await request.json() if await request.body() else {}
    try:
        manager = _get_manager()
        info = await manager.create_session(
            working_dir=body.get("working_dir", "~"),
            description=body.get("description", "Web chat session"),
        )
        return JSONResponse(
            content={
                "session_id": info.session_id,
                "project_id": info.project_id,
                "working_dir": info.working_dir,
            }
        )
    except RuntimeError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        logger.warning("Session creation failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500, content={"error": str(e), "type": type(e).__name__}
        )


@router.post("/api/chat")
async def chat(request: Request) -> JSONResponse:
    """Chat endpoint - send a message to the active session.

    Memory-aware: intercepts "remember this: ..." and "what do you
    remember about ..." patterns and routes them through the memory
    service. Memory commands work even without an active session.

    Body:
        message: str - The user's message
    """
    manager = _get_manager()
    body = await request.json()
    user_message = body.get("message", "")

    if not user_message:
        return JSONResponse(
            status_code=400,
            content={"error": "message is required"},
        )

    # Check for memory commands first - these work without a session
    memory_intent = check_memory_intent(user_message)
    if memory_intent is not None:
        action, text = memory_intent
        try:
            result = _handle_memory_command(action, text)
            result["session_connected"] = manager.active_session_id is not None
            return JSONResponse(content=result)
        except Exception as e:  # noqa: BLE001
            logger.warning("Memory command failed: %s", e, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": str(e), "type": type(e).__name__},
            )

    if manager.active_session_id is None:
        return JSONResponse(
            status_code=409,
            content={
                "error": "No active session. Create one first via POST /api/session.",
                "session_connected": False,
            },
        )

    try:
        response = await manager.send_message(user_message)
        return JSONResponse(
            content={
                "response": response,
                "session_id": manager.active_session_id,
                "session_connected": True,
            }
        )
    except ValueError:
        return JSONResponse(
            status_code=409,
            content={
                "error": "Session no longer exists. Create a new one.",
                "session_connected": False,
            },
        )
    except RuntimeError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        logger.warning("Chat message failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "type": type(e).__name__},
        )


@router.post("/api/end")
async def end_session() -> JSONResponse:
    """End the active web chat session."""
    manager = _get_manager()
    session_id = manager.active_session_id

    if session_id is None:
        return JSONResponse(content={"ended": False, "message": "No active session."})

    await manager.end_session()
    return JSONResponse(content={"ended": True, "session_id": session_id})


@router.get("/api/sessions")
async def list_sessions() -> dict:
    """List all web chat sessions.

    Returns all sessions (active and inactive), sorted by last_active desc.
    """
    manager = _get_manager()
    sessions = manager.list_sessions()
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "description": s.description,
                "created_at": s.created_at,
                "last_active": s.last_active,
                "is_active": s.is_active,
                "project_id": s.extra.get("project_id", ""),
            }
            for s in sessions
        ]
    }


@router.post("/api/session/resume")
async def resume_session(request: Request) -> JSONResponse:
    """Resume a previously created session.

    Body:
        session_id: str - The session to resume

    Returns:
        200 with {session_id, resumed: true} on success
        400 if session_id is missing
        404 if session_id is not found in the registry
    """
    body = await request.json() if await request.body() else {}
    session_id = body.get("session_id")

    if not session_id:
        return JSONResponse(
            status_code=400,
            content={"error": "session_id is required"},
        )

    try:
        manager = _get_manager()
        session = manager.resume_session(session_id)
        return JSONResponse(
            content={
                "session_id": session.session_id,
                "resumed": True,
            }
        )
    except ValueError as e:
        return JSONResponse(
            status_code=404,
            content={"error": str(e)},
        )


manifest = AppManifest(
    name="web-chat",
    description="Amplifier web chat interface",
    version="0.1.0",
    router=router,
)
