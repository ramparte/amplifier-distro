"""Web Chat App Acceptance Tests

These tests validate the web-chat server app which serves a
self-contained chat UI and provides API endpoints backed by the
shared server session backend.

Exit criteria verified:
1. Manifest has correct name, description, and router
2. Index endpoint serves HTML chat interface
3. Session status reports not-connected before session creation
4. Session creation works via POST /api/session
5. Chat endpoint sends messages through the backend
6. Chat endpoint rejects messages when no session exists
7. End session endpoint works
8. Server discovers web-chat app
"""

from pathlib import Path

import pytest
from fastapi import APIRouter
from starlette.testclient import TestClient

from amplifier_distro.server.app import AppManifest, DistroServer
from amplifier_distro.server.services import (
    init_services,
    reset_services,
)


@pytest.fixture(autouse=True)
def _clean_services():
    """Ensure services are reset between tests."""
    reset_services()
    yield
    reset_services()


@pytest.fixture
def webchat_client() -> TestClient:
    """Create a TestClient with web-chat app and services initialized."""
    import asyncio

    import amplifier_distro.server.apps.web_chat as wc

    wc._active_session_id = None
    wc._session_lock = asyncio.Lock()
    wc._message_in_flight = False

    init_services(dev_mode=True)

    from amplifier_distro.server.apps.web_chat import manifest

    server = DistroServer()
    server.register_app(manifest)
    return TestClient(server.app)


class TestWebChatManifest:
    """Verify the web-chat manifest has correct structure.

    Antagonist note: The manifest is the contract between the web-chat
    app and the distro server. It must expose the correct name and a
    working router for route mounting.
    """

    def test_manifest_name_is_web_chat(self):
        from amplifier_distro.server.apps.web_chat import manifest

        assert manifest.name == "web-chat"

    def test_manifest_has_router(self):
        from amplifier_distro.server.apps.web_chat import manifest

        assert manifest.router is not None
        assert isinstance(manifest.router, APIRouter)

    def test_manifest_has_description(self):
        from amplifier_distro.server.apps.web_chat import manifest

        assert isinstance(manifest.description, str)
        assert len(manifest.description) > 0

    def test_manifest_is_app_manifest_type(self):
        from amplifier_distro.server.apps.web_chat import manifest

        assert isinstance(manifest, AppManifest)


class TestWebChatIndexEndpoint:
    """Verify GET /apps/web-chat/ serves the chat HTML page.

    Antagonist note: The index endpoint must serve an HTML page
    that contains the chat interface. This is the landing page
    after quickstart completes.
    """

    def test_index_returns_200(self, webchat_client: TestClient):
        response = webchat_client.get("/apps/web-chat/")
        assert response.status_code == 200

    def test_index_returns_html(self, webchat_client: TestClient):
        response = webchat_client.get("/apps/web-chat/")
        assert "text/html" in response.headers["content-type"]

    def test_index_contains_amplifier_title(self, webchat_client: TestClient):
        response = webchat_client.get("/apps/web-chat/")
        assert "Amplifier" in response.text

    def test_index_contains_chat_area(self, webchat_client: TestClient):
        response = webchat_client.get("/apps/web-chat/")
        assert "chatArea" in response.text

    def test_index_contains_settings_link(self, webchat_client: TestClient):
        response = webchat_client.get("/apps/web-chat/")
        assert "/apps/settings/" in response.text

    def test_index_contains_message_input(self, webchat_client: TestClient):
        response = webchat_client.get("/apps/web-chat/")
        assert "messageInput" in response.text


class TestWebChatSessionAPI:
    """Verify session management endpoints."""

    def test_session_status_returns_200(self, webchat_client: TestClient):
        response = webchat_client.get("/apps/web-chat/api/session")
        assert response.status_code == 200

    def test_session_status_not_connected_by_default(self, webchat_client: TestClient):
        data = webchat_client.get("/apps/web-chat/api/session").json()
        assert data["connected"] is False

    def test_session_status_has_message(self, webchat_client: TestClient):
        data = webchat_client.get("/apps/web-chat/api/session").json()
        assert "message" in data
        assert len(data["message"]) > 0

    def test_create_session(self, webchat_client: TestClient):
        response = webchat_client.post(
            "/apps/web-chat/api/session",
            json={"working_dir": "/tmp"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert data["session_id"].startswith("mock-session-")

    def test_session_status_connected_after_create(self, webchat_client: TestClient):
        webchat_client.post("/apps/web-chat/api/session", json={})
        data = webchat_client.get("/apps/web-chat/api/session").json()
        assert data["connected"] is True
        assert data["session_id"] is not None


class TestWebChatChatAPI:
    """Verify POST /apps/web-chat/api/chat with backend integration.

    Antagonist note: The chat endpoint requires an active session.
    Without a session, it returns 409. With a session, messages
    go through the shared backend.
    """

    def test_chat_without_session_returns_409(self, webchat_client: TestClient):
        response = webchat_client.post(
            "/apps/web-chat/api/chat",
            json={"message": "hello"},
        )
        assert response.status_code == 409
        data = response.json()
        assert data["session_connected"] is False

    def test_chat_empty_message_returns_400(self, webchat_client: TestClient):
        response = webchat_client.post(
            "/apps/web-chat/api/chat",
            json={"message": ""},
        )
        assert response.status_code == 400

    def test_chat_with_session_returns_response(self, webchat_client: TestClient):
        # Create session first
        webchat_client.post("/apps/web-chat/api/session", json={})
        # Now chat
        response = webchat_client.post(
            "/apps/web-chat/api/chat",
            json={"message": "hello"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert isinstance(data["response"], str)
        assert len(data["response"]) > 0
        assert data["session_connected"] is True

    def test_chat_response_contains_original_message(self, webchat_client: TestClient):
        """MockBackend echoes the message back."""
        webchat_client.post("/apps/web-chat/api/session", json={})
        data = webchat_client.post(
            "/apps/web-chat/api/chat",
            json={"message": "test message"},
        ).json()
        assert "test message" in data["response"]


class TestWebChatEndSession:
    """Verify POST /apps/web-chat/api/end endpoint."""

    def test_end_without_session(self, webchat_client: TestClient):
        response = webchat_client.post("/apps/web-chat/api/end")
        assert response.status_code == 200
        data = response.json()
        assert data["ended"] is False

    def test_end_with_session(self, webchat_client: TestClient):
        # Create and then end
        create = webchat_client.post("/apps/web-chat/api/session", json={}).json()
        response = webchat_client.post("/apps/web-chat/api/end")
        assert response.status_code == 200
        data = response.json()
        assert data["ended"] is True
        assert data["session_id"] == create["session_id"]

    def test_session_disconnected_after_end(self, webchat_client: TestClient):
        webchat_client.post("/apps/web-chat/api/session", json={})
        webchat_client.post("/apps/web-chat/api/end")
        data = webchat_client.get("/apps/web-chat/api/session").json()
        assert data["connected"] is False


class TestAppDiscovery:
    """Verify the server discovers apps from the apps directory.

    Antagonist note: web-chat and install-wizard must be
    discoverable from the apps directory so the server can
    auto-register them at startup.
    """

    def test_discover_finds_install_wizard(self):
        apps_dir = (
            Path(__file__).parent.parent
            / "src"
            / "amplifier_distro"
            / "server"
            / "apps"
        )
        server = DistroServer()
        found = server.discover_apps(apps_dir)
        assert "install-wizard" in found

    def test_discover_finds_web_chat(self):
        apps_dir = (
            Path(__file__).parent.parent
            / "src"
            / "amplifier_distro"
            / "server"
            / "apps"
        )
        server = DistroServer()
        found = server.discover_apps(apps_dir)
        assert "web-chat" in found

    def test_discover_finds_voice(self):
        apps_dir = (
            Path(__file__).parent.parent
            / "src"
            / "amplifier_distro"
            / "server"
            / "apps"
        )
        server = DistroServer()
        found = server.discover_apps(apps_dir)
        assert "voice" in found

    def test_both_apps_mount_at_expected_paths(self):
        apps_dir = (
            Path(__file__).parent.parent
            / "src"
            / "amplifier_distro"
            / "server"
            / "apps"
        )
        server = DistroServer()
        server.discover_apps(apps_dir)
        assert server.apps["install-wizard"].mount_path == "/apps/install-wizard"
        assert server.apps["web-chat"].mount_path == "/apps/web-chat"
        assert server.apps["voice"].mount_path == "/apps/voice"

    def test_apps_accessible_via_http(self):
        apps_dir = (
            Path(__file__).parent.parent
            / "src"
            / "amplifier_distro"
            / "server"
            / "apps"
        )
        server = DistroServer()
        server.discover_apps(apps_dir)
        client = TestClient(server.app)

        # install-wizard quickstart page
        wiz = client.get("/apps/install-wizard/")
        assert wiz.status_code == 200

        chat = client.get("/apps/web-chat/")
        assert chat.status_code == 200

        voice = client.get("/apps/voice/")
        assert voice.status_code == 200


class TestWebChatSessionLifecycle:
    """Test the full create -> end -> chat lifecycle.

    Web Chat correctly clears _active_session_id on ValueError (line 297-299
    of web_chat/__init__.py). These tests document and guard that behavior.
    """

    def test_chat_after_end_returns_409(self, webchat_client: TestClient):
        """Chat after ending session returns 409 (no active session)."""
        # Create session
        webchat_client.post("/apps/web-chat/api/session", json={})
        # End it
        webchat_client.post("/apps/web-chat/api/end")
        # Chat should fail with 409
        response = webchat_client.post(
            "/apps/web-chat/api/chat",
            json={"message": "hello after end"},
        )
        assert response.status_code == 409
        data = response.json()
        assert data["session_connected"] is False

    def test_chat_valueerror_clears_session(self, webchat_client: TestClient):
        """When backend.send_message raises ValueError, session is cleared.

        This is the Web Chat equivalent of the Slack zombie fix -- it already
        works correctly. This test guards against regression.
        """
        from amplifier_distro.server.services import get_services
        from amplifier_distro.server.session_backend import MockBackend

        # Create session
        create_resp = webchat_client.post("/apps/web-chat/api/session", json={})
        session_id = create_resp.json()["session_id"]

        # Mark the session as inactive on the backend (simulates lost handle).
        # This is sync-safe: MockBackend has no loop-bound state, so direct
        # mutation avoids asyncio.run() conflicts with TestClient's event loop.
        backend = get_services().backend
        assert isinstance(backend, MockBackend)
        backend._sessions[session_id].is_active = False

        # Chat should get 409 because ValueError triggers session cleanup
        response = webchat_client.post(
            "/apps/web-chat/api/chat",
            json={"message": "hello to dead session"},
        )
        assert response.status_code == 409
        data = response.json()
        assert data["session_connected"] is False

        # Verify session status also shows disconnected
        status = webchat_client.get("/apps/web-chat/api/session").json()
        assert status["connected"] is False


class TestWebChatConcurrency:
    """Verify concurrent request behaviour after lock narrowing.

    These tests use httpx.AsyncClient (async_webchat_client fixture)
    because starlette.testclient.TestClient runs requests in a thread
    and cannot produce true asyncio concurrency.
    """

    async def test_in_flight_guard_rejects_concurrent_chat(self, async_webchat_client):
        """While a chat is in-flight a second chat returns 409."""
        from unittest.mock import AsyncMock, patch

        await async_webchat_client.post("/apps/web-chat/api/session", json={})

        async def slow_send(session_id, message):
            import asyncio

            await asyncio.sleep(0.05)
            return f"[response: {message}]"

        with patch(
            "amplifier_distro.server.apps.web_chat._get_backend"
        ) as mock_get_backend:
            mock_get_backend.return_value = AsyncMock(send_message=slow_send)

            import asyncio

            r1, r2 = await asyncio.gather(
                async_webchat_client.post(
                    "/apps/web-chat/api/chat", json={"message": "first"}
                ),
                async_webchat_client.post(
                    "/apps/web-chat/api/chat", json={"message": "second"}
                ),
            )

        codes = sorted([r1.status_code, r2.status_code])
        assert codes == [200, 409], f"Expected [200, 409], got {codes}"
        resp_409 = r1 if r1.status_code == 409 else r2
        assert (
            "in_flight" in resp_409.json().get("error", "").lower()
            or resp_409.json().get("in_flight") is True
        )

    async def test_chat_succeeds_after_in_flight_clears(self, async_webchat_client):
        """After a chat completes, the next chat is accepted normally."""
        await async_webchat_client.post("/apps/web-chat/api/session", json={})
        r1 = await async_webchat_client.post(
            "/apps/web-chat/api/chat", json={"message": "hello"}
        )
        assert r1.status_code == 200

        r2 = await async_webchat_client.post(
            "/apps/web-chat/api/chat", json={"message": "world"}
        )
        assert r2.status_code == 200

    async def test_session_id_cleared_under_lock_on_value_error(
        self, async_webchat_client
    ):
        """When send_message raises ValueError, _active_session_id is cleared safely."""
        from unittest.mock import AsyncMock, patch

        await async_webchat_client.post("/apps/web-chat/api/session", json={})

        async def failing_send(session_id, message):
            raise ValueError("Unknown session")

        with patch(
            "amplifier_distro.server.apps.web_chat._get_backend"
        ) as mock_get_backend:
            mock_get_backend.return_value = AsyncMock(send_message=failing_send)
            r = await async_webchat_client.post(
                "/apps/web-chat/api/chat", json={"message": "hello"}
            )

        assert r.status_code == 409
        assert r.json()["session_connected"] is False

        # Session should now be cleared
        status = await async_webchat_client.get("/apps/web-chat/api/session")
        assert status.json()["connected"] is False

    async def test_session_status_does_not_block_concurrent_chat(
        self, async_webchat_client
    ):
        """session_status() must not hold _session_lock during backend I/O."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        await async_webchat_client.post("/apps/web-chat/api/session", json={})

        async def slow_get_info(session_id):
            await asyncio.sleep(0.05)
            from amplifier_distro.server.session_backend import SessionInfo

            return SessionInfo(session_id=session_id, is_active=True)

        with patch(
            "amplifier_distro.server.apps.web_chat._get_backend"
        ) as mock_get_backend:
            mock_backend = AsyncMock()
            mock_backend.get_session_info = slow_get_info
            mock_backend.send_message = AsyncMock(return_value="ok")
            mock_get_backend.return_value = mock_backend

            r_status, r_chat = await asyncio.gather(
                async_webchat_client.get("/apps/web-chat/api/session"),
                async_webchat_client.post(
                    "/apps/web-chat/api/chat", json={"message": "hi"}
                ),
            )

        # Both should complete — neither should time out or deadlock
        assert r_status.status_code == 200
        assert r_chat.status_code in (200, 409)  # 409 if in-flight guard fires

    async def test_new_session_not_clobbered_when_old_session_errors(
        self, async_webchat_client
    ):
        """create_session() while chat() ValueError path runs must not lose the new session."""
        from unittest.mock import patch, AsyncMock
        import asyncio
        import amplifier_distro.server.apps.web_chat as wc

        # Create initial session
        r = await async_webchat_client.post("/apps/web-chat/api/session", json={})
        original_session_id = r.json()["session_id"]

        new_session_id = "new-session-after-error"

        created_new_session = asyncio.Event()
        backend_called = asyncio.Event()

        async def failing_send(session_id, message):
            # Signal that we're in send_message, let create_session run first
            backend_called.set()
            await created_new_session.wait()
            raise ValueError("Unknown session")

        async def mock_create(working_dir, description):
            from amplifier_distro.server.session_backend import SessionInfo
            return SessionInfo(
                session_id=new_session_id,
                project_id="test",
                working_dir="/tmp",
                is_active=True,
            )

        mock_backend = AsyncMock()
        mock_backend.send_message = failing_send
        mock_backend.create_session = mock_create
        mock_backend.end_session = AsyncMock()

        with patch("amplifier_distro.server.apps.web_chat._get_backend", return_value=mock_backend):
            # Start chat (will block at backend_called.set())
            chat_task = asyncio.create_task(
                async_webchat_client.post("/apps/web-chat/api/chat", json={"message": "hi"})
            )
            # Wait until send_message is running, then create a new session
            await backend_called.wait()
            await async_webchat_client.post("/apps/web-chat/api/session", json={})
            created_new_session.set()
            await chat_task

        # New session must still be active
        assert wc._active_session_id == new_session_id, (
            f"New session was clobbered! Got: {wc._active_session_id}"
        )

    async def test_session_status_handles_unexpected_backend_error(
        self, async_webchat_client
    ):
        """session_status() must return connected:False, not 500, on unexpected errors."""
        from unittest.mock import patch, AsyncMock

        await async_webchat_client.post("/apps/web-chat/api/session", json={})

        async def exploding_get_info(session_id):
            raise OSError("Connection refused")

        mock_backend = AsyncMock()
        mock_backend.get_session_info = exploding_get_info
        with patch("amplifier_distro.server.apps.web_chat._get_backend", return_value=mock_backend):
            r = await async_webchat_client.get("/apps/web-chat/api/session")

        assert r.status_code == 200   # not 500
        assert r.json()["connected"] is False
