"""amp-distro CLI - Amplifier Distribution management tool."""

import sys

import click

from .config import (
    config_path,
    detect_github_identity,
    detect_workspace_root,
    load_config,
    save_config,
)
from .migrate import migrate_memory
from .preflight import PreflightReport, run_preflight
from .schema import IdentityConfig


@click.group()
@click.version_option(package_name="amplifier-distro")
def main() -> None:
    """Amplifier Distribution management tool."""


@main.command()
def init() -> None:
    """Initialize the Amplifier Distribution.

    Detects identity, sets workspace, creates distro.yaml.
    """
    click.echo("Amplifier Distro - Setup\n")

    path = config_path()
    if path.exists():
        if not click.confirm(
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
    ws = click.prompt("Workspace root", default=default_ws)
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


@main.command()
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
        sys.exit(1)


@main.command()
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
    except Exception as e:
        click.echo(f"Invalid: {e}")
        sys.exit(1)


@main.command("backup")
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


@main.command("restore")
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
