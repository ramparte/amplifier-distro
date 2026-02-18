"""Tests for T9: CLI Enhancements.

Covers:
- Version command output (T9.1)
- PackageStatus and VersionInfo models (T9.2)
- Update command with mocked subprocess (T9.4)
- Status command update notice (T9.3)
- Improved help text (T9.5)
"""

import platform
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from amplifier_distro.cli import main
from amplifier_distro.update_check import (
    PackageStatus,
    VersionInfo,
    get_version_info,
    run_self_update,
)


class TestVersionCommand:
    """T9.1: Test the 'amp-distro version' command."""

    def test_version_command_exists(self):
        """version command is registered and shows help."""
        runner = CliRunner()
        result = runner.invoke(main, ["version", "--help"])
        assert result.exit_code == 0
        assert "version" in result.output.lower()

    def test_version_output_contains_python_version(self):
        """Output includes Python version string."""
        runner = CliRunner()
        result = runner.invoke(main, ["version"])
        assert result.exit_code == 0
        assert platform.python_version() in result.output

    def test_version_output_contains_platform(self):
        """Output includes platform information."""
        runner = CliRunner()
        result = runner.invoke(main, ["version"])
        assert result.exit_code == 0
        assert platform.system() in result.output

    def test_version_output_contains_install_method(self):
        """Output includes the detected install method."""
        runner = CliRunner()
        result = runner.invoke(main, ["version"])
        assert result.exit_code == 0
        assert "Install method:" in result.output

    def test_version_output_contains_distro_version(self):
        """Output includes the amplifier-distro version."""
        runner = CliRunner()
        result = runner.invoke(main, ["version"])
        assert result.exit_code == 0
        assert "amplifier-distro:" in result.output


class TestVersionInfo:
    """T9.2: Test the VersionInfo model and get_version_info()."""

    def test_version_info_fields(self):
        info = VersionInfo(
            python_version="3.11.0",
            platform="Linux 6.1 (x86_64)",
            install_method="uv",
        )
        assert info.python_version == "3.11.0"
        assert info.install_method == "uv"
        assert info.distro is None
        assert info.amplifier is None
        assert info.tui is None

    def test_get_version_info_returns_real_data(self):
        info = get_version_info()
        assert isinstance(info, VersionInfo)
        assert info.python_version == platform.python_version()
        assert platform.system() in info.platform
        assert info.install_method.split()[0] in ("uv", "pip", "pipx")


class TestUpdateCommand:
    """T9.4: Test the 'amp-distro update' command."""

    def test_update_command_exists(self):
        """update command is registered."""
        runner = CliRunner()
        result = runner.invoke(main, ["update", "--help"])
        assert result.exit_code == 0
        assert "update" in result.output.lower()

    def test_update_when_already_latest(self):
        """Shows 'already at latest' when no update available."""
        runner = CliRunner()
        with patch(
            "amplifier_distro.cli.run_self_update",
            return_value=(True, "Already at latest version (0.1.0)."),
        ):
            result = runner.invoke(main, ["update"])
            assert result.exit_code == 0
            assert "latest version" in result.output.lower()

    def test_run_self_update_success(self):
        """run_self_update succeeds with mocked subprocess (non-editable)."""
        mock_upgrade = MagicMock(returncode=0, stdout="", stderr="")
        mock_verify = MagicMock(
            returncode=0, stdout="amp-distro, version 0.2.0", stderr=""
        )

        with (
            patch(
                "amplifier_distro.update_check._is_editable_install",
                return_value=False,
            ),
            patch(
                "amplifier_distro.update_check._get_distro_version",
                return_value="0.1.0",
            ),
            patch(
                "amplifier_distro.update_check.subprocess.run",
                side_effect=[mock_upgrade, mock_verify],
            ),
        ):
            success, message = run_self_update()
            assert success is True
            assert "0.2.0" in message

    def test_run_self_update_editable(self):
        """run_self_update returns message for editable installs."""
        with patch(
            "amplifier_distro.update_check._is_editable_install",
            return_value=True,
        ):
            success, message = run_self_update()
            assert success is True
            assert "editable" in message.lower()
            assert "git pull" in message

    def test_run_self_update_failure(self):
        """run_self_update reports failure on non-zero exit."""
        mock_result = MagicMock(returncode=1, stdout="", stderr="permission denied")

        with (
            patch(
                "amplifier_distro.update_check._is_editable_install",
                return_value=False,
            ),
            patch(
                "amplifier_distro.update_check._get_distro_version",
                return_value="0.1.0",
            ),
            patch(
                "amplifier_distro.update_check.subprocess.run", return_value=mock_result
            ),
        ):
            success, message = run_self_update()
            assert success is False
            assert "failed" in message.lower()


class TestStatusUpdateNotice:
    """T9.3: Test that status command shows update notices via SHA comparison."""

    def test_status_shows_update_notice(self):
        """When local SHA != remote SHA, status shows the notice."""
        from amplifier_distro.preflight import CheckResult, PreflightReport

        runner = CliRunner()
        ok_report = PreflightReport()
        ok_report.checks.append(CheckResult("test", True, "OK"))

        status_with_update = PackageStatus(
            version="0.1.0",
            local_sha="abc1234",
            remote_sha="def5678",
        )

        with (
            patch("amplifier_distro.cli.run_preflight", return_value=ok_report),
            patch("amplifier_distro.cli._is_editable_install", return_value=False),
            patch(
                "amplifier_distro.cli._get_package_status",
                return_value=status_with_update,
            ),
            patch(
                "amplifier_distro.cli._get_distro_version",
                return_value="0.1.0",
            ),
        ):
            result = runner.invoke(main, ["status"])
            assert result.exit_code == 0
            assert "Update available" in result.output
            assert "abc1234" in result.output
            assert "def5678" in result.output
            assert "amp-distro update" in result.output

    def test_status_no_notice_when_up_to_date(self):
        """When local SHA == remote SHA, status does NOT show an update notice."""
        from amplifier_distro.preflight import CheckResult, PreflightReport

        runner = CliRunner()
        ok_report = PreflightReport()
        ok_report.checks.append(CheckResult("test", True, "OK"))

        status_up_to_date = PackageStatus(
            version="0.1.0",
            local_sha="abc1234",
            remote_sha="abc1234",
        )

        with (
            patch("amplifier_distro.cli.run_preflight", return_value=ok_report),
            patch(
                "amplifier_distro.cli._get_package_status",
                return_value=status_up_to_date,
            ),
            patch(
                "amplifier_distro.cli._get_distro_version",
                return_value="0.1.0",
            ),
        ):
            result = runner.invoke(main, ["status"])
            assert result.exit_code == 0
            assert "Update available" not in result.output


class TestImprovedHelp:
    """T9.5: Test improved help text."""

    def test_main_help_has_epilog(self):
        """Main help includes quick-start examples."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Quick-start examples" in result.output
        assert "amp-distro init" in result.output
        assert "amp-distro status" in result.output
        assert "amp-distro doctor" in result.output

    def test_main_help_lists_all_commands(self):
        """Main help lists version and update commands."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "version" in result.output
        assert "update" in result.output

    def test_version_help_has_description(self):
        """version command has a rich help description."""
        runner = CliRunner()
        result = runner.invoke(main, ["version", "--help"])
        assert result.exit_code == 0
        # Should have meaningful help, not just "version"
        assert "version" in result.output.lower()
        assert (
            "platform" in result.output.lower()
            or "environment" in result.output.lower()
        )

    def test_status_help_has_description(self):
        """status command has a rich help description."""
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--help"])
        assert result.exit_code == 0
        assert "health" in result.output.lower() or "update" in result.output.lower()
