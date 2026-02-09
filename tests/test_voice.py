"""Voice App Acceptance Tests

These tests validate the voice app placeholder which provides
WebSocket-based voice interaction scaffolding.

Exit criteria verified:
1. Manifest has correct name, description, and router
2. Index endpoint serves HTML placeholder page
3. Status endpoint reports placeholder state
4. WebSocket endpoint accepts connections and responds
5. Server discovers the voice app
"""

import pytest
from fastapi import APIRouter
from starlette.testclient import TestClient

from amplifier_distro.server.app import AppManifest, DistroServer


@pytest.fixture
def voice_client() -> TestClient:
    """Create a TestClient with the voice app registered."""
    from amplifier_distro.server.apps.voice import manifest

    server = DistroServer()
    server.register_app(manifest)
    return TestClient(server.app)


class TestVoiceManifest:
    """Verify the voice manifest has correct structure."""

    def test_manifest_name_is_voice(self):
        from amplifier_distro.server.apps.voice import manifest

        assert manifest.name == "voice"

    def test_manifest_has_router(self):
        from amplifier_distro.server.apps.voice import manifest

        assert manifest.router is not None
        assert isinstance(manifest.router, APIRouter)

    def test_manifest_has_description(self):
        from amplifier_distro.server.apps.voice import manifest

        assert isinstance(manifest.description, str)
        assert len(manifest.description) > 0

    def test_manifest_is_app_manifest_type(self):
        from amplifier_distro.server.apps.voice import manifest

        assert isinstance(manifest, AppManifest)


class TestVoiceIndexEndpoint:
    """Verify GET /apps/voice/ serves the placeholder page."""

    def test_index_returns_200(self, voice_client: TestClient):
        response = voice_client.get("/apps/voice/")
        assert response.status_code == 200

    def test_index_returns_html(self, voice_client: TestClient):
        response = voice_client.get("/apps/voice/")
        assert "text/html" in response.headers["content-type"]

    def test_index_contains_amplifier_title(self, voice_client: TestClient):
        response = voice_client.get("/apps/voice/")
        assert "Amplifier Voice" in response.text

    def test_index_mentions_not_implemented(self, voice_client: TestClient):
        response = voice_client.get("/apps/voice/")
        assert "not yet implemented" in response.text


class TestVoiceStatusEndpoint:
    """Verify GET /apps/voice/api/status returns service info."""

    def test_status_returns_200(self, voice_client: TestClient):
        response = voice_client.get("/apps/voice/api/status")
        assert response.status_code == 200

    def test_status_reports_placeholder(self, voice_client: TestClient):
        data = voice_client.get("/apps/voice/api/status").json()
        assert data["status"] == "placeholder"

    def test_status_includes_websocket_endpoint(self, voice_client: TestClient):
        data = voice_client.get("/apps/voice/api/status").json()
        assert "websocket_endpoint" in data

    def test_status_includes_provider_info(self, voice_client: TestClient):
        data = voice_client.get("/apps/voice/api/status").json()
        assert "stt_provider" in data
        assert "tts_provider" in data


class TestVoiceWebSocket:
    """Verify the WebSocket endpoint accepts connections."""

    def test_websocket_connects(self, voice_client: TestClient):
        with voice_client.websocket_connect("/apps/voice/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "status"
            assert "connected" in data["message"].lower()

    def test_websocket_start_message(self, voice_client: TestClient):
        with voice_client.websocket_connect("/apps/voice/ws") as ws:
            # Consume initial status
            ws.receive_json()
            # Send start
            ws.send_json({"type": "start", "session_id": "test-123"})
            data = ws.receive_json()
            assert data["type"] == "status"
            assert data["session_id"] == "test-123"

    def test_websocket_audio_placeholder(self, voice_client: TestClient):
        with voice_client.websocket_connect("/apps/voice/ws") as ws:
            ws.receive_json()  # initial status
            ws.send_json({"type": "audio", "data": "base64data"})
            data = ws.receive_json()
            assert data["type"] == "status"
            assert "not implemented" in data["message"].lower()

    def test_websocket_end_message(self, voice_client: TestClient):
        with voice_client.websocket_connect("/apps/voice/ws") as ws:
            ws.receive_json()  # initial status
            ws.send_json({"type": "end"})
            data = ws.receive_json()
            assert data["type"] == "status"
            assert "ended" in data["message"].lower()

    def test_websocket_unknown_type(self, voice_client: TestClient):
        with voice_client.websocket_connect("/apps/voice/ws") as ws:
            ws.receive_json()  # initial status
            ws.send_json({"type": "bogus"})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "bogus" in data["message"]
