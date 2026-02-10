"""Tests for T9: CLI Enhancements.

Covers:
- Version command output (T9.1)
- Update check logic with mocked HTTP (T9.2)
- Update check caching / TTL (T9.2)
- UpdateInfo and VersionInfo models (T9.2)
- Update command with mocked subprocess (T9.4)
- Status command update notice (T9.3)
- Improved help text (T9.5)
"""

import platform
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from amplifier_distro import conventions
from amplifier_distro.cli import main
from amplifier_distro.update_check import (
    UpdateInfo,
    VersionInfo,
    _cache_path,
    _parse_version,
    _read_cache,
    _write_cache,
    check_for_updates,
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


class TestUpdateInfoModel:
    """T9.2: Test the UpdateInfo Pydantic model."""

    def test_update_info_fields(self):
        info = UpdateInfo(
            current_version="0.1.0",
            latest_version="0.2.0",
            release_url="https://pypi.org/project/amplifier-distro/0.2.0/",
            release_notes_url="https://github.com/microsoft/amplifier-distro/releases/tag/v0.2.0",
        )
        assert info.current_version == "0.1.0"
        assert info.latest_version == "0.2.0"
        assert "pypi.org" in info.release_url
        assert "github.com" in info.release_notes_url

    def test_update_info_serializes(self):
        info = UpdateInfo(
            current_version="1.0.0",
            latest_version="1.1.0",
            release_url="https://example.com",
            release_notes_url="https://example.com/notes",
        )
        data = info.model_dump()
        assert data["current_version"] == "1.0.0"
        restored = UpdateInfo(**data)
        assert restored == info


class TestVersionInfo:
    """T9.2: Test the VersionInfo model and get_version_info()."""

    def test_version_info_fields(self):
        info = VersionInfo(
            distro_version="0.1.0",
            amplifier_version=None,
            python_version="3.11.0",
            platform="Linux 6.1 (x86_64)",
            install_method="uv",
        )
        assert info.distro_version == "0.1.0"
        assert info.amplifier_version is None
        assert info.install_method == "uv"

    def test_get_version_info_returns_real_data(self):
        info = get_version_info()
        assert isinstance(info, VersionInfo)
        assert info.python_version == platform.python_version()
        assert platform.system() in info.platform
        assert info.install_method in ("uv", "pip", "pipx")


class TestParseVersion:
    """T9.2: Test version string parsing."""

    def test_simple_version(self):
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_version_with_v_prefix(self):
        assert _parse_version("v1.2.3") == (1, 2, 3)

    def test_version_comparison(self):
        assert _parse_version("0.2.0") > _parse_version("0.1.0")
        assert _parse_version("1.0.0") > _parse_version("0.9.9")
        assert _parse_version("0.1.0") == _parse_version("0.1.0")

    def test_invalid_version(self):
        assert _parse_version("invalid") == (0, 0, 0)
        assert _parse_version("") == (0, 0, 0)


class TestUpdateCheckCaching:
    """T9.2: Test that update checks are cached and respect TTL."""

    def test_cache_path_uses_conventions(self):
        """Cache path must use conventions.py constants."""
        path = _cache_path()
        assert conventions.CACHE_DIR in str(path)
        assert conventions.UPDATE_CHECK_CACHE_FILENAME in str(path)

    def test_write_and_read_cache(self, tmp_path):
        """Cache round-trips correctly."""
        cache_file = tmp_path / "update-check.json"
        with patch(
            "amplifier_distro.update_check._cache_path", return_value=cache_file
        ):
            data = {"checked_at": time.time(), "update_available": False}
            _write_cache(data)
            assert cache_file.exists()

            result = _read_cache()
            assert result is not None
            assert result["update_available"] is False

    def test_expired_cache_returns_none(self, tmp_path):
        """Cache older than TTL is treated as missing."""
        cache_file = tmp_path / "update-check.json"
        with patch(
            "amplifier_distro.update_check._cache_path", return_value=cache_file
        ):
            old_time = time.time() - (conventions.UPDATE_CHECK_TTL_HOURS + 1) * 3600
            data = {"checked_at": old_time, "update_available": False}
            _write_cache(data)

            result = _read_cache()
            assert result is None  # Expired, should not be returned

    def test_check_for_updates_uses_cache(self, tmp_path):
        """check_for_updates returns None when cache says up-to-date."""
        cache_file = tmp_path / "update-check.json"
        with patch(
            "amplifier_distro.update_check._cache_path", return_value=cache_file
        ):
            # Write a fresh "up to date" cache entry
            data = {"checked_at": time.time(), "update_available": False}
            _write_cache(data)

            # Should return None without making any HTTP calls
            result = check_for_updates()
            assert result is None

    def test_check_for_updates_returns_cached_update(self, tmp_path):
        """check_for_updates returns UpdateInfo from cache if update available."""
        cache_file = tmp_path / "update-check.json"
        info = UpdateInfo(
            current_version="0.1.0",
            latest_version="0.2.0",
            release_url="https://example.com",
            release_notes_url="https://example.com/notes",
        )
        with patch(
            "amplifier_distro.update_check._cache_path", return_value=cache_file
        ):
            data = {
                "checked_at": time.time(),
                "update_available": True,
                "update_info": info.model_dump(),
            }
            _write_cache(data)

            result = check_for_updates()
            assert result is not None
            assert result.latest_version == "0.2.0"


class TestCheckForUpdates:
    """T9.2: Test the update check with mocked HTTP calls."""

    def test_returns_update_info_when_newer_available(self, tmp_path):
        """Returns UpdateInfo when PyPI has a newer version."""
        cache_file = tmp_path / "update-check.json"

        mock_response = MagicMock()
        mock_response.json.return_value = {"info": {"version": "99.0.0"}}
        mock_response.raise_for_status = MagicMock()

        with (
            patch("amplifier_distro.update_check._cache_path", return_value=cache_file),
            patch(
                "amplifier_distro.update_check._get_distro_version",
                return_value="0.1.0",
            ),
            patch("httpx.get", return_value=mock_response),
        ):
            result = check_for_updates()
            assert result is not None
            assert result.current_version == "0.1.0"
            assert result.latest_version == "99.0.0"

    def test_returns_none_when_up_to_date(self, tmp_path):
        """Returns None when installed version matches PyPI."""
        cache_file = tmp_path / "update-check.json"

        mock_response = MagicMock()
        mock_response.json.return_value = {"info": {"version": "0.1.0"}}
        mock_response.raise_for_status = MagicMock()

        with (
            patch("amplifier_distro.update_check._cache_path", return_value=cache_file),
            patch(
                "amplifier_distro.update_check._get_distro_version",
                return_value="0.1.0",
            ),
            patch("httpx.get", return_value=mock_response),
        ):
            result = check_for_updates()
            assert result is None

    def test_returns_none_on_network_error(self, tmp_path):
        """Returns None silently when network is unavailable."""
        cache_file = tmp_path / "update-check.json"

        with (
            patch("amplifier_distro.update_check._cache_path", return_value=cache_file),
            patch("httpx.get", side_effect=Exception("Network error")),
        ):
            result = check_for_updates()
            assert result is None


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
        with patch("amplifier_distro.cli.check_for_updates", return_value=None):
            result = runner.invoke(main, ["update"])
            assert result.exit_code == 0
            assert "latest version" in result.output.lower()

    def test_run_self_update_success(self):
        """run_self_update succeeds with mocked subprocess."""
        mock_upgrade = MagicMock(returncode=0, stdout="", stderr="")
        mock_verify = MagicMock(
            returncode=0, stdout="amp-distro, version 0.2.0", stderr=""
        )

        with (
            patch(
                "amplifier_distro.update_check._detect_install_method",
                return_value="pip",
            ),
            patch(
                "amplifier_distro.update_check._get_distro_version",
                return_value="0.1.0",
            ),
            patch(
                "amplifier_distro.update_check.subprocess.run",
                side_effect=[mock_upgrade, mock_verify],
            ),
            patch(
                "amplifier_distro.update_check._cache_path",
                return_value=Path("/tmp/nonexistent-cache.json"),
            ),
        ):
            success, message = run_self_update()
            assert success is True

    def test_run_self_update_failure(self):
        """run_self_update reports failure on non-zero exit."""
        mock_result = MagicMock(returncode=1, stdout="", stderr="permission denied")

        with (
            patch(
                "amplifier_distro.update_check._detect_install_method",
                return_value="pip",
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
    """T9.3: Test that status command shows update notices."""

    def test_status_shows_update_notice(self):
        """When an update is available, status shows the notice."""
        from amplifier_distro.preflight import CheckResult, PreflightReport

        runner = CliRunner()
        ok_report = PreflightReport()
        ok_report.checks.append(CheckResult("test", True, "OK"))

        update_info = UpdateInfo(
            current_version="0.1.0",
            latest_version="0.2.0",
            release_url="https://example.com",
            release_notes_url="https://example.com/notes",
        )

        with (
            patch("amplifier_distro.cli.run_preflight", return_value=ok_report),
            patch("amplifier_distro.cli.check_for_updates", return_value=update_info),
        ):
            result = runner.invoke(main, ["status"])
            assert result.exit_code == 0
            assert "Update available" in result.output
            assert "0.1.0" in result.output
            assert "0.2.0" in result.output
            assert "amp-distro update" in result.output

    def test_status_no_notice_when_up_to_date(self):
        """When up to date, status does NOT show an update notice."""
        from amplifier_distro.preflight import CheckResult, PreflightReport

        runner = CliRunner()
        ok_report = PreflightReport()
        ok_report.checks.append(CheckResult("test", True, "OK"))

        with (
            patch("amplifier_distro.cli.run_preflight", return_value=ok_report),
            patch("amplifier_distro.cli.check_for_updates", return_value=None),
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
