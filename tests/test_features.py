"""Feature Catalog Tests

Validates the feature catalog data structures and helper functions
used by the install wizard and bundle composer.

Exit criteria verified:
1. PROVIDERS has anthropic and openai with correct fields
2. FEATURES has all 6 expected entries with required fields
3. detect_provider() correctly identifies key prefixes
4. features_for_tier() returns cumulative feature lists
5. TIERS maps tier numbers to feature ID lists
"""

from amplifier_distro.features import (
    FEATURES,
    PROVIDERS,
    TIERS,
    Feature,
    Provider,
    detect_provider,
    features_for_tier,
)


class TestProviders:
    """Verify PROVIDERS dict has correct entries and structure."""

    def test_has_anthropic(self):
        assert "anthropic" in PROVIDERS

    def test_has_openai(self):
        assert "openai" in PROVIDERS

    def test_anthropic_is_provider_type(self):
        assert isinstance(PROVIDERS["anthropic"], Provider)

    def test_openai_is_provider_type(self):
        assert isinstance(PROVIDERS["openai"], Provider)

    def test_anthropic_fields(self):
        p = PROVIDERS["anthropic"]
        assert p.id == "anthropic"
        assert p.name == "Anthropic"
        assert isinstance(p.description, str) and len(p.description) > 0
        assert p.include == "foundation:providers/anthropic-sonnet"
        assert p.key_prefix == "sk-ant-"
        assert p.env_var == "ANTHROPIC_API_KEY"
        assert p.default_model == "claude-sonnet-4-5"

    def test_openai_fields(self):
        p = PROVIDERS["openai"]
        assert p.id == "openai"
        assert p.name == "OpenAI"
        assert isinstance(p.description, str) and len(p.description) > 0
        assert p.include == "foundation:providers/openai-gpt4o"
        assert p.key_prefix == "sk-"
        assert p.env_var == "OPENAI_API_KEY"
        assert p.default_model == "gpt-4o"

    def test_each_provider_has_all_fields(self):
        required = {
            "id",
            "name",
            "description",
            "include",
            "key_prefix",
            "env_var",
            "default_model",
        }
        for pid, provider in PROVIDERS.items():
            for field_name in required:
                value = getattr(provider, field_name)
                assert isinstance(value, str), (
                    f"Provider {pid}.{field_name} should be str"
                )
                assert len(value) > 0, (
                    f"Provider {pid}.{field_name} should not be empty"
                )


class TestFeatures:
    """Verify FEATURES dict has all expected entries with required fields."""

    EXPECTED_IDS = {
        "dev-memory",
        "deliberate-dev",
        "agent-memory",
        "recipes",
        "stories",
        "session-discovery",
    }

    def test_has_all_expected_features(self):
        assert set(FEATURES.keys()) == self.EXPECTED_IDS

    def test_count_is_six(self):
        assert len(FEATURES) == 6

    def test_each_feature_is_feature_type(self):
        for fid, feature in FEATURES.items():
            assert isinstance(feature, Feature), f"{fid} should be Feature"

    def test_each_feature_has_required_fields(self):
        for fid, feature in FEATURES.items():
            assert isinstance(feature.id, str) and feature.id == fid
            assert isinstance(feature.name, str) and len(feature.name) > 0
            assert isinstance(feature.description, str) and len(feature.description) > 0
            assert isinstance(feature.tier, int) and feature.tier in (1, 2)
            assert isinstance(feature.includes, list) and len(feature.includes) > 0
            assert isinstance(feature.category, str) and len(feature.category) > 0

    def test_agent_memory_requires_dev_memory(self):
        assert "dev-memory" in FEATURES["agent-memory"].requires

    def test_tier_1_features(self):
        tier_1 = [fid for fid, f in FEATURES.items() if f.tier == 1]
        assert set(tier_1) == {"dev-memory", "deliberate-dev"}

    def test_tier_2_features(self):
        tier_2 = [fid for fid, f in FEATURES.items() if f.tier == 2]
        assert set(tier_2) == {
            "agent-memory",
            "recipes",
            "stories",
            "session-discovery",
        }


class TestDetectProvider:
    """Verify detect_provider() identifies key formats correctly."""

    def test_anthropic_key(self):
        assert detect_provider("sk-ant-api03-xxx") == "anthropic"

    def test_openai_key(self):
        assert detect_provider("sk-xxx") == "openai"

    def test_invalid_key_returns_none(self):
        assert detect_provider("invalid") is None

    def test_empty_key_returns_none(self):
        assert detect_provider("") is None

    def test_anthropic_prefix_takes_priority(self):
        """sk-ant- must match anthropic before the generic sk- matches openai."""
        assert detect_provider("sk-ant-something") == "anthropic"


class TestFeaturesForTier:
    """Verify features_for_tier() returns cumulative feature lists."""

    def test_tier_0_returns_empty(self):
        assert features_for_tier(0) == []

    def test_tier_1_returns_two_features(self):
        result = features_for_tier(1)
        assert result == ["dev-memory", "deliberate-dev"]

    def test_tier_2_returns_all_six_features(self):
        result = features_for_tier(2)
        assert len(result) == 6
        assert set(result) == {
            "dev-memory",
            "deliberate-dev",
            "agent-memory",
            "recipes",
            "stories",
            "session-discovery",
        }

    def test_tier_2_includes_tier_1(self):
        """Tier 2 is cumulative - includes tier 1 features."""
        result = features_for_tier(2)
        for fid in features_for_tier(1):
            assert fid in result


class TestTiers:
    """Verify TIERS dict structure."""

    def test_has_keys_0_1_2(self):
        assert set(TIERS.keys()) == {0, 1, 2}

    def test_tier_0_is_empty(self):
        assert TIERS[0] == []

    def test_tier_1_features(self):
        assert TIERS[1] == ["dev-memory", "deliberate-dev"]

    def test_tier_2_features(self):
        assert set(TIERS[2]) == {
            "agent-memory",
            "recipes",
            "stories",
            "session-discovery",
        }
