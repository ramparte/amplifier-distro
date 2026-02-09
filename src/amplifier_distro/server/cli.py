"""CLI entry point for the distro server.

Usage:
    amp-distro-server [OPTIONS]              # via installed script
    python -m amplifier_distro.server [OPTIONS]  # via module
"""

from pathlib import Path

import click


@click.command("amp-distro-server")
@click.option(
    "--host", default="127.0.0.1", help="Bind host (use 0.0.0.0 for LAN/Tailscale)"
)
@click.option("--port", default=8400, type=int, help="Bind port")
@click.option(
    "--apps-dir", default=None, type=click.Path(exists=True), help="Apps directory"
)
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
@click.option(
    "--dev", is_flag=True, help="Dev mode: skip wizard, use existing environment"
)
def serve(host: str, port: int, apps_dir: str | None, reload: bool, dev: bool) -> None:
    """Start the Amplifier distro server."""
    import uvicorn

    from amplifier_distro.server.app import create_server

    server = create_server(dev_mode=dev)

    # Auto-discover apps
    if apps_dir:
        discovered = server.discover_apps(Path(apps_dir))
        click.echo(f"Discovered {len(discovered)} app(s): {', '.join(discovered)}")
    else:
        # Default: discover from built-in apps directory
        builtin_apps = Path(__file__).parent / "apps"
        if builtin_apps.exists():
            discovered = server.discover_apps(builtin_apps)
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
