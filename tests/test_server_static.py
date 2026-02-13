"""Server Root Redirect & App HTML Serving Tests

These tests validate:
1. GET / returns a phase-aware redirect to an app route
2. Install-wizard app serves its HTML pages (quickstart, wizard)
3. Settings app serves its HTML page
4. HTML pages contain expected elements (title, Amplifier branding)
"""

from pathlib import Path

from starlette.testclient import TestClient

from amplifier_distro.server.app import DistroServer


def _make_client() -> TestClient:
    """Create a test client with apps discovered."""
    server = DistroServer()
    builtin_apps = Path(__file__).parent.parent / "src" / "amplifier_distro" / "server" / "apps"
    server.discover_apps(builtin_apps)
    return TestClient(server.app)


class TestRootRedirect:
    """Verify GET / redirects based on setup phase.

    The root URL is the first thing a user hits.
    It redirects based on compute_phase(): unconfigured -> install-wizard,
    ready -> web-chat (or settings).
    """

    def test_root_returns_redirect(self):
        client = _make_client()
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (302, 307)

    def test_root_redirects_to_app_route(self):
        client = _make_client()
        response = client.get("/", follow_redirects=False)
        location = response.headers["location"]
        assert "/apps/" in location

    def test_root_follow_redirect_reaches_page(self):
        client = _make_client()
        response = client.get("/")
        assert response.status_code == 200


class TestInstallWizardPages:
    """Verify install-wizard app serves its HTML pages."""

    def test_quickstart_returns_200(self):
        client = _make_client()
        response = client.get("/apps/install-wizard/")
        assert response.status_code == 200

    def test_wizard_html_returns_200(self):
        client = _make_client()
        response = client.get("/apps/install-wizard/wizard")
        assert response.status_code == 200

    def test_wizard_html_is_html_content(self):
        client = _make_client()
        response = client.get("/apps/install-wizard/wizard")
        content_type = response.headers.get("content-type", "")
        assert "text/html" in content_type

    def test_wizard_html_contains_doctype(self):
        client = _make_client()
        response = client.get("/apps/install-wizard/wizard")
        assert "<!DOCTYPE html>" in response.text

    def test_wizard_html_contains_title(self):
        client = _make_client()
        response = client.get("/apps/install-wizard/wizard")
        assert "<title>" in response.text
        assert "Amplifier" in response.text

    def test_wizard_html_contains_step_indicator(self):
        """The wizard UI should have step indicator elements."""
        client = _make_client()
        response = client.get("/apps/install-wizard/wizard")
        assert "step" in response.text.lower()


class TestSettingsPage:
    """Verify settings app serves its HTML page."""

    def test_settings_returns_200(self):
        client = _make_client()
        response = client.get("/apps/settings/")
        assert response.status_code == 200

    def test_settings_is_html_content(self):
        client = _make_client()
        response = client.get("/apps/settings/")
        content_type = response.headers.get("content-type", "")
        assert "text/html" in content_type

    def test_settings_contains_amplifier(self):
        client = _make_client()
        response = client.get("/apps/settings/")
        assert "Amplifier" in response.text
