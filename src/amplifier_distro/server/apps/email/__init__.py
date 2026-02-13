"""Email Bridge App - connects Gmail to Amplifier sessions.

This is the app plugin entry point for the distro server. It registers
FastAPI routes for:
- Bridge management API (/status, /sessions)
- Setup wizard endpoints (/setup/*)
- Email polling control (/poll, /poll/once)

Architecture:
    Gmail -> EmailPoller -> EmailEventHandler
        -> CommandHandler (for /amp commands in email body)
        -> EmailSessionManager -> SessionBackend -> Amplifier
        -> Reply via Gmail API

Configuration:
    Set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN
    in keys.yaml or environment variables. Non-secret config in
    distro.yaml under the email: section.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import APIRouter

from amplifier_distro.server.app import AppManifest

from .client import GmailClient, MemoryEmailClient
from .commands import CommandHandler
from .config import EmailConfig
from .events import EmailEventHandler
from .models import EmailAddress
from .poller import EmailPoller
from .sessions import EmailSessionManager
from .setup import router as setup_router

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Global bridge state (initialized on startup) ---

_state: dict[str, Any] = {}
_state_lock = threading.Lock()


def _get_state() -> dict[str, Any]:
    """Get the initialized bridge state."""
    with _state_lock:
        if not _state:
            raise RuntimeError("Email bridge not initialized. Call on_startup() first.")
        return _state


def initialize(
    config: EmailConfig | None = None,
    client: Any | None = None,
    backend: Any | None = None,
) -> dict[str, Any]:
    """Initialize the bridge components.

    This is separated from on_startup() so it can be called directly
    in tests with injected dependencies.

    Backend resolution order:
    1. Explicit backend parameter (tests)
    2. Shared server services backend (production)
    3. Fallback: create own MockBackend (standalone)
    """
    if config is None:
        config = EmailConfig.from_env()

    # Select client implementation
    if client is None:
        if config.simulator_mode or not config.is_configured:
            logger.info("Email bridge starting in simulator mode")
            client = MemoryEmailClient(
                agent_address=config.agent_address or "agent@test.com"
            )
            config.simulator_mode = True
        else:
            client = GmailClient(config)

    # Select backend: prefer shared server backend
    if backend is None:
        try:
            from amplifier_distro.server.services import get_services

            backend = get_services().backend
            logger.info("Email bridge using shared server backend")
        except RuntimeError:
            # Services not initialized (standalone mode or tests)
            from amplifier_distro.server.session_backend import MockBackend

            backend = MockBackend()
            logger.info("Email bridge using own backend (standalone mode)")

    session_manager = EmailSessionManager(client, backend, config)
    command_handler = CommandHandler(session_manager, config)
    event_handler = EmailEventHandler(client, session_manager, command_handler, config)
    poller = EmailPoller(client, event_handler, config)

    state = {
        "config": config,
        "client": client,
        "backend": backend,
        "session_manager": session_manager,
        "command_handler": command_handler,
        "event_handler": event_handler,
        "poller": poller,
    }
    with _state_lock:
        _state.update(state)

    return state


async def on_startup() -> None:
    """Initialize the email bridge on server startup."""
    initialize()
    with _state_lock:
        config: EmailConfig = _state["config"]
        poller: EmailPoller = _state["poller"]
    logger.info("Email bridge initialized (mode: %s)", config.mode)

    # Start polling if configured
    if config.is_configured and not config.simulator_mode:
        poller.start()
        logger.info(
            "Email polling started (interval: %ds)", config.poll_interval_seconds
        )


async def on_shutdown() -> None:
    """Clean up the email bridge on server shutdown."""
    with _state_lock:
        poller = _state.get("poller")
        session_manager = _state.get("session_manager")
        backend = _state.get("backend")

    # Stop polling
    if poller is not None:
        poller.stop()

    # End all active sessions
    if session_manager is not None and backend is not None:
        for mapping in session_manager.list_active():
            try:
                await backend.end_session(mapping.session_id)
            except (RuntimeError, ValueError, ConnectionError, OSError):
                logger.exception("Error ending session %s", mapping.session_id)

    with _state_lock:
        _state.clear()
    logger.info("Email bridge shut down")


# --- Bridge Management API ---


@router.get("/status")
async def bridge_status() -> dict[str, Any]:
    """Bridge health and status."""
    state = _get_state()
    config: EmailConfig = state["config"]
    session_manager: EmailSessionManager = state["session_manager"]
    poller: EmailPoller = state["poller"]

    return {
        "status": "ok",
        "mode": config.mode,
        "agent_address": config.agent_address,
        "active_sessions": len(session_manager.list_active()),
        "is_configured": config.is_configured,
        "polling": poller.is_running,
    }


@router.get("/sessions")
async def list_bridge_sessions() -> list[dict[str, Any]]:
    """List active session mappings."""
    state = _get_state()
    session_manager: EmailSessionManager = state["session_manager"]

    return [
        {
            "session_id": m.session_id,
            "thread_id": m.thread_id,
            "sender_address": m.sender_address,
            "subject": m.subject,
            "message_count": m.message_count,
            "is_active": m.is_active,
            "last_activity": m.last_activity,
        }
        for m in session_manager.list_active()
    ]


@router.post("/poll/once")
async def poll_once() -> dict[str, Any]:
    """Trigger a single poll cycle (useful for testing)."""
    state = _get_state()
    poller: EmailPoller = state["poller"]

    count = await poller.poll_once()
    return {"processed": count}


@router.post("/poll/start")
async def poll_start() -> dict[str, Any]:
    """Start the background poller."""
    state = _get_state()
    poller: EmailPoller = state["poller"]

    if poller.is_running:
        return {"status": "already_running"}

    poller.start()
    return {"status": "started"}


@router.post("/poll/stop")
async def poll_stop() -> dict[str, Any]:
    """Stop the background poller."""
    state = _get_state()
    poller: EmailPoller = state["poller"]

    if not poller.is_running:
        return {"status": "not_running"}

    poller.stop()
    return {"status": "stopped"}


@router.post("/send")
async def send_email(request: dict[str, Any]) -> dict[str, Any]:
    """Send an email via the bridge (API access for other apps)."""
    state = _get_state()
    client = state["client"]

    to_addr = request.get("to", "")
    subject = request.get("subject", "")
    body = request.get("body", "")

    if not to_addr or not body:
        return {"error": "Missing 'to' and 'body' fields"}

    try:
        msg_id = await client.send_email(
            to=EmailAddress(address=to_addr),
            subject=subject or "(no subject)",
            body_html=f"<p>{body}</p>",
            body_text=body,
        )
        return {"status": "sent", "message_id": msg_id}
    except Exception as e:
        logger.exception("Failed to send email")
        return {"status": "error", "error": str(e)}


# --- Setup Routes (always available for configuration) ---

router.include_router(setup_router)


# --- Manifest ---


manifest = AppManifest(
    name="email",
    description="Email bridge - connects Gmail to Amplifier sessions",
    version="0.1.0",
    router=router,
    on_startup=on_startup,
    on_shutdown=on_shutdown,
)
