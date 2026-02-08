"""Session management - maps Slack conversations to Amplifier sessions.

The SlackSessionManager is the routing core of the bridge. It maintains
a mapping table between Slack conversation contexts (channel_id + thread_ts)
and Amplifier session IDs, and delegates message handling to the backend.

Conversation model:
- Hub channel: Commands and session creation happen here
- Thread: Each new session starts as a thread in the hub channel
- Breakout channel: A thread can be promoted to its own channel

The conversation_key is "channel_id:thread_ts" for threads, or just
"channel_id" for top-level channel conversations.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .backend import SessionBackend
from .client import SlackClient
from .config import SlackConfig
from .models import SessionMapping, SlackChannel, SlackMessage

logger = logging.getLogger(__name__)


class SlackSessionManager:
    """Manages Slack-to-Amplifier session mappings.

    This is the core routing table. When a message comes in from Slack,
    the manager looks up which Amplifier session it belongs to and
    routes the message through the backend.
    """

    def __init__(
        self,
        client: SlackClient,
        backend: SessionBackend,
        config: SlackConfig,
    ) -> None:
        self._client = client
        self._backend = backend
        self._config = config
        self._mappings: dict[str, SessionMapping] = {}
        # Track which channels are breakout channels
        self._breakout_channels: dict[str, str] = {}  # channel_id -> session_id

    @property
    def mappings(self) -> dict[str, SessionMapping]:
        """Current mappings (read-only view)."""
        return dict(self._mappings)

    def get_mapping(
        self, channel_id: str, thread_ts: str | None = None
    ) -> SessionMapping | None:
        """Find the session mapping for a Slack conversation context."""
        # First check for thread-specific mapping
        if thread_ts:
            key = f"{channel_id}:{thread_ts}"
            if key in self._mappings:
                return self._mappings[key]

        # Then check for channel-level mapping (breakout channels)
        if channel_id in self._mappings:
            return self._mappings[channel_id]

        # Check breakout channel registry
        if channel_id in self._breakout_channels:
            session_id = self._breakout_channels[channel_id]
            # Find the mapping by session_id
            for mapping in self._mappings.values():
                if mapping.session_id == session_id:
                    return mapping

        return None

    def get_mapping_by_session(self, session_id: str) -> SessionMapping | None:
        """Find mapping by Amplifier session ID."""
        for mapping in self._mappings.values():
            if mapping.session_id == session_id:
                return mapping
        return None

    async def create_session(
        self,
        channel_id: str,
        thread_ts: str | None,
        user_id: str,
        description: str = "",
    ) -> SessionMapping:
        """Create a new Amplifier session and map it to a Slack context.

        If thread_per_session is enabled and thread_ts is None, the bridge
        will create a new thread in the hub channel for this session.
        """
        # Check session limit
        user_sessions = [
            m
            for m in self._mappings.values()
            if m.created_by == user_id and m.is_active
        ]
        if len(user_sessions) >= self._config.max_sessions_per_user:
            raise ValueError(
                f"Session limit reached ({self._config.max_sessions_per_user}). "
                "End an existing session first."
            )

        # Create the backend session
        info = await self._backend.create_session(
            working_dir=self._config.default_working_dir,
            bundle_name=self._config.default_bundle,
            description=description,
        )

        # Determine the conversation key
        key = f"{channel_id}:{thread_ts}" if thread_ts else channel_id

        now = datetime.now(UTC).isoformat()
        mapping = SessionMapping(
            session_id=info.session_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            project_id=info.project_id,
            description=description,
            created_by=user_id,
            created_at=now,
            last_active=now,
        )
        self._mappings[key] = mapping
        logger.info(f"Created session {info.session_id} mapped to {key}")
        return mapping

    async def route_message(self, message: SlackMessage) -> str | None:
        """Route a Slack message to the appropriate Amplifier session.

        Returns the response text, or None if no session is mapped.
        Updates the last_active timestamp on the mapping.
        """
        mapping = self.get_mapping(message.channel_id, message.thread_ts)
        if mapping is None or not mapping.is_active:
            return None

        # Update activity timestamp
        mapping.last_active = datetime.now(UTC).isoformat()

        # Send to backend
        try:
            response = await self._backend.send_message(
                mapping.session_id, message.text
            )
            return response
        except Exception:
            logger.exception(f"Error routing message to session {mapping.session_id}")
            return "Error: Failed to get response from Amplifier session."

    async def end_session(self, channel_id: str, thread_ts: str | None = None) -> bool:
        """End the session mapped to a Slack context.

        Returns True if a session was ended, False if none was found.
        """
        mapping = self.get_mapping(channel_id, thread_ts)
        if mapping is None:
            return False

        mapping.is_active = False
        try:
            await self._backend.end_session(mapping.session_id)
        except Exception:
            logger.exception(f"Error ending session {mapping.session_id}")

        return True

    async def breakout_to_channel(
        self,
        channel_id: str,
        thread_ts: str,
        channel_name: str | None = None,
    ) -> SlackChannel | None:
        """Promote a thread-based session to its own channel.

        Creates a new Slack channel and remaps the session to it.
        Returns the new channel, or None if no session was found.
        """
        mapping = self.get_mapping(channel_id, thread_ts)
        if mapping is None:
            return None

        if not self._config.allow_breakout:
            raise ValueError("Channel breakout is not enabled.")

        # Generate channel name
        if channel_name is None:
            short_id = mapping.session_id[:8]
            channel_name = f"{self._config.channel_prefix}{short_id}"

        # Create the channel
        topic = f"Amplifier session {mapping.session_id[:8]}"
        if mapping.description:
            topic += f" - {mapping.description}"

        new_channel = await self._client.create_channel(channel_name, topic=topic)

        # Update mapping: remove old key, add channel-level key
        old_key = mapping.conversation_key
        self._mappings.pop(old_key, None)

        mapping.channel_id = new_channel.id
        mapping.thread_ts = None  # Now it's channel-level
        self._mappings[new_channel.id] = mapping
        self._breakout_channels[new_channel.id] = mapping.session_id

        # Notify in the new channel
        await self._client.post_message(
            new_channel.id,
            f"Session `{mapping.session_id[:8]}` moved to this channel."
            " Continue the conversation here.",
        )

        return new_channel

    def list_active(self) -> list[SessionMapping]:
        """List all active session mappings."""
        return [m for m in self._mappings.values() if m.is_active]

    def list_user_sessions(self, user_id: str) -> list[SessionMapping]:
        """List active sessions for a specific user."""
        return [
            m
            for m in self._mappings.values()
            if m.created_by == user_id and m.is_active
        ]
