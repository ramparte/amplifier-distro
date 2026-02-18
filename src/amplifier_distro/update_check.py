"""Update check for amplifier-distro.

SHA-based version comparison for installed packages against GitHub HEAD,
plus self-update helpers for the CLI.
"""

from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path

from pydantic import BaseModel

from . import conventions

logger = logging.getLogger(__name__)


class PackageStatus(BaseModel):
    """Version and commit status for a single package."""

    version: str
    local_sha: str | None = None
    remote_sha: str | None = None
    installed: bool = True

    @property
    def update_available(self) -> bool | None:
        """True if remote is ahead, None if we can't tell."""
        if self.local_sha and self.remote_sha:
            return self.local_sha != self.remote_sha
        return None


class VersionInfo(BaseModel):
    """Comprehensive version and environment information."""

    python_version: str
    platform: str
    install_method: str
    distro: PackageStatus | None = None
    amplifier: PackageStatus | None = None
    tui: PackageStatus | None = None


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


def _get_local_sha(package_name: str) -> str | None:
    """Get the git commit SHA for an installed package.

    For editable installs: runs git rev-parse HEAD in the source dir.
    For tool/venv installs: reads commit_id from direct_url.json.
    For uv tool installs: reads from the tool's isolated site-packages.
    """
    # Try importlib.metadata first (works for packages in our venv)
    sha = _sha_from_metadata(package_name)
    if sha:
        return sha

    # Try uv tool environment (isolated site-packages)
    return _sha_from_uv_tool(package_name)


def _sha_from_metadata(package_name: str) -> str | None:
    """Read SHA from importlib.metadata (current environment)."""
    try:
        from importlib.metadata import distribution

        dist = distribution(package_name)
        text = dist.read_text("direct_url.json")
        if not text:
            return None
        data = json.loads(text)
        # Editable install — use git in the source dir
        if data.get("dir_info", {}).get("editable"):
            url = data.get("url", "")
            if url.startswith("file://"):
                result = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    capture_output=True,
                    text=True,
                    cwd=url[7:],
                    timeout=5,
                )
                if result.returncode == 0:
                    return result.stdout.strip()
        # Git install — read from vcs_info
        commit = data.get("vcs_info", {}).get("commit_id", "")
        if commit:
            return commit[:7]
    except Exception:  # noqa: BLE001
        pass
    return None


def _sha_from_uv_tool(package_name: str) -> str | None:
    """Read SHA from a uv tool's isolated site-packages."""
    import glob

    # uv tools live at ~/.local/share/uv/tools/<tool>/lib/python*/site-packages/
    tools_dir = Path.home() / ".local" / "share" / "uv" / "tools"
    # The tool dir name may differ from the package name
    # (e.g. tool "amplifier" has package "amplifier-app-cli")
    dist_name = package_name.replace("-", "_")
    pattern = str(
        tools_dir / "*" / "lib" / "python*" / "site-packages"
        / f"{dist_name}-*.dist-info" / "direct_url.json"
    )
    for path in glob.glob(pattern):
        try:
            data = json.loads(Path(path).read_text())
            commit = data.get("vcs_info", {}).get("commit_id", "")
            if commit:
                return commit[:7]
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _get_remote_sha(repo: str) -> str | None:
    """Fetch the latest commit SHA for a GitHub repo's default branch."""
    try:
        import urllib.request

        url = f"https://api.github.com/repos/{repo}/commits/main"
        req = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github.sha"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            sha = resp.read().decode().strip()
            if sha:
                return sha[:7]
    except Exception:  # noqa: BLE001
        logger.debug("Failed to fetch remote SHA for %s", repo)
    return None


def _get_tui_version() -> str | None:
    """Get the installed amplifier-tui version, if available."""
    try:
        return pkg_version("amplifier-tui")
    except PackageNotFoundError:
        pass
    # Try CLI fallback (uv tool install)
    if shutil.which("amplifier-tui"):
        try:
            result = subprocess.run(
                ["amplifier-tui", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                parts = output.split()
                return parts[-1] if parts else output
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
    return None


def _get_package_status(
    package_name: str, version: str | None, repo: str
) -> PackageStatus | None:
    """Build a PackageStatus for a package, or None if not installed."""
    if version is None:
        return PackageStatus(version="—", installed=False)
    local_sha = _get_local_sha(package_name)
    remote_sha = _get_remote_sha(repo)
    return PackageStatus(
        version=version,
        local_sha=local_sha,
        remote_sha=remote_sha,
    )


def get_version_info() -> VersionInfo:
    """Gather comprehensive version and environment information."""
    distro_ver = _get_distro_version()
    amp_ver = _get_amplifier_version()
    tui_ver = _get_tui_version()
    editable = _is_editable_install()

    # Skip remote SHA for distro when editable — developer manages their own source.
    if editable:
        local_sha = _get_local_sha(conventions.PYPI_PACKAGE_NAME)
        distro = PackageStatus(version=distro_ver, local_sha=local_sha)
    else:
        distro = _get_package_status(
            conventions.PYPI_PACKAGE_NAME, distro_ver, conventions.PACKAGE_REPOS["amplifier-distro"]
        )

    return VersionInfo(
        python_version=platform.python_version(),
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
        install_method=_detect_install_method()
        + (" (editable)" if editable else ""),
        distro=distro,
        amplifier=_get_package_status(
            "amplifier-app-cli", amp_ver, conventions.PACKAGE_REPOS["amplifier-app-cli"]
        ),
        tui=_get_package_status(
            "amplifier-tui", tui_ver, conventions.PACKAGE_REPOS["amplifier-tui"]
        ),
    )


def _is_editable_install() -> bool:
    """Check if amplifier-distro is installed in editable mode."""
    try:
        from importlib.metadata import distribution

        dist = distribution(conventions.PYPI_PACKAGE_NAME)
        text = dist.read_text("direct_url.json")
        if text:
            data = json.loads(text)
            return bool(data.get("dir_info", {}).get("editable"))
    except Exception:  # noqa: BLE001
        pass
    return False


def run_self_update() -> tuple[bool, str]:
    """Self-update amplifier-distro.

    Editable installs get a message to use git.
    Tool installs are updated via uv tool install --force.

    Returns (success, message) tuple.
    """
    if _is_editable_install():
        return True, (
            "Editable install detected — update with: git pull\n"
            "(Re-run `uv pip install -e '.[all]'` if dependencies changed.)"
        )

    git_url = f"git+{conventions.GITHUB_REPO_URL}"
    old_version = _get_distro_version()

    try:
        result = subprocess.run(
            ["uv", "tool", "install", "--force", git_url],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return False, f"Update failed: {result.stderr.strip()}"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return False, f"Update failed: {e}"

    # Verify via subprocess (importlib.metadata may be cached)
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
        return True, f"Updated {old_version} -> {new_version}."
    elif new_version == old_version:
        return True, f"Already at latest version ({old_version})."
    return True, "Update succeeded. Restart to use new version."
