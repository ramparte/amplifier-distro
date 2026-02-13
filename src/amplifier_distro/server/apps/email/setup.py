"""Email Bridge Setup Module - guided installation and configuration.

Follows Opinion #11: secrets in keys.yaml, config in distro.yaml.

Provides API routes for:
- Checking setup status (what's configured, what's missing)
- Persisting Gmail OAuth secrets to ~/.amplifier/keys.yaml (chmod 600)
- Persisting email config to ~/.amplifier/distro.yaml (email: section)
- Running the OAuth authorization flow
- End-to-end connectivity test (send/receive)

The setup flow:
1. User creates Google Cloud project + OAuth credentials
2. POST /setup/configure with client_id, client_secret, agent_address
3. GET /setup/oauth/start to begin OAuth flow (opens browser)
4. OAuth callback saves refresh_token
5. POST /setup/test to verify end-to-end
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter
from pydantic import BaseModel

from amplifier_distro.conventions import AMPLIFIER_HOME, KEYS_FILENAME

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["email-setup"])

# Gmail API scopes needed for the bridge
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


# --- Pydantic Models ---


class ConfigureRequest(BaseModel):
    gmail_client_id: str
    gmail_client_secret: str
    gmail_refresh_token: str = ""
    agent_address: str = ""
    agent_name: str = "Amplifier"
    send_as: str = ""
    poll_interval_seconds: int = 30


class TestSendRequest(BaseModel):
    to_address: str = ""


# --- Persistence helpers (Opinion #11 pattern) ---


def _amplifier_home() -> Path:
    return Path(AMPLIFIER_HOME).expanduser()


def _keys_path() -> Path:
    return _amplifier_home() / KEYS_FILENAME


def _distro_config_path() -> Path:
    return _amplifier_home() / "distro.yaml"


def _load_keys() -> dict[str, Any]:
    """Load ~/.amplifier/keys.yaml."""
    path = _keys_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
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


def _load_distro_email() -> dict[str, Any]:
    """Load the email: section from distro.yaml."""
    path = _distro_config_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
        if isinstance(data, dict) and isinstance(data.get("email"), dict):
            return data["email"]
        return {}
    except (OSError, yaml.YAMLError):
        logger.warning("Failed to read distro.yaml email section", exc_info=True)
        return {}


def _save_distro_email(email_config: dict[str, Any]) -> None:
    """Merge email config into distro.yaml (preserves other sections)."""
    path = _distro_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if path.exists():
        existing = yaml.safe_load(path.read_text()) or {}

    existing["email"] = email_config
    path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False))


# --- Routes ---


@router.get("/status")
async def setup_status() -> dict[str, Any]:
    """Check what's configured and what's missing."""
    keys = _load_keys()
    cfg = _load_distro_email()

    client_id = os.environ.get("GMAIL_CLIENT_ID", "") or keys.get("GMAIL_CLIENT_ID", "")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "") or keys.get(
        "GMAIL_CLIENT_SECRET", ""
    )
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "") or keys.get(
        "GMAIL_REFRESH_TOKEN", ""
    )
    agent_address = os.environ.get("EMAIL_AGENT_ADDRESS", "") or cfg.get(
        "agent_address", ""
    )

    steps = {
        "gmail_client_id": bool(client_id),
        "gmail_client_secret": bool(client_secret),
        "gmail_refresh_token": bool(refresh_token),
        "agent_address": bool(agent_address),
        "keys_persisted": bool(keys.get("GMAIL_CLIENT_ID")),
        "config_persisted": bool(cfg.get("agent_address")),
    }
    all_required = all(
        steps[k]
        for k in [
            "gmail_client_id",
            "gmail_client_secret",
            "gmail_refresh_token",
            "agent_address",
        ]
    )

    return {
        "configured": all_required,
        "steps": steps,
        "keys_path": str(_keys_path()),
        "config_path": str(_distro_config_path()),
        "agent_address": agent_address,
        "mode": "gmail-api" if all_required else "unconfigured",
    }


@router.post("/configure")
async def configure(req: ConfigureRequest) -> dict[str, Any]:
    """Save Gmail secrets to keys.yaml and config to distro.yaml.

    Follows Opinion #11: secrets and config in standard locations.
    Also sets environment variables for the current process.
    """
    # 1. Persist secrets to keys.yaml
    _save_keys(
        {
            "GMAIL_CLIENT_ID": req.gmail_client_id,
            "GMAIL_CLIENT_SECRET": req.gmail_client_secret,
            "GMAIL_REFRESH_TOKEN": req.gmail_refresh_token,
        }
    )

    # 2. Persist config to distro.yaml email: section
    email_cfg: dict[str, Any] = {
        "agent_address": req.agent_address,
        "agent_name": req.agent_name,
        "poll_interval_seconds": req.poll_interval_seconds,
    }
    if req.send_as:
        email_cfg["send_as"] = req.send_as
    _save_distro_email(email_cfg)

    # 3. Set env vars for current process
    env_map = {
        "GMAIL_CLIENT_ID": req.gmail_client_id,
        "GMAIL_CLIENT_SECRET": req.gmail_client_secret,
        "GMAIL_REFRESH_TOKEN": req.gmail_refresh_token,
        "EMAIL_AGENT_ADDRESS": req.agent_address,
        "EMAIL_AGENT_NAME": req.agent_name,
    }
    for key, value in env_map.items():
        if value:
            os.environ[key] = value

    return {
        "status": "saved",
        "keys_path": str(_keys_path()),
        "config_path": str(_distro_config_path()),
        "configured": bool(
            req.gmail_client_id
            and req.gmail_client_secret
            and req.gmail_refresh_token
            and req.agent_address
        ),
    }


@router.get("/oauth/start")
async def oauth_start() -> dict[str, Any]:
    """Return the OAuth authorization URL for Gmail API.

    The user opens this URL in their browser, authorizes the app,
    and gets back an authorization code to exchange for tokens.
    """
    keys = _load_keys()
    client_id = os.environ.get("GMAIL_CLIENT_ID", "") or keys.get("GMAIL_CLIENT_ID", "")

    if not client_id:
        return {
            "error": "No GMAIL_CLIENT_ID configured. "
            "Run /setup/configure with client_id first."
        }

    scope = " ".join(GMAIL_SCOPES)
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={client_id}"
        "&redirect_uri=urn:ietf:wg:oauth:2.0:oob"
        f"&scope={scope}"
        "&response_type=code"
        "&access_type=offline"
        "&prompt=consent"
    )

    return {
        "auth_url": auth_url,
        "instructions": (
            "1. Open the auth_url in your browser\n"
            "2. Sign in with the Gmail account for the agent\n"
            "3. Grant the requested permissions\n"
            "4. Copy the authorization code shown on screen\n"
            "5. POST /setup/oauth/exchange with the code"
        ),
    }


@router.post("/oauth/exchange")
async def oauth_exchange(request: dict[str, Any]) -> dict[str, Any]:
    """Exchange an authorization code for OAuth tokens.

    Saves the refresh_token to keys.yaml automatically.
    """
    import httpx

    code = request.get("code", "")
    if not code:
        return {"error": "Missing 'code' field"}

    keys = _load_keys()
    client_id = os.environ.get("GMAIL_CLIENT_ID", "") or keys.get("GMAIL_CLIENT_ID", "")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "") or keys.get(
        "GMAIL_CLIENT_SECRET", ""
    )

    if not client_id or not client_secret:
        return {"error": "Client ID and secret must be configured first"}

    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
                "grant_type": "authorization_code",
            },
            timeout=15.0,
        )
        data = resp.json()

    if "error" in data:
        return {
            "status": "error",
            "error": data.get("error"),
            "error_description": data.get("error_description", ""),
        }

    refresh_token = data.get("refresh_token", "")
    if not refresh_token:
        return {
            "status": "error",
            "error": "No refresh_token in response. "
            "Try again with prompt=consent to force a new refresh token.",
        }

    # Save refresh token to keys.yaml
    _save_keys({"GMAIL_REFRESH_TOKEN": refresh_token})
    os.environ["GMAIL_REFRESH_TOKEN"] = refresh_token

    return {
        "status": "authorized",
        "refresh_token_saved": True,
        "keys_path": str(_keys_path()),
        "message": "OAuth tokens saved. The bridge is now authorized.",
    }


@router.post("/test")
async def test_connection(req: TestSendRequest | None = None) -> dict[str, Any]:
    """Send a test email to verify end-to-end configuration."""
    from . import _get_state

    try:
        state = _get_state()
    except RuntimeError:
        return {"error": "Bridge not initialized. Start the server first."}

    client = state.get("client")
    config = state.get("config")
    if client is None or config is None:
        return {"error": "Bridge not initialized"}

    if not config.is_configured:
        return {
            "error": "Bridge not fully configured",
            "mode": config.mode,
            "hint": "Run /setup/status to see what's missing",
        }

    from .models import EmailAddress

    to_addr = (req.to_address if req else "") or config.agent_address
    try:
        msg_id = await client.send_email(
            to=EmailAddress(address=to_addr),
            subject="Amplifier Email Bridge Test",
            body_html=(
                "<p>This is a test email from the Amplifier email bridge.</p>"
                "<p>If you received this, the bridge is working correctly.</p>"
            ),
            body_text=(
                "This is a test email from the Amplifier email bridge.\n"
                "If you received this, the bridge is working correctly."
            ),
        )
        return {
            "success": True,
            "message_id": msg_id,
            "sent_to": to_addr,
            "message": f"Test email sent to {to_addr}. Check inbox.",
        }
    except Exception as e:
        logger.exception("Test email failed")
        return {
            "success": False,
            "error": str(e),
            "hint": "Check OAuth credentials and Gmail API access.",
        }


@router.get("/instructions")
async def setup_instructions() -> dict[str, Any]:
    """Return step-by-step setup instructions."""
    return {
        "title": "Email Bridge Setup Guide",
        "steps": [
            {
                "step": 1,
                "title": "Create Google Cloud Project",
                "instructions": (
                    "1. Go to https://console.cloud.google.com\n"
                    "2. Create a new project: 'Amplifier Email Bridge'\n"
                    "3. Enable the Gmail API:\n"
                    "   - APIs & Services > Library\n"
                    "   - Search 'Gmail API' > Enable"
                ),
            },
            {
                "step": 2,
                "title": "Create OAuth Credentials",
                "instructions": (
                    "1. APIs & Services > Credentials\n"
                    "2. Create Credentials > OAuth client ID\n"
                    "3. Application type: 'Desktop app'\n"
                    "4. Name: 'Amplifier Local Client'\n"
                    "5. Note the Client ID and Client Secret"
                ),
            },
            {
                "step": 3,
                "title": "Configure OAuth Consent Screen",
                "instructions": (
                    "1. OAuth consent screen > User Type: External\n"
                    "2. App name: 'Amplifier'\n"
                    "3. Add scopes:\n"
                    "   - gmail.readonly\n"
                    "   - gmail.send\n"
                    "   - gmail.modify\n"
                    "4. Add test user: your agent Gmail address\n"
                    "5. Publish the app (or keep in testing mode)"
                ),
            },
            {
                "step": 4,
                "title": "Save Credentials",
                "instructions": (
                    "POST /apps/email/setup/configure with:\n"
                    "{\n"
                    '  "gmail_client_id": "your-client-id",\n'
                    '  "gmail_client_secret": "your-client-secret",\n'
                    '  "agent_address": "agent@yourdomain.com"\n'
                    "}"
                ),
            },
            {
                "step": 5,
                "title": "Authorize Gmail Access",
                "instructions": (
                    "1. GET /apps/email/setup/oauth/start\n"
                    "2. Open the auth_url in your browser\n"
                    "3. Sign in and authorize\n"
                    "4. Copy the code\n"
                    "5. POST /apps/email/setup/oauth/exchange "
                    'with {"code": "your-code"}'
                ),
            },
            {
                "step": 6,
                "title": "Test",
                "instructions": (
                    "POST /apps/email/setup/test\nCheck your inbox for the test email."
                ),
            },
        ],
        "quick_start": (
            "If you already have credentials:\n"
            "POST /apps/email/setup/configure with all three "
            "(client_id, client_secret, refresh_token) + agent_address\n"
            "Then POST /apps/email/setup/test to verify."
        ),
    }
