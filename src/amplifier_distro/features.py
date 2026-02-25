"""Feature catalog for the Amplifier Distro.

Each feature maps to one or more bundle includes. Features are organized
into tiers. The wizard uses this catalog to generate and modify the
distro bundle.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Feature:
    id: str
    name: str
    description: str
    tier: int
    includes: list[str]
    category: str  # "memory", "planning", "search", "workflow", "content"
    requires: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    description: str
    include: str
    key_prefix: str
    env_var: str
    default_model: str
    module_id: str = ""
    source_url: str = ""  # git URL for module installation
    console_url: str = ""
    fallback_models: tuple[str, ...] = ()
    base_url: str | None = None
    api_key_config: str | None = None


# --- Ecosystem URIs ---
AMPLIFIER_START_URI = "git+https://github.com/payneio/amplifier-start@main"
FOUNDATION_GIT_URI = "git+https://github.com/microsoft/amplifier-foundation@main"


def provider_bundle_uri(provider: Provider) -> str:
    """Build the full git URI for a provider's foundation sub-bundle."""
    # Convert "foundation:providers/anthropic-sonnet" to full git URI
    # so it can be included in the overlay without namespace timing issues
    _, path = provider.include.split(":", 1)
    return f"{FOUNDATION_GIT_URI}#subdirectory={path}.yaml"


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        id="anthropic",
        name="Anthropic",
        description="Claude models (Sonnet, Opus, Haiku)",
        include="foundation:providers/anthropic-sonnet",
        key_prefix="sk-ant-",
        env_var="ANTHROPIC_API_KEY",
        default_model="claude-sonnet-4-5",
        module_id="provider-anthropic",
        source_url="git+https://github.com/microsoft/amplifier-module-provider-anthropic@main",
        console_url="https://console.anthropic.com/settings/keys",
        fallback_models=(
            "claude-opus-4-5",
            "claude-sonnet-4-5",
            "claude-3-5-sonnet-20241022",
        ),
    ),
    "openai": Provider(
        id="openai",
        name="OpenAI",
        description="GPT models (GPT-4o, o3, Codex)",
        include="foundation:providers/openai-gpt",
        key_prefix="sk-",
        env_var="OPENAI_API_KEY",
        default_model="gpt-4o",
        module_id="provider-openai",
        source_url="git+https://github.com/microsoft/amplifier-module-provider-openai@main",
        console_url="https://platform.openai.com/api-keys",
        fallback_models=("gpt-4o", "gpt-4o-mini", "o1", "o3-mini"),
    ),
    "google": Provider(
        id="google",
        name="Google",
        description="Gemini models (Pro, Flash)",
        include="foundation:providers/gemini-pro",
        key_prefix="AI",
        env_var="GOOGLE_API_KEY",
        default_model="gemini-2.5-pro",
        module_id="provider-gemini",
        source_url="git+https://github.com/microsoft/amplifier-module-provider-gemini@main",
        console_url="https://aistudio.google.com/apikey",
        fallback_models=("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"),
    ),
    "xai": Provider(
        id="xai",
        name="xAI",
        description="Grok models via xAI API",
        include="foundation:providers/openai-gpt",
        key_prefix="xai-",
        env_var="XAI_API_KEY",
        default_model="grok-3",
        module_id="provider-openai",
        console_url="https://console.x.ai/",
        fallback_models=("grok-4", "grok-3", "grok-3-mini"),
        base_url="https://api.x.ai/v1",
        api_key_config="api_key",
    ),
    "ollama": Provider(
        id="ollama",
        name="Ollama",
        description="Local models via Ollama",
        include="foundation:providers/ollama",
        key_prefix="",
        env_var="OLLAMA_HOST",
        default_model="llama3.1",
        module_id="provider-ollama",
        source_url="git+https://github.com/microsoft/amplifier-module-provider-ollama@main",
        console_url="https://ollama.com/",
        fallback_models=("llama3.1", "mistral", "codellama"),
    ),
    "azure": Provider(
        id="azure",
        name="Azure OpenAI",
        description="OpenAI models via Azure",
        include="foundation:providers/azure-openai",
        key_prefix="",
        env_var="AZURE_OPENAI_API_KEY",
        default_model="gpt-4o",
        module_id="provider-azure-openai",
        source_url="git+https://github.com/microsoft/amplifier-module-provider-azure-openai@main",
        console_url="https://portal.azure.com/",
        fallback_models=("gpt-4o", "gpt-4o-mini"),
    ),
}


FEATURES: dict[str, Feature] = {
    "dev-memory": Feature(
        id="dev-memory",
        name="Persistent Memory",
        description="Remember context, decisions, and preferences across sessions",
        tier=1,
        includes=[
            "git+https://github.com/ramparte/amplifier-collection-dev-memory@main"
            "#subdirectory=behaviors/dev-memory.yaml"
        ],
        category="memory",
    ),
    "deliberate-dev": Feature(
        id="deliberate-dev",
        name="Planning Mode",
        description="Deliberate planner, implementer, reviewer, and debugger agents",
        tier=1,
        includes=[
            "git+https://github.com/ramparte/amplifier-bundle-deliberate-development@main"
        ],
        category="planning",
    ),
    "agent-memory": Feature(
        id="agent-memory",
        name="Vector Search Memory",
        description="Semantic search across past sessions and conversations",
        tier=2,
        includes=["git+https://github.com/ramparte/amplifier-bundle-agent-memory@main"],
        category="search",
        requires=["dev-memory"],
    ),
    "recipes": Feature(
        id="recipes",
        name="Recipes",
        description="Multi-step workflow orchestration with approval gates",
        tier=2,
        includes=["git+https://github.com/microsoft/amplifier-bundle-recipes@main"],
        category="workflow",
    ),
    "stories": Feature(
        id="stories",
        name="Content Studio",
        description="10 specialist agents for docs, presentations, and communications",
        tier=2,
        includes=["git+https://github.com/microsoft/amplifier-bundle-stories@main"],
        category="content",
    ),
    "session-discovery": Feature(
        id="session-discovery",
        name="Session Discovery",
        description="Index and search past sessions",
        tier=2,
        includes=[
            "git+https://github.com/ramparte/amplifier-toolkit@main"
            "#subdirectory=bundles/session-discovery"
        ],
        category="search",
    ),
    "routines": Feature(
        id="routines",
        name="Routines",
        description="Scheduled AI task execution with natural language management",
        tier=2,
        includes=["git+https://github.com/microsoft/amplifier-bundle-routines@main"],
        category="workflow",
        requires=[],
    ),
}


TIERS: dict[int, list[str]] = {
    0: [],
    1: ["dev-memory", "deliberate-dev"],
    2: ["agent-memory", "recipes", "stories", "session-discovery", "routines"],
}


# Aliases — normalize common variants to canonical names
PROVIDER_ALIASES: dict[str, str] = {
    "gemini": "google",
    "azure-openai": "azure",
}


def resolve_provider(name: str) -> str:
    """Resolve a provider name through aliases to its canonical key."""
    normalized = name.replace("provider-", "")
    return PROVIDER_ALIASES.get(normalized, normalized)


def detect_provider(api_key: str) -> str | None:
    """Detect provider from API key format."""
    if api_key.startswith("sk-ant-"):
        return "anthropic"
    if api_key.startswith("sk-"):
        return "openai"
    if api_key.startswith("AI"):
        return "google"
    if api_key.startswith("xai-"):
        return "xai"
    # Ollama uses a host URL, not an API key — no prefix detection
    return None


def features_for_tier(tier: int) -> list[str]:
    """Return all feature IDs that should be enabled up to a given tier."""
    result: list[str] = []
    for t in range(1, tier + 1):
        result.extend(TIERS.get(t, []))
    return result


# ---------------------------------------------------------------------------
#  Shared provider registration
# ---------------------------------------------------------------------------


@dataclass
class ProviderRegistrationResult:
    """Outcome of a provider registration attempt."""

    provider_id: str
    provider_name: str
    default_model: str
    key_saved: bool = False
    settings_updated: bool = False
    overlay_updated: bool = False
    overlay_error: str = ""

    @property
    def ok(self) -> bool:
        return self.key_saved and self.settings_updated and self.overlay_updated


def register_provider(provider_id: str, api_key: str) -> ProviderRegistrationResult:
    """Register a provider: persist API key, update settings, update overlay.

    This is the single entry point for adding a provider to the distro.
    All three writes are performed in order, with individual error handling
    so partial success is reported clearly.

    Args:
        provider_id: Canonical provider key (e.g. ``"anthropic"``).
        api_key: The raw API key or connection string.

    Returns:
        A ``ProviderRegistrationResult`` describing what succeeded.

    Raises:
        KeyError: If *provider_id* is not in ``PROVIDERS``.
    """
    # Lazy imports to avoid circular dependency
    # (settings imports features; features must not import settings at module level)
    from amplifier_distro import overlay
    from amplifier_distro.server.apps.settings import (
        add_provider_config,
        persist_api_key,
    )

    provider = PROVIDERS[provider_id]
    result = ProviderRegistrationResult(
        provider_id=provider_id,
        provider_name=provider.name,
        default_model=provider.default_model,
    )

    # 1. Write key to keys.env and set in current process env
    persist_api_key(provider_id, api_key)
    result.key_saved = True

    # 2. Add provider module config to settings.yaml
    add_provider_config(provider_id)
    result.settings_updated = True

    # 3. Add provider include to overlay bundle
    try:
        overlay.ensure_overlay(provider)
        result.overlay_updated = True
    except OSError as exc:
        result.overlay_error = str(exc)

    return result
