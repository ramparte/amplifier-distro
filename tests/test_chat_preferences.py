"""Tests for GET/PUT /api/preferences."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from amplifier_distro.server.app import DistroServer
from amplifier_distro.server.services import init_services, reset_services


@pytest.fixture(autouse=True)
def _clean():
    reset_services()
    yield
    reset_services()


@pytest.fixture
def chat_client(tmp_path) -> TestClient:
    init_services(dev_mode=True)
    import amplifier_distro.server.apps.chat.preferences as prefs_mod
    from amplifier_distro.server.apps.chat import manifest

    prefs_mod._PREFS_PATH = tmp_path / "chat-preferences.json"

    server = DistroServer()
    server.register_app(manifest)
    return TestClient(server.app)


class TestGetPreferences:
    def test_returns_200(self, chat_client):
        r = chat_client.get("/apps/chat/api/preferences")
        assert r.status_code == 200

    def test_returns_defaults_when_no_file(self, chat_client):
        data = chat_client.get("/apps/chat/api/preferences").json()
        assert "default_bundle" in data
        assert "default_behaviors" in data
        assert "show_thinking" in data
        assert "default_cwd" in data
        assert data["show_thinking"] is False
        assert data["default_behaviors"] == []

    def test_default_cwd_is_string(self, chat_client):
        data = chat_client.get("/apps/chat/api/preferences").json()
        assert isinstance(data["default_cwd"], str)


class TestPutPreferences:
    def test_put_updates_show_thinking(self, chat_client):
        chat_client.put("/apps/chat/api/preferences", json={"show_thinking": True})
        data = chat_client.get("/apps/chat/api/preferences").json()
        assert data["show_thinking"] is True

    def test_put_partial_update_preserves_other_fields(self, chat_client):
        chat_client.put(
            "/apps/chat/api/preferences", json={"default_bundle": "my-bundle"}
        )
        data = chat_client.get("/apps/chat/api/preferences").json()
        assert data["default_bundle"] == "my-bundle"
        assert data["show_thinking"] is False  # unchanged

    def test_put_returns_updated_prefs(self, chat_client):
        r = chat_client.put(
            "/apps/chat/api/preferences",
            json={"default_behaviors": ["web-search"]},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["default_behaviors"] == ["web-search"]
