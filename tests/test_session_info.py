"""Tests for session-info.json persistence (Issue #53).

Covers the _write_session_info() and _read_session_info_working_dir()
helpers in bridge.py, plus their integration into create_session()
and resume_session().
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amplifier_distro.bridge import BridgeConfig, LocalBridge

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
        assert session_dir is not None
        info_file = session_dir / "session-info.json"
        assert info_file.exists(), f"session-info.json not found in {session_dir}"
        data = json.loads(info_file.read_text())
        assert data["working_dir"] == str(working_dir.resolve())
        assert "created_at" in data

    def test_create_succeeds_even_if_session_info_write_fails(
        self, tmp_path: Path
    ) -> None:
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
        """session-info.json working_dir is passed to create_session."""
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
        actual_cwd = call_kwargs.kwargs.get("session_cwd") or call_kwargs[1].get(
            "session_cwd"
        )
        assert actual_cwd == Path(original_cwd), (
            f"Expected session_cwd={original_cwd}, got {actual_cwd}"
        )

    def test_resume_falls_back_when_no_session_info(self, tmp_path: Path) -> None:
        """Without session-info.json, resume uses config.working_dir."""
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
        actual_cwd = call_kwargs.kwargs.get("session_cwd") or call_kwargs[1].get(
            "session_cwd"
        )
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
        actual_cwd = call_kwargs.kwargs.get("session_cwd") or call_kwargs[1].get(
            "session_cwd"
        )
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
        """With config=None (_reconnect), persisted CWD overrides Path.cwd()."""
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
        actual_cwd = call_kwargs.kwargs.get("session_cwd") or call_kwargs[1].get(
            "session_cwd"
        )
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
        assert info_file.exists(), (
            "session-info.json should be backfilled on first resume"
        )
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
        assert session_dir is not None, "create_session must set _session_dir"

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

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load2, mock_reg2),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", "projects"),
        ):
            resume_handle = asyncio.run(
                bridge.resume_session(session_id, resume_config)
            )

        # Verify: the session was created with the ORIGINAL cwd, not server cwd
        call_kwargs = mock_prepared2.create_session.call_args
        actual_cwd = call_kwargs.kwargs.get("session_cwd") or call_kwargs[1].get(
            "session_cwd"
        )
        assert actual_cwd == original_cwd, (
            f"Expected session_cwd={original_cwd}, got {actual_cwd}. "
            "Issue #53 regression: resume used server CWD instead of original."
        )

        # Verify: the handle also reports the correct working_dir
        assert resume_handle.working_dir == original_cwd
