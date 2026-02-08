"""Bridge API Acceptance Tests

These tests validate the Amplifier Bridge - the single interface through
which all Amplifier surfaces (CLI, TUI, Voice, Web, Server) create and
manage sessions.

Exit criteria verified:
1. BridgeConfig has sensible defaults (working_dir is cwd, run_preflight is True)
2. SessionHandle has required fields and enforces initialization
3. LocalBridge implements the AmplifierBridge protocol
4. Project ID derivation works correctly for various path layouts
5. Handoff lookup returns None for nonexistent projects
6. Session creation returns a valid SessionHandle
7. HandoffSummary has all required fields
"""

import asyncio
from pathlib import Path

import pytest

from amplifier_distro.bridge import (
    AmplifierBridge,
    BridgeConfig,
    HandoffSummary,
    LocalBridge,
    SessionHandle,
)


class TestBridgeConfig:
    """Verify BridgeConfig has sensible defaults.

    Antagonist note: BridgeConfig is the entry point for every session
    creation. Its defaults determine what happens when an interface calls
    create_session() without specifying options.
    """

    def test_default_working_dir_is_cwd(self):
        config = BridgeConfig()
        assert config.working_dir == Path.cwd()

    def test_default_run_preflight_is_true(self):
        config = BridgeConfig()
        assert config.run_preflight is True

    def test_default_bundle_name_is_none(self):
        config = BridgeConfig()
        assert config.bundle_name is None

    def test_default_provider_preferences_is_none(self):
        config = BridgeConfig()
        assert config.provider_preferences is None

    def test_default_inject_context_is_none(self):
        config = BridgeConfig()
        assert config.inject_context is None

    def test_custom_working_dir(self):
        custom = Path("/tmp/my-project")
        config = BridgeConfig(working_dir=custom)
        assert config.working_dir == custom

    def test_custom_bundle_name(self):
        config = BridgeConfig(bundle_name="my-bundle")
        assert config.bundle_name == "my-bundle"

    def test_preflight_can_be_disabled(self):
        config = BridgeConfig(run_preflight=False)
        assert config.run_preflight is False


class TestSessionHandle:
    """Verify SessionHandle has required fields and enforces initialization.

    Antagonist note: SessionHandle.run() must raise RuntimeError if the
    underlying session is None. This prevents interfaces from calling
    run() before the session is actually created by foundation.
    """

    def test_required_fields(self):
        handle = SessionHandle(
            session_id="test-123",
            project_id="my-project",
            working_dir=Path("/tmp"),
        )
        assert handle.session_id == "test-123"
        assert handle.project_id == "my-project"
        assert handle.working_dir == Path("/tmp")

    def test_run_raises_when_session_is_none(self):
        """run() must raise RuntimeError if _session is None."""
        handle = SessionHandle(
            session_id="test-123",
            project_id="my-project",
            working_dir=Path("/tmp"),
            _session=None,
        )
        with pytest.raises(RuntimeError, match="Session not initialized"):
            asyncio.run(handle.run("hello"))

    def test_run_streaming_raises_when_session_is_none(self):
        """run_streaming() must raise RuntimeError if _session is None."""
        handle = SessionHandle(
            session_id="test-123",
            project_id="my-project",
            working_dir=Path("/tmp"),
            _session=None,
        )

        async def consume():
            async for _chunk in handle.run_streaming("hello"):
                pass

        with pytest.raises(RuntimeError, match="Session not initialized"):
            asyncio.run(consume())

    def test_session_excluded_from_repr(self):
        """_session should be excluded from repr (it's an internal handle)."""
        handle = SessionHandle(
            session_id="test-123",
            project_id="my-project",
            working_dir=Path("/tmp"),
        )
        repr_str = repr(handle)
        assert "_session" not in repr_str

    def test_session_id_is_string(self):
        handle = SessionHandle(
            session_id="abc-def",
            project_id="proj",
            working_dir=Path("/tmp"),
        )
        assert isinstance(handle.session_id, str)


class TestHandoffSummary:
    """Verify HandoffSummary has all required fields.

    Antagonist note: HandoffSummary is the contract for session continuity.
    Every field must be present and correctly typed. Missing fields break
    the handoff pipeline.
    """

    def test_all_required_fields(self):
        summary = HandoffSummary(
            session_id="sess-001",
            project_id="my-project",
            summary="Did some work on the auth module",
            key_decisions=["chose JWT over session cookies"],
            open_questions=["what about token refresh?"],
            files_modified=["src/auth.py", "tests/test_auth.py"],
            timestamp="2025-01-15T10:30:00Z",
        )
        assert summary.session_id == "sess-001"
        assert summary.project_id == "my-project"
        assert summary.summary == "Did some work on the auth module"
        assert summary.key_decisions == ["chose JWT over session cookies"]
        assert summary.open_questions == ["what about token refresh?"]
        assert summary.files_modified == ["src/auth.py", "tests/test_auth.py"]
        assert summary.timestamp == "2025-01-15T10:30:00Z"

    def test_lists_can_be_empty(self):
        """A trivial session may have empty lists for decisions/questions/files."""
        summary = HandoffSummary(
            session_id="sess-002",
            project_id="p",
            summary="quick check",
            key_decisions=[],
            open_questions=[],
            files_modified=[],
            timestamp="",
        )
        assert summary.key_decisions == []
        assert summary.open_questions == []
        assert summary.files_modified == []

    def test_has_exactly_seven_fields(self):
        """HandoffSummary must have exactly these 7 fields - no more, no less."""
        expected_fields = {
            "session_id",
            "project_id",
            "summary",
            "key_decisions",
            "open_questions",
            "files_modified",
            "timestamp",
        }
        # dataclass fields are in __dataclass_fields__
        actual_fields = set(HandoffSummary.__dataclass_fields__.keys())
        assert actual_fields == expected_fields


class TestLocalBridgeProtocol:
    """Verify LocalBridge implements the AmplifierBridge protocol.

    Antagonist note: The @runtime_checkable decorator on AmplifierBridge
    means isinstance() checks work at runtime. This test proves LocalBridge
    satisfies the protocol contract.
    """

    def test_implements_amplifier_bridge(self):
        bridge = LocalBridge()
        assert isinstance(bridge, AmplifierBridge)

    def test_has_all_protocol_methods(self):
        """LocalBridge must have every method declared in AmplifierBridge."""
        required_methods = [
            "create_session",
            "resume_session",
            "end_session",
            "get_handoff",
            "get_config",
            "get_project_id",
        ]
        bridge = LocalBridge()
        for method_name in required_methods:
            assert hasattr(bridge, method_name), (
                f"LocalBridge missing protocol method: {method_name}"
            )
            assert callable(getattr(bridge, method_name))


class TestLocalBridgeProjectId:
    """Verify LocalBridge.get_project_id() derives IDs correctly.

    Antagonist note: Project ID derivation is critical for session file
    organization. These tests cover three distinct code paths:
    1. Path directly under workspace_root -> first path component
    2. Nested path under workspace_root -> still first component
    3. Path outside workspace_root -> fallback to directory name
    """

    def _make_bridge(self, workspace_root="~/dev"):
        """Create a LocalBridge with pre-set config (skips disk I/O)."""
        bridge = LocalBridge()
        bridge._config = {"workspace_root": workspace_root}
        return bridge

    def test_project_under_workspace(self):
        """~/dev/my-project -> 'my-project'"""
        bridge = self._make_bridge()
        workspace = Path("~/dev").expanduser()
        project_dir = workspace / "my-project"
        assert bridge.get_project_id(project_dir) == "my-project"

    def test_nested_path_under_workspace(self):
        """~/dev/my-project/subdir -> 'my-project'"""
        bridge = self._make_bridge()
        workspace = Path("~/dev").expanduser()
        nested_dir = workspace / "my-project" / "subdir"
        assert bridge.get_project_id(nested_dir) == "my-project"

    def test_deeply_nested_path_under_workspace(self):
        """~/dev/my-project/src/lib/core -> 'my-project'"""
        bridge = self._make_bridge()
        workspace = Path("~/dev").expanduser()
        deep_dir = workspace / "my-project" / "src" / "lib" / "core"
        assert bridge.get_project_id(deep_dir) == "my-project"

    def test_path_outside_workspace(self):
        """/some/other/path -> 'path' (fallback to dir name)"""
        bridge = self._make_bridge()
        outside_dir = Path("/some/other/path")
        assert bridge.get_project_id(outside_dir) == "path"

    def test_different_workspace_root(self):
        """Custom workspace_root should change the derivation base."""
        bridge = self._make_bridge(workspace_root="/opt/projects")
        project_dir = Path("/opt/projects/cool-tool")
        assert bridge.get_project_id(project_dir) == "cool-tool"


class TestLocalBridgeHandoff:
    """Verify handoff lookup behavior.

    Antagonist note: get_handoff() must return None when the project
    directory doesn't exist. This is the common case for first-time use
    or projects that have never had a session.
    """

    def test_get_handoff_returns_none_for_nonexistent_project(self):
        """A project with no session history should return None."""
        bridge = LocalBridge()
        bridge._config = {"workspace_root": "~/dev"}
        result = asyncio.run(bridge.get_handoff("nonexistent-project-xyz-99999"))
        assert result is None


class TestLocalBridgeCreateSession:
    """Verify session creation returns a valid SessionHandle.

    Antagonist note: create_session() is the main entry point. Even in
    placeholder mode (before full foundation integration), it must return
    a properly structured SessionHandle with correct project derivation.

    These tests mock amplifier-foundation since it's not installed in the
    test environment. The mock chain: _require_foundation -> load_bundle
    -> bundle.prepare() -> prepared.create_session() -> session object.
    """

    @staticmethod
    def _make_bridge_and_config():
        """Create a configured bridge and config for testing."""
        bridge = LocalBridge()
        bridge._config = {
            "workspace_root": "~/dev",
            "preflight": {"enabled": False},
            "bundle": {"active": "test-bundle"},
        }
        config = BridgeConfig(
            working_dir=Path("~/dev/test-project").expanduser(),
            run_preflight=False,
        )
        return bridge, config

    @staticmethod
    def _mock_foundation():
        """Create mocks for the amplifier-foundation chain."""
        from unittest.mock import AsyncMock, MagicMock

        mock_session = MagicMock()
        mock_session.coordinator.session_id = "test-session-id-12345678"

        mock_prepared = AsyncMock()
        mock_prepared.create_session = AsyncMock(return_value=mock_session)

        mock_bundle = AsyncMock()
        mock_bundle.prepare = AsyncMock(return_value=mock_prepared)

        mock_load_bundle = AsyncMock(return_value=mock_bundle)
        mock_registry_cls = MagicMock()

        return mock_load_bundle, mock_registry_cls

    def test_create_session_returns_session_handle(self):
        from unittest.mock import patch

        bridge, config = self._make_bridge_and_config()
        mock_load, mock_reg = self._mock_foundation()
        with patch(
            "amplifier_distro.bridge._require_foundation",
            return_value=(mock_load, mock_reg),
        ):
            handle = asyncio.run(bridge.create_session(config))
        assert isinstance(handle, SessionHandle)

    def test_create_session_derives_project_id(self):
        from unittest.mock import patch

        bridge, config = self._make_bridge_and_config()
        mock_load, mock_reg = self._mock_foundation()
        with patch(
            "amplifier_distro.bridge._require_foundation",
            return_value=(mock_load, mock_reg),
        ):
            handle = asyncio.run(bridge.create_session(config))
        assert handle.project_id == "test-project"

    def test_create_session_preserves_working_dir(self):
        from unittest.mock import patch

        bridge, config = self._make_bridge_and_config()
        working = config.working_dir
        mock_load, mock_reg = self._mock_foundation()
        with patch(
            "amplifier_distro.bridge._require_foundation",
            return_value=(mock_load, mock_reg),
        ):
            handle = asyncio.run(bridge.create_session(config))
        assert handle.working_dir == working

    def test_create_session_generates_nonempty_session_id(self):
        from unittest.mock import patch

        bridge, config = self._make_bridge_and_config()
        mock_load, mock_reg = self._mock_foundation()
        with patch(
            "amplifier_distro.bridge._require_foundation",
            return_value=(mock_load, mock_reg),
        ):
            handle = asyncio.run(bridge.create_session(config))
        assert handle.session_id  # non-empty string
        assert isinstance(handle.session_id, str)
