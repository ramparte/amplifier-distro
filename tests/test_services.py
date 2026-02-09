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
