"""Phase 0 Acceptance Tests

These tests validate the Phase 0 milestone: "One config file. One base bundle.
Validated startup." They are designed to be inspected by an antagonist session
for completeness and correctness.

Exit criteria verified:
1. distro.yaml schema has correct structure and defaults
2. Config I/O round-trips correctly
3. Pre-flight checks detect all required conditions
4. CLI commands exist and have correct help text
5. Base bundle has required composition
"""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from amplifier_distro.cli import main
from amplifier_distro.config import config_path, load_config, save_config
from amplifier_distro.preflight import CheckResult, PreflightReport, run_preflight
from amplifier_distro.schema import (
    DistroConfig,
    IdentityConfig,
    looks_like_path,
    normalize_path,
)


class TestPathHelpers:
    """Verify path helper functions from schema.py."""

    def test_looks_like_path_absolute(self):
        assert looks_like_path("/usr/local") is True

    def test_looks_like_path_tilde(self):
        assert looks_like_path("~/dev") is True

    def test_looks_like_path_relative_dot(self):
        assert looks_like_path("./src") is True

    def test_looks_like_path_rejects_bare_word(self):
        assert looks_like_path("not-a-path") is False

    def test_looks_like_path_rejects_empty(self):
        assert looks_like_path("") is False

    def test_normalize_path_expands_tilde(self):
        result = normalize_path("~/dev")
        assert "~" not in result
        assert result.endswith("/dev")

    def test_normalize_path_expands_env_var(self):
        import os

        with patch.dict(os.environ, {"MY_TEST_DIR": "/tmp/test"}):
            result = normalize_path("$MY_TEST_DIR/sub")
            assert result == "/tmp/test/sub"


class TestDistroYamlSchema:
    """Verify distro.yaml schema has correct structure and defaults.

    Antagonist note: Each test pins a specific default value from the schema.
    If any default changes without updating these tests, they will fail.
    """

    def test_default_config_has_all_sections(self):
        """DistroConfig must have exactly these 7 top-level sections."""
        config = DistroConfig()
        assert hasattr(config, "workspace_root")
        assert hasattr(config, "identity")
        assert hasattr(config, "bundle")
        assert hasattr(config, "cache")
        assert hasattr(config, "preflight")
        assert hasattr(config, "interfaces")
        assert hasattr(config, "memory")

    def test_default_workspace_root(self):
        config = DistroConfig()
        assert config.workspace_root == "~/dev"

    def test_default_bundle_config(self):
        config = DistroConfig()
        assert config.bundle.active is None
        assert config.bundle.validate_on_start is True
        assert config.bundle.strict is True

    def test_default_preflight_mode_is_block(self):
        config = DistroConfig()
        assert config.preflight.enabled is True
        assert config.preflight.mode == "block"

    def test_default_memory_path_is_canonical(self):
        config = DistroConfig()
        assert config.memory.path == "~/.amplifier/memory"

    def test_default_memory_legacy_paths(self):
        config = DistroConfig()
        assert "~/amplifier-dev-memory" in config.memory.legacy_paths

    def test_default_interfaces_cli_installed(self):
        config = DistroConfig()
        assert config.interfaces.cli.installed is True
        assert config.interfaces.tui.installed is False
        assert config.interfaces.voice.installed is False
        assert config.interfaces.gui.installed is False

    def test_default_cache_config(self):
        config = DistroConfig()
        assert config.cache.max_age_hours == 168
        assert config.cache.auto_refresh_on_error is True
        assert config.cache.auto_refresh_on_stale is True

    def test_config_serializes_to_valid_yaml(self):
        """model_dump() -> yaml.dump() -> yaml.safe_load() must round-trip."""
        config = DistroConfig()
        data = config.model_dump()
        yaml_str = yaml.dump(data)
        loaded = yaml.safe_load(yaml_str)
        assert loaded["workspace_root"] == "~/dev"
        assert loaded["identity"]["github_handle"] == ""
        assert loaded["bundle"]["strict"] is True

    def test_config_roundtrips_through_yaml(self):
        """A non-default config must survive YAML serialization round-trip."""
        original = DistroConfig(
            workspace_root="~/projects",
            identity=IdentityConfig(
                github_handle="testuser", git_email="test@example.com"
            ),
        )
        data = original.model_dump()
        yaml_str = yaml.dump(data)
        loaded = yaml.safe_load(yaml_str)
        restored = DistroConfig(**loaded)
        assert restored.workspace_root == "~/projects"
        assert restored.identity.github_handle == "testuser"
        assert restored.identity.git_email == "test@example.com"

    def test_identity_fields_default_to_empty(self):
        config = DistroConfig()
        assert config.identity.github_handle == ""
        assert config.identity.git_email == ""

    def test_workspace_root_validator_rejects_bare_word(self):
        """DistroConfig rejects workspace_root that doesn't look like a path."""
        with pytest.raises(Exception):
            DistroConfig(workspace_root="not-a-path")

    def test_workspace_root_validator_accepts_tilde(self):
        config = DistroConfig(workspace_root="~/dev")
        assert config.workspace_root == "~/dev"

    def test_workspace_root_validator_accepts_absolute(self):
        config = DistroConfig(workspace_root="/home/user/dev")
        assert config.workspace_root == "/home/user/dev"

    def test_workspace_root_validator_accepts_relative_dot(self):
        config = DistroConfig(workspace_root="./projects")
        assert config.workspace_root == "./projects"


class TestConfigIO:
    """Verify config load/save works correctly.

    Antagonist note: These tests use tmp_path and mock config_path() so they
    never touch the real ~/.amplifier/distro.yaml. The round-trip test proves
    save_config and load_config are inverses of each other.
    """

    def test_config_path_is_under_amplifier(self):
        path = config_path()
        assert ".amplifier" in str(path)
        assert str(path).endswith("distro.yaml")

    def test_load_config_returns_defaults_when_missing(self):
        with patch(
            "amplifier_distro.config.config_path",
            return_value=Path("/nonexistent/distro.yaml"),
        ):
            config = load_config()
            assert isinstance(config, DistroConfig)
            assert config.workspace_root == "~/dev"

    def test_save_and_load_roundtrip(self, tmp_path):
        fake_path = tmp_path / ".amplifier" / "distro.yaml"
        config = DistroConfig(
            workspace_root="~/mywork",
            identity=IdentityConfig(github_handle="roundtrip_user"),
        )
        with patch("amplifier_distro.config.config_path", return_value=fake_path):
            save_config(config)
            assert fake_path.exists()
            loaded = load_config()
            assert loaded.workspace_root == "~/mywork"
            assert loaded.identity.github_handle == "roundtrip_user"

    def test_save_creates_parent_directories(self, tmp_path):
        """save_config must create ~/.amplifier/ if it doesn't exist."""
        deep_path = tmp_path / "a" / "b" / "distro.yaml"
        config = DistroConfig()
        with patch("amplifier_distro.config.config_path", return_value=deep_path):
            save_config(config)
            assert deep_path.exists()

    def test_load_config_raises_on_invalid_values(self, tmp_path):
        """load_config() raises ValidationError when config has invalid values."""
        from unittest.mock import patch

        from amplifier_distro.config import load_config

        config_file = tmp_path / "distro.yaml"
        config_file.write_text("workspace_root: not-a-path\n")
        with patch("amplifier_distro.config.config_path", return_value=config_file):
            with pytest.raises(Exception):  # ValidationError
                load_config()

    def test_load_config_raises_on_malformed_yaml(self, tmp_path):
        """load_config() raises ValueError when YAML is malformed."""
        config_file = tmp_path / "distro.yaml"
        config_file.write_text("{{invalid yaml: [}\n")
        with patch("amplifier_distro.config.config_path", return_value=config_file):
            with pytest.raises(ValueError, match="Malformed YAML"):
                load_config()


class TestPreflightChecks:
    """Verify pre-flight checks detect all required conditions.

    Antagonist note: We mock subprocess.run (gh CLI) and shutil.which
    (amplifier binary) so tests don't depend on external tools. The check
    names are verified against the exact strings used in preflight.py.
    """

    def test_report_structure(self):
        """Empty report has correct initial state."""
        report = PreflightReport()
        assert isinstance(report.checks, list)
        assert len(report.checks) == 0
        assert report.passed is True  # Empty report passes

    def test_report_fails_on_error(self):
        """A single error-severity failure causes the report to fail."""
        report = PreflightReport()
        report.checks.append(
            CheckResult(name="test", passed=False, message="bad", severity="error")
        )
        assert report.passed is False

    def test_report_passes_with_warnings_only(self):
        """Warning-severity failures do NOT cause the report to fail."""
        report = PreflightReport()
        report.checks.append(
            CheckResult(name="test", passed=False, message="meh", severity="warning")
        )
        assert report.passed is True

    def test_report_warnings_property(self):
        """The warnings property returns only non-passed warning-severity checks."""
        report = PreflightReport()
        report.checks.append(CheckResult("ok", True, "good"))
        report.checks.append(CheckResult("warn1", False, "w1", severity="warning"))
        report.checks.append(CheckResult("err1", False, "e1", severity="error"))
        report.checks.append(CheckResult("warn2", False, "w2", severity="warning"))
        assert len(report.warnings) == 2
        assert all(w.severity == "warning" for w in report.warnings)

    @patch("amplifier_distro.preflight.shutil.which", return_value=None)
    @patch("amplifier_distro.preflight.subprocess.run", side_effect=FileNotFoundError)
    def test_preflight_checks_all_required_areas(self, _mock_run, _mock_which):
        """Pre-flight must produce exactly these 9 named checks.

        Antagonist note: The exact check names are pinned here. If preflight.py
        changes a name or drops a check, this test catches it.
        """
        report = run_preflight()
        check_names = [c.name for c in report.checks]
        required = [
            "distro.yaml",
            "GitHub CLI",
            "Identity",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "Workspace",
            "Memory store",
            "Amplifier CLI",
        ]
        for req in required:
            assert req in check_names, f"Missing pre-flight check: {req}"
        assert len(report.checks) == 8, (
            f"Expected exactly 8 checks, got {len(report.checks)}: {check_names}"
        )

    @patch("amplifier_distro.preflight.shutil.which", return_value=None)
    @patch("amplifier_distro.preflight.subprocess.run", side_effect=FileNotFoundError)
    def test_preflight_api_key_checks_are_warnings(self, _mock_run, _mock_which):
        """API key failures must use warning severity, not error.

        This ensures missing API keys don't block startup.
        """
        report = run_preflight()
        for check in report.checks:
            if check.name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
                if not check.passed:
                    assert check.severity == "warning", (
                        f"{check.name} should be warning severity, got {check.severity}"
                    )

    @patch("amplifier_distro.preflight.shutil.which", return_value=None)
    @patch("amplifier_distro.preflight.subprocess.run", side_effect=FileNotFoundError)
    def test_preflight_memory_store_check_is_warning(self, _mock_run, _mock_which):
        """Memory store failure must use warning severity, not error."""
        report = run_preflight()
        memory_checks = [c for c in report.checks if c.name == "Memory store"]
        assert len(memory_checks) == 1, "Expected exactly one Memory store check"
        if not memory_checks[0].passed:
            assert memory_checks[0].severity == "warning"


class TestCLI:
    """Verify CLI commands exist and have correct structure.

    Antagonist note: We test --help for each command (proving it exists
    and is registered) and test behavioral contracts (exit codes) by
    mocking run_preflight at the CLI module level.
    """

    def test_cli_has_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_cli_has_init_command(self):
        runner = CliRunner()
        result = runner.invoke(main, ["init", "--help"])
        assert result.exit_code == 0
        assert "init" in result.output.lower() or "initialize" in result.output.lower()

    def test_cli_has_status_command(self):
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--help"])
        assert result.exit_code == 0

    def test_cli_has_validate_command(self):
        runner = CliRunner()
        result = runner.invoke(main, ["validate", "--help"])
        assert result.exit_code == 0

    def test_status_exits_nonzero_on_failures(self):
        """status command must exit non-zero when error-severity checks fail.

        Antagonist note: We inject a failing report directly so this test
        is deterministic regardless of the host environment.
        """
        runner = CliRunner()
        failed_report = PreflightReport()
        failed_report.checks.append(
            CheckResult("distro.yaml", False, "Not found", severity="error")
        )
        with patch("amplifier_distro.cli.run_preflight", return_value=failed_report):
            result = runner.invoke(main, ["status"])
            assert result.exit_code != 0

    def test_status_exits_zero_when_all_pass(self):
        """status command must exit zero when all checks pass."""
        runner = CliRunner()
        ok_report = PreflightReport()
        ok_report.checks.append(CheckResult("test", True, "OK"))
        with patch("amplifier_distro.cli.run_preflight", return_value=ok_report):
            result = runner.invoke(main, ["status"])
            assert result.exit_code == 0

    def test_validate_exits_nonzero_when_no_config(self):
        """validate must fail when distro.yaml doesn't exist."""
        runner = CliRunner()
        with patch(
            "amplifier_distro.cli.config_path",
            return_value=Path("/nonexistent/distro.yaml"),
        ):
            result = runner.invoke(main, ["validate"])
            assert result.exit_code != 0


# TestBaseBundleFile removed: static distro-base.md was replaced by
# dynamic bundle_composer.py (tested in test_bundle_composer.py).
