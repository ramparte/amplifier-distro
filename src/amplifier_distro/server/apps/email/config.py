"""Configuration for the email bridge.

Follows Opinion #11: secrets in keys file, config in distro.yaml.

Priority order (highest wins):
1. Environment variables (EMAIL_*, GMAIL_*)
2. keys.env or keys.yaml for secrets
3. distro.yaml email: section for config
4. Dataclass defaults
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from amplifier_distro.conventions import AMPLIFIER_HOME, KEYS_FILENAME

logger = logging.getLogger(__name__)


def _amplifier_home() -> Path:
    return Path(AMPLIFIER_HOME).expanduser()


def _load_keys_env(path: Path) -> dict[str, Any]:
    """Parse a .env file into a dict.

    Handles both dotenv (KEY=VALUE) and YAML-ish (KEY: VALUE) formats
    since users may mix styles in their keys file.
    """
    result: dict[str, Any] = {}
    if not path.exists():
        return result
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Try = first (dotenv), then : (YAML-ish)
            if "=" in line:
                key, _, value = line.partition("=")
            elif ": " in line:
                key, _, value = line.partition(": ")
            else:
                continue
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            result[key] = value
    except OSError:
        logger.warning("Failed to read %s", path, exc_info=True)
    return result


def _load_keys() -> dict[str, Any]:
    """Load keys from ~/.amplifier/keys.env (dotenv) or keys.yaml."""
    home = _amplifier_home()

    # Try keys.env first (dotenv format)
    env_path = home / "keys.env"
    if env_path.exists():
        return _load_keys_env(env_path)

    # Fall back to keys.yaml
    yaml_path = home / KEYS_FILENAME
    if not yaml_path.exists():
        return {}
    try:
        data = yaml.safe_load(yaml_path.read_text())
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
        logger.warning("Failed to read distro.yaml", exc_info=True)
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


def _bool(
    env_key: str,
    config: dict[str, Any],
    config_key: str,
    default: bool = False,
) -> bool:
    """Get bool: env > distro.yaml > default."""
    env = os.environ.get(env_key, "")
    if env:
        return env.lower() in ("1", "true", "yes")
    val = config.get(config_key)
    if val is not None:
        return bool(val)
    return default


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
    gmail_access_token: str = ""  # Auto-refreshed, can be empty

    # --- Email Settings (from distro.yaml) ---
    agent_address: str = ""  # e.g., agent@schillace.com
    send_as: str = ""  # Send-As alias (if different from Gmail account)
    agent_name: str = "Amplifier"  # Display name in From header

    # --- Behavior ---
    poll_interval_seconds: int = 30
    max_message_length: int = 50000  # Email can be long
    max_sessions_per_sender: int = 10
    response_timeout: int = 600  # 10 minutes for email

    # --- Session Defaults ---
    default_bundle: str | None = None
    default_working_dir: str = "~"

    # --- Mode ---
    simulator_mode: bool = False

    @classmethod
    def from_env(cls) -> EmailConfig:
        """Load from keys.yaml + distro.yaml + env."""
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
            gmail_access_token=_str(
                "GMAIL_ACCESS_TOKEN", keys, cfg, "gmail_access_token"
            ),
            agent_address=_str("EMAIL_AGENT_ADDRESS", {}, cfg, "agent_address"),
            send_as=_str("EMAIL_SEND_AS", {}, cfg, "send_as"),
            agent_name=_str("EMAIL_AGENT_NAME", {}, cfg, "agent_name", "Amplifier"),
            poll_interval_seconds=_int(
                "EMAIL_POLL_INTERVAL", cfg, "poll_interval_seconds", 30
            ),
            simulator_mode=_bool("EMAIL_SIMULATOR_MODE", cfg, "simulator_mode"),
        )

    @property
    def is_configured(self) -> bool:
        return bool(
            self.gmail_client_id
            and self.gmail_client_secret
            and self.gmail_refresh_token
        )

    @property
    def mode(self) -> str:
        if self.simulator_mode:
            return "simulator"
        if self.is_configured:
            return "gmail-api"
        return "unconfigured"
