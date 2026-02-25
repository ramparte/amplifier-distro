"""Install Wizard App - Quickstart setup flow.

Handles initial Amplifier setup only. Post-setup configuration
management (features, tiers, provider changes) lives in the
settings app.

Routes:
    GET  /          - Quickstart page (paste API key)
    GET  /wizard    - Full multi-step setup wizard
    GET  /detect    - Auto-detect environment
    POST /quickstart - Fast-path API key setup
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from amplifier_distro import distro_settings, overlay
from amplifier_distro.features import PROVIDERS, detect_provider
from amplifier_distro.server.app import AppManifest
from amplifier_distro.server.apps.settings import (
    add_provider_config,
    detect_bridges,
    persist_api_key,
)

router = APIRouter()

_static_dir = Path(__file__).parent / "static"


# --- Pydantic Models ---


class QuickstartRequest(BaseModel):
    api_key: str
    workspace_root: str = ""
    github_handle: str = ""


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

    # API keys (check env)
    result["api_keys"] = {
        pid: bool(os.environ.get(p.env_var)) for pid, p in PROVIDERS.items()
    }

    # Amplifier CLI
    result["amplifier_cli"] = {"installed": shutil.which("amplifier") is not None}

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

    return result


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

    provider = PROVIDERS[provider_id]

    # Step 1-2: Write key to disk and environment
    persist_api_key(provider_id, req.api_key)

    # Step 3: Add provider config to settings.yaml
    add_provider_config(provider_id)

    # Step 4: Create overlay bundle (includes amplifier-start + provider)
    overlay.ensure_overlay(provider)

    # Step 5: Persist identity and workspace to distro settings
    if req.github_handle:
        distro_settings.update("identity", github_handle=req.github_handle)
    if req.workspace_root:
        distro_settings.update(workspace_root=req.workspace_root)

    return {
        "status": "ready",
        "provider": provider_id,
        "model": provider.default_model,
    }


manifest = AppManifest(
    name="install-wizard",
    description="Quickstart setup for Amplifier",
    version="0.1.0",
    router=router,
)
