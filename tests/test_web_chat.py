"""Web Chat App Acceptance Tests

These tests validate the web-chat server app which serves a
self-contained chat UI and provides API endpoints.

Exit criteria verified:
1. Manifest has correct name, description, and router
2. Index endpoint serves HTML chat interface
3. API session endpoint returns connection status
4. API chat endpoint accepts messages and returns responses
5. Server discovers both web-chat and install-wizard apps
"""

from pathlib import Path

import pytest
from fastapi import APIRouter
from starlette.testclient import TestClient

from amplifier_distro.server.app import AppManifest, DistroServer


@pytest.fixture
def webchat_client() -> TestClient:
    """Create a TestClient with the web-chat app registered."""
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
        assert "/static/settings.html" in response.text

    def test_index_contains_message_input(self, webchat_client: TestClient):
        response = webchat_client.get("/apps/web-chat/")
        assert "messageInput" in response.text


class TestWebChatSessionAPI:
    """Verify GET /apps/web-chat/api/session returns status."""

    def test_session_returns_200(self, webchat_client: TestClient):
        response = webchat_client.get("/apps/web-chat/api/session")
        assert response.status_code == 200

    def test_session_returns_connected_bool(self, webchat_client: TestClient):
        data = webchat_client.get("/apps/web-chat/api/session").json()
        assert "connected" in data
        assert isinstance(data["connected"], bool)

    def test_session_not_connected_by_default(self, webchat_client: TestClient):
        data = webchat_client.get("/apps/web-chat/api/session").json()
        assert data["connected"] is False

    def test_session_returns_message(self, webchat_client: TestClient):
        data = webchat_client.get("/apps/web-chat/api/session").json()
        assert "message" in data
        assert len(data["message"]) > 0


class TestWebChatChatAPI:
    """Verify POST /apps/web-chat/api/chat accepts messages.

    Antagonist note: Even without a connected session, the chat
    endpoint must accept messages and return a well-formed response
    so the UI can display feedback.
    """

    def test_chat_returns_200(self, webchat_client: TestClient):
        response = webchat_client.post(
            "/apps/web-chat/api/chat",
            json={"message": "hello"},
        )
        assert response.status_code == 200

    def test_chat_returns_response_text(self, webchat_client: TestClient):
        data = webchat_client.post(
            "/apps/web-chat/api/chat",
            json={"message": "hello"},
        ).json()
        assert "response" in data
        assert isinstance(data["response"], str)
        assert len(data["response"]) > 0

    def test_chat_echoes_message(self, webchat_client: TestClient):
        data = webchat_client.post(
            "/apps/web-chat/api/chat",
            json={"message": "test message"},
        ).json()
        assert data.get("echo") == "test message"

    def test_chat_reports_session_not_connected(self, webchat_client: TestClient):
        data = webchat_client.post(
            "/apps/web-chat/api/chat",
            json={"message": "hello"},
        ).json()
        assert data.get("session_connected") is False


class TestAppDiscovery:
    """Verify the server discovers apps from the apps directory.

    Antagonist note: Both web-chat and install-wizard must be
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

    def test_both_apps_accessible_via_http(self):
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

        # install-wizard has no index route; /status is the canonical endpoint
        wiz = client.get("/apps/install-wizard/status")
        assert wiz.status_code == 200

        chat = client.get("/apps/web-chat/")
        assert chat.status_code == 200
