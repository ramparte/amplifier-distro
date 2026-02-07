"""Config I/O and environment detection for distro.yaml."""

import subprocess
from pathlib import Path

import yaml

from .schema import DistroConfig


def config_path() -> Path:
    """Return the path to ~/.amplifier/distro.yaml, expanded."""
    return Path("~/.amplifier/distro.yaml").expanduser()


def load_config() -> DistroConfig:
    """Load and parse distro.yaml, returning defaults if missing."""
    path = config_path()
    if not path.exists():
        return DistroConfig()

    text = path.read_text()
    data = yaml.safe_load(text)
    if not data:
        return DistroConfig()

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

    Returns "~/dev" as default if it exists, otherwise "~/dev".
    """
    dev = Path("~/dev").expanduser()
    if dev.is_dir():
        return "~/dev"
    return "~/dev"
