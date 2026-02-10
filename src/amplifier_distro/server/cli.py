"""CLI entry point for the distro server.

Usage:
    amp-distro-server [OPTIONS]                # foreground mode (default)
    amp-distro-server start [OPTIONS]          # start as background daemon
    amp-distro-server stop                     # stop background daemon
    amp-distro-server restart [OPTIONS]        # restart background daemon
    amp-distro-server status                   # check daemon status
    amp-distro-server watchdog start           # start health watchdog
    amp-distro-server watchdog stop            # stop health watchdog
    amp-distro-server watchdog status          # check watchdog status
    python -m amplifier_distro.server [OPTIONS]  # via module (foreground)
"""

from __future__ import annotations

import socket
from pathlib import Path

import click

from amplifier_distro import conventions


@click.group("amp-distro-server", invoke_without_command=True)
@click.option(
    "--host",
    default="127.0.0.1",
    help="Bind host (use 0.0.0.0 for LAN/Tailscale)",
)
@click.option(
    "--port",
    default=conventions.SERVER_DEFAULT_PORT,
    type=int,
    help="Bind port",
)
@click.option(
    "--apps-dir",
    default=None,
    type=click.Path(exists=True),
    help="Apps directory",
)
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
@click.option(
    "--dev",
    is_flag=True,
    help="Dev mode: skip wizard, use existing environment",
)
@click.pass_context
def serve(
    ctx: click.Context,
    host: str,
    port: int,
    apps_dir: str | None,
    reload: bool,
    dev: bool,
) -> None:
    """Amplifier distro server.

    Run without a subcommand for foreground mode, or use
    start/stop/restart/status for daemon management.
    """
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand is None:
        _run_foreground(host, port, apps_dir, reload, dev)


@serve.command()
@click.option(
    "--host",
    default="127.0.0.1",
    help="Bind host (use 0.0.0.0 for LAN/Tailscale)",
)
@click.option(
    "--port",
    default=conventions.SERVER_DEFAULT_PORT,
    type=int,
    help="Bind port",
)
@click.option("--apps-dir", default=None, help="Apps directory")
@click.option(
    "--dev",
    is_flag=True,
    help="Dev mode: skip wizard, use existing environment",
)
def start(host: str, port: int, apps_dir: str | None, dev: bool) -> None:
    """Start the server as a background daemon."""
    from amplifier_distro.server.daemon import (
        daemonize,
        is_running,
        pid_file_path,
        wait_for_health,
    )
    from amplifier_distro.server.startup import load_env_file

    pid_file = pid_file_path()
    if is_running(pid_file):
        click.echo("Server is already running.", err=True)
        raise SystemExit(1)

    # Load .env files so daemon inherits env vars
    loaded = load_env_file()
    if loaded:
        click.echo(f"Loaded env: {', '.join(loaded)}")

    try:
        pid = daemonize(host=host, port=port, apps_dir=apps_dir, dev=dev)
    except RuntimeError as e:
        click.echo(f"Cannot start: {e}", err=True)
        raise SystemExit(1) from None

    click.echo(f"Server starting (PID {pid})...")

    # Wait for health
    if wait_for_health(host=host, port=port, timeout=15):
        click.echo("Server is healthy!")
        click.echo(f"  URL: http://{host}:{port}")
        click.echo(f"  PID file: {pid_file}")
    else:
        click.echo("Warning: Server started but health check not responding yet.")
        click.echo("  Check logs: ~/.amplifier/server/server.log")
        click.echo("  Crash log:  ~/.amplifier/server/crash.log")


@serve.command()
def stop() -> None:
    """Stop the running server daemon."""
    from amplifier_distro.server.daemon import pid_file_path, read_pid, stop_process

    pid_file = pid_file_path()
    pid = read_pid(pid_file)
    if pid is None:
        click.echo("No PID file found — server may not be running.")
        return

    click.echo(f"Stopping server (PID {pid})...")
    stopped = stop_process(pid_file)
    if stopped:
        click.echo("Server stopped.")
    else:
        click.echo("Could not stop server.", err=True)
        raise SystemExit(1)


@serve.command()
@click.option(
    "--host",
    default="127.0.0.1",
    help="Bind host (use 0.0.0.0 for LAN/Tailscale)",
)
@click.option(
    "--port",
    default=conventions.SERVER_DEFAULT_PORT,
    type=int,
    help="Bind port",
)
@click.option("--apps-dir", default=None, help="Apps directory")
@click.option(
    "--dev",
    is_flag=True,
    help="Dev mode: skip wizard, use existing environment",
)
@click.pass_context
def restart(
    ctx: click.Context,
    host: str,
    port: int,
    apps_dir: str | None,
    dev: bool,
) -> None:
    """Restart the server daemon (stop + start)."""
    ctx.invoke(stop)
    ctx.invoke(start, host=host, port=port, apps_dir=apps_dir, dev=dev)


@serve.command("status")
def server_status() -> None:
    """Check server daemon status."""
    from amplifier_distro.server.daemon import (
        cleanup_pid,
        is_running,
        pid_file_path,
        read_pid,
    )

    pid_file = pid_file_path()
    pid = read_pid(pid_file)
    running = is_running(pid_file)

    if running and pid is not None:
        click.echo(f"Server is running (PID {pid})")
        # Check if port is responsive
        port = conventions.SERVER_DEFAULT_PORT
        if _check_port("127.0.0.1", port):
            click.echo(f"  Port {port}: listening")
            click.echo(f"  Health: http://127.0.0.1:{port}/api/health")
        else:
            click.echo(f"  Port {port}: not responding (server may be starting)")
    elif pid is not None:
        click.echo(f"Server is NOT running (stale PID file for PID {pid})")
        click.echo("  Cleaning up stale PID file...")
        cleanup_pid(pid_file)
    else:
        click.echo("Server is not running (no PID file)")


def _check_port(host: str, port: int) -> bool:
    """Check if a port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


# ---------------------------------------------------------------------------
# Watchdog subcommands
# ---------------------------------------------------------------------------


@serve.group("watchdog", invoke_without_command=True)
@click.pass_context
def watchdog_group(ctx: click.Context) -> None:
    """Manage the server health watchdog."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(watchdog_status)


@watchdog_group.command("start")
@click.option(
    "--host",
    default="127.0.0.1",
    help="Server host to monitor",
)
@click.option(
    "--port",
    default=conventions.SERVER_DEFAULT_PORT,
    type=int,
    help="Server port to monitor",
)
@click.option(
    "--check-interval",
    default=30,
    type=int,
    help="Seconds between health checks",
)
@click.option(
    "--restart-after",
    default=300,
    type=int,
    help="Seconds of sustained downtime before restart",
)
@click.option(
    "--max-restarts",
    default=5,
    type=int,
    help="Max restart attempts (0 = unlimited)",
)
@click.option("--apps-dir", default=None, help="Server apps directory")
@click.option("--dev", is_flag=True, help="Server dev mode")
def watchdog_start(
    host: str,
    port: int,
    check_interval: int,
    restart_after: int,
    max_restarts: int,
    apps_dir: str | None,
    dev: bool,
) -> None:
    """Start the watchdog as a background process."""
    from amplifier_distro.server.watchdog import is_watchdog_running, start_watchdog

    if is_watchdog_running():
        click.echo("Watchdog is already running.", err=True)
        raise SystemExit(1)

    pid = start_watchdog(
        host=host,
        port=port,
        check_interval=check_interval,
        restart_after=restart_after,
        max_restarts=max_restarts,
        apps_dir=apps_dir,
        dev=dev,
    )
    click.echo(f"Watchdog started (PID {pid})")
    click.echo(f"  Monitoring: http://{host}:{port}/api/health")
    click.echo(f"  Check interval: {check_interval}s")
    click.echo(f"  Restart after: {restart_after}s downtime")


@watchdog_group.command("stop")
def watchdog_stop() -> None:
    """Stop the running watchdog."""
    from amplifier_distro.server.daemon import read_pid
    from amplifier_distro.server.watchdog import stop_watchdog, watchdog_pid_file_path

    wd_pid_file = watchdog_pid_file_path()
    pid = read_pid(wd_pid_file)
    if pid is None:
        click.echo("No watchdog PID file found \u2014 watchdog may not be running.")
        return

    click.echo(f"Stopping watchdog (PID {pid})...")
    stopped = stop_watchdog()
    if stopped:
        click.echo("Watchdog stopped.")
    else:
        click.echo("Could not stop watchdog.", err=True)
        raise SystemExit(1)


@watchdog_group.command("status")
def watchdog_status() -> None:
    """Check watchdog status."""
    from amplifier_distro.server.daemon import cleanup_pid, read_pid
    from amplifier_distro.server.watchdog import (
        is_watchdog_running,
        watchdog_pid_file_path,
    )

    wd_pid_file = watchdog_pid_file_path()
    pid = read_pid(wd_pid_file)
    running = is_watchdog_running()

    if running and pid is not None:
        click.echo(f"Watchdog is running (PID {pid})")
    elif pid is not None:
        click.echo(f"Watchdog is NOT running (stale PID file for PID {pid})")
        click.echo("  Cleaning up stale PID file...")
        cleanup_pid(wd_pid_file)
    else:
        click.echo("Watchdog is not running (no PID file)")


def _run_foreground(
    host: str,
    port: int,
    apps_dir: str | None,
    reload: bool,
    dev: bool,
) -> None:
    """Run the server in the foreground (existing behavior + startup improvements)."""
    import logging

    import uvicorn

    from amplifier_distro.server.app import create_server
    from amplifier_distro.server.services import init_services
    from amplifier_distro.server.startup import (
        export_keys,
        load_env_file,
        log_startup_info,
        run_startup_checks,
        setup_logging,
    )

    # Set up structured logging first
    setup_logging()
    logger = logging.getLogger("amplifier_distro.server")

    # Load .env files
    loaded_env = load_env_file()
    if loaded_env:
        logger.info(
            "Loaded %d var(s) from .env: %s", len(loaded_env), ", ".join(loaded_env)
        )

    # Export keys from keys.yaml
    exported = export_keys()
    if exported:
        logger.info(
            "Exported %d key(s) from keys.yaml: %s",
            len(exported),
            ", ".join(exported),
        )

    # Run pre-flight checks
    run_startup_checks(logger)

    # Initialize shared services
    services = init_services(dev_mode=dev)
    click.echo(f"Services: backend={type(services.backend).__name__}")

    server = create_server(dev_mode=dev)

    # Auto-discover apps
    loaded_apps: list[str] = []
    if apps_dir:
        discovered = server.discover_apps(Path(apps_dir))
        loaded_apps = discovered
        click.echo(f"Discovered {len(discovered)} app(s): {', '.join(discovered)}")
    else:
        # Default: discover from built-in apps directory
        builtin_apps = Path(__file__).parent / "apps"
        if builtin_apps.exists():
            discovered = server.discover_apps(builtin_apps)
            loaded_apps = discovered
            if discovered:
                click.echo(f"Loaded {len(discovered)} app(s): {', '.join(discovered)}")

    if dev:
        click.echo("--- Dev mode: using existing environment ---")
        # Show detected config
        try:
            from amplifier_distro.config import config_path, load_config

            if config_path().exists():
                cfg = load_config()
                click.echo(f"  Config: {config_path()}")
                click.echo(f"  Workspace: {cfg.workspace_root}")
                click.echo(
                    f"  Identity: {cfg.identity.github_handle or '(auto-detect)'}"
                )
            else:
                click.echo(f"  No distro.yaml found at {config_path()}")
                click.echo("  Creating default config...")
                _create_default_config()
        except Exception as e:
            click.echo(f"  Config issue: {e}")

    # Log startup info (structured)
    log_startup_info(
        host=host,
        port=port,
        apps=loaded_apps,
        dev_mode=dev,
        logger=logger,
    )

    click.echo(f"Starting Amplifier Distro Server on {host}:{port}")
    if host == "0.0.0.0":
        click.echo(f"  Local:     http://127.0.0.1:{port}")
        _show_tailscale_url(port)
    else:
        click.echo(f"  URL: http://{host}:{port}")
    click.echo(f"  API docs:  http://{host}:{port}/api/docs")

    uvicorn.run(
        server.app,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )

    # Auto-backup on shutdown (if enabled in distro.yaml)
    try:
        from amplifier_distro.backup import run_auto_backup

        result = run_auto_backup()
        if result is not None:
            if result.status == "success":
                logger.info("Auto-backup: %s", result.message)
            else:
                logger.warning("Auto-backup failed: %s", result.message)
    except Exception:
        logger.exception("Auto-backup error")


def _show_tailscale_url(port: int) -> None:
    """Show Tailscale URL if available."""
    import subprocess

    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            ts_ip = result.stdout.strip().split("\n")[0]
            click.echo(f"  Tailscale: http://{ts_ip}:{port}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _create_default_config() -> None:
    """Create a default distro.yaml from environment detection."""
    import subprocess

    from amplifier_distro.config import save_config
    from amplifier_distro.schema import DistroConfig, IdentityConfig

    # Detect identity
    gh_handle = ""
    git_email = ""
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            gh_handle = result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        result = subprocess.run(
            ["git", "config", "--global", "user.email"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            git_email = result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Detect workspace
    home = Path.home()
    workspace = str(home / "dev")
    for candidate in ["dev/ANext", "dev", "projects", "workspace"]:
        if (home / candidate).exists():
            workspace = str(home / candidate)
            break

    cfg = DistroConfig(
        workspace_root=workspace,
        identity=IdentityConfig(github_handle=gh_handle, git_email=git_email),
    )
    save_config(cfg)
    click.echo(f"  Created: {cfg.workspace_root} ({gh_handle or 'no gh handle'})")
