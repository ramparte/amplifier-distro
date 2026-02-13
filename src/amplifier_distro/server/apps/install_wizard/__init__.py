"""Install Wizard App - Quickstart setup flow.

Replaces the 7-step wizard with a fast-path approach:
1. Quickstart: paste ONE API key, get a working chat in < 2 minutes
2. Settings panel: incrementally enable features after hello world

Routes:
    GET  /          - Quickstart page (paste API key)
    GET  /wizard    - Full multi-step setup wizard
    GET  /settings  - Post-setup settings panel
    GET  /detect    - Auto-detect environment
    GET  /status    - Current setup state
    POST /quickstart - Fast-path API key setup
    POST /features  - Toggle a feature
    POST /tier      - Set feature tier
    POST /provider  - Change provider
    GET  /bridges   - Bridge status
    GET  /docs      - Documentation pointers
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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
    "email": {
        "name": "Email",
        "description": "Send and receive email through Gmail API",
        "required_keys": [
            "GMAIL_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GMAIL_REFRESH_TOKEN",
        ],
        "optional_keys": ["EMAIL_AGENT_ADDRESS"],
        "setup_url": "/apps/email/setup/status",
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


# --- HTML Pages ---


@router.get("/", response_class=HTMLResponse)
async def quickstart_page() -> HTMLResponse:
    """Serve the quickstart page (fast-path API key entry)."""
    html_file = _static_dir / "quickstart.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text())
    return HTMLResponse(
        content="<h1>Install Wizard</h1><p>quickstart.html not found.</p>",
        status_code=500,
    )


@router.get("/wizard", response_class=HTMLResponse)
async def wizard_page() -> HTMLResponse:
    """Serve the full multi-step setup wizard."""
    html_file = _static_dir / "wizard.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text())
    return HTMLResponse(
        content="<h1>Install Wizard</h1><p>wizard.html not found.</p>",
        status_code=500,
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page() -> HTMLResponse:
    """Serve the settings panel."""
    html_file = _static_dir / "settings.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text())
    return HTMLResponse(
        content="<h1>Settings</h1><p>settings.html not found.</p>",
        status_code=500,
    )


# --- Pydantic Models ---


class QuickstartRequest(BaseModel):
    api_key: str


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


def _persist_api_key(provider_id: str, api_key: str) -> None:
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


def _write_settings(bundle_path: Path) -> None:
    """Write ~/.amplifier/settings.yaml pointing to the generated bundle."""
    settings = {
        "bundle": {
            "active": bundle_composer.BUNDLE_NAME,
            "added": [str(bundle_path)],
        }
    }
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(settings, default_flow_style=False, sort_keys=False))


def _write_distro_config() -> None:
    """Write ~/.amplifier/distro.yaml with permissive defaults."""
    config = {
        "workspace_root": str(Path.home() / "dev"),
        "cache": {"max_age_hours": 168},
        "identity": {},
    }
    path = _distro_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))


def _load_keys() -> dict[str, str]:
    """Load keys.yaml if it exists, returning an empty dict on failure."""
    keys_path = _keys_path()
    if not keys_path.exists():
        return {}
    try:
        return yaml.safe_load(keys_path.read_text()) or {}
    except yaml.YAMLError:
        return {}


def _detect_bridges() -> dict[str, Any]:
    """Detect configuration status of all known bridges.

    Checks env vars first, then keys.yaml.  Returns a dict keyed by
    bridge id with ``configured``, ``missing``, and metadata fields.
    """
    keys = _load_keys()
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
        "bridges": _detect_bridges(),
    }


# --- Routes ---


@router.get("/detect")
async def detect_environment() -> dict[str, Any]:
    """Auto-detect environment: GitHub, git, Tailscale, API keys, CLI, bundles."""
    from amplifier_distro.server.stub import is_stub_mode, stub_detect_environment

    if is_stub_mode():
        return stub_detect_environment()

    result: dict[str, Any] = {}

    # GitHub
    try:
        proc = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            result["github"] = {"handle": proc.stdout.strip(), "configured": True}
        else:
            result["github"] = {"handle": None, "configured": False}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        result["github"] = {"handle": None, "configured": False}

    # Git
    git_installed = shutil.which("git") is not None
    git_configured = False
    if git_installed:
        try:
            proc = subprocess.run(
                ["git", "config", "--global", "user.email"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            git_configured = proc.returncode == 0 and bool(proc.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    result["git"] = {"installed": git_installed, "configured": git_configured}

    # Tailscale
    ts_installed = shutil.which("tailscale") is not None
    ts_ip: str | None = None
    if ts_installed:
        try:
            proc = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                ts_data = json.loads(proc.stdout)
                ts_self = ts_data.get("Self", {})
                addrs = ts_self.get("TailscaleIPs", [])
                ts_ip = addrs[0] if addrs else None
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
    result["tailscale"] = {"installed": ts_installed, "ip": ts_ip}

    # API keys
    result["api_keys"] = {
        pid: bool(os.environ.get(p.env_var)) for pid, p in PROVIDERS.items()
    }

    # Amplifier CLI
    result["amplifier_cli"] = {"installed": shutil.which("amplifier") is not None}

    # Existing bundle
    bundle_data = bundle_composer.read()
    result["existing_bundle"] = bundle_data if bundle_data else None

    # Workspace candidates
    home = Path.home()
    candidates = []
    for name in ["dev", "dev/ANext", "projects", "workspace", "code", "src"]:
        p = home / name
        if p.exists() and p.is_dir():
            candidates.append(f"~/{name}")
    result["workspace_candidates"] = candidates

    # Bridges (Slack, Email, Voice)
    result["bridges"] = _detect_bridges()

    return result


@router.get("/status")
async def get_status() -> dict[str, Any]:
    """Current setup state (computed from filesystem, never stored)."""
    return _build_status()


@router.post("/quickstart")
async def quickstart(req: QuickstartRequest) -> dict[str, Any]:
    """Fast path: paste one API key, get a working setup.

    1. Detect provider from key prefix
    2. Write keys.env (append/update, chmod 600)
    3. Set os.environ for the key
    4. Generate Tier 0 bundle via bundle_composer.write()
    5. Write settings.yaml
    6. Write distro.yaml with permissive defaults
    """
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

    # Steps 1-3: Write key to disk and environment
    _persist_api_key(provider_id, req.api_key)

    # Step 4: Generate Tier 0 bundle
    bp = bundle_composer.write(provider_id)

    # Step 5: Write settings.yaml
    _write_settings(bp)

    # Step 6: Write distro.yaml
    _write_distro_config()

    return {
        "status": "ready",
        "provider": provider_id,
        "model": provider.default_model,
    }


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
    _persist_api_key(provider_id, req.api_key)

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
    return {"bridges": _detect_bridges()}


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
    name="install-wizard",
    description="Quickstart setup and feature management for Amplifier",
    version="0.1.0",
    router=router,
)
