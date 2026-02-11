"""amp-distro CLI - Amplifier Distribution management tool."""

import json
import logging
import sys
from pathlib import Path

import click

from . import conventions
from .config import (
    config_path,
    detect_github_identity,
    detect_workspace_root,
    load_config,
    save_config,
)
from .doctor import CheckStatus, DoctorReport, run_diagnostics, run_fixes
from .migrate import migrate_memory
from .preflight import PreflightReport, run_preflight
from .schema import IdentityConfig, looks_like_path
from .update_check import check_for_updates, get_version_info, run_self_update

logger = logging.getLogger(__name__)


class _EpilogGroup(click.Group):
    """Click group that preserves epilog formatting."""

    def format_epilog(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        if self.epilog:
            formatter.write("\n")
            for line in self.epilog.splitlines():
                formatter.write(f"{line}\n")


EPILOG = """\
Quick-start examples:

  amp-distro init        Set up identity, workspace, and config
  amp-distro status      Check that everything is healthy
  amp-distro doctor      Diagnose problems (add --fix to auto-repair)
  amp-distro version     Show version and environment info
  amp-distro update      Self-update to the latest release
  amp-distro install     Install an interface (tui, voice, gui)
  amp-distro interfaces  List available interfaces and status
  amp-distro service     Manage auto-start service (install/uninstall)"""


@click.group(
    cls=_EpilogGroup,
    epilog=EPILOG,
    help="Amplifier Distribution management tool.\n\n"
    "Manages configuration, health checks, backups, and updates for "
    "the Amplifier ecosystem.",
)
@click.version_option(package_name="amplifier-distro")
def main() -> None:
    """Amplifier Distribution management tool."""


# ── Core commands ────────────────────────────────────────────────


@main.command(
    help="Initialize the Amplifier Distribution. Detects identity, "
    "sets workspace root, and creates distro.yaml."
)
def init() -> None:
    """Initialize the Amplifier Distribution.

    Detects identity, sets workspace, creates distro.yaml.
    """
    click.echo("Amplifier Distro - Setup\n")

    path = config_path()
    if path.exists() and not click.confirm(
        f"distro.yaml already exists at {path}. Overwrite?", default=False
    ):
        click.echo("Aborted.")
        return

    config = load_config()

    # Detect identity
    click.echo("Detecting identity...")
    handle, email = detect_github_identity()
    if handle:
        click.echo(f"  Found GitHub handle: {handle}")
        if not click.confirm("  Use this?", default=True):
            handle = click.prompt("  GitHub handle")
    else:
        click.echo("  Could not detect GitHub identity (is gh CLI authenticated?)")
        handle = click.prompt("  GitHub handle")

    if email:
        click.echo(f"  Found email: {email}")
        if not click.confirm("  Use this?", default=True):
            email = click.prompt("  Git email")
    else:
        email = click.prompt("  Git email")

    config.identity = IdentityConfig(github_handle=handle, git_email=email)

    # Workspace
    default_ws = detect_workspace_root()
    while True:
        ws = click.prompt("Workspace root", default=default_ws)
        if looks_like_path(ws):
            break
        click.echo(f"  '{ws}' doesn't look like a directory path.")
        click.echo("  Enter a path like ~/dev or /home/user/projects.")
    config.workspace_root = ws

    # Save
    save_config(config)
    click.echo(f"\nSaved to {path}")

    # Migrate memory store
    click.echo("\nMemory store:")
    result = migrate_memory()
    if result.migrated:
        click.echo(f"  Migrated from {result.source}")
        click.echo(f"  New location: {result.destination}")
        for f in result.files_moved:
            click.echo(f"    moved {f}")
    else:
        click.echo(f"  {result.message}")

    # Run preflight to show status
    click.echo("\n--- Health Check ---\n")
    report = run_preflight()
    _print_report(report)

    if report.passed:
        click.echo("\nReady. Start a session with 'amplifier'.")
    else:
        click.echo(
            "\nSome checks failed. Fix the issues above and run 'amp-distro status'."
        )


@main.command(help="Show environment health and check for updates.")
def status() -> None:
    """Show environment health."""
    click.echo("Amplifier Distro - Status\n")
    report = run_preflight()
    _print_report(report)

    if report.passed:
        click.echo("\nAll checks passed.")
    else:
        failed = [c for c in report.checks if not c.passed and c.severity == "error"]
        click.echo(f"\n{len(failed)} check(s) failed.")

    # Show update notice (non-blocking)
    _show_update_notice()

    if not report.passed:
        sys.exit(1)


@main.command(help="Validate distro.yaml schema and bundle configuration.")
def validate() -> None:
    """Validate distro.yaml and bundle configuration."""
    click.echo("Validating distro.yaml...\n")

    path = config_path()
    if not path.exists():
        click.echo(f"Not found: {path}")
        click.echo("Run 'amp-distro init' first.")
        sys.exit(1)

    try:
        config = load_config()
        click.echo(f"  workspace_root: {config.workspace_root}")
        click.echo(f"  identity: @{config.identity.github_handle}")
        click.echo(f"  bundle: {config.bundle.active}")
        click.echo(f"  preflight: {config.preflight.mode}")
        click.echo(f"  cache TTL: {config.cache.max_age_hours}h")
        click.echo("\nValid.")
    except (OSError, ValueError, KeyError) as e:
        click.echo(f"Invalid: {e}")
        sys.exit(1)


@main.command(
    help="Diagnose and auto-fix common problems. Runs comprehensive "
    "checks against the local Amplifier installation."
)
@click.option("--fix", is_flag=True, help="Auto-fix issues that can be resolved.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def doctor(fix: bool, as_json: bool) -> None:
    """Diagnose and auto-fix common problems.

    Runs a comprehensive suite of checks against the local Amplifier
    installation.  Use --fix to automatically resolve fixable issues
    (missing directories, wrong permissions, stale PID files).
    """
    amplifier_home = Path(conventions.AMPLIFIER_HOME).expanduser()
    report = run_diagnostics(amplifier_home)

    # Apply fixes if requested
    fixes_applied: list[str] = []
    if fix:
        fixes_applied = run_fixes(amplifier_home, report)
        # Re-run diagnostics to show updated state
        if fixes_applied:
            report = run_diagnostics(amplifier_home)

    if as_json:
        _print_doctor_json(report, fixes_applied)
    else:
        _print_doctor_report(report, fixes_applied)

    # Exit non-zero if any errors remain
    if report.summary["error"] > 0:
        sys.exit(1)


# ── Data commands ────────────────────────────────────────────────


@main.command("backup", help="Back up Amplifier state to a private GitHub repo.")
@click.option("--name", default=None, help="Override backup repo name for this run.")
def backup_cmd(name: str | None) -> None:
    """Back up Amplifier state to a private GitHub repo."""
    from pathlib import Path

    from . import conventions
    from .backup import backup as run_backup
    from .schema import BackupConfig

    config = load_config()
    gh_handle = config.identity.github_handle
    if not gh_handle:
        click.echo("Error: no github_handle in distro.yaml identity.", err=True)
        click.echo("Run 'amp-distro init' first.", err=True)
        sys.exit(1)

    backup_cfg = config.backup
    if name:
        backup_cfg = BackupConfig(
            repo_name=name,
            repo_owner=backup_cfg.repo_owner,
            auto=backup_cfg.auto,
        )

    amplifier_home = Path(conventions.AMPLIFIER_HOME).expanduser()
    click.echo("Starting backup...")
    result = run_backup(backup_cfg, amplifier_home, gh_handle)

    if result.status == "success":
        click.echo(f"  {result.message}")
        for f in result.files:
            click.echo(f"    {f}")
    else:
        click.echo(f"Backup failed: {result.message}", err=True)
        sys.exit(1)


@main.command("restore", help="Restore Amplifier state from a private GitHub repo.")
@click.option("--name", default=None, help="Restore from a specific backup repo name.")
def restore_cmd(name: str | None) -> None:
    """Restore Amplifier state from a private GitHub repo."""
    from pathlib import Path

    from . import conventions
    from .backup import restore as run_restore
    from .schema import BackupConfig

    config = load_config()
    gh_handle = config.identity.github_handle
    if not gh_handle:
        click.echo("Error: no github_handle in distro.yaml identity.", err=True)
        click.echo("Run 'amp-distro init' first.", err=True)
        sys.exit(1)

    backup_cfg = config.backup
    if name:
        backup_cfg = BackupConfig(
            repo_name=name,
            repo_owner=backup_cfg.repo_owner,
            auto=backup_cfg.auto,
        )

    amplifier_home = Path(conventions.AMPLIFIER_HOME).expanduser()
    click.echo("Starting restore...")
    result = run_restore(backup_cfg, amplifier_home, gh_handle)

    if result.status == "success":
        click.echo(f"  {result.message}")
        for f in result.files:
            click.echo(f"    {f}")
    else:
        click.echo(f"Restore failed: {result.message}", err=True)
        sys.exit(1)


# ── Interface commands ────────────────────────────────────────

INTERFACE_REGISTRY: dict[str, dict[str, str]] = {
    "tui": {
        "repo": "ramparte/amplifier-tui",
        "package": "amplifier-tui",
        "description": "Terminal UI with Textual",
    },
    "voice": {
        "repo": "ramparte/amplifier-voice-bridge",
        "package": "amplifier-voice-bridge",
        "description": "Voice interface via OpenAI Realtime API",
    },
    "gui": {
        "repo": "ramparte/amplifier-gui",
        "package": "amplifier-gui",
        "description": "Web-based GUI",
    },
}


@main.command(help="Install an Amplifier interface (tui, voice, gui).")
@click.argument("interface", type=click.Choice(list(INTERFACE_REGISTRY.keys())))
@click.option(
    "--from-source", is_flag=True, help="Clone repo and install in editable mode."
)
def install(interface: str, from_source: bool) -> None:
    """Install an Amplifier interface."""
    info = INTERFACE_REGISTRY[interface]
    repo = info["repo"]
    package = info["package"]
    repo_name = repo.split("/")[1]

    click.echo(f"Installing {interface} ({info['description']})...\n")

    if from_source:
        _install_from_source(interface, repo, repo_name, package)
    else:
        _install_from_package(interface, repo, package)


def _install_from_package(interface: str, repo: str, package: str) -> None:
    """Install an interface via uv tool install, falling back to pip."""
    import subprocess

    url = f"git+https://github.com/{repo}"
    click.echo(f"  Trying: uv tool install {url}")

    try:
        result = subprocess.run(
            ["uv", "tool", "install", url],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            click.echo("  Installed via uv.")
        else:
            logger.debug("uv install failed: %s", result.stderr)
            click.echo(f"  uv failed, trying: pip install {package}")
            result = subprocess.run(
                ["pip", "install", package],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                click.echo(f"  pip install failed: {result.stderr.strip()}", err=True)
                sys.exit(1)
            click.echo("  Installed via pip.")
    except FileNotFoundError:
        click.echo("  uv not found, trying: pip install " + package)
        try:
            result = subprocess.run(
                ["pip", "install", package],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                click.echo(f"  pip install failed: {result.stderr.strip()}", err=True)
                sys.exit(1)
            click.echo("  Installed via pip.")
        except FileNotFoundError:
            click.echo("Error: neither uv nor pip found.", err=True)
            sys.exit(1)
    except subprocess.TimeoutExpired:
        click.echo("Error: install command timed out.", err=True)
        sys.exit(1)

    _update_config(interface)
    _smoke_test(package)
    click.echo(f"\n{interface} interface installed successfully.")


def _install_from_source(
    interface: str, repo: str, repo_name: str, package: str
) -> None:
    """Clone repo and install in editable mode."""
    import subprocess

    config = load_config()
    workspace = Path(config.workspace_root).expanduser()
    clone_dir = workspace / repo_name

    if clone_dir.exists():
        click.echo(f"  Directory exists: {clone_dir} (skipping clone)")
    else:
        clone_url = f"https://github.com/{repo}.git"
        click.echo(f"  Cloning {clone_url} -> {clone_dir}")
        try:
            result = subprocess.run(
                ["git", "clone", clone_url, str(clone_dir)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                click.echo(f"  Clone failed: {result.stderr.strip()}", err=True)
                sys.exit(1)
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            click.echo(f"  Clone failed: {e}", err=True)
            sys.exit(1)

    click.echo(f"  Installing editable: uv pip install -e {clone_dir}")
    try:
        result = subprocess.run(
            ["uv", "pip", "install", "-e", "."],
            capture_output=True,
            text=True,
            cwd=str(clone_dir),
            timeout=120,
        )
        if result.returncode != 0:
            click.echo(f"  Editable install failed: {result.stderr.strip()}", err=True)
            sys.exit(1)
    except FileNotFoundError:
        click.echo("Error: uv not found. Install uv first.", err=True)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        click.echo("Error: install command timed out.", err=True)
        sys.exit(1)

    _update_config(interface, path=str(clone_dir))
    _smoke_test(package)
    click.echo(f"\n{interface} interface installed from source at {clone_dir}.")


def _update_config(interface: str, path: str = "") -> None:
    """Mark an interface as installed in distro.yaml."""
    config = load_config()
    entry = getattr(config.interfaces, interface)
    entry.installed = True
    if path:
        entry.path = path
    save_config(config)
    logger.debug("Updated distro.yaml: interfaces.%s.installed = True", interface)


def _smoke_test(package: str) -> None:
    """Try importing the package's main module as a quick sanity check."""
    module_name = package.replace("-", "_")
    try:
        __import__(module_name)
        click.echo(f"  Smoke test: import {module_name} OK")
    except ImportError:
        click.echo(
            f"  Smoke test: import {module_name} not available (may need PATH update)"
        )


@main.command("interfaces", help="List available interfaces and their install status.")
def list_interfaces() -> None:
    """List available interfaces and their install status."""
    config = load_config()

    click.echo("Amplifier Interfaces\n")

    # CLI is always installed
    cli_entry = config.interfaces.cli
    mark = click.style("✓", fg="green") if cli_entry.installed else " "
    click.echo(f"  [{mark}] cli        Amplifier CLI (always installed)")

    for name, info in INTERFACE_REGISTRY.items():
        entry = getattr(config.interfaces, name)
        if entry.installed:
            mark = click.style("✓", fg="green")
            suffix = f" ({entry.path})" if entry.path else ""
        else:
            mark = " "
            suffix = ""
        click.echo(f"  [{mark}] {name:<10} {info['description']}{suffix}")

    click.echo("\nInstall with: amp-distro install <name>")
    click.echo("Source mode:  amp-distro install <name> --from-source")


# ── Info commands ────────────────────────────────────────────────


@main.command(help="Show version, platform, and environment information.")
def version() -> None:
    """Show version information."""
    info = get_version_info()

    click.echo("Amplifier Distro - Version\n")
    click.echo(f"  amplifier-distro:  {info.distro_version}")
    if info.amplifier_version:
        click.echo(f"  amplifier:         {info.amplifier_version}")
    else:
        click.echo("  amplifier:         not installed")
    click.echo(f"  Python:            {info.python_version}")
    click.echo(f"  Platform:          {info.platform}")
    click.echo(f"  Install method:    {info.install_method}")


@main.command(help="Self-update amplifier-distro to the latest release.")
def update() -> None:
    """Self-update amplifier-distro."""
    click.echo("Checking for updates...")

    update_info = check_for_updates()
    if update_info is None:
        info = get_version_info()
        click.echo(f"Already at latest version ({info.distro_version}).")
        return

    click.echo(
        f"Update available: v{update_info.current_version} -> "
        f"v{update_info.latest_version}"
    )
    click.echo("Updating...")

    success, message = run_self_update()
    if success:
        click.echo(message)
    else:
        click.echo(f"Update failed: {message}", err=True)
        sys.exit(1)


# —— Service commands————————————————————————————————————————


@main.group("service")
def service_group() -> None:
    """Manage platform auto-start service (systemd/launchd)."""


@service_group.command("install")
@click.option(
    "--no-watchdog",
    is_flag=True,
    help="Install server only, without the health watchdog.",
)
def service_install(no_watchdog: bool) -> None:
    """Install the platform service for auto-start on boot."""
    from .service import install_service

    result = install_service(include_watchdog=not no_watchdog)
    if result.success:
        click.echo(f"Service installed ({result.platform})")
        for detail in result.details:
            click.echo(f"  {detail}")
    else:
        click.echo(f"Failed: {result.message}", err=True)
        for detail in result.details:
            click.echo(f"  {detail}", err=True)
        raise SystemExit(1)


@service_group.command("uninstall")
def service_uninstall() -> None:
    """Remove the platform auto-start service."""
    from .service import uninstall_service

    result = uninstall_service()
    if result.success:
        click.echo(f"Service removed ({result.platform})")
        for detail in result.details:
            click.echo(f"  {detail}")
    else:
        click.echo(f"Failed: {result.message}", err=True)
        raise SystemExit(1)


@service_group.command("status")
def service_cmd_status() -> None:
    """Check platform service status."""
    from .service import service_status

    result = service_status()
    click.echo(f"Platform: {result.platform}")
    click.echo(f"Status: {result.message}")
    for detail in result.details:
        click.echo(f"  {detail}")


# ── Internal helpers ─────────────────────────────────────────────


def _show_update_notice() -> None:
    """Show an update notice if a newer version is available.

    Non-blocking: any failure is silently ignored.
    """
    try:
        info = check_for_updates()
        if info is not None:
            click.echo(
                f"\nUpdate available: v{info.current_version} -> "
                f"v{info.latest_version}. "
                "Run `amp-distro update` to upgrade."
            )
    except Exception:  # noqa: BLE001
        logger.debug("Update check failed", exc_info=True)


def _print_doctor_report(report: DoctorReport, fixes: list[str]) -> None:
    """Format and print a doctor report with coloured status markers."""
    click.echo("Amplifier Distro - Doctor\n")

    for check in report.checks:
        if check.status == CheckStatus.ok:
            mark = click.style("\u2714", fg="green")  # checkmark
        elif check.status == CheckStatus.warning:
            mark = click.style("!", fg="yellow")
        else:
            mark = click.style("\u2718", fg="red")  # X

        click.echo(f"  {mark} {check.name}: {check.message}")

        # Show fix suggestion for non-ok checks that have a fix
        if check.status != CheckStatus.ok and check.fix_available:
            click.echo(click.style(f"    fix: {check.fix_description}", fg="cyan"))

    # Summary
    s = report.summary
    click.echo(f"\n  {s['ok']} ok, {s['warning']} warning(s), {s['error']} error(s)")

    if fixes:
        click.echo("\nFixes applied:")
        checkmark = click.style("\u2714", fg="green")
        for f in fixes:
            click.echo(f"  {checkmark} {f}")


def _print_doctor_json(report: DoctorReport, fixes: list[str]) -> None:
    """Print the doctor report as machine-readable JSON."""
    data = {
        "checks": [c.model_dump() for c in report.checks],
        "summary": report.summary,
        "fixes_applied": fixes,
    }
    click.echo(json.dumps(data, indent=2))


def _print_report(report: PreflightReport) -> None:
    """Format and print a preflight report."""
    for check in report.checks:
        if check.passed:
            mark = "ok"
        elif check.severity == "warning":
            mark = "!!"
        else:
            mark = "FAIL"
        click.echo(f"  [{mark:>4}] {check.name}: {check.message}")
