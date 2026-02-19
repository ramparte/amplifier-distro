"""Tests for WebChatSession and WebChatSessionStore.

Tests are isolated: no server, no backend, no services.
All store tests use persistence_path=None (in-memory mode).
"""

from __future__ import annotations

from amplifier_distro.server.apps.web_chat.session_store import WebChatSession


class TestWebChatSession:
    """Verify the WebChatSession dataclass."""

    def test_session_has_required_fields(self):
        s = WebChatSession(
            session_id="abc123",
            description="my project",
            created_at="2026-01-01T00:00:00",
            last_active="2026-01-01T00:00:00",
        )
        assert s.session_id == "abc123"
        assert s.description == "my project"
        assert s.created_at == "2026-01-01T00:00:00"
        assert s.last_active == "2026-01-01T00:00:00"

    def test_session_is_active_by_default(self):
        s = WebChatSession(
            session_id="abc123",
            description="test",
            created_at="2026-01-01T00:00:00",
            last_active="2026-01-01T00:00:00",
        )
        assert s.is_active is True

    def test_session_extra_defaults_to_empty_dict(self):
        s = WebChatSession(
            session_id="abc123",
            description="test",
            created_at="2026-01-01T00:00:00",
            last_active="2026-01-01T00:00:00",
        )
        assert s.extra == {}

    def test_session_extra_instances_are_independent(self):
        """Each instance must have its own dict — not shared via mutable default."""
        s1 = WebChatSession(
            session_id="s1",
            description="a",
            created_at="t",
            last_active="t",
        )
        s2 = WebChatSession(
            session_id="s2",
            description="b",
            created_at="t",
            last_active="t",
        )
        s1.extra["key"] = "value"
        assert "key" not in s2.extra
