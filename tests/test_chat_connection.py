"""Tests for ChatConnection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def make_ws(messages: list[dict]):
    """Create a mock WebSocket that replays messages then raises disconnect."""
    from starlette.websockets import WebSocketDisconnect

    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_json = AsyncMock()

    msg_iter = iter(messages)

    async def receive_json():
        try:
            return next(msg_iter)
        except StopIteration:
            raise WebSocketDisconnect(code=1000) from None

    ws.receive_json = receive_json
    return ws


def make_backend(session_id: str = "test-sess-001"):
    backend = MagicMock()
    info = MagicMock()
    info.session_id = session_id
    info.working_dir = "/tmp/test"
    backend.create_session = AsyncMock(return_value=info)
    backend.execute = AsyncMock(return_value=None)
    backend.cancel_session = AsyncMock(return_value=None)
    backend.resolve_approval = MagicMock(return_value=True)
    return backend


def make_config(api_key: str | None = None):
    config = MagicMock()
    config.server = MagicMock()
    config.server.api_key = api_key
    return config


class TestAuthHandshake:
    @pytest.mark.asyncio
    async def test_no_api_key_skips_auth(self):
        """When api_key is None, auth is skipped immediately."""
        from amplifier_distro.server.apps.chat.connection import ChatConnection

        ws = make_ws([])
        backend = make_backend()
        config = make_config(api_key=None)

        conn = ChatConnection(ws, backend, config)
        await conn.auth_handshake()
        ws.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_correct_token_sends_auth_ok(self):
        from amplifier_distro.server.apps.chat.connection import ChatConnection

        ws = make_ws([{"type": "auth", "token": "secret"}])
        backend = make_backend()
        config = make_config(api_key="secret")

        conn = ChatConnection(ws, backend, config)
        await conn.auth_handshake()

        ws.send_json.assert_awaited_once_with({"type": "auth_ok"})
        ws.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_token_closes_4001(self):
        from starlette.websockets import WebSocketDisconnect

        from amplifier_distro.server.apps.chat.connection import ChatConnection

        ws = make_ws([{"type": "auth", "token": "wrong"}])
        backend = make_backend()
        config = make_config(api_key="secret")

        conn = ChatConnection(ws, backend, config)
        with pytest.raises(WebSocketDisconnect):
            await conn.auth_handshake()

        ws.close.assert_awaited_once_with(4001, "Unauthorized")


class TestReceiveLoop:
    @pytest.mark.asyncio
    async def test_create_session_message(self):
        from starlette.websockets import WebSocketDisconnect

        from amplifier_distro.server.apps.chat.connection import ChatConnection

        ws = make_ws(
            [
                {
                    "type": "create_session",
                    "bundle": "foundation",
                    "cwd": "/tmp",
                    "behaviors": [],
                },
            ]
        )
        backend = make_backend("sess-abc")
        config = make_config()

        conn = ChatConnection(ws, backend, config)
        with pytest.raises(WebSocketDisconnect):
            await conn._receive_loop()

        backend.create_session.assert_awaited_once()
        call_kwargs = backend.create_session.call_args.kwargs
        assert call_kwargs.get("working_dir") == "/tmp"

    @pytest.mark.asyncio
    async def test_ping_sends_pong(self):
        from starlette.websockets import WebSocketDisconnect

        from amplifier_distro.server.apps.chat.connection import ChatConnection

        ws = make_ws([{"type": "ping"}])
        backend = make_backend()
        config = make_config()

        conn = ChatConnection(ws, backend, config)
        with pytest.raises(WebSocketDisconnect):
            await conn._receive_loop()

        sent = [call.args[0] for call in ws.send_json.await_args_list]
        assert any(m.get("type") == "pong" for m in sent)


class TestEventFanout:
    @pytest.mark.asyncio
    async def test_events_forwarded_to_websocket(self):
        from amplifier_distro.server.apps.chat.connection import ChatConnection

        ws = make_ws([])
        backend = make_backend()
        config = make_config()

        conn = ChatConnection(ws, backend, config)
        await conn.event_queue.put(("orchestrator:complete", {"turn_count": 1}))
        await conn.event_queue.put(None)  # sentinel to stop the loop

        await conn._event_fanout_loop()

        sent = [call.args[0] for call in ws.send_json.await_args_list]
        assert any(m.get("type") == "prompt_complete" for m in sent)

    @pytest.mark.asyncio
    async def test_unknown_events_not_forwarded(self):
        from amplifier_distro.server.apps.chat.connection import ChatConnection

        ws = make_ws([])
        backend = make_backend()
        config = make_config()

        conn = ChatConnection(ws, backend, config)
        await conn.event_queue.put(("some:unknown:event", {}))
        await conn.event_queue.put(None)

        await conn._event_fanout_loop()

        # Unknown event produces None from translator — nothing sent
        ws.send_json.assert_not_awaited()
