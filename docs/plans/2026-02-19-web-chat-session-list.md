# Web Chat Session List & Resume — Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Add session list + resume capability to the web chat UI so users can see past sessions, switch between them, and auto-create a session on first message.

**Architecture:** Self-contained within `src/amplifier_distro/server/apps/web_chat/`. A new `session_store.py` provides a `WebChatSession` dataclass and `WebChatSessionStore` with atomic JSON persistence. A `WebChatSessionManager` class (added to `__init__.py`) replaces the module-level `_active_session_id` global and `_session_lock`, wrapping the store and the existing `SessionBackend`. All 5 existing routes are refactored through the manager. 2 new routes are added. The frontend gets a sessions dropdown and an auto-create fix.

**Tech Stack:** Python 3.11+, dataclasses, FastAPI/Starlette, pytest, vanilla JS (no framework)

---

## Verified File Paths (confirmed against codebase)

```
src/amplifier_distro/
├── conventions.py                            ← Task 1: add constant
├── fileutil.py                               ← atomic_write lives here
└── server/
    └── apps/
        └── web_chat/
            ├── __init__.py                   ← Tasks 4–7: manager + routes
            ├── session_store.py              ← Tasks 2–3: NEW FILE
            └── static/
                └── index.html               ← Task 8: frontend

tests/
├── test_web_chat.py                          ← Task 5–7: modify existing tests
└── test_web_chat_store.py                    ← Tasks 2–3: NEW FILE
```

---

## Task 1: Add `WEB_CHAT_SESSIONS_FILENAME` to `conventions.py`

**Files:**
- Modify: `src/amplifier_distro/conventions.py`

This is a one-line change. No test needed — the constant is exercised by the manager in Tasks 4+.

**Step 1: Add the constant**

Open `src/amplifier_distro/conventions.py`. Find the block at lines 72–73:

```python
SLACK_SESSIONS_FILENAME = "slack-sessions.json"  # Slack bridge session mappings
TEAMS_SESSIONS_FILENAME = "teams-sessions.json"  # Teams bridge session mappings
```

Add one line immediately after `TEAMS_SESSIONS_FILENAME`:

```python
SLACK_SESSIONS_FILENAME = "slack-sessions.json"  # Slack bridge session mappings
TEAMS_SESSIONS_FILENAME = "teams-sessions.json"  # Teams bridge session mappings
WEB_CHAT_SESSIONS_FILENAME = "web-chat-sessions.json"  # Web chat session registry
```

**Step 2: Verify the import works**

```bash
cd /Users/samule/repo/distro-pr-50
python -c "from amplifier_distro.conventions import WEB_CHAT_SESSIONS_FILENAME; print(WEB_CHAT_SESSIONS_FILENAME)"
```

Expected output:
```
web-chat-sessions.json
```

**Step 3: Commit**

```bash
git add src/amplifier_distro/conventions.py
git commit -m "feat: add WEB_CHAT_SESSIONS_FILENAME to conventions"
```

---

## Task 2: `WebChatSession` dataclass (TDD)

**Files:**
- Create: `src/amplifier_distro/server/apps/web_chat/session_store.py`
- Create: `tests/test_web_chat_store.py`

### Step 1: Write the failing test

Create `tests/test_web_chat_store.py` with this content:

```python
"""Tests for WebChatSession and WebChatSessionStore.

Tests are isolated: no server, no backend, no services.
All store tests use persistence_path=None (in-memory mode).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

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
            session_id="s1", description="a",
            created_at="t", last_active="t",
        )
        s2 = WebChatSession(
            session_id="s2", description="b",
            created_at="t", last_active="t",
        )
        s1.extra["key"] = "value"
        assert "key" not in s2.extra
```

### Step 2: Run to verify it fails

```bash
cd /Users/samule/repo/distro-pr-50
pytest tests/test_web_chat_store.py::TestWebChatSession -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'amplifier_distro.server.apps.web_chat.session_store'`

### Step 3: Create `session_store.py` with the dataclass only

Create `src/amplifier_distro/server/apps/web_chat/session_store.py`:

```python
"""Session store for web chat.

Provides WebChatSession (dataclass) and WebChatSessionStore (in-memory dict
with optional atomic JSON persistence).

Mirrors the pattern used by SlackSessionManager in server/apps/slack/sessions.py
but stripped of all Slack-specific routing complexity.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class WebChatSession:
    """One entry in the web chat session registry.

    created_at / last_active are ISO-format UTC strings.
    extra holds arbitrary metadata (e.g. project_id) for forward compatibility.
    """

    session_id: str
    description: str
    created_at: str
    last_active: str
    is_active: bool = True
    extra: dict = field(default_factory=dict)
```

### Step 4: Run to verify it passes

```bash
pytest tests/test_web_chat_store.py::TestWebChatSession -v
```

Expected:
```
PASSED tests/test_web_chat_store.py::TestWebChatSession::test_session_has_required_fields
PASSED tests/test_web_chat_store.py::TestWebChatSession::test_session_is_active_by_default
PASSED tests/test_web_chat_store.py::TestWebChatSession::test_session_extra_defaults_to_empty_dict
PASSED tests/test_web_chat_store.py::TestWebChatSession::test_session_extra_instances_are_independent
4 passed in 0.XXs
```

### Step 5: Commit

```bash
git add src/amplifier_distro/server/apps/web_chat/session_store.py \
        tests/test_web_chat_store.py
git commit -m "feat: add WebChatSession dataclass with tests"
```

---

## Task 3: `WebChatSessionStore` (TDD)

**Files:**
- Modify: `src/amplifier_distro/server/apps/web_chat/session_store.py`
- Modify: `tests/test_web_chat_store.py`

### Step 1: Add store tests to `tests/test_web_chat_store.py`

Append this class to the existing `tests/test_web_chat_store.py` (after `TestWebChatSession`):

```python
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
```

### Step 2: Run to verify the store tests fail

```bash
pytest tests/test_web_chat_store.py::TestWebChatSessionStore -v
```

Expected: `ERROR` — `ImportError: cannot import name 'WebChatSessionStore'`

### Step 3: Implement `WebChatSessionStore` in `session_store.py`

Append this class to `src/amplifier_distro/server/apps/web_chat/session_store.py`, after the `WebChatSession` dataclass:

```python
class WebChatSessionStore:
    """In-memory dict of WebChatSession, optionally persisted to JSON.

    Pass persistence_path=None to disable disk I/O (useful in tests).
    On every mutation (add, deactivate, reactivate) the store is saved.

    Thread safety: single-threaded writes assumed (web chat is single-user).
    """

    def __init__(self, persistence_path: Path | None = None) -> None:
        self._sessions: dict[str, WebChatSession] = {}
        self._persistence_path = persistence_path
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        session_id: str,
        description: str,
        extra: dict | None = None,
    ) -> WebChatSession:
        """Register a new session. Raises ValueError if session_id already exists."""
        if session_id in self._sessions:
            raise ValueError(f"Session {session_id!r} already exists")
        now = datetime.now(UTC).isoformat()
        session = WebChatSession(
            session_id=session_id,
            description=description,
            created_at=now,
            last_active=now,
            is_active=True,
            extra=dict(extra) if extra else {},
        )
        self._sessions[session_id] = session
        self._save()
        return session

    def deactivate(self, session_id: str) -> None:
        """Mark session as inactive. No-op if session_id not found."""
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.is_active = False
        self._save()

    def reactivate(self, session_id: str) -> WebChatSession:
        """Mark session as active again. Raises ValueError if not found."""
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session {session_id!r} not found")
        session.is_active = True
        session.last_active = datetime.now(UTC).isoformat()
        self._save()
        return session

    def get(self, session_id: str) -> WebChatSession | None:
        """Return the session or None."""
        return self._sessions.get(session_id)

    def list_all(self) -> list[WebChatSession]:
        """All sessions, sorted by last_active descending (most recent first)."""
        return sorted(
            self._sessions.values(),
            key=lambda s: s.last_active,
            reverse=True,
        )

    def active_session(self) -> WebChatSession | None:
        """Return the first active session, or None."""
        for session in self._sessions.values():
            if session.is_active:
                return session
        return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Atomically write all sessions to the persistence file."""
        if self._persistence_path is None:
            return
        try:
            from amplifier_distro.fileutil import atomic_write

            data = [asdict(s) for s in self._sessions.values()]
            atomic_write(self._persistence_path, json.dumps(data, indent=2))
        except OSError:
            logger.warning("Failed to save web chat sessions", exc_info=True)

    def _load(self) -> None:
        """Load sessions from persistence file. Silently ignores missing/corrupt files."""
        if self._persistence_path is None or not self._persistence_path.exists():
            return
        try:
            data = json.loads(self._persistence_path.read_text())
            for entry in data:
                session = WebChatSession(
                    session_id=entry["session_id"],
                    description=entry.get("description", ""),
                    created_at=entry.get("created_at", ""),
                    last_active=entry.get("last_active", ""),
                    is_active=entry.get("is_active", True),
                    extra=entry.get("extra", {}),
                )
                self._sessions[session.session_id] = session
            logger.info(
                "Loaded %d web chat sessions from %s",
                len(data),
                self._persistence_path,
            )
        except (json.JSONDecodeError, KeyError, OSError):
            logger.warning("Failed to load web chat sessions", exc_info=True)
```

### Step 4: Run to verify all store tests pass

```bash
pytest tests/test_web_chat_store.py -v
```

Expected:
```
PASSED tests/test_web_chat_store.py::TestWebChatSession::test_session_has_required_fields
PASSED tests/test_web_chat_store.py::TestWebChatSession::test_session_is_active_by_default
PASSED tests/test_web_chat_store.py::TestWebChatSession::test_session_extra_defaults_to_empty_dict
PASSED tests/test_web_chat_store.py::TestWebChatSession::test_session_extra_instances_are_independent
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_add_returns_session
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_add_timestamps_are_set
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_add_extra_is_stored
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_add_duplicate_raises
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_get_returns_session
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_get_missing_returns_none
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_deactivate_marks_inactive
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_deactivate_missing_does_not_raise
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_reactivate_marks_active
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_reactivate_updates_last_active
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_reactivate_missing_raises
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_list_all_empty
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_list_all_returns_all_sessions
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_list_all_sorted_by_last_active_desc
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_active_session_none_when_empty
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_active_session_returns_active_entry
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_active_session_none_after_deactivate
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_persistence_roundtrip
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_persistence_none_path_means_in_memory
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_persistence_corrupt_json_is_ignored
PASSED tests/test_web_chat_store.py::TestWebChatSessionStore::test_persistence_missing_file_is_ignored
25 passed in 0.XXs
```

### Step 5: Commit

```bash
git add src/amplifier_distro/server/apps/web_chat/session_store.py \
        tests/test_web_chat_store.py
git commit -m "feat: add WebChatSessionStore with atomic JSON persistence"
```

---

## Task 4: `WebChatSessionManager` (TDD)

**Files:**
- Modify: `src/amplifier_distro/server/apps/web_chat/__init__.py`
- Modify: `tests/test_web_chat_store.py`

The manager class goes into `__init__.py` but we test it in `test_web_chat_store.py` using a `MockBackend` directly — no HTTP, no server, no services setup needed.

### Step 1: Add manager tests to `tests/test_web_chat_store.py`

Append this class to `tests/test_web_chat_store.py`:

```python
class TestWebChatSessionManager:
    """Verify WebChatSessionManager behaviour using MockBackend directly.

    No server, no services, no HTTP. Pure unit tests.
    """

    def _make_manager(self):
        """Create a manager with a fresh MockBackend and in-memory store."""
        from amplifier_distro.server.session_backend import MockBackend
        from amplifier_distro.server.apps.web_chat import WebChatSessionManager

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
        import asyncio
        manager, _ = self._make_manager()
        info = asyncio.get_event_loop().run_until_complete(
            manager.create_session(working_dir="~", description="test session")
        )
        assert info.session_id.startswith("mock-session-")

    def test_create_session_sets_active(self):
        import asyncio
        manager, _ = self._make_manager()
        info = asyncio.get_event_loop().run_until_complete(
            manager.create_session(working_dir="~", description="test")
        )
        assert manager.active_session_id == info.session_id

    def test_create_session_registers_in_store(self):
        import asyncio
        manager, _ = self._make_manager()
        info = asyncio.get_event_loop().run_until_complete(
            manager.create_session(working_dir="~", description="my description")
        )
        stored = manager._store.get(info.session_id)
        assert stored is not None
        assert stored.description == "my description"

    def test_create_session_stores_project_id_in_extra(self):
        import asyncio
        manager, _ = self._make_manager()
        info = asyncio.get_event_loop().run_until_complete(
            manager.create_session(working_dir="~", description="test")
        )
        stored = manager._store.get(info.session_id)
        assert stored.extra.get("project_id") == info.project_id

    def test_create_session_ends_previous_session(self):
        import asyncio
        manager, backend = self._make_manager()
        loop = asyncio.get_event_loop()
        info1 = loop.run_until_complete(
            manager.create_session(working_dir="~", description="first")
        )
        info2 = loop.run_until_complete(
            manager.create_session(working_dir="~", description="second")
        )
        # First session should be deactivated in store
        s1 = manager._store.get(info1.session_id)
        assert s1.is_active is False
        # Second session is now active
        assert manager.active_session_id == info2.session_id

    # ------------------------------------------------------------------
    # send_message()
    # ------------------------------------------------------------------

    def test_send_message_returns_none_without_session(self):
        import asyncio
        manager, _ = self._make_manager()
        result = asyncio.get_event_loop().run_until_complete(
            manager.send_message("hello")
        )
        assert result is None

    def test_send_message_returns_response(self):
        import asyncio
        manager, _ = self._make_manager()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            manager.create_session(working_dir="~", description="test")
        )
        response = loop.run_until_complete(manager.send_message("hello"))
        assert response is not None
        assert "hello" in response  # MockBackend echoes the message

    def test_send_message_deactivates_on_backend_valueerror(self):
        import asyncio
        from amplifier_distro.server.session_backend import MockBackend

        from amplifier_distro.server.apps.web_chat import WebChatSessionManager

        backend = MockBackend()
        manager = WebChatSessionManager(backend, persistence_path=None)
        loop = asyncio.get_event_loop()
        info = loop.run_until_complete(
            manager.create_session(working_dir="~", description="test")
        )
        # Kill backend session
        backend._sessions[info.session_id].is_active = False

        with pytest.raises(ValueError):
            loop.run_until_complete(manager.send_message("hello after death"))

        # Store should have deactivated the session
        assert manager.active_session_id is None

    # ------------------------------------------------------------------
    # end_session()
    # ------------------------------------------------------------------

    def test_end_session_returns_false_without_session(self):
        import asyncio
        manager, _ = self._make_manager()
        result = asyncio.get_event_loop().run_until_complete(manager.end_session())
        assert result is False

    def test_end_session_returns_true_with_session(self):
        import asyncio
        manager, _ = self._make_manager()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            manager.create_session(working_dir="~", description="test")
        )
        result = loop.run_until_complete(manager.end_session())
        assert result is True

    def test_end_session_clears_active(self):
        import asyncio
        manager, _ = self._make_manager()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            manager.create_session(working_dir="~", description="test")
        )
        loop.run_until_complete(manager.end_session())
        assert manager.active_session_id is None

    # ------------------------------------------------------------------
    # list_sessions()
    # ------------------------------------------------------------------

    def test_list_sessions_empty(self):
        manager, _ = self._make_manager()
        assert manager.list_sessions() == []

    def test_list_sessions_returns_all(self):
        import asyncio
        manager, _ = self._make_manager()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            manager.create_session(working_dir="~", description="first")
        )
        loop.run_until_complete(
            manager.create_session(working_dir="~", description="second")
        )
        sessions = manager.list_sessions()
        assert len(sessions) == 2

    # ------------------------------------------------------------------
    # resume_session()
    # ------------------------------------------------------------------

    def test_resume_session_raises_for_unknown_id(self):
        manager, _ = self._make_manager()
        with pytest.raises(ValueError, match="not found"):
            manager.resume_session("no-such-id")

    def test_resume_session_reactivates_inactive_session(self):
        import asyncio
        manager, _ = self._make_manager()
        loop = asyncio.get_event_loop()
        info1 = loop.run_until_complete(
            manager.create_session(working_dir="~", description="first")
        )
        # Create second session (deactivates first)
        loop.run_until_complete(
            manager.create_session(working_dir="~", description="second")
        )
        # Resume first
        resumed = manager.resume_session(info1.session_id)
        assert resumed.is_active is True
        assert manager.active_session_id == info1.session_id

    def test_resume_session_deactivates_current(self):
        import asyncio
        manager, _ = self._make_manager()
        loop = asyncio.get_event_loop()
        info1 = loop.run_until_complete(
            manager.create_session(working_dir="~", description="first")
        )
        info2 = loop.run_until_complete(
            manager.create_session(working_dir="~", description="second")
        )
        manager.resume_session(info1.session_id)
        # Second session should be deactivated
        s2 = manager._store.get(info2.session_id)
        assert s2.is_active is False
```

### Step 2: Run to verify the manager tests fail

```bash
pytest tests/test_web_chat_store.py::TestWebChatSessionManager -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'WebChatSessionManager' from 'amplifier_distro.server.apps.web_chat'`

### Step 3: Add `WebChatSessionManager` to `__init__.py`

Add this block to `src/amplifier_distro/server/apps/web_chat/__init__.py`, **after** the `_get_backend()` function and **before** the `@router.get("/")` route (i.e., after line 128 in the existing file):

```python
from amplifier_distro.conventions import (
    AMPLIFIER_HOME,
    SERVER_DIR,
    WEB_CHAT_SESSIONS_FILENAME,
)

from amplifier_distro.server.apps.web_chat.session_store import (
    WebChatSession,
    WebChatSessionStore,
)


class WebChatSessionManager:
    """Manages web chat sessions: store registry + backend lifecycle.

    Replaces the module-level _active_session_id global and _session_lock.
    One active session at a time (single-user web chat).

    Pass persistence_path=None to disable disk persistence (test mode).
    In production, persistence_path is resolved at singleton creation time.
    """

    def __init__(
        self,
        backend: Any,
        persistence_path: Path | None = None,
    ) -> None:
        self._backend = backend
        self._store = WebChatSessionStore(persistence_path=persistence_path)

    @property
    def active_session_id(self) -> str | None:
        """ID of the current active session, or None."""
        session = self._store.active_session()
        return session.session_id if session else None

    async def create_session(
        self,
        working_dir: str = "~",
        description: str = "Web chat session",
    ):
        """End any active session, create a new one, register in store.

        Returns the SessionInfo from the backend.
        """
        # End existing session if any
        existing = self._store.active_session()
        if existing:
            await self._end_active(existing.session_id)

        info = await self._backend.create_session(
            working_dir=working_dir,
            description=description,
        )
        self._store.add(
            info.session_id,
            description,
            extra={"project_id": info.project_id},
        )
        return info

    async def send_message(self, message: str) -> str | None:
        """Send message to active session. Returns None if no session.

        Updates last_active on success.
        On backend ValueError (session died), deactivates store entry and re-raises.
        """
        from datetime import UTC, datetime

        session = self._store.active_session()
        if session is None:
            return None

        session.last_active = datetime.now(UTC).isoformat()
        self._store._save()

        try:
            return await self._backend.send_message(session.session_id, message)
        except ValueError:
            # Backend confirmed session is dead — deactivate in store
            self._store.deactivate(session.session_id)
            raise

    async def end_session(self) -> bool:
        """Deactivate and end the active session.

        Returns True if a session existed, False otherwise.
        """
        session = self._store.active_session()
        if session is None:
            return False
        await self._end_active(session.session_id)
        return True

    def list_sessions(self) -> list[WebChatSession]:
        """All sessions sorted by last_active desc."""
        return self._store.list_all()

    def resume_session(self, session_id: str) -> WebChatSession:
        """Switch active session to session_id.

        Deactivates the current active session (store only — backend stays alive).
        Raises ValueError if session_id is not found.
        """
        if self._store.get(session_id) is None:
            raise ValueError(f"Session {session_id!r} not found")

        # Deactivate current if it's a different session
        current = self._store.active_session()
        if current and current.session_id != session_id:
            self._store.deactivate(current.session_id)

        return self._store.reactivate(session_id)

    async def _end_active(self, session_id: str) -> None:
        """Deactivate in store and end on backend. Swallows backend errors."""
        self._store.deactivate(session_id)
        try:
            await self._backend.end_session(session_id)
        except (RuntimeError, ValueError, OSError):
            logger.warning("Error ending session %s", session_id, exc_info=True)


_manager: WebChatSessionManager | None = None


def _get_manager() -> WebChatSessionManager:
    """Return the module-level WebChatSessionManager singleton.

    Creates it on first call, wiring up the real persistence path.
    """
    global _manager
    if _manager is None:
        persistence_path = (
            Path(AMPLIFIER_HOME).expanduser() / SERVER_DIR / WEB_CHAT_SESSIONS_FILENAME
        )
        _manager = WebChatSessionManager(
            _get_backend(),
            persistence_path=persistence_path,
        )
    return _manager
```

Also add `WebChatSessionManager` to the imports at the top of `__init__.py` — specifically, add it to the existing import at line 25 so it's importable from the module:

```python
# Make WebChatSessionManager importable at package level (used by tests)
# (The class is defined in the same file, so no import needed — just ensure
# it is NOT accidentally in __all__. Nothing to change here.)
```

Actually there is no `__all__`, so `WebChatSessionManager` is importable automatically. Nothing to add.

### Step 4: Run to verify manager tests pass

```bash
pytest tests/test_web_chat_store.py::TestWebChatSessionManager -v
```

Expected: all 18 manager tests pass.

### Step 5: Run all store tests to make sure nothing broke

```bash
pytest tests/test_web_chat_store.py -v
```

Expected: all 43 tests pass (4 dataclass + 25 store + 18 manager).

### Step 6: Run existing web chat tests to confirm nothing is broken yet

```bash
pytest tests/test_web_chat.py -v
```

Expected: all existing tests still pass (the existing routes still use the old globals — that's fine, we haven't touched them yet).

### Step 7: Commit

```bash
git add src/amplifier_distro/server/apps/web_chat/__init__.py \
        tests/test_web_chat_store.py
git commit -m "feat: add WebChatSessionManager with store integration"
```

---

## Task 5: Refactor existing 5 routes to use manager (drop globals)

**Files:**
- Modify: `src/amplifier_distro/server/apps/web_chat/__init__.py`
- Modify: `tests/test_web_chat.py`

This task removes `_active_session_id` and `_session_lock` globals and rewires all 5 existing routes through `_get_manager()`. The existing tests must stay green.

### Step 1: Update the `webchat_client` fixture in `tests/test_web_chat.py`

The fixture currently resets `wc._active_session_id = None`. After the refactor that global is gone — replace it with `wc._manager = None`.

Find this block in `tests/test_web_chat.py` (lines 39–53):

```python
@pytest.fixture
def webchat_client() -> TestClient:
    """Create a TestClient with web-chat app and services initialized."""
    # Reset module-level state in web_chat
    import amplifier_distro.server.apps.web_chat as wc

    wc._active_session_id = None

    init_services(dev_mode=True)

    from amplifier_distro.server.apps.web_chat import manifest

    server = DistroServer()
    server.register_app(manifest)
    return TestClient(server.app)
```

Replace with:

```python
@pytest.fixture(autouse=True)
def _reset_web_chat_manager():
    """Reset the _manager singleton between every test to prevent bleed."""
    import amplifier_distro.server.apps.web_chat as wc

    wc._manager = None
    yield
    wc._manager = None


@pytest.fixture
def webchat_client() -> TestClient:
    """Create a TestClient with web-chat app and services initialized."""
    init_services(dev_mode=True)

    from amplifier_distro.server.apps.web_chat import manifest

    server = DistroServer()
    server.register_app(manifest)
    return TestClient(server.app)
```

> **Why `autouse=True`?** The `webchat_client` fixture only runs for tests that request it, but `_reset_web_chat_manager` must run for *all* tests in the file (including `TestAppDiscovery` which doesn't use `webchat_client` but still imports the module).

### Step 2: Run existing tests to confirm the fixture change doesn't break them

```bash
pytest tests/test_web_chat.py -v
```

Expected: all tests still pass (routes haven't changed yet — they still use the old globals).

### Step 3: Refactor `__init__.py` — remove globals, rewrite 5 routes

Replace the **entire contents** of `src/amplifier_distro/server/apps/web_chat/__init__.py` with the following. Read the current file first to ensure no logic is accidentally dropped:

```python
"""Web Chat App - Amplifier web chat interface.

Serves a self-contained chat UI and provides API endpoints for
session management and chat. Uses the shared server backend to
create and interact with Amplifier sessions.

Memory-aware: recognizes "remember this: ..." and "what do you remember
about ..." patterns and routes them through the memory service instead of
(or before) the Amplifier backend.

Routes:
    GET  /                    - Serves the chat HTML page
    GET  /api/session         - Session connection status
    POST /api/session         - Create a new session
    POST /api/chat            - Send a message to active session
    POST /api/end             - End the active session
    GET  /api/sessions        - List all sessions
    POST /api/session/resume  - Resume a previous session
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from amplifier_distro.conventions import (
    AMPLIFIER_HOME,
    SERVER_DIR,
    WEB_CHAT_SESSIONS_FILENAME,
)
from amplifier_distro.server.app import AppManifest
from amplifier_distro.server.apps.web_chat.session_store import (
    WebChatSession,
    WebChatSessionStore,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_static_dir = Path(__file__).parent / "static"

# --- Memory pattern matching ---

# Patterns for "remember this: <text>" style messages
_REMEMBER_PATTERNS = [
    re.compile(r"^remember\s+this:\s*(.+)", re.IGNORECASE | re.DOTALL),
    re.compile(r"^remember\s+that\s+(.+)", re.IGNORECASE | re.DOTALL),
    re.compile(r"^remember:\s*(.+)", re.IGNORECASE | re.DOTALL),
]

# Patterns for "what do you remember about <query>" style messages
_RECALL_PATTERNS = [
    re.compile(r"^what\s+do\s+you\s+remember\s+about\s+(.+)", re.IGNORECASE),
    re.compile(r"^recall\s+(.+)", re.IGNORECASE),
    re.compile(r"^search\s+memory\s+(?:for\s+)?(.+)", re.IGNORECASE),
]


def check_memory_intent(message: str) -> tuple[str, str] | None:
    """Check if a message is a memory command.

    Returns:
        A (action, text) tuple if it's a memory command, or None.
        action is 'remember' or 'recall'.
    """
    stripped = message.strip()
    for pattern in _REMEMBER_PATTERNS:
        match = pattern.match(stripped)
        if match:
            return ("remember", match.group(1).strip())
    for pattern in _RECALL_PATTERNS:
        match = pattern.match(stripped)
        if match:
            return ("recall", match.group(1).strip())
    return None


def _handle_memory_command(action: str, text: str) -> dict[str, Any]:
    """Handle a memory command and return a chat-style response.

    Args:
        action: 'remember' or 'recall'.
        text: The memory content or search query.

    Returns:
        Dict with 'response' key suitable for chat response.
    """
    from amplifier_distro.server.memory import get_memory_service

    service = get_memory_service()

    if action == "remember":
        result = service.remember(text)
        return {
            "response": (
                f"Remembered! Stored as {result['id']} "
                f"(category: {result['category']}, "
                f"tags: {', '.join(result['tags'])})"
            ),
            "memory_action": "remember",
            "memory_result": result,
        }
    else:  # recall
        results = service.recall(text)
        if not results:
            return {
                "response": f"No memories found matching '{text}'.",
                "memory_action": "recall",
                "memory_result": [],
            }
        lines = [
            f"Found {len(results)} memory(ies):\n",
            *[f"- [{m['id']}] ({m['category']}) {m['content']}" for m in results],
        ]
        return {
            "response": "\n".join(lines),
            "memory_action": "recall",
            "memory_result": results,
        }


def _get_backend():
    """Get the shared session backend."""
    from amplifier_distro.server.services import get_services

    return get_services().backend


class WebChatSessionManager:
    """Manages web chat sessions: store registry + backend lifecycle.

    Replaces the module-level _active_session_id global and _session_lock.
    One active session at a time (single-user web chat).

    Pass persistence_path=None to disable disk persistence (test mode).
    In production, persistence_path is resolved at singleton creation time.
    """

    def __init__(
        self,
        backend: Any,
        persistence_path: Path | None = None,
    ) -> None:
        self._backend = backend
        self._store = WebChatSessionStore(persistence_path=persistence_path)

    @property
    def active_session_id(self) -> str | None:
        """ID of the current active session, or None."""
        session = self._store.active_session()
        return session.session_id if session else None

    async def create_session(
        self,
        working_dir: str = "~",
        description: str = "Web chat session",
    ):
        """End any active session, create a new one, register in store.

        Returns the SessionInfo from the backend.
        """
        existing = self._store.active_session()
        if existing:
            await self._end_active(existing.session_id)

        info = await self._backend.create_session(
            working_dir=working_dir,
            description=description,
        )
        self._store.add(
            info.session_id,
            description,
            extra={"project_id": info.project_id},
        )
        return info

    async def send_message(self, message: str) -> str | None:
        """Send message to active session. Returns None if no session.

        Updates last_active on success.
        On backend ValueError (session died), deactivates store entry and re-raises.
        """
        from datetime import UTC, datetime

        session = self._store.active_session()
        if session is None:
            return None

        session.last_active = datetime.now(UTC).isoformat()
        self._store._save()

        try:
            return await self._backend.send_message(session.session_id, message)
        except ValueError:
            self._store.deactivate(session.session_id)
            raise

    async def end_session(self) -> bool:
        """Deactivate and end the active session.

        Returns True if a session existed, False otherwise.
        """
        session = self._store.active_session()
        if session is None:
            return False
        await self._end_active(session.session_id)
        return True

    def list_sessions(self) -> list[WebChatSession]:
        """All sessions sorted by last_active desc."""
        return self._store.list_all()

    def resume_session(self, session_id: str) -> WebChatSession:
        """Switch active session to session_id.

        Deactivates the current active session (store only — backend stays alive).
        Raises ValueError if session_id is not found.
        """
        if self._store.get(session_id) is None:
            raise ValueError(f"Session {session_id!r} not found")

        current = self._store.active_session()
        if current and current.session_id != session_id:
            self._store.deactivate(current.session_id)

        return self._store.reactivate(session_id)

    async def _end_active(self, session_id: str) -> None:
        """Deactivate in store and end on backend. Swallows backend errors."""
        self._store.deactivate(session_id)
        try:
            await self._backend.end_session(session_id)
        except (RuntimeError, ValueError, OSError):
            logger.warning("Error ending session %s", session_id, exc_info=True)


_manager: WebChatSessionManager | None = None


def _get_manager() -> WebChatSessionManager:
    """Return the module-level WebChatSessionManager singleton."""
    global _manager
    if _manager is None:
        persistence_path = (
            Path(AMPLIFIER_HOME).expanduser() / SERVER_DIR / WEB_CHAT_SESSIONS_FILENAME
        )
        _manager = WebChatSessionManager(
            _get_backend(),
            persistence_path=persistence_path,
        )
    return _manager


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the web chat interface."""
    html_file = _static_dir / "index.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text())
    return HTMLResponse(
        content=(
            "<h1>Amplifier Web Chat</h1>"
            "<p>index.html not found. Reinstall amplifier-distro.</p>"
        ),
        status_code=500,
    )


@router.get("/api/session")
async def session_status() -> dict:
    """Return session connection status.

    Reports whether a session is active and its ID.
    """
    manager = _get_manager()
    session_id = manager.active_session_id

    if session_id is None:
        return {
            "connected": False,
            "session_id": None,
            "message": "No active session. Click 'New Session' to start.",
        }

    # Verify session is still alive on the backend
    try:
        backend = _get_backend()
        info = await backend.get_session_info(session_id)
        if info and info.is_active:
            return {
                "connected": True,
                "session_id": session_id,
                "project_id": info.project_id,
                "working_dir": info.working_dir,
            }
        else:
            manager._store.deactivate(session_id)
            return {
                "connected": False,
                "session_id": None,
                "message": "Previous session ended. Start a new one.",
            }
    except RuntimeError:
        return {
            "connected": False,
            "session_id": None,
            "message": "Server services not ready. Is the server fully started?",
        }


@router.post("/api/session")
async def create_session(request: Request) -> JSONResponse:
    """Create a new Amplifier session for web chat.

    Body (all optional):
        working_dir: str - Working directory for the session
        description: str - Human-readable description
    """
    body = await request.json() if await request.body() else {}

    try:
        manager = _get_manager()
        info = await manager.create_session(
            working_dir=body.get("working_dir", "~"),
            description=body.get("description", "Web chat session"),
        )
        return JSONResponse(
            content={
                "session_id": info.session_id,
                "project_id": info.project_id,
                "working_dir": info.working_dir,
            }
        )
    except RuntimeError as e:
        return JSONResponse(
            status_code=503,
            content={"error": str(e)},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Session creation failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "type": type(e).__name__},
        )


@router.post("/api/chat")
async def chat(request: Request) -> JSONResponse:
    """Chat endpoint - send a message to the active session.

    Memory-aware: intercepts "remember this: ..." and "what do you
    remember about ..." patterns and routes them through the memory
    service. Memory commands work even without an active session.

    Body:
        message: str - The user's message
    """
    manager = _get_manager()

    body = await request.json()
    user_message = body.get("message", "")

    if not user_message:
        return JSONResponse(
            status_code=400,
            content={"error": "message is required"},
        )

    # Check for memory commands first - these work without a session
    memory_intent = check_memory_intent(user_message)
    if memory_intent is not None:
        action, text = memory_intent
        try:
            result = _handle_memory_command(action, text)
            result["session_connected"] = manager.active_session_id is not None
            return JSONResponse(content=result)
        except Exception as e:  # noqa: BLE001
            logger.warning("Memory command failed: %s", e, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": str(e), "type": type(e).__name__},
            )

    if manager.active_session_id is None:
        return JSONResponse(
            status_code=409,
            content={
                "error": "No active session. Create one first via POST /api/session.",
                "session_connected": False,
            },
        )

    try:
        response = await manager.send_message(user_message)
        return JSONResponse(
            content={
                "response": response,
                "session_id": manager.active_session_id,
                "session_connected": True,
            }
        )
    except ValueError:
        return JSONResponse(
            status_code=409,
            content={
                "error": "Session no longer exists. Create a new one.",
                "session_connected": False,
            },
        )
    except RuntimeError as e:
        return JSONResponse(
            status_code=503,
            content={"error": str(e)},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Chat message failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "type": type(e).__name__},
        )


@router.post("/api/end")
async def end_session() -> JSONResponse:
    """End the active web chat session."""
    manager = _get_manager()
    session_id = manager.active_session_id

    if session_id is None:
        return JSONResponse(content={"ended": False, "message": "No active session."})

    await manager.end_session()
    return JSONResponse(content={"ended": True, "session_id": session_id})


manifest = AppManifest(
    name="web-chat",
    description="Amplifier web chat interface",
    version="0.1.0",
    router=router,
)
```

### Step 4: Run existing web chat tests — they must all still pass

```bash
pytest tests/test_web_chat.py -v
```

Expected: all existing tests pass (same count as before, no new failures).

If any test fails, debug before proceeding. Common issues:
- `AttributeError: module has no attribute '_active_session_id'` → fixture was not updated in Step 1
- `test_chat_valueerror_clears_session` fails → check that `manager.send_message()` deactivates store on ValueError

### Step 5: Run full test suite

```bash
pytest tests/test_web_chat.py tests/test_web_chat_store.py -v
```

Expected: all tests pass.

### Step 6: Commit

```bash
git add src/amplifier_distro/server/apps/web_chat/__init__.py \
        tests/test_web_chat.py
git commit -m "refactor: replace _active_session_id global with WebChatSessionManager"
```

---

## Task 6: Add `GET /api/sessions` endpoint + tests

**Files:**
- Modify: `src/amplifier_distro/server/apps/web_chat/__init__.py`
- Modify: `tests/test_web_chat.py`

### Step 1: Add the failing tests to `tests/test_web_chat.py`

Append this class to the end of `tests/test_web_chat.py`:

```python
class TestWebChatSessionsListAPI:
    """Verify GET /apps/web-chat/api/sessions endpoint."""

    def test_list_sessions_returns_200(self, webchat_client: TestClient):
        response = webchat_client.get("/apps/web-chat/api/sessions")
        assert response.status_code == 200

    def test_list_sessions_empty_by_default(self, webchat_client: TestClient):
        data = webchat_client.get("/apps/web-chat/api/sessions").json()
        assert data["sessions"] == []

    def test_list_sessions_includes_created_session(self, webchat_client: TestClient):
        webchat_client.post(
            "/apps/web-chat/api/session",
            json={"description": "my test session"},
        )
        data = webchat_client.get("/apps/web-chat/api/sessions").json()
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["description"] == "my test session"

    def test_list_sessions_entry_has_required_fields(self, webchat_client: TestClient):
        webchat_client.post("/apps/web-chat/api/session", json={})
        sessions = webchat_client.get("/apps/web-chat/api/sessions").json()["sessions"]
        s = sessions[0]
        assert "session_id" in s
        assert "description" in s
        assert "created_at" in s
        assert "last_active" in s
        assert "is_active" in s
        assert "project_id" in s

    def test_list_sessions_active_flag_is_true_for_current(
        self, webchat_client: TestClient
    ):
        webchat_client.post("/apps/web-chat/api/session", json={})
        sessions = webchat_client.get("/apps/web-chat/api/sessions").json()["sessions"]
        assert sessions[0]["is_active"] is True

    def test_list_sessions_shows_both_active_and_inactive(
        self, webchat_client: TestClient
    ):
        # Create first session
        webchat_client.post("/apps/web-chat/api/session", json={"description": "first"})
        # Create second session — automatically deactivates first
        webchat_client.post(
            "/apps/web-chat/api/session", json={"description": "second"}
        )
        sessions = webchat_client.get("/apps/web-chat/api/sessions").json()["sessions"]
        assert len(sessions) == 2
        active = [s for s in sessions if s["is_active"]]
        inactive = [s for s in sessions if not s["is_active"]]
        assert len(active) == 1
        assert len(inactive) == 1

    def test_list_sessions_project_id_field_is_present(
        self, webchat_client: TestClient
    ):
        webchat_client.post("/apps/web-chat/api/session", json={})
        sessions = webchat_client.get("/apps/web-chat/api/sessions").json()["sessions"]
        # project_id should be a string (may be empty for unknown sessions)
        assert isinstance(sessions[0]["project_id"], str)
```

### Step 2: Run to verify the new tests fail

```bash
pytest tests/test_web_chat.py::TestWebChatSessionsListAPI -v
```

Expected: `FAILED` — `404 Not Found` (route doesn't exist yet)

### Step 3: Add the `GET /api/sessions` route to `__init__.py`

Add this route to `src/amplifier_distro/server/apps/web_chat/__init__.py` **before** the `manifest = AppManifest(...)` line at the bottom:

```python
@router.get("/api/sessions")
async def list_sessions() -> dict:
    """List all web chat sessions.

    Returns all sessions (active and inactive), sorted by last_active desc.
    """
    manager = _get_manager()
    sessions = manager.list_sessions()
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "description": s.description,
                "created_at": s.created_at,
                "last_active": s.last_active,
                "is_active": s.is_active,
                "project_id": s.extra.get("project_id", ""),
            }
            for s in sessions
        ]
    }
```

### Step 4: Run the new tests to verify they pass

```bash
pytest tests/test_web_chat.py::TestWebChatSessionsListAPI -v
```

Expected: all 7 tests pass.

### Step 5: Run full suite to make sure nothing broke

```bash
pytest tests/test_web_chat.py tests/test_web_chat_store.py -v
```

Expected: all tests pass.

### Step 6: Commit

```bash
git add src/amplifier_distro/server/apps/web_chat/__init__.py \
        tests/test_web_chat.py
git commit -m "feat: add GET /api/sessions endpoint"
```

---

## Task 7: Add `POST /api/session/resume` endpoint + tests

**Files:**
- Modify: `src/amplifier_distro/server/apps/web_chat/__init__.py`
- Modify: `tests/test_web_chat.py`

### Step 1: Add the failing tests to `tests/test_web_chat.py`

Append this class to the end of `tests/test_web_chat.py`:

```python
class TestWebChatSessionResumeAPI:
    """Verify POST /apps/web-chat/api/session/resume endpoint."""

    def test_resume_missing_session_id_returns_400(self, webchat_client: TestClient):
        response = webchat_client.post(
            "/apps/web-chat/api/session/resume",
            json={},
        )
        assert response.status_code == 400
        assert "session_id" in response.json()["error"]

    def test_resume_unknown_session_returns_404(self, webchat_client: TestClient):
        response = webchat_client.post(
            "/apps/web-chat/api/session/resume",
            json={"session_id": "no-such-session"},
        )
        assert response.status_code == 404

    def test_resume_known_session_returns_200(self, webchat_client: TestClient):
        # Create a session to get a known ID
        create_resp = webchat_client.post(
            "/apps/web-chat/api/session", json={"description": "session to resume"}
        )
        session_id = create_resp.json()["session_id"]
        # Create another session (pushes first to inactive)
        webchat_client.post("/apps/web-chat/api/session", json={})

        # Resume first session
        response = webchat_client.post(
            "/apps/web-chat/api/session/resume",
            json={"session_id": session_id},
        )
        assert response.status_code == 200

    def test_resume_response_has_required_fields(self, webchat_client: TestClient):
        create_resp = webchat_client.post("/apps/web-chat/api/session", json={})
        session_id = create_resp.json()["session_id"]
        webchat_client.post("/apps/web-chat/api/session", json={})

        data = webchat_client.post(
            "/apps/web-chat/api/session/resume",
            json={"session_id": session_id},
        ).json()
        assert data["session_id"] == session_id
        assert data["resumed"] is True

    def test_resume_makes_session_active(self, webchat_client: TestClient):
        create_resp = webchat_client.post("/apps/web-chat/api/session", json={})
        session_id = create_resp.json()["session_id"]
        webchat_client.post("/apps/web-chat/api/session", json={})

        webchat_client.post(
            "/apps/web-chat/api/session/resume",
            json={"session_id": session_id},
        )

        # GET /api/session should now report this session as connected
        status = webchat_client.get("/apps/web-chat/api/session").json()
        assert status["connected"] is True
        assert status["session_id"] == session_id

    def test_resume_deactivates_current_session(self, webchat_client: TestClient):
        create1 = webchat_client.post("/apps/web-chat/api/session", json={})
        session_id_1 = create1.json()["session_id"]
        create2 = webchat_client.post("/apps/web-chat/api/session", json={})
        session_id_2 = create2.json()["session_id"]

        # Resume first session
        webchat_client.post(
            "/apps/web-chat/api/session/resume",
            json={"session_id": session_id_1},
        )

        # session_id_2 should no longer be the active one
        sessions = webchat_client.get("/apps/web-chat/api/sessions").json()["sessions"]
        by_id = {s["session_id"]: s for s in sessions}
        assert by_id[session_id_1]["is_active"] is True
        assert by_id[session_id_2]["is_active"] is False
```

### Step 2: Run to verify the new tests fail

```bash
pytest tests/test_web_chat.py::TestWebChatSessionResumeAPI -v
```

Expected: `FAILED` — `404 Not Found`

### Step 3: Add the `POST /api/session/resume` route to `__init__.py`

Add this route to `src/amplifier_distro/server/apps/web_chat/__init__.py`, after the `list_sessions` route and **before** `manifest = AppManifest(...)`:

```python
@router.post("/api/session/resume")
async def resume_session(request: Request) -> JSONResponse:
    """Resume a previously created session.

    Body:
        session_id: str - The session to resume

    Returns:
        200 with {session_id, resumed: true} on success
        400 if session_id is missing
        404 if session_id is not found in the registry
    """
    body = await request.json() if await request.body() else {}
    session_id = body.get("session_id")

    if not session_id:
        return JSONResponse(
            status_code=400,
            content={"error": "session_id is required"},
        )

    try:
        manager = _get_manager()
        session = manager.resume_session(session_id)
        return JSONResponse(
            content={
                "session_id": session.session_id,
                "resumed": True,
            }
        )
    except ValueError as e:
        return JSONResponse(
            status_code=404,
            content={"error": str(e)},
        )
```

### Step 4: Run the new tests to verify they pass

```bash
pytest tests/test_web_chat.py::TestWebChatSessionResumeAPI -v
```

Expected: all 6 tests pass.

### Step 5: Run full suite

```bash
pytest tests/test_web_chat.py tests/test_web_chat_store.py -v
```

Expected: all tests pass. Check the total count — should be all original tests plus the new ones.

### Step 6: Commit

```bash
git add src/amplifier_distro/server/apps/web_chat/__init__.py \
        tests/test_web_chat.py
git commit -m "feat: add POST /api/session/resume endpoint"
```

---

## Task 8: Update frontend — sessions panel, auto-create fix, JS functions

**Files:**
- Modify: `src/amplifier_distro/server/apps/web_chat/static/index.html`

This is a frontend-only task. No Python tests needed — the API endpoints are already tested. The work is:
1. Add CSS for the sessions dropdown panel
2. Add Sessions button + panel HTML in the header
3. Add 5 JS functions
4. Fix `sendMessage()` to auto-create session before sending

### Step 1: Add sessions panel CSS

In `static/index.html`, find the existing `@media (max-width: 640px)` block at the end of the `<style>` section (around line 348). **Before** the `@media` block, add:

```css
/* ------------------------------------------------------------------ */
/*  Sessions Panel                                                     */
/* ------------------------------------------------------------------ */
.sessions-wrapper {
  position: relative;
}

.sessions-panel {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  width: 320px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  z-index: 100;
  overflow: hidden;
}

.sessions-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.new-session-btn {
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  font-family: var(--font);
  font-weight: 600;
}
.new-session-btn:hover { background: var(--accent-hover); }

.sessions-list { max-height: 360px; overflow-y: auto; }

.session-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  cursor: pointer;
  border-bottom: 1px solid rgba(75,85,99,0.4);
  transition: background 0.1s;
}
.session-row:hover { background: var(--bg-card); }
.session-row:last-child { border-bottom: none; }

.session-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.session-dot.active  { background: var(--success); }
.session-dot.inactive {
  background: transparent;
  border: 2px solid var(--text-secondary);
}

.session-row-info { flex: 1; overflow: hidden; min-width: 0; }
.session-row-desc {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text-primary);
}
.session-row-meta {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}
```

### Step 2: Add Sessions button and panel to the HTML header

In `static/index.html`, find the `<div class="header-right">` block (around line 374):

```html
  <div class="header-right">
    <a href="/apps/settings/" class="settings-btn">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
      </svg>
      <span>Settings</span>
    </a>
  </div>
```

Replace with:

```html
  <div class="header-right">
    <!-- Sessions dropdown -->
    <div class="sessions-wrapper">
      <button class="settings-btn" onclick="toggleSessions()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/>
          <line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>
        </svg>
        <span>Sessions</span>
      </button>
      <div class="sessions-panel" id="sessionsPanel" style="display:none">
        <div class="sessions-panel-header">
          <span>Sessions</span>
          <button class="new-session-btn" onclick="createNewSession()">+ New</button>
        </div>
        <div class="sessions-list" id="sessionList">
          <div style="padding:16px;color:var(--text-secondary);font-size:13px;text-align:center">Loading...</div>
        </div>
      </div>
    </div>
    <!-- Settings link -->
    <a href="/apps/settings/" class="settings-btn">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
      </svg>
      <span>Settings</span>
    </a>
  </div>
```

### Step 3: Add sessions JS functions

In `static/index.html`, find the `/* State */` section at the top of the `<script>` block:

```javascript
let sessionConnected = false;
```

Add `let sessionsPanelOpen = false;` on the next line:

```javascript
let sessionConnected = false;
let sessionsPanelOpen = false;
```

### Step 4: Add the 5 new JS functions

In `static/index.html`, find the `/* Session Status */` comment block. **Before** it, insert the new functions:

```javascript
/* ------------------------------------------------------------------ */
/*  Sessions Panel                                                     */
/* ------------------------------------------------------------------ */
function toggleSessions() {
  const panel = document.getElementById('sessionsPanel');
  sessionsPanelOpen = !sessionsPanelOpen;
  panel.style.display = sessionsPanelOpen ? 'block' : 'none';
  if (sessionsPanelOpen) loadSessions();
}

async function loadSessions() {
  const list = document.getElementById('sessionList');
  list.innerHTML = '<div style="padding:16px;color:var(--text-secondary);font-size:13px;text-align:center">Loading...</div>';
  try {
    const res = await fetch('./api/sessions');
    const data = await res.json();
    renderSessionList(data.sessions || []);
  } catch {
    list.innerHTML = '<div style="padding:16px;color:var(--error);font-size:13px;text-align:center">Failed to load sessions.</div>';
  }
}

function renderSessionList(sessions) {
  const list = document.getElementById('sessionList');
  if (!sessions.length) {
    list.innerHTML = '<div style="padding:16px;color:var(--text-secondary);font-size:13px;text-align:center">No sessions yet. Start chatting to create one.</div>';
    return;
  }
  list.innerHTML = sessions.map(s => {
    const ts = s.last_active
      ? new Date(s.last_active).toLocaleString(undefined, { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' })
      : '';
    const shortId = s.session_id.slice(0, 8);
    const dotClass = s.is_active ? 'active' : 'inactive';
    const desc = esc(s.description || 'Web chat session');
    return `<div class="session-row" onclick="resumeSessionById('${esc(s.session_id)}')">
      <span class="session-dot ${dotClass}"></span>
      <div class="session-row-info">
        <div class="session-row-desc">${desc}</div>
        <div class="session-row-meta">${shortId} &middot; ${ts}</div>
      </div>
    </div>`;
  }).join('');
}

async function resumeSessionById(sessionId) {
  document.getElementById('sessionsPanel').style.display = 'none';
  sessionsPanelOpen = false;
  try {
    const res = await fetch('./api/session/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!res.ok) {
      const err = await res.json();
      addMessage('system', '<p>Could not resume session: ' + esc(err.error || 'Unknown error') + '</p>');
      return;
    }
    const data = await res.json();
    sessionConnected = true;
    updateBadge();
    document.getElementById('chatArea').innerHTML = '';
    addMessage('system', '<p>Resumed session <code>' + esc(data.session_id.slice(0, 8)) + '</code></p>');
  } catch {
    addMessage('system', '<p>Failed to resume session.</p>');
  }
}

async function createNewSession() {
  document.getElementById('sessionsPanel').style.display = 'none';
  sessionsPanelOpen = false;
  try {
    const res = await fetch('./api/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      const err = await res.json();
      addMessage('system', '<p>Could not create session: ' + esc(err.error || 'Unknown error') + '</p>');
      return;
    }
    const data = await res.json();
    sessionConnected = true;
    updateBadge();
    document.getElementById('chatArea').innerHTML = '';
    addMessage('system', '<p>New session started <code>' + esc(data.session_id.slice(0, 8)) + '</code></p>');
  } catch {
    addMessage('system', '<p>Failed to create session.</p>');
  }
}
```

### Step 5: Fix `sendMessage()` to auto-create session on first message

Find the existing `sendMessage()` function:

```javascript
async function sendMessage() {
  const text = messageInput.value.trim();
  if (!text) return;

  // Show user message
  addMessage('user', '<p>' + esc(text) + '</p>');
  messageInput.value = '';
  autoResize();

  // Try sending to backend
  showTyping();
  try {
    const res = await fetch('./api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });
    const data = await res.json();
    removeTyping();
    addMessage('assistant', '<p>' + esc(data.response) + '</p>');
  } catch {
    removeTyping();
    addMessage('system',
      '<p>Could not reach the chat API. ' +
      'Make sure the Amplifier server is running.</p>'
    );
  }
}
```

Replace it with:

```javascript
async function sendMessage() {
  const text = messageInput.value.trim();
  if (!text) return;

  // Show user message immediately
  addMessage('user', '<p>' + esc(text) + '</p>');
  messageInput.value = '';
  autoResize();

  // Auto-create session on first message if not already connected
  if (!sessionConnected) {
    try {
      const res = await fetch('./api/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (res.ok) {
        sessionConnected = true;
        updateBadge();
      }
    } catch {
      // Will fail gracefully below when we try to send the message
    }
  }

  // Send message to backend
  showTyping();
  try {
    const res = await fetch('./api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });
    const data = await res.json();
    removeTyping();
    if (res.ok) {
      addMessage('assistant', '<p>' + esc(data.response) + '</p>');
    } else {
      addMessage('system', '<p>' + esc(data.error || 'Error sending message') + '</p>');
      sessionConnected = data.session_connected === true;
      updateBadge();
    }
  } catch {
    removeTyping();
    addMessage('system',
      '<p>Could not reach the chat API. ' +
      'Make sure the Amplifier server is running.</p>'
    );
  }
}
```

### Step 6: Verify the existing frontend tests still pass

The existing `TestWebChatIndexEndpoint` tests check that the HTML contains certain strings. Verify they still pass:

```bash
pytest tests/test_web_chat.py::TestWebChatIndexEndpoint -v
```

Expected: all 6 tests pass (the HTML still contains `Amplifier`, `chatArea`, `/apps/settings/`, `messageInput`).

### Step 7: Run the full test suite one final time

```bash
pytest tests/test_web_chat.py tests/test_web_chat_store.py -v
```

Expected: all tests pass. Zero failures, zero errors.

### Step 8: Commit

```bash
git add src/amplifier_distro/server/apps/web_chat/static/index.html
git commit -m "feat: add sessions panel, auto-create on first message"
```

---

## Final Verification

Run the complete test suite for both test files:

```bash
cd /Users/samule/repo/distro-pr-50
pytest tests/test_web_chat.py tests/test_web_chat_store.py -v --tb=short
```

Expected summary line:
```
XX passed in X.XXs
```

(No failures, no errors, no skips.)

---

## Summary of All Changes

| File | Change |
|------|--------|
| `src/amplifier_distro/conventions.py` | +1 line: `WEB_CHAT_SESSIONS_FILENAME` |
| `src/amplifier_distro/server/apps/web_chat/session_store.py` | **NEW**: `WebChatSession` + `WebChatSessionStore` |
| `src/amplifier_distro/server/apps/web_chat/__init__.py` | Replace globals with `WebChatSessionManager`; add 2 new routes |
| `src/amplifier_distro/server/apps/web_chat/static/index.html` | Sessions panel CSS/HTML/JS; fix `sendMessage()` |
| `tests/test_web_chat_store.py` | **NEW**: 43 tests for dataclass, store, manager |
| `tests/test_web_chat.py` | Update fixture; add 13 new API tests |

## Deferred (not in this plan)

- Frontend transcript replay on session resume (backend capability exists, UI left for follow-on)
- Cross-surface session discovery (seeing CLI sessions in web chat)
