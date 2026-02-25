"""Install Wizard App - Quickstart setup flow.

Handles initial Amplifier setup only. Post-setup configuration
management (features, tiers, provider changes) lives in the
settings app.

Routes:
    GET  /             - Quickstart page (paste API key)
    GET  /wizard       - Full multi-step setup wizard
    GET  /detect       - Auto-detect environment
    GET  /modules      - Feature/module catalog
    GET  /providers    - Provider catalog with config status
    POST /quickstart   - Fast-path API key setup
    POST /steps/welcome   - Save identity + workspace
    POST /steps/config    - Save cache/preflight
    POST /steps/modules   - Toggle features in overlay
    POST /steps/interfaces - CLI install status
    POST /steps/network   - Save network config
    POST /steps/provider  - Save API key + provider
    POST /steps/verify    - Final verification
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from amplifier_distro import distro_settings, overlay
from amplifier_distro.features import (
    FEATURES,
    PROVIDERS,
    detect_provider,
    register_provider,
)
from amplifier_distro.server.app import AppManifest
from amplifier_distro.server.apps.settings import (
    _get_enabled_features,
    detect_bridges,
)

router = APIRouter()
steps_router = APIRouter(prefix="/steps")

_static_dir = Path(__file__).parent / "static"


# --- Pydantic Models ---


class QuickstartRequest(BaseModel):
    api_key: str
    workspace_root: str = ""
    github_handle: str = ""


class WelcomeData(BaseModel):
    workspace_root: str = ""
    github_handle: str = ""
    git_email: str = ""


class ModulesData(BaseModel):
    modules: list[str] = []


class ProviderData(BaseModel):
    provider: str = ""
    api_key: str = ""


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


# --- API Routes ---


@router.get("/detect")
async def detect_environment() -> dict[str, Any]:
    """Auto-detect environment: GitHub, git, Tailscale, API keys, CLI, bundles.

    Returns both nested objects (backward compat) and flat convenience
    fields that the wizard JS reads directly.
    """
    from amplifier_distro.server.stub import is_stub_mode, stub_detect_environment

    if is_stub_mode():
        return stub_detect_environment()

    result: dict[str, Any] = {}

    # Load existing distro settings for pre-fill
    settings = distro_settings.load()

    # GitHub
    gh_handle: str | None = None
    try:
        proc = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            gh_handle = proc.stdout.strip()
            result["github"] = {"handle": gh_handle, "configured": True}
        else:
            result["github"] = {"handle": None, "configured": False}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        result["github"] = {"handle": None, "configured": False}

    # Git
    git_installed = shutil.which("git") is not None
    git_configured = False
    git_email: str | None = None
    if git_installed:
        try:
            proc = subprocess.run(
                ["git", "config", "--global", "user.email"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                git_configured = True
                git_email = proc.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    result["git"] = {
        "installed": git_installed,
        "configured": git_configured,
        "email": git_email,
    }

    # Tailscale
    ts_installed = shutil.which("tailscale") is not None
    ts_ip: str | None = None
    ts_hostname: str | None = None
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
                # Extract hostname - prefer DNSName, fall back to HostName
                dns_name = ts_self.get("DNSName", "")
                if dns_name:
                    # DNSName has trailing dot, strip it
                    ts_hostname = dns_name.rstrip(".")
                else:
                    ts_hostname = ts_self.get("HostName") or None
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
    result["tailscale"] = {
        "installed": ts_installed,
        "ip": ts_ip,
        "hostname": ts_hostname,
    }

    # API keys (check env)
    result["api_keys"] = {
        pid: bool(os.environ.get(p.env_var)) for pid, p in PROVIDERS.items()
    }

    # Amplifier CLI
    cli_installed = shutil.which("amplifier") is not None
    result["amplifier_cli"] = {"installed": cli_installed}

    # Overlay bundle
    result["overlay_bundle"] = overlay.read_overlay() or None

    # Workspace candidates
    home = Path.home()
    candidates = []
    for name in ["dev", "dev/ANext", "projects", "workspace", "code", "src"]:
        p = home / name
        if p.exists() and p.is_dir():
            candidates.append(f"~/{name}")
    result["workspace_candidates"] = candidates

    # Bridges (Slack, Voice)
    result["bridges"] = detect_bridges()

    # --- Flat convenience fields (settings win, then detection, then None) ---

    # workspace_root: settings > first candidate > ""
    result["workspace_root"] = (
        settings.workspace_root
        if settings.workspace_root and settings.workspace_root != "~"
        else (candidates[0] if candidates else "")
    )

    # github_handle: settings > gh CLI detection
    result["github_handle"] = settings.identity.github_handle or gh_handle or ""

    # git_email: settings > git config detection
    result["git_email"] = settings.identity.git_email or git_email or ""

    # Active provider: which provider has a key in env
    result["provider"] = None
    for pid, p in PROVIDERS.items():
        if os.environ.get(p.env_var):
            result["provider"] = pid
            break

    # has_api_key: any provider key present
    result["has_api_key"] = any(
        bool(os.environ.get(p.env_var)) for p in PROVIDERS.values()
    )

    # cli_installed flat alias
    result["cli_installed"] = cli_installed

    # tailscale_hostname flat alias
    result["tailscale_hostname"] = ts_hostname

    return result


@router.get("/modules")
async def get_modules() -> dict[str, Any]:
    """Return the feature/module catalog with current enabled state."""
    currently_enabled = set(_get_enabled_features())

    modules = [
        {
            "id": fid,
            "name": feature.name,
            "description": feature.description,
            "tier": feature.tier,
            "category": feature.category,
            "default": feature.tier <= 1,
            "enabled": fid in currently_enabled,
            "requires": feature.requires,
        }
        for fid, feature in FEATURES.items()
    ]

    return {"modules": modules}


@router.get("/providers")
async def get_providers() -> dict[str, Any]:
    """Return all supported providers with their current configuration status."""
    providers = [
        {
            "id": pid,
            "name": p.name,
            "description": p.description,
            "console_url": p.console_url,
            "key_prefix": p.key_prefix,
            "configured": bool(os.environ.get(p.env_var)),
        }
        for pid, p in PROVIDERS.items()
    ]
    return {"providers": providers}


@router.post("/quickstart")
async def quickstart(req: QuickstartRequest) -> dict[str, Any]:
    """Fast path: paste one API key, get a working setup.

    1. Detect provider from key prefix
    2. Write key to keys.env (chmod 600)
    3. Add provider config to settings.yaml (additive)
    4. Create local overlay bundle (includes amplifier-start + provider)
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

    reg = register_provider(provider_id, req.api_key)

    # Persist identity and workspace to distro settings
    if req.github_handle:
        distro_settings.update("identity", github_handle=req.github_handle)
    if req.workspace_root:
        distro_settings.update(workspace_root=req.workspace_root)

    return {
        "status": "ready",
        "provider": reg.provider_id,
        "model": reg.default_model,
    }


# --- Step Handlers ---


@steps_router.post("/welcome")
async def step_welcome(req: WelcomeData) -> dict[str, Any]:
    """Save identity + workspace root from the welcome step."""
    if req.workspace_root:
        distro_settings.update(workspace_root=req.workspace_root)
    if req.github_handle or req.git_email:
        kwargs: dict[str, str] = {}
        if req.github_handle:
            kwargs["github_handle"] = req.github_handle
        if req.git_email:
            kwargs["git_email"] = req.git_email
        distro_settings.update("identity", **kwargs)
    return {"status": "ok"}


@steps_router.post("/config")
async def step_config(request: Request) -> dict[str, Any]:
    """Acknowledge config step (cache/preflight live in foundation settings)."""
    return {"status": "ok"}


@steps_router.post("/modules")
async def step_modules(req: ModulesData) -> dict[str, Any]:
    """Toggle features in the overlay bundle based on selected module IDs."""
    requested = set(req.modules)
    for fid, feature in FEATURES.items():
        if fid in requested:
            # Enable: add dependencies first, then feature includes
            for dep_id in feature.requires:
                dep = FEATURES[dep_id]
                for inc in dep.includes:
                    overlay.add_include(inc)
            for inc in feature.includes:
                overlay.add_include(inc)
        else:
            for inc in feature.includes:
                overlay.remove_include(inc)
    return {"status": "ok", "enabled": req.modules}


@steps_router.post("/interfaces")
async def step_interfaces(request: Request) -> dict[str, Any]:
    """Acknowledge interfaces step (CLI install is a user action)."""
    return {
        "status": "ok",
        "cli_installed": shutil.which("amplifier") is not None,
    }


@steps_router.post("/network")
async def step_network(request: Request) -> dict[str, Any]:
    """Acknowledge network step."""
    return {"status": "ok"}


@steps_router.post("/provider")
async def step_provider(req: ProviderData) -> dict[str, Any]:
    """Save API key and provider configuration."""
    if not req.api_key.strip():
        return {"status": "skipped"}

    provider_id = detect_provider(req.api_key) or req.provider
    if not provider_id or provider_id not in PROVIDERS:
        return {"status": "error", "detail": "Unknown provider or key format"}

    reg = register_provider(provider_id, req.api_key)

    result: dict[str, Any] = {
        "status": "ok",
        "verified": True,
        "provider": reg.provider_id,
        "provider_name": reg.provider_name,
        "model": reg.default_model,
        "overlay_updated": reg.overlay_updated,
    }
    if reg.overlay_error:
        result["overlay_error"] = reg.overlay_error
    return result


@steps_router.post("/verify")
async def step_verify(request: Request) -> dict[str, Any]:
    """Final verification step - check overall readiness."""
    from amplifier_distro.server.apps.settings import compute_phase

    phase = compute_phase()
    settings = distro_settings.load()

    return {
        "status": "ok",
        "phase": phase,
        "ready": phase == "ready",
        "workspace_root": settings.workspace_root,
        "github_handle": settings.identity.github_handle,
        "has_api_key": any(bool(os.environ.get(p.env_var)) for p in PROVIDERS.values()),
        "cli_installed": shutil.which("amplifier") is not None,
        "overlay_exists": overlay.overlay_exists(),
    }


# Wire the steps sub-router into the main router
router.include_router(steps_router)

manifest = AppManifest(
    name="install-wizard",
    description="Quickstart setup for Amplifier",
    version="0.1.0",
    router=router,
)
