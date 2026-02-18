"""Session management - maps Slack conversations to Amplifier sessions.

The SlackSessionManager is the routing core of the bridge. It maintains
a mapping table between Slack conversation contexts (channel_id + thread_ts)
and Amplifier session IDs, and delegates message handling to the backend.

Conversation model:
- Hub channel: Commands and session creation happen here
- Thread: Each new session starts as a thread in the hub channel
- Breakout channel: A thread can be promoted to its own channel

The routing_key is "channel_id:thread_ts" for threads, or just
"channel_id" for top-level channel conversations.

Persistence:
- Session mappings are persisted via SurfaceSessionRegistry.
- The file path comes from conventions.py (SLACK_SESSIONS_FILENAME).
- Mappings are loaded on startup and saved on every change.
"""

from __future__ import annotations

import logging
from pathlib import Path

from amplifier_distro.conventions import (
    AMPLIFIER_HOME,
    SERVER_DIR,
    SLACK_SESSIONS_FILENAME,
)
from amplifier_distro.server.surface_registry import (
    SessionMapping as RegistryMapping,
)
from amplifier_distro.server.surface_registry import (
    SurfaceSessionRegistry,
)

from .backend import SessionBackend
from .client import SlackClient
from .config import SlackConfig
from .models import SlackChannel, SlackMessage

logger = logging.getLogger(__name__)

# The registry's SessionMapping is now the canonical type.
# Alias for backward compatibility with code that imports from here.
SessionMapping = RegistryMapping


def _default_persistence_path() -> Path:
    """Return the default path for session persistence file."""
    return Path(AMPLIFIER_HOME).expanduser() / SERVER_DIR / SLACK_SESSIONS_FILENAME


class SlackSessionManager:
    """Manages Slack-to-Amplifier session mappings.

    This is the core routing table. When a message comes in from Slack,
    the manager looks up which Amplifier session it belongs to and
    routes the message through the backend.

    Session mappings are persisted via SurfaceSessionRegistry so they
    survive server restarts. Pass persistence_path=None to disable
    persistence (useful in tests).
    """

    def __init__(
        self,
        client: SlackClient,
        backend: SessionBackend,
        config: SlackConfig,
        persistence_path: Path | None = None,
    ) -> None:
        self._client = client
        self._backend = backend
        self._config = config
        self._registry = SurfaceSessionRegistry(
            "slack",
            persistence_path,
            self._config.max_sessions_per_user,
        )
        # Track which channels are breakout channels
        self._breakout_channels: dict[str, str] = {}  # channel_id -> session_id

    @property
    def mappings(self) -> dict[str, RegistryMapping]:
        """Current mappings (read-only view)."""
        return self._registry.mappings

    def get_mapping(
        self, channel_id: str, thread_ts: str | None = None
    ) -> RegistryMapping | None:
        """Find the session mapping for a Slack conversation context.

        Uses the registry for lookup but implements Slack's 3-tier
        routing: thread -> channel -> breakout registry.
        """
        if thread_ts:
            key = f"{channel_id}:{thread_ts}"
            found = self._registry.lookup(key)
            if found is not None:
                return found

        found = self._registry.lookup(channel_id)
        if found is not None:
            return found

        if channel_id in self._breakout_channels:
            session_id = self._breakout_channels[channel_id]
            return self._registry.lookup_by_session_id(session_id)

        return None

    def get_mapping_by_session(self, session_id: str) -> RegistryMapping | None:
        """Find mapping by Amplifier session ID."""
        return self._registry.lookup_by_session_id(session_id)

    async def create_session(
        self,
        channel_id: str,
        thread_ts: str | None,
        user_id: str,
        description: str = "",
    ) -> RegistryMapping:
        """Create a new Amplifier session and map it to a Slack context."""
        self._registry.check_limit(user_id)

        info = await self._backend.create_session(
            working_dir=self._config.default_working_dir,
            bundle_name=self._config.default_bundle,
            description=description,
        )

        key = f"{channel_id}:{thread_ts}" if thread_ts else channel_id

        mapping = self._registry.register(
            routing_key=key,
            session_id=info.session_id,
            user_id=user_id,
            project_id=info.project_id,
            description=description,
            channel_id=channel_id,
            thread_ts=thread_ts or "",
        )
        logger.info(f"Created session {info.session_id} mapped to {key}")
        return mapping

    async def connect_session(
        self,
        channel_id: str,
        thread_ts: str | None,
        user_id: str,
        working_dir: str,
        description: str = "",
    ) -> RegistryMapping:
        """Connect a Slack context to a new backend session in *working_dir*."""
        self._registry.check_limit(user_id)

        info = await self._backend.create_session(
            working_dir=working_dir,
            bundle_name=self._config.default_bundle,
            description=description,
        )

        key = f"{channel_id}:{thread_ts}" if thread_ts else channel_id

        mapping = self._registry.register(
            routing_key=key,
            session_id=info.session_id,
            user_id=user_id,
            project_id=info.project_id,
            description=description,
            channel_id=channel_id,
            thread_ts=thread_ts or "",
        )
        logger.info(
            f"Connected session {info.session_id} (in {working_dir}) mapped to {key}"
        )
        return mapping

    async def route_message(self, message: SlackMessage) -> str | None:
        """Route a Slack message to the appropriate Amplifier session."""
        mapping = self.get_mapping(message.channel_id, message.thread_ts)
        if mapping is None or not mapping.is_active:
            return None

        self._registry.update_activity(mapping.routing_key)

        try:
            response = await self._backend.send_message(
                mapping.session_id, message.text
            )
            return response
        except Exception:
            logger.exception(f"Error routing message to session {mapping.session_id}")
            return "Error: Failed to get response from Amplifier session."

    async def end_session(self, channel_id: str, thread_ts: str | None = None) -> bool:
        """End the session mapped to a Slack context."""
        mapping = self.get_mapping(channel_id, thread_ts)
        if mapping is None:
            return False

        self._registry.deactivate(mapping.routing_key)
        try:
            await self._backend.end_session(mapping.session_id)
        except (RuntimeError, ValueError, ConnectionError, OSError):
            logger.exception(f"Error ending session {mapping.session_id}")

        return True

    async def breakout_to_channel(
        self,
        channel_id: str,
        thread_ts: str,
        channel_name: str | None = None,
    ) -> SlackChannel | None:
        """Promote a thread-based session to its own channel."""
        mapping = self.get_mapping(channel_id, thread_ts)
        if mapping is None:
            return None

        if not self._config.allow_breakout:
            raise ValueError("Channel breakout is not enabled.")

        if channel_name is None:
            short_id = mapping.session_id[:8]
            channel_name = f"{self._config.channel_prefix}{short_id}"

        topic = f"Amplifier session {mapping.session_id[:8]}"
        if mapping.description:
            topic += f" - {mapping.description}"

        new_channel = await self._client.create_channel(channel_name, topic=topic)

        # Remove old mapping, register new one under channel key
        self._registry.remove(mapping.routing_key)

        self._registry.register(
            routing_key=new_channel.id,
            session_id=mapping.session_id,
            user_id=mapping.created_by,
            project_id=mapping.project_id,
            description=mapping.description,
            channel_id=new_channel.id,
            thread_ts="",
        )
        self._breakout_channels[new_channel.id] = mapping.session_id

        await self._client.post_message(
            new_channel.id,
            f"Session `{mapping.session_id[:8]}` moved to this channel."
            " Continue the conversation here.",
        )

        return new_channel

    def list_active(self) -> list[RegistryMapping]:
        """List all active session mappings."""
        return self._registry.list_active()

    def list_user_sessions(self, user_id: str) -> list[RegistryMapping]:
        """List active sessions for a specific user."""
        return self._registry.list_for_user(user_id)
