"""Voice App Tests - OpenAI Realtime API via WebRTC

These tests validate the voice app which provides:
1. Ephemeral session creation via OpenAI Realtime API
2. SDP exchange for WebRTC connection brokering
3. Voice configuration from distro.yaml
4. Status endpoint reporting service readiness

Exit criteria verified:
1. Manifest has correct name, description, and router
2. Index endpoint serves HTML voice UI page
3. Status endpoint reports configuration state
4. Session endpoint calls OpenAI and returns client_secret
5. SDP endpoint relays offer/answer via OpenAI
6. Missing API key is handled gracefully
7. VoiceConfig defaults and loading work correctly
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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


# ------------------------------------------------------------------ #
#  Manifest Tests                                                      #
# ------------------------------------------------------------------ #


class TestVoiceManifest:
    """Verify the voice manifest has correct structure."""

    def test_manifest_name_is_voice(self) -> None:
        from amplifier_distro.server.apps.voice import manifest

        assert manifest.name == "voice"

    def test_manifest_has_router(self) -> None:
        from amplifier_distro.server.apps.voice import manifest

        assert manifest.router is not None
        assert isinstance(manifest.router, APIRouter)

    def test_manifest_has_description(self) -> None:
        from amplifier_distro.server.apps.voice import manifest

        assert isinstance(manifest.description, str)
        assert len(manifest.description) > 0

    def test_manifest_is_app_manifest_type(self) -> None:
        from amplifier_distro.server.apps.voice import manifest

        assert isinstance(manifest, AppManifest)


# ------------------------------------------------------------------ #
#  Index Endpoint Tests                                                #
# ------------------------------------------------------------------ #


class TestVoiceIndexEndpoint:
    """Verify GET /apps/voice/ serves the voice UI page."""

    def test_index_returns_200(self, voice_client: TestClient) -> None:
        response = voice_client.get("/apps/voice/")
        assert response.status_code == 200

    def test_index_returns_html(self, voice_client: TestClient) -> None:
        response = voice_client.get("/apps/voice/")
        assert "text/html" in response.headers["content-type"]

    def test_index_contains_amplifier_title(self, voice_client: TestClient) -> None:
        response = voice_client.get("/apps/voice/")
        assert "Amplifier Voice" in response.text

    def test_index_contains_webrtc_code(self, voice_client: TestClient) -> None:
        response = voice_client.get("/apps/voice/")
        assert "RTCPeerConnection" in response.text

    def test_index_contains_start_button(self, voice_client: TestClient) -> None:
        response = voice_client.get("/apps/voice/")
        assert "Start Conversation" in response.text


# ------------------------------------------------------------------ #
#  Status Endpoint Tests                                               #
# ------------------------------------------------------------------ #


class TestVoiceStatusEndpoint:
    """Verify GET /apps/voice/api/status returns service info."""

    def test_status_returns_200(self, voice_client: TestClient) -> None:
        response = voice_client.get("/apps/voice/api/status")
        assert response.status_code == 200

    def test_status_includes_model(self, voice_client: TestClient) -> None:
        data = voice_client.get("/apps/voice/api/status").json()
        assert "model" in data

    def test_status_includes_voice(self, voice_client: TestClient) -> None:
        data = voice_client.get("/apps/voice/api/status").json()
        assert "voice" in data

    def test_status_includes_api_key_flag(self, voice_client: TestClient) -> None:
        data = voice_client.get("/apps/voice/api/status").json()
        assert "api_key_set" in data

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    def test_status_ready_when_key_set(self, voice_client: TestClient) -> None:
        data = voice_client.get("/apps/voice/api/status").json()
        assert data["status"] == "ready"
        assert data["api_key_set"] is True

    @patch.dict("os.environ", {}, clear=True)
    def test_status_unconfigured_when_no_key(self) -> None:
        """Without OPENAI_API_KEY, status should be unconfigured."""
        from amplifier_distro.server.apps.voice import manifest

        server = DistroServer()
        server.register_app(manifest)
        client = TestClient(server.app)
        data = client.get("/apps/voice/api/status").json()
        assert data["status"] == "unconfigured"
        assert data["api_key_set"] is False


# ------------------------------------------------------------------ #
#  Session Endpoint Tests                                              #
# ------------------------------------------------------------------ #


class TestVoiceSessionEndpoint:
    """Verify GET /apps/voice/session creates ephemeral tokens."""

    @patch.dict("os.environ", {}, clear=True)
    def test_session_returns_503_without_api_key(self) -> None:
        """Session endpoint returns 503 when OPENAI_API_KEY is missing."""
        from amplifier_distro.server.apps.voice import manifest

        server = DistroServer()
        server.register_app(manifest)
        client = TestClient(server.app)
        response = client.get("/apps/voice/session")
        assert response.status_code == 503
        data = response.json()
        assert "error" in data
        assert "OPENAI_API_KEY" in data["error"]

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    @patch("amplifier_distro.server.apps.voice.httpx.AsyncClient")
    def test_session_calls_openai(self, mock_client_cls: MagicMock) -> None:
        """Session endpoint calls OpenAI and returns the response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "client_secret": {"value": "ek_test_token", "expires_at": 9999999999},
            "model": "gpt-4o-realtime-preview",
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        from amplifier_distro.server.apps.voice import manifest

        server = DistroServer()
        server.register_app(manifest)
        client = TestClient(server.app)
        response = client.get("/apps/voice/session")

        assert response.status_code == 200
        data = response.json()
        assert "client_secret" in data
        assert data["client_secret"]["value"] == "ek_test_token"

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    @patch("amplifier_distro.server.apps.voice.httpx.AsyncClient")
    def test_session_handles_openai_error(self, mock_client_cls: MagicMock) -> None:
        """Session endpoint returns error when OpenAI rejects request."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Invalid API key"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        from amplifier_distro.server.apps.voice import manifest

        server = DistroServer()
        server.register_app(manifest)
        client = TestClient(server.app)
        response = client.get("/apps/voice/session")

        assert response.status_code == 401
        data = response.json()
        assert "error" in data

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"})
    @patch("amplifier_distro.server.apps.voice.httpx.AsyncClient")
    def test_session_handles_timeout(self, mock_client_cls: MagicMock) -> None:
        """Session endpoint returns 504 on timeout."""
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        from amplifier_distro.server.apps.voice import manifest

        server = DistroServer()
        server.register_app(manifest)
        client = TestClient(server.app)
        response = client.get("/apps/voice/session")

        assert response.status_code == 504
        data = response.json()
        assert "Timeout" in data["error"]


# ------------------------------------------------------------------ #
#  SDP Endpoint Tests                                                  #
# ------------------------------------------------------------------ #


class TestVoiceSdpEndpoint:
    """Verify POST /apps/voice/sdp exchanges SDP with OpenAI."""

    def test_sdp_requires_authorization(self, voice_client: TestClient) -> None:
        """SDP endpoint returns 401 without Authorization header."""
        response = voice_client.post(
            "/apps/voice/sdp",
            content=b"v=0\r\n",
            headers={"Content-Type": "application/sdp"},
        )
        assert response.status_code == 401

    def test_sdp_requires_body(self, voice_client: TestClient) -> None:
        """SDP endpoint returns 400 with empty body."""
        response = voice_client.post(
            "/apps/voice/sdp",
            content=b"",
            headers={
                "Content-Type": "application/sdp",
                "Authorization": "Bearer ek_test_token",
            },
        )
        assert response.status_code == 400

    @patch("amplifier_distro.server.apps.voice.httpx.AsyncClient")
    def test_sdp_relays_to_openai(self, mock_client_cls: MagicMock) -> None:
        """SDP endpoint relays offer to OpenAI and returns answer."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "v=0\r\no=- 12345 2 IN IP4 127.0.0.1\r\n"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        from amplifier_distro.server.apps.voice import manifest

        server = DistroServer()
        server.register_app(manifest)
        client = TestClient(server.app)

        response = client.post(
            "/apps/voice/sdp",
            content=b"v=0\r\no=- 67890 2 IN IP4 127.0.0.1\r\n",
            headers={
                "Content-Type": "application/sdp",
                "Authorization": "Bearer ek_test_token",
            },
        )

        assert response.status_code == 200
        assert "v=0" in response.text

    @patch("amplifier_distro.server.apps.voice.httpx.AsyncClient")
    def test_sdp_handles_openai_error(self, mock_client_cls: MagicMock) -> None:
        """SDP endpoint returns error when OpenAI rejects SDP."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Invalid SDP"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        from amplifier_distro.server.apps.voice import manifest

        server = DistroServer()
        server.register_app(manifest)
        client = TestClient(server.app)

        response = client.post(
            "/apps/voice/sdp",
            content=b"bad-sdp",
            headers={
                "Content-Type": "application/sdp",
                "Authorization": "Bearer ek_test_token",
            },
        )

        assert response.status_code == 400


# ------------------------------------------------------------------ #
#  Configuration Tests                                                 #
# ------------------------------------------------------------------ #


class TestVoiceConfig:
    """Verify VoiceConfig schema and defaults."""

    def test_voice_config_defaults(self) -> None:
        from amplifier_distro.schema import VoiceConfig

        cfg = VoiceConfig()
        assert cfg.voice == "ash"
        assert cfg.model == "gpt-4o-realtime-preview"

    def test_voice_config_custom_values(self) -> None:
        from amplifier_distro.schema import VoiceConfig

        cfg = VoiceConfig(voice="coral", model="gpt-4o-mini-realtime-preview")
        assert cfg.voice == "coral"
        assert cfg.model == "gpt-4o-mini-realtime-preview"

    def test_distro_config_has_voice(self) -> None:
        from amplifier_distro.schema import DistroConfig

        cfg = DistroConfig()
        assert hasattr(cfg, "voice")
        assert cfg.voice.voice == "ash"
        assert cfg.voice.model == "gpt-4o-realtime-preview"

    def test_distro_config_loads_voice_from_dict(self) -> None:
        from amplifier_distro.schema import DistroConfig

        cfg = DistroConfig.model_validate(
            {"voice": {"voice": "sage", "model": "gpt-4o-realtime-preview"}}
        )
        assert cfg.voice.voice == "sage"

    def test_voice_config_in_model_dump(self) -> None:
        from amplifier_distro.schema import DistroConfig

        cfg = DistroConfig()
        dumped = cfg.model_dump()
        assert "voice" in dumped
        assert dumped["voice"]["voice"] == "ash"
        assert dumped["voice"]["model"] == "gpt-4o-realtime-preview"
