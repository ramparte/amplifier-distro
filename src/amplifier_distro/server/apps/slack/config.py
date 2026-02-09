"""Configuration for the Slack bridge.

Loaded from environment variables and/or the distro server config.
The bridge can operate in three modes:

- Events API mode: Slack sends webhooks to our endpoint (needs public URL)
- Socket Mode: We open a WebSocket to Slack (no public URL needed)
- Simulator mode: No real Slack, uses in-memory client (testing)
"""

from __future__ import annotations

import os
from dataclasses import dataclass


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
        """Load config from environment variables."""
        return cls(
            bot_token=os.environ.get("SLACK_BOT_TOKEN", ""),
            app_token=os.environ.get("SLACK_APP_TOKEN", ""),
            signing_secret=os.environ.get("SLACK_SIGNING_SECRET", ""),
            hub_channel_id=os.environ.get("SLACK_HUB_CHANNEL_ID", ""),
            hub_channel_name=os.environ.get("SLACK_HUB_CHANNEL_NAME", "amplifier"),
            simulator_mode=os.environ.get("SLACK_SIMULATOR_MODE", "").lower()
            in ("1", "true", "yes"),
            socket_mode=os.environ.get("SLACK_SOCKET_MODE", "").lower()
            in ("1", "true", "yes"),
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
