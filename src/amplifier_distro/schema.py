"""Pydantic schema for ~/.amplifier/distro.yaml

Default values here MUST match the canonical constants in conventions.py.
conventions.py is the source of truth for all filenames, paths, and naming
standards. This schema defines the shape of distro.yaml; conventions.py
defines the fixed assumptions the distro relies on.
"""

from pydantic import BaseModel, Field


class IdentityConfig(BaseModel):
    github_handle: str = ""
    git_email: str = ""


class BundleConfig(BaseModel):
    active: str = "my-amplifier"
    validate_on_start: bool = True
    strict: bool = True


class CacheConfig(BaseModel):
    max_age_hours: int = 168
    auto_refresh_on_error: bool = True
    auto_refresh_on_stale: bool = True


class MemoryConfig(BaseModel):
    # Source of truth: conventions.AMPLIFIER_HOME / conventions.MEMORY_DIR
    path: str = "~/.amplifier/memory"
    # Source of truth: conventions.LEGACY_MEMORY_DIR
    legacy_paths: list[str] = Field(default_factory=lambda: ["~/amplifier-dev-memory"])


class PreflightConfig(BaseModel):
    enabled: bool = True
    mode: str = "block"  # block | warn | off


class InterfaceEntry(BaseModel):
    installed: bool = False
    path: str = ""


class InterfacesConfig(BaseModel):
    cli: InterfaceEntry = Field(default_factory=lambda: InterfaceEntry(installed=True))
    tui: InterfaceEntry = Field(default_factory=InterfaceEntry)
    voice: InterfaceEntry = Field(default_factory=InterfaceEntry)
    gui: InterfaceEntry = Field(default_factory=InterfaceEntry)


class SlackConfig(BaseModel):
    """Slack bridge settings (non-secret).

    Secrets (bot_token, app_token) live in keys.yaml per Opinion #11.
    """

    hub_channel_id: str = ""
    hub_channel_name: str = "amplifier"
    socket_mode: bool = True
    thread_per_session: bool = True
    allow_breakout: bool = True
    channel_prefix: str = "amp-"
    bot_name: str = "slackbridge"


class VoiceConfig(BaseModel):
    """Voice bridge settings for OpenAI Realtime API.

    Uses WebRTC for direct browser-to-OpenAI audio streaming.
    The OPENAI_API_KEY secret lives in keys.yaml / environment per Opinion #11.
    """

    # OpenAI voice: alloy, ash, ballad, coral, echo, sage, shimmer, verse
    voice: str = "ash"
    model: str = "gpt-4o-realtime-preview"
    instructions: str = ""  # System prompt for voice sessions
    tools_enabled: bool = False  # Enable Amplifier tool calling


class BackupConfig(BaseModel):
    """Backup to a private GitHub repo.

    repo_owner defaults to identity.github_handle when None.
    """

    repo_name: str = "amplifier-backup"
    repo_owner: str | None = None
    auto: bool = False


class ServerConfig(BaseModel):
    """Server settings including optional API key authentication.

    If api_key is set, mutation endpoints require an
    Authorization: Bearer <key> header. Read-only endpoints
    (health, status, apps) remain open.
    """

    api_key: str = ""


class WatchdogConfig(BaseModel):
    """Watchdog settings for server health monitoring.

    The watchdog is a lightweight process that polls the server health
    endpoint and restarts the server after sustained downtime.
    """

    check_interval_seconds: int = 30
    restart_after_seconds: int = 300  # 5 minutes of sustained downtime
    max_restarts: int = 5  # per watchdog session; 0 = unlimited


class DistroConfig(BaseModel):
    workspace_root: str = "~/dev"
    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    bundle: BundleConfig = Field(default_factory=BundleConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    preflight: PreflightConfig = Field(default_factory=PreflightConfig)
    interfaces: InterfacesConfig = Field(default_factory=InterfacesConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    watchdog: WatchdogConfig = Field(default_factory=WatchdogConfig)
