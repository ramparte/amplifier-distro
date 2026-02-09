# pyright: reportMissingImports=false
"""Socket Mode adapter for the Slack bridge.

Connects to Slack via WebSocket (no public URL needed).
Routes incoming events to the existing SlackEventHandler.

Uses a direct aiohttp WebSocket connection instead of slack_bolt,
because the slack_bolt AsyncSocketModeHandler silently drops events
in some configurations. This gives us full control over the
WebSocket lifecycle and event dispatch.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import aiohttp
import httpx

if TYPE_CHECKING:
    from .config import SlackConfig
    from .events import SlackEventHandler

logger = logging.getLogger(__name__)

# Reconnect backoff
_INITIAL_BACKOFF = 1.0
_MAX_BACKOFF = 60.0
_BACKOFF_FACTOR = 2.0

# Dedup window: ignore duplicate events for the same message within this window
_DEDUP_WINDOW_SECS = 10.0
_DEDUP_MAX_SIZE = 200


class SocketModeAdapter:
    """Bridges Slack Socket Mode events to our SlackEventHandler.

    Manages the WebSocket connection directly via aiohttp:
    - Calls apps.connections.open for a fresh WebSocket URL
    - Connects and processes frames (hello, events, ping/pong)
    - Acknowledges events and forwards them to our handler
    - Automatic reconnection with exponential backoff
    """

    def __init__(
        self,
        config: SlackConfig,
        event_handler: SlackEventHandler,
    ) -> None:
        self._config = config
        self._event_handler = event_handler
        self._task: asyncio.Task[None] | None = None
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._running = False
        self._bot_user_id: str | None = None
        # Dedup: track recently-seen message timestamps to avoid processing
        # both app_mention and message events for the same @mention.
        # Maps "channel:ts" -> monotonic time when first seen.
        self._seen_events: dict[str, float] = {}

    async def start(self) -> None:
        """Start the Socket Mode connection in the background."""
        if not self._config.app_token:
            raise ValueError(
                "SLACK_APP_TOKEN is required for Socket Mode. "
                "Generate one at https://api.slack.com/apps -> Socket Mode"
            )

        # Resolve our own bot user ID so we can filter self-messages
        self._bot_user_id = await self._resolve_bot_id()

        self._running = True
        self._task = asyncio.create_task(self._connection_loop())
        logger.info("Socket Mode adapter started")

    async def _resolve_bot_id(self) -> str | None:
        """Get the bot's own user ID via auth.test."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {self._config.bot_token}"},
                )
                data = resp.json()
                if data.get("ok"):
                    bot_id = data.get("user_id")
                    logger.info(f"Bot user ID: {bot_id}")
                    return bot_id
        except Exception:
            logger.exception("Failed to resolve bot user ID")
        return None

    async def _get_ws_url(self) -> str:
        """Call apps.connections.open to get a fresh WebSocket URL."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://slack.com/api/apps.connections.open",
                headers={
                    "Authorization": f"Bearer {self._config.app_token}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"apps.connections.open failed: {data.get('error')}")
            return data["url"]

    async def _connection_loop(self) -> None:
        """Main loop: connect, process, reconnect on failure."""
        backoff = _INITIAL_BACKOFF

        while self._running:
            try:
                url = await self._get_ws_url()
                logger.info("Connecting to Slack Socket Mode WebSocket...")

                session = aiohttp.ClientSession()
                self._session = session
                self._ws = await session.ws_connect(url)
                logger.info("WebSocket connected")

                # Reset backoff on successful connection
                backoff = _INITIAL_BACKOFF

                await self._process_frames()

            except asyncio.CancelledError:
                logger.info("Socket Mode connection cancelled")
                break
            except Exception:
                logger.exception("Socket Mode connection error")
            finally:
                await self._close_ws()

            if self._running:
                logger.info(f"Reconnecting in {backoff:.0f}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * _BACKOFF_FACTOR, _MAX_BACKOFF)

    async def _process_frames(self) -> None:
        """Read and dispatch WebSocket frames."""
        assert self._ws is not None
        logger.info("[socket] Entering frame processing loop")

        async for msg in self._ws:
            if not self._running:
                logger.info("[socket] Stopping: running=False")
                break

            logger.debug(f"[socket] Frame: type={msg.type}")

            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    frame_type = data.get("type", "?")
                    logger.debug(f"[socket] TEXT frame: {frame_type}")
                    await self._handle_frame(data)
                except Exception:
                    logger.exception("Error handling WebSocket frame")

            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error(f"WebSocket error: {self._ws.exception()}")
                break

            elif msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
            ):
                logger.info("WebSocket closed by server")
                break

        logger.info("[socket] Frame processing loop exited")

    async def _handle_frame(self, frame: dict[str, Any]) -> None:
        """Dispatch a single WebSocket frame."""
        frame_type = frame.get("type", "")

        if frame_type == "hello":
            num_conns = frame.get("num_connections", "?")
            logger.info(f"Socket Mode hello (connections: {num_conns})")

        elif frame_type == "disconnect":
            reason = frame.get("reason", "unknown")
            logger.warning(f"Socket Mode disconnect requested: {reason}")
            # Server wants us to reconnect (e.g., deploy)
            if self._ws:
                await self._ws.close()

        elif frame_type == "events_api":
            await self._handle_event(frame)

        elif frame_type == "interactive":
            # Future: handle button clicks, modals, etc.
            await self._ack(frame)
            logger.debug("Interactive payload (not yet handled)")

        elif frame_type == "slash_commands":
            # Future: handle slash commands
            await self._ack(frame)
            logger.debug("Slash command (not yet handled)")

        # Ignore pings -- aiohttp handles pong automatically

    async def _handle_event(self, frame: dict[str, Any]) -> None:
        """Process an events_api frame."""
        payload = frame.get("payload", {})
        event = payload.get("event", {})

        event_type = event.get("type", "?")
        user = event.get("user", "?")
        text = event.get("text", "")[:80]
        channel = event.get("channel", "?")
        msg_ts = event.get("ts", "")

        logger.info(
            f"[socket] Event: type={event_type} user={user} "
            f"channel={channel} text={text!r}"
        )

        # Acknowledge immediately (Slack retries if no ack within 3s)
        await self._ack(frame)

        # Skip our own messages
        if user == self._bot_user_id:
            logger.debug("[socket] Skipping own message")
            return

        # Skip bot messages (subtype check)
        if event.get("subtype") == "bot_message":
            logger.debug("[socket] Skipping bot_message subtype")
            return

        # Deduplicate: Slack sends both app_mention and message events for
        # the same @mention. We only process the first one we see for a
        # given channel:ts pair.
        if msg_ts and channel:
            dedup_key = f"{channel}:{msg_ts}"
            if self._is_duplicate(dedup_key):
                logger.info(
                    f"[socket] Skipping duplicate event {event_type} for {dedup_key}"
                )
                return

        # Forward to our event handler
        handler_payload = {
            "type": "event_callback",
            "event": event,
        }
        try:
            result = await self._event_handler.handle_event_payload(handler_payload)
            logger.info(f"[socket] Handler result: {result}")
        except Exception:
            logger.exception("[socket] Error in event handler")

    def _is_duplicate(self, key: str) -> bool:
        """Check if this event key was recently seen. Records it if not.

        Uses a simple dict with monotonic timestamps. Evicts stale entries
        periodically to bound memory.
        """
        now = time.monotonic()

        # Evict stale entries if the cache is getting large
        if len(self._seen_events) > _DEDUP_MAX_SIZE:
            cutoff = now - _DEDUP_WINDOW_SECS
            self._seen_events = {
                k: v for k, v in self._seen_events.items() if v > cutoff
            }

        if key in self._seen_events:
            age = now - self._seen_events[key]
            if age < _DEDUP_WINDOW_SECS:
                return True
            # Expired, treat as new

        self._seen_events[key] = now
        return False

    async def _ack(self, frame: dict[str, Any]) -> None:
        """Send acknowledgement for a Socket Mode envelope."""
        eid = frame.get("envelope_id")
        if eid and self._ws and not self._ws.closed:
            await self._ws.send_json({"envelope_id": eid})

    async def _close_ws(self) -> None:
        """Close WebSocket and HTTP session."""
        if self._ws and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None

        if self._session and not self._session.closed:
            try:
                await self._session.close()
            except Exception:
                pass
        self._session = None

    async def stop(self) -> None:
        """Stop the Socket Mode connection."""
        self._running = False

        await self._close_ws()

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("Socket Mode adapter stopped")
