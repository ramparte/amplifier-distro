"""Config I/O and environment detection for distro.yaml."""

import logging
import subprocess
from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import DistroConfig

logger = logging.getLogger(__name__)


def config_path() -> Path:
    """Return the path to ~/.amplifier/distro.yaml, expanded."""
    return Path("~/.amplifier/distro.yaml").expanduser()


def load_config() -> DistroConfig:
    """Load and parse distro.yaml, returning defaults if missing or invalid.

    If the file contains invalid values (e.g. workspace_root is not a path),
    logs a warning and returns defaults so the server can still start.
    """
    path = config_path()
    if not path.exists():
        return DistroConfig()

    text = path.read_text()
    data = yaml.safe_load(text)
    if not data:
        return DistroConfig()

    try:
        return DistroConfig(**data)
    except ValidationError as exc:
        logger.warning(
            "Invalid distro.yaml at %s: %s. Using defaults. "
            "Re-run 'amp-distro init' to fix.",
            path,
            exc,
        )
        return DistroConfig()


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
