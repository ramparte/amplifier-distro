"""Conventions Acceptance Tests

These tests validate that conventions.py is correct, complete, and immutable.
The conventions file is the bedrock social contract of the distro - filenames,
paths, and naming standards that all tools agree on.

Exit criteria verified:
1. All canonical constants have correct pinned values
2. All filename/directory constants are non-empty strings
3. BACKUP_EXCLUDE includes KEYS_FILENAME (security: never backup keys)
4. BACKUP_INCLUDE includes required config files
5. FORMATS covers all expected categories with correct values
6. Module contains NO functions and NO classes (pure constants)
7. Every constant referenced by other modules (schema, bridge, server) exists
8. BACKUP_INCLUDE and BACKUP_EXCLUDE are disjoint (no contradictions)
"""

import inspect
import types

from amplifier_distro import conventions


class TestCanonicalValues:
    """Verify every canonical constant has the correct pinned value.

    Antagonist note: Each test pins exactly one constant. If any value
    changes without updating these tests, it will fail. This IS the
    social contract.
    """

    def test_amplifier_home(self):
        assert conventions.AMPLIFIER_HOME == "~/.amplifier"

    def test_distro_config_filename(self):
        assert conventions.DISTRO_CONFIG_FILENAME == "distro.yaml"

    def test_memory_dir(self):
        assert conventions.MEMORY_DIR == "memory"

    def test_memory_store_filename(self):
        assert conventions.MEMORY_STORE_FILENAME == "memory-store.yaml"

    def test_work_log_filename(self):
        assert conventions.WORK_LOG_FILENAME == "work-log.yaml"

    def test_project_notes_filename(self):
        assert conventions.PROJECT_NOTES_FILENAME == "project-notes.md"

    def test_legacy_memory_dir(self):
        assert conventions.LEGACY_MEMORY_DIR == "~/amplifier-dev-memory"

    def test_projects_dir(self):
        assert conventions.PROJECTS_DIR == "projects"

    def test_transcript_filename(self):
        assert conventions.TRANSCRIPT_FILENAME == "transcript.jsonl"

    def test_events_filename(self):
        assert conventions.EVENTS_FILENAME == "events.jsonl"

    def test_session_info_filename(self):
        assert conventions.SESSION_INFO_FILENAME == "session-info.json"

    def test_metadata_filename(self):
        assert conventions.METADATA_FILENAME == "metadata.json"

    def test_handoff_filename(self):
        assert conventions.HANDOFF_FILENAME == "handoff.md"

    def test_keys_filename(self):
        assert conventions.KEYS_FILENAME == "keys.yaml"

    def test_bundle_registry_filename(self):
        assert conventions.BUNDLE_REGISTRY_FILENAME == "bundle-registry.yaml"

    def test_settings_filename(self):
        assert conventions.SETTINGS_FILENAME == "settings.yaml"

    def test_cache_dir(self):
        assert conventions.CACHE_DIR == "cache"

    def test_server_dir(self):
        assert conventions.SERVER_DIR == "server"

    def test_server_socket(self):
        assert conventions.SERVER_SOCKET == "server.sock"

    def test_server_pid_file(self):
        assert conventions.SERVER_PID_FILE == "server.pid"

    def test_server_default_port(self):
        assert conventions.SERVER_DEFAULT_PORT == 8400

    def test_interfaces_dir(self):
        assert conventions.INTERFACES_DIR == "interfaces"

    def test_project_agents_filename(self):
        assert conventions.PROJECT_AGENTS_FILENAME == "AGENTS.md"

    def test_project_amplifier_dir(self):
        assert conventions.PROJECT_AMPLIFIER_DIR == ".amplifier"

    def test_project_settings_filename(self):
        assert conventions.PROJECT_SETTINGS_FILENAME == "settings.yaml"

    def test_distro_bundle_dir(self):
        assert conventions.DISTRO_BUNDLE_DIR == "bundles"

    def test_distro_bundle_filename(self):
        assert conventions.DISTRO_BUNDLE_FILENAME == "distro.yaml"

    def test_distro_bundle_name(self):
        assert conventions.DISTRO_BUNDLE_NAME == "amplifier-distro"

    def test_backup_repo_pattern(self):
        assert conventions.BACKUP_REPO_PATTERN == "{github_handle}/amplifier-backup"


class TestStringConstants:
    """Verify all filename and directory constants are non-empty strings.

    Antagonist note: This catches accidental `= ""` or `= None` assignments.
    Every constant that represents a filename or directory must be a
    non-empty string.
    """

    FILENAME_CONSTANTS = [
        "DISTRO_CONFIG_FILENAME",
        "MEMORY_STORE_FILENAME",
        "WORK_LOG_FILENAME",
        "PROJECT_NOTES_FILENAME",
        "TRANSCRIPT_FILENAME",
        "EVENTS_FILENAME",
        "SESSION_INFO_FILENAME",
        "METADATA_FILENAME",
        "HANDOFF_FILENAME",
        "KEYS_FILENAME",
        "BUNDLE_REGISTRY_FILENAME",
        "SETTINGS_FILENAME",
        "SERVER_SOCKET",
        "SERVER_PID_FILE",
        "PROJECT_AGENTS_FILENAME",
        "PROJECT_SETTINGS_FILENAME",
        "DISTRO_BUNDLE_FILENAME",
        "DISTRO_BUNDLE_NAME",
    ]

    DIRECTORY_CONSTANTS = [
        "MEMORY_DIR",
        "PROJECTS_DIR",
        "CACHE_DIR",
        "SERVER_DIR",
        "INTERFACES_DIR",
        "PROJECT_AMPLIFIER_DIR",
        "DISTRO_BUNDLE_DIR",
    ]

    def test_all_filename_constants_are_nonempty_strings(self):
        for name in self.FILENAME_CONSTANTS:
            value = getattr(conventions, name)
            assert isinstance(value, str), f"{name} should be str, got {type(value)}"
            assert len(value) > 0, f"{name} should not be empty"

    def test_all_directory_constants_are_nonempty_strings(self):
        for name in self.DIRECTORY_CONSTANTS:
            value = getattr(conventions, name)
            assert isinstance(value, str), f"{name} should be str, got {type(value)}"
            assert len(value) > 0, f"{name} should not be empty"


class TestBackupSecurity:
    """Verify backup lists enforce security invariants.

    Antagonist note: The BACKUP_EXCLUDE list MUST contain KEYS_FILENAME.
    If someone removes it, credentials could be backed up to GitHub.
    This is a security-critical assertion.
    """

    def test_backup_exclude_contains_keys(self):
        """KEYS_FILENAME must be excluded from backups (security: never backup keys)."""
        assert conventions.KEYS_FILENAME in conventions.BACKUP_EXCLUDE

    def test_backup_exclude_contains_cache(self):
        """Cache rebuilds automatically - no need to backup."""
        assert conventions.CACHE_DIR in conventions.BACKUP_EXCLUDE

    def test_backup_exclude_contains_projects(self):
        """Team tracking handles project session data."""
        assert conventions.PROJECTS_DIR in conventions.BACKUP_EXCLUDE

    def test_backup_include_contains_distro_config(self):
        assert conventions.DISTRO_CONFIG_FILENAME in conventions.BACKUP_INCLUDE

    def test_backup_include_contains_memory_dir(self):
        assert conventions.MEMORY_DIR in conventions.BACKUP_INCLUDE

    def test_backup_include_contains_settings(self):
        assert conventions.SETTINGS_FILENAME in conventions.BACKUP_INCLUDE

    def test_backup_include_contains_bundle_registry(self):
        assert conventions.BUNDLE_REGISTRY_FILENAME in conventions.BACKUP_INCLUDE

    def test_backup_include_and_exclude_are_disjoint(self):
        """No item should appear in both include and exclude lists."""
        overlap = set(conventions.BACKUP_INCLUDE) & set(conventions.BACKUP_EXCLUDE)
        assert not overlap, f"Items in both INCLUDE and EXCLUDE: {overlap}"


class TestFormats:
    """Verify FORMATS dict covers all expected categories.

    Antagonist note: The FORMATS dict documents the file format convention
    for each category. Missing or wrong entries break tooling assumptions.
    """

    EXPECTED_CATEGORIES = ["config", "memory", "sessions", "handoffs", "bundles"]

    def test_formats_has_all_expected_categories(self):
        for category in self.EXPECTED_CATEGORIES:
            assert category in conventions.FORMATS, (
                f"Missing FORMATS category: {category}"
            )

    def test_formats_values_are_nonempty_strings(self):
        for category, fmt in conventions.FORMATS.items():
            assert isinstance(fmt, str), f"FORMATS[{category!r}] should be str"
            assert len(fmt) > 0, f"FORMATS[{category!r}] should not be empty"

    def test_config_format_is_yaml(self):
        assert conventions.FORMATS["config"] == "yaml"

    def test_memory_format_is_yaml(self):
        assert conventions.FORMATS["memory"] == "yaml"

    def test_sessions_format_is_jsonl(self):
        assert conventions.FORMATS["sessions"] == "jsonl"

    def test_handoffs_format_is_markdown(self):
        assert conventions.FORMATS["handoffs"] == "markdown"

    def test_bundles_format_includes_yaml_frontmatter(self):
        assert "yaml" in conventions.FORMATS["bundles"]
        assert "markdown" in conventions.FORMATS["bundles"]


class TestModulePurity:
    """Verify the conventions module is pure constants - no functions, no classes.

    Antagonist note: conventions.py must remain a pure data file. Functions
    and classes introduce behavior that could diverge from the contract.
    If you need logic, put it in a different module.
    """

    def test_no_functions_defined(self):
        """Module must have zero function definitions."""
        functions = [
            name
            for name, obj in inspect.getmembers(conventions)
            if inspect.isfunction(obj) and obj.__module__ == conventions.__name__
        ]
        assert functions == [], f"Unexpected functions in conventions: {functions}"

    def test_no_classes_defined(self):
        """Module must have zero class definitions."""
        classes = [
            name
            for name, obj in inspect.getmembers(conventions)
            if inspect.isclass(obj) and obj.__module__ == conventions.__name__
        ]
        assert classes == [], f"Unexpected classes in conventions: {classes}"

    def test_all_public_names_are_data_not_callables(self):
        """Every public name must be str, int, list, or dict - no callables.

        Antagonist note: This catches accidentally defined lambdas,
        imported functions, or other non-constant objects.
        """
        allowed_types = (str, int, list, dict)
        for name in dir(conventions):
            if name.startswith("_"):
                continue
            obj = getattr(conventions, name)
            # Skip imported modules (e.g., if someone adds `import os`)
            if isinstance(obj, types.ModuleType):
                continue
            assert isinstance(obj, allowed_types), (
                f"{name} is {type(obj).__name__}, expected one of "
                f"(str, int, list, dict)"
            )


class TestCrossModuleReferences:
    """Verify every constant referenced by other modules actually exists.

    Antagonist note: bridge.py, schema.py, and server/cli.py all depend
    on conventions having specific constants. If a constant is renamed or
    removed, these tests catch the breakage before runtime.
    """

    def test_constants_used_by_bridge(self):
        """bridge.py uses AMPLIFIER_HOME, PROJECTS_DIR, HANDOFF_FILENAME."""
        assert hasattr(conventions, "AMPLIFIER_HOME")
        assert hasattr(conventions, "PROJECTS_DIR")
        assert hasattr(conventions, "HANDOFF_FILENAME")

    def test_constants_used_by_schema(self):
        """schema.py defaults reference AMPLIFIER_HOME + MEMORY_DIR."""
        assert hasattr(conventions, "AMPLIFIER_HOME")
        assert hasattr(conventions, "MEMORY_DIR")
        assert hasattr(conventions, "LEGACY_MEMORY_DIR")
        # schema.py default memory.path must be derivable from conventions
        expected = conventions.AMPLIFIER_HOME + "/" + conventions.MEMORY_DIR
        assert expected == "~/.amplifier/memory"

    def test_constants_used_by_server(self):
        """server/cli.py uses SERVER_DEFAULT_PORT as its default."""
        assert hasattr(conventions, "SERVER_DEFAULT_PORT")
        assert conventions.SERVER_DEFAULT_PORT == 8400

    def test_backup_repo_pattern_has_placeholder(self):
        """BACKUP_REPO_PATTERN is used with .format(github_handle=...)."""
        assert hasattr(conventions, "BACKUP_REPO_PATTERN")
        assert "{github_handle}" in conventions.BACKUP_REPO_PATTERN
