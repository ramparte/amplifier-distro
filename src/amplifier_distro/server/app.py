"""Distro Server - Core Application

The server uses FastAPI with a plugin system based on routers.
Apps register themselves and get mounted at their designated paths.

Architecture:
    DistroServer
        /api/health          - Health check
        /api/config          - Distro configuration
        /api/bridge          - Amplifier Bridge API (session management)
        /apps/<name>/...     - Mounted app routes

Apps are Python modules that expose:
    - name: str            - App identifier
    - router: APIRouter    - FastAPI router with routes
    - description: str     - Human-readable description
    - on_startup()         - Optional async startup hook
    - on_shutdown()        - Optional async shutdown hook
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI

logger = logging.getLogger(__name__)


@dataclass
class AppManifest:
    """Metadata for a registered app."""

    name: str
    description: str
    version: str = "0.1.0"
    mount_path: str = ""  # Computed as /apps/{name}
    enabled: bool = True
    # The actual router
    router: APIRouter | None = field(default=None, repr=False)
    # Lifecycle hooks
    on_startup: Any = field(default=None, repr=False)
    on_shutdown: Any = field(default=None, repr=False)


class DistroServer:
    """The core distro server with app plugin system.

    Usage:
        server = DistroServer()

        # Register apps
        server.register_app(slack_app)
        server.register_app(voice_app)

        # Or auto-discover from directory
        server.discover_apps(Path("./apps"))

        # Get the FastAPI instance (for uvicorn)
        app = server.app
    """

    def __init__(self, title: str = "Amplifier Distro", version: str = "0.1.0") -> None:
        self._apps: dict[str, AppManifest] = {}
        self._app = FastAPI(
            title=title,
            version=version,
            docs_url="/api/docs",
            openapi_url="/api/openapi.json",
        )
        self._core_router = APIRouter(prefix="/api", tags=["core"])
        self._setup_core_routes()
        self._app.include_router(self._core_router)

    @property
    def app(self) -> FastAPI:
        """Get the FastAPI application instance."""
        return self._app

    @property
    def apps(self) -> dict[str, AppManifest]:
        """Get registered apps."""
        return dict(self._apps)

    def register_app(self, manifest: AppManifest) -> None:
        """Register an app with the server.

        The app's router is mounted at /apps/{name}/.
        """
        if manifest.name in self._apps:
            raise ValueError(f"App already registered: {manifest.name}")

        manifest.mount_path = f"/apps/{manifest.name}"

        if manifest.router:
            self._app.include_router(
                manifest.router,
                prefix=manifest.mount_path,
                tags=[manifest.name],
            )

        if manifest.on_startup:
            self._app.add_event_handler("startup", manifest.on_startup)

        if manifest.on_shutdown:
            self._app.add_event_handler("shutdown", manifest.on_shutdown)

        self._apps[manifest.name] = manifest
        logger.info(f"Registered app: {manifest.name} at {manifest.mount_path}")

    def discover_apps(self, apps_dir: Path) -> list[str]:
        """Auto-discover and register apps from a directory.

        Each app is a Python package with an __init__.py that exposes:
        - manifest: AppManifest (required)

        Args:
            apps_dir: Directory containing app packages

        Returns:
            List of registered app names
        """
        registered = []
        if not apps_dir.exists():
            logger.warning(f"Apps directory not found: {apps_dir}")
            return registered

        for app_path in sorted(apps_dir.iterdir()):
            if not app_path.is_dir():
                continue
            if not (app_path / "__init__.py").exists():
                continue

            try:
                # Import the app module
                module_name = f"amplifier_distro.server.apps.{app_path.name}"
                spec = importlib.util.spec_from_file_location(
                    module_name, app_path / "__init__.py"
                )
                if spec is None or spec.loader is None:
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                if hasattr(module, "manifest"):
                    self.register_app(module.manifest)
                    registered.append(module.manifest.name)
                else:
                    logger.warning(f"App {app_path.name} missing 'manifest'")

            except Exception:
                logger.exception(f"Failed to load app {app_path.name}")

        return registered

    def _setup_core_routes(self) -> None:
        """Set up the built-in core routes."""

        @self._core_router.get("/health")
        async def health() -> dict[str, str]:
            """Health check endpoint."""
            return {"status": "ok", "version": self._app.version}

        @self._core_router.get("/config")
        async def config() -> dict[str, Any]:
            """Get distro configuration."""
            from amplifier_distro.config import load_config

            cfg = load_config()
            return cfg.model_dump()

        @self._core_router.get("/status")
        async def status() -> dict[str, Any]:
            """Get distro status (preflight results)."""
            from amplifier_distro.preflight import run_preflight

            report = run_preflight()
            return {
                "passed": report.passed,
                "checks": [
                    {
                        "name": c.name,
                        "passed": c.passed,
                        "message": c.message,
                        "severity": c.severity,
                    }
                    for c in report.checks
                ],
            }

        @self._core_router.get("/apps")
        async def list_apps() -> dict[str, dict[str, Any]]:
            """List registered apps."""
            return {
                name: {
                    "description": m.description,
                    "version": m.version,
                    "mount_path": m.mount_path,
                    "enabled": m.enabled,
                }
                for name, m in self._apps.items()
            }


def create_server(**kwargs: Any) -> DistroServer:
    """Factory function to create and configure the server.

    This is the main entry point for starting the server.

    Usage:
        server = create_server()

        # Auto-discover apps
        server.discover_apps(Path("./apps"))

        # Run with uvicorn
        import uvicorn
        uvicorn.run(server.app, host="0.0.0.0", port=8400)
    """
    return DistroServer(**kwargs)
