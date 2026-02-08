"""Web Chat App - Amplifier web interface.

Wraps the amplifier-web FastAPI application and mounts it as a
distro server app. This is the primary web chat interface.

If amplifier-web is not installed, the app still registers but
returns a helpful "not installed" message.
"""

import importlib.util

from fastapi import APIRouter

from amplifier_distro.server.app import AppManifest

router = APIRouter()

_web_available = importlib.util.find_spec("amplifier_web") is not None


@router.get("/")
async def index() -> dict[str, str]:
    """Web chat status."""
    if _web_available:
        return {
            "status": "available",
            "app": "web-chat",
            "message": "Amplifier web chat is available",
        }
    return {
        "status": "not_installed",
        "app": "web-chat",
        "message": "amplifier-web is not installed. Run: pip install amplifier-web",
        "install_hint": "pip install git+https://github.com/ramparte/amplifier-web.git",
    }


@router.get("/status")
async def status() -> dict[str, bool]:
    """Check if amplifier-web is available."""
    return {"available": _web_available}


manifest = AppManifest(
    name="web-chat",
    description="Amplifier web chat interface (wraps amplifier-web)",
    version="0.1.0",
    router=router,
)
