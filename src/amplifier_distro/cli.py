"""amp-distro CLI - Amplifier Experience Server management tool.

Manages the experience server (web chat, Slack, voice), backup/restore,
and platform service registration. Core CLI functionality (init, doctor,
sessions) lives in the amplifier CLI itself.
"""

import sys
from pathlib import Path

import click

from . import conventions


class _EpilogGroup(click.Group):
    """Click group that preserves epilog formatting."""

    def format_epilog(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        if self.epilog:
            formatter.write("\n")
            for line in self.epilog.splitlines():
                formatter.write(f"{line}\n")


EPILOG = """\
Quick-start examples:

  amp-distro server          Start the experience server (foreground)
  amp-distro server start    Start as background daemon
  amp-distro server stop     Stop the daemon
  amp-distro backup          Back up Amplifier state to GitHub
  amp-distro restore         Restore from backup
  amp-distro service install Register as auto-start service"""


@click.group(
    cls=_EpilogGroup,
    epilog=EPILOG,
    help="Amplifier Experience Server management tool.\n\n"
    "Manages the experience server, backups, and platform service.",
)
@click.version_option(package_name="amplifier-distro")
def main() -> None:
    """Amplifier Experience Server management tool."""


# -- Server (delegates to server.cli) ------------------------------------


@main.command(
    "server",
    cls=click.Group,
    help="Manage the Amplifier experience server.",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
def server_group() -> None:
    """Manage the Amplifier experience server."""


# Register the full server CLI as a subcommand
def _register_server_commands() -> None:
    """Lazily wire up server subcommands from server.cli."""
    from .server.cli import serve

    # Merge server CLI commands into our server group
    for name, cmd in serve.commands.items():
        main.add_command(cmd, f"server-{name}" if False else None)

    # Replace the placeholder group with the real one
    main.add_command(serve, "server")


_register_server_commands()


# -- Backup commands -----------------------------------------------------


@main.command("backup", help="Back up Amplifier state to a private GitHub repo.")
@click.option("--name", default="amplifier-backup", help="Backup repo name.")
def backup_cmd(name: str) -> None:
    """Back up Amplifier state to a private GitHub repo."""
    from .backup import _detect_gh_handle, backup

    gh_handle = _detect_gh_handle()
    if not gh_handle:
        click.echo(
            "Error: Could not detect GitHub handle. "
            "Is the gh CLI installed and authenticated?",
            err=True,
        )
        sys.exit(1)

    amplifier_home = Path(conventions.AMPLIFIER_HOME).expanduser()
    click.echo("Starting backup...")
    result = backup(amplifier_home, gh_handle, repo_name=name)

    if result.status == "success":
        click.echo(f"  {result.message}")
        for f in result.files:
            click.echo(f"    {f}")
    else:
        click.echo(f"Backup failed: {result.message}", err=True)
        sys.exit(1)


@main.command("restore", help="Restore Amplifier state from a private GitHub repo.")
@click.option("--name", default="amplifier-backup", help="Backup repo name.")
def restore_cmd(name: str) -> None:
    """Restore Amplifier state from a private GitHub repo."""
    from .backup import _detect_gh_handle, restore

    gh_handle = _detect_gh_handle()
    if not gh_handle:
        click.echo(
            "Error: Could not detect GitHub handle. "
            "Is the gh CLI installed and authenticated?",
            err=True,
        )
        sys.exit(1)

    amplifier_home = Path(conventions.AMPLIFIER_HOME).expanduser()
    click.echo("Starting restore...")
    result = restore(amplifier_home, gh_handle, repo_name=name)

    if result.status == "success":
        click.echo(f"  {result.message}")
        for f in result.files:
            click.echo(f"    {f}")
    else:
        click.echo(f"Restore failed: {result.message}", err=True)
        sys.exit(1)


# -- Service commands ----------------------------------------------------


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
