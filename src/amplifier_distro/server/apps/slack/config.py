"""Configuration for the Slack bridge.

Follows Opinion #11: secrets in keys.yaml, config in distro.yaml.

Priority order (highest wins):
1. Environment variables (SLACK_BOT_TOKEN, etc.)
2. keys.yaml for secrets, distro.yaml for config
3. Dataclass defaults
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


def _load_distro_slack() -> dict[str, Any]:
    """Load the slack: section from ~/.amplifier/distro.yaml."""
    path = _amplifier_home() / "distro.yaml"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
        if isinstance(data, dict) and isinstance(data.get("slack"), dict):
            return data["slack"]
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


@dataclass
class SlackConfig:
    """Slack bridge configuration."""

    # --- Slack API Credentials (from keys.yaml) ---
    bot_token: str = ""  # xoxb-... (Bot User OAuth Token)
    app_token: str = ""  # xapp-... (for Socket Mode)
    signing_secret: str = ""  # For Events API verification

    # --- Channel Configuration (from distro.yaml) ---
    hub_channel_id: str = ""
    hub_channel_name: str = "amplifier"

    # --- Behavior (from distro.yaml) ---
    thread_per_session: bool = True
    allow_breakout: bool = True
    channel_prefix: str = "amp-"
    bot_name: str = "slackbridge"

    # --- Session Defaults ---
    default_bundle: str | None = None
    default_working_dir: str = "~"

    # --- Limits ---
    max_message_length: int = 3900
    max_sessions_per_user: int = 10
    response_timeout: int = 300

    # --- Mode ---
    simulator_mode: bool = False
    socket_mode: bool = False

    @classmethod
    def from_env(cls) -> SlackConfig:
        """Load config from keys.yaml + distro.yaml + env overrides.

        Priority: env vars > keys.yaml (secrets) > distro.yaml (config)
        > dataclass defaults.
        """
        keys = _load_keys()
        cfg = _load_distro_slack()
        config = cls(
            bot_token=_str("SLACK_BOT_TOKEN", keys, cfg, "bot_token"),
            app_token=_str("SLACK_APP_TOKEN", keys, cfg, "app_token"),
            signing_secret=_str("SLACK_SIGNING_SECRET", keys, cfg, "signing_secret"),
            hub_channel_id=_str("SLACK_HUB_CHANNEL_ID", {}, cfg, "hub_channel_id"),
            hub_channel_name=_str(
                "SLACK_HUB_CHANNEL_NAME",
                {},
                cfg,
                "hub_channel_name",
                "amplifier",
            ),
            default_working_dir=_str(
                "SLACK_DEFAULT_WORKING_DIR",
                {},
                cfg,
                "default_working_dir",
                "~",
            ),
            simulator_mode=_bool("SLACK_SIMULATOR_MODE", cfg, "simulator_mode"),
            socket_mode=_bool("SLACK_SOCKET_MODE", cfg, "socket_mode"),
        )
        logger.debug(
            "SlackConfig.from_env: default_working_dir=%s",
            config.default_working_dir,
        )
        return config

    @property
    def is_configured(self) -> bool:
        """Whether the Slack credentials are configured."""
        if self.socket_mode:
            return bool(self.bot_token and self.app_token)
        return bool(self.bot_token and self.signing_secret)

    @property
    def mode(self) -> str:
        """Current operating mode."""
        if self.simulator_mode:
            return "simulator"
        if self.socket_mode and self.bot_token and self.app_token:
            return "socket"
        if self.is_configured:
            return "events-api"
        return "unconfigured"
