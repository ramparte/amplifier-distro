"""Slack Bridge Setup Module - guided installation and configuration.

Provides API routes for:
- Checking setup status (what's configured, what's missing)
- Validating tokens against the Slack API
- Discovering channels for hub selection
- Persisting configuration to ~/.amplifier/slack.yaml
- Returning the Slack App Manifest for one-click app creation
- End-to-end connectivity test

The setup flow:
1. User creates Slack app (using manifest or manually)
2. POST /setup/validate with bot_token + app_token
3. GET /setup/channels to pick the hub channel
4. POST /setup/configure to persist everything
5. POST /setup/test to verify end-to-end
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from amplifier_distro.conventions import AMPLIFIER_HOME

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["slack-setup"])

SLACK_CONFIG_FILENAME = "slack.yaml"

# --- The Slack App Manifest (for one-click app creation) ---

SLACK_APP_MANIFEST = {
    "display_information": {
        "name": "Amplifier Bridge",
        "description": "Connects Slack to Amplifier AI sessions",
        "background_color": "#1a1a2e",
    },
    "features": {
        "bot_user": {
            "display_name": "amplifier",
            "always_online": True,
        },
    },
    "oauth_config": {
        "scopes": {
            "bot": [
                "app_mentions:read",
                "channels:history",
                "channels:read",
                "chat:write",
                "reactions:write",
                "channels:manage",
                "channels:join",
            ],
        },
    },
    "settings": {
        "event_subscriptions": {
            "bot_events": [
                "app_mention",
                "message.channels",
            ],
        },
        "interactivity": {
            "is_enabled": False,
        },
        "org_deploy_enabled": False,
        "socket_mode_enabled": True,
    },
}


# --- Pydantic Models ---


class ValidateRequest(BaseModel):
    bot_token: str
    app_token: str = ""


class ConfigureRequest(BaseModel):
    bot_token: str
    app_token: str = ""
    signing_secret: str = ""
    hub_channel_id: str = ""
    hub_channel_name: str = "amplifier"
    socket_mode: bool = True


class TestRequest(BaseModel):
    channel_id: str = ""


# --- Config file helpers ---


def _config_path() -> Path:
    return Path(AMPLIFIER_HOME).expanduser() / SLACK_CONFIG_FILENAME


def load_slack_config() -> dict[str, Any]:
    """Load Slack config from ~/.amplifier/slack.yaml."""
    path = _config_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("Failed to read slack.yaml", exc_info=True)
        return {}


def save_slack_config(config: dict[str, Any]) -> Path:
    """Save Slack config to ~/.amplifier/slack.yaml (chmod 600)."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    path.chmod(0o600)
    return path


# --- Slack API helpers ---


async def _slack_api(method: str, token: str, **kwargs: Any) -> dict[str, Any]:
    """Call a Slack Web API method and return the response."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://slack.com/api/{method}",
            headers={"Authorization": f"Bearer {token}"},
            json=kwargs if kwargs else None,
            timeout=15.0,
        )
        data = resp.json()
        return data


async def _validate_bot_token(token: str) -> dict[str, Any]:
    """Validate a bot token via auth.test."""
    data = await _slack_api("auth.test", token)
    if not data.get("ok"):
        return {"valid": False, "error": data.get("error", "unknown")}
    return {
        "valid": True,
        "team": data.get("team"),
        "team_id": data.get("team_id"),
        "user": data.get("user"),
        "user_id": data.get("user_id"),
        "bot_id": data.get("bot_id"),
    }


async def _validate_app_token(token: str) -> dict[str, Any]:
    """Validate an app token via apps.connections.open (dry run)."""
    data = await _slack_api("apps.connections.open", token)
    if not data.get("ok"):
        return {"valid": False, "error": data.get("error", "unknown")}
    # We got a WebSocket URL, meaning the token works. We don't connect.
    return {"valid": True}


async def _list_channels(token: str, *, limit: int = 200) -> list[dict[str, Any]]:
    """List public channels the bot can see."""
    data = await _slack_api(
        "conversations.list",
        token,
        types="public_channel",
        limit=limit,
        exclude_archived=True,
    )
    if not data.get("ok"):
        return []
    channels = data.get("channels", [])
    return [
        {
            "id": ch["id"],
            "name": ch.get("name", ""),
            "is_member": ch.get("is_member", False),
            "num_members": ch.get("num_members", 0),
            "topic": ch.get("topic", {}).get("value", ""),
        }
        for ch in channels
    ]


# --- Routes ---


@router.get("/status")
async def setup_status() -> dict[str, Any]:
    """Check what's configured and what's missing.

    Returns a checklist of setup steps with pass/fail status.
    """
    config = load_slack_config()
    env_bot = os.environ.get("SLACK_BOT_TOKEN", "")
    env_app = os.environ.get("SLACK_APP_TOKEN", "")

    bot_token = config.get("bot_token", "") or env_bot
    app_token = config.get("app_token", "") or env_app
    hub_channel_id = config.get("hub_channel_id", "") or os.environ.get(
        "SLACK_HUB_CHANNEL_ID", ""
    )
    socket_mode = config.get("socket_mode", False) or os.environ.get(
        "SLACK_SOCKET_MODE", ""
    ).lower() in ("1", "true", "yes")

    steps = {
        "bot_token": bool(bot_token),
        "app_token": bool(app_token),
        "hub_channel": bool(hub_channel_id),
        "socket_mode": socket_mode,
        "config_persisted": _config_path().exists(),
    }
    all_required = steps["bot_token"] and steps["hub_channel"]
    if socket_mode:
        all_required = all_required and steps["app_token"]

    return {
        "configured": all_required,
        "steps": steps,
        "config_path": str(_config_path()),
        "mode": "socket"
        if socket_mode and app_token
        else "events-api"
        if bot_token
        else "unconfigured",
    }


@router.post("/validate")
async def validate_tokens(req: ValidateRequest) -> dict[str, Any]:
    """Validate Slack tokens against the API.

    Tests bot token via auth.test and app token via apps.connections.open.
    Returns detailed info about what the tokens can do.
    """
    if not req.bot_token.startswith("xoxb-"):
        raise HTTPException(
            status_code=400,
            detail="Bot token must start with 'xoxb-'. "
            "Find it at: OAuth & Permissions > Bot User OAuth Token",
        )

    result: dict[str, Any] = {}

    # Validate bot token
    result["bot_token"] = await _validate_bot_token(req.bot_token)

    # Validate app token if provided
    if req.app_token:
        if not req.app_token.startswith("xapp-"):
            raise HTTPException(
                status_code=400,
                detail="App token must start with 'xapp-'. "
                "Find it at: Basic Information > App-Level Tokens, "
                "or enable Socket Mode to generate one.",
            )
        result["app_token"] = await _validate_app_token(req.app_token)
    else:
        result["app_token"] = {"valid": False, "error": "not_provided"}

    result["all_valid"] = result["bot_token"]["valid"] and (
        not req.app_token or result["app_token"]["valid"]
    )

    return result


@router.get("/channels")
async def list_channels(bot_token: str = "") -> dict[str, Any]:
    """List channels visible to the bot for hub channel selection.

    Pass bot_token as query param, or it will read from saved config / env.
    """
    token = (
        bot_token
        or load_slack_config().get("bot_token", "")
        or os.environ.get("SLACK_BOT_TOKEN", "")
    )
    if not token:
        raise HTTPException(
            status_code=400,
            detail="No bot token available. Validate tokens first.",
        )

    channels = await _list_channels(token)
    # Sort: channels the bot is a member of first, then by name
    channels.sort(key=lambda c: (not c["is_member"], c["name"]))

    return {
        "channels": channels,
        "count": len(channels),
        "tip": "Choose a channel for the Amplifier hub. "
        "The bot must be invited to it (/invite @amplifier).",
    }


@router.post("/configure")
async def configure(req: ConfigureRequest) -> dict[str, Any]:
    """Save Slack configuration to ~/.amplifier/slack.yaml.

    Also sets environment variables for the current process so the
    bridge can pick them up without restart.
    """
    # Build config dict (only include non-empty values)
    config: dict[str, Any] = {}
    if req.bot_token:
        config["bot_token"] = req.bot_token
    if req.app_token:
        config["app_token"] = req.app_token
    if req.signing_secret:
        config["signing_secret"] = req.signing_secret
    if req.hub_channel_id:
        config["hub_channel_id"] = req.hub_channel_id
    config["hub_channel_name"] = req.hub_channel_name
    config["socket_mode"] = req.socket_mode

    # Persist to disk
    path = save_slack_config(config)

    # Set env vars for current process (bridge reads from env)
    env_map = {
        "SLACK_BOT_TOKEN": req.bot_token,
        "SLACK_APP_TOKEN": req.app_token,
        "SLACK_SIGNING_SECRET": req.signing_secret,
        "SLACK_HUB_CHANNEL_ID": req.hub_channel_id,
        "SLACK_HUB_CHANNEL_NAME": req.hub_channel_name,
        "SLACK_SOCKET_MODE": "true" if req.socket_mode else "false",
    }
    for key, value in env_map.items():
        if value:
            os.environ[key] = value

    return {
        "status": "saved",
        "config_path": str(path),
        "mode": "socket" if req.socket_mode else "events-api",
    }


@router.post("/test")
async def test_connection(req: TestRequest) -> dict[str, Any]:
    """Send a test message to verify end-to-end connectivity.

    Posts a message to the hub channel (or specified channel) and
    confirms it was delivered.
    """
    config = load_slack_config()
    token = config.get("bot_token", "") or os.environ.get("SLACK_BOT_TOKEN", "")
    channel = (
        req.channel_id
        or config.get("hub_channel_id", "")
        or os.environ.get("SLACK_HUB_CHANNEL_ID", "")
    )

    if not token:
        raise HTTPException(status_code=400, detail="No bot token configured")
    if not channel:
        raise HTTPException(status_code=400, detail="No channel specified")

    # Post a test message
    data = await _slack_api(
        "chat.postMessage",
        token,
        channel=channel,
        text="Amplifier Bridge connected. Setup complete.",
    )

    if not data.get("ok"):
        error = data.get("error", "unknown")
        hints: dict[str, str] = {
            "channel_not_found": "Channel ID is wrong or bot isn't in the channel. "
            "Try: /invite @amplifier in the channel.",
            "not_in_channel": "Bot needs to be invited: /invite @amplifier",
            "invalid_auth": "Bot token is invalid or expired.",
            "missing_scope": "Bot token is missing 'chat:write' scope. "
            "Add it in OAuth & Permissions, then reinstall the app.",
        }
        return {
            "success": False,
            "error": error,
            "hint": hints.get(error, f"Slack API error: {error}"),
        }

    return {
        "success": True,
        "channel": channel,
        "message_ts": data.get("ts"),
        "message": "Test message sent. Check the channel in Slack.",
    }


@router.get("/manifest")
async def get_manifest() -> dict[str, Any]:
    """Return the Slack App Manifest for one-click app creation.

    Users can paste this YAML into https://api.slack.com/apps > Create New App
    > From a manifest, to get all scopes and events pre-configured.
    """
    manifest_yaml = yaml.dump(
        SLACK_APP_MANIFEST, default_flow_style=False, sort_keys=False
    )
    return {
        "manifest": SLACK_APP_MANIFEST,
        "manifest_yaml": manifest_yaml,
        "instructions": (
            "1. Go to https://api.slack.com/apps\n"
            "2. Click 'Create New App' > 'From a manifest'\n"
            "3. Select your workspace\n"
            "4. Choose YAML format and paste the manifest\n"
            "5. Click 'Create'\n"
            "6. Go to 'Install App' and install to your workspace\n"
            "7. Copy the Bot Token (xoxb-...) from OAuth & Permissions\n"
            "8. Copy the App Token (xapp-...) from Basic Information\n"
            "   > App-Level Tokens (create one with 'connections:write')\n"
            "9. Use /setup/configure to save both tokens"
        ),
        "create_url": ("https://api.slack.com/apps?new_app=1"),
    }
