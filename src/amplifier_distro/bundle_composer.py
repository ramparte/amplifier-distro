"""Generate and modify the distro bundle YAML.

The bundle is a list of includes. This module adds/removes entries.
No templates, no complexity -- just list manipulation on a YAML file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .conventions import AMPLIFIER_HOME, DISTRO_BUNDLE_DIR, DISTRO_BUNDLE_FILENAME
from .features import FEATURES, PROVIDERS, TIERS, features_for_tier

BUNDLE_PATH = (
    Path(AMPLIFIER_HOME).expanduser() / DISTRO_BUNDLE_DIR / DISTRO_BUNDLE_FILENAME
)
BUNDLE_NAME = "amplifier-distro"
BUNDLE_VERSION = "0.1.0"
FOUNDATION_INCLUDE = "foundation"


def bundle_path() -> Path:
    """Return the path to the generated distro bundle."""
    return BUNDLE_PATH


def generate(provider_id: str, feature_ids: list[str] | None = None) -> str:
    """Generate bundle YAML string."""
    provider = PROVIDERS[provider_id]
    includes: list[dict[str, str]] = [
        {"bundle": FOUNDATION_INCLUDE},
        {"bundle": provider.include},
    ]

    for fid in feature_ids or []:
        feature = FEATURES[fid]
        for inc in feature.includes:
            includes.append({"bundle": inc})

    data = {
        "bundle": {
            "name": BUNDLE_NAME,
            "version": BUNDLE_VERSION,
            "description": "Amplifier Distribution",
        },
        "includes": includes,
    }

    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def write(provider_id: str, feature_ids: list[str] | None = None) -> Path:
    """Generate and write the bundle to disk."""
    path = bundle_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = generate(provider_id, feature_ids)
    path.write_text(content)
    return path


def read() -> dict[str, Any]:
    """Read and parse the current bundle."""
    path = bundle_path()
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def get_current_includes(data: dict[str, Any] | None = None) -> list[str]:
    """Extract the list of include URIs from bundle data."""
    if data is None:
        data = read()
    return [
        entry["bundle"] if isinstance(entry, dict) else entry
        for entry in data.get("includes", [])
    ]


def get_enabled_features() -> list[str]:
    """Return IDs of currently enabled features."""
    current = set(get_current_includes())
    enabled = []
    for fid, feature in FEATURES.items():
        if all(inc in current for inc in feature.includes):
            enabled.append(fid)
    return enabled


def get_current_provider() -> str | None:
    """Return the current provider ID, or None."""
    current = set(get_current_includes())
    for pid, provider in PROVIDERS.items():
        if provider.include in current:
            return pid
    return None


def get_current_tier() -> int:
    """Return the current effective tier (highest tier fully satisfied)."""
    enabled = set(get_enabled_features())
    for tier in sorted(TIERS.keys(), reverse=True):
        if tier == 0:
            return 0
        needed = set(features_for_tier(tier))
        if needed.issubset(enabled):
            return tier
    return 0


def add_feature(feature_id: str) -> list[str]:
    """Add a feature to the bundle. Returns list of feature IDs that were added."""
    feature = FEATURES[feature_id]
    data = read()
    if not data:
        return []

    current = get_current_includes(data)
    added: list[str] = []

    # Add dependencies first
    for req_id in feature.requires:
        req = FEATURES[req_id]
        for inc in req.includes:
            if inc not in current:
                data.setdefault("includes", []).append({"bundle": inc})
                current.append(inc)
        added.append(req_id)

    # Add the feature's includes
    for inc in feature.includes:
        if inc not in current:
            data.setdefault("includes", []).append({"bundle": inc})

    added.append(feature_id)

    bundle_path().write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return added


def remove_feature(feature_id: str) -> None:
    """Remove a feature from the bundle."""
    feature = FEATURES[feature_id]
    data = read()
    if not data:
        return

    remove_set = set(feature.includes)
    data["includes"] = [
        entry
        for entry in data.get("includes", [])
        if (entry.get("bundle") if isinstance(entry, dict) else entry) not in remove_set
    ]

    bundle_path().write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def set_tier(tier: int) -> list[str]:
    """Set the bundle to a specific tier. Returns feature IDs added."""
    needed = features_for_tier(tier)
    current = set(get_enabled_features())
    added: list[str] = []
    for fid in needed:
        if fid not in current:
            result = add_feature(fid)
            added.extend(result)
    return list(dict.fromkeys(added))  # deduplicate preserving order
