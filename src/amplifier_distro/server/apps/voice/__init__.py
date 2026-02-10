"""Voice App - Amplifier voice interface via OpenAI Realtime API.

Architecture:
    Browser (vanilla JS)
        -> WebRTC audio (Opus codec)
        -> OpenAI Realtime API (direct connection, no audio through server)
            -> Native speech-to-speech (no separate STT/TTS)
            -> Function calling for tools
        <- Audio response streamed back via WebRTC

    Backend (this module):
        GET  /           - Voice UI page
        GET  /session    - Create ephemeral client_secret from OpenAI
        POST /sdp        - Exchange WebRTC SDP offer/answer via OpenAI
        GET  /api/status - Voice service status

Key insight: The browser connects DIRECTLY to OpenAI via WebRTC for audio.
The backend only brokers session creation (ephemeral token) and SDP exchange.
No audio flows through our server.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from amplifier_distro.server.app import AppManifest

logger = logging.getLogger(__name__)

router = APIRouter()

# OpenAI Realtime API endpoints
OPENAI_REALTIME_BASE = "https://api.openai.com/v1/realtime"
OPENAI_SESSION_ENDPOINT = f"{OPENAI_REALTIME_BASE}/sessions"


def _get_openai_api_key() -> str | None:
    """Read OPENAI_API_KEY from environment.

    The server startup exports keys.yaml values into env vars,
    so we just read from os.environ.
    """
    return os.environ.get("OPENAI_API_KEY")


def _get_voice_config() -> dict[str, str]:
    """Load voice config from distro.yaml, with safe defaults."""
    try:
        from amplifier_distro.config import load_config

        cfg = load_config()
        return {
            "voice": cfg.voice.voice,
            "model": cfg.voice.model,
        }
    except Exception:
        logger.debug("Could not load voice config, using defaults")
        return {
            "voice": "ash",
            "model": "gpt-4o-realtime-preview",
        }


@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Voice interface page."""
    html_path = Path(__file__).parent / "voice.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(
        content="<h1>Amplifier Voice</h1><p>voice.html not found.</p>",
        status_code=500,
    )


@router.get("/session")
async def create_session() -> JSONResponse:
    """Create an ephemeral client secret from OpenAI Realtime API.

    Calls POST https://api.openai.com/v1/realtime/sessions to get
    a short-lived token the browser uses for WebRTC auth.

    Returns:
        JSON with client_secret.value and client_secret.expires_at
    """
    api_key = _get_openai_api_key()
    if not api_key:
        return JSONResponse(
            status_code=503,
            content={
                "error": "OPENAI_API_KEY not configured",
                "detail": "Set your OpenAI API key in keys.yaml or environment.",
            },
        )

    vcfg = _get_voice_config()

    payload: dict[str, Any] = {
        "model": vcfg["model"],
        "voice": vcfg["voice"],
        "modalities": ["audio", "text"],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                OPENAI_SESSION_ENDPOINT,
                json=payload,
                headers=headers,
            )

        if resp.status_code != 200:
            logger.error(
                "OpenAI session creation failed: %d - %s",
                resp.status_code,
                resp.text,
            )
            return JSONResponse(
                status_code=resp.status_code,
                content={
                    "error": "OpenAI session creation failed",
                    "detail": resp.text,
                },
            )

        data = resp.json()
        logger.info("Voice session created successfully")
        return JSONResponse(content=data)

    except httpx.TimeoutException:
        logger.error("Timeout connecting to OpenAI Realtime API")
        return JSONResponse(
            status_code=504,
            content={"error": "Timeout connecting to OpenAI"},
        )
    except httpx.HTTPError as exc:
        logger.error("HTTP error calling OpenAI: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": f"HTTP error: {exc}"},
        )


@router.post("/sdp", response_model=None)
async def exchange_sdp(request: Request) -> PlainTextResponse | JSONResponse:
    """Exchange WebRTC SDP offer/answer via OpenAI.

    The browser sends its SDP offer here along with an Authorization
    header containing the ephemeral token from /session.
    We relay this to OpenAI and return the SDP answer.

    Headers required:
        Authorization: Bearer <ephemeral_token>
        Content-Type: application/sdp

    Body: Raw SDP offer text

    Returns:
        SDP answer from OpenAI (text/sdp)
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        return JSONResponse(
            status_code=401,
            content={"error": "Authorization header required"},
        )

    offer_sdp = await request.body()
    if not offer_sdp:
        return JSONResponse(
            status_code=400,
            content={"error": "SDP offer body required"},
        )

    vcfg = _get_voice_config()
    sdp_url = f"{OPENAI_REALTIME_BASE}?model={vcfg['model']}"

    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/sdp",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                sdp_url,
                content=offer_sdp,
                headers=headers,
            )

        if resp.status_code != 200:
            logger.error(
                "OpenAI SDP exchange failed: %d - %s",
                resp.status_code,
                resp.text,
            )
            return JSONResponse(
                status_code=resp.status_code,
                content={
                    "error": "OpenAI SDP exchange failed",
                    "detail": resp.text,
                },
            )

        logger.info("SDP exchange successful")
        return PlainTextResponse(
            content=resp.text,
            media_type="application/sdp",
        )

    except httpx.TimeoutException:
        logger.error("Timeout during SDP exchange with OpenAI")
        return JSONResponse(
            status_code=504,
            content={"error": "Timeout during SDP exchange"},
        )
    except httpx.HTTPError as exc:
        logger.error("HTTP error during SDP exchange: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": f"HTTP error: {exc}"},
        )


@router.get("/api/status")
async def voice_status() -> dict[str, Any]:
    """Voice service status."""
    api_key = _get_openai_api_key()
    vcfg = _get_voice_config()

    return {
        "status": "ready" if api_key else "unconfigured",
        "api_key_set": bool(api_key),
        "model": vcfg["model"],
        "voice": vcfg["voice"],
        "message": (
            "Voice service ready."
            if api_key
            else "OPENAI_API_KEY not set. Configure it in keys.yaml."
        ),
    }


manifest = AppManifest(
    name="voice",
    description="Amplifier voice interface via OpenAI Realtime API",
    version="0.2.0",
    router=router,
)
