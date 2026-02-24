"""ChatConnection — manages one WebSocket session lifecycle.

One instance per WebSocket connection. Owns:
  - _auth_handshake(): validate token if api_key is configured
  - _receive_loop(): read client messages, dispatch to backend
  - _event_fanout_loop(): drain asyncio.Queue, translate, send to WS
  - event_queue: asyncio.Queue wired to BridgeBackend.on_stream
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
from typing import TYPE_CHECKING, Any

from starlette.websockets import WebSocketDisconnect

from amplifier_distro.server.apps.chat.translator import SessionEventTranslator

if TYPE_CHECKING:
    from fastapi import WebSocket

    from amplifier_distro.server.session_backend import BridgeBackend

logger = logging.getLogger(__name__)

_AUTH_TIMEOUT_S = 30.0

# Sentinel: put into event_queue to stop _event_fanout_loop
_STOP: object = object()


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
        self._active_execution: asyncio.Task | None = None
        # tracks which local block indices received at least one delta
        self._seen_deltas: set[int] = set()

    async def run(self) -> None:
        """Full connection lifecycle: auth then concurrent receive + fanout."""
        await self._ws.accept()
        try:
            await self._auth_handshake()
        except WebSocketDisconnect:
            return

        fanout_task = asyncio.create_task(
            self._event_fanout_loop(), name="event_fanout_loop"
        )
        try:
            await self._receive_loop()
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            logger.warning("ChatConnection receive error", exc_info=True)
        finally:
            # Cancel in-flight execute tasks
            for task in list(self._tasks):
                task.cancel()
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)
            # Stop the fanout loop and wait for it to finish
            fanout_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await fanout_task
            # End the session if one was created
            if self._session_id:
                with contextlib.suppress(Exception):
                    await self._backend.end_session(self._session_id)
            await self.event_queue.put(_STOP)

    async def _auth_handshake(self) -> None:
        """Validate auth token if api_key is configured.

        Also validates WebSocket Origin header to prevent CSRF attacks —
        any browser page can open a WebSocket connection, bypassing SOP.
        Only allows connections from localhost origins.
        """
        # Origin check — prevents CSRF from evil.com → localhost:PORT
        origin = self._ws.headers.get("origin", "")
        if origin:  # skip for non-browser clients (no Origin header)
            allowed = {"http://localhost", "http://127.0.0.1", "https://localhost"}
            # Allow any localhost:PORT variant
            is_localhost = any(
                origin.startswith(allowed_prefix) for allowed_prefix in allowed
            )
            if not is_localhost:
                logger.warning(
                    "Rejected WebSocket from non-localhost origin: %s", origin
                )
                await self._ws.close(4003, "Forbidden origin")
                raise WebSocketDisconnect(code=4003)

        api_key = getattr(self._config.server, "api_key", None)
        if api_key is None:
            return

        try:
            msg = await asyncio.wait_for(
                self._ws.receive_json(), timeout=_AUTH_TIMEOUT_S
            )
        except TimeoutError:
            logger.warning("Auth handshake timed out — closing connection")
            await self._ws.close(4008, "Auth timeout")
            raise WebSocketDisconnect(code=4008) from None

        token = msg.get("token", "")
        if msg.get("type") != "auth" or not hmac.compare_digest(
            str(token), str(api_key)
        ):
            await self._ws.close(4001, "Unauthorized")
            raise WebSocketDisconnect(code=4001)  # signal run() to exit immediately

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
                if self._active_execution and not self._active_execution.done():
                    await self._ws.send_json(
                        {
                            "type": "execution_error",
                            "error": "Execution in progress. Send cancel first.",
                        }
                    )
                    return
                task = asyncio.create_task(
                    self._execute(content, images), name=f"execute-{self._session_id}"
                )
                self._active_execution = task
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
        # TODO: load saved preferences as fallback defaults for cwd, bundle, behaviors
        # from amplifier_distro.server.apps.chat.preferences import load_preferences
        cwd = msg.get("cwd", "~")
        bundle = msg.get("bundle")

        try:
            info = await self._backend.create_session(
                working_dir=cwd,
                bundle_name=bundle,
                event_queue=self.event_queue,
            )
            self._session_id = info.session_id
            self._translator.reset()
            await self._ws.send_json(
                {
                    "type": "session_created",
                    "session_id": info.session_id,
                    "cwd": str(info.working_dir),
                    "bundle": bundle,
                }
            )
        except Exception:  # noqa: BLE001
            logger.warning("Session creation failed", exc_info=True)
            await self._ws.send_json(
                {
                    "type": "execution_error",
                    "error": "Session creation failed. Check server logs.",
                }
            )

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
        except Exception:  # noqa: BLE001
            logger.warning("Execution error", exc_info=True)
            with contextlib.suppress(Exception):
                await self._ws.send_json(
                    {
                        "type": "execution_error",
                        "error": "Execution failed. Check server logs.",
                    }
                )

    async def _handle_command(self, name: str, args: list[str]) -> None:
        """Handle a slash command from the client."""
        try:
            result = await self._dispatch_command(name, args)
            await self._ws.send_json(
                {"type": "command_result", "command": name, "result": result}
            )
        except Exception:  # noqa: BLE001
            logger.warning("Command '%s' failed", name, exc_info=True)
            await self._ws.send_json(
                {
                    "type": "command_result",
                    "command": name,
                    "result": {"error": f"Command '{name}' failed. Check server logs."},
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
                if self._session_id:
                    await self._backend.cancel_session(self._session_id, "graceful")
                    with contextlib.suppress(Exception):
                        await self._backend.end_session(self._session_id)
                info = await self._backend.create_session(
                    bundle_name=new_bundle,
                    event_queue=self.event_queue,
                )
                self._session_id = info.session_id
                self._translator.reset()
                return {"bundle": new_bundle, "session_id": info.session_id}
            case "cwd" if args:
                new_cwd = args[0]
                if self._session_id:
                    await self._backend.cancel_session(self._session_id, "graceful")
                    with contextlib.suppress(Exception):
                        await self._backend.end_session(self._session_id)
                info = await self._backend.create_session(
                    working_dir=new_cwd,
                    event_queue=self.event_queue,
                )
                self._session_id = info.session_id
                self._translator.reset()
                return {"cwd": new_cwd, "session_id": info.session_id}
            case _:
                return {"error": f"Unknown command: {name}"}

    async def _event_fanout_loop(self) -> None:
        """Drain event_queue and forward translated events to WebSocket.

        Stops on _STOP sentinel. Synthesizes streaming deltas for non-streaming
        providers that deliver full text in content_end with no prior deltas.
        """
        while True:
            raw = await self.event_queue.get()
            if raw is _STOP:
                break
            event_name, data = raw
            try:
                # Track which local indices received deltas
                if event_name == "content_block:delta":
                    local_idx = self._translator.get_local_index(data.get("index", 0))
                    self._seen_deltas.add(local_idx)

                # Synthetic streaming: if content_end has text but no deltas were seen,
                # synthesize chunked deltas to animate the response
                if event_name == "content_block:end":
                    local_idx = self._translator.get_local_index(data.get("index", 0))
                    text = data.get("text", "")
                    if text and local_idx not in self._seen_deltas:
                        # Synthesize: send chunked deltas before the end event
                        chunk_size = 12
                        server_index = data.get("index", 0)
                        for i in range(0, len(text), chunk_size):
                            chunk = text[i : i + chunk_size]
                            delta_msg = self._translator.translate(
                                "content_block:delta",
                                {"delta": chunk, "index": server_index},
                            )
                            if delta_msg is not None:
                                await self._ws.send_json(delta_msg)
                    self._seen_deltas.discard(local_idx)

                msg = self._translator.translate(event_name, data)
                if msg is not None:
                    await self._ws.send_json(msg)

                # Reset seen_deltas on prompt_complete
                if event_name == "orchestrator:complete":
                    self._seen_deltas.clear()

            except WebSocketDisconnect:
                logger.debug("WebSocket disconnected during event fanout")
                break
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Error translating/sending event %s session=%s",
                    event_name,
                    self._session_id,
                    exc_info=True,
                )
