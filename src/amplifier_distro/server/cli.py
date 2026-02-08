"""CLI entry point for the distro server."""

from pathlib import Path

import click


@click.command("serve")
@click.option("--host", default="127.0.0.1", help="Bind host")
@click.option("--port", default=8400, type=int, help="Bind port")
@click.option(
    "--apps-dir", default=None, type=click.Path(exists=True), help="Apps directory"
)
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
def serve(host: str, port: int, apps_dir: str | None, reload: bool) -> None:
    """Start the Amplifier distro server."""
    import uvicorn

    from amplifier_distro.server.app import create_server

    server = create_server()

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

    click.echo(f"Starting Amplifier Distro Server on {host}:{port}")
    click.echo(f"API docs: http://{host}:{port}/api/docs")
    click.echo(f"Apps: http://{host}:{port}/api/apps")

    uvicorn.run(
        server.app,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
