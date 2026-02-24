"""Chat App — Rich WebSocket-based chat UI for amplifier-distro.

Successor to web_chat. Provides streaming text, thinking blocks,
tool call cards, sub-agent nesting, focus mode, and multi-session.

Routes:
    GET  /                 - Serves the chat HTML page
    GET  /vendor.js        - Serves vendored frontend bundle
    GET  /api/health       - Health check
    WS   /ws               - WebSocket chat connection (Task 6)
    GET  /api/sessions     - List sessions (Task 11)
    GET  /api/sessions/{id}/transcript  - Transcript (Task 12)
    GET  /api/preferences  - User preferences (Task 13)
    PUT  /api/preferences  - Update preferences (Task 13)
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import types
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, Response

from amplifier_distro.conventions import (
    AMPLIFIER_HOME,
    PROJECTS_DIR,
    TRANSCRIPT_FILENAME,
)
from amplifier_distro.server.app import AppManifest
from amplifier_distro.server.apps.chat.preferences import (
    load_preferences,
    save_preferences,
)

logger = logging.getLogger(__name__)


def _require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> None:
    """Verify api_key if configured. No-op when api_key is None."""
    try:
        from amplifier_distro.config import get_config as _get_config

        config = _get_config()
        api_key = getattr(config.server, "api_key", None)
    except ImportError:
        return  # no auth configured
    if api_key is None:
        return  # auth not enabled
    if not x_api_key or not hmac.compare_digest(str(x_api_key), str(api_key)):
        raise HTTPException(status_code=401, detail="Unauthorized")


router = APIRouter()

_static_dir = Path(__file__).parent / "static"

_VALID_SESSION_ID = re.compile(r"^[a-zA-Z0-9_\-]+$")


@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the chat interface."""
    html_file = _static_dir / "index.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
    return HTMLResponse(
        content=(
            "<html><body>"
            "<h1>Amplifier Chat</h1>"
            "<p>index.html not found. Run the vendor build step.</p>"
            "</body></html>"
        ),
        status_code=200,
    )


@router.get("/vendor.js")
async def vendor_js() -> Response:
    """Serve vendored frontend bundle (Preact + HTM + marked.js)."""
    vendor_file = _static_dir / "vendor.js"
    if vendor_file.exists():
        return Response(
            content=vendor_file.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )
    return Response(
        content="// vendor.js not found — run the vendor build step\n",
        media_type="application/javascript",
        status_code=404,
    )


@router.get("/api/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket endpoint — one connection per Amplifier session."""
    from amplifier_distro.server.apps.chat.connection import ChatConnection
    from amplifier_distro.server.services import get_services

    try:
        from amplifier_distro.config import get_config as _get_config

        config = _get_config()
    except ImportError:
        logger.warning(
            "amplifier_distro.config not installed — running without API key auth"
        )
        config = types.SimpleNamespace(server=types.SimpleNamespace(api_key=None))

    try:
        services = get_services()
    except Exception:
        logger.exception("Services unavailable — closing WebSocket with 1011")
        await ws.accept()
        await ws.close(1011, "Internal server error")
        return

    conn = ChatConnection(ws, services.backend, config)
    await conn.run()


# TODO: sessions list only shows in-memory active sessions (current process).
# Sessions from previous server runs are on disk but not listed here.
# Future: union active sessions with disk-discovered session directories.
@router.get("/api/sessions", dependencies=[Depends(_require_api_key)])
async def list_sessions() -> dict:
    """List all active chat sessions with metadata."""
    from amplifier_distro.server.services import get_services

    try:
        services = get_services()
    except Exception:  # noqa: BLE001
        logger.warning("Services unavailable — returning empty session list")
        return {"sessions": []}

    sessions = services.backend.list_active_sessions()
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "working_dir": str(s.working_dir) if s.working_dir else None,
                "description": s.description,
                "is_active": s.is_active,
            }
            for s in sessions
        ]
    }


@router.get(
    "/api/sessions/{session_id}/transcript",
    dependencies=[Depends(_require_api_key)],
)
async def get_transcript(session_id: str) -> JSONResponse:
    """Return the transcript for a session as a JSON array of messages."""
    if not _VALID_SESSION_ID.fullmatch(session_id):
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid session ID format"},
        )

    projects_path = Path(AMPLIFIER_HOME).expanduser() / PROJECTS_DIR

    # Search all project directories for this session
    transcript_file: Path | None = None
    if projects_path.exists():
        for project_dir in projects_path.iterdir():
            if not project_dir.is_dir():
                continue
            sessions_subdir = project_dir / "sessions"
            candidate_dir = sessions_subdir if sessions_subdir.is_dir() else project_dir
            candidate = candidate_dir / session_id / TRANSCRIPT_FILENAME
            if candidate.exists():
                transcript_file = candidate
                break

    if transcript_file is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"Session {session_id!r} not found"},
        )

    messages = []
    try:
        with transcript_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if isinstance(entry, dict) and entry.get("role"):
                        messages.append(entry)
                except json.JSONDecodeError:
                    continue
    except OSError:
        logger.warning(
            "Failed to read transcript for session %r", session_id, exc_info=True
        )
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to read transcript. Check server logs."},
        )

    return JSONResponse(
        content={
            "session_id": session_id,
            "transcript": messages,
        }
    )


@router.get("/api/preferences")
async def get_preferences() -> dict:
    """Return current user preferences."""
    return load_preferences()


@router.put("/api/preferences", dependencies=[Depends(_require_api_key)])
async def put_preferences(request: Request) -> dict:
    """Apply partial preference updates."""
    raw = await request.body()
    if not raw:
        return save_preferences({})
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="Request body must be valid JSON"
        ) from exc
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400, detail="Request body must be a JSON object"
        )
    try:
        return save_preferences(body)
    except OSError as exc:
        logger.warning("Failed to persist preferences", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Preferences could not be saved. Check disk/permissions.",
        ) from exc


manifest = AppManifest(
    name="chat",
    description="Amplifier rich web chat interface with WebSocket streaming",
    version="0.1.0",
    router=router,
)
