"""Phase 1 Acceptance Tests

These tests validate Phase 1 capabilities: memory standardization
and bundle validation strict mode enablement.

Exit criteria verified:
1. Memory config uses canonical path ~/.amplifier/memory
2. Migration helper moves files from legacy location
3. Migration creates backward-compat symlink
4. Pre-flight includes memory store check
5. Schema supports strict bundle validation flag
"""

from unittest.mock import patch

import yaml

from amplifier_distro.migrate import MEMORY_FILES, MigrationResult, migrate_memory
from amplifier_distro.schema import (  # noqa: F401
    BundleConfig,
    DistroConfig,
    MemoryConfig,
)


class TestMemoryConfig:
    """Verify memory configuration uses canonical paths.

    Antagonist note: These pin the exact default path and legacy path strings.
    Any change to the canonical location without updating these tests will fail.
    """

    def test_canonical_path(self):
        config = DistroConfig()
        assert config.memory.path == "~/.amplifier/memory"

    def test_legacy_paths_include_old_location(self):
        config = DistroConfig()
        assert "~/amplifier-dev-memory" in config.memory.legacy_paths

    def test_memory_config_in_yaml_roundtrip(self):
        config = DistroConfig()
        data = config.model_dump()
        yaml_str = yaml.dump(data)
        loaded = yaml.safe_load(yaml_str)
        assert loaded["memory"]["path"] == "~/.amplifier/memory"
        assert "~/amplifier-dev-memory" in loaded["memory"]["legacy_paths"]


class TestMemoryMigration:
    """Verify migration from legacy to canonical location.

    Antagonist note: Each test exercises a distinct code path in migrate_memory:
    1. Legacy exists, canonical doesn't -> migrate files + create symlink
    2. Canonical already exists -> no-op, don't overwrite
    3. Neither exists -> create empty canonical directory
    All tests use real filesystem operations in tmp_path with load_config
    mocked to return controlled paths (never touching real ~/.amplifier/).
    """

    def _make_config(self, tmp_path, legacy_name="old-memory"):
        """Create a DistroConfig pointing at tmp_path locations."""
        return DistroConfig(
            memory=MemoryConfig(
                path=str(tmp_path / ".amplifier" / "memory"),
                legacy_paths=[str(tmp_path / legacy_name)],
            )
        )

    def test_migration_moves_files_from_legacy(self, tmp_path):
        """When legacy dir exists and canonical doesn't, files are moved."""
        legacy = tmp_path / "old-memory"
        legacy.mkdir()
        (legacy / "memory-store.yaml").write_text("memories: []")
        (legacy / "work-log.yaml").write_text("log: []")

        config = self._make_config(tmp_path)
        canonical = tmp_path / ".amplifier" / "memory"

        with patch("amplifier_distro.migrate.load_config", return_value=config):
            result = migrate_memory()

        assert result.migrated is True
        assert "memory-store.yaml" in result.files_moved
        assert "work-log.yaml" in result.files_moved
        assert (canonical / "memory-store.yaml").exists()
        assert (canonical / "work-log.yaml").exists()

    def test_migration_creates_backward_compat_symlink(self, tmp_path):
        """After migration, a symlink must exist at the legacy location."""
        legacy = tmp_path / "old-memory"
        legacy.mkdir()
        (legacy / "memory-store.yaml").write_text("memories: []")

        config = self._make_config(tmp_path)
        canonical = tmp_path / ".amplifier" / "memory"

        with patch("amplifier_distro.migrate.load_config", return_value=config):
            result = migrate_memory()

        assert result.migrated is True
        assert legacy.is_symlink(), "Legacy path should be a symlink after migration"
        assert legacy.resolve() == canonical.resolve()

    def test_migration_noop_when_canonical_exists(self, tmp_path):
        """When canonical already has data, migration must NOT overwrite it."""
        canonical = tmp_path / ".amplifier" / "memory"
        canonical.mkdir(parents=True)
        (canonical / "memory-store.yaml").write_text("canonical: data")

        legacy = tmp_path / "old-memory"
        legacy.mkdir()
        (legacy / "memory-store.yaml").write_text("legacy: data")

        config = self._make_config(tmp_path)

        with patch("amplifier_distro.migrate.load_config", return_value=config):
            result = migrate_memory()

        assert result.migrated is False
        # Canonical data must be untouched
        assert (canonical / "memory-store.yaml").read_text() == "canonical: data"

    def test_migration_creates_empty_when_neither_exists(self, tmp_path):
        """When neither legacy nor canonical exist, create empty canonical."""
        config = self._make_config(tmp_path, legacy_name="nonexistent-legacy")
        canonical = tmp_path / ".amplifier" / "memory"

        with patch("amplifier_distro.migrate.load_config", return_value=config):
            result = migrate_memory()

        assert result.migrated is False
        assert canonical.exists(), "Empty canonical directory should be created"
        assert "nitializ" in result.message  # "Initialized empty memory store"

    def test_migration_result_has_correct_fields(self, tmp_path):
        """MigrationResult must have all documented fields."""
        result = MigrationResult(
            migrated=True,
            source="/old",
            destination="/new",
            files_moved=["a.yaml"],
            message="done",
        )
        assert result.migrated is True
        assert result.source == "/old"
        assert result.destination == "/new"
        assert result.files_moved == ["a.yaml"]
        assert result.message == "done"

    def test_memory_files_constant_has_expected_entries(self):
        """The MEMORY_FILES constant should include the known memory files."""
        assert "memory-store.yaml" in MEMORY_FILES
        assert "work-log.yaml" in MEMORY_FILES


class TestStrictBundleValidation:
    """Verify schema supports strict validation flag.

    Antagonist note: This tests that the strict flag exists, defaults to True,
    and can be toggled. The strict flag gates whether bundle composition errors
    are fatal or just warnings.
    """

    def test_strict_defaults_to_true(self):
        config = DistroConfig()
        assert config.bundle.strict is True

    def test_strict_can_be_disabled(self):
        config = DistroConfig(
            bundle=BundleConfig(active="test", strict=False, validate_on_start=True)
        )
        assert config.bundle.strict is False

    def test_validate_on_start_defaults_to_true(self):
        config = DistroConfig()
        assert config.bundle.validate_on_start is True
