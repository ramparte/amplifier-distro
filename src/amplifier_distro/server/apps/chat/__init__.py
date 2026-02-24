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

import logging
from pathlib import Path

from fastapi import APIRouter, WebSocket
from fastapi.responses import HTMLResponse, Response

from amplifier_distro.server.app import AppManifest

logger = logging.getLogger(__name__)

router = APIRouter()

_static_dir = Path(__file__).parent / "static"


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
    except Exception:  # noqa: BLE001
        config = type("Config", (), {"server": type("S", (), {"api_key": None})()})()

    services = get_services()
    conn = ChatConnection(ws, services.backend, config)
    await conn.run()


manifest = AppManifest(
    name="chat",
    description="Amplifier rich web chat interface with WebSocket streaming",
    version="0.1.0",
    router=router,
)
