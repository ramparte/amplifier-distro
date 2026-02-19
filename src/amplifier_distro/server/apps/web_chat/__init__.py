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

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from amplifier_distro.server.app import AppManifest

logger = logging.getLogger(__name__)

router = APIRouter()

_static_dir = Path(__file__).parent / "static"

# Per-connection session tracking (simple: one active session for web-chat)
# In the future this becomes per-user via auth tokens.
_active_session_id: str | None = None
_session_lock = asyncio.Lock()
_message_in_flight: bool = False  # True while a send_message() call is in progress

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


from amplifier_distro.conventions import (  # noqa: E402
    AMPLIFIER_HOME,
    SERVER_DIR,
    WEB_CHAT_SESSIONS_FILENAME,
)
from amplifier_distro.server.apps.web_chat.session_store import (  # noqa: E402
    WebChatSession,
    WebChatSessionStore,
)


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
        """End any active session, create a new one, register in store.

        Returns the SessionInfo from the backend.
        """
        # End existing session if any
        existing = self._store.active_session()
        if existing:
            await self._end_active(existing.session_id)

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
    """Return session connection status."""
    global _active_session_id

    async with _session_lock:
        if _active_session_id is None:
            return {
                "connected": False,
                "session_id": None,
                "message": "No active session. Click 'New Session' to start.",
            }
        session_id = _active_session_id

    # Lock released — backend I/O runs without blocking other routes
    try:
        backend = _get_backend()
        info = await backend.get_session_info(session_id)
        if info and info.is_active:
            return {
                "connected": True,
                "session_id": session_id,
                "project_id": info.project_id,
                "working_dir": info.working_dir,
            }
        else:
            async with _session_lock:
                # Only clear if it hasn't been replaced by a new session
                if _active_session_id == session_id:
                    _active_session_id = None
            return {
                "connected": False,
                "session_id": None,
                "message": "Previous session ended. Start a new one.",
            }
    except Exception:  # noqa: BLE001
        return {
            "connected": False,
            "session_id": None,
            "message": "Could not reach session backend.",
        }


@router.post("/api/session")
async def create_session(request: Request) -> JSONResponse:
    """Create a new Amplifier session for web chat.

    Body (all optional):
        working_dir: str - Working directory for the session
        description: str - Human-readable description
    """
    global _active_session_id

    body = await request.json() if await request.body() else {}

    # Capture and clear the old session id under the lock
    async with _session_lock:
        old_session_id = _active_session_id
        _active_session_id = None

    # End old session outside the lock
    if old_session_id:
        try:
            backend = _get_backend()
            await backend.end_session(old_session_id)
        except (RuntimeError, ValueError, OSError):
            logger.warning("Error ending previous session", exc_info=True)

    try:
        backend = _get_backend()
        info = await backend.create_session(
            working_dir=body.get("working_dir", "~"),
            description=body.get("description", "Web chat session"),
        )
        async with _session_lock:
            _active_session_id = info.session_id

        return JSONResponse(
            content={
                "session_id": info.session_id,
                "project_id": info.project_id,
                "working_dir": info.working_dir,
            }
        )
    except RuntimeError as e:
        return JSONResponse(
            status_code=503,
            content={"error": str(e)},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Session creation failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "type": type(e).__name__},
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
    global _active_session_id, _message_in_flight

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
            async with _session_lock:
                result["session_connected"] = _active_session_id is not None
            return JSONResponse(content=result)
        except Exception as e:  # noqa: BLE001
            logger.warning("Memory command failed: %s", e, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": str(e), "type": type(e).__name__},
            )

    async with _session_lock:
        if _active_session_id is None:
            return JSONResponse(
                status_code=409,
                content={
                    "error": (
                        "No active session. Create one first via POST /api/session."
                    ),
                    "session_connected": False,
                },
            )
        if _message_in_flight:
            return JSONResponse(
                status_code=409,
                content={
                    "error": "A message is already in-flight. Wait for it to complete.",
                    "session_connected": True,
                    "in_flight": True,
                },
            )
        session_id = _active_session_id
        _message_in_flight = True

    # Lock released — backend call runs concurrently with other routes
    try:
        backend = _get_backend()
        response = await backend.send_message(session_id, user_message)
        return JSONResponse(
            content={
                "response": response,
                "session_id": session_id,
                "session_connected": True,
            }
        )
    except ValueError:
        # Session disappeared — CAS guard: don't clobber a new session
        async with _session_lock:
            if _active_session_id == session_id:
                _active_session_id = None
        return JSONResponse(
            status_code=409,
            content={
                "error": "Session no longer exists. Create a new one.",
                "session_connected": False,
            },
        )
    except RuntimeError as e:
        return JSONResponse(
            status_code=503,
            content={"error": str(e)},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Chat message failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "type": type(e).__name__},
        )
    finally:
        _message_in_flight = False


@router.post("/api/end")
async def end_session() -> JSONResponse:
    """End the active web chat session."""
    global _active_session_id

    async with _session_lock:
        if _active_session_id is None:
            return JSONResponse(
                content={"ended": False, "message": "No active session."}
            )

        session_id = _active_session_id
        _active_session_id = None

    try:
        backend = _get_backend()
        await backend.end_session(session_id)
        return JSONResponse(content={"ended": True, "session_id": session_id})
    except (RuntimeError, ValueError, OSError) as e:
        logger.warning("Error ending session %s: %s", session_id, e)
        return JSONResponse(
            content={"ended": True, "session_id": session_id, "warning": str(e)}
        )


manifest = AppManifest(
    name="web-chat",
    description="Amplifier web chat interface",
    version="0.1.0",
    router=router,
)
