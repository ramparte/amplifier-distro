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
from amplifier_distro.server.session_backend import SessionBackend, SessionInfo
from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

logger = logging.getLogger(__name__)

router = APIRouter()

_static_dir = Path(__file__).parent / "static"

_manager: WebChatSessionManager | None = None


def _get_manager() -> WebChatSessionManager:
    """Get or create the WebChatSessionManager."""
    global _manager
    if _manager is None:
        _manager = WebChatSessionManager(_get_backend())
    return _manager


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
    """Manages the active web-chat session using the shared registry.

    Simple model: one active session at a time (max_per_user=1).
    Gains persistence and structured lifecycle from the registry.
    """

    def __init__(
        self,
        backend: SessionBackend,
        persistence_path: Path | None = None,
    ) -> None:
        self._backend = backend
        self._registry = SurfaceSessionRegistry(
            "web-chat",
            persistence_path,
            max_per_user=1,
        )
        self._lock = asyncio.Lock()

    @property
    def active_session_id(self) -> str | None:
        """Return the active session ID, or None."""
        active = self._registry.list_active()
        if active:
            return active[0].session_id
        return None

    async def create_session(
        self,
        working_dir: str = "~",
        description: str = "Web chat session",
    ) -> SessionInfo:
        """Create a new session, ending any existing one first."""
        async with self._lock:
            # End existing session if any
            active_id = self.active_session_id
            if active_id:
                await self._end_active(active_id)

            info = await self._backend.create_session(
                working_dir=working_dir,
                description=description,
            )
            self._registry.register(
                routing_key=info.session_id,
                session_id=info.session_id,
                user_id="web-chat",
                project_id=info.project_id,
                description=description,
            )
            return info

    async def send_message(self, message: str) -> str | None:
        """Send a message to the active session. Returns None if no session."""
        async with self._lock:
            active_id = self.active_session_id
            if active_id is None:
                return None
            mapping = self._registry.lookup_by_session_id(active_id)
            if mapping:
                self._registry.update_activity(mapping.routing_key)
            return await self._backend.send_message(active_id, message)

    async def end_session(self) -> bool:
        """End the active session. Returns True if one was ended."""
        async with self._lock:
            active_id = self.active_session_id
            if active_id is None:
                return False
            await self._end_active(active_id)
            return True

    def list_sessions(self) -> list:
        """List all sessions (active and inactive), most recent first."""
        sessions = self._registry.list_all()
        sessions.sort(key=lambda s: s.last_active, reverse=True)
        return sessions

    async def resume_session(self, session_id: str):
        """Resume a previous session, making it the active one.

        Deactivates the current session and reactivates the target.
        The backend will auto-reconnect on next send_message().

        Raises ValueError if session_id not found in registry.
        """
        async with self._lock:
            mapping = self._registry.lookup_by_session_id(session_id)
            if mapping is None:
                raise ValueError(f"Unknown session: {session_id}")

            # Deactivate current active session (if any)
            current_id = self.active_session_id
            if current_id and current_id != session_id:
                await self._end_active(current_id)

            # Reactivate the target
            self._registry.reactivate(mapping.routing_key)
            return mapping

    async def _end_active(self, session_id: str) -> None:
        """Deactivate and end a session."""
        mapping = self._registry.lookup_by_session_id(session_id)
        if mapping:
            self._registry.deactivate(mapping.routing_key)
        try:
            await self._backend.end_session(session_id)
        except (RuntimeError, ValueError, OSError):
            logger.warning("Error ending session %s", session_id, exc_info=True)


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
    mgr = _get_manager()

    if mgr.active_session_id is None:
        return {
            "connected": False,
            "session_id": None,
            "message": "No active session. Click 'New Session' to start.",
        }

    # Verify session is still alive
    try:
        backend = _get_backend()
        info = await backend.get_session_info(mgr.active_session_id)
        if info and info.is_active:
            return {
                "connected": True,
                "session_id": mgr.active_session_id,
                "project_id": info.project_id,
                "working_dir": info.working_dir,
            }
        else:
            # Session died externally - clean up registry
            await mgr.end_session()
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
    """Create a new Amplifier session for web chat."""
    body = await request.json() if await request.body() else {}

    try:
        mgr = _get_manager()
        info = await mgr.create_session(
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
    """Chat endpoint - send a message to the active session."""
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
            mgr = _get_manager()
            result["session_connected"] = mgr.active_session_id is not None
            return JSONResponse(content=result)
        except Exception as e:  # noqa: BLE001
            logger.warning("Memory command failed: %s", e, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": str(e), "type": type(e).__name__},
            )

    mgr = _get_manager()
    if mgr.active_session_id is None:
        return JSONResponse(
            status_code=409,
            content={
                "error": ("No active session. Create one first via POST /api/session."),
                "session_connected": False,
            },
        )

    try:
        response = await mgr.send_message(user_message)
        return JSONResponse(
            content={
                "response": response,
                "session_id": mgr.active_session_id,
                "session_connected": True,
            }
        )
    except ValueError:
        # Session disappeared
        await mgr.end_session()
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


@router.post("/api/end")
async def end_session() -> JSONResponse:
    """End the active web chat session."""
    mgr = _get_manager()
    session_id = mgr.active_session_id

    if session_id is None:
        return JSONResponse(content={"ended": False, "message": "No active session."})

    ended = await mgr.end_session()
    return JSONResponse(content={"ended": ended, "session_id": session_id})


@router.get("/api/sessions")
async def list_sessions() -> JSONResponse:
    """List all web chat sessions (active and inactive)."""
    mgr = _get_manager()
    sessions = mgr.list_sessions()
    return JSONResponse(
        content={
            "sessions": [
                {
                    "session_id": m.session_id,
                    "description": m.description or "Web chat session",
                    "created_at": m.created_at,
                    "last_active": m.last_active,
                    "is_active": m.is_active,
                    "project_id": m.project_id,
                }
                for m in sessions
            ],
        }
    )


@router.post("/api/session/resume")
async def resume_session(request: Request) -> JSONResponse:
    """Resume a previous web chat session."""
    body = await request.json()
    session_id = body.get("session_id")
    if not session_id:
        return JSONResponse(
            status_code=400,
            content={"error": "session_id is required"},
        )

    try:
        mgr = _get_manager()
        mapping = await mgr.resume_session(session_id)
        return JSONResponse(
            content={
                "session_id": mapping.session_id,
                "project_id": mapping.project_id,
                "resumed": True,
            }
        )
    except ValueError as e:
        return JSONResponse(
            status_code=404,
            content={"error": str(e)},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Session resume failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "type": type(e).__name__},
        )


manifest = AppManifest(
    name="web-chat",
    description="Amplifier web chat interface",
    version="0.1.0",
    router=router,
)
