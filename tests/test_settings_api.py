"""Settings & Configuration API Tests (T5)

Tests for the settings API endpoints added to the core server:
1. PUT /api/config - Update distro.yaml values
2. GET /api/integrations - Status of each integration
3. POST /api/test-provider - Test a provider connection
4. Behavior toggle round-trip verification

These endpoints extend the core server routes in app.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from starlette.testclient import TestClient

from amplifier_distro.server.app import DistroServer


@pytest.fixture
def settings_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp amplifier home with a valid distro.yaml for testing."""
    home = tmp_path / "amplifier"
    home.mkdir()

    # Write a distro.yaml config file
    config_data = {
        "workspace_root": "~/dev",
        "identity": {
            "github_handle": "testuser",
            "git_email": "test@example.com",
        },
    }
    config_path = home / "distro.yaml"
    config_path.write_text(yaml.dump(config_data, default_flow_style=False))

    # Patch config_path() to point to our temp file
    monkeypatch.setattr(
        "amplifier_distro.config.config_path",
        lambda: config_path,
    )

    # Redirect bundle_composer's BUNDLE_PATH
    test_bundle = home / "bundles" / "distro.yaml"
    monkeypatch.setattr("amplifier_distro.bundle_composer.BUNDLE_PATH", test_bundle)

    # Redirect install wizard's AMPLIFIER_HOME
    monkeypatch.setattr(
        "amplifier_distro.server.apps.install_wizard.AMPLIFIER_HOME",
        str(home),
    )

    # Clear provider env vars to start clean
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)

    return home


@pytest.fixture
def settings_client(settings_home: Path) -> TestClient:
    """Create a TestClient with the install wizard registered."""
    from amplifier_distro.server.apps.install_wizard import manifest

    server = DistroServer()
    server.register_app(manifest)
    return TestClient(server.app)


# --- GET /api/config Tests ---


class TestGetConfig:
    """Verify GET /api/config returns current distro.yaml values."""

    def test_returns_200(self, settings_client: TestClient) -> None:
        response = settings_client.get("/api/config")
        assert response.status_code == 200

    def test_returns_workspace_root(self, settings_client: TestClient) -> None:
        data = settings_client.get("/api/config").json()
        assert data["workspace_root"] == "~/dev"

    def test_returns_identity(self, settings_client: TestClient) -> None:
        data = settings_client.get("/api/config").json()
        assert data["identity"]["github_handle"] == "testuser"
        assert data["identity"]["git_email"] == "test@example.com"


# --- PUT /api/config Tests ---


class TestPutConfig:
    """Verify PUT /api/config updates distro.yaml values."""

    def test_update_workspace_root(self, settings_client: TestClient) -> None:
        response = settings_client.put(
            "/api/config",
            json={"workspace_root": "~/projects"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["workspace_root"] == "~/projects"

    def test_update_github_handle(self, settings_client: TestClient) -> None:
        response = settings_client.put(
            "/api/config",
            json={"identity": {"github_handle": "newuser"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["identity"]["github_handle"] == "newuser"

    def test_update_persists_to_disk(
        self, settings_client: TestClient, settings_home: Path
    ) -> None:
        """Verify that PUT /api/config actually writes to distro.yaml."""
        settings_client.put(
            "/api/config",
            json={"workspace_root": "~/new-workspace"},
        )
        config_path = settings_home / "distro.yaml"
        data = yaml.safe_load(config_path.read_text())
        assert data["workspace_root"] == "~/new-workspace"

    def test_partial_update_preserves_other_fields(
        self, settings_client: TestClient
    ) -> None:
        """Updating one field should not clobber others."""
        settings_client.put(
            "/api/config",
            json={"workspace_root": "~/changed"},
        )
        data = settings_client.get("/api/config").json()
        # workspace_root changed
        assert data["workspace_root"] == "~/changed"
        # identity preserved
        assert data["identity"]["github_handle"] == "testuser"


# --- GET /api/integrations Tests ---


class TestGetIntegrations:
    """Verify GET /api/integrations returns integration status."""

    def test_returns_200(self, settings_client: TestClient) -> None:
        response = settings_client.get("/api/integrations")
        assert response.status_code == 200

    def test_has_slack_entry(self, settings_client: TestClient) -> None:
        data = settings_client.get("/api/integrations").json()
        assert "slack" in data
        assert "status" in data["slack"]
        assert "name" in data["slack"]

    def test_has_voice_entry(self, settings_client: TestClient) -> None:
        data = settings_client.get("/api/integrations").json()
        assert "voice" in data
        assert "status" in data["voice"]
        assert "name" in data["voice"]

    def test_slack_not_configured_by_default(self, settings_client: TestClient) -> None:
        """Without SLACK_BOT_TOKEN, slack should be not_configured."""
        data = settings_client.get("/api/integrations").json()
        assert data["slack"]["status"] == "not_configured"

    def test_voice_not_configured_by_default(self, settings_client: TestClient) -> None:
        """Without OPENAI_API_KEY, voice should be not_configured."""
        data = settings_client.get("/api/integrations").json()
        assert data["voice"]["status"] == "not_configured"

    def test_voice_configured_with_env_var(
        self,
        settings_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With OPENAI_API_KEY set, voice should be configured."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        data = settings_client.get("/api/integrations").json()
        assert data["voice"]["status"] == "configured"

    def test_integration_has_setup_url(self, settings_client: TestClient) -> None:
        data = settings_client.get("/api/integrations").json()
        assert "setup_url" in data["slack"]
        assert "setup_url" in data["voice"]


# --- POST /api/test-provider Tests ---


class TestTestProvider:
    """Verify POST /api/test-provider tests provider connections."""

    def test_unknown_provider_returns_400(self, settings_client: TestClient) -> None:
        response = settings_client.post(
            "/api/test-provider",
            json={"provider": "invalid-provider"},
        )
        assert response.status_code == 400

    def test_anthropic_no_key_returns_error(self, settings_client: TestClient) -> None:
        """Without ANTHROPIC_API_KEY set, test should report not set."""
        response = settings_client.post(
            "/api/test-provider",
            json={"provider": "anthropic"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert "not set" in data["error"]

    def test_openai_no_key_returns_error(self, settings_client: TestClient) -> None:
        """Without OPENAI_API_KEY set, test should report not set."""
        response = settings_client.post(
            "/api/test-provider",
            json={"provider": "openai"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert "not set" in data["error"]

    def test_anthropic_with_key_calls_api(
        self,
        settings_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With key set, should attempt an API call (mocked)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            response = settings_client.post(
                "/api/test-provider",
                json={"provider": "anthropic"},
            )

        data = response.json()
        assert data["ok"] is True
        assert data["provider"] == "anthropic"

    def test_openai_with_key_calls_api(
        self,
        settings_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With key set, should attempt an API call (mocked)."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-456")

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            response = settings_client.post(
                "/api/test-provider",
                json={"provider": "openai"},
            )

        data = response.json()
        assert data["ok"] is True
        assert data["provider"] == "openai"


# --- Behavior Toggle Round-Trip Test ---


class TestBehaviorToggleRoundTrip:
    """Verify the full behavior toggle flow: enable, verify, disable, verify."""

    def _setup_bundle(self, client: TestClient) -> None:
        """Helper: quickstart to create initial bundle."""
        client.post(
            "/apps/install-wizard/quickstart",
            json={"api_key": "sk-ant-test123"},
        )

    def test_enable_disable_round_trip(self, settings_client: TestClient) -> None:
        """Enable a feature, verify it's on, disable it, verify it's off."""
        self._setup_bundle(settings_client)

        # Enable
        resp = settings_client.post(
            "/apps/install-wizard/features",
            json={"feature_id": "dev-memory", "enabled": True},
        )
        assert resp.status_code == 200
        assert resp.json()["features"]["dev-memory"]["enabled"] is True

        # Verify via status
        status = settings_client.get("/apps/install-wizard/status").json()
        assert status["features"]["dev-memory"]["enabled"] is True

        # Disable
        resp = settings_client.post(
            "/apps/install-wizard/features",
            json={"feature_id": "dev-memory", "enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["features"]["dev-memory"]["enabled"] is False

        # Verify via status
        status = settings_client.get("/apps/install-wizard/status").json()
        assert status["features"]["dev-memory"]["enabled"] is False
