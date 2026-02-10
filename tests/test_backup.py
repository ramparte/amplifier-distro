"""Backup System Tests

These tests validate the T6 backup system: configuration, file collection,
backup/restore flows, CLI commands, and auto-backup.

Exit criteria verified:
1. BackupConfig defaults and custom values
2. BackupConfig integrates with DistroConfig
3. File collection includes correct files (conventions.BACKUP_INCLUDE)
4. File collection excludes keys, cache, projects, server
5. Backup flow creates repo and pushes (mocked gh/git)
6. Restore flow clones and copies (mocked git)
7. Restore never restores keys.yaml
8. CLI backup and restore commands exist and work
9. Configurable repo names via CLI --name flag
10. Auto-backup respects config.backup.auto
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from amplifier_distro import conventions
from amplifier_distro.backup import (
    BackupResult,
    RestoreResult,
    _resolve_repo,
    collect_backup_files,
    run_auto_backup,
)
from amplifier_distro.cli import main
from amplifier_distro.schema import BackupConfig, DistroConfig, IdentityConfig

# ---------------------------------------------------------------------------
#  BackupConfig schema
# ---------------------------------------------------------------------------


class TestBackupConfig:
    """Verify BackupConfig defaults and integration with DistroConfig."""

    def test_default_repo_name(self):
        cfg = BackupConfig()
        assert cfg.repo_name == "amplifier-backup"

    def test_default_repo_owner_is_none(self):
        cfg = BackupConfig()
        assert cfg.repo_owner is None

    def test_default_auto_is_false(self):
        cfg = BackupConfig()
        assert cfg.auto is False

    def test_custom_values(self):
        cfg = BackupConfig(repo_name="my-backup", repo_owner="myorg", auto=True)
        assert cfg.repo_name == "my-backup"
        assert cfg.repo_owner == "myorg"
        assert cfg.auto is True

    def test_distro_config_has_backup_section(self):
        config = DistroConfig()
        assert hasattr(config, "backup")
        assert isinstance(config.backup, BackupConfig)

    def test_distro_config_backup_defaults(self):
        config = DistroConfig()
        assert config.backup.repo_name == "amplifier-backup"
        assert config.backup.repo_owner is None
        assert config.backup.auto is False

    def test_distro_config_roundtrips_backup(self):
        """BackupConfig survives YAML-style dict round-trip."""
        import yaml

        config = DistroConfig(
            backup=BackupConfig(repo_name="custom-bak", auto=True),
        )
        data = config.model_dump()
        yaml_str = yaml.dump(data)
        loaded = yaml.safe_load(yaml_str)
        restored = DistroConfig(**loaded)
        assert restored.backup.repo_name == "custom-bak"
        assert restored.backup.auto is True
        assert restored.backup.repo_owner is None


# ---------------------------------------------------------------------------
#  Repo name resolution
# ---------------------------------------------------------------------------


class TestResolveRepo:
    """Verify _resolve_repo builds the correct owner/repo string."""

    def test_defaults_to_gh_handle(self):
        cfg = BackupConfig()
        assert _resolve_repo(cfg, "alice") == "alice/amplifier-backup"

    def test_custom_repo_name(self):
        cfg = BackupConfig(repo_name="my-bak")
        assert _resolve_repo(cfg, "alice") == "alice/my-bak"

    def test_custom_owner_overrides_handle(self):
        cfg = BackupConfig(repo_owner="myorg")
        assert _resolve_repo(cfg, "alice") == "myorg/amplifier-backup"

    def test_custom_owner_and_name(self):
        cfg = BackupConfig(repo_name="state", repo_owner="myorg")
        assert _resolve_repo(cfg, "alice") == "myorg/state"


# ---------------------------------------------------------------------------
#  File collection
# ---------------------------------------------------------------------------


class TestCollectBackupFiles:
    """Verify collect_backup_files includes/excludes the right things."""

    @pytest.fixture()
    def amp_home(self, tmp_path):
        """Create a realistic ~/.amplifier directory tree."""
        home = tmp_path / ".amplifier"
        home.mkdir()

        # Included files
        (home / conventions.DISTRO_CONFIG_FILENAME).write_text("workspace_root: ~/dev")
        (home / conventions.SETTINGS_FILENAME).write_text("theme: dark")
        (home / conventions.BUNDLE_REGISTRY_FILENAME).write_text("bundles: []")

        # Included directory: memory/
        mem = home / conventions.MEMORY_DIR
        mem.mkdir()
        (mem / conventions.MEMORY_STORE_FILENAME).write_text("memories: []")
        (mem / conventions.WORK_LOG_FILENAME).write_text("log: []")

        # Included directory: bundles/
        bundles = home / conventions.DISTRO_BUNDLE_DIR
        bundles.mkdir()
        (bundles / "custom.yaml").write_text("name: custom")

        # Excluded files / directories
        (home / conventions.KEYS_FILENAME).write_text("SECRET=abc")
        cache = home / conventions.CACHE_DIR
        cache.mkdir()
        (cache / "cached.txt").write_text("stale")
        projects = home / conventions.PROJECTS_DIR
        projects.mkdir()
        (projects / "proj.json").write_text("{}")
        server = home / conventions.SERVER_DIR
        server.mkdir()
        (server / "server.pid").write_text("1234")

        return home

    def test_includes_distro_config(self, amp_home):
        files = collect_backup_files(amp_home)
        names = [f.name for f in files]
        assert conventions.DISTRO_CONFIG_FILENAME in names

    def test_includes_settings(self, amp_home):
        files = collect_backup_files(amp_home)
        names = [f.name for f in files]
        assert conventions.SETTINGS_FILENAME in names

    def test_includes_bundle_registry(self, amp_home):
        files = collect_backup_files(amp_home)
        names = [f.name for f in files]
        assert conventions.BUNDLE_REGISTRY_FILENAME in names

    def test_includes_memory_files(self, amp_home):
        files = collect_backup_files(amp_home)
        names = [f.name for f in files]
        assert conventions.MEMORY_STORE_FILENAME in names
        assert conventions.WORK_LOG_FILENAME in names

    def test_includes_custom_bundles(self, amp_home):
        files = collect_backup_files(amp_home)
        names = [f.name for f in files]
        assert "custom.yaml" in names

    def test_excludes_keys(self, amp_home):
        files = collect_backup_files(amp_home)
        names = [f.name for f in files]
        assert conventions.KEYS_FILENAME not in names

    def test_excludes_cache(self, amp_home):
        files = collect_backup_files(amp_home)
        rel_parts = [f.relative_to(amp_home).parts[0] for f in files]
        assert conventions.CACHE_DIR not in rel_parts

    def test_excludes_projects(self, amp_home):
        files = collect_backup_files(amp_home)
        rel_parts = [f.relative_to(amp_home).parts[0] for f in files]
        assert conventions.PROJECTS_DIR not in rel_parts

    def test_excludes_server(self, amp_home):
        files = collect_backup_files(amp_home)
        rel_parts = [f.relative_to(amp_home).parts[0] for f in files]
        assert conventions.SERVER_DIR not in rel_parts

    def test_returns_sorted_paths(self, amp_home):
        files = collect_backup_files(amp_home)
        assert files == sorted(files)

    def test_empty_home_returns_empty_list(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert collect_backup_files(empty) == []

    def test_returns_absolute_paths(self, amp_home):
        files = collect_backup_files(amp_home)
        assert all(f.is_absolute() for f in files)


# ---------------------------------------------------------------------------
#  Backup flow (mocked subprocess)
# ---------------------------------------------------------------------------


class TestBackupFlow:
    """Verify the backup function orchestrates gh and git correctly."""

    @pytest.fixture()
    def amp_home(self, tmp_path):
        home = tmp_path / ".amplifier"
        home.mkdir()
        (home / conventions.DISTRO_CONFIG_FILENAME).write_text("ok")
        mem = home / conventions.MEMORY_DIR
        mem.mkdir()
        (mem / "note.yaml").write_text("hello")
        return home

    @patch("amplifier_distro.backup._run_git")
    @patch("amplifier_distro.backup._ensure_repo_exists", return_value=True)
    def test_backup_success(self, _mock_repo, _mock_git, amp_home):
        from amplifier_distro.backup import backup

        cfg = BackupConfig()
        result = backup(cfg, amp_home, "alice")
        assert result.status == "success"
        assert result.repo == "alice/amplifier-backup"
        assert len(result.files) > 0
        assert result.timestamp != ""

    @patch("amplifier_distro.backup._ensure_repo_exists", return_value=False)
    def test_backup_fails_when_repo_unavailable(self, _mock_repo, amp_home):
        from amplifier_distro.backup import backup

        cfg = BackupConfig()
        result = backup(cfg, amp_home, "alice")
        assert result.status == "error"
        assert "Could not create" in result.message

    def test_backup_no_files(self, tmp_path):
        from amplifier_distro.backup import backup

        empty = tmp_path / "empty"
        empty.mkdir()
        result = backup(BackupConfig(), empty, "alice")
        assert result.status == "error"
        assert "No files" in result.message

    @patch("amplifier_distro.backup._ensure_repo_exists", side_effect=FileNotFoundError)
    def test_backup_handles_missing_gh_cli(self, _mock, amp_home):
        from amplifier_distro.backup import backup

        result = backup(BackupConfig(), amp_home, "alice")
        assert result.status == "error"
        assert "gh CLI" in result.message


# ---------------------------------------------------------------------------
#  Restore flow (mocked subprocess)
# ---------------------------------------------------------------------------


class TestRestoreFlow:
    """Verify the restore function clones and copies correctly."""

    @patch("amplifier_distro.backup.subprocess.run")
    def test_restore_success(self, mock_run, tmp_path):
        from amplifier_distro.backup import restore

        amp_home = tmp_path / ".amplifier"
        amp_home.mkdir()

        def fake_clone(cmd, **kwargs):
            """Simulate git clone by creating files in the target dir."""
            clone_dir = Path(cmd[-1])
            clone_dir.mkdir(parents=True, exist_ok=True)
            (clone_dir / conventions.DISTRO_CONFIG_FILENAME).write_text("ok")
            (clone_dir / conventions.SETTINGS_FILENAME).write_text("settings")
            # Simulate .git dir (should be skipped)
            git_dir = clone_dir / ".git"
            git_dir.mkdir()
            (git_dir / "config").write_text("gitconfig")
            # Simulate keys.yaml in backup (should NOT be restored)
            (clone_dir / conventions.KEYS_FILENAME).write_text("SECRET")
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_clone
        result = restore(BackupConfig(), amp_home, "alice")

        assert result.status == "success"
        assert len(result.files) == 2  # distro.yaml + settings.yaml
        assert conventions.KEYS_FILENAME not in result.files
        assert (amp_home / conventions.DISTRO_CONFIG_FILENAME).exists()
        assert (amp_home / conventions.SETTINGS_FILENAME).exists()
        assert not (amp_home / conventions.KEYS_FILENAME).exists()

    @patch("amplifier_distro.backup.subprocess.run", side_effect=FileNotFoundError)
    def test_restore_clone_failure(self, _mock, tmp_path):
        from amplifier_distro.backup import restore

        amp_home = tmp_path / ".amplifier"
        amp_home.mkdir()
        result = restore(BackupConfig(), amp_home, "alice")
        assert result.status == "error"
        assert "Clone failed" in result.message

    @patch("amplifier_distro.backup.subprocess.run")
    def test_restore_never_restores_keys(self, mock_run, tmp_path):
        """Security: keys.yaml must NEVER be restored even if present in backup."""
        from amplifier_distro.backup import restore

        amp_home = tmp_path / ".amplifier"
        amp_home.mkdir()

        def fake_clone(cmd, **kwargs):
            clone_dir = Path(cmd[-1])
            clone_dir.mkdir(parents=True, exist_ok=True)
            (clone_dir / conventions.KEYS_FILENAME).write_text("SECRET=xyz")
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_clone
        result = restore(BackupConfig(), amp_home, "alice")

        assert result.status == "success"
        assert not (amp_home / conventions.KEYS_FILENAME).exists()
        assert conventions.KEYS_FILENAME in result.message


# ---------------------------------------------------------------------------
#  Auto-backup
# ---------------------------------------------------------------------------


class TestAutoBackup:
    """Verify run_auto_backup honours the config flag."""

    @patch("amplifier_distro.config.load_config")
    def test_auto_backup_disabled_returns_none(self, mock_load):
        mock_load.return_value = DistroConfig(
            backup=BackupConfig(auto=False),
        )
        assert run_auto_backup() is None

    @patch("amplifier_distro.config.load_config")
    def test_auto_backup_no_handle_returns_error(self, mock_load):
        mock_load.return_value = DistroConfig(
            backup=BackupConfig(auto=True),
            identity=IdentityConfig(github_handle=""),
        )
        result = run_auto_backup()
        assert result is not None
        assert result.status == "error"
        assert "github_handle" in result.message

    @patch("amplifier_distro.backup.backup")
    @patch("amplifier_distro.config.load_config")
    def test_auto_backup_enabled_calls_backup(self, mock_load, mock_backup):
        mock_load.return_value = DistroConfig(
            backup=BackupConfig(auto=True),
            identity=IdentityConfig(github_handle="alice"),
        )
        mock_backup.return_value = BackupResult(status="success", message="ok")
        result = run_auto_backup()
        assert result is not None
        assert result.status == "success"
        mock_backup.assert_called_once()


# ---------------------------------------------------------------------------
#  CLI commands
# ---------------------------------------------------------------------------


class TestBackupCLI:
    """Verify backup and restore CLI commands exist and accept --name."""

    def test_backup_command_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["backup", "--help"])
        assert result.exit_code == 0
        assert "backup" in result.output.lower()

    def test_restore_command_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["restore", "--help"])
        assert result.exit_code == 0
        assert "restore" in result.output.lower()

    def test_backup_has_name_option(self):
        runner = CliRunner()
        result = runner.invoke(main, ["backup", "--help"])
        assert "--name" in result.output

    def test_restore_has_name_option(self):
        runner = CliRunner()
        result = runner.invoke(main, ["restore", "--help"])
        assert "--name" in result.output

    @patch("amplifier_distro.cli.load_config")
    def test_backup_fails_without_identity(self, mock_load):
        """backup must fail if no github_handle is configured."""
        mock_load.return_value = DistroConfig()
        runner = CliRunner()
        result = runner.invoke(main, ["backup"])
        assert result.exit_code != 0
        assert "github_handle" in result.output or "init" in result.output

    @patch("amplifier_distro.cli.load_config")
    def test_restore_fails_without_identity(self, mock_load):
        """restore must fail if no github_handle is configured."""
        mock_load.return_value = DistroConfig()
        runner = CliRunner()
        result = runner.invoke(main, ["restore"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
#  Result models
# ---------------------------------------------------------------------------


class TestResultModels:
    """Verify BackupResult and RestoreResult data models."""

    def test_backup_result_defaults(self):
        r = BackupResult(status="success")
        assert r.files == []
        assert r.timestamp == ""
        assert r.message == ""
        assert r.repo == ""

    def test_restore_result_defaults(self):
        r = RestoreResult(status="error", message="fail")
        assert r.files == []
        assert r.repo == ""
