# Session CWD Persistence Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Fix Issue #53 — prevent duplicate session directories on resume by persisting the original `working_dir` in `session-info.json` at creation time and reading it back at resume time.

**Architecture:** Two touch points in `bridge.py`, plus two small helper functions. At session creation, `_write_session_info()` writes a `session-info.json` file into the session directory with the original `working_dir`. At resume time, `_read_session_info_working_dir()` reads it back into a local `effective_cwd` variable (without mutating the caller's config) before `prepared.create_session()` is called — so `hooks-logging` mounts with the correct CWD. When resuming pre-fix sessions that lack the file, the effective CWD falls back to `config.working_dir` and the file is backfilled so subsequent resumes are stable. Both helpers are best-effort (never crash the session lifecycle). A new test file `tests/test_session_info.py` covers all behavior.

**Tech Stack:** Python 3.11+, pytest + pytest-asyncio, `atomic_write` from `amplifier_distro.fileutil`, `SESSION_INFO_FILENAME` from `amplifier_distro.conventions`.

---

## Pre-flight

Before starting, create the feature branch:

```bash
cd /Users/samule/repo/distro-2
git checkout main
git pull origin main
git checkout -b fix/53-session-cwd-persistence
```

Verify existing tests pass:

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/test_bridge.py tests/test_bridge_resume.py tests/test_conventions.py -v --tb=short
```

Expected: 134 passed.

---

## Task 1: `_write_session_info()` helper

Write a module-level helper function in `bridge.py` that persists session metadata to `session-info.json`. This function is best-effort — it never raises exceptions.

**Files:**
- Create: `tests/test_session_info.py` (new test file)
- Modify: `src/amplifier_distro/bridge.py` (add import + helper function)

### Step 1: Write failing tests for `_write_session_info`

Create the file `tests/test_session_info.py` with these initial tests:

```python
"""Tests for session-info.json persistence (Issue #53).

Covers the _write_session_info() and _read_session_info_working_dir()
helpers in bridge.py, plus their integration into create_session()
and resume_session().
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Tests for _write_session_info()
# ---------------------------------------------------------------------------


class TestWriteSessionInfo:
    """Verify _write_session_info() writes correct JSON and handles errors."""

    def test_writes_valid_json_with_working_dir(self, tmp_path: Path) -> None:
        """session-info.json contains working_dir as a string."""
        from amplifier_distro.bridge import _write_session_info

        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()
        working_dir = Path("/Users/testuser")

        _write_session_info(session_dir, working_dir)

        info_file = session_dir / "session-info.json"
        assert info_file.exists()
        data = json.loads(info_file.read_text())
        assert data["working_dir"] == "/Users/testuser"

    def test_writes_created_at_timestamp(self, tmp_path: Path) -> None:
        """session-info.json contains a created_at ISO timestamp."""
        from amplifier_distro.bridge import _write_session_info

        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()

        _write_session_info(session_dir, Path("/tmp"))

        data = json.loads((session_dir / "session-info.json").read_text())
        assert "created_at" in data
        # Basic sanity: ISO format contains 'T' separator
        assert "T" in data["created_at"]

    def test_creates_session_dir_if_missing(self, tmp_path: Path) -> None:
        """session_dir is created if it doesn't exist yet."""
        from amplifier_distro.bridge import _write_session_info

        session_dir = tmp_path / "deep" / "nested" / "session-xyz"
        assert not session_dir.exists()

        _write_session_info(session_dir, Path("/Users/testuser"))

        assert session_dir.exists()
        assert (session_dir / "session-info.json").exists()

    def test_uses_session_info_filename_convention(self, tmp_path: Path) -> None:
        """The file is named using SESSION_INFO_FILENAME from conventions."""
        from amplifier_distro.bridge import _write_session_info
        from amplifier_distro.conventions import SESSION_INFO_FILENAME

        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()

        _write_session_info(session_dir, Path("/tmp"))

        assert (session_dir / SESSION_INFO_FILENAME).exists()

    def test_handles_write_failure_gracefully(self, tmp_path: Path) -> None:
        """If atomic_write raises, the exception does NOT propagate."""
        from amplifier_distro.bridge import _write_session_info

        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()

        with patch(
            "amplifier_distro.bridge.atomic_write",
            side_effect=OSError("disk full"),
        ):
            # Must not raise
            _write_session_info(session_dir, Path("/tmp"))

        # File should not exist since write failed
        assert not (session_dir / "session-info.json").exists()

    def test_resolves_working_dir_path(self, tmp_path: Path) -> None:
        """working_dir is stored as a resolved absolute path string."""
        from amplifier_distro.bridge import _write_session_info

        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()

        # Pass a relative-ish path
        _write_session_info(session_dir, Path("/Users/sam/../sam"))

        data = json.loads((session_dir / "session-info.json").read_text())
        # Should be resolved (no ".." components)
        assert ".." not in data["working_dir"]
        assert data["working_dir"] == "/Users/sam"

    def test_expands_tilde_in_working_dir(self, tmp_path: Path) -> None:
        """~ is expanded to the real home directory before storage."""
        from amplifier_distro.bridge import _write_session_info

        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()

        _write_session_info(session_dir, Path("~"))

        data = json.loads((session_dir / "session-info.json").read_text())
        assert "~" not in data["working_dir"]
        assert data["working_dir"] == str(Path.home())
```

### Step 2: Run tests — verify they fail

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/test_session_info.py::TestWriteSessionInfo -v
```

Expected: FAIL — `ImportError: cannot import name '_write_session_info' from 'amplifier_distro.bridge'`

### Step 3: Implement `_write_session_info` in bridge.py

**3a.** Add `SESSION_INFO_FILENAME` to the conventions import at lines 35-42.

In `src/amplifier_distro/bridge.py`, find the import block:

```python
from amplifier_distro.conventions import (
    AMPLIFIER_HOME,
    DISTRO_BUNDLE_DIR,
    DISTRO_BUNDLE_FILENAME,
    HANDOFF_FILENAME,
    PROJECTS_DIR,
    TRANSCRIPT_FILENAME,
)
```

Replace with:

```python
from amplifier_distro.conventions import (
    AMPLIFIER_HOME,
    DISTRO_BUNDLE_DIR,
    DISTRO_BUNDLE_FILENAME,
    HANDOFF_FILENAME,
    PROJECTS_DIR,
    SESSION_INFO_FILENAME,
    TRANSCRIPT_FILENAME,
)
```

**3b.** Add a top-level import for `atomic_write` after the conventions import block (after line 42, before `logger = logging.getLogger(__name__)`):

```python
from amplifier_distro.fileutil import atomic_write
```

**3c.** Add the `_write_session_info` function after the `_encode_cwd` function (after line 53). Insert it between `_encode_cwd` and the `BridgeConfig` dataclass:

```python
def _write_session_info(session_dir: Path, working_dir: Path) -> None:
    """Persist session metadata to session-info.json (best-effort).

    Writes the original working_dir so resume_session() can recover it
    instead of defaulting to the server's CWD. Uses atomic_write for
    crash safety.

    Never raises — all errors are logged and swallowed.
    """
    try:
        session_dir.mkdir(parents=True, exist_ok=True)
        info = {
            "working_dir": str(working_dir.expanduser().resolve()),
            "created_at": datetime.now(UTC).isoformat(),
        }
        atomic_write(
            session_dir / SESSION_INFO_FILENAME,
            json.dumps(info, indent=2),
        )
        logger.debug(
            "Wrote session-info.json to %s (working_dir=%s)",
            session_dir,
            working_dir,
        )
    except Exception:
        logger.warning(
            "Failed to write session-info.json to %s",
            session_dir,
            exc_info=True,
        )
```

### Step 4: Run tests — verify they pass

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/test_session_info.py::TestWriteSessionInfo -v
```

Expected: 7 passed.

### Step 5: Run existing tests — verify no regressions

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/test_bridge.py tests/test_bridge_resume.py tests/test_conventions.py -v --tb=short
```

Expected: 134 passed (same as before).

### Step 6: Commit

```bash
cd /Users/samule/repo/distro-2
git add src/amplifier_distro/bridge.py tests/test_session_info.py
git commit -m "feat: add _write_session_info helper for session CWD persistence (#53)

Adds a best-effort helper that writes session-info.json with the
original working_dir and created_at timestamp. Uses atomic_write
for crash safety. Expands ~ and resolves the path before storage.
Never raises — errors are logged and swallowed.

Activates the SESSION_INFO_FILENAME convention that was reserved
in conventions.py but never implemented."
```

---

## Task 2: `_read_session_info_working_dir()` helper

Write the reader counterpart that extracts `working_dir` from `session-info.json`.

**Files:**
- Modify: `tests/test_session_info.py` (add reader tests)
- Modify: `src/amplifier_distro/bridge.py` (add reader function)

### Step 1: Write failing tests for `_read_session_info_working_dir`

Append to `tests/test_session_info.py`:

```python
# ---------------------------------------------------------------------------
# Tests for _read_session_info_working_dir()
# ---------------------------------------------------------------------------


class TestReadSessionInfoWorkingDir:
    """Verify _read_session_info_working_dir() reads correctly and handles all error cases."""

    def test_returns_path_from_valid_file(self, tmp_path: Path) -> None:
        """Reads working_dir from a well-formed session-info.json."""
        from amplifier_distro.bridge import _read_session_info_working_dir

        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()
        info = {"working_dir": "/Users/testuser", "created_at": "2026-02-18T15:00:00+00:00"}
        (session_dir / "session-info.json").write_text(json.dumps(info))

        result = _read_session_info_working_dir(session_dir)

        assert result == Path("/Users/testuser")

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        """Returns None when session-info.json does not exist."""
        from amplifier_distro.bridge import _read_session_info_working_dir

        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()

        result = _read_session_info_working_dir(session_dir)

        assert result is None

    def test_returns_none_for_corrupt_json(self, tmp_path: Path) -> None:
        """Returns None when file contains invalid JSON."""
        from amplifier_distro.bridge import _read_session_info_working_dir

        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()
        (session_dir / "session-info.json").write_text("not valid json {{{")

        result = _read_session_info_working_dir(session_dir)

        assert result is None

    def test_returns_none_for_missing_working_dir_key(self, tmp_path: Path) -> None:
        """Returns None when JSON is valid but working_dir key is absent."""
        from amplifier_distro.bridge import _read_session_info_working_dir

        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()
        (session_dir / "session-info.json").write_text(json.dumps({"created_at": "2026-01-01"}))

        result = _read_session_info_working_dir(session_dir)

        assert result is None

    def test_returns_none_for_empty_working_dir(self, tmp_path: Path) -> None:
        """Returns None when working_dir is an empty string."""
        from amplifier_distro.bridge import _read_session_info_working_dir

        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()
        (session_dir / "session-info.json").write_text(json.dumps({"working_dir": ""}))

        result = _read_session_info_working_dir(session_dir)

        assert result is None

    def test_returns_none_for_nonexistent_session_dir(self, tmp_path: Path) -> None:
        """Returns None when the session directory itself doesn't exist."""
        from amplifier_distro.bridge import _read_session_info_working_dir

        result = _read_session_info_working_dir(tmp_path / "does-not-exist")

        assert result is None

    def test_returns_none_for_permission_error(self, tmp_path: Path) -> None:
        """Returns None when file exists but is unreadable."""
        from amplifier_distro.bridge import _read_session_info_working_dir

        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()
        info_file = session_dir / "session-info.json"
        info_file.write_text(json.dumps({"working_dir": "/Users/test"}))
        info_file.chmod(0o000)

        try:
            result = _read_session_info_working_dir(session_dir)
            assert result is None
        finally:
            info_file.chmod(0o644)  # restore for tmp_path cleanup

    def test_returns_none_for_non_string_working_dir(self, tmp_path: Path) -> None:
        """Returns None when working_dir is not a string (e.g. int, null)."""
        from amplifier_distro.bridge import _read_session_info_working_dir

        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()
        (session_dir / "session-info.json").write_text(json.dumps({"working_dir": 42}))

        result = _read_session_info_working_dir(session_dir)

        assert result is None
```

### Step 2: Run tests — verify they fail

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/test_session_info.py::TestReadSessionInfoWorkingDir -v
```

Expected: FAIL — `ImportError: cannot import name '_read_session_info_working_dir' from 'amplifier_distro.bridge'`

### Step 3: Implement `_read_session_info_working_dir` in bridge.py

Add immediately after the `_write_session_info` function:

```python
def _read_session_info_working_dir(session_dir: Path) -> Path | None:
    """Read the original working_dir from session-info.json.

    Returns the persisted working directory as a Path, or None if the
    file is missing, corrupt, or lacks the working_dir key.

    Used by resume_session() to recover the original CWD instead of
    defaulting to the server's current directory.

    Never raises — all errors are logged and swallowed.
    """
    info_file = session_dir / SESSION_INFO_FILENAME
    try:
        data = json.loads(info_file.read_text(encoding="utf-8"))
        working_dir = data["working_dir"]
        if not isinstance(working_dir, str) or not working_dir:
            logger.warning(
                "session-info.json in %s has invalid working_dir=%r, ignoring",
                session_dir,
                working_dir,
            )
            return None
        logger.debug(
            "Read working_dir=%s from session-info.json in %s",
            working_dir,
            session_dir,
        )
        return Path(working_dir)
    except FileNotFoundError:
        logger.debug(
            "No session-info.json in %s (pre-fix session), will use default working_dir",
            session_dir,
        )
        return None
    except (json.JSONDecodeError, KeyError):
        logger.warning(
            "Invalid or incomplete session-info.json in %s, will use default working_dir",
            session_dir,
            exc_info=True,
        )
        return None
    except OSError:
        logger.warning(
            "Could not read session-info.json from %s, will use default working_dir",
            session_dir,
            exc_info=True,
        )
        return None
    except Exception:
        logger.warning(
            "Unexpected error reading session-info.json from %s",
            session_dir,
            exc_info=True,
        )
        return None
```

### Step 4: Run tests — verify they pass

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/test_session_info.py::TestReadSessionInfoWorkingDir -v
```

Expected: 8 passed.

### Step 5: Write and run the round-trip tests

Append to `tests/test_session_info.py`:

```python
# ---------------------------------------------------------------------------
# Round-trip test: write then read
# ---------------------------------------------------------------------------


class TestSessionInfoRoundTrip:
    """Verify write + read produces consistent results."""

    def test_write_then_read_returns_same_path(self, tmp_path: Path) -> None:
        """Writing then reading recovers the original working_dir."""
        from amplifier_distro.bridge import (
            _read_session_info_working_dir,
            _write_session_info,
        )

        session_dir = tmp_path / "session-abc"
        original = Path("/Users/testuser/projects/my-app")

        _write_session_info(session_dir, original)
        recovered = _read_session_info_working_dir(session_dir)

        assert recovered == original

    def test_round_trip_with_home_dir(self, tmp_path: Path) -> None:
        """Round-trip works for home directory path (common Slack session CWD)."""
        from amplifier_distro.bridge import (
            _read_session_info_working_dir,
            _write_session_info,
        )

        session_dir = tmp_path / "session-abc"
        # Simulate the common Slack case: working_dir = expanduser("~")
        home = Path.home()

        _write_session_info(session_dir, home)
        recovered = _read_session_info_working_dir(session_dir)

        assert recovered == home

    def test_round_trip_with_hyphenated_path(self, tmp_path: Path) -> None:
        """Round-trip preserves hyphens (which _encode_cwd loses)."""
        from amplifier_distro.bridge import (
            _read_session_info_working_dir,
            _write_session_info,
        )

        session_dir = tmp_path / "session-abc"
        # This path would be lossy through _encode_cwd/_decode_project_path
        original = Path("/Users/sam/my-project")

        _write_session_info(session_dir, original)
        recovered = _read_session_info_working_dir(session_dir)

        assert recovered == original

    def test_round_trip_with_tilde_path(self, tmp_path: Path) -> None:
        """Round-trip expands ~ on write and recovers the expanded path on read."""
        from amplifier_distro.bridge import (
            _read_session_info_working_dir,
            _write_session_info,
        )

        session_dir = tmp_path / "session-abc"
        _write_session_info(session_dir, Path("~"))
        recovered = _read_session_info_working_dir(session_dir)

        assert recovered == Path.home()

    @pytest.mark.parametrize(
        "path_str",
        [
            "/Users/sam/my project/with spaces",
            "/Users/sam/développeur/проект",
            "/Users/sam/" + "a" * 200,
            "/Users/sam/path'with\"quotes",
        ],
        ids=["spaces", "unicode", "long", "quotes"],
    )
    def test_round_trip_special_paths(self, tmp_path: Path, path_str: str) -> None:
        """Round-trip preserves paths with special characters."""
        from amplifier_distro.bridge import (
            _read_session_info_working_dir,
            _write_session_info,
        )

        session_dir = tmp_path / "session-abc"
        original = Path(path_str)
        _write_session_info(session_dir, original)
        recovered = _read_session_info_working_dir(session_dir)
        assert recovered == original.expanduser().resolve()
```

Run:

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/test_session_info.py -v
```

Expected: 23 passed (7 write + 8 read + 8 round-trip).

### Step 6: Commit

```bash
cd /Users/samule/repo/distro-2
git add src/amplifier_distro/bridge.py tests/test_session_info.py
git commit -m "feat: add _read_session_info_working_dir helper (#53)

Reads working_dir from session-info.json. Returns None if file is
missing, corrupt, or lacks the key. Never raises.

Logging severity is split by error type:
- FileNotFoundError -> DEBUG (expected for pre-fix sessions)
- JSONDecodeError/KeyError -> WARNING with exc_info (data corruption)
- OSError -> WARNING with exc_info (IO/permission errors)

Includes round-trip tests verifying write-then-read consistency,
including hyphenated paths, Unicode, spaces, and quotes."
```

---

## Task 3: Integrate `_write_session_info` into `create_session()`

Wire the writer into the session creation flow.

**Files:**
- Modify: `src/amplifier_distro/bridge.py` (one line in `create_session()`)
- Modify: `tests/test_session_info.py` (add integration test)

### Step 1: Write failing test

Append to `tests/test_session_info.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock

from amplifier_distro.bridge import BridgeConfig, LocalBridge

# ---------------------------------------------------------------------------
# Integration: create_session writes session-info.json
# ---------------------------------------------------------------------------


def _mock_foundation_chain():
    """Create mocks for the amplifier-foundation load/prepare/create chain."""
    mock_session = MagicMock()
    mock_session.coordinator.session_id = "test-session-id-12345678"
    mock_session.coordinator.hooks.register = MagicMock()

    mock_prepared = AsyncMock()
    mock_prepared.create_session = AsyncMock(return_value=mock_session)

    mock_bundle = AsyncMock()
    mock_bundle.prepare = AsyncMock(return_value=mock_prepared)

    mock_load_bundle = AsyncMock(return_value=mock_bundle)
    mock_registry_cls = MagicMock()

    return mock_load_bundle, mock_registry_cls, mock_session


class TestCreateSessionWritesSessionInfo:
    """Verify create_session() persists session-info.json."""

    def test_session_info_written_on_create(self, tmp_path: Path) -> None:
        """create_session() writes session-info.json with the correct working_dir."""
        bridge = LocalBridge()
        bridge._config = {
            "workspace_root": "~/dev",
            "preflight": {"enabled": False},
            "bundle": {"active": "test-bundle"},
        }
        working_dir = Path("/Users/testuser")
        config = BridgeConfig(
            working_dir=working_dir,
            bundle_name="test-bundle",
            run_preflight=False,
        )

        mock_load, mock_reg, _ = _mock_foundation_chain()

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
        ):
            handle = asyncio.run(bridge.create_session(config))

        # Verify session-info.json was written in the session directory
        session_dir = handle._session_dir
        info_file = session_dir / "session-info.json"
        assert info_file.exists(), f"session-info.json not found in {session_dir}"
        data = json.loads(info_file.read_text())
        assert data["working_dir"] == str(working_dir.resolve())
        assert "created_at" in data

    def test_create_succeeds_even_if_session_info_write_fails(self, tmp_path: Path) -> None:
        """Session creation completes even if _write_session_info fails."""
        bridge = LocalBridge()
        bridge._config = {
            "workspace_root": "~/dev",
            "preflight": {"enabled": False},
            "bundle": {"active": "test-bundle"},
        }
        config = BridgeConfig(
            working_dir=Path("/Users/testuser"),
            bundle_name="test-bundle",
            run_preflight=False,
        )

        mock_load, mock_reg, _ = _mock_foundation_chain()

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch(
                "amplifier_distro.bridge._write_session_info",
                side_effect=Exception("catastrophic failure"),
            ),
        ):
            # Must not raise — session creation must complete
            handle = asyncio.run(bridge.create_session(config))

        assert handle is not None
        assert handle.session_id == "test-session-id-12345678"
```

### Step 2: Run tests — verify they fail

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/test_session_info.py::TestCreateSessionWritesSessionInfo -v
```

Expected: `test_session_info_written_on_create` FAILS (no `session-info.json` written yet).

### Step 3: Add `_write_session_info` call to `create_session()`

In `src/amplifier_distro/bridge.py`, in the `create_session()` method, find the block that computes `session_dir` (currently lines 361-368):

```python
        sid = session.coordinator.session_id
        session_dir = (
            Path(AMPLIFIER_HOME).expanduser()
            / PROJECTS_DIR
            / _encode_cwd(config.working_dir)
            / "sessions"
            / sid
        )
```

Immediately after this block and **before** the `logger.info(...)` call at line 370, insert:

```python
        # Persist session metadata for resume (Issue #53).
        # Note: if the process crashes before hooks-logging writes transcript.jsonl,
        # this directory will contain only session-info.json. resume_session() handles
        # the empty-transcript case gracefully.
        _write_session_info(session_dir, config.working_dir)
```

### Step 4: Run tests — verify they pass

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/test_session_info.py::TestCreateSessionWritesSessionInfo -v
```

Expected: 2 passed.

### Step 5: Run full bridge test suite — verify no regressions

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/test_bridge.py tests/test_bridge_resume.py tests/test_session_info.py -v --tb=short
```

Expected: All pass (existing 134 + new tests).

### Step 6: Commit

```bash
cd /Users/samule/repo/distro-2
git add src/amplifier_distro/bridge.py tests/test_session_info.py
git commit -m "feat: write session-info.json in create_session() (#53)

Calls _write_session_info() after session_dir is computed, persisting
the original working_dir. This activates the session-info.json
convention that was reserved but never implemented."
```

---

## Task 4: Integrate `_read_session_info_working_dir` into `resume_session()`

Wire the reader into the resume flow. Uses a local `effective_cwd` variable instead of mutating `config.working_dir` (since `resume_session()` is a public API — callers don't expect their config to be modified). When `session-info.json` is missing (pre-fix sessions), backfills it so subsequent resumes are stable.

**Files:**
- Modify: `src/amplifier_distro/bridge.py` (add read + override in `resume_session()`)
- Modify: `tests/test_session_info.py` (add resume integration tests)

### Step 1: Write failing tests

Append to `tests/test_session_info.py`:

```python
# ---------------------------------------------------------------------------
# Integration: resume_session reads session-info.json
# ---------------------------------------------------------------------------

SESSION_ID = "test-session-00000000"
PROJECT_NAME = "test-project"


def _make_session_dir_for_resume(tmp_path: Path) -> Path:
    """Create the directory tree that resume_session() expects."""
    session_dir = tmp_path / PROJECT_NAME / "sessions" / SESSION_ID
    session_dir.mkdir(parents=True)
    return session_dir


def _mock_foundation_for_resume():
    """Return (mock_load_bundle, mock_registry_cls, mock_session, mock_prepared)."""
    mock_session = MagicMock()
    mock_session.coordinator.session_id = SESSION_ID
    mock_session.coordinator.context.set_messages = AsyncMock()
    mock_session.coordinator.hooks.register = MagicMock()

    mock_prepared = AsyncMock()
    mock_prepared.create_session = AsyncMock(return_value=mock_session)

    mock_bundle = AsyncMock()
    mock_bundle.prepare = AsyncMock(return_value=mock_prepared)

    mock_load_bundle = AsyncMock(return_value=mock_bundle)
    mock_registry_cls = MagicMock()

    return mock_load_bundle, mock_registry_cls, mock_session, mock_prepared


class TestResumeSessionReadsSessionInfo:
    """Verify resume_session() recovers original working_dir from session-info.json."""

    def test_resume_uses_persisted_working_dir(self, tmp_path: Path) -> None:
        """When session-info.json exists, its working_dir is passed to create_session."""
        session_dir = _make_session_dir_for_resume(tmp_path)

        # Write session-info.json with the ORIGINAL working_dir
        original_cwd = "/Users/testuser"
        info = {"working_dir": original_cwd, "created_at": "2026-02-18T15:00:00+00:00"}
        (session_dir / "session-info.json").write_text(json.dumps(info))

        mock_load, mock_reg, _, mock_prepared = _mock_foundation_for_resume()

        bridge = LocalBridge()
        # Config with a DIFFERENT working_dir (simulates server restart)
        server_cwd = tmp_path  # this is the "wrong" CWD
        config = BridgeConfig(working_dir=server_cwd)

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", PROJECT_NAME),
        ):
            asyncio.run(bridge.resume_session(SESSION_ID, config))

        # Verify create_session was called with the ORIGINAL cwd, not server cwd
        call_kwargs = mock_prepared.create_session.call_args
        actual_cwd = call_kwargs.kwargs.get("session_cwd") or call_kwargs[1].get("session_cwd")
        assert actual_cwd == Path(original_cwd), (
            f"Expected session_cwd={original_cwd}, got {actual_cwd}"
        )

    def test_resume_falls_back_when_no_session_info(self, tmp_path: Path) -> None:
        """Without session-info.json, resume uses config.working_dir (backward compat)."""
        _make_session_dir_for_resume(tmp_path)
        # No session-info.json written — simulates pre-fix session

        mock_load, mock_reg, _, mock_prepared = _mock_foundation_for_resume()

        bridge = LocalBridge()
        fallback_cwd = tmp_path
        config = BridgeConfig(working_dir=fallback_cwd)

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", PROJECT_NAME),
        ):
            asyncio.run(bridge.resume_session(SESSION_ID, config))

        call_kwargs = mock_prepared.create_session.call_args
        actual_cwd = call_kwargs.kwargs.get("session_cwd") or call_kwargs[1].get("session_cwd")
        assert actual_cwd == fallback_cwd

    def test_resume_falls_back_when_session_info_corrupt(self, tmp_path: Path) -> None:
        """Corrupt session-info.json causes fallback to config.working_dir."""
        session_dir = _make_session_dir_for_resume(tmp_path)
        (session_dir / "session-info.json").write_text("not valid json {{{")

        mock_load, mock_reg, _, mock_prepared = _mock_foundation_for_resume()

        bridge = LocalBridge()
        fallback_cwd = tmp_path
        config = BridgeConfig(working_dir=fallback_cwd)

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", PROJECT_NAME),
        ):
            asyncio.run(bridge.resume_session(SESSION_ID, config))

        call_kwargs = mock_prepared.create_session.call_args
        actual_cwd = call_kwargs.kwargs.get("session_cwd") or call_kwargs[1].get("session_cwd")
        assert actual_cwd == fallback_cwd

    def test_resume_handle_has_correct_working_dir(self, tmp_path: Path) -> None:
        """The returned SessionHandle.working_dir reflects the restored CWD."""
        session_dir = _make_session_dir_for_resume(tmp_path)

        original_cwd = "/Users/testuser"
        info = {"working_dir": original_cwd, "created_at": "2026-02-18T15:00:00+00:00"}
        (session_dir / "session-info.json").write_text(json.dumps(info))

        mock_load, mock_reg, _, _ = _mock_foundation_for_resume()

        bridge = LocalBridge()
        config = BridgeConfig(working_dir=tmp_path)  # "wrong" CWD

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", PROJECT_NAME),
        ):
            handle = asyncio.run(bridge.resume_session(SESSION_ID, config))

        assert handle.working_dir == Path(original_cwd)

    def test_resume_with_no_config_uses_persisted_cwd(self, tmp_path: Path) -> None:
        """When config is None (as in _reconnect), persisted CWD overrides Path.cwd()."""
        session_dir = _make_session_dir_for_resume(tmp_path)
        original_cwd = "/Users/testuser/my-project"
        info = {"working_dir": original_cwd, "created_at": "2026-02-18T15:00:00+00:00"}
        (session_dir / "session-info.json").write_text(json.dumps(info))

        mock_load, mock_reg, _, mock_prepared = _mock_foundation_for_resume()

        bridge = LocalBridge()
        # NOTE: No config passed — mirrors what _reconnect() does
        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", PROJECT_NAME),
        ):
            asyncio.run(bridge.resume_session(SESSION_ID))  # No config!

        call_kwargs = mock_prepared.create_session.call_args
        actual_cwd = call_kwargs.kwargs.get("session_cwd") or call_kwargs[1].get("session_cwd")
        assert actual_cwd == Path(original_cwd)

    def test_resume_backfills_session_info_when_missing(self, tmp_path: Path) -> None:
        """Pre-fix sessions get session-info.json backfilled on first resume."""
        session_dir = _make_session_dir_for_resume(tmp_path)
        # No session-info.json — simulates pre-fix session

        mock_load, mock_reg, _, _ = _mock_foundation_for_resume()

        bridge = LocalBridge()
        config = BridgeConfig(working_dir=tmp_path)

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", PROJECT_NAME),
        ):
            asyncio.run(bridge.resume_session(SESSION_ID, config))

        # Verify backfill happened
        info_file = session_dir / "session-info.json"
        assert info_file.exists(), "session-info.json should be backfilled on first resume"
        data = json.loads(info_file.read_text())
        assert data["working_dir"] == str(tmp_path.resolve())

    def test_resume_does_not_mutate_config(self, tmp_path: Path) -> None:
        """resume_session() must not mutate the caller's BridgeConfig."""
        session_dir = _make_session_dir_for_resume(tmp_path)
        original_cwd = "/Users/testuser"
        info = {"working_dir": original_cwd, "created_at": "2026-02-18T15:00:00+00:00"}
        (session_dir / "session-info.json").write_text(json.dumps(info))

        mock_load, mock_reg, _, _ = _mock_foundation_for_resume()

        bridge = LocalBridge()
        server_cwd = tmp_path
        config = BridgeConfig(working_dir=server_cwd)

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", PROJECT_NAME),
        ):
            asyncio.run(bridge.resume_session(SESSION_ID, config))

        # config.working_dir must NOT have been mutated
        assert config.working_dir == server_cwd
```

### Step 2: Run tests — verify they fail

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/test_session_info.py::TestResumeSessionReadsSessionInfo -v
```

Expected: `test_resume_uses_persisted_working_dir`, `test_resume_handle_has_correct_working_dir`, `test_resume_with_no_config_uses_persisted_cwd`, `test_resume_backfills_session_info_when_missing`, and `test_resume_does_not_mutate_config` FAIL (resume still passes `config.working_dir` unchanged).

### Step 3: Add `_read_session_info_working_dir` call to `resume_session()`

In `src/amplifier_distro/bridge.py`, first update the `resume_session()` docstring:

Find:

```python
    async def resume_session(
        self, session_id: str, config: BridgeConfig | None = None
    ) -> SessionHandle:
        """Resume an existing session.

        Finds the session directory by ID (or prefix), loads the bundle,
        creates a new session, and injects the previous transcript as context.
        """
```

Replace with:

```python
    async def resume_session(
        self, session_id: str, config: BridgeConfig | None = None
    ) -> SessionHandle:
        """Resume an existing session.

        Finds the session directory by ID (or prefix), recovers the original
        working directory from session-info.json (falling back to config.working_dir
        for pre-fix sessions), loads the bundle, creates a new session, and
        injects the previous transcript as context.
        """
```

Next, find the block after session discovery (currently lines 429-435):

```python
        project_id, session_dir = matches[0]
        logger.info(
            "Found session to resume: id=%s project=%s dir=%s",
            session_id,
            project_id,
            session_dir,
        )
```

Immediately **after** this `logger.info(...)` block (after line 435) and **before** `# 2. Load foundation` (line 437), insert:

```python
        # 1b. Recover original working_dir from session-info.json (Issue #53)
        persisted_cwd = _read_session_info_working_dir(session_dir)
        if persisted_cwd is not None:
            effective_cwd = persisted_cwd
            logger.info(
                "Restored original working_dir=%s from session info (was %s)",
                effective_cwd,
                config.working_dir,
            )
        else:
            effective_cwd = config.working_dir
            logger.info(
                "No session info found, using default working_dir=%s",
                effective_cwd,
            )
            # Backfill for pre-fix sessions so subsequent resumes are stable
            _write_session_info(session_dir, effective_cwd)
```

Then update the two downstream sites that use `config.working_dir`:

**Site 1:** Find line 475 (inside `create_session` call):

```python
            session_cwd=config.working_dir,
```

Replace with:

```python
            session_cwd=effective_cwd,
```

**Site 2:** Find line 572 (inside `SessionHandle` return):

```python
            working_dir=config.working_dir,
```

Replace with:

```python
            working_dir=effective_cwd,
```

### Step 4: Run tests — verify they pass

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/test_session_info.py::TestResumeSessionReadsSessionInfo -v
```

Expected: 7 passed.

### Step 5: Run full test suite — verify no regressions

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/test_bridge.py tests/test_bridge_resume.py tests/test_session_info.py tests/test_conventions.py -v --tb=short
```

Expected: All pass.

### Step 6: Commit

```bash
cd /Users/samule/repo/distro-2
git add src/amplifier_distro/bridge.py tests/test_session_info.py
git commit -m "fix: resume_session reads persisted working_dir from session-info.json (#53)

After discovering the session directory, resume_session() now reads
session-info.json to recover the original working_dir into a local
effective_cwd variable (config is not mutated). This prevents
hooks-logging from creating a duplicate session directory under a
different project slug when the server CWD differs from the original.

Falls back to config.working_dir when the file is missing (backward
compat with sessions created before this fix) and backfills
session-info.json so subsequent resumes are stable.

Closes #53. Partially addresses #54 (Bug 2). Improves #31."
```

---

## Task 5: End-to-end round-trip integration test

Verify the complete create -> resume cycle produces consistent CWD behavior.

**Files:**
- Modify: `tests/test_session_info.py` (add integration test)

### Step 1: Write the integration test

Append to `tests/test_session_info.py`:

```python
# ---------------------------------------------------------------------------
# End-to-end: create then resume with different CWD
# ---------------------------------------------------------------------------


class TestCreateThenResumeRoundTrip:
    """Full round-trip: create with one CWD, resume from another, verify consistency."""

    def test_create_then_resume_preserves_cwd(self, tmp_path: Path) -> None:
        """A session created with working_dir=X resumes with the same X,
        even when the server's CWD is Y.

        This is the core regression test for Issue #53.
        """
        original_cwd = Path("/Users/testuser")

        # --- Phase 1: Create session ---
        bridge = LocalBridge()
        bridge._config = {
            "workspace_root": "~/dev",
            "preflight": {"enabled": False},
            "bundle": {"active": "test-bundle"},
        }
        create_config = BridgeConfig(
            working_dir=original_cwd,
            bundle_name="test-bundle",
            run_preflight=False,
        )

        mock_load, mock_reg, _ = _mock_foundation_chain()

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
        ):
            create_handle = asyncio.run(bridge.create_session(create_config))

        session_id = create_handle.session_id
        session_dir = create_handle._session_dir

        # Verify session-info.json was written
        info_file = session_dir / "session-info.json"
        assert info_file.exists()
        data = json.loads(info_file.read_text())
        assert data["working_dir"] == str(original_cwd.resolve())

        # --- Phase 2: Resume from a DIFFERENT CWD ---
        # This simulates a server restart where CWD is the server's directory
        server_cwd = Path("/opt/amplifier-server")

        mock_load2, mock_reg2, _, mock_prepared2 = _mock_foundation_for_resume()

        # We need the session dir to be discoverable under the AMPLIFIER_HOME
        # The create already wrote to tmp_path, so the dir exists there
        resume_config = BridgeConfig(working_dir=server_cwd)

        # Determine the project dir name that create used
        from amplifier_distro.bridge import _encode_cwd

        project_slug = _encode_cwd(original_cwd)

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load2, mock_reg2),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", "projects"),
        ):
            resume_handle = asyncio.run(bridge.resume_session(session_id, resume_config))

        # Verify: the session was created with the ORIGINAL cwd, not server cwd
        call_kwargs = mock_prepared2.create_session.call_args
        actual_cwd = call_kwargs.kwargs.get("session_cwd") or call_kwargs[1].get("session_cwd")
        assert actual_cwd == original_cwd, (
            f"Expected session_cwd={original_cwd}, got {actual_cwd}. "
            "Issue #53 regression: resume used server CWD instead of original."
        )

        # Verify: the handle also reports the correct working_dir
        assert resume_handle.working_dir == original_cwd
```

### Step 2: Run the test

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/test_session_info.py::TestCreateThenResumeRoundTrip -v
```

Expected: 1 passed.

### Step 3: Run the complete test suite

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/ -x -q
```

Expected: All tests pass, zero failures.

### Step 4: Commit

```bash
cd /Users/samule/repo/distro-2
git add tests/test_session_info.py
git commit -m "test: add end-to-end create/resume CWD round-trip test (#53)

Verifies the core Issue #53 fix: a session created with working_dir=X
resumes with the same X even when the server's CWD is Y."
```

---

## Task 6: Code quality check and final commit

**Files:**
- All modified files

### Step 1: Run code quality checks

```bash
cd /Users/samule/repo/distro-2
uv run python -m ruff check src/amplifier_distro/bridge.py tests/test_session_info.py
uv run python -m ruff format --check src/amplifier_distro/bridge.py tests/test_session_info.py
```

Fix any issues reported. Common: line length, import order.

### Step 2: Run the full test suite one final time

```bash
cd /Users/samule/repo/distro-2
uv run python -m pytest tests/ -x -q
```

Expected: All pass.

### Step 3: Push and create PR

```bash
cd /Users/samule/repo/distro-2
git push -u origin fix/53-session-cwd-persistence
```

PR description:

```
## Fix: Resume creates duplicate session directory (#53)

### Problem
When the server restarts and reconnects a session, `resume_session()` defaults
`working_dir` to `Path.cwd()` (the server's directory) instead of the original
session's CWD. `hooks-logging` mounts with the wrong CWD and creates a duplicate
session directory under a different project slug. Second restart finds two
matches -> `ValueError: Ambiguous session prefix`.

### Fix
- **Write:** `create_session()` now writes `session-info.json` (with `working_dir`
  and `created_at`) into the session directory using `atomic_write`. The path is
  expanded (`expanduser`) and resolved before storage.
- **Read:** `resume_session()` reads `session-info.json` from the discovered
  session directory into a local `effective_cwd` variable (the caller's config
  is never mutated), used in place of `config.working_dir` when calling
  `prepared.create_session(session_cwd=...)`.
- **Fallback:** If the file is missing (pre-fix sessions), corrupt, or unreadable,
  resume falls back to `config.working_dir` — same behavior as before.
- **Backfill:** When the file is missing on resume, it is written with the
  current effective CWD so that subsequent resumes are stable.

Both helpers are best-effort (never crash the session lifecycle).

Activates the `SESSION_INFO_FILENAME = "session-info.json"` convention that
was reserved in `conventions.py` since day one but never implemented.

### Testing
- 33 new tests in `tests/test_session_info.py`
- Unit tests for `_write_session_info()` (7 tests)
- Unit tests for `_read_session_info_working_dir()` (8 tests)
- Write/read round-trip tests (8 tests, including parametrized special paths)
- `create_session()` integration tests (2 tests)
- `resume_session()` integration tests (7 tests, including config=None and backfill)
- End-to-end create->resume round-trip (1 test)
- Full suite regression check passes

### Breaking changes
None.

### Manual verification
1. Create a session via Slack or web chat
2. Verify: `cat ~/.amplifier/projects/<slug>/sessions/<id>/session-info.json`
3. Restart the server (or change CWD: `cd /tmp`)
4. Resume the session
5. Verify: NO new directory appears under `~/.amplifier/projects/`
6. Verify: logs show "Restored original working_dir=... from session info (was ...)"

### Related Issues
- Closes #53
- Partially addresses #54 (Bug 2 — ambiguous session prefix)
- Improves #31 (zombie reconnect success)
- Lays groundwork for #24 (session metadata)
- Compatible with #34 (per-session CWD enhancement — remains open)
```

---

## Summary

| Task | What | Tests Added | Files Modified |
|------|------|-------------|----------------|
| 1 | `_write_session_info()` helper | 7 | `bridge.py`, `test_session_info.py` |
| 2 | `_read_session_info_working_dir()` helper | 16 (8 reader + 8 round-trip) | `bridge.py`, `test_session_info.py` |
| 3 | Wire write into `create_session()` | 2 | `bridge.py`, `test_session_info.py` |
| 4 | Wire read into `resume_session()` | 7 | `bridge.py`, `test_session_info.py` |
| 5 | End-to-end round-trip test | 1 | `test_session_info.py` |
| 6 | Code quality + PR | 0 | -- |
| **Total** | | **33** | **2 files** |
