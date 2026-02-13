"""Setup routes for guided email bridge configuration."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/setup/status")
async def setup_status() -> dict[str, Any]:
    """Get email bridge configuration status."""
    from . import _state

    config = _state.get("config")
    if config is None:
        return {
            "configured": False,
            "mode": "uninitialized",
            "agent_address": "",
        }

    return {
        "configured": config.is_configured,
        "mode": config.mode,
        "agent_address": config.agent_address,
        "agent_name": config.agent_name,
        "poll_interval": config.poll_interval_seconds,
    }


@router.post("/setup/configure")
async def setup_configure(request: dict[str, Any]) -> dict[str, Any]:
    """Accept configuration values for the email bridge."""
    from . import _state

    config = _state.get("config")
    if config is None:
        return {"error": "Bridge not initialized"}

    # Update config fields from request
    if "agent_address" in request:
        config.agent_address = request["agent_address"]
    if "agent_name" in request:
        config.agent_name = request["agent_name"]
    if "gmail_client_id" in request:
        config.gmail_client_id = request["gmail_client_id"]
    if "gmail_client_secret" in request:
        config.gmail_client_secret = request["gmail_client_secret"]
    if "gmail_refresh_token" in request:
        config.gmail_refresh_token = request["gmail_refresh_token"]
    if "poll_interval_seconds" in request:
        config.poll_interval_seconds = request["poll_interval_seconds"]

    return {
        "status": "updated",
        "configured": config.is_configured,
        "mode": config.mode,
    }


@router.post("/setup/test")
async def setup_test() -> dict[str, Any]:
    """Send a test email to verify configuration."""
    from . import _state

    client = _state.get("client")
    config = _state.get("config")
    if client is None or config is None:
        return {"error": "Bridge not initialized"}

    from .models import EmailAddress

    try:
        msg_id = await client.send_email(
            to=EmailAddress(address=config.agent_address),
            subject="Email Bridge Test",
            body_html="<p>This is a test email from the Amplifier email bridge.</p>",
            body_text="This is a test email from the Amplifier email bridge.",
        )
        return {"status": "sent", "message_id": msg_id}
    except Exception as e:
        logger.exception("Test email failed")
        return {"status": "error", "error": str(e)}
