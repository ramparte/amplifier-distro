"""Configuration for the Slack bridge.

Loaded from ~/.amplifier/slack.yaml (persisted config) with environment
variable overrides. The bridge can operate in three modes:

- Events API mode: Slack sends webhooks to our endpoint (needs public URL)
- Socket Mode: We open a WebSocket to Slack (no public URL needed)
- Simulator mode: No real Slack, uses in-memory client (testing)

Priority order (highest wins):
1. Environment variables (SLACK_BOT_TOKEN, etc.)
2. Config file (~/.amplifier/slack.yaml)
3. Dataclass defaults
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from amplifier_distro.conventions import AMPLIFIER_HOME

logger = logging.getLogger(__name__)

SLACK_CONFIG_FILENAME = "slack.yaml"


def _load_config_file() -> dict[str, Any]:
    """Load ~/.amplifier/slack.yaml if it exists."""
    path = Path(AMPLIFIER_HOME).expanduser() / SLACK_CONFIG_FILENAME
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("Failed to read slack.yaml", exc_info=True)
        return {}


def _str_val(
    env_key: str, file_data: dict[str, Any], file_key: str, default: str = ""
) -> str:
    """Get a string value: env > file > default."""
    env = os.environ.get(env_key, "")
    if env:
        return env
    file_val = file_data.get(file_key, "")
    if file_val:
        return str(file_val)
    return default


def _bool_val(
    env_key: str,
    file_data: dict[str, Any],
    file_key: str,
    default: bool = False,
) -> bool:
    """Get a bool value: env > file > default."""
    env = os.environ.get(env_key, "")
    if env:
        return env.lower() in ("1", "true", "yes")
    file_val = file_data.get(file_key)
    if file_val is not None:
        return bool(file_val)
    return default


@dataclass
class SlackConfig:
    """Slack bridge configuration."""

    # --- Slack API Credentials ---
    bot_token: str = ""  # xoxb-... (Bot User OAuth Token)
    app_token: str = ""  # xapp-... (for Socket Mode)
    signing_secret: str = ""  # For Events API signature verification

    # --- Channel Configuration ---
    hub_channel_id: str = ""  # Channel ID for the main hub
    hub_channel_name: str = "amplifier"  # Channel name (used for creation)

    # --- Behavior ---
    thread_per_session: bool = True  # New sessions start as threads
    allow_breakout: bool = True  # Allow promoting threads to channels
    channel_prefix: str = "amp-"  # Prefix for breakout channel names
    bot_name: str = "slackbridge"  # Name the bot responds to

    # --- Session Defaults ---
    default_bundle: str | None = None  # Override distro.yaml default
    default_working_dir: str = "~"  # Default cwd for new sessions

    # --- Limits ---
    max_message_length: int = 3900  # Slack limit is 4000, leave margin
    max_sessions_per_user: int = 10  # Concurrent sessions per user
    response_timeout: int = 300  # Seconds before timing out a response

    # --- Mode ---
    simulator_mode: bool = False  # Use in-memory client (no real Slack)
    socket_mode: bool = False  # Use Socket Mode instead of Events API

    @classmethod
    def from_env(cls) -> SlackConfig:
        """Load config from config file + environment overrides.

        Despite the name (kept for backward compat), this now reads
        from ~/.amplifier/slack.yaml first, then overrides with any
        environment variables that are set.
        """
        f = _load_config_file()
        return cls(
            bot_token=_str_val("SLACK_BOT_TOKEN", f, "bot_token"),
            app_token=_str_val("SLACK_APP_TOKEN", f, "app_token"),
            signing_secret=_str_val("SLACK_SIGNING_SECRET", f, "signing_secret"),
            hub_channel_id=_str_val("SLACK_HUB_CHANNEL_ID", f, "hub_channel_id"),
            hub_channel_name=_str_val(
                "SLACK_HUB_CHANNEL_NAME",
                f,
                "hub_channel_name",
                "amplifier",
            ),
            simulator_mode=_bool_val("SLACK_SIMULATOR_MODE", f, "simulator_mode"),
            socket_mode=_bool_val("SLACK_SOCKET_MODE", f, "socket_mode"),
        )

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
