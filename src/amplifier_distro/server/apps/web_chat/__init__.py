"""Web Chat App - Amplifier web chat interface.

Serves a self-contained chat UI and provides API endpoints for
session management and chat. Uses the shared server backend to
create and interact with Amplifier sessions.

Routes:
    GET  /              - Serves the chat HTML page
    GET  /api/session   - Session connection status
    POST /api/session   - Create a new session
    POST /api/chat      - Send a message to active session
    POST /api/end       - End the active session
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from amplifier_distro.server.app import AppManifest

logger = logging.getLogger(__name__)

router = APIRouter()

_static_dir = Path(__file__).parent / "static"

# Per-connection session tracking (simple: one active session for web-chat)
# In the future this becomes per-user via auth tokens.
_active_session_id: str | None = None


def _get_backend():
    """Get the shared session backend."""
    from amplifier_distro.server.services import get_services

    return get_services().backend


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
    global _active_session_id

    if _active_session_id is None:
        return {
            "connected": False,
            "session_id": None,
            "message": "No active session. Click 'New Session' to start.",
        }

    # Verify session is still alive
    try:
        backend = _get_backend()
        info = await backend.get_session_info(_active_session_id)
        if info and info.is_active:
            return {
                "connected": True,
                "session_id": _active_session_id,
                "project_id": info.project_id,
                "working_dir": info.working_dir,
            }
        else:
            _active_session_id = None
            return {
                "connected": False,
                "session_id": None,
                "message": "Previous session ended. Start a new one.",
            }
    except RuntimeError:
        # Services not initialized
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
    global _active_session_id

    body = await request.json() if await request.body() else {}

    try:
        backend = _get_backend()

        # End existing session if any
        if _active_session_id:
            try:
                await backend.end_session(_active_session_id)
            except Exception:
                logger.warning("Error ending previous session", exc_info=True)

        info = await backend.create_session(
            working_dir=body.get("working_dir", "~"),
            description=body.get("description", "Web chat session"),
        )
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
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "type": type(e).__name__},
        )


@router.post("/api/chat")
async def chat(request: Request) -> JSONResponse:
    """Chat endpoint - send a message to the active session.

    Body:
        message: str - The user's message
    """
    global _active_session_id

    body = await request.json()
    user_message = body.get("message", "")

    if not user_message:
        return JSONResponse(
            status_code=400,
            content={"error": "message is required"},
        )

    if _active_session_id is None:
        return JSONResponse(
            status_code=409,
            content={
                "error": "No active session. Create one first via POST /api/session.",
                "session_connected": False,
            },
        )

    try:
        backend = _get_backend()
        response = await backend.send_message(_active_session_id, user_message)
        return JSONResponse(
            content={
                "response": response,
                "session_id": _active_session_id,
                "session_connected": True,
            }
        )
    except ValueError:
        # Session disappeared
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
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "type": type(e).__name__},
        )


@router.post("/api/end")
async def end_session() -> JSONResponse:
    """End the active web chat session."""
    global _active_session_id

    if _active_session_id is None:
        return JSONResponse(content={"ended": False, "message": "No active session."})

    session_id = _active_session_id
    _active_session_id = None

    try:
        backend = _get_backend()
        await backend.end_session(session_id)
        return JSONResponse(content={"ended": True, "session_id": session_id})
    except Exception as e:
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
