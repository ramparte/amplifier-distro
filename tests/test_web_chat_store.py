"""Tests for WebChatSession and WebChatSessionStore.

Tests are isolated: no server, no backend, no services.
All store tests use persistence_path=None (in-memory mode).
"""

from __future__ import annotations

import pytest

from amplifier_distro.server.apps.web_chat.session_store import (
    WebChatSession,
    WebChatSessionStore,
)


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


class TestWebChatSessionStore:
    """Verify WebChatSessionStore behaviour.

    All tests use persistence_path=None (in-memory, no disk I/O).
    Persistence roundtrip tests use a tmpdir.
    """

    # ------------------------------------------------------------------
    # add()
    # ------------------------------------------------------------------

    def test_add_returns_session(self):
        store = WebChatSessionStore()
        s = store.add("sess-001", "my project")
        assert isinstance(s, WebChatSession)
        assert s.session_id == "sess-001"
        assert s.description == "my project"
        assert s.is_active is True

    def test_add_timestamps_are_set(self):
        store = WebChatSessionStore()
        s = store.add("sess-001", "test")
        assert s.created_at != ""
        assert s.last_active != ""

    def test_add_extra_is_stored(self):
        store = WebChatSessionStore()
        s = store.add("sess-001", "test", extra={"project_id": "proj-42"})
        assert s.extra["project_id"] == "proj-42"

    def test_add_duplicate_raises(self):
        store = WebChatSessionStore()
        store.add("sess-001", "first")
        with pytest.raises(ValueError, match="already exists"):
            store.add("sess-001", "second")

    # ------------------------------------------------------------------
    # get()
    # ------------------------------------------------------------------

    def test_get_returns_session(self):
        store = WebChatSessionStore()
        store.add("sess-001", "test")
        s = store.get("sess-001")
        assert s is not None
        assert s.session_id == "sess-001"

    def test_get_missing_returns_none(self):
        store = WebChatSessionStore()
        assert store.get("nonexistent") is None

    # ------------------------------------------------------------------
    # deactivate()
    # ------------------------------------------------------------------

    def test_deactivate_marks_inactive(self):
        store = WebChatSessionStore()
        store.add("sess-001", "test")
        store.deactivate("sess-001")
        s = store.get("sess-001")
        assert s is not None
        assert s.is_active is False

    def test_deactivate_missing_does_not_raise(self):
        store = WebChatSessionStore()
        store.deactivate("nonexistent")  # should not raise

    # ------------------------------------------------------------------
    # reactivate()
    # ------------------------------------------------------------------

    def test_reactivate_marks_active(self):
        store = WebChatSessionStore()
        store.add("sess-001", "test")
        store.deactivate("sess-001")
        s = store.reactivate("sess-001")
        assert s.is_active is True

    def test_reactivate_updates_last_active(self):
        store = WebChatSessionStore()
        original = store.add("sess-001", "test")
        old_ts = original.last_active
        store.deactivate("sess-001")
        resumed = store.reactivate("sess-001")
        assert resumed.last_active >= old_ts

    def test_reactivate_missing_raises(self):
        store = WebChatSessionStore()
        with pytest.raises(ValueError, match="not found"):
            store.reactivate("nonexistent")

    # ------------------------------------------------------------------
    # list_all()
    # ------------------------------------------------------------------

    def test_list_all_empty(self):
        store = WebChatSessionStore()
        assert store.list_all() == []

    def test_list_all_returns_all_sessions(self):
        store = WebChatSessionStore()
        store.add("sess-001", "first")
        store.add("sess-002", "second")
        sessions = store.list_all()
        assert len(sessions) == 2

    def test_list_all_sorted_by_last_active_desc(self):
        """Most recently active session comes first."""
        store = WebChatSessionStore()
        s1 = store.add("sess-001", "first")
        s2 = store.add("sess-002", "second")
        # Manually set timestamps so ordering is deterministic
        s1.last_active = "2026-01-01T10:00:00"
        s2.last_active = "2026-01-01T12:00:00"
        sessions = store.list_all()
        assert sessions[0].session_id == "sess-002"
        assert sessions[1].session_id == "sess-001"

    # ------------------------------------------------------------------
    # active_session()
    # ------------------------------------------------------------------

    def test_active_session_none_when_empty(self):
        store = WebChatSessionStore()
        assert store.active_session() is None

    def test_active_session_returns_active_entry(self):
        store = WebChatSessionStore()
        store.add("sess-001", "test")
        s = store.active_session()
        assert s is not None
        assert s.session_id == "sess-001"

    def test_active_session_none_after_deactivate(self):
        store = WebChatSessionStore()
        store.add("sess-001", "test")
        store.deactivate("sess-001")
        assert store.active_session() is None

    # ------------------------------------------------------------------
    # Persistence — roundtrip
    # ------------------------------------------------------------------

    def test_persistence_roundtrip(self, tmp_path):
        """Sessions survive save → load cycle."""
        path = tmp_path / "sessions.json"
        store = WebChatSessionStore(persistence_path=path)
        store.add("sess-001", "persisted session", extra={"project_id": "proj-1"})
        store.deactivate("sess-001")

        # Load into fresh store
        store2 = WebChatSessionStore(persistence_path=path)
        s = store2.get("sess-001")
        assert s is not None
        assert s.description == "persisted session"
        assert s.is_active is False
        assert s.extra["project_id"] == "proj-1"

    def test_persistence_none_path_means_in_memory(self, tmp_path):
        """When persistence_path=None, no file is written."""
        store = WebChatSessionStore(persistence_path=None)
        store.add("sess-001", "test")
        # No file written
        assert not (tmp_path / "sessions.json").exists()

    def test_persistence_corrupt_json_is_ignored(self, tmp_path):
        """Corrupt file on disk doesn't crash the store — starts empty."""
        path = tmp_path / "sessions.json"
        path.write_text("this is not valid json{{{")
        store = WebChatSessionStore(persistence_path=path)
        assert store.list_all() == []

    def test_persistence_missing_file_is_ignored(self, tmp_path):
        """Missing file doesn't crash the store — starts empty."""
        path = tmp_path / "nonexistent.json"
        store = WebChatSessionStore(persistence_path=path)
        assert store.list_all() == []
