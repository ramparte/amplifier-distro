"""Chat App Acceptance Tests — Skeleton"""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from starlette.testclient import TestClient

from amplifier_distro.server.app import AppManifest, DistroServer
from amplifier_distro.server.services import init_services, reset_services


@pytest.fixture(autouse=True)
def _clean_services():
    reset_services()
    yield
    reset_services()


@pytest.fixture
def chat_client() -> TestClient:
    init_services(dev_mode=True)
    from amplifier_distro.server.apps.chat import manifest

    server = DistroServer()
    server.register_app(manifest)
    return TestClient(server.app)


class TestChatManifest:
    def test_manifest_name_is_chat(self):
        from amplifier_distro.server.apps.chat import manifest

        assert manifest.name == "chat"

    def test_manifest_has_router(self):
        from amplifier_distro.server.apps.chat import manifest

        assert isinstance(manifest.router, APIRouter)

    def test_manifest_is_app_manifest_type(self):
        from amplifier_distro.server.apps.chat import manifest

        assert isinstance(manifest, AppManifest)


class TestChatIndexEndpoint:
    def test_index_returns_200(self, chat_client):
        r = chat_client.get("/apps/chat/")
        assert r.status_code == 200

    def test_index_returns_html(self, chat_client):
        r = chat_client.get("/apps/chat/")
        assert "text/html" in r.headers["content-type"]

    def test_index_contains_amplifier(self, chat_client):
        r = chat_client.get("/apps/chat/")
        assert "Amplifier" in r.text


class TestChatHealthEndpoint:
    def test_health_returns_ok(self, chat_client):
        r = chat_client.get("/apps/chat/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestChatVendorEndpoint:
    def test_vendor_js_returns_404_when_absent(self, chat_client):
        r = chat_client.get("/apps/chat/vendor.js")
        assert r.status_code == 404

    def test_vendor_js_is_javascript_when_absent(self, chat_client):
        r = chat_client.get("/apps/chat/vendor.js")
        assert "javascript" in r.headers["content-type"]

    @pytest.mark.skip(reason="vendor.js built in Task 14")
    def test_vendor_js_returns_200(self, chat_client):
        r = chat_client.get("/apps/chat/vendor.js")
        assert r.status_code == 200

    @pytest.mark.skip(reason="vendor.js built in Task 14")
    def test_vendor_js_content_type(self, chat_client):
        r = chat_client.get("/apps/chat/vendor.js")
        assert "javascript" in r.headers["content-type"]


class TestChatWebSocketEndpoint:
    def test_websocket_accepts_connection(self, chat_client):
        """WebSocket at /apps/chat/ws accepts connections."""
        with chat_client.websocket_connect("/apps/chat/ws") as ws:
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"

    def test_websocket_create_session(self, chat_client):
        """create_session message returns session_created."""
        with chat_client.websocket_connect("/apps/chat/ws") as ws:
            ws.send_json(
                {
                    "type": "create_session",
                    "cwd": "~",
                    "bundle": None,
                }
            )
            msg = ws.receive_json()
            assert msg["type"] == "session_created"
            assert isinstance(msg["session_id"], str) and msg["session_id"]
