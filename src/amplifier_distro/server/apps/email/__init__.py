"""Email Bridge App - connects email to Amplifier sessions.

This is the app plugin entry point for the distro server. It registers
FastAPI routes for:
- Bridge status and session listing
- Manual poll trigger
- Incoming email webhook
- Setup and configuration

Architecture:
    Email -> POST /apps/email/incoming -> EmailEventHandler
        -> CommandHandler (for /amp commands)
        -> EmailSessionManager -> SessionBackend -> Amplifier
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from amplifier_distro.server.app import AppManifest
from amplifier_distro.server.session_backend import MockBackend

from .client import EmailClient, MemoryEmailClient
from .commands import CommandHandler
from .config import EmailConfig
from .events import EmailEventHandler
from .models import EmailAddress, EmailMessage
from .poller import EmailPoller
from .sessions import EmailSessionManager
from .setup import router as setup_router

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Global bridge state (initialized on startup) ---

_state: dict[str, Any] = {}


def initialize(
    config: EmailConfig | None = None,
    client: EmailClient | None = None,
    backend: Any | None = None,
) -> dict[str, Any]:
    """Initialize the email bridge components.

    Separated from on_startup() for testability with injected dependencies.
    """
    global _state

    if config is None:
        config = EmailConfig.from_env()

    # Select client implementation
    if client is None:
        if config.simulator_mode or not config.is_configured:
            logger.info("Email bridge starting in simulator mode")
            client = MemoryEmailClient(agent_address=config.agent_address)
            config.simulator_mode = True
        else:
            from .client import GmailClient

            client = GmailClient(config)

    # Select backend
    if backend is None:
        try:
            from amplifier_distro.server.services import get_services

            backend = get_services().backend
            logger.info("Email bridge using shared server backend")
        except RuntimeError:
            backend = MockBackend()
            logger.info("Email bridge using mock backend (standalone mode)")

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
    _state.update(state)

    return state


async def on_startup() -> None:
    """Initialize the email bridge on server startup."""
    initialize()
    config: EmailConfig = _state["config"]
    logger.info("Email bridge initialized (mode: %s)", config.mode)

    # Start poller if configured
    if config.is_configured and not config.simulator_mode:
        poller: EmailPoller = _state["poller"]
        poller.start()
        logger.info(
            "Email poller started (interval: %ds)", config.poll_interval_seconds
        )


async def on_shutdown() -> None:
    """Clean up the email bridge on server shutdown."""
    poller = _state.get("poller")
    if poller is not None:
        poller.stop()

    session_manager = _state.get("session_manager")
    if session_manager is not None:
        for mapping in session_manager.list_active():
            try:
                backend = _state.get("backend")
                if backend is not None:
                    await backend.end_session(mapping.session_id)
            except (RuntimeError, ValueError, ConnectionError, OSError):
                logger.exception("Error ending session %s", mapping.session_id)

    _state.clear()
    logger.info("Email bridge shut down")


# --- Routes ---


@router.get("/status")
async def bridge_status() -> dict[str, Any]:
    """Bridge health and status."""
    config = _state.get("config")
    session_manager = _state.get("session_manager")
    poller = _state.get("poller")

    if config is None:
        return {"status": "uninitialized"}

    return {
        "status": "ok",
        "mode": config.mode,
        "agent_address": config.agent_address,
        "active_sessions": len(session_manager.list_active()) if session_manager else 0,
        "is_configured": config.is_configured,
        "poller_running": poller.is_running if poller else False,
    }


@router.get("/sessions")
async def list_sessions() -> list[dict[str, Any]]:
    """List active email session mappings."""
    session_manager = _state.get("session_manager")
    if session_manager is None:
        return []

    return [
        {
            "session_id": m.session_id,
            "thread_id": m.thread_id,
            "sender_address": m.sender_address,
            "subject": m.subject,
            "message_count": m.message_count,
            "created_at": m.created_at,
            "last_activity": m.last_activity,
        }
        for m in session_manager.list_active()
    ]


@router.post("/poll")
async def trigger_poll() -> dict[str, Any]:
    """Trigger a manual poll for new emails."""
    poller = _state.get("poller")
    if poller is None:
        return {"error": "Bridge not initialized"}

    count = await poller.poll_once()
    return {"status": "ok", "messages_processed": count}


@router.post("/incoming")
async def incoming_email(message: dict[str, Any]) -> dict[str, Any]:
    """Webhook endpoint for incoming email (test/forwarding)."""
    event_handler = _state.get("event_handler")
    if event_handler is None:
        return {"error": "Bridge not initialized"}

    # Parse the incoming message dict into an EmailMessage
    from_addr = message.get("from", {})
    to_addrs = message.get("to", [])

    email_msg = EmailMessage(
        message_id=message.get("message_id", ""),
        thread_id=message.get("thread_id", ""),
        from_addr=EmailAddress(
            address=from_addr.get("address", ""),
            display_name=from_addr.get("display_name", ""),
        ),
        to_addrs=[
            EmailAddress(
                address=a.get("address", ""),
                display_name=a.get("display_name", ""),
            )
            for a in to_addrs
        ],
        subject=message.get("subject", ""),
        body_text=message.get("body_text", ""),
        body_html=message.get("body_html", ""),
    )

    await event_handler.handle_incoming_email(email_msg)
    return {"status": "ok"}


# --- Setup Routes ---
router.include_router(setup_router)


# --- Manifest ---

manifest = AppManifest(
    name="email",
    description="Email bridge - connects email to Amplifier sessions",
    version="0.1.0",
    router=router,
    on_startup=on_startup,
    on_shutdown=on_shutdown,
)
