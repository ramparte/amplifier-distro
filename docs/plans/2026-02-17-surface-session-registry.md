# Shared Surface Session Registry — Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Extract duplicated session management (persistence, limits, lifecycle, queries) into a shared `SurfaceSessionRegistry` service that Slack, Web Chat, and future surfaces take as a constructor dependency.

**Architecture:** Composition, not inheritance — matching the codebase's existing patterns of Protocols + dependency injection. `SurfaceSessionRegistry` is a service class that surfaces own via `self._registry`. The registry handles persistence (via `atomic_write`), per-user limits, activity tracking, and queries. Surfaces keep their own routing logic, API-specific code, and backend interaction.

**Tech Stack:** Python 3.12, dataclasses, `atomic_write` from `fileutil.py`, pytest, `asyncio.run()` in tests.

---

## Task 1: Create `SessionMapping` dataclass and `SurfaceSessionRegistry` service

### Task 1a: Write the failing tests for `SessionMapping`

**Files:**
- Create: `tests/test_surface_registry.py`

**Step 1: Write the failing tests**

Create `tests/test_surface_registry.py` with the following content:

```python
"""Tests for the shared SurfaceSessionRegistry.

Covers: SessionMapping dataclass, registry CRUD, persistence,
per-user limits, and queries.
"""

import json
from pathlib import Path

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
```

**Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_surface_registry.py::TestSessionMapping -x -q`

Expected: `ModuleNotFoundError: No module named 'amplifier_distro.server.surface_registry'`

**Step 3: Write minimal `SessionMapping` implementation**

Create `src/amplifier_distro/server/surface_registry.py`:

```python
"""Shared Surface Session Registry.

Provides a reusable session-mapping service that any surface (Slack,
Web Chat, Voice, etc.) can take as a constructor dependency.

The registry owns:
- Mapping storage (routing_key -> SessionMapping)
- Persistence (JSON via atomic_write)
- Per-user session limits
- Activity tracking and lifecycle (active/inactive)
- Queries (by routing key, session ID, user, active status)

Surfaces own:
- Routing key construction (surface-specific)
- Backend interaction (create_session, send_message, end_session)
- Surface-specific API calls (Slack threads, web sockets, etc.)

Design: Composition, not inheritance. Surfaces hold a registry
instance — they do NOT extend it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SessionMapping:
    """Maps a surface-specific routing key to an Amplifier session.

    Universal fields live as typed attributes. Surface-specific fields
    (e.g. Slack's channel_id, thread_ts) go in ``extra``.
    """

    routing_key: str
    session_id: str
    surface: str = ""
    project_id: str = ""
    description: str = ""
    created_by: str = ""
    created_at: str = ""
    last_active: str = ""
    is_active: bool = True
    extra: dict = field(default_factory=dict)
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_surface_registry.py::TestSessionMapping -x -q`

Expected: All 4 tests PASS.

---

### Task 1b: Write the failing tests for registry CRUD operations

**Files:**
- Modify: `tests/test_surface_registry.py` (append)
- Modify: `src/amplifier_distro/server/surface_registry.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_surface_registry.py`:

```python
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
        copy["injected"] = "bad"
        assert "injected" not in reg.mappings
```

**Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_surface_registry.py::TestRegistryCRUD -x -q`

Expected: `ImportError` — `SurfaceSessionRegistry` does not exist yet.

**Step 3: Write the `SurfaceSessionRegistry` class**

Append to `src/amplifier_distro/server/surface_registry.py`:

```python
class SurfaceSessionRegistry:
    """Shared session-mapping service.

    Surfaces take this as a constructor dependency and delegate
    persistence, limits, and queries to it.

    Args:
        surface_name: Identifier for the surface ("slack", "web-chat").
        persistence_path: JSON file for persistence. None disables persistence.
        max_per_user: Maximum active sessions per user_id.
    """

    def __init__(
        self,
        surface_name: str,
        persistence_path: Path | None,
        max_per_user: int = 10,
    ) -> None:
        self._surface = surface_name
        self._persistence_path = persistence_path
        self._max_per_user = max_per_user
        self._mappings: dict[str, SessionMapping] = {}
        self._load()

    # --- Persistence ---

    def _load(self) -> None:
        """Load session mappings from the persistence file."""
        if self._persistence_path is None or not self._persistence_path.exists():
            return
        try:
            data = json.loads(self._persistence_path.read_text())
            for entry in data:
                # Handle old Slack format: has channel_id but no routing_key
                if "routing_key" not in entry and "channel_id" in entry:
                    channel_id = entry["channel_id"]
                    thread_ts = entry.get("thread_ts")
                    if thread_ts:
                        routing_key = f"{channel_id}:{thread_ts}"
                    else:
                        routing_key = channel_id
                    extra = {
                        "channel_id": channel_id,
                        "thread_ts": thread_ts or "",
                    }
                    mapping = SessionMapping(
                        routing_key=routing_key,
                        session_id=entry["session_id"],
                        surface=entry.get("surface", self._surface),
                        project_id=entry.get("project_id", ""),
                        description=entry.get("description", ""),
                        created_by=entry.get("created_by", ""),
                        created_at=entry.get("created_at", ""),
                        last_active=entry.get("last_active", ""),
                        is_active=entry.get("is_active", True),
                        extra=extra,
                    )
                else:
                    mapping = SessionMapping(
                        routing_key=entry["routing_key"],
                        session_id=entry["session_id"],
                        surface=entry.get("surface", self._surface),
                        project_id=entry.get("project_id", ""),
                        description=entry.get("description", ""),
                        created_by=entry.get("created_by", ""),
                        created_at=entry.get("created_at", ""),
                        last_active=entry.get("last_active", ""),
                        is_active=entry.get("is_active", True),
                        extra=entry.get("extra", {}),
                    )
                self._mappings[mapping.routing_key] = mapping
            logger.info(
                f"Loaded {len(data)} session mappings from "
                f"{self._persistence_path}"
            )
        except (json.JSONDecodeError, KeyError, OSError):
            logger.warning("Failed to load session mappings", exc_info=True)

    def _save(self) -> None:
        """Save session mappings to the persistence file via atomic_write."""
        if self._persistence_path is None:
            return
        try:
            from amplifier_distro.fileutil import atomic_write

            data = [
                {
                    "routing_key": m.routing_key,
                    "session_id": m.session_id,
                    "surface": m.surface,
                    "project_id": m.project_id,
                    "description": m.description,
                    "created_by": m.created_by,
                    "created_at": m.created_at,
                    "last_active": m.last_active,
                    "is_active": m.is_active,
                    "extra": m.extra,
                }
                for m in self._mappings.values()
            ]
            atomic_write(self._persistence_path, json.dumps(data, indent=2))
        except OSError:
            logger.warning("Failed to save session mappings", exc_info=True)

    # --- Registration ---

    def register(
        self,
        routing_key: str,
        session_id: str,
        user_id: str,
        project_id: str = "",
        description: str = "",
        **extra: str,
    ) -> SessionMapping:
        """Register a new session mapping.

        Any keyword arguments beyond the named parameters are stored
        in ``mapping.extra`` for surface-specific fields.
        """
        now = datetime.now(UTC).isoformat()
        mapping = SessionMapping(
            routing_key=routing_key,
            session_id=session_id,
            surface=self._surface,
            project_id=project_id,
            description=description,
            created_by=user_id,
            created_at=now,
            last_active=now,
            extra=dict(extra),
        )
        self._mappings[routing_key] = mapping
        self._save()
        return mapping

    # --- Lookup ---

    def lookup(self, routing_key: str) -> SessionMapping | None:
        """Find a mapping by routing key."""
        return self._mappings.get(routing_key)

    def lookup_by_session_id(self, session_id: str) -> SessionMapping | None:
        """Find a mapping by Amplifier session ID (linear scan)."""
        for mapping in self._mappings.values():
            if mapping.session_id == session_id:
                return mapping
        return None

    # --- Lifecycle ---

    def update_activity(self, routing_key: str) -> None:
        """Update the last_active timestamp for a mapping."""
        mapping = self._mappings.get(routing_key)
        if mapping is None:
            return
        mapping.last_active = datetime.now(UTC).isoformat()
        self._save()

    def deactivate(self, routing_key: str) -> None:
        """Mark a mapping as inactive."""
        mapping = self._mappings.get(routing_key)
        if mapping is None:
            return
        mapping.is_active = False
        self._save()

    def remove(self, routing_key: str) -> SessionMapping | None:
        """Remove a mapping entirely. Returns the removed mapping or None."""
        mapping = self._mappings.pop(routing_key, None)
        if mapping is not None:
            self._save()
        return mapping

    # --- Queries ---

    def list_active(self) -> list[SessionMapping]:
        """List all active mappings."""
        return [m for m in self._mappings.values() if m.is_active]

    def list_for_user(self, user_id: str) -> list[SessionMapping]:
        """List active mappings for a specific user."""
        return [
            m
            for m in self._mappings.values()
            if m.created_by == user_id and m.is_active
        ]

    # --- Limits ---

    def check_limit(self, user_id: str) -> None:
        """Raise ValueError if the user has reached the session limit."""
        active = self.list_for_user(user_id)
        if len(active) >= self._max_per_user:
            raise ValueError(
                f"Session limit reached ({self._max_per_user}). "
                "End an existing session first."
            )

    # --- Properties ---

    @property
    def mappings(self) -> dict[str, SessionMapping]:
        """Current mappings (read-only copy)."""
        return dict(self._mappings)
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_surface_registry.py::TestRegistryCRUD -x -q`

Expected: All 13 tests PASS.

**Step 5: Commit**

```
git add src/amplifier_distro/server/surface_registry.py tests/test_surface_registry.py
git commit -m "feat(#27): add SessionMapping and SurfaceSessionRegistry with CRUD tests"
```

---

### Task 1c: Write tests for registry persistence

**Files:**
- Modify: `tests/test_surface_registry.py` (append)

**Step 1: Write the persistence tests**

Append to `tests/test_surface_registry.py`:

```python
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

        # Create a NEW registry from the same file — should load
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
```

**Step 2: Run tests to verify they pass**

These tests exercise code already written in Task 1b. They should pass immediately.

Run: `uv run python -m pytest tests/test_surface_registry.py::TestRegistryPersistence -x -q`

Expected: All 7 tests PASS.

**Step 3: Commit**

```
git add tests/test_surface_registry.py
git commit -m "test(#27): add persistence tests for SurfaceSessionRegistry"
```

---

### Task 1d: Write tests for per-user limits

**Files:**
- Modify: `tests/test_surface_registry.py` (append)

**Step 1: Write the limit tests**

Append to `tests/test_surface_registry.py`:

```python
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
            reg.register(
                routing_key=f"k{i}", session_id=f"s{i}", user_id="U1"
            )

        with pytest.raises(ValueError, match="5"):
            reg.check_limit("U1")
```

**Step 2: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_surface_registry.py::TestRegistryLimits -x -q`

Expected: All 5 tests PASS.

---

### Task 1e: Write tests for query methods

**Files:**
- Modify: `tests/test_surface_registry.py` (append)

**Step 1: Write the query tests**

Append to `tests/test_surface_registry.py`:

```python
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
```

**Step 2: Run full test file**

Run: `uv run python -m pytest tests/test_surface_registry.py -x -q`

Expected: All tests PASS (approximately 33 tests total).

**Step 3: Commit**

```
git add tests/test_surface_registry.py
git commit -m "test(#27): add limit and query tests for SurfaceSessionRegistry"
```

---

### Task 1f: Write tests for backward-compatible Slack format loading

**Files:**
- Modify: `tests/test_surface_registry.py` (append)

**Step 1: Write the migration tests**

Append to `tests/test_surface_registry.py`:

```python
class TestSlackMigration:
    """Test backward-compatible loading of old Slack session format.

    The existing slack-sessions.json has channel_id and thread_ts as
    top-level fields with no routing_key or extra. The registry must
    detect this and construct the correct routing_key + extra.
    """

    def test_load_old_slack_format(self, tmp_path):
        """Registry loads old format that has channel_id/thread_ts but no routing_key."""
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
```

**Step 2: Run tests to verify they pass**

These tests exercise the migration logic already in the `_load()` method from Task 1b.

Run: `uv run python -m pytest tests/test_surface_registry.py::TestSlackMigration -x -q`

Expected: All 3 tests PASS.

**Step 3: Commit**

```
git add tests/test_surface_registry.py
git commit -m "test(#27): add backward-compatible Slack format migration tests"
```

---

## Task 2: Integrate `SurfaceSessionRegistry` into `SlackSessionManager`

### Task 2a: Add registry integration test for Slack

**Files:**
- Modify: `tests/test_slack_bridge.py` (append new test class)

**Step 1: Write the failing integration test**

Append to `tests/test_slack_bridge.py`:

```python
class TestSlackRegistryIntegration:
    """Verify SlackSessionManager delegates to SurfaceSessionRegistry."""

    def test_manager_has_registry(self, session_manager):
        assert hasattr(session_manager, "_registry")

    def test_registry_surface_is_slack(self, session_manager):
        assert session_manager._registry._surface == "slack"

    def test_create_session_registers_in_registry(self, session_manager):
        mapping = asyncio.run(
            session_manager.create_session("C1", "t1", "U1", "test")
        )
        key = f"C1:t1"
        found = session_manager._registry.lookup(key)
        assert found is not None
        assert found.extra["channel_id"] == "C1"
        assert found.extra["thread_ts"] == "t1"
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_slack_bridge.py::TestSlackRegistryIntegration -x -q`

Expected: `AttributeError: 'SlackSessionManager' object has no attribute '_registry'`

### Task 2b: Refactor `SlackSessionManager` to use the registry

**Files:**
- Modify: `src/amplifier_distro/server/apps/slack/sessions.py`

This is the most complex task. The refactoring replaces internal storage and persistence with registry delegation while preserving the exact behavioral contract.

**Step 3: Refactor sessions.py**

Changes to `src/amplifier_distro/server/apps/slack/sessions.py`:

1. **Update imports** at top of file (around line 28):
   - Add: `from amplifier_distro.server.surface_registry import SessionMapping as RegistryMapping, SurfaceSessionRegistry`
   - In the `.models` import line, remove `SessionMapping` (keep `SlackChannel, SlackMessage`)
   - Remove `import json` (no longer needed)

2. **Add a type alias** for backward compatibility:
   ```python
   # The registry's SessionMapping is now the canonical type.
   # Alias for backward compatibility with code that imports from here.
   SessionMapping = RegistryMapping
   ```

3. **Replace `__init__`** (lines 59-74):
   ```python
       def __init__(
           self,
           client: SlackClient,
           backend: SessionBackend,
           config: SlackConfig,
           persistence_path: Path | None = None,
       ) -> None:
           self._client = client
           self._backend = backend
           self._config = config
           self._registry = SurfaceSessionRegistry(
               "slack", persistence_path, self._config.max_sessions_per_user,
           )
           # Track which channels are breakout channels
           self._breakout_channels: dict[str, str] = {}  # channel_id -> session_id
   ```

4. **Delete `_load_sessions`** (lines 76-100) — registry handles this.

5. **Delete `_save_sessions`** (lines 102-126) — registry handles this.

6. **Replace `mappings` property** (lines 128-131):
   ```python
       @property
       def mappings(self) -> dict[str, RegistryMapping]:
           """Current mappings (read-only view)."""
           return self._registry.mappings
   ```

7. **Replace `get_mapping`** (lines 133-155):
   ```python
       def get_mapping(
           self, channel_id: str, thread_ts: str | None = None
       ) -> RegistryMapping | None:
           """Find the session mapping for a Slack conversation context.

           Uses the registry for lookup but implements Slack's 3-tier
           routing: thread -> channel -> breakout registry.
           """
           if thread_ts:
               key = f"{channel_id}:{thread_ts}"
               found = self._registry.lookup(key)
               if found is not None:
                   return found

           found = self._registry.lookup(channel_id)
           if found is not None:
               return found

           if channel_id in self._breakout_channels:
               session_id = self._breakout_channels[channel_id]
               return self._registry.lookup_by_session_id(session_id)

           return None
   ```

8. **Replace `get_mapping_by_session`** (lines 157-162):
   ```python
       def get_mapping_by_session(self, session_id: str) -> RegistryMapping | None:
           """Find mapping by Amplifier session ID."""
           return self._registry.lookup_by_session_id(session_id)
   ```

9. **Replace `create_session`** (lines 164-212):
   ```python
       async def create_session(
           self,
           channel_id: str,
           thread_ts: str | None,
           user_id: str,
           description: str = "",
       ) -> RegistryMapping:
           """Create a new Amplifier session and map it to a Slack context."""
           self._registry.check_limit(user_id)

           info = await self._backend.create_session(
               working_dir=self._config.default_working_dir,
               bundle_name=self._config.default_bundle,
               description=description,
           )

           key = f"{channel_id}:{thread_ts}" if thread_ts else channel_id

           mapping = self._registry.register(
               routing_key=key,
               session_id=info.session_id,
               user_id=user_id,
               project_id=info.project_id,
               description=description,
               channel_id=channel_id,
               thread_ts=thread_ts or "",
           )
           logger.info(f"Created session {info.session_id} mapped to {key}")
           return mapping
   ```

10. **Replace `connect_session`** (lines 214-266) — same pattern as `create_session`:
    ```python
        async def connect_session(
            self,
            channel_id: str,
            thread_ts: str | None,
            user_id: str,
            working_dir: str,
            description: str = "",
        ) -> RegistryMapping:
            """Connect a Slack context to a new backend session in *working_dir*."""
            self._registry.check_limit(user_id)

            info = await self._backend.create_session(
                working_dir=working_dir,
                bundle_name=self._config.default_bundle,
                description=description,
            )

            key = f"{channel_id}:{thread_ts}" if thread_ts else channel_id

            mapping = self._registry.register(
                routing_key=key,
                session_id=info.session_id,
                user_id=user_id,
                project_id=info.project_id,
                description=description,
                channel_id=channel_id,
                thread_ts=thread_ts or "",
            )
            logger.info(
                f"Connected session {info.session_id} (in {working_dir}) "
                f"mapped to {key}"
            )
            return mapping
    ```

11. **Replace `route_message`** (lines 268-290):
    ```python
        async def route_message(self, message: SlackMessage) -> str | None:
            """Route a Slack message to the appropriate Amplifier session."""
            mapping = self.get_mapping(message.channel_id, message.thread_ts)
            if mapping is None or not mapping.is_active:
                return None

            self._registry.update_activity(mapping.routing_key)

            try:
                response = await self._backend.send_message(
                    mapping.session_id, message.text
                )
                return response
            except Exception:
                logger.exception(
                    f"Error routing message to session {mapping.session_id}"
                )
                return "Error: Failed to get response from Amplifier session."
    ```

12. **Replace `end_session`** (lines 292-308):
    ```python
        async def end_session(
            self, channel_id: str, thread_ts: str | None = None
        ) -> bool:
            """End the session mapped to a Slack context."""
            mapping = self.get_mapping(channel_id, thread_ts)
            if mapping is None:
                return False

            self._registry.deactivate(mapping.routing_key)
            try:
                await self._backend.end_session(mapping.session_id)
            except (RuntimeError, ValueError, ConnectionError, OSError):
                logger.exception(f"Error ending session {mapping.session_id}")

            return True
    ```

13. **Replace `breakout_to_channel`** (lines 310-357):
    ```python
        async def breakout_to_channel(
            self,
            channel_id: str,
            thread_ts: str,
            channel_name: str | None = None,
        ) -> SlackChannel | None:
            """Promote a thread-based session to its own channel."""
            mapping = self.get_mapping(channel_id, thread_ts)
            if mapping is None:
                return None

            if not self._config.allow_breakout:
                raise ValueError("Channel breakout is not enabled.")

            if channel_name is None:
                short_id = mapping.session_id[:8]
                channel_name = f"{self._config.channel_prefix}{short_id}"

            topic = f"Amplifier session {mapping.session_id[:8]}"
            if mapping.description:
                topic += f" - {mapping.description}"

            new_channel = await self._client.create_channel(
                channel_name, topic=topic
            )

            # Remove old mapping, register new one under channel key
            self._registry.remove(mapping.routing_key)

            self._registry.register(
                routing_key=new_channel.id,
                session_id=mapping.session_id,
                user_id=mapping.created_by,
                project_id=mapping.project_id,
                description=mapping.description,
                channel_id=new_channel.id,
                thread_ts="",
            )
            self._breakout_channels[new_channel.id] = mapping.session_id

            await self._client.post_message(
                new_channel.id,
                f"Session `{mapping.session_id[:8]}` moved to this channel."
                " Continue the conversation here.",
            )

            return new_channel
    ```

14. **Replace `list_active`** (lines 359-361):
    ```python
        def list_active(self) -> list[RegistryMapping]:
            """List all active session mappings."""
            return self._registry.list_active()
    ```

15. **Replace `list_user_sessions`** (lines 363-369):
    ```python
        def list_user_sessions(self, user_id: str) -> list[RegistryMapping]:
            """List active sessions for a specific user."""
            return self._registry.list_for_user(user_id)
    ```

**Step 4: Update call sites that access `mapping.channel_id` and `mapping.thread_ts`**

These are now in `mapping.extra["channel_id"]` and `mapping.extra["thread_ts"]`. The `conversation_key` property is replaced by `routing_key`.

Files to check (use grep: `mapping\.channel_id|mapping\.thread_ts|mapping\.conversation_key`):

- `src/amplifier_distro/server/apps/slack/commands.py` — uses `mapping.session_id`, `mapping.description`, `mapping.channel_id`, `mapping.created_by`, `mapping.project_id`, `mapping.conversation_key`. Update `.channel_id` to `.extra["channel_id"]` and `.conversation_key` to `.routing_key`.

- `src/amplifier_distro/server/apps/slack/__init__.py` — uses `mapping.session_id`, `mapping.channel_id`. Update `.channel_id` to `.extra["channel_id"]`.

- `src/amplifier_distro/server/apps/slack/formatter.py` — uses `SessionMapping` fields for formatting session lists. Update field access as needed.

- `tests/test_slack_bridge.py` — tests that assert on `mapping.channel_id`, `mapping.thread_ts`, `mapping.conversation_key`. Update to use `.extra["channel_id"]`, `.extra["thread_ts"]`, `.routing_key`.

**Step 5: Run ALL existing Slack tests**

Run: `uv run python -m pytest tests/test_slack_bridge.py -x -q`

Expected: All existing tests PASS. The behavioral contract is identical.

**Step 6: Run python_check on modified files**

Run: `uv run python -m pytest tests/test_slack_bridge.py tests/test_surface_registry.py -x -q`

Expected: All tests PASS.

**Step 7: Commit**

```
git add src/amplifier_distro/server/surface_registry.py \
        src/amplifier_distro/server/apps/slack/sessions.py \
        src/amplifier_distro/server/apps/slack/commands.py \
        src/amplifier_distro/server/apps/slack/__init__.py \
        src/amplifier_distro/server/apps/slack/formatter.py \
        tests/test_slack_bridge.py
git commit -m "refactor(#27): SlackSessionManager delegates to SurfaceSessionRegistry"
```

---

## Task 3: Create `WebChatSessionManager`

### Task 3a: Write failing tests and implement the manager

**Files:**
- Modify: `tests/test_web_chat.py`
- Modify: `src/amplifier_distro/server/apps/web_chat/__init__.py`

**Step 1: Write the failing tests**

Add `import asyncio` to the top of `tests/test_web_chat.py` if not already present. Then append a new test class:

```python
class TestWebChatSessionManager:
    """Verify the WebChatSessionManager uses the registry."""

    def test_manager_exists(self):
        from amplifier_distro.server.apps.web_chat import WebChatSessionManager

        assert WebChatSessionManager is not None

    def test_create_and_get_active(self):
        from amplifier_distro.server.apps.web_chat import WebChatSessionManager
        from amplifier_distro.server.session_backend import MockBackend

        backend = MockBackend()
        mgr = WebChatSessionManager(backend)

        info = asyncio.run(mgr.create_session())
        assert info.session_id.startswith("mock-session-")
        assert mgr.active_session_id == info.session_id

    def test_end_session(self):
        from amplifier_distro.server.apps.web_chat import WebChatSessionManager
        from amplifier_distro.server.session_backend import MockBackend

        backend = MockBackend()
        mgr = WebChatSessionManager(backend)

        asyncio.run(mgr.create_session())
        ended = asyncio.run(mgr.end_session())
        assert ended is True
        assert mgr.active_session_id is None

    def test_send_message(self):
        from amplifier_distro.server.apps.web_chat import WebChatSessionManager
        from amplifier_distro.server.session_backend import MockBackend

        backend = MockBackend()
        mgr = WebChatSessionManager(backend)

        asyncio.run(mgr.create_session())
        response = asyncio.run(mgr.send_message("hello"))
        assert response is not None
        assert "hello" in response

    def test_send_message_no_session(self):
        from amplifier_distro.server.apps.web_chat import WebChatSessionManager
        from amplifier_distro.server.session_backend import MockBackend

        backend = MockBackend()
        mgr = WebChatSessionManager(backend)

        response = asyncio.run(mgr.send_message("hello"))
        assert response is None

    def test_create_ends_previous_session(self):
        from amplifier_distro.server.apps.web_chat import WebChatSessionManager
        from amplifier_distro.server.session_backend import MockBackend

        backend = MockBackend()
        mgr = WebChatSessionManager(backend)

        info1 = asyncio.run(mgr.create_session())
        info2 = asyncio.run(mgr.create_session())
        assert mgr.active_session_id == info2.session_id
        assert mgr.active_session_id != info1.session_id
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_web_chat.py::TestWebChatSessionManager -x -q`

Expected: `ImportError: cannot import name 'WebChatSessionManager'`

**Step 3: Implement `WebChatSessionManager`**

In `src/amplifier_distro/server/apps/web_chat/__init__.py`, add these imports near the top (after the existing imports, around line 28):

```python
from amplifier_distro.server.session_backend import SessionBackend, SessionInfo
from amplifier_distro.server.surface_registry import SurfaceSessionRegistry
```

Then add the class **before** the route handlers (after the memory pattern matching code, around line 77):

```python
class WebChatSessionManager:
    """Manages the active web-chat session using the shared registry.

    Simple model: one active session at a time (max_per_user=1).
    Gains persistence and structured lifecycle from the registry.
    """

    def __init__(
        self,
        backend: SessionBackend,
        persistence_path: Path | None = None,
    ) -> None:
        self._backend = backend
        self._registry = SurfaceSessionRegistry(
            "web-chat", persistence_path, max_per_user=1,
        )
        self._lock = asyncio.Lock()

    @property
    def active_session_id(self) -> str | None:
        """Return the active session ID, or None."""
        active = self._registry.list_active()
        if active:
            return active[0].session_id
        return None

    async def create_session(
        self,
        working_dir: str = "~",
        description: str = "Web chat session",
    ) -> SessionInfo:
        """Create a new session, ending any existing one first."""
        async with self._lock:
            # End existing session if any
            active_id = self.active_session_id
            if active_id:
                await self._end_active(active_id)

            info = await self._backend.create_session(
                working_dir=working_dir,
                description=description,
            )
            self._registry.register(
                routing_key=info.session_id,
                session_id=info.session_id,
                user_id="web-chat",
                project_id=info.project_id,
                description=description,
            )
            return info

    async def send_message(self, message: str) -> str | None:
        """Send a message to the active session. Returns None if no session."""
        async with self._lock:
            active_id = self.active_session_id
            if active_id is None:
                return None
            mapping = self._registry.lookup_by_session_id(active_id)
            if mapping:
                self._registry.update_activity(mapping.routing_key)
            return await self._backend.send_message(active_id, message)

    async def end_session(self) -> bool:
        """End the active session. Returns True if one was ended."""
        async with self._lock:
            active_id = self.active_session_id
            if active_id is None:
                return False
            await self._end_active(active_id)
            return True

    async def _end_active(self, session_id: str) -> None:
        """Deactivate and end a session."""
        mapping = self._registry.lookup_by_session_id(session_id)
        if mapping:
            self._registry.deactivate(mapping.routing_key)
        try:
            await self._backend.end_session(session_id)
        except (RuntimeError, ValueError, OSError):
            logger.warning(
                "Error ending session %s", session_id, exc_info=True
            )
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_web_chat.py::TestWebChatSessionManager -x -q`

Expected: All 6 tests PASS.

**Step 5: Commit**

```
git add src/amplifier_distro/server/apps/web_chat/__init__.py tests/test_web_chat.py
git commit -m "feat(#27): add WebChatSessionManager backed by SurfaceSessionRegistry"
```

---

### Task 3b: Wire `WebChatSessionManager` into route handlers

**Files:**
- Modify: `src/amplifier_distro/server/apps/web_chat/__init__.py`
- Modify: `tests/test_web_chat.py`

**Step 1: Replace module globals with manager**

In `src/amplifier_distro/server/apps/web_chat/__init__.py`:

1. **Remove** the module-level globals (lines 38-41):
   ```python
   # DELETE these lines:
   _active_session_id: str | None = None
   _session_lock = asyncio.Lock()
   ```

2. **Add** a module-level manager and lazy initializer:
   ```python
   _manager: WebChatSessionManager | None = None


   def _get_manager() -> WebChatSessionManager:
       """Get or create the WebChatSessionManager."""
       global _manager
       if _manager is None:
           _manager = WebChatSessionManager(_get_backend())
       return _manager
   ```

3. **Update `session_status` route** (around line 145): Replace `global _active_session_id` and `_session_lock` usage with `_get_manager()`. The manager's `active_session_id` property replaces the global variable.

4. **Update `create_session` route** (around line 188): Use `mgr = _get_manager()` and call `await mgr.create_session(...)`. Remove the inline backend calls and `global _active_session_id`.

5. **Update `chat` route** (around line 237): Use `mgr = _get_manager()` for session ID checks and message sending.

6. **Update `end_session` route** (around line 320): Use `mgr = _get_manager()` and `await mgr.end_session()`.

**Step 2: Update the webchat_client fixture**

In `tests/test_web_chat.py`, update the `webchat_client` fixture (around line 39):

```python
@pytest.fixture
def webchat_client() -> TestClient:
    """Create a TestClient with web-chat app and services initialized."""
    import amplifier_distro.server.apps.web_chat as wc

    # Reset module-level manager state
    wc._manager = None

    init_services(dev_mode=True)

    from amplifier_distro.server.apps.web_chat import manifest

    server = DistroServer()
    server.register_app(manifest)
    return TestClient(server.app)
```

**Step 3: Run all existing web chat tests**

Run: `uv run python -m pytest tests/test_web_chat.py -x -q`

Expected: All existing tests PASS. Zero behavioral changes to the HTTP API.

**Step 4: Commit**

```
git add src/amplifier_distro/server/apps/web_chat/__init__.py tests/test_web_chat.py
git commit -m "refactor(#27): wire WebChatSessionManager into web-chat route handlers"
```

---

## Task 4: Clean up

### Task 4a: Remove dead code and verify everything

**Files:**
- Modify: `src/amplifier_distro/server/apps/slack/models.py`
- Possibly modify: `src/amplifier_distro/conventions.py`

**Step 1: Check if old `SessionMapping` in `slack/models.py` is still imported**

Run: `grep -rn "from.*slack.*models.*import.*SessionMapping" src/ tests/`

If nothing imports it, delete the `SessionMapping` class from `src/amplifier_distro/server/apps/slack/models.py` (lines 66-89). Keep `ChannelType`, `SlackUser`, `SlackChannel`, and `SlackMessage`.

If imports remain, update them to import from `amplifier_distro.server.surface_registry` instead, then delete the old class.

**Step 2: Optionally add web-chat sessions filename to conventions**

If the web-chat manager is wired to use persistence in production, add to `src/amplifier_distro/conventions.py` after line 72:

```python
WEB_CHAT_SESSIONS_FILENAME = "web-chat-sessions.json"
```

Skip this if web-chat persistence remains disabled (None) for now.

**Step 3: Run full test suite**

Run: `uv run python -m pytest tests/ -x -q`

Expected: ALL tests PASS.

**Step 4: Run code quality check**

Run python_check on all modified files:
- `src/amplifier_distro/server/surface_registry.py`
- `src/amplifier_distro/server/apps/slack/sessions.py`
- `src/amplifier_distro/server/apps/slack/models.py`
- `src/amplifier_distro/server/apps/slack/commands.py`
- `src/amplifier_distro/server/apps/slack/__init__.py`
- `src/amplifier_distro/server/apps/slack/formatter.py`
- `src/amplifier_distro/server/apps/web_chat/__init__.py`
- `tests/test_surface_registry.py`
- `tests/test_slack_bridge.py`
- `tests/test_web_chat.py`

Expected: Clean — no lint errors, no type errors, no formatting issues.

**Step 5: Commit**

```
git add -A
git commit -m "chore(#27): remove old SessionMapping from slack/models, final cleanup"
```

---

## Task Dependencies

```
Task 1a → 1b → 1c → 1d → 1e → 1f  (registry built incrementally)
                                    ↓
                          Task 2a → 2b  (Slack integration)
                                    ↓
                          Task 3a → 3b  (Web Chat integration)
                                    ↓
                                 Task 4a  (cleanup)
```

Tasks 2 and 3 are independent of each other (both depend only on Task 1). Task 4 depends on both.

---

## Key Files Reference

| File | Role |
|------|------|
| `src/amplifier_distro/server/surface_registry.py` | **NEW** — `SessionMapping` + `SurfaceSessionRegistry` |
| `src/amplifier_distro/server/apps/slack/sessions.py` | **MODIFY** — delegates to registry |
| `src/amplifier_distro/server/apps/slack/models.py` | **MODIFY** — remove old `SessionMapping` |
| `src/amplifier_distro/server/apps/slack/commands.py` | **MODIFY** — `.channel_id` → `.extra["channel_id"]` |
| `src/amplifier_distro/server/apps/slack/__init__.py` | **MODIFY** — update field access |
| `src/amplifier_distro/server/apps/slack/formatter.py` | **MODIFY** — update field access |
| `src/amplifier_distro/server/apps/web_chat/__init__.py` | **MODIFY** — add `WebChatSessionManager`, wire routes |
| `src/amplifier_distro/fileutil.py` | **READ ONLY** — `atomic_write` used by registry |
| `src/amplifier_distro/conventions.py` | **MAYBE MODIFY** — add `WEB_CHAT_SESSIONS_FILENAME` |
| `tests/test_surface_registry.py` | **NEW** — ~250 lines of registry tests |
| `tests/test_slack_bridge.py` | **MODIFY** — add registry integration tests |
| `tests/test_web_chat.py` | **MODIFY** — add `WebChatSessionManager` tests, update fixture |

---

## Run Commands

```bash
# Per-task verification
uv run python -m pytest tests/test_surface_registry.py -x -q      # Task 1
uv run python -m pytest tests/test_slack_bridge.py -x -q           # Task 2
uv run python -m pytest tests/test_web_chat.py -x -q               # Task 3
uv run python -m pytest tests/ -x -q                               # Full suite (Task 4)
```

---

## Estimated Lines

| Task | New | Removed | Net |
|------|-----|---------|-----|
| 1: Registry + tests | ~400 | 0 | +400 |
| 2: Slack integration | ~50 | ~150 | -100 |
| 3: Web Chat manager | ~100 | ~30 | +70 |
| 4: Cleanup | ~5 | ~30 | -25 |
| **Total** | ~555 | ~210 | **+345** |
