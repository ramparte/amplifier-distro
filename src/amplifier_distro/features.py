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


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        id="anthropic",
        name="Anthropic",
        description="Claude models (Sonnet, Opus, Haiku)",
        include="foundation:providers/anthropic-sonnet",
        key_prefix="sk-ant-",
        env_var="ANTHROPIC_API_KEY",
        default_model="claude-sonnet-4-5",
    ),
    "openai": Provider(
        id="openai",
        name="OpenAI",
        description="GPT models (GPT-4o, o3, Codex)",
        include="foundation:providers/openai-gpt",
        key_prefix="sk-",
        env_var="OPENAI_API_KEY",
        default_model="gpt-4o",
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
}


TIERS: dict[int, list[str]] = {
    0: [],
    1: ["dev-memory", "deliberate-dev"],
    2: ["agent-memory", "recipes", "stories", "session-discovery"],
}


def detect_provider(api_key: str) -> str | None:
    """Detect provider from API key format."""
    if api_key.startswith("sk-ant-"):
        return "anthropic"
    if api_key.startswith("sk-"):
        return "openai"
    return None


def features_for_tier(tier: int) -> list[str]:
    """Return all feature IDs that should be enabled up to a given tier."""
    result: list[str] = []
    for t in range(1, tier + 1):
        result.extend(TIERS.get(t, []))
    return result
