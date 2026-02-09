"""Web Chat App - Amplifier web chat interface.

Serves a self-contained chat UI and provides API endpoints for
session management and chat. This is the "hello world" landing
page after quickstart completes.

Routes:
    GET  /              - Serves the chat HTML page
    GET  /api/session   - Session connection status
    POST /api/chat      - Send a message (stub, echoes locally)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from amplifier_distro.server.app import AppManifest

router = APIRouter()

_static_dir = Path(__file__).parent / "static"


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

    When a real session backend is wired up, this will report
    the active session ID and connection health.
    """
    return {
        "connected": False,
        "session_id": None,
        "message": "No active session. Use the Bridge API or CLI to create one.",
    }


@router.post("/api/chat")
async def chat(request: Request) -> JSONResponse:
    """Chat endpoint.

    When a session backend is connected, this forwards the message
    to the Amplifier session and streams the response. For now it
    returns a helpful placeholder.
    """
    body = await request.json()
    user_message = body.get("message", "")

    # No session connected - return a helpful response
    return JSONResponse(
        content={
            "response": (
                "No Amplifier session is connected yet. "
                "Your message was received, but there is no AI "
                "backend to process it. Use the Amplifier CLI "
                "to start a session, or check Settings."
            ),
            "session_connected": False,
            "echo": user_message,
        }
    )


manifest = AppManifest(
    name="web-chat",
    description="Amplifier web chat interface",
    version="0.1.0",
    router=router,
)
