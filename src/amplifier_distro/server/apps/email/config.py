"""Configuration for the email bridge.

Follows Opinion #11: secrets in keys.yaml, config in distro.yaml.

Priority order (highest wins):
1. Environment variables (GMAIL_CLIENT_ID, etc.)
2. keys.yaml for secrets, distro.yaml for config
3. Dataclass defaults
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from amplifier_distro.conventions import AMPLIFIER_HOME, KEYS_FILENAME

logger = logging.getLogger(__name__)


def _amplifier_home() -> Path:
    return Path(AMPLIFIER_HOME).expanduser()


def _load_keys() -> dict[str, Any]:
    """Load ~/.amplifier/keys.yaml if it exists."""
    path = _amplifier_home() / KEYS_FILENAME
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        logger.warning("Failed to read keys.yaml", exc_info=True)
        return {}


def _load_distro_email() -> dict[str, Any]:
    """Load the email: section from ~/.amplifier/distro.yaml."""
    path = _amplifier_home() / "distro.yaml"
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


def _str(
    env_key: str,
    keys: dict[str, Any],
    config: dict[str, Any],
    config_key: str,
    default: str = "",
) -> str:
    """Get string: env > keys.yaml > distro.yaml > default."""
    env = os.environ.get(env_key, "")
    if env:
        return env
    k = keys.get(env_key, "")
    if k:
        return str(k)
    c = config.get(config_key, "")
    if c:
        return str(c)
    return default


def _list_str(config: dict[str, Any], config_key: str) -> list[str]:
    """Get list of strings from distro.yaml config."""
    val = config.get(config_key)
    if isinstance(val, list):
        return [str(v) for v in val if v]
    return []


def _int(
    env_key: str,
    config: dict[str, Any],
    config_key: str,
    default: int = 0,
) -> int:
    """Get int: env > distro.yaml > default."""
    env = os.environ.get(env_key, "")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    val = config.get(config_key)
    if val is not None:
        try:
            return int(val)
        except (ValueError, TypeError):
            pass
    return default


@dataclass
class EmailConfig:
    """Email bridge configuration."""

    # --- Gmail API Credentials (from keys.yaml) ---
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""

    # --- Email Identity (from distro.yaml) ---
    agent_address: str = ""  # e.g., agent@schillace.com
    agent_name: str = "Amplifier"
    send_as: str = ""  # Send-as address (defaults to agent_address)

    # --- Behavior (from distro.yaml) ---
    poll_interval_seconds: int = 30
    max_message_length: int = 50000
    max_sessions_per_user: int = 10
    response_timeout: int = 300

    # --- Session Defaults ---
    default_bundle: str | None = None
    default_working_dir: str = "~"

    # --- Security ---
    allowed_senders: list[str] = field(default_factory=list)

    # --- Mode ---
    simulator_mode: bool = False

    @classmethod
    def from_env(cls) -> EmailConfig:
        """Load config from keys.yaml + distro.yaml + env overrides.

        Priority: env vars > keys.yaml (secrets) > distro.yaml (config)
        > dataclass defaults.
        """
        keys = _load_keys()
        cfg = _load_distro_email()
        return cls(
            gmail_client_id=_str("GMAIL_CLIENT_ID", keys, cfg, "gmail_client_id"),
            gmail_client_secret=_str(
                "GMAIL_CLIENT_SECRET", keys, cfg, "gmail_client_secret"
            ),
            gmail_refresh_token=_str(
                "GMAIL_REFRESH_TOKEN", keys, cfg, "gmail_refresh_token"
            ),
            agent_address=_str("EMAIL_AGENT_ADDRESS", {}, cfg, "agent_address"),
            agent_name=_str("EMAIL_AGENT_NAME", {}, cfg, "agent_name", "Amplifier"),
            send_as=_str("EMAIL_SEND_AS", {}, cfg, "send_as"),
            poll_interval_seconds=_int(
                "EMAIL_POLL_INTERVAL", cfg, "poll_interval_seconds", 30
            ),
            max_message_length=_int(
                "EMAIL_MAX_MESSAGE_LENGTH", cfg, "max_message_length", 50000
            ),
            max_sessions_per_user=_int(
                "EMAIL_MAX_SESSIONS_PER_USER", cfg, "max_sessions_per_user", 10
            ),
            response_timeout=_int(
                "EMAIL_RESPONSE_TIMEOUT", cfg, "response_timeout", 300
            ),
            allowed_senders=_list_str(cfg, "allowed_senders"),
        )

    @property
    def effective_send_as(self) -> str:
        """The address to send email from (send_as or agent_address)."""
        return self.send_as or self.agent_address

    @property
    def is_configured(self) -> bool:
        """Whether the Gmail credentials are configured."""
        return bool(
            self.gmail_client_id
            and self.gmail_client_secret
            and self.gmail_refresh_token
            and self.agent_address
        )

    @property
    def mode(self) -> str:
        """Current operating mode."""
        if self.simulator_mode:
            return "simulator"
        if self.is_configured:
            return "gmail-api"
        return "unconfigured"
