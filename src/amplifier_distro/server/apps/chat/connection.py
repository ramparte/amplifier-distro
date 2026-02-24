"""ChatConnection — manages one WebSocket session lifecycle.

One instance per WebSocket connection. Owns:
  - auth_handshake(): validate token if api_key is configured
  - _receive_loop(): read client messages, dispatch to backend
  - _event_fanout_loop(): drain asyncio.Queue, translate, send to WS
  - event_queue: asyncio.Queue wired to BridgeBackend.on_stream
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from starlette.websockets import WebSocketDisconnect

from amplifier_distro.server.apps.chat.translator import SessionEventTranslator

if TYPE_CHECKING:
    from fastapi import WebSocket

    from amplifier_distro.server.session_backend import BridgeBackend

logger = logging.getLogger(__name__)

# Sentinel: put into event_queue to stop _event_fanout_loop
_STOP = None


class ChatConnection:
    """Manages one WebSocket connection: auth, receive loop, event fanout."""

    def __init__(
        self,
        ws: WebSocket,
        backend: BridgeBackend,
        config: Any,
    ) -> None:
        self._ws = ws
        self._backend = backend
        self._config = config
        self.event_queue: asyncio.Queue = asyncio.Queue()
        self._translator = SessionEventTranslator()
        self._session_id: str | None = None
        # keeps strong refs to fire-and-forget tasks so GC can't collect them
        self._tasks: set[asyncio.Task] = set()

    async def run(self) -> None:
        """Full connection lifecycle: auth then concurrent receive + fanout."""
        await self._ws.accept()
        try:
            await self.auth_handshake()
        except WebSocketDisconnect:
            return

        try:
            await asyncio.gather(
                self._receive_loop(),
                self._event_fanout_loop(),
            )
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            logger.warning("ChatConnection error", exc_info=True)
        finally:
            await self.event_queue.put(_STOP)

    async def auth_handshake(self) -> None:
        """Validate auth token if api_key is configured.

        Closes with code 4001 if wrong token.
        No-op if api_key is None.
        """
        api_key = getattr(self._config.server, "api_key", None)
        if not api_key:
            return

        msg = await self._ws.receive_json()  # propagates WebSocketDisconnect

        if msg.get("type") != "auth" or msg.get("token") != api_key:
            await self._ws.close(4001, "Unauthorized")
            return

        await self._ws.send_json({"type": "auth_ok"})

    async def _receive_loop(self) -> None:
        """Read messages from client and dispatch by type.

        Raises WebSocketDisconnect when the client disconnects — callers
        (e.g. run()) are responsible for handling it.
        """
        while True:
            msg = await self._ws.receive_json()  # propagates WebSocketDisconnect

            msg_type = msg.get("type", "")
            try:
                await self._dispatch(msg_type, msg)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Error dispatching message type=%s", msg_type, exc_info=True
                )
                await self._ws.send_json(
                    {
                        "type": "execution_error",
                        "error": "Internal error processing message",
                    }
                )

    async def _dispatch(self, msg_type: str, msg: dict[str, Any]) -> None:
        """Route a received message to the appropriate handler."""
        match msg_type:
            case "create_session":
                await self._handle_create_session(msg)

            case "prompt":
                content = msg.get("content", "")
                images = msg.get("images")
                task = asyncio.create_task(self._execute(content, images))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

            case "cancel":
                level = msg.get("level", "graceful")
                if self._session_id:
                    await self._backend.cancel_session(self._session_id, level)

            case "approval_response":
                req_id = msg.get("id", "")
                choice = msg.get("choice", "deny")
                if self._session_id:
                    self._backend.resolve_approval(self._session_id, req_id, choice)

            case "command":
                name = msg.get("name", "")
                args = msg.get("args", [])
                await self._handle_command(name, args)

            case "ping":
                await self._ws.send_json({"type": "pong"})

            case _:
                logger.debug("Unknown message type: %s", msg_type)

    async def _handle_create_session(self, msg: dict[str, Any]) -> None:
        """Create or resume an Amplifier session."""
        cwd = msg.get("cwd", "~")
        bundle = msg.get("bundle")

        try:
            info = await self._backend.create_session(
                working_dir=cwd,
                bundle_name=bundle,
                event_queue=self.event_queue,
            )
            self._session_id = info.session_id
            await self._ws.send_json(
                {
                    "type": "session_created",
                    "session_id": info.session_id,
                    "cwd": str(info.working_dir),
                    "bundle": bundle,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Session creation failed", exc_info=True)
            await self._ws.send_json({"type": "execution_error", "error": str(exc)})

    async def _execute(self, content: str, images: list[str] | None = None) -> None:
        """Execute a prompt — events stream via event_queue."""
        if not self._session_id:
            await self._ws.send_json(
                {
                    "type": "execution_error",
                    "error": "No session. Send create_session first.",
                }
            )
            return

        try:
            await self._backend.execute(self._session_id, content, images)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Execution error", exc_info=True)
            await self._ws.send_json({"type": "execution_error", "error": str(exc)})

    async def _handle_command(self, name: str, args: list[str]) -> None:
        """Handle a slash command from the client."""
        try:
            result = await self._dispatch_command(name, args)
            await self._ws.send_json(
                {"type": "command_result", "command": name, "result": result}
            )
        except Exception as exc:  # noqa: BLE001
            await self._ws.send_json(
                {
                    "type": "command_result",
                    "command": name,
                    "result": {"error": str(exc)},
                }
            )

    async def _dispatch_command(self, name: str, args: list[str]) -> dict[str, Any]:
        """Route server-side slash commands."""
        match name:
            case "status":
                return {
                    "session_id": self._session_id,
                    "status": "active" if self._session_id else "no_session",
                }
            case "bundle" if args:
                new_bundle = args[0]
                info = await self._backend.create_session(
                    bundle_name=new_bundle,
                    event_queue=self.event_queue,
                )
                self._session_id = info.session_id
                return {"bundle": new_bundle, "session_id": info.session_id}
            case "cwd" if args:
                new_cwd = args[0]
                info = await self._backend.create_session(
                    working_dir=new_cwd,
                    event_queue=self.event_queue,
                )
                self._session_id = info.session_id
                return {"cwd": new_cwd, "session_id": info.session_id}
            case _:
                return {"error": f"Unknown command: {name}"}

    async def _event_fanout_loop(self) -> None:
        """Drain event_queue and forward translated events to WebSocket.

        Stops on None sentinel.
        """
        while True:
            raw = await self.event_queue.get()
            if raw is _STOP:
                break
            event_name, data = raw
            try:
                msg = self._translator.translate(event_name, data)
                if msg is not None:
                    await self._ws.send_json(msg)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Error translating/sending event %s", event_name, exc_info=True
                )
