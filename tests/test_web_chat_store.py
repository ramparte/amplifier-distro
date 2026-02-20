"""Tests for WebChatSession and WebChatSessionStore.

Tests are isolated: no server, no backend, no services.
All store tests use persistence_path=None (in-memory mode).
"""

from __future__ import annotations

import asyncio

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
    # touch()
    # ------------------------------------------------------------------

    def test_touch_updates_last_active(self):
        store = WebChatSessionStore()
        s = store.add("sess-001", "test")
        old_ts = s.last_active
        store.touch("sess-001")
        updated = store.get("sess-001")
        assert updated is not None
        assert updated.last_active >= old_ts

    def test_touch_missing_does_not_raise(self):
        store = WebChatSessionStore()
        store.touch("nonexistent")  # should not raise

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


class TestWebChatSessionManager:
    """Verify WebChatSessionManager behaviour using MockBackend directly.

    No server, no services, no HTTP. Pure unit tests.
    """

    def _make_manager(self):
        """Create a manager with a fresh MockBackend and in-memory store."""
        from amplifier_distro.server.apps.web_chat import WebChatSessionManager
        from amplifier_distro.server.session_backend import MockBackend

        backend = MockBackend()
        manager = WebChatSessionManager(backend, persistence_path=None)
        return manager, backend

    # ------------------------------------------------------------------
    # active_session_id property
    # ------------------------------------------------------------------

    def test_active_session_id_none_initially(self):
        manager, _ = self._make_manager()
        assert manager.active_session_id is None

    # ------------------------------------------------------------------
    # create_session()
    # ------------------------------------------------------------------

    def test_create_session_returns_session_info(self):
        manager, _ = self._make_manager()
        info = asyncio.run(
            manager.create_session(working_dir="~", description="test session")
        )
        assert info.session_id.startswith("mock-session-")

    def test_create_session_sets_active(self):
        manager, _ = self._make_manager()
        info = asyncio.run(manager.create_session(working_dir="~", description="test"))
        assert manager.active_session_id == info.session_id

    def test_create_session_registers_in_store(self):
        manager, _ = self._make_manager()
        info = asyncio.run(
            manager.create_session(working_dir="~", description="my description")
        )
        stored = manager._store.get(info.session_id)
        assert stored is not None
        assert stored.description == "my description"

    def test_create_session_stores_project_id_in_extra(self):
        manager, _ = self._make_manager()
        info = asyncio.run(manager.create_session(working_dir="~", description="test"))
        stored = manager._store.get(info.session_id)
        assert stored is not None
        assert stored.extra.get("project_id") == info.project_id

    def test_create_session_stores_working_dir_in_extra(self):
        manager, _ = self._make_manager()
        info = asyncio.run(
            manager.create_session(working_dir="/tmp/myproject", description="test")
        )
        stored = manager._store.get(info.session_id)
        assert stored is not None
        assert stored.extra.get("working_dir") == "/tmp/myproject"

    def test_create_session_ends_previous_session(self):
        manager, _backend = self._make_manager()
        info1 = asyncio.run(
            manager.create_session(working_dir="~", description="first")
        )
        info2 = asyncio.run(
            manager.create_session(working_dir="~", description="second")
        )
        # First session should be deactivated in store
        s1 = manager._store.get(info1.session_id)
        assert s1 is not None
        assert s1.is_active is False
        # Second session is now active
        assert manager.active_session_id == info2.session_id

    # ------------------------------------------------------------------
    # send_message()
    # ------------------------------------------------------------------

    def test_send_message_returns_none_without_session(self):
        manager, _ = self._make_manager()
        result = asyncio.run(manager.send_message("hello"))
        assert result is None

    def test_send_message_returns_response(self):
        manager, _ = self._make_manager()
        asyncio.run(manager.create_session(working_dir="~", description="test"))
        response = asyncio.run(manager.send_message("hello"))
        assert response is not None
        assert "hello" in response  # MockBackend echoes the message

    def test_send_message_deactivates_on_backend_valueerror(self):
        from amplifier_distro.server.apps.web_chat import WebChatSessionManager
        from amplifier_distro.server.session_backend import MockBackend

        backend = MockBackend()
        manager = WebChatSessionManager(backend, persistence_path=None)
        info = asyncio.run(manager.create_session(working_dir="~", description="test"))
        # Kill backend session
        backend._sessions[info.session_id].is_active = False

        with pytest.raises(ValueError):
            asyncio.run(manager.send_message("hello after death"))

        # Store should have deactivated the session
        assert manager.active_session_id is None

    # ------------------------------------------------------------------
    # end_session()
    # ------------------------------------------------------------------

    def test_end_session_returns_false_without_session(self):
        manager, _ = self._make_manager()
        result = asyncio.run(manager.end_session())
        assert result is False

    def test_end_session_returns_true_with_session(self):
        manager, _ = self._make_manager()
        asyncio.run(manager.create_session(working_dir="~", description="test"))
        result = asyncio.run(manager.end_session())
        assert result is True

    def test_end_session_clears_active(self):
        manager, _ = self._make_manager()
        asyncio.run(manager.create_session(working_dir="~", description="test"))
        asyncio.run(manager.end_session())
        assert manager.active_session_id is None

    # ------------------------------------------------------------------
    # list_sessions()
    # ------------------------------------------------------------------

    def test_list_sessions_empty(self):
        manager, _ = self._make_manager()
        assert manager.list_sessions() == []

    def test_list_sessions_returns_all(self):
        manager, _ = self._make_manager()
        asyncio.run(manager.create_session(working_dir="~", description="first"))
        asyncio.run(manager.create_session(working_dir="~", description="second"))
        sessions = manager.list_sessions()
        assert len(sessions) == 2

    # ------------------------------------------------------------------
    # resume_session()
    # ------------------------------------------------------------------

    def test_resume_session_raises_for_unknown_id(self):
        manager, _ = self._make_manager()
        with pytest.raises(ValueError, match="not found"):
            asyncio.run(manager.resume_session("no-such-id"))

    def test_resume_session_reactivates_inactive_session(self):
        manager, _ = self._make_manager()
        info1 = asyncio.run(
            manager.create_session(working_dir="~", description="first")
        )
        # Create second session (deactivates first)
        asyncio.run(manager.create_session(working_dir="~", description="second"))
        # Resume first
        resumed = asyncio.run(manager.resume_session(info1.session_id))
        assert resumed.is_active is True
        assert manager.active_session_id == info1.session_id

    def test_resume_session_deactivates_current(self):
        manager, _ = self._make_manager()
        info1 = asyncio.run(
            manager.create_session(working_dir="~", description="first")
        )
        info2 = asyncio.run(
            manager.create_session(working_dir="~", description="second")
        )
        asyncio.run(manager.resume_session(info1.session_id))
        # Second session should be deactivated
        s2 = manager._store.get(info2.session_id)
        assert s2 is not None
        assert s2.is_active is False

    def test_resume_session_calls_backend(self):
        """resume_session() must call backend.resume_session() with the correct args."""
        manager, backend = self._make_manager()
        info = asyncio.run(
            manager.create_session(working_dir="/tmp/proj", description="test")
        )
        # Clear the create_session call from the log so we can isolate the resume call
        backend.calls.clear()

        asyncio.run(manager.resume_session(info.session_id))

        resume_calls = [c for c in backend.calls if c["method"] == "resume_session"]
        assert len(resume_calls) == 1
        assert resume_calls[0]["session_id"] == info.session_id
        assert resume_calls[0]["working_dir"] == "/tmp/proj"


class TestMockBackendResumeSession:
    """Verify MockBackend.resume_session() records the call correctly."""

    def test_resume_session_records_call(self):
        from amplifier_distro.server.session_backend import MockBackend

        backend = MockBackend()
        asyncio.run(backend.resume_session("sess-001", "/tmp/myproject"))
        assert len(backend.calls) == 1
        call = backend.calls[0]
        assert call["method"] == "resume_session"
        assert call["session_id"] == "sess-001"
        assert call["working_dir"] == "/tmp/myproject"

    def test_resume_session_returns_none(self):
        from amplifier_distro.server.session_backend import MockBackend

        backend = MockBackend()
        result = asyncio.run(backend.resume_session("sess-001", "~"))
        assert result is None

    def test_resume_session_does_not_affect_existing_sessions(self):
        """resume_session is a no-op from MockBackend's session state perspective."""
        from amplifier_distro.server.session_backend import MockBackend

        backend = MockBackend()
        asyncio.run(backend.create_session(working_dir="~", description="existing"))
        session_id = backend.calls[0]["result"]
        before_count = len(backend._sessions)

        asyncio.run(backend.resume_session(session_id, "~"))

        # No new sessions were created
        assert len(backend._sessions) == before_count
