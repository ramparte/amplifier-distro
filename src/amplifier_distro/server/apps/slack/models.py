"""Data models for the Slack bridge.

Defines the core data structures used throughout the bridge:
- Slack-side models (messages, channels, users)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChannelType(StrEnum):
    """Type of Slack channel in the bridge context."""

    HUB = "hub"  # The main #amplifier channel
    SESSION = "session"  # A breakout channel for a specific session


@dataclass
class SlackUser:
    """A Slack user."""

    id: str
    name: str
    display_name: str = ""


@dataclass
class SlackChannel:
    """A Slack channel."""

    id: str
    name: str
    channel_type: ChannelType = ChannelType.HUB
    topic: str = ""
    created_at: str = ""


@dataclass
class SlackMessage:
    """A message from Slack."""

    channel_id: str
    user_id: str
    text: str
    ts: str  # Slack timestamp (unique message ID)
    thread_ts: str | None = None  # Parent thread timestamp (None = top-level)
    user_name: str = ""

    @property
    def is_threaded(self) -> bool:
        """Whether this message is in a thread."""
        return self.thread_ts is not None

    @property
    def conversation_key(self) -> str:
        """Unique key for the conversation context (channel + thread)."""
        if self.thread_ts:
            return f"{self.channel_id}:{self.thread_ts}"
        return self.channel_id
