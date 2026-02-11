"""Update check for amplifier-distro.

Checks PyPI for newer versions, caches results to avoid repeated network
calls, and provides helpers for displaying update notices in the CLI.
All paths come from conventions.py.
"""

from __future__ import annotations

import contextlib
import json
import logging
import platform
import shutil
import subprocess
import time
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path

from pydantic import BaseModel

from . import conventions

logger = logging.getLogger(__name__)


class UpdateInfo(BaseModel):
    """Information about an available update."""

    current_version: str
    latest_version: str
    release_url: str
    release_notes_url: str


class VersionInfo(BaseModel):
    """Comprehensive version and environment information."""

    distro_version: str
    amplifier_version: str | None = None
    python_version: str
    platform: str
    install_method: str


def _cache_path() -> Path:
    """Return the path to the update-check cache file.

    Uses conventions.AMPLIFIER_HOME / conventions.CACHE_DIR /
    conventions.UPDATE_CHECK_CACHE_FILENAME.
    """
    return (
        Path(conventions.AMPLIFIER_HOME).expanduser()
        / conventions.CACHE_DIR
        / conventions.UPDATE_CHECK_CACHE_FILENAME
    )


def _get_distro_version() -> str:
    """Get the installed amplifier-distro version from package metadata."""
    try:
        return pkg_version(conventions.PYPI_PACKAGE_NAME)
    except PackageNotFoundError:
        return "0.0.0"


def _get_amplifier_version() -> str | None:
    """Get the installed amplifier version, if available.

    Tries package metadata first, then falls back to `amplifier --version`.
    Returns None if amplifier is not installed.
    """
    # Try package metadata first
    try:
        return pkg_version("amplifier")
    except PackageNotFoundError:
        pass

    # Try amplifier-core
    try:
        return pkg_version("amplifier-core")
    except PackageNotFoundError:
        pass

    # Try CLI fallback
    amp_path = shutil.which("amplifier")
    if amp_path:
        try:
            result = subprocess.run(
                ["amplifier", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Parse "amplifier X.Y.Z" or just "X.Y.Z"
                output = result.stdout.strip()
                parts = output.split()
                return parts[-1] if parts else output
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    return None


def _detect_install_method() -> str:
    """Detect how amplifier-distro was installed.

    Checks for uv, pipx, or pip in the Python executable path and
    environment.
    """
    import sys

    exe = sys.executable or ""

    if "uv" in exe or shutil.which("uv"):
        return "uv"
    if "pipx" in exe or shutil.which("pipx"):
        return "pipx"
    return "pip"


def get_version_info() -> VersionInfo:
    """Gather comprehensive version and environment information."""
    return VersionInfo(
        distro_version=_get_distro_version(),
        amplifier_version=_get_amplifier_version(),
        python_version=platform.python_version(),
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
        install_method=_detect_install_method(),
    )


def _read_cache() -> dict | None:
    """Read the cached update-check result, if fresh.

    Returns the cached data dict if the cache exists and is less than
    UPDATE_CHECK_TTL_HOURS old.  Returns None otherwise.
    """
    path = _cache_path()
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())
        checked_at = data.get("checked_at", 0)
        age_hours = (time.time() - checked_at) / 3600
        if age_hours < conventions.UPDATE_CHECK_TTL_HOURS:
            return data
    except (json.JSONDecodeError, OSError, KeyError):
        pass

    return None


def _write_cache(data: dict) -> None:
    """Write update-check result to the cache file."""
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    except OSError:
        pass  # Non-critical: cache write failure is silent


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a version string like '0.1.0' into a comparable tuple."""
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def check_for_updates() -> UpdateInfo | None:
    """Check if a newer version of amplifier-distro is available.

    Checks PyPI for the latest release.  Results are cached for
    UPDATE_CHECK_TTL_HOURS (from conventions.py) to avoid repeated
    network calls.

    Returns None if:
    - Already up to date
    - Cache says we checked recently and were up to date
    - Network is unavailable or request times out (3s)
    - Any error occurs (non-blocking by design)
    """
    # Check cache first
    cached = _read_cache()
    if cached is not None:
        if cached.get("update_available"):
            return UpdateInfo(**cached["update_info"])
        return None  # Cached as up-to-date

    current = _get_distro_version()

    try:
        import httpx

        resp = httpx.get(
            f"https://pypi.org/pypi/{conventions.PYPI_PACKAGE_NAME}/json",
            timeout=3.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()
        latest = data["info"]["version"]
    except Exception:  # noqa: BLE001
        logger.debug("Could not check PyPI for updates", exc_info=True)
        return None

    update_available = _parse_version(latest) > _parse_version(current)

    if update_available:
        info = UpdateInfo(
            current_version=current,
            latest_version=latest,
            release_url=f"https://pypi.org/project/{conventions.PYPI_PACKAGE_NAME}/{latest}/",
            release_notes_url=f"https://github.com/{conventions.GITHUB_REPO}/releases/tag/v{latest}",
        )
        _write_cache(
            {
                "checked_at": time.time(),
                "update_available": True,
                "update_info": info.model_dump(),
            }
        )
        return info
    else:
        _write_cache(
            {
                "checked_at": time.time(),
                "update_available": False,
            }
        )
        return None


def run_self_update() -> tuple[bool, str]:
    """Self-update amplifier-distro using the detected install method.

    Returns (success, message) tuple.
    """
    method = _detect_install_method()
    package = conventions.PYPI_PACKAGE_NAME

    if method == "uv":
        cmd = ["uv", "pip", "install", "--upgrade", package]
    elif method == "pipx":
        cmd = ["pipx", "upgrade", package]
    else:
        import sys

        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", package]

    old_version = _get_distro_version()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return False, f"Update command failed: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, "Update timed out after 120 seconds."
    except FileNotFoundError:
        return False, f"Install tool '{method}' not found. Install it or use pip."
    except OSError as e:
        return False, f"Update failed: {e}"

    # Verify the update by re-reading metadata
    # Note: in the same process, importlib.metadata may be cached,
    # so we check via subprocess
    try:
        verify = subprocess.run(
            ["amp-distro", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        new_version = (
            verify.stdout.strip().split()[-1] if verify.returncode == 0 else "unknown"
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        new_version = "unknown"

    if new_version != old_version and new_version != "unknown":
        # Clear the update cache since we just updated
        with contextlib.suppress(OSError):
            _cache_path().unlink(missing_ok=True)
        return True, f"Updated {old_version} -> {new_version} (via {method})."
    elif new_version == old_version:
        return True, f"Already at latest version ({old_version})."
    else:
        return (
            True,
            f"Update command succeeded (via {method}). Restart to use new version.",
        )
