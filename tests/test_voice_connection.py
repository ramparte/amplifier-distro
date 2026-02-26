"""Tests for VoiceConnection lifecycle manager.

Exit criteria (TestVoiceConnectionLifecycle):
1. create() calls backend.create_session with app_name='voice' and event_queue kwargs
2. create() returns amplifier session_id
3. spawn capability registered on coordinator after create
   (register_capability called with 'spawn')
4. teardown() calls mark_disconnected with session_id
5. hook unregistered even when mark_disconnected raises RuntimeError (finally block)
6. end() calls backend.end_session with session_id
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from amplifier_distro.server.apps.voice.connection import VoiceConnection


class _MockSession:
    """Fake AmplifierSession with coordinator."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.coordinator = MagicMock()
        self.coordinator.register_capability = MagicMock()


class _MockBackend:
    """Minimal fake backend for VoiceConnection tests."""

    def __init__(self) -> None:
        self._session = _MockSession("test-session-001")
        self.create_session_calls: list[dict] = []
        self.register_hooks_calls: list[tuple] = []
        self.mark_disconnected_calls: list[str] = []
        self.end_session_calls: list[str] = []
        self.cancel_session_calls: list[dict] = []
        self._unregister_mock = MagicMock()

    async def create_session(self, **kwargs) -> _MockSession:
        self.create_session_calls.append(kwargs)
        return self._session

    def register_hooks(self, session_id: str, hook: object) -> object:
        self.register_hooks_calls.append((session_id, hook))
        return self._unregister_mock

    async def mark_disconnected(self, session_id: str) -> None:
        self.mark_disconnected_calls.append(session_id)

    async def end_session(self, session_id: str) -> None:
        self.end_session_calls.append(session_id)

    async def cancel_session(self, session_id: str, immediate: bool = False) -> None:
        self.cancel_session_calls.append(
            {"session_id": session_id, "immediate": immediate}
        )


class _MockRepository:
    """Minimal fake repository for VoiceConnection tests."""

    def __init__(self) -> None:
        self.update_status_calls: list[tuple] = []
        self.end_conversation_calls: list[tuple] = []

    def update_status(self, session_id: str, status: str) -> None:
        self.update_status_calls.append((session_id, status))

    def end_conversation(self, session_id: str, reason: str) -> None:
        self.end_conversation_calls.append((session_id, reason))


class TestVoiceConnectionLifecycle:
    """Tests for VoiceConnection lifecycle methods."""

    def _make_connection(self) -> tuple[VoiceConnection, _MockBackend, _MockRepository]:
        backend = _MockBackend()
        repo = _MockRepository()
        conn = VoiceConnection(repository=repo, backend=backend)
        return conn, backend, repo

    async def test_create_calls_backend_with_app_name_and_event_queue(self) -> None:
        """create() calls backend.create_session with app_name='voice' and event_queue."""  # noqa: E501
        conn, backend, _ = self._make_connection()
        await conn.create(workspace_root="/tmp/test")

        assert len(backend.create_session_calls) == 1
        kwargs = backend.create_session_calls[0]
        assert kwargs.get("app_name") == "voice"
        assert "event_queue" in kwargs

    async def test_create_returns_session_id(self) -> None:
        """create() returns the amplifier session_id from backend."""
        conn, _backend, _ = self._make_connection()
        result = await conn.create(workspace_root="/tmp/test")
        assert result == "test-session-001"

    async def test_spawn_capability_registered_on_coordinator(self) -> None:
        """spawn capability registered on coordinator after create."""
        conn, backend, _ = self._make_connection()
        await conn.create(workspace_root="/tmp/test")

        session = backend._session
        session.coordinator.register_capability.assert_called_once_with(
            "spawn", conn._spawn_child_session
        )

    async def test_teardown_calls_mark_disconnected(self) -> None:
        """teardown() calls mark_disconnected with session_id."""
        conn, backend, _ = self._make_connection()
        await conn.create(workspace_root="/tmp/test")
        await conn.teardown()

        assert backend.mark_disconnected_calls == ["test-session-001"]

    async def test_hook_unregistered_even_when_mark_disconnected_raises(self) -> None:
        """hook unregistered even when mark_disconnected raises RuntimeError."""

        async def _raise_on_disconnect(session_id: str) -> None:
            raise RuntimeError("connection lost")

        conn, backend, _ = self._make_connection()
        backend.mark_disconnected = _raise_on_disconnect
        await conn.create(workspace_root="/tmp/test")

        with pytest.raises(RuntimeError, match="connection lost"):
            await conn.teardown()

        # Hook unregister must still have been called
        backend._unregister_mock.assert_called_once()

    async def test_end_calls_backend_end_session(self) -> None:
        """end() calls backend.end_session with session_id."""
        conn, backend, _ = self._make_connection()
        await conn.create(workspace_root="/tmp/test")
        await conn.end()

        assert backend.end_session_calls == ["test-session-001"]
