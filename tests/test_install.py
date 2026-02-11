"""Tests for TASK-13: amp-distro install <interface> CLI command.

Covers:
- install command registration and help
- interfaces command listing
- Invalid interface name rejection
- Package install flow (mocked subprocess)
- Source install flow (mocked subprocess)
- Config update after install
- Smoke test behavior
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from amplifier_distro.cli import (
    INTERFACE_REGISTRY,
    _smoke_test,
    _update_config,
    main,
)
from amplifier_distro.schema import DistroConfig


class TestInstallCommandRegistration:
    """install command is registered and accessible."""

    def test_install_in_help(self):
        """install command appears in top-level help."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "install" in result.output

    def test_install_help_text(self):
        """install --help shows argument and options."""
        runner = CliRunner()
        result = runner.invoke(main, ["install", "--help"])
        assert result.exit_code == 0
        assert "tui" in result.output
        assert "voice" in result.output
        assert "gui" in result.output
        assert "--from-source" in result.output

    def test_interfaces_in_help(self):
        """interfaces command appears in top-level help."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "interfaces" in result.output

    def test_epilog_contains_install(self):
        """EPILOG includes install and interfaces entries."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "amp-distro install" in result.output
        assert "amp-distro interfaces" in result.output


class TestInstallInvalidInterface:
    """install rejects unknown interface names."""

    def test_invalid_interface_name(self):
        """Passing an unknown interface name fails gracefully."""
        runner = CliRunner()
        result = runner.invoke(main, ["install", "banana"])
        assert result.exit_code != 0
        assert "Invalid value" in result.output or "banana" in result.output

    def test_no_interface_argument(self):
        """Omitting the interface argument shows an error."""
        runner = CliRunner()
        result = runner.invoke(main, ["install"])
        assert result.exit_code != 0


class TestInterfacesCommand:
    """interfaces command lists available interfaces."""

    @patch("amplifier_distro.cli.load_config")
    def test_interfaces_shows_all(self, mock_load):
        """Lists all interfaces (cli, tui, voice, gui)."""
        mock_load.return_value = DistroConfig()
        runner = CliRunner()
        result = runner.invoke(main, ["interfaces"])
        assert result.exit_code == 0
        assert "cli" in result.output
        assert "tui" in result.output
        assert "voice" in result.output
        assert "gui" in result.output

    @patch("amplifier_distro.cli.load_config")
    def test_interfaces_shows_descriptions(self, mock_load):
        """Shows descriptions from INTERFACE_REGISTRY."""
        mock_load.return_value = DistroConfig()
        runner = CliRunner()
        result = runner.invoke(main, ["interfaces"])
        assert result.exit_code == 0
        assert "Terminal UI" in result.output
        assert "Voice interface" in result.output
        assert "Web-based GUI" in result.output

    @patch("amplifier_distro.cli.load_config")
    def test_interfaces_shows_install_hint(self, mock_load):
        """Shows how to install."""
        mock_load.return_value = DistroConfig()
        runner = CliRunner()
        result = runner.invoke(main, ["interfaces"])
        assert result.exit_code == 0
        assert "amp-distro install <name>" in result.output

    @patch("amplifier_distro.cli.load_config")
    def test_interfaces_shows_source_path(self, mock_load):
        """Shows source path for source-installed interfaces."""
        config = DistroConfig()
        config.interfaces.tui.installed = True
        config.interfaces.tui.path = "/home/dev/amplifier-tui"
        mock_load.return_value = config
        runner = CliRunner()
        result = runner.invoke(main, ["interfaces"])
        assert result.exit_code == 0
        assert "/home/dev/amplifier-tui" in result.output


class TestInstallPackageMode:
    """install in default (package) mode."""

    @patch("amplifier_distro.cli._smoke_test")
    @patch("amplifier_distro.cli._update_config")
    @patch("subprocess.run")
    def test_uv_success(self, mock_run, mock_cfg, mock_smoke):
        """Successful uv tool install path."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        runner = CliRunner()
        result = runner.invoke(main, ["install", "tui"])
        assert result.exit_code == 0
        assert "Installed via uv" in result.output
        mock_cfg.assert_called_once_with("tui")
        mock_smoke.assert_called_once_with("amplifier-tui")

    @patch("amplifier_distro.cli._smoke_test")
    @patch("amplifier_distro.cli._update_config")
    @patch("subprocess.run")
    def test_uv_fails_pip_succeeds(self, mock_run, mock_cfg, mock_smoke):
        """Falls back to pip when uv fails."""
        uv_fail = MagicMock(returncode=1, stdout="", stderr="uv error")
        pip_ok = MagicMock(returncode=0, stdout="", stderr="")
        mock_run.side_effect = [uv_fail, pip_ok]

        runner = CliRunner()
        result = runner.invoke(main, ["install", "tui"])
        assert result.exit_code == 0
        assert "Installed via pip" in result.output

    @patch("amplifier_distro.cli._smoke_test")
    @patch("amplifier_distro.cli._update_config")
    @patch("subprocess.run")
    def test_uv_not_found_pip_succeeds(self, mock_run, mock_cfg, mock_smoke):
        """Falls back to pip when uv binary is not found."""

        def side_effect(cmd, **kwargs):
            if cmd[0] == "uv":
                raise FileNotFoundError("uv not found")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        runner = CliRunner()
        result = runner.invoke(main, ["install", "voice"])
        assert result.exit_code == 0
        assert "Installed via pip" in result.output

    @patch("subprocess.run")
    def test_both_fail(self, mock_run):
        """Exit 1 when both uv and pip fail."""
        uv_fail = MagicMock(returncode=1, stdout="", stderr="uv error")
        pip_fail = MagicMock(returncode=1, stdout="", stderr="pip error")
        mock_run.side_effect = [uv_fail, pip_fail]

        runner = CliRunner()
        result = runner.invoke(main, ["install", "tui"])
        assert result.exit_code != 0


class TestInstallSourceMode:
    """install --from-source mode."""

    @patch("amplifier_distro.cli._smoke_test")
    @patch("amplifier_distro.cli._update_config")
    @patch("subprocess.run")
    @patch("amplifier_distro.cli.load_config")
    def test_clone_and_install(self, mock_load, mock_run, mock_cfg, mock_smoke):
        """Clones repo and installs editable when dir doesn't exist."""
        config = DistroConfig(workspace_root="/tmp/test-ws")
        mock_load.return_value = config

        # git clone OK, uv pip install -e OK
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = CliRunner()
        with patch.object(Path, "exists", return_value=False):
            result = runner.invoke(main, ["install", "tui", "--from-source"])

        assert result.exit_code == 0
        assert "Cloning" in result.output
        assert "from source" in result.output

    @patch("amplifier_distro.cli._smoke_test")
    @patch("amplifier_distro.cli._update_config")
    @patch("subprocess.run")
    @patch("amplifier_distro.cli.load_config")
    def test_skip_clone_if_exists(self, mock_load, mock_run, mock_cfg, mock_smoke):
        """Skips clone when directory already exists."""
        config = DistroConfig(workspace_root="/tmp/test-ws")
        mock_load.return_value = config

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = CliRunner()
        with patch.object(Path, "exists", return_value=True):
            result = runner.invoke(main, ["install", "tui", "--from-source"])

        assert result.exit_code == 0
        assert "skipping clone" in result.output

    @patch("subprocess.run")
    @patch("amplifier_distro.cli.load_config")
    def test_clone_failure(self, mock_load, mock_run):
        """Exit 1 when git clone fails."""
        config = DistroConfig(workspace_root="/tmp/test-ws")
        mock_load.return_value = config
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="clone error")

        runner = CliRunner()
        with patch.object(Path, "exists", return_value=False):
            result = runner.invoke(main, ["install", "gui", "--from-source"])

        assert result.exit_code != 0


class TestUpdateConfig:
    """_update_config marks interfaces installed in distro.yaml."""

    @patch("amplifier_distro.cli.save_config")
    @patch("amplifier_distro.cli.load_config")
    def test_marks_installed(self, mock_load, mock_save):
        """Sets installed=True on the interface entry."""
        config = DistroConfig()
        mock_load.return_value = config

        _update_config("tui")

        assert config.interfaces.tui.installed is True
        mock_save.assert_called_once_with(config)

    @patch("amplifier_distro.cli.save_config")
    @patch("amplifier_distro.cli.load_config")
    def test_sets_path_for_source(self, mock_load, mock_save):
        """Sets path when installing from source."""
        config = DistroConfig()
        mock_load.return_value = config

        _update_config("voice", path="/home/dev/amplifier-voice-bridge")

        assert config.interfaces.voice.installed is True
        assert config.interfaces.voice.path == "/home/dev/amplifier-voice-bridge"


class TestSmokeTest:
    """_smoke_test import check."""

    def test_importable_package(self):
        """Does not raise for packages that can be imported."""
        runner = CliRunner()
        # 'json' is in stdlib, always importable
        with runner.isolated_filesystem():
            _smoke_test("json")  # should not raise

    def test_non_importable_package(self):
        """Handles missing packages gracefully (no exception)."""
        _smoke_test("nonexistent-fake-package")  # should not raise


class TestInterfaceRegistry:
    """INTERFACE_REGISTRY is well-formed."""

    def test_required_keys(self):
        """Each entry has repo, package, description."""
        for name, info in INTERFACE_REGISTRY.items():
            assert "repo" in info, f"{name} missing 'repo'"
            assert "package" in info, f"{name} missing 'package'"
            assert "description" in info, f"{name} missing 'description'"

    def test_expected_interfaces(self):
        """Registry contains tui, voice, gui."""
        assert "tui" in INTERFACE_REGISTRY
        assert "voice" in INTERFACE_REGISTRY
        assert "gui" in INTERFACE_REGISTRY

    def test_cli_not_in_registry(self):
        """CLI is not installable (always present)."""
        assert "cli" not in INTERFACE_REGISTRY
