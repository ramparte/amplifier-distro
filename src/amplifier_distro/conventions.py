"""Amplifier Distro Conventions - Server & Experience Layer

Path constants and naming conventions for the distro experience server.
Core CLI and bundle conventions live in amplifier-foundation's
DIRECTORY_CONTRACT.md — this file covers only server-specific paths.

These values are NOT configurable. They are the bedrock assumptions
that make the experience server work.
"""

# --- The Root ---
AMPLIFIER_HOME = "~/.amplifier"

# --- Keys ---
KEYS_FILENAME = "keys.yaml"
SETTINGS_FILENAME = "settings.yaml"

# --- Memory Store ---
MEMORY_DIR = "memory"  # relative to AMPLIFIER_HOME
MEMORY_STORE_FILENAME = "memory-store.yaml"
WORK_LOG_FILENAME = "work-log.yaml"

# --- Sessions ---
TRANSCRIPT_FILENAME = "transcript.jsonl"

# --- Server ---
SERVER_DIR = "server"  # relative to AMPLIFIER_HOME
SERVER_SOCKET = "server.sock"
SERVER_PID_FILE = "server.pid"
SERVER_LOG_FILE = "server.log"
SERVER_DEFAULT_PORT = 8400
SLACK_SESSIONS_FILENAME = "slack-sessions.json"
TEAMS_SESSIONS_FILENAME = "teams-sessions.json"
WEB_CHAT_SESSIONS_FILENAME = "web-chat-sessions.json"

# --- Crash logs ---
CRASH_LOG_FILE = "crash.log"  # relative to SERVER_DIR
WATCHDOG_CRASH_LOG_FILE = "watchdog-crash.log"

# --- Watchdog ---
WATCHDOG_PID_FILE = "watchdog.pid"  # relative to SERVER_DIR
WATCHDOG_LOG_FILE = "watchdog.log"

# --- Platform Service ---
SERVICE_NAME = "amplifier-distro"  # systemd unit name
LAUNCHD_LABEL = "com.amplifier.distro"  # macOS launchd job label

# --- Backup ---
BACKUP_REPO_PATTERN = "{github_handle}/amplifier-backup"
BACKUP_INCLUDE = [
    SETTINGS_FILENAME,
    MEMORY_DIR,
]
BACKUP_EXCLUDE = [
    KEYS_FILENAME,  # Security: never backup keys
    SERVER_DIR,  # Runtime state, not config
]
