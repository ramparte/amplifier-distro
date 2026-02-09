"""Voice App - Amplifier voice interface.

Placeholder for the voice bridge. Provides WebSocket endpoint for
real-time voice interaction with Amplifier sessions.

Architecture (planned):
    Browser/Client
        -> WebSocket /ws
            -> Audio frames in (user speech)
            -> STT (speech-to-text)
            -> Amplifier session (via shared backend)
            -> TTS (text-to-speech)
            -> Audio frames out (assistant speech)

For now this is scaffolding only. The WebSocket endpoint accepts
connections and returns status messages, but does not process audio.

Team owner: TBD
Dependencies: shared SessionBackend from server.services

Routes:
    GET  /           - Voice UI page (placeholder)
    GET  /api/status - Voice service status
    WS   /ws         - WebSocket endpoint for voice streaming
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from amplifier_distro.server.app import AppManifest

logger = logging.getLogger(__name__)

router = APIRouter()

# Placeholder configuration - will move to distro.yaml voice section
_VOICE_CONFIG: dict[str, Any] = {
    "stt_provider": None,  # e.g., "whisper", "azure-speech", "deepgram"
    "tts_provider": None,  # e.g., "openai-tts", "azure-speech", "elevenlabs"
    "sample_rate": 16000,
    "channels": 1,
}


@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Voice interface landing page."""
    return HTMLResponse(
        content="""<!DOCTYPE html>
<html>
<head><title>Amplifier Voice</title></head>
<body style="font-family:system-ui;max-width:600px;margin:40px auto;padding:20px">
    <h1>Amplifier Voice</h1>
    <p>Voice interface is not yet implemented.</p>
    <p>This will provide real-time voice interaction with Amplifier sessions
       via WebSocket audio streaming.</p>
    <h3>Planned Features</h3>
    <ul>
        <li>Push-to-talk and voice activity detection</li>
        <li>Configurable STT/TTS providers</li>
        <li>Session continuity with other interfaces</li>
        <li>Audio streaming via WebSocket</li>
    </ul>
    <h3>Status</h3>
    <p id="status">Checking...</p>
    <script>
        fetch('./api/status')
            .then(r => r.json())
            .then(d => {
                document.getElementById('status').textContent =
                    JSON.stringify(d, null, 2)});
    </script>
</body>
</html>"""
    )


@router.get("/api/status")
async def voice_status() -> dict[str, Any]:
    """Voice service status."""
    return {
        "status": "placeholder",
        "message": "Voice interface not yet implemented.",
        "stt_provider": _VOICE_CONFIG["stt_provider"],
        "tts_provider": _VOICE_CONFIG["tts_provider"],
        "websocket_endpoint": "/apps/voice/ws",
    }


@router.websocket("/ws")
async def voice_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for voice streaming.

    Protocol (planned):
        Client -> Server:
            {"type": "start", "session_id": "...", "config": {...}}
            {"type": "audio", "data": "<base64 audio chunk>"}
            {"type": "end"}

        Server -> Client:
            {"type": "status", "message": "..."}
            {"type": "transcript", "text": "...", "final": bool}
            {"type": "response", "text": "...", "audio": "<base64>"}
            {"type": "error", "message": "..."}
    """
    await websocket.accept()

    try:
        # Send initial status
        await websocket.send_json(
            {
                "type": "status",
                "message": (
                    "Voice endpoint connected. Audio processing not yet implemented."
                ),
            }
        )

        # Echo loop - placeholder for real audio pipeline
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "unknown")

            if msg_type == "start":
                await websocket.send_json(
                    {
                        "type": "status",
                        "message": (
                            "Session start acknowledged."
                            " Audio processing is a placeholder."
                        ),
                        "session_id": data.get("session_id"),
                    }
                )
            elif msg_type == "audio":
                # Placeholder: acknowledge audio but don't process
                await websocket.send_json(
                    {
                        "type": "status",
                        "message": "Audio chunk received but STT not implemented.",
                    }
                )
            elif msg_type == "end":
                await websocket.send_json(
                    {"type": "status", "message": "Session ended."}
                )
                break
            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}",
                    }
                )

    except WebSocketDisconnect:
        logger.info("Voice WebSocket client disconnected")
    except Exception:
        logger.exception("Voice WebSocket error")


manifest = AppManifest(
    name="voice",
    description="Amplifier voice interface (placeholder)",
    version="0.1.0",
    router=router,
)
