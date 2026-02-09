"""Bundle Composer Tests

Validates bundle YAML generation, reading, writing, and feature
manipulation used by the install wizard.

Exit criteria verified:
1. generate() produces valid YAML with correct includes
2. write() creates the file on disk
3. read() returns parsed YAML data
4. get_current_includes() extracts include URIs
5. get_enabled_features() identifies enabled features
6. get_current_provider() returns provider ID
7. add_feature() adds includes and handles dependencies
8. remove_feature() removes includes
9. set_tier() adds all features for a tier
10. get_current_tier() returns the correct effective tier
"""

from pathlib import Path

import pytest
import yaml

from amplifier_distro import bundle_composer
from amplifier_distro.features import FEATURES, PROVIDERS


@pytest.fixture(autouse=True)
def isolate_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect bundle operations to a temp directory."""
    test_bundle = tmp_path / "bundles" / "distro.yaml"
    monkeypatch.setattr("amplifier_distro.bundle_composer.BUNDLE_PATH", test_bundle)
    return test_bundle


class TestGenerate:
    """Verify generate() produces valid YAML with correct includes."""

    def test_anthropic_produces_valid_yaml(self):
        result = bundle_composer.generate("anthropic")
        data = yaml.safe_load(result)
        assert isinstance(data, dict)

    def test_anthropic_has_bundle_metadata(self):
        data = yaml.safe_load(bundle_composer.generate("anthropic"))
        assert "bundle" in data
        assert data["bundle"]["name"] == "amplifier-distro"

    def test_anthropic_includes_foundation(self):
        data = yaml.safe_load(bundle_composer.generate("anthropic"))
        includes = [e["bundle"] for e in data["includes"]]
        assert "foundation" in includes

    def test_anthropic_includes_provider(self):
        data = yaml.safe_load(bundle_composer.generate("anthropic"))
        includes = [e["bundle"] for e in data["includes"]]
        assert PROVIDERS["anthropic"].include in includes

    def test_openai_includes_provider(self):
        data = yaml.safe_load(bundle_composer.generate("openai"))
        includes = [e["bundle"] for e in data["includes"]]
        assert PROVIDERS["openai"].include in includes

    def test_with_features(self):
        data = yaml.safe_load(bundle_composer.generate("openai", ["dev-memory"]))
        includes = [e["bundle"] for e in data["includes"]]
        assert "foundation" in includes
        assert PROVIDERS["openai"].include in includes
        for inc in FEATURES["dev-memory"].includes:
            assert inc in includes

    def test_without_features_has_only_foundation_and_provider(self):
        data = yaml.safe_load(bundle_composer.generate("anthropic"))
        assert len(data["includes"]) == 2


class TestWriteAndRead:
    """Verify write() creates files and read() parses them."""

    def test_write_creates_file(self, isolate_bundle: Path):
        path = bundle_composer.write("anthropic")
        assert path.exists()
        assert path == isolate_bundle

    def test_write_creates_parent_dirs(self, isolate_bundle: Path):
        bundle_composer.write("anthropic")
        assert isolate_bundle.parent.exists()

    def test_read_returns_parsed_yaml(self):
        bundle_composer.write("anthropic")
        data = bundle_composer.read()
        assert isinstance(data, dict)
        assert "bundle" in data
        assert "includes" in data

    def test_read_returns_empty_when_no_file(self):
        data = bundle_composer.read()
        assert data == {}


class TestGetCurrentIncludes:
    """Verify get_current_includes() extracts include URIs."""

    def test_extracts_uris(self):
        bundle_composer.write("anthropic")
        includes = bundle_composer.get_current_includes()
        assert "foundation" in includes
        assert PROVIDERS["anthropic"].include in includes

    def test_from_explicit_data(self):
        data = yaml.safe_load(bundle_composer.generate("openai", ["dev-memory"]))
        includes = bundle_composer.get_current_includes(data)
        assert "foundation" in includes
        for inc in FEATURES["dev-memory"].includes:
            assert inc in includes

    def test_empty_data_returns_empty(self):
        includes = bundle_composer.get_current_includes({})
        assert includes == []


class TestGetEnabledFeatures:
    """Verify get_enabled_features() correctly identifies enabled features."""

    def test_no_features_when_tier_0(self):
        bundle_composer.write("anthropic")
        enabled = bundle_composer.get_enabled_features()
        assert enabled == []

    def test_with_features(self):
        bundle_composer.write("anthropic", ["dev-memory", "deliberate-dev"])
        enabled = bundle_composer.get_enabled_features()
        assert "dev-memory" in enabled
        assert "deliberate-dev" in enabled


class TestGetCurrentProvider:
    """Verify get_current_provider() returns the provider ID."""

    def test_anthropic(self):
        bundle_composer.write("anthropic")
        assert bundle_composer.get_current_provider() == "anthropic"

    def test_openai(self):
        bundle_composer.write("openai")
        assert bundle_composer.get_current_provider() == "openai"

    def test_none_when_no_bundle(self):
        assert bundle_composer.get_current_provider() is None


class TestAddFeature:
    """Verify add_feature() adds includes and handles dependencies."""

    def test_adds_feature(self):
        bundle_composer.write("anthropic")
        added = bundle_composer.add_feature("dev-memory")
        assert "dev-memory" in added
        enabled = bundle_composer.get_enabled_features()
        assert "dev-memory" in enabled

    def test_adds_dependencies(self):
        """agent-memory requires dev-memory - both should be added."""
        bundle_composer.write("anthropic")
        added = bundle_composer.add_feature("agent-memory")
        assert "dev-memory" in added
        assert "agent-memory" in added
        enabled = bundle_composer.get_enabled_features()
        assert "dev-memory" in enabled
        assert "agent-memory" in enabled

    def test_no_duplicates_when_dep_already_present(self):
        bundle_composer.write("anthropic", ["dev-memory"])
        bundle_composer.add_feature("agent-memory")
        includes = bundle_composer.get_current_includes()
        # dev-memory include should appear only once
        dm_includes = FEATURES["dev-memory"].includes
        for inc in dm_includes:
            assert includes.count(inc) == 1

    def test_returns_empty_when_no_bundle(self):
        result = bundle_composer.add_feature("dev-memory")
        assert result == []


class TestRemoveFeature:
    """Verify remove_feature() removes includes."""

    def test_removes_feature(self):
        bundle_composer.write("anthropic", ["dev-memory"])
        assert "dev-memory" in bundle_composer.get_enabled_features()
        bundle_composer.remove_feature("dev-memory")
        assert "dev-memory" not in bundle_composer.get_enabled_features()

    def test_preserves_other_features(self):
        bundle_composer.write("anthropic", ["dev-memory", "deliberate-dev"])
        bundle_composer.remove_feature("dev-memory")
        enabled = bundle_composer.get_enabled_features()
        assert "dev-memory" not in enabled
        assert "deliberate-dev" in enabled

    def test_preserves_foundation_and_provider(self):
        bundle_composer.write("anthropic", ["dev-memory"])
        bundle_composer.remove_feature("dev-memory")
        includes = bundle_composer.get_current_includes()
        assert "foundation" in includes
        assert PROVIDERS["anthropic"].include in includes

    def test_noop_when_no_bundle(self):
        # Should not raise
        bundle_composer.remove_feature("dev-memory")


class TestSetTier:
    """Verify set_tier() adds all features for a tier."""

    def test_set_tier_1(self):
        bundle_composer.write("anthropic")
        added = bundle_composer.set_tier(1)
        assert "dev-memory" in added
        assert "deliberate-dev" in added
        enabled = bundle_composer.get_enabled_features()
        assert "dev-memory" in enabled
        assert "deliberate-dev" in enabled

    def test_set_tier_2(self):
        bundle_composer.write("anthropic")
        bundle_composer.set_tier(2)
        enabled = set(bundle_composer.get_enabled_features())
        assert enabled == {
            "dev-memory",
            "deliberate-dev",
            "agent-memory",
            "recipes",
            "stories",
            "session-discovery",
        }

    def test_set_tier_0_adds_nothing(self):
        bundle_composer.write("anthropic")
        added = bundle_composer.set_tier(0)
        assert added == []


class TestGetCurrentTier:
    """Verify get_current_tier() returns the correct effective tier."""

    def test_tier_0_when_no_features(self):
        bundle_composer.write("anthropic")
        assert bundle_composer.get_current_tier() == 0

    def test_tier_1_when_tier_1_features(self):
        bundle_composer.write("anthropic", ["dev-memory", "deliberate-dev"])
        assert bundle_composer.get_current_tier() == 1

    def test_tier_2_when_all_features(self):
        all_features = [
            "dev-memory",
            "deliberate-dev",
            "agent-memory",
            "recipes",
            "stories",
            "session-discovery",
        ]
        bundle_composer.write("anthropic", all_features)
        assert bundle_composer.get_current_tier() == 2

    def test_tier_0_when_no_bundle(self):
        assert bundle_composer.get_current_tier() == 0
