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


# ---------------------------------------------------------------------------
# Tests for _read_session_info_working_dir()
# ---------------------------------------------------------------------------


class TestReadSessionInfoWorkingDir:
    """Verify _read_session_info_working_dir() reads correctly and handles errors."""

    def test_returns_path_from_valid_file(self, tmp_path: Path) -> None:
        """Reads working_dir from a well-formed session-info.json."""
        from amplifier_distro.bridge import _read_session_info_working_dir

        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()
        info = {
            "working_dir": "/Users/testuser",
            "created_at": "2026-02-18T15:00:00+00:00",
        }
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
        (session_dir / "session-info.json").write_text(
            json.dumps({"created_at": "2026-01-01"})
        )

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
        """Round-trip works for home directory path."""
        from amplifier_distro.bridge import (
            _read_session_info_working_dir,
            _write_session_info,
        )

        session_dir = tmp_path / "session-abc"
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
        original = Path("/Users/sam/my-project")

        _write_session_info(session_dir, original)
        recovered = _read_session_info_working_dir(session_dir)

        assert recovered == original

    def test_round_trip_with_tilde_path(self, tmp_path: Path) -> None:
        """Round-trip expands ~ on write and recovers expanded path."""
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
