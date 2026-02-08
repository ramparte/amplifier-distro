"""Web Chat App Acceptance Tests

These tests validate the web-chat server app which wraps
the amplifier-web interface.

Exit criteria verified:
1. Manifest has correct name, description, and router
2. Index endpoint returns status (available or not_installed)
3. Status endpoint returns availability boolean
4. When amplifier-web is not installed, response includes install hint
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
    """Verify GET /apps/web-chat/ returns status.

    Antagonist note: The index endpoint must always return a valid
    status regardless of whether amplifier-web is installed. The
    status field is the key discriminator.
    """

    def test_index_returns_200(self, webchat_client: TestClient):
        response = webchat_client.get("/apps/web-chat/")
        assert response.status_code == 200

    def test_index_returns_app_name(self, webchat_client: TestClient):
        data = webchat_client.get("/apps/web-chat/").json()
        assert data["app"] == "web-chat"

    def test_index_returns_valid_status(self, webchat_client: TestClient):
        data = webchat_client.get("/apps/web-chat/").json()
        assert data["status"] in ("available", "not_installed")

    def test_index_returns_message(self, webchat_client: TestClient):
        data = webchat_client.get("/apps/web-chat/").json()
        assert "message" in data
        assert len(data["message"]) > 0


class TestWebChatStatusEndpoint:
    """Verify GET /apps/web-chat/status returns availability."""

    def test_status_returns_200(self, webchat_client: TestClient):
        response = webchat_client.get("/apps/web-chat/status")
        assert response.status_code == 200

    def test_status_returns_available_bool(self, webchat_client: TestClient):
        data = webchat_client.get("/apps/web-chat/status").json()
        assert "available" in data
        assert isinstance(data["available"], bool)


class TestWebChatNotInstalled:
    """Verify behavior when amplifier-web is not installed.

    Antagonist note: In test environments, amplifier-web is typically
    not installed. The app must gracefully handle this and provide
    clear installation instructions.
    """

    def test_not_installed_includes_install_hint(self, webchat_client: TestClient):
        """When amplifier-web is not installed, install_hint should be present."""
        from amplifier_distro.server.apps.web_chat import _web_available

        if _web_available:
            pytest.skip("amplifier-web is installed; cannot test not_installed path")
        data = webchat_client.get("/apps/web-chat/").json()
        assert data["status"] == "not_installed"
        assert "install_hint" in data

    def test_not_installed_status_is_false(self, webchat_client: TestClient):
        from amplifier_distro.server.apps.web_chat import _web_available

        if _web_available:
            pytest.skip("amplifier-web is installed; cannot test not_installed path")
        data = webchat_client.get("/apps/web-chat/status").json()
        assert data["available"] is False


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

        wiz = client.get("/apps/install-wizard/")
        assert wiz.status_code == 200

        chat = client.get("/apps/web-chat/")
        assert chat.status_code == 200
