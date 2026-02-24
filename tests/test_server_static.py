"""Server Root Landing Page Tests

These tests validate:
1. GET / serves a landing page (when configured) or redirects (when not)
2. HTML pages contain expected elements (title, Amplifier branding)
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


class TestRootLandingPage:
    """Verify GET / serves a landing page when configured.

    The root URL is the first thing a user hits.
    When ready, it serves an HTML landing page with app links.
    """

    def test_root_returns_200(self):
        client = _make_client()
        response = client.get("/")
        assert response.status_code == 200

    def test_root_returns_html(self):
        client = _make_client()
        response = client.get("/")
        content_type = response.headers.get("content-type", "")
        assert "text/html" in content_type

    def test_root_contains_amplifier(self):
        client = _make_client()
        response = client.get("/")
        assert "Amplifier" in response.text

    def test_root_contains_chat_link(self):
        client = _make_client()
        response = client.get("/")
        assert "/apps/web-chat/" in response.text
