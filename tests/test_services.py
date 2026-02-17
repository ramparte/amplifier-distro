"""Server Services Layer Tests

These tests validate the shared services infrastructure that all
server apps depend on. The services layer owns the session backend
and provides it to all apps via init_services() / get_services().

Exit criteria verified:
1. init_services() creates a ServerServices with MockBackend in dev mode
2. get_services() returns the initialized instance
3. get_services() raises RuntimeError before initialization
4. reset_services() clears the singleton (for test isolation)
5. Custom backend can be injected (for testing)
6. ServerServices extras dict works for extensibility
"""

import pytest

from amplifier_distro.server.services import (
    ServerServices,
    get_services,
    init_services,
    reset_services,
)
from amplifier_distro.server.session_backend import (
    MockBackend,
    SessionBackend,
    SessionInfo,
)


@pytest.fixture(autouse=True)
def _clean_services():
    """Ensure services are reset between tests."""
    reset_services()
    yield
    reset_services()


class TestInitServices:
    """Verify init_services() creates correct backends."""

    def test_dev_mode_uses_mock_backend(self):
        services = init_services(dev_mode=True)
        assert isinstance(services.backend, MockBackend)

    def test_dev_mode_flag_stored(self):
        services = init_services(dev_mode=True)
        assert services.dev_mode is True

    def test_custom_backend_injected(self):
        custom = MockBackend()
        services = init_services(backend=custom)
        assert services.backend is custom

    def test_returns_server_services_instance(self):
        services = init_services(dev_mode=True)
        assert isinstance(services, ServerServices)


class TestGetServices:
    """Verify get_services() retrieval and error handling."""

    def test_raises_before_init(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            get_services()

    def test_returns_initialized_instance(self):
        original = init_services(dev_mode=True)
        retrieved = get_services()
        assert retrieved is original

    def test_returns_same_instance_on_repeated_calls(self):
        init_services(dev_mode=True)
        first = get_services()
        second = get_services()
        assert first is second


class TestResetServices:
    """Verify reset_services() clears the singleton."""

    def test_reset_makes_get_raise(self):
        init_services(dev_mode=True)
        get_services()  # Should work
        reset_services()
        with pytest.raises(RuntimeError):
            get_services()


class TestServerServicesExtras:
    """Verify the extras dict for extensibility."""

    def test_set_and_get_extra(self):
        services = init_services(dev_mode=True)
        services["discovery"] = "mock-discovery"
        assert services["discovery"] == "mock-discovery"

    def test_get_with_default(self):
        services = init_services(dev_mode=True)
        assert services.get("nonexistent") is None
        assert services.get("nonexistent", 42) == 42

    def test_missing_extra_raises_key_error(self):
        services = init_services(dev_mode=True)
        with pytest.raises(KeyError):
            _ = services["missing"]


class TestSessionBackendProtocol:
    """Verify MockBackend conforms to SessionBackend protocol."""

    def test_mock_backend_is_session_backend(self):
        backend = MockBackend()
        assert isinstance(backend, SessionBackend)

    def test_session_info_dataclass(self):
        info = SessionInfo(
            session_id="test-123",
            project_id="proj",
            working_dir="/tmp",
        )
        assert info.session_id == "test-123"
        assert info.is_active is True
        assert info.created_by_app == ""


class TestMockBackendOperations:
    """Verify MockBackend CRUD operations."""

    @pytest.fixture
    def backend(self):
        return MockBackend()

    @pytest.mark.asyncio
    async def test_create_session(self, backend):
        info = await backend.create_session(
            working_dir="/tmp",
            description="test session",
        )
        assert info.session_id.startswith("mock-session-")
        assert info.is_active is True
        assert info.working_dir == "/tmp"

    @pytest.mark.asyncio
    async def test_send_message(self, backend):
        info = await backend.create_session()
        response = await backend.send_message(info.session_id, "hello")
        assert "hello" in response

    @pytest.mark.asyncio
    async def test_send_message_unknown_session(self, backend):
        with pytest.raises(ValueError, match="Unknown session"):
            await backend.send_message("nonexistent", "hello")

    @pytest.mark.asyncio
    async def test_end_session(self, backend):
        info = await backend.create_session()
        await backend.end_session(info.session_id)
        ended = await backend.get_session_info(info.session_id)
        assert ended is not None
        assert ended.is_active is False

    @pytest.mark.asyncio
    async def test_list_active_sessions(self, backend):
        await backend.create_session(description="a")
        await backend.create_session(description="b")
        info_c = await backend.create_session(description="c")
        await backend.end_session(info_c.session_id)

        active = backend.list_active_sessions()
        assert len(active) == 2

    @pytest.mark.asyncio
    async def test_get_session_info_unknown(self, backend):
        result = await backend.get_session_info("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_custom_response_fn(self, backend):
        backend.set_response_fn(lambda sid, msg: f"Custom: {msg}")
        info = await backend.create_session()
        response = await backend.send_message(info.session_id, "test")
        assert response == "Custom: test"

    @pytest.mark.asyncio
    async def test_calls_recorded(self, backend):
        info = await backend.create_session()
        await backend.send_message(info.session_id, "hi")
        await backend.end_session(info.session_id)

        methods = [c["method"] for c in backend.calls]
        assert methods == [
            "create_session",
            "send_message",
            "end_session",
        ]

    @pytest.mark.asyncio
    async def test_message_history(self, backend):
        info = await backend.create_session()
        await backend.send_message(info.session_id, "first")
        await backend.send_message(info.session_id, "second")

        history = backend.get_message_history(info.session_id)
        assert len(history) == 4  # 2 user + 2 assistant
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "first"
        assert history[1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# BridgeBackend reconnect lock tests (#20)
# ---------------------------------------------------------------------------


class TestBridgeBackendReconnectLock:
    """Verify that concurrent reconnects for the same session are serialized.

    Uses a mock bridge to track how many times resume_session is called.
    Two concurrent send_message calls for a missing session should trigger
    exactly ONE resume, not two.
    """

    @pytest.mark.asyncio
    async def test_concurrent_reconnect_calls_resume_once(self):
        """Two concurrent send_message to missing session = one reconnect."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from amplifier_distro.server.session_backend import BridgeBackend

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {}
        backend._reconnect_locks = {}

        # Mock handle that run() returns a response
        mock_handle = MagicMock()
        mock_handle.session_id = "sess-123"
        mock_handle.project_id = "test"
        mock_handle.working_dir = "~"
        mock_handle.run = AsyncMock(return_value="response")

        # Track resume calls
        resume_count = 0

        async def fake_resume(session_id, config=None):
            nonlocal resume_count
            resume_count += 1
            # Simulate slow resume (bundle load + transcript replay)
            await asyncio.sleep(0.1)
            return mock_handle

        backend._bridge = MagicMock()
        backend._bridge.resume_session = AsyncMock(side_effect=fake_resume)

        # Fire two concurrent send_message calls
        results = await asyncio.gather(
            backend.send_message("sess-123", "hello"),
            backend.send_message("sess-123", "world"),
        )

        # Both should succeed
        assert results[0] == "response"
        assert results[1] == "response"

        # But resume should only be called ONCE
        assert resume_count == 1, (
            f"Expected 1 reconnect, got {resume_count}. "
            "The per-session lock should prevent duplicate reconnects."
        )

    @pytest.mark.asyncio
    async def test_cached_session_bypasses_lock(self):
        """Normal send_message with cached handle doesn't touch locks."""
        from unittest.mock import AsyncMock, MagicMock

        from amplifier_distro.server.session_backend import BridgeBackend

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._reconnect_locks = {}

        mock_handle = MagicMock()
        mock_handle.run = AsyncMock(return_value="cached response")

        backend._sessions = {"sess-456": mock_handle}
        backend._bridge = MagicMock()

        result = await backend.send_message("sess-456", "hi")
        assert result == "cached response"

        # Bridge should never be called (no reconnect needed)
        backend._bridge.resume_session.assert_not_called()
        # No locks should have been created
        assert len(backend._reconnect_locks) == 0

    @pytest.mark.asyncio
    async def test_different_sessions_reconnect_independently(self):
        """Two different missing sessions reconnect in parallel (no blocking)."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from amplifier_distro.server.session_backend import BridgeBackend

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {}
        backend._reconnect_locks = {}

        handles = {}
        resume_count = 0

        async def fake_resume(session_id, config=None):
            nonlocal resume_count
            resume_count += 1
            await asyncio.sleep(0.05)
            h = MagicMock()
            h.session_id = session_id
            h.project_id = "test"
            h.working_dir = "~"
            h.run = AsyncMock(return_value=f"response-{session_id}")
            handles[session_id] = h
            return h

        backend._bridge = MagicMock()
        backend._bridge.resume_session = AsyncMock(side_effect=fake_resume)

        results = await asyncio.gather(
            backend.send_message("sess-A", "hello"),
            backend.send_message("sess-B", "world"),
        )

        assert results[0] == "response-sess-A"
        assert results[1] == "response-sess-B"
        # Both sessions should reconnect (different session IDs)
        assert resume_count == 2

    @pytest.mark.asyncio
    async def test_lock_cleaned_up_after_successful_reconnect(self):
        """Lock entry is removed after successful reconnect."""
        from unittest.mock import AsyncMock, MagicMock

        from amplifier_distro.server.session_backend import BridgeBackend

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {}
        backend._reconnect_locks = {}

        mock_handle = MagicMock()
        mock_handle.session_id = "sess-cleanup"
        mock_handle.project_id = "test"
        mock_handle.working_dir = "~"
        mock_handle.run = AsyncMock(return_value="ok")

        backend._bridge = MagicMock()
        backend._bridge.resume_session = AsyncMock(return_value=mock_handle)

        await backend.send_message("sess-cleanup", "hi")

        # Lock should be cleaned up after successful reconnect
        assert "sess-cleanup" not in backend._reconnect_locks

    @pytest.mark.asyncio
    async def test_reconnect_failure_cleans_up_lock(self):
        """Lock entry is removed even when reconnect fails."""
        from unittest.mock import AsyncMock, MagicMock

        from amplifier_distro.server.session_backend import BridgeBackend

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {}
        backend._reconnect_locks = {}

        backend._bridge = MagicMock()
        backend._bridge.resume_session = AsyncMock(
            side_effect=FileNotFoundError("session dir gone")
        )

        with pytest.raises(ValueError, match="Unknown session"):
            await backend.send_message("sess-gone", "hello")

        # Lock should be cleaned up even on failure
        assert "sess-gone" not in backend._reconnect_locks

    @pytest.mark.asyncio
    async def test_reconnect_failure_does_not_deadlock_retry(self):
        """After failed reconnect, a retry can proceed (not deadlocked)."""
        from unittest.mock import AsyncMock, MagicMock

        from amplifier_distro.server.session_backend import BridgeBackend

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {}
        backend._reconnect_locks = {}

        call_count = 0

        mock_handle = MagicMock()
        mock_handle.session_id = "sess-retry"
        mock_handle.project_id = "test"
        mock_handle.working_dir = "~"
        mock_handle.run = AsyncMock(return_value="recovered")

        async def fail_then_succeed(session_id, config=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("bridge temporarily down")
            return mock_handle

        backend._bridge = MagicMock()
        backend._bridge.resume_session = AsyncMock(side_effect=fail_then_succeed)

        # First call fails
        with pytest.raises(ValueError):
            await backend.send_message("sess-retry", "attempt 1")

        # Second call should succeed (not deadlocked by stale lock)
        result = await backend.send_message("sess-retry", "attempt 2")
        assert result == "recovered"
        assert call_count == 2
