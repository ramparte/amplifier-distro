"""Slack Bridge Setup Module - guided installation and configuration.

Follows Opinion #11: secrets in keys.yaml, config in distro.yaml.

Provides API routes for:
- Checking setup status (what's configured, what's missing)
- Validating tokens against the Slack API
- Discovering channels for hub selection
- Persisting secrets to ~/.amplifier/keys.yaml (chmod 600)
- Persisting config to ~/.amplifier/distro.yaml (slack: section)
- Returning the Slack App Manifest for one-click app creation
- End-to-end connectivity test

The setup flow:
1. User creates Slack app (using manifest)
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

from amplifier_distro.conventions import AMPLIFIER_HOME, KEYS_FILENAME

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["slack-setup"])

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


# --- Persistence helpers (Opinion #11 pattern) ---


def _amplifier_home() -> Path:
    return Path(AMPLIFIER_HOME).expanduser()


def _keys_path() -> Path:
    return _amplifier_home() / KEYS_FILENAME


def _distro_config_path() -> Path:
    return _amplifier_home() / "distro.yaml"


def load_keys() -> dict[str, Any]:
    """Load ~/.amplifier/keys.yaml."""
    path = _keys_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("Failed to read keys.yaml", exc_info=True)
        return {}


def _save_keys(updates: dict[str, str]) -> None:
    """Merge updates into keys.yaml (chmod 600)."""
    path = _keys_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, str] = {}
    if path.exists():
        existing = yaml.safe_load(path.read_text()) or {}

    existing.update({k: v for k, v in updates.items() if v})
    path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False))
    path.chmod(0o600)


def load_distro_slack() -> dict[str, Any]:
    """Load the slack: section from distro.yaml."""
    path = _distro_config_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
        if isinstance(data, dict) and isinstance(data.get("slack"), dict):
            return data["slack"]
        return {}
    except Exception:
        logger.warning("Failed to read distro.yaml slack section", exc_info=True)
        return {}


def _save_distro_slack(slack_config: dict[str, Any]) -> None:
    """Merge slack config into distro.yaml (preserves other sections)."""
    path = _distro_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if path.exists():
        existing = yaml.safe_load(path.read_text()) or {}

    existing["slack"] = slack_config
    path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False))


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
    """Check what's configured and what's missing."""
    keys = load_keys()
    cfg = load_distro_slack()

    bot_token = os.environ.get("SLACK_BOT_TOKEN", "") or keys.get("SLACK_BOT_TOKEN", "")
    app_token = os.environ.get("SLACK_APP_TOKEN", "") or keys.get("SLACK_APP_TOKEN", "")
    hub_channel_id = os.environ.get("SLACK_HUB_CHANNEL_ID", "") or cfg.get(
        "hub_channel_id", ""
    )
    socket_mode = bool(
        os.environ.get("SLACK_SOCKET_MODE", "").lower() in ("1", "true", "yes")
        or cfg.get("socket_mode", False)
    )

    steps = {
        "bot_token": bool(bot_token),
        "app_token": bool(app_token),
        "hub_channel": bool(hub_channel_id),
        "socket_mode": socket_mode,
        "keys_persisted": bool(keys.get("SLACK_BOT_TOKEN")),
        "config_persisted": bool(cfg.get("hub_channel_id")),
    }
    all_required = steps["bot_token"] and steps["hub_channel"]
    if socket_mode:
        all_required = all_required and steps["app_token"]

    return {
        "configured": all_required,
        "steps": steps,
        "keys_path": str(_keys_path()),
        "config_path": str(_distro_config_path()),
        "mode": "socket"
        if socket_mode and app_token
        else "events-api"
        if bot_token
        else "unconfigured",
    }


@router.post("/validate")
async def validate_tokens(req: ValidateRequest) -> dict[str, Any]:
    """Validate Slack tokens against the API."""
    if not req.bot_token.startswith("xoxb-"):
        raise HTTPException(
            status_code=400,
            detail="Bot token must start with 'xoxb-'. "
            "Find it at: OAuth & Permissions > Bot User OAuth Token",
        )

    result: dict[str, Any] = {}
    result["bot_token"] = await _validate_bot_token(req.bot_token)

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
    """List channels visible to the bot for hub channel selection."""
    keys = load_keys()
    token = (
        bot_token
        or os.environ.get("SLACK_BOT_TOKEN", "")
        or keys.get("SLACK_BOT_TOKEN", "")
    )
    if not token:
        raise HTTPException(
            status_code=400,
            detail="No bot token available. Validate tokens first.",
        )

    channels = await _list_channels(token)
    channels.sort(key=lambda c: (not c["is_member"], c["name"]))

    return {
        "channels": channels,
        "count": len(channels),
        "tip": "Choose a channel for the Amplifier hub. "
        "The bot must be invited to it (/invite @amplifier).",
    }


@router.post("/configure")
async def configure(req: ConfigureRequest) -> dict[str, Any]:
    """Save Slack secrets to keys.yaml and config to distro.yaml.

    Follows Opinion #11: secrets and config in standard locations.
    Also sets environment variables for the current process.
    """
    # 1. Persist secrets to keys.yaml
    _save_keys(
        {
            "SLACK_BOT_TOKEN": req.bot_token,
            "SLACK_APP_TOKEN": req.app_token,
            "SLACK_SIGNING_SECRET": req.signing_secret,
        }
    )

    # 2. Persist config to distro.yaml slack: section
    slack_cfg: dict[str, Any] = {
        "hub_channel_name": req.hub_channel_name,
        "socket_mode": req.socket_mode,
    }
    if req.hub_channel_id:
        slack_cfg["hub_channel_id"] = req.hub_channel_id
    _save_distro_slack(slack_cfg)

    # 3. Set env vars for current process (bridge reads from env)
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
        "keys_path": str(_keys_path()),
        "config_path": str(_distro_config_path()),
        "mode": "socket" if req.socket_mode else "events-api",
    }


@router.post("/test")
async def test_connection(req: TestRequest) -> dict[str, Any]:
    """Send a test message to verify end-to-end connectivity."""
    keys = load_keys()
    cfg = load_distro_slack()

    token = os.environ.get("SLACK_BOT_TOKEN", "") or keys.get("SLACK_BOT_TOKEN", "")
    channel = (
        req.channel_id
        or os.environ.get("SLACK_HUB_CHANNEL_ID", "")
        or cfg.get("hub_channel_id", "")
    )

    if not token:
        raise HTTPException(status_code=400, detail="No bot token configured")
    if not channel:
        raise HTTPException(status_code=400, detail="No channel specified")

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
    """Return the Slack App Manifest for one-click app creation."""
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
        "create_url": "https://api.slack.com/apps?new_app=1",
    }
