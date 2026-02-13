"""Amplifier Distro Conventions - IMMUTABLE

This file defines the canonical names, paths, and conventions that all
distro tools agree on. These values are NOT configurable. They are the
bedrock assumptions that make the distro work.

Things that CAN be configured (via distro.yaml):
- workspace_root (where projects live)
- which bundle is active
- cache TTL

Things that CANNOT be configured (defined HERE):
- filenames (handoff.md, memory-store.yaml, etc.)
- directory structure within ~/.amplifier/
- session file names
- convention file locations

If you need to change something here, you're changing the distro's
social contract. That requires a major version bump and migration.
"""

# --- The Root ---
# Everything lives under this directory. This is the ONE path
# that is hardcoded. distro.yaml lives here.
AMPLIFIER_HOME = "~/.amplifier"

# --- Configuration ---
DISTRO_CONFIG_FILENAME = "distro.yaml"
# Full path: ~/.amplifier/distro.yaml

# --- Memory Store ---
MEMORY_DIR = "memory"  # relative to AMPLIFIER_HOME
MEMORY_STORE_FILENAME = "memory-store.yaml"
WORK_LOG_FILENAME = "work-log.yaml"
PROJECT_NOTES_FILENAME = "project-notes.md"
# Full paths: ~/.amplifier/memory/memory-store.yaml, etc.

# Legacy memory location (for migration detection)
LEGACY_MEMORY_DIR = "~/amplifier-dev-memory"

# --- Sessions ---
PROJECTS_DIR = "projects"  # relative to AMPLIFIER_HOME
# Session files (within each session directory)
TRANSCRIPT_FILENAME = "transcript.jsonl"
EVENTS_FILENAME = "events.jsonl"
SESSION_INFO_FILENAME = "session-info.json"
METADATA_FILENAME = "metadata.json"

# --- Handoffs ---
HANDOFF_FILENAME = "handoff.md"
# Lives in: ~/.amplifier/projects/<project>/<session>/handoff.md
# Also optionally in project working directory for cross-session context

# --- Bundle ---
KEYS_FILENAME = "keys.yaml"
BUNDLE_REGISTRY_FILENAME = "bundle-registry.yaml"
SETTINGS_FILENAME = "settings.yaml"
CACHE_DIR = "cache"  # relative to AMPLIFIER_HOME

# --- Generated Bundle ---
DISTRO_BUNDLE_DIR = "bundles"  # relative to AMPLIFIER_HOME
DISTRO_BUNDLE_FILENAME = "distro.yaml"
DISTRO_BUNDLE_NAME = "amplifier-distro"
# Full path: ~/.amplifier/bundles/distro.yaml

# --- Server ---
SERVER_DIR = "server"  # relative to AMPLIFIER_HOME
SERVER_SOCKET = "server.sock"  # Unix socket for local IPC
SERVER_PID_FILE = "server.pid"
SERVER_LOG_FILE = "server.log"
SERVER_DEFAULT_PORT = 8400
SLACK_SESSIONS_FILENAME = "slack-sessions.json"  # Slack bridge session mappings
EMAIL_SESSIONS_FILENAME = "email-sessions.json"  # Email bridge session mappings

# --- Crash logs ---
CRASH_LOG_FILE = "crash.log"  # relative to SERVER_DIR
WATCHDOG_CRASH_LOG_FILE = "watchdog-crash.log"  # relative to SERVER_DIR

# --- Watchdog ---
WATCHDOG_PID_FILE = "watchdog.pid"  # relative to SERVER_DIR
WATCHDOG_LOG_FILE = "watchdog.log"  # relative to SERVER_DIR

# --- Platform Service ---
SERVICE_NAME = "amplifier-distro"  # systemd unit name
LAUNCHD_LABEL = "com.amplifier.distro"  # macOS launchd job label

# --- Interface Registry ---
# When an interface is installed, it registers here
INTERFACES_DIR = "interfaces"  # relative to AMPLIFIER_HOME

# --- Backup ---
BACKUP_REPO_PATTERN = "{github_handle}/amplifier-backup"
BACKUP_INCLUDE = [
    DISTRO_CONFIG_FILENAME,
    MEMORY_DIR,
    SETTINGS_FILENAME,
    BUNDLE_REGISTRY_FILENAME,
    DISTRO_BUNDLE_DIR,  # Custom bundles
]
BACKUP_EXCLUDE = [
    KEYS_FILENAME,  # Security: never backup keys
    CACHE_DIR,  # Rebuilds automatically
    PROJECTS_DIR,  # Team tracking handles this
    SERVER_DIR,  # Runtime state, not config
]

# --- Update Check ---
UPDATE_CHECK_CACHE_FILENAME = "update-check.json"  # relative to CACHE_DIR
# Full path: ~/.amplifier/cache/update-check.json
UPDATE_CHECK_TTL_HOURS = 24  # Don't re-check more than once per day
PYPI_PACKAGE_NAME = "amplifier-distro"
GITHUB_REPO = "microsoft/amplifier-distro"

# --- Project-Level Conventions ---
# These files may appear in a project's working directory
PROJECT_AGENTS_FILENAME = "AGENTS.md"
PROJECT_AMPLIFIER_DIR = ".amplifier"
PROJECT_SETTINGS_FILENAME = "settings.yaml"  # within .amplifier/

# --- File Format Standards ---
# These define what format each convention file uses
FORMATS = {
    "config": "yaml",
    "memory": "yaml",
    "sessions": "jsonl",
    "handoffs": "markdown",
    "bundles": "markdown+yaml-frontmatter",
}
