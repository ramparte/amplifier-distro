"""Tests for the shared SurfaceSessionRegistry.

Covers: SessionMapping dataclass, registry CRUD, persistence,
per-user limits, and queries.
"""

import json

import pytest


class TestSessionMapping:
    """Test the SessionMapping dataclass."""

    def test_required_fields(self):
        from amplifier_distro.server.surface_registry import SessionMapping

        m = SessionMapping(routing_key="ch:thread", session_id="s1")
        assert m.routing_key == "ch:thread"
        assert m.session_id == "s1"

    def test_defaults(self):
        from amplifier_distro.server.surface_registry import SessionMapping

        m = SessionMapping(routing_key="k", session_id="s")
        assert m.surface == ""
        assert m.project_id == ""
        assert m.description == ""
        assert m.created_by == ""
        assert m.created_at == ""
        assert m.last_active == ""
        assert m.is_active is True
        assert m.extra == {}

    def test_extra_fields_preserved(self):
        from amplifier_distro.server.surface_registry import SessionMapping

        m = SessionMapping(
            routing_key="k",
            session_id="s",
            extra={"channel_id": "C1", "thread_ts": "t1"},
        )
        assert m.extra["channel_id"] == "C1"
        assert m.extra["thread_ts"] == "t1"

    def test_extra_default_not_shared(self):
        """Each instance gets its own extra dict (no mutable default sharing)."""
        from amplifier_distro.server.surface_registry import SessionMapping

        m1 = SessionMapping(routing_key="k1", session_id="s1")
        m2 = SessionMapping(routing_key="k2", session_id="s2")
        m1.extra["foo"] = "bar"
        assert "foo" not in m2.extra


class TestRegistryCRUD:
    """Test register, lookup, update, deactivate, remove."""

    def _make_registry(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        return SurfaceSessionRegistry("test", persistence_path=None)

    def test_register_and_lookup(self):
        reg = self._make_registry()
        m = reg.register(
            routing_key="C1:t1",
            session_id="s1",
            user_id="U1",
            project_id="p1",
            description="test session",
        )
        assert m.routing_key == "C1:t1"
        assert m.session_id == "s1"
        assert m.surface == "test"
        assert m.created_by == "U1"
        assert m.project_id == "p1"
        assert m.description == "test session"
        assert m.is_active is True
        assert m.created_at != ""
        assert m.last_active != ""

        found = reg.lookup("C1:t1")
        assert found is m

    def test_register_with_extra_kwargs(self):
        reg = self._make_registry()
        m = reg.register(
            routing_key="k1",
            session_id="s1",
            user_id="U1",
            channel_id="C1",
            thread_ts="t1",
        )
        assert m.extra["channel_id"] == "C1"
        assert m.extra["thread_ts"] == "t1"

    def test_lookup_missing_returns_none(self):
        reg = self._make_registry()
        assert reg.lookup("nonexistent") is None

    def test_lookup_by_session_id(self):
        reg = self._make_registry()
        reg.register(routing_key="k1", session_id="s1", user_id="U1")
        reg.register(routing_key="k2", session_id="s2", user_id="U1")

        found = reg.lookup_by_session_id("s2")
        assert found is not None
        assert found.routing_key == "k2"

    def test_lookup_by_session_id_missing(self):
        reg = self._make_registry()
        assert reg.lookup_by_session_id("nope") is None

    def test_update_activity(self):
        reg = self._make_registry()
        m = reg.register(routing_key="k1", session_id="s1", user_id="U1")
        original_ts = m.last_active

        # Ensure clock advances (at least a different call)
        reg.update_activity("k1")
        assert m.last_active >= original_ts

    def test_update_activity_missing_key_is_noop(self):
        """Updating activity for a missing key should not raise."""
        reg = self._make_registry()
        reg.update_activity("nonexistent")  # no error

    def test_deactivate(self):
        reg = self._make_registry()
        reg.register(routing_key="k1", session_id="s1", user_id="U1")

        reg.deactivate("k1")
        m = reg.lookup("k1")
        assert m is not None
        assert m.is_active is False

    def test_deactivate_missing_key_is_noop(self):
        reg = self._make_registry()
        reg.deactivate("nonexistent")  # no error

    def test_remove(self):
        reg = self._make_registry()
        reg.register(routing_key="k1", session_id="s1", user_id="U1")

        removed = reg.remove("k1")
        assert removed is not None
        assert removed.session_id == "s1"
        assert reg.lookup("k1") is None

    def test_remove_missing_returns_none(self):
        reg = self._make_registry()
        assert reg.remove("nonexistent") is None

    def test_mappings_property_is_copy(self):
        reg = self._make_registry()
        reg.register(routing_key="k1", session_id="s1", user_id="U1")

        copy = reg.mappings
        copy["injected"] = "bad"  # type: ignore[assignment]
        assert "injected" not in reg.mappings


class TestRegistryPersistence:
    """Test JSON persistence via atomic_write."""

    def test_save_and_load_round_trip(self, tmp_path):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        path = tmp_path / "sessions.json"

        # Create registry, register a session
        reg1 = SurfaceSessionRegistry("test", persistence_path=path)
        reg1.register(
            routing_key="C1:t1",
            session_id="s1",
            user_id="U1",
            description="round trip",
            channel_id="C1",
            thread_ts="t1",
        )

        # Verify file was written
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["routing_key"] == "C1:t1"
        assert data[0]["extra"]["channel_id"] == "C1"

        # Create a NEW registry from the same file - should load
        reg2 = SurfaceSessionRegistry("test", persistence_path=path)
        loaded = reg2.lookup("C1:t1")
        assert loaded is not None
        assert loaded.session_id == "s1"
        assert loaded.description == "round trip"
        assert loaded.extra["channel_id"] == "C1"
        assert loaded.is_active is True

    def test_persistence_survives_deactivate(self, tmp_path):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        path = tmp_path / "sessions.json"
        reg = SurfaceSessionRegistry("test", persistence_path=path)
        reg.register(routing_key="k1", session_id="s1", user_id="U1")
        reg.deactivate("k1")

        # Reload and verify
        reg2 = SurfaceSessionRegistry("test", persistence_path=path)
        loaded = reg2.lookup("k1")
        assert loaded is not None
        assert loaded.is_active is False

    def test_persistence_no_file_on_startup(self, tmp_path):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        path = tmp_path / "nonexistent" / "sessions.json"
        reg = SurfaceSessionRegistry("test", persistence_path=path)
        assert reg.list_active() == []

    def test_persistence_disabled_when_none(self, tmp_path):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None)
        reg.register(routing_key="k1", session_id="s1", user_id="U1")
        # No file should be created in tmp_path
        assert list(tmp_path.iterdir()) == []

    def test_persistence_handles_corrupt_file(self, tmp_path):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        path = tmp_path / "sessions.json"
        path.write_text("NOT VALID JSON {{{{")

        # Should not raise, just start empty
        reg = SurfaceSessionRegistry("test", persistence_path=path)
        assert reg.list_active() == []

    def test_persistence_no_tmp_files_remain(self, tmp_path):
        """After save, no .tmp files should remain (atomic_write cleans up)."""
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        path = tmp_path / "sessions.json"
        reg = SurfaceSessionRegistry("test", persistence_path=path)
        reg.register(routing_key="k1", session_id="s1", user_id="U1")

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Temp files not cleaned up: {tmp_files}"

    def test_persistence_includes_all_fields(self, tmp_path):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        path = tmp_path / "sessions.json"
        reg = SurfaceSessionRegistry("test", persistence_path=path)
        reg.register(
            routing_key="k1",
            session_id="s1",
            user_id="U1",
            project_id="p1",
            description="full",
        )

        data = json.loads(path.read_text())
        record = data[0]
        required = {
            "routing_key",
            "session_id",
            "surface",
            "project_id",
            "description",
            "created_by",
            "created_at",
            "last_active",
            "is_active",
            "extra",
        }
        for f in required:
            assert f in record, f"Missing field: {f}"


class TestRegistryLimits:
    """Test per-user session limit enforcement."""

    def test_check_limit_allows_under_cap(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None, max_per_user=3)
        reg.register(routing_key="k1", session_id="s1", user_id="U1")
        reg.register(routing_key="k2", session_id="s2", user_id="U1")

        reg.check_limit("U1")  # should not raise (2 < 3)

    def test_check_limit_raises_at_cap(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None, max_per_user=2)
        reg.register(routing_key="k1", session_id="s1", user_id="U1")
        reg.register(routing_key="k2", session_id="s2", user_id="U1")

        with pytest.raises(ValueError, match="Session limit reached"):
            reg.check_limit("U1")

    def test_check_limit_ignores_inactive(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None, max_per_user=2)
        reg.register(routing_key="k1", session_id="s1", user_id="U1")
        reg.register(routing_key="k2", session_id="s2", user_id="U1")
        reg.deactivate("k1")

        reg.check_limit("U1")  # should not raise (1 active < 2)

    def test_check_limit_scoped_to_user(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None, max_per_user=1)
        reg.register(routing_key="k1", session_id="s1", user_id="U1")

        reg.check_limit("U2")  # different user, should not raise

    def test_check_limit_error_message_includes_cap(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None, max_per_user=5)
        for i in range(5):
            reg.register(routing_key=f"k{i}", session_id=f"s{i}", user_id="U1")

        with pytest.raises(ValueError, match="5"):
            reg.check_limit("U1")


class TestRegistryQueries:
    """Test list_active and list_for_user."""

    def test_list_active_filters_inactive(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None)
        reg.register(routing_key="k1", session_id="s1", user_id="U1")
        reg.register(routing_key="k2", session_id="s2", user_id="U1")
        reg.deactivate("k1")

        active = reg.list_active()
        assert len(active) == 1
        assert active[0].routing_key == "k2"

    def test_list_active_empty(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None)
        assert reg.list_active() == []

    def test_list_for_user(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None)
        reg.register(routing_key="k1", session_id="s1", user_id="U1")
        reg.register(routing_key="k2", session_id="s2", user_id="U1")
        reg.register(routing_key="k3", session_id="s3", user_id="U2")

        u1 = reg.list_for_user("U1")
        assert len(u1) == 2

        u2 = reg.list_for_user("U2")
        assert len(u2) == 1

    def test_list_for_user_excludes_inactive(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None)
        reg.register(routing_key="k1", session_id="s1", user_id="U1")
        reg.register(routing_key="k2", session_id="s2", user_id="U1")
        reg.deactivate("k1")

        assert len(reg.list_for_user("U1")) == 1


class TestSlackMigration:
    """Test backward-compatible loading of old Slack session format.

    The existing slack-sessions.json has channel_id and thread_ts as
    top-level fields with no routing_key or extra. The registry must
    detect this and construct the correct routing_key + extra.
    """

    def test_load_old_slack_format(self, tmp_path):
        """Registry loads old format with channel_id/thread_ts, no routing_key."""
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        path = tmp_path / "sessions.json"
        old_data = [
            {
                "session_id": "s1",
                "channel_id": "C1",
                "thread_ts": "t1",
                "project_id": "p1",
                "description": "old format",
                "created_by": "U1",
                "created_at": "2025-01-01T00:00:00",
                "last_active": "2025-01-01T00:00:00",
                "is_active": True,
            }
        ]
        path.write_text(json.dumps(old_data))

        reg = SurfaceSessionRegistry("slack", persistence_path=path)
        # Should have constructed routing_key from channel_id:thread_ts
        found = reg.lookup("C1:t1")
        assert found is not None
        assert found.session_id == "s1"
        assert found.extra["channel_id"] == "C1"
        assert found.extra["thread_ts"] == "t1"

    def test_load_old_format_channel_only(self, tmp_path):
        """Old format entry with no thread_ts uses channel_id as routing_key."""
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        path = tmp_path / "sessions.json"
        old_data = [
            {
                "session_id": "s1",
                "channel_id": "C1",
                "thread_ts": None,
                "project_id": "",
                "description": "",
                "created_by": "U1",
                "created_at": "",
                "last_active": "",
                "is_active": True,
            }
        ]
        path.write_text(json.dumps(old_data))

        reg = SurfaceSessionRegistry("slack", persistence_path=path)
        found = reg.lookup("C1")
        assert found is not None
        assert found.extra["channel_id"] == "C1"


class TestRegistryReactivate:
    """Test reactivate method."""

    def test_reactivate_inactive_session(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None)
        reg.register(routing_key="k1", session_id="s1", user_id="U1")
        reg.deactivate("k1")
        m = reg.lookup("k1")
        assert m is not None
        assert m.is_active is False

        reg.reactivate("k1")
        m = reg.lookup("k1")
        assert m is not None
        assert m.is_active is True

    def test_reactivate_updates_last_active(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None)
        reg.register(routing_key="k1", session_id="s1", user_id="U1")
        reg.deactivate("k1")
        m = reg.lookup("k1")
        assert m is not None
        old_ts = m.last_active

        reg.reactivate("k1")
        m = reg.lookup("k1")
        assert m is not None
        assert m.last_active >= old_ts

    def test_reactivate_missing_key_is_noop(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None)
        reg.reactivate("nonexistent")  # no error

    def test_reactivate_already_active_is_noop(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None)
        reg.register(routing_key="k1", session_id="s1", user_id="U1")
        reg.reactivate("k1")  # already active, should not error
        m = reg.lookup("k1")
        assert m is not None
        assert m.is_active is True


class TestRegistryListAll:
    """Test list_all method."""

    def test_list_all_includes_inactive(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None)
        reg.register(routing_key="k1", session_id="s1", user_id="U1")
        reg.register(routing_key="k2", session_id="s2", user_id="U1")
        reg.deactivate("k1")

        all_sessions = reg.list_all()
        assert len(all_sessions) == 2
        active = reg.list_active()
        assert len(active) == 1

    def test_list_all_empty(self):
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        reg = SurfaceSessionRegistry("test", persistence_path=None)
        assert reg.list_all() == []

    def test_new_format_loads_normally(self, tmp_path):
        """New format with routing_key loads without migration."""
        from amplifier_distro.server.surface_registry import SurfaceSessionRegistry

        path = tmp_path / "sessions.json"
        new_data = [
            {
                "routing_key": "C1:t1",
                "session_id": "s1",
                "surface": "slack",
                "project_id": "p1",
                "description": "new format",
                "created_by": "U1",
                "created_at": "2025-01-01T00:00:00",
                "last_active": "2025-01-01T00:00:00",
                "is_active": True,
                "extra": {"channel_id": "C1", "thread_ts": "t1"},
            }
        ]
        path.write_text(json.dumps(new_data))

        reg = SurfaceSessionRegistry("slack", persistence_path=path)
        found = reg.lookup("C1:t1")
        assert found is not None
        assert found.extra["channel_id"] == "C1"
