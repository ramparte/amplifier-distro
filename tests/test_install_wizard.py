"""Install Wizard Tests (Refactored)

Tests for the new quickstart-based install wizard that replaced
the 7-step wizard. The new wizard is stateless - everything is
derived from the filesystem.

Exit criteria verified:
1. Manifest has correct name, description, and router
2. compute_phase() returns correct phase based on filesystem state
3. GET /detect returns structured environment detection
4. GET /status returns phase, provider, tier, features
5. POST /quickstart creates bundle and settings from API key
6. POST /features toggles features on/off
7. POST /tier sets feature tier level
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import APIRouter
from starlette.testclient import TestClient

from amplifier_distro.server.app import AppManifest, DistroServer


@pytest.fixture
def wizard_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect all wizard file operations to a temp directory."""
    home = tmp_path / "amplifier"
    home.mkdir()

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

    return home


@pytest.fixture
def wizard_client(wizard_home: Path) -> TestClient:
    """Create a TestClient with the install wizard registered."""
    from amplifier_distro.server.apps.install_wizard import manifest

    server = DistroServer()
    server.register_app(manifest)
    return TestClient(server.app)


# --- Manifest Tests ---


class TestInstallWizardManifest:
    """Verify the install wizard manifest has correct structure."""

    def test_manifest_name_is_install_wizard(self):
        from amplifier_distro.server.apps.install_wizard import manifest

        assert manifest.name == "install-wizard"

    def test_manifest_has_router(self):
        from amplifier_distro.server.apps.install_wizard import manifest

        assert manifest.router is not None
        assert isinstance(manifest.router, APIRouter)

    def test_manifest_has_description(self):
        from amplifier_distro.server.apps.install_wizard import manifest

        assert isinstance(manifest.description, str)
        assert len(manifest.description) > 0

    def test_manifest_is_app_manifest_type(self):
        from amplifier_distro.server.apps.install_wizard import manifest

        assert isinstance(manifest, AppManifest)


# --- compute_phase Tests ---


class TestComputePhase:
    """Verify compute_phase() returns correct phase from filesystem state."""

    def test_unconfigured_when_no_settings(self, wizard_home: Path):
        from amplifier_distro.server.apps.install_wizard import compute_phase

        # No settings.yaml exists
        assert compute_phase() == "unconfigured"

    def test_unconfigured_when_settings_but_no_key(self, wizard_home: Path):
        from amplifier_distro.server.apps.install_wizard import compute_phase

        # Create settings.yaml but no env var
        settings = wizard_home / "settings.yaml"
        settings.write_text("bundle:\n  active: amplifier-distro\n")
        assert compute_phase() == "unconfigured"

    def test_ready_when_settings_and_key(
        self, wizard_home: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from amplifier_distro.server.apps.install_wizard import compute_phase

        # Create settings.yaml AND set env var
        settings = wizard_home / "settings.yaml"
        settings.write_text("bundle:\n  active: amplifier-distro\n")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test123")
        assert compute_phase() == "ready"


# --- GET /detect Tests ---


class TestDetectEndpoint:
    """Verify GET /detect returns structured environment data."""

    def test_returns_200(self, wizard_client: TestClient):
        response = wizard_client.get("/apps/install-wizard/detect")
        assert response.status_code == 200

    def test_has_github_key(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/detect").json()
        assert "github" in data

    def test_has_git_key(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/detect").json()
        assert "git" in data

    def test_has_tailscale_key(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/detect").json()
        assert "tailscale" in data

    def test_has_api_keys_key(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/detect").json()
        assert "api_keys" in data


# --- GET /status Tests ---


class TestStatusEndpoint:
    """Verify GET /status returns current setup state."""

    def test_returns_200(self, wizard_client: TestClient):
        response = wizard_client.get("/apps/install-wizard/status")
        assert response.status_code == 200

    def test_has_phase(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/status").json()
        assert "phase" in data

    def test_has_provider(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/status").json()
        assert "provider" in data

    def test_has_tier(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/status").json()
        assert "tier" in data

    def test_has_features(self, wizard_client: TestClient):
        data = wizard_client.get("/apps/install-wizard/status").json()
        assert "features" in data


# --- POST /quickstart Tests ---


class TestQuickstartEndpoint:
    """Verify POST /quickstart sets up a working environment."""

    def test_anthropic_key_returns_ready(self, wizard_client: TestClient):
        resp = wizard_client.post(
            "/apps/install-wizard/quickstart",
            json={"api_key": "sk-ant-test123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["provider"] == "anthropic"

    def test_openai_key_returns_ready(self, wizard_client: TestClient):
        resp = wizard_client.post(
            "/apps/install-wizard/quickstart",
            json={"api_key": "sk-test123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["provider"] == "openai"

    def test_invalid_key_returns_400(self, wizard_client: TestClient):
        resp = wizard_client.post(
            "/apps/install-wizard/quickstart",
            json={"api_key": "invalid-key"},
        )
        assert resp.status_code == 400

    def test_empty_key_returns_400(self, wizard_client: TestClient):
        resp = wizard_client.post(
            "/apps/install-wizard/quickstart",
            json={"api_key": ""},
        )
        assert resp.status_code == 400

    def test_missing_key_returns_422(self, wizard_client: TestClient):
        resp = wizard_client.post(
            "/apps/install-wizard/quickstart",
            json={},
        )
        assert resp.status_code == 422

    def test_creates_bundle_file(self, wizard_client: TestClient, wizard_home: Path):
        wizard_client.post(
            "/apps/install-wizard/quickstart",
            json={"api_key": "sk-ant-test123"},
        )
        bundle_path = wizard_home / "bundles" / "distro.yaml"
        assert bundle_path.exists()

    def test_creates_settings_file(self, wizard_client: TestClient, wizard_home: Path):
        wizard_client.post(
            "/apps/install-wizard/quickstart",
            json={"api_key": "sk-ant-test123"},
        )
        settings_path = wizard_home / "settings.yaml"
        assert settings_path.exists()

    def test_creates_keys_file(self, wizard_client: TestClient, wizard_home: Path):
        wizard_client.post(
            "/apps/install-wizard/quickstart",
            json={"api_key": "sk-ant-test123"},
        )
        keys_path = wizard_home / "keys.env"
        assert keys_path.exists()

    def test_sets_env_var(self, wizard_client: TestClient):
        wizard_client.post(
            "/apps/install-wizard/quickstart",
            json={"api_key": "sk-ant-test123"},
        )
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-test123"


# --- POST /features Tests ---


class TestFeaturesEndpoint:
    """Verify POST /features toggles features on/off."""

    def _setup_bundle(self, client: TestClient) -> None:
        """Helper: quickstart to create initial bundle."""
        client.post(
            "/apps/install-wizard/quickstart",
            json={"api_key": "sk-ant-test123"},
        )

    def test_enable_feature(self, wizard_client: TestClient):
        self._setup_bundle(wizard_client)
        resp = wizard_client.post(
            "/apps/install-wizard/features",
            json={"feature_id": "dev-memory", "enabled": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["features"]["dev-memory"]["enabled"] is True

    def test_disable_feature(self, wizard_client: TestClient):
        self._setup_bundle(wizard_client)
        # Enable first
        wizard_client.post(
            "/apps/install-wizard/features",
            json={"feature_id": "dev-memory", "enabled": True},
        )
        # Then disable
        resp = wizard_client.post(
            "/apps/install-wizard/features",
            json={"feature_id": "dev-memory", "enabled": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["features"]["dev-memory"]["enabled"] is False

    def test_unknown_feature_returns_400(self, wizard_client: TestClient):
        self._setup_bundle(wizard_client)
        resp = wizard_client.post(
            "/apps/install-wizard/features",
            json={"feature_id": "nonexistent", "enabled": True},
        )
        assert resp.status_code == 400


# --- POST /tier Tests ---


class TestTierEndpoint:
    """Verify POST /tier sets the feature tier level."""

    def _setup_bundle(self, client: TestClient) -> None:
        """Helper: quickstart to create initial bundle."""
        client.post(
            "/apps/install-wizard/quickstart",
            json={"api_key": "sk-ant-test123"},
        )

    def test_set_tier_1(self, wizard_client: TestClient):
        self._setup_bundle(wizard_client)
        resp = wizard_client.post(
            "/apps/install-wizard/tier",
            json={"tier": 1},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["features"]["dev-memory"]["enabled"] is True
        assert data["features"]["deliberate-dev"]["enabled"] is True

    def test_set_tier_returns_features_added(self, wizard_client: TestClient):
        self._setup_bundle(wizard_client)
        resp = wizard_client.post(
            "/apps/install-wizard/tier",
            json={"tier": 1},
        )
        data = resp.json()
        assert "features_added" in data
        assert "dev-memory" in data["features_added"]
