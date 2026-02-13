"""Config I/O and environment detection for distro.yaml."""

import logging
import subprocess
from pathlib import Path

import yaml
from pydantic import ValidationError  # noqa: F401 - re-exported for callers

from .conventions import AMPLIFIER_HOME, DISTRO_CONFIG_FILENAME
from .schema import DistroConfig

logger = logging.getLogger(__name__)


def config_path() -> Path:
    """Return the path to distro.yaml, expanded."""
    return Path(AMPLIFIER_HOME).expanduser() / DISTRO_CONFIG_FILENAME


def load_config() -> DistroConfig:
    """Load and parse distro.yaml, returning defaults if missing.

    Raises ValidationError if the file contains invalid values.
    Callers should catch and handle appropriately for their context.
    """
    path = config_path()
    if not path.exists():
        return DistroConfig()

    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed YAML in {path}: {exc}") from exc

    if not data:
        return DistroConfig()

    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a YAML mapping in {path}, got {type(data).__name__}"
        )

    return DistroConfig(**data)


def save_config(config: DistroConfig) -> None:
    """Write config to ~/.amplifier/distro.yaml."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump()
    text = yaml.dump(data, default_flow_style=False, sort_keys=False)
    path.write_text(text)


def detect_github_identity() -> tuple[str, str]:
    """Detect GitHub handle and email via gh CLI.

    Returns:
        Tuple of (handle, email). Either may be "" if detection fails.
    """
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        handle = result.stdout.strip() if result.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        handle = ""

    try:
        result2 = subprocess.run(
            ["gh", "api", "user", "--jq", ".email // empty"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        email = result2.stdout.strip() if result2.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        email = ""

    return handle, email


def detect_workspace_root() -> str:
    """Detect a reasonable workspace root directory.

    Checks common development directory names and returns the first
    that exists. Falls back to "~/dev" as the convention default.
    """
    candidates = [
        "~/dev",
        "~/Development",
        "~/projects",
        "~/src",
        "~/code",
        "~/workspace",
    ]
    for candidate in candidates:
        if Path(candidate).expanduser().is_dir():
            return candidate
    return "~/dev"
