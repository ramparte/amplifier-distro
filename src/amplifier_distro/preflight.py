"""Pre-flight checks for distro health."""

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import config_path, load_config
from .schema import looks_like_path, normalize_path


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    severity: str = "error"  # error | warning | info


@dataclass
class PreflightReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.severity == "error")

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed and c.severity == "warning"]


def run_preflight() -> PreflightReport:
    """Run all pre-flight checks and return report."""
    report = PreflightReport()

    # Check 1: distro.yaml exists
    path = config_path()
    if path.exists():
        report.checks.append(CheckResult("distro.yaml", True, f"Found at {path}"))
    else:
        report.checks.append(
            CheckResult(
                "distro.yaml", False, f"Not found at {path}. Run 'amp-distro init'"
            )
        )

    # Check 2: GitHub CLI authenticated
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            report.checks.append(CheckResult("GitHub CLI", True, "Authenticated"))
        else:
            report.checks.append(
                CheckResult(
                    "GitHub CLI", False, "Not authenticated. Run 'gh auth login'"
                )
            )
    except FileNotFoundError:
        report.checks.append(CheckResult("GitHub CLI", False, "gh CLI not installed"))
    except subprocess.TimeoutExpired:
        report.checks.append(
            CheckResult("GitHub CLI", False, "Timed out checking gh auth")
        )

    # Check 3: Identity configured
    config = load_config()
    if config.identity.github_handle:
        report.checks.append(
            CheckResult("Identity", True, f"@{config.identity.github_handle}")
        )
    else:
        report.checks.append(
            CheckResult(
                "Identity", False, "GitHub handle not set. Run 'amp-distro init'"
            )
        )

    # Check 4: ANTHROPIC_API_KEY
    _check_api_key(report, "ANTHROPIC_API_KEY")

    # Check 5: OPENAI_API_KEY
    _check_api_key(report, "OPENAI_API_KEY")

    # Check 6: Workspace root exists
    ws_raw = config.workspace_root
    ws = Path(normalize_path(ws_raw))
    if ws.is_dir():
        report.checks.append(CheckResult("Workspace", True, str(ws)))
    elif not looks_like_path(ws_raw):
        report.checks.append(
            CheckResult(
                "Workspace",
                False,
                f"workspace_root is not a valid path: {ws_raw!r}. "
                "Re-run 'amp-distro init' to fix.",
            )
        )
    else:
        report.checks.append(CheckResult("Workspace", False, f"{ws} does not exist"))

    # Check 7: Memory store location
    memory_path = Path(config.memory.path).expanduser()
    if memory_path.is_dir():
        report.checks.append(CheckResult("Memory store", True, str(memory_path)))
    else:
        report.checks.append(
            CheckResult(
                "Memory store",
                False,
                f"{memory_path} not found. Run 'amp-distro init' to create it",
                severity="warning",
            )
        )

    # Check 8: Amplifier installed
    if shutil.which("amplifier"):
        report.checks.append(CheckResult("Amplifier CLI", True, "Installed"))
    else:
        report.checks.append(
            CheckResult(
                "Amplifier CLI",
                False,
                "Not found. Run 'uv tool install git+https://github.com/microsoft/amplifier'",
            )
        )

    # Check 9: Email bridge (optional - warning only)
    _check_email_bridge(report)

    return report


def _check_email_bridge(report: PreflightReport) -> None:
    """Check email bridge configuration (optional, warning only)."""
    required = ["GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"]
    present = [k for k in required if os.environ.get(k)]

    if len(present) == len(required):
        report.checks.append(CheckResult("Email bridge", True, "Gmail credentials set"))
    elif present:
        missing = [k for k in required if k not in present]
        report.checks.append(
            CheckResult(
                "Email bridge",
                False,
                f"Partial config - missing: {', '.join(missing)}",
                severity="warning",
            )
        )
    else:
        report.checks.append(
            CheckResult(
                "Email bridge",
                False,
                "Not configured (optional)",
                severity="warning",
            )
        )


def _check_api_key(report: PreflightReport, key_name: str) -> None:
    """Check an API key environment variable."""
    key = os.environ.get(key_name, "")
    if key and not key.startswith("test"):
        report.checks.append(CheckResult(key_name, True, "Set"))
    elif key:
        report.checks.append(
            CheckResult(key_name, False, "Appears to be a test key", severity="warning")
        )
    else:
        report.checks.append(
            CheckResult(key_name, False, "Not set", severity="warning")
        )
