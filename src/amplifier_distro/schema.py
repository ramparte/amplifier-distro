"""Pydantic schema for ~/.amplifier/distro.yaml"""

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
    path: str = "~/.amplifier/memory"
    # Legacy location for migration detection
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


class DistroConfig(BaseModel):
    workspace_root: str = "~/dev"
    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    bundle: BundleConfig = Field(default_factory=BundleConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    preflight: PreflightConfig = Field(default_factory=PreflightConfig)
    interfaces: InterfacesConfig = Field(default_factory=InterfacesConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
