"""Tests for session-info.json persistence (Issue #53).

Covers the _write_session_info() and _read_session_info_working_dir()
helpers in bridge.py, plus their integration into create_session()
and resume_session().
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

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
