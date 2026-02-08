"""Install Wizard App - First-run setup flow.

Guides new users through Amplifier setup:
1. Welcome + workspace setup (choose dev folder)
2. Configuration (paths, preferences)
3. Module selection (add/remove amplifier modules)
4. Interface installation (CLI, GUI)
5. Network setup (Tailscale, if applicable)
6. Provider setup (API keys, model selection)
7. Verification (hello world test)

The wizard maintains state in memory during the setup flow
and writes results to distro.yaml when complete.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from amplifier_distro.server.app import AppManifest

router = APIRouter()


# --- Wizard State ---


class WizardState(BaseModel):
    """Current state of the install wizard."""

    current_step: int = 0
    completed_steps: list[str] = []
    workspace_root: str = ""
    github_handle: str = ""
    git_email: str = ""
    selected_modules: list[str] = []
    installed_interfaces: list[str] = []
    tailscale_enabled: bool = False
    tailscale_hostname: str = ""
    provider: str = ""
    provider_key_set: bool = False
    setup_complete: bool = False


# In-memory state (single-user wizard)
_wizard_state = WizardState()


WIZARD_STEPS = [
    {"id": "welcome", "name": "Welcome", "description": "Welcome and workspace setup"},
    {"id": "config", "name": "Configuration", "description": "Paths and preferences"},
    {"id": "modules", "name": "Modules", "description": "Select amplifier modules"},
    {"id": "interfaces", "name": "Interfaces", "description": "Install CLI and GUI"},
    {"id": "network", "name": "Network", "description": "Tailscale setup (optional)"},
    {
        "id": "provider",
        "name": "Provider",
        "description": "API keys and model selection",
    },
    {"id": "verify", "name": "Verify", "description": "Hello world test"},
]


# --- Request Models ---


class WorkspaceSetup(BaseModel):
    workspace_root: str
    github_handle: str = ""
    git_email: str = ""


class ModuleSelection(BaseModel):
    modules: list[str]


class InterfaceSelection(BaseModel):
    interfaces: list[str]  # e.g., ["cli", "gui"]


class NetworkSetup(BaseModel):
    tailscale_enabled: bool = False
    tailscale_hostname: str = ""


class ProviderSetup(BaseModel):
    provider: str  # "anthropic" or "openai"
    api_key: str


class ConfigUpdate(BaseModel):
    """Generic config updates for step 2."""

    updates: dict[str, Any]


# --- Available Modules ---

AVAILABLE_MODULES = [
    {
        "id": "provider-anthropic",
        "name": "Anthropic Provider",
        "description": "Claude models (Sonnet, Haiku, Opus)",
        "category": "provider",
        "default": True,
        "repo": "microsoft/amplifier-module-provider-anthropic",
    },
    {
        "id": "provider-openai",
        "name": "OpenAI Provider",
        "description": "GPT-4, GPT-4o models",
        "category": "provider",
        "default": True,
        "repo": "microsoft/amplifier-module-provider-openai",
    },
    {
        "id": "provider-azure",
        "name": "Azure OpenAI Provider",
        "description": "Azure-hosted OpenAI models",
        "category": "provider",
        "default": False,
        "repo": "microsoft/amplifier-module-provider-azure-openai",
    },
    {
        "id": "tool-bash",
        "name": "Bash Tool",
        "description": "Shell command execution",
        "category": "tool",
        "default": True,
        "repo": "microsoft/amplifier-module-tool-bash",
    },
    {
        "id": "tool-filesystem",
        "name": "Filesystem Tool",
        "description": "File read/write/edit operations",
        "category": "tool",
        "default": True,
        "repo": "microsoft/amplifier-module-tool-filesystem",
    },
    {
        "id": "tool-web",
        "name": "Web Tool",
        "description": "Web search and fetch",
        "category": "tool",
        "default": True,
        "repo": "microsoft/amplifier-module-tool-web",
    },
    {
        "id": "tool-task",
        "name": "Task/Agent Delegation",
        "description": "Spawn sub-agents for specialized tasks",
        "category": "tool",
        "default": True,
        "repo": "microsoft/amplifier-module-tool-task",
    },
    {
        "id": "tool-recipes",
        "name": "Recipes",
        "description": "Multi-step workflow orchestration",
        "category": "tool",
        "default": True,
        "repo": "microsoft/amplifier-bundle-recipes",
    },
    {
        "id": "tool-skills",
        "name": "Skills",
        "description": "Domain knowledge packages",
        "category": "tool",
        "default": False,
        "repo": "microsoft/amplifier-module-tool-skills",
    },
    {
        "id": "bundle-foundation",
        "name": "Foundation Agents",
        "description": "16+ specialized agents (explorer, architect, builder, etc.)",
        "category": "bundle",
        "default": True,
        "repo": "microsoft/amplifier-foundation",
    },
    {
        "id": "bundle-dev-memory",
        "name": "Developer Memory",
        "description": "Persistent memory across sessions",
        "category": "bundle",
        "default": True,
        "repo": "community/amplifier-collection-dev-memory",
    },
    {
        "id": "bundle-team-tracking",
        "name": "Team Tracking",
        "description": "Session sync and team dashboards",
        "category": "bundle",
        "default": False,
        "repo": "marklicata/amplifier-bundle-team-tracking",
    },
    {
        "id": "bundle-python-dev",
        "name": "Python Development",
        "description": "Python code quality, linting, type checking",
        "category": "bundle",
        "default": False,
        "repo": "microsoft/amplifier-bundle-python-dev",
    },
    {
        "id": "bundle-lsp",
        "name": "LSP Code Intelligence",
        "description": "Language Server Protocol for code navigation",
        "category": "bundle",
        "default": False,
        "repo": "microsoft/amplifier-bundle-lsp",
    },
]


# --- Routes ---


@router.get("/")
async def index() -> dict[str, Any]:
    """Wizard status and current step."""
    return {
        "app": "install-wizard",
        "setup_complete": _wizard_state.setup_complete,
        "current_step": _wizard_state.current_step,
        "total_steps": len(WIZARD_STEPS),
        "steps": WIZARD_STEPS,
    }


@router.get("/state")
async def get_state() -> dict[str, Any]:
    """Get full wizard state."""
    return _wizard_state.model_dump()


@router.get("/steps")
async def get_steps() -> list[dict[str, Any]]:
    """Get all wizard steps with completion status."""
    return [
        {
            **step,
            "completed": step["id"] in _wizard_state.completed_steps,
            "current": i == _wizard_state.current_step,
        }
        for i, step in enumerate(WIZARD_STEPS)
    ]


@router.get("/modules")
async def get_modules() -> dict[str, Any]:
    """Get available modules for selection."""
    return {
        "modules": AVAILABLE_MODULES,
        "selected": _wizard_state.selected_modules,
    }


@router.get("/detect")
async def detect_environment() -> dict[str, Any]:
    """Auto-detect environment settings.

    Detects: GitHub handle, git email, existing workspace,
    installed tools, Tailscale status.
    """
    detections: dict[str, Any] = {}

    # GitHub handle
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            detections["github_handle"] = result.stdout.strip()
        else:
            detections["github_handle"] = None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        detections["github_handle"] = None

    # Git email
    try:
        result = subprocess.run(
            ["git", "config", "--global", "user.email"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            detections["git_email"] = result.stdout.strip()
        else:
            detections["git_email"] = None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        detections["git_email"] = None

    # Existing workspace candidates
    home = Path.home()
    candidates = []
    for name in ["dev", "dev/ANext", "projects", "workspace", "code", "src"]:
        p = home / name
        if p.exists() and p.is_dir():
            candidates.append(str(p))
    detections["workspace_candidates"] = candidates

    # Tools
    detections["tools"] = {}
    for tool in ["gh", "git", "uv", "node", "npm", "tailscale", "amplifier"]:
        detections["tools"][tool] = shutil.which(tool) is not None

    # Tailscale
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            ts = json.loads(result.stdout)
            detections["tailscale"] = {
                "connected": ts.get("BackendState") == "Running",
                "hostname": ts.get("Self", {}).get("HostName", ""),
            }
        else:
            detections["tailscale"] = {"connected": False, "hostname": ""}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        detections["tailscale"] = {"connected": False, "hostname": ""}

    # API keys present
    detections["api_keys"] = {
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
    }

    return detections


# --- Step handlers ---


@router.post("/steps/welcome")
async def step_welcome(setup: WorkspaceSetup) -> dict[str, Any]:
    """Step 1: Workspace setup."""
    workspace = Path(setup.workspace_root).expanduser()

    # Create workspace if it doesn't exist
    workspace.mkdir(parents=True, exist_ok=True)

    _wizard_state.workspace_root = str(workspace)
    _wizard_state.github_handle = setup.github_handle
    _wizard_state.git_email = setup.git_email
    _wizard_state.completed_steps.append("welcome")
    _wizard_state.current_step = 1

    return {"status": "ok", "workspace_created": True, "path": str(workspace)}


@router.post("/steps/config")
async def step_config(config: ConfigUpdate) -> dict[str, Any]:
    """Step 2: Configuration updates."""
    from amplifier_distro.config import load_config, save_config
    from amplifier_distro.schema import DistroConfig

    cfg = load_config()
    cfg_dict = cfg.model_dump()

    for key, value in config.updates.items():
        # Support dotted keys like "cache.max_age_hours"
        parts = key.split(".")
        target = cfg_dict
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value

    # Rebuild and save
    new_cfg = DistroConfig(**cfg_dict)
    save_config(new_cfg)

    _wizard_state.completed_steps.append("config")
    _wizard_state.current_step = 2

    return {"status": "ok", "config_saved": True}


@router.post("/steps/modules")
async def step_modules(selection: ModuleSelection) -> dict[str, Any]:
    """Step 3: Module selection."""
    _wizard_state.selected_modules = selection.modules
    _wizard_state.completed_steps.append("modules")
    _wizard_state.current_step = 3

    return {
        "status": "ok",
        "selected": selection.modules,
        "count": len(selection.modules),
    }


@router.post("/steps/interfaces")
async def step_interfaces(selection: InterfaceSelection) -> dict[str, Any]:
    """Step 4: Interface installation."""
    results: dict[str, Any] = {}

    for interface in selection.interfaces:
        if interface == "cli":
            # CLI is installed if amplifier command exists
            cli_exists = shutil.which("amplifier") is not None
            results["cli"] = {
                "installed": cli_exists,
                "message": "CLI already available"
                if cli_exists
                else "Install with: uv tool install amplifier",
            }
        elif interface == "gui":
            results["gui"] = {
                "installed": True,
                "message": "Web GUI is provided by this server",
            }
        else:
            results[interface] = {
                "installed": False,
                "message": f"Unknown interface: {interface}",
            }

    _wizard_state.installed_interfaces = selection.interfaces
    _wizard_state.completed_steps.append("interfaces")
    _wizard_state.current_step = 4

    return {"status": "ok", "results": results}


@router.post("/steps/network")
async def step_network(setup: NetworkSetup) -> dict[str, Any]:
    """Step 5: Network/Tailscale setup."""
    _wizard_state.tailscale_enabled = setup.tailscale_enabled
    _wizard_state.tailscale_hostname = setup.tailscale_hostname
    _wizard_state.completed_steps.append("network")
    _wizard_state.current_step = 5

    return {
        "status": "ok",
        "tailscale_enabled": setup.tailscale_enabled,
    }


@router.post("/steps/provider")
async def step_provider(setup: ProviderSetup) -> dict[str, Any]:
    """Step 6: Provider and API key setup."""
    # Store API key in environment (for this session)
    if setup.provider == "anthropic":
        os.environ["ANTHROPIC_API_KEY"] = setup.api_key
    elif setup.provider == "openai":
        os.environ["OPENAI_API_KEY"] = setup.api_key

    # Also write to keys.env
    from amplifier_distro.conventions import AMPLIFIER_HOME, KEYS_FILENAME

    keys_path = Path(AMPLIFIER_HOME).expanduser() / KEYS_FILENAME
    keys_path.parent.mkdir(parents=True, exist_ok=True)

    # Append or update
    key_name = (
        "ANTHROPIC_API_KEY" if setup.provider == "anthropic" else "OPENAI_API_KEY"
    )
    lines: list[str] = []
    if keys_path.exists():
        lines = keys_path.read_text().splitlines()

    # Remove existing line for this key
    lines = [line for line in lines if not line.startswith(f"{key_name}=")]
    lines.append(f"{key_name}={setup.api_key}")

    keys_path.write_text("\n".join(lines) + "\n")
    keys_path.chmod(0o600)

    _wizard_state.provider = setup.provider
    _wizard_state.provider_key_set = True
    _wizard_state.completed_steps.append("provider")
    _wizard_state.current_step = 6

    return {"status": "ok", "provider": setup.provider, "key_stored": True}


@router.post("/steps/verify")
async def step_verify() -> dict[str, Any]:
    """Step 7: Verification - run hello world test."""
    from amplifier_distro.config import config_path, load_config, save_config

    results: dict[str, Any] = {"checks": []}

    # Check 1: distro.yaml exists
    results["checks"].append(
        {
            "name": "distro.yaml",
            "passed": config_path().exists(),
        }
    )

    # Check 2: workspace exists
    workspace = Path(_wizard_state.workspace_root)
    results["checks"].append(
        {
            "name": "workspace",
            "passed": workspace.exists(),
        }
    )

    # Check 3: API key is set
    has_key = bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
    )
    results["checks"].append(
        {
            "name": "api_key",
            "passed": has_key,
        }
    )

    # Check 4: amplifier CLI available
    results["checks"].append(
        {
            "name": "amplifier_cli",
            "passed": shutil.which("amplifier") is not None,
        }
    )

    all_passed = all(c["passed"] for c in results["checks"])
    results["all_passed"] = all_passed

    if all_passed:
        _wizard_state.setup_complete = True
        _wizard_state.completed_steps.append("verify")
        _wizard_state.current_step = 7

        # Write final distro.yaml
        cfg = load_config()
        cfg.workspace_root = _wizard_state.workspace_root
        cfg.identity.github_handle = _wizard_state.github_handle
        cfg.identity.git_email = _wizard_state.git_email
        save_config(cfg)

    return results


@router.post("/reset")
async def reset_wizard() -> dict[str, str]:
    """Reset wizard state (start over)."""
    global _wizard_state
    _wizard_state = WizardState()
    return {"status": "ok", "message": "Wizard state reset"}


manifest = AppManifest(
    name="install-wizard",
    description="First-run setup wizard for Amplifier",
    version="0.1.0",
    router=router,
)
