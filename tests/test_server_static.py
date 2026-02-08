"""Server Static Files & Root Redirect Acceptance Tests

These tests validate the server modifications for static file
serving and root redirect to the install wizard.

Exit criteria verified:
1. GET / returns a 302 redirect to /static/wizard.html
2. GET /static/wizard.html returns 200 with HTML content
3. wizard.html contains expected elements (title, step indicators)
"""

from starlette.testclient import TestClient

from amplifier_distro.server.app import DistroServer


class TestRootRedirect:
    """Verify GET / redirects to the install wizard.

    Antagonist note: The root URL is the first thing a user hits.
    It must redirect to the wizard so new users land on the setup
    flow immediately.
    """

    def test_root_returns_redirect(self):
        server = DistroServer()
        client = TestClient(server.app, follow_redirects=False)
        response = client.get("/")
        assert response.status_code == 307 or response.status_code == 302

    def test_root_redirects_to_wizard_html(self):
        server = DistroServer()
        client = TestClient(server.app, follow_redirects=False)
        response = client.get("/")
        assert "/static/wizard.html" in response.headers["location"]

    def test_root_follow_redirect_reaches_wizard(self):
        server = DistroServer()
        client = TestClient(server.app, follow_redirects=True)
        response = client.get("/")
        assert response.status_code == 200


class TestStaticFiles:
    """Verify static file serving works correctly.

    Antagonist note: The server mounts a /static directory that
    serves the wizard HTML. This must be accessible and return
    valid HTML content.
    """

    def test_wizard_html_returns_200(self):
        server = DistroServer()
        client = TestClient(server.app)
        response = client.get("/static/wizard.html")
        assert response.status_code == 200

    def test_wizard_html_is_html_content(self):
        server = DistroServer()
        client = TestClient(server.app)
        response = client.get("/static/wizard.html")
        content_type = response.headers.get("content-type", "")
        assert "text/html" in content_type

    def test_wizard_html_contains_doctype(self):
        server = DistroServer()
        client = TestClient(server.app)
        response = client.get("/static/wizard.html")
        assert "<!DOCTYPE html>" in response.text

    def test_wizard_html_contains_title(self):
        server = DistroServer()
        client = TestClient(server.app)
        response = client.get("/static/wizard.html")
        assert "<title>" in response.text
        assert "Amplifier" in response.text

    def test_wizard_html_contains_step_indicator(self):
        """The wizard UI should have step indicator elements."""
        server = DistroServer()
        client = TestClient(server.app)
        response = client.get("/static/wizard.html")
        # The HTML references step indicators in its CSS/structure
        assert "step" in response.text.lower()

    def test_nonexistent_static_file_returns_404(self):
        server = DistroServer()
        client = TestClient(server.app)
        response = client.get("/static/nonexistent.html")
        assert response.status_code == 404
