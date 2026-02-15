"""Settings App - post-setup configuration management.

Provides the settings dashboard and API for managing features,
providers, tiers, and bridges after initial setup is complete.

Routes:
    GET  /          - Settings dashboard page
    GET  /status    - Current setup state (phase, features, provider, bridges)
    POST /features  - Toggle a feature on/off
    POST /tier      - Set feature tier level
    POST /provider  - Change provider (write key + update bundle)
    GET  /bridges   - Bridge configuration status
    GET  /docs      - Documentation pointers
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from amplifier_distro import bundle_composer
from amplifier_distro.conventions import (
    AMPLIFIER_HOME,
    DISTRO_CONFIG_FILENAME,
    KEYS_FILENAME,
    SETTINGS_FILENAME,
)
from amplifier_distro.docs_config import DOC_POINTERS, get_docs_for_category
from amplifier_distro.features import FEATURES, PROVIDERS, detect_provider
from amplifier_distro.server.app import AppManifest

# Bridge env-var / keys.yaml lookups used by _detect_bridges()
_BRIDGE_DEFS: dict[str, dict[str, Any]] = {
    "slack": {
        "name": "Slack",
        "description": "Connect Slack channels to Amplifier sessions",
        "required_keys": ["SLACK_BOT_TOKEN"],
        "optional_keys": ["SLACK_APP_TOKEN"],
        "setup_url": "/apps/slack/setup/status",
    },
    "voice": {
        "name": "Voice",
        "description": "Real-time voice conversations via OpenAI Realtime API",
        "required_keys": ["OPENAI_API_KEY"],
        "optional_keys": [],
        "setup_url": "/apps/voice/",
    },
}

router = APIRouter()

_static_dir = Path(__file__).parent / "static"


# --- Pydantic Models ---


class FeatureToggle(BaseModel):
    feature_id: str
    enabled: bool


class TierRequest(BaseModel):
    tier: int


class ProviderRequest(BaseModel):
    api_key: str


# --- Helpers ---


def _amplifier_home() -> Path:
    return Path(AMPLIFIER_HOME).expanduser()


def _settings_path() -> Path:
    return _amplifier_home() / SETTINGS_FILENAME


def _keys_path() -> Path:
    return _amplifier_home() / KEYS_FILENAME


def _distro_config_path() -> Path:
    return _amplifier_home() / DISTRO_CONFIG_FILENAME


def _has_any_provider_key() -> bool:
    """Check if any provider API key is available in environment."""
    return any(bool(os.environ.get(p.env_var)) for p in PROVIDERS.values())


def compute_phase() -> str:
    """Compute current setup phase from filesystem state.

    Returns:
        "unconfigured" - no settings.yaml OR no provider key available
        "ready"        - has settings.yaml AND at least one provider key
    """
    if not _settings_path().exists():
        return "unconfigured"
    if not _has_any_provider_key():
        return "unconfigured"
    return "ready"


def persist_api_key(provider_id: str, api_key: str) -> None:
    """Write an API key to keys.yaml (merge/update, chmod 600)."""
    provider = PROVIDERS[provider_id]
    keys_path = _keys_path()
    keys_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing keys (or start fresh)
    keys: dict[str, str] = {}
    if keys_path.exists():
        keys = yaml.safe_load(keys_path.read_text()) or {}

    # Set/update the key
    key_name = provider.env_var
    keys[key_name] = api_key

    keys_path.write_text(yaml.dump(keys, default_flow_style=False, sort_keys=False))
    keys_path.chmod(0o600)

    # Also set in current process
    os.environ[key_name] = api_key


def load_keys() -> dict[str, str]:
    """Load keys.yaml if it exists, returning an empty dict on failure."""
    keys_path = _keys_path()
    if not keys_path.exists():
        return {}
    try:
        return yaml.safe_load(keys_path.read_text()) or {}
    except yaml.YAMLError:
        return {}


def detect_bridges() -> dict[str, Any]:
    """Detect configuration status of all known bridges.

    Checks env vars first, then keys.yaml.  Returns a dict keyed by
    bridge id with ``configured``, ``missing``, and metadata fields.
    """
    keys = load_keys()
    bridges: dict[str, Any] = {}

    for bid, defn in _BRIDGE_DEFS.items():
        present: list[str] = []
        missing: list[str] = []
        for k in defn["required_keys"]:
            if os.environ.get(k) or keys.get(k):
                present.append(k)
            else:
                missing.append(k)

        configured = len(missing) == 0
        bridges[bid] = {
            "name": defn["name"],
            "description": defn["description"],
            "configured": configured,
            "missing_keys": missing,
            "setup_url": defn["setup_url"],
        }
    return bridges


def _build_status() -> dict[str, Any]:
    """Build the full status response."""
    phase = compute_phase()
    provider = bundle_composer.get_current_provider()
    tier = bundle_composer.get_current_tier()
    enabled = set(bundle_composer.get_enabled_features())

    features: dict[str, Any] = {}
    for fid, feature in FEATURES.items():
        features[fid] = {
            "enabled": fid in enabled,
            "tier": feature.tier,
            "name": feature.name,
            "description": feature.description,
        }

    return {
        "phase": phase,
        "provider": provider,
        "tier": tier,
        "features": features,
        "bridges": detect_bridges(),
    }


# --- HTML Pages ---


@router.get("/", response_class=HTMLResponse)
async def settings_page() -> HTMLResponse:
    """Serve the settings dashboard."""
    html_file = _static_dir / "settings.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text())
    return HTMLResponse(
        content="<h1>Settings</h1><p>settings.html not found.</p>",
        status_code=500,
    )


# --- API Routes ---


@router.get("/status")
async def get_status() -> dict[str, Any]:
    """Current setup state (computed from filesystem, never stored)."""
    return _build_status()


@router.post("/features")
async def toggle_feature(req: FeatureToggle) -> dict[str, Any]:
    """Toggle a feature on or off."""
    if req.feature_id not in FEATURES:
        raise HTTPException(
            status_code=400, detail=f"Unknown feature: {req.feature_id}"
        )

    if req.enabled:
        bundle_composer.add_feature(req.feature_id)
    else:
        bundle_composer.remove_feature(req.feature_id)

    return _build_status()


@router.post("/tier")
async def set_tier(req: TierRequest) -> dict[str, Any]:
    """Set feature tier level."""
    added = bundle_composer.set_tier(req.tier)
    status = _build_status()
    status["features_added"] = added
    return status


@router.post("/provider")
async def change_provider(req: ProviderRequest) -> dict[str, Any]:
    """Change provider (write key + update bundle's provider include)."""
    if not req.api_key.strip():
        raise HTTPException(status_code=400, detail="API key is required")

    provider_id = detect_provider(req.api_key)
    if provider_id is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unknown API key format."
                " Expected sk-ant-... (Anthropic) or sk-... (OpenAI)"
            ),
        )

    provider = PROVIDERS[provider_id]

    # Write key and set env
    persist_api_key(provider_id, req.api_key)

    # Regenerate bundle with new provider, preserving enabled features
    enabled_features = bundle_composer.get_enabled_features()
    bundle_composer.write(provider_id, enabled_features)

    return {
        "status": "ok",
        "provider": provider_id,
        "model": provider.default_model,
    }


@router.get("/bridges")
async def get_bridges() -> dict[str, Any]:
    """Status of all communication bridges (Slack, Email, Voice)."""
    return {"bridges": detect_bridges()}


@router.get("/docs")
async def get_docs(category: str | None = None) -> dict[str, Any]:
    """Return documentation pointers, optionally filtered by category."""
    if category:
        pointers = get_docs_for_category(category)
    else:
        pointers = list(DOC_POINTERS.values())

    return {
        "docs": [
            {
                "id": dp.id,
                "title": dp.title,
                "url": dp.url,
                "description": dp.description,
                "category": dp.category,
            }
            for dp in pointers
        ]
    }


manifest = AppManifest(
    name="settings",
    description="Settings dashboard and configuration management",
    version="0.1.0",
    router=router,
)
