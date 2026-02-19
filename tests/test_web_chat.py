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


@pytest.fixture(autouse=True)
def _reset_web_chat_manager():
    """Reset the _manager singleton between every test to prevent bleed."""
    import amplifier_distro.server.apps.web_chat as wc

    wc._manager = None
    yield
    wc._manager = None


@pytest.fixture
def webchat_client() -> TestClient:
    """Create a TestClient with web-chat app and services initialized."""
    import amplifier_distro.server.apps.web_chat as wc
    from amplifier_distro.server.apps.web_chat import WebChatSessionManager
    from amplifier_distro.server.services import get_services

    init_services(dev_mode=True)

    # Pre-create manager with no persistence for test isolation.
    # _get_manager() uses the real filesystem path; we override it here so
    # each test gets a clean in-memory store that never touches disk.
    wc._manager = WebChatSessionManager(
        get_services().backend,
        persistence_path=None,
    )

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

    Guards the ValueError path: when the backend confirms a session is dead,
    the manager deactivates the store entry and the route returns 409.
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


class TestWebChatSessionsListAPI:
    """Verify GET /apps/web-chat/api/sessions endpoint."""

    def test_list_sessions_returns_200(self, webchat_client: TestClient):
        response = webchat_client.get("/apps/web-chat/api/sessions")
        assert response.status_code == 200

    def test_list_sessions_empty_by_default(self, webchat_client: TestClient):
        data = webchat_client.get("/apps/web-chat/api/sessions").json()
        assert data["sessions"] == []

    def test_list_sessions_includes_created_session(self, webchat_client: TestClient):
        webchat_client.post(
            "/apps/web-chat/api/session",
            json={"description": "my test session"},
        )
        data = webchat_client.get("/apps/web-chat/api/sessions").json()
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["description"] == "my test session"

    def test_list_sessions_entry_has_required_fields(self, webchat_client: TestClient):
        webchat_client.post("/apps/web-chat/api/session", json={})
        sessions = webchat_client.get("/apps/web-chat/api/sessions").json()["sessions"]
        s = sessions[0]
        assert "session_id" in s
        assert "description" in s
        assert "created_at" in s
        assert "last_active" in s
        assert "is_active" in s
        assert "project_id" in s

    def test_list_sessions_active_flag_is_true_for_current(
        self, webchat_client: TestClient
    ):
        webchat_client.post("/apps/web-chat/api/session", json={})
        sessions = webchat_client.get("/apps/web-chat/api/sessions").json()["sessions"]
        assert sessions[0]["is_active"] is True

    def test_list_sessions_shows_both_active_and_inactive(
        self, webchat_client: TestClient
    ):
        # Create first session
        webchat_client.post("/apps/web-chat/api/session", json={"description": "first"})
        # Create second session — automatically deactivates first
        webchat_client.post(
            "/apps/web-chat/api/session", json={"description": "second"}
        )
        sessions = webchat_client.get("/apps/web-chat/api/sessions").json()["sessions"]
        assert len(sessions) == 2
        active = [s for s in sessions if s["is_active"]]
        inactive = [s for s in sessions if not s["is_active"]]
        assert len(active) == 1
        assert len(inactive) == 1
        assert sessions[0]["description"] == "second"  # most recently active first

    def test_list_sessions_project_id_field_is_present(
        self, webchat_client: TestClient
    ):
        webchat_client.post("/apps/web-chat/api/session", json={})
        sessions = webchat_client.get("/apps/web-chat/api/sessions").json()["sessions"]
        # project_id should be a string (may be empty for unknown sessions)
        assert isinstance(sessions[0]["project_id"], str)
