"""Distro Server - Core Application

The server uses FastAPI with a plugin system based on routers.
Apps register themselves and get mounted at their designated paths.

Architecture:
    DistroServer
        /api/health          - Health check
        /api/config          - Distro configuration
        /api/sessions        - Unified session list (all apps)
        /api/bridge          - Amplifier Bridge API (session creation)
        /api/memory          - Memory storage and retrieval
        /apps/<name>/...     - Mounted app routes

Apps are Python modules that expose:
    - name: str            - App identifier
    - router: APIRouter    - FastAPI router with routes
    - description: str     - Human-readable description
    - on_startup()         - Optional async startup hook
    - on_shutdown()        - Optional async shutdown hook

Shared services (session backend, etc.) are available to all apps
via `from amplifier_distro.server.services import get_services`.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# Optional bearer token scheme (auto_error=False so missing header
# doesn't raise before our logic runs).
_bearer_scheme = HTTPBearer(auto_error=False)


def _get_configured_api_key() -> str:
    """Read the server.api_key from distro config. Returns '' if unset."""
    try:
        from amplifier_distro.config import load_config

        return load_config().server.api_key
    except (ImportError, AttributeError, OSError):
        logger.debug("Could not read API key from config", exc_info=True)
        return ""


_bearer_dependency = Depends(_bearer_scheme)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = _bearer_dependency,
) -> None:
    """FastAPI dependency that enforces bearer-token auth on mutation routes.

    - If no ``server.api_key`` is configured the request passes through
      (backward-compatible / local-only use).
    - If a key IS configured the caller must supply an
      ``Authorization: Bearer <key>`` header that matches.
    """
    api_key = _get_configured_api_key()
    if not api_key:
        return  # No key configured — open access

    if credentials is None or credentials.credentials != api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


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

    def __init__(
        self,
        title: str = "Amplifier Distro",
        version: str = "0.1.0",
        dev_mode: bool = False,
    ) -> None:
        self._apps: dict[str, AppManifest] = {}
        self._dev_mode = dev_mode
        self._app = FastAPI(
            title=title,
            version=version,
            docs_url="/api/docs",
            openapi_url="/api/openapi.json",
        )
        self._core_router = APIRouter(prefix="/api", tags=["core"])
        self._setup_core_routes()
        self._setup_bridge_routes()
        self._setup_memory_routes()
        self._setup_root_redirect()
        self._app.include_router(self._core_router)

    @property
    def app(self) -> FastAPI:
        """Get the FastAPI application instance."""
        return self._app

    @property
    def apps(self) -> dict[str, AppManifest]:
        """Get registered apps."""
        return dict(self._apps)

    @property
    def dev_mode(self) -> bool:
        """Whether the server is running in dev mode."""
        return self._dev_mode

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

            except (ImportError, AttributeError):
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
            from amplifier_distro.server.stub import is_stub_mode, stub_preflight_status

            if is_stub_mode():
                return stub_preflight_status()

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

        @self._core_router.put("/config", dependencies=[Depends(verify_api_key)])
        async def update_config(request: Request) -> JSONResponse:
            """Update distro.yaml with partial config values.

            Accepts a JSON body with keys matching DistroConfig fields.
            Only provided fields are updated; others are preserved.
            """
            from pydantic import ValidationError

            from amplifier_distro.config import load_config, save_config

            body = await request.json()
            try:
                cfg = load_config()

                # Update top-level scalar fields
                if "workspace_root" in body:
                    cfg.workspace_root = body["workspace_root"]

                # Update nested identity fields
                if "identity" in body and isinstance(body["identity"], dict):
                    if "github_handle" in body["identity"]:
                        cfg.identity.github_handle = body["identity"]["github_handle"]
                    if "git_email" in body["identity"]:
                        cfg.identity.git_email = body["identity"]["git_email"]

                save_config(cfg)
                return JSONResponse(content=cfg.model_dump())
            except (ValidationError, ValueError) as e:
                logger.info("Config update rejected: %s", e)
                return JSONResponse(
                    status_code=400,
                    content={"error": str(e), "type": type(e).__name__},
                )
            except Exception as e:
                logger.warning("Config update failed: %s", e, exc_info=True)
                return JSONResponse(
                    status_code=500,
                    content={"error": str(e), "type": type(e).__name__},
                )

        @self._core_router.get("/integrations")
        async def get_integrations() -> JSONResponse:
            """Status of each integration (Slack, Voice)."""
            import os
            from pathlib import Path as _Path

            from amplifier_distro.conventions import (
                AMPLIFIER_HOME,
                KEYS_FILENAME,
            )

            keys_path = _Path(AMPLIFIER_HOME).expanduser() / KEYS_FILENAME
            keys_data: dict[str, str] = {}
            if keys_path.exists():
                import yaml as _yaml

                keys_data = _yaml.safe_load(keys_path.read_text()) or {}

            def _check_key(env_var: str) -> str:
                """Return 'configured' if key is in env or keys.yaml."""
                if os.environ.get(env_var):
                    return "configured"
                if keys_data.get(env_var):
                    return "configured"
                return "not_configured"

            integrations = {
                "slack": {
                    "name": "Slack Bridge",
                    "status": _check_key("SLACK_BOT_TOKEN"),
                    "description": "Connect Slack workspace to Amplifier",
                    "setup_url": "/apps/slack/setup-ui",
                },
                "voice": {
                    "name": "Voice Bridge",
                    "status": _check_key("OPENAI_API_KEY"),
                    "description": "Voice interface via OpenAI Realtime API",
                    "setup_url": "/apps/voice/",
                },
            }
            return JSONResponse(content=integrations)

        @self._core_router.post(
            "/test-provider", dependencies=[Depends(verify_api_key)]
        )
        async def test_provider(request: Request) -> JSONResponse:
            """Test a provider connection with a minimal API request.

            Body: {"provider": "anthropic"} or {"provider": "openai"}
            """
            import os

            import httpx

            body = await request.json()
            provider = body.get("provider", "")

            from amplifier_distro.server.stub import is_stub_mode, stub_test_provider

            if is_stub_mode():
                return JSONResponse(content=stub_test_provider(provider))

            if provider == "anthropic":
                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                if not api_key:
                    return JSONResponse(
                        content={
                            "provider": provider,
                            "ok": False,
                            "error": "ANTHROPIC_API_KEY not set",
                        }
                    )
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        resp = await client.post(
                            "https://api.anthropic.com/v1/messages",
                            headers={
                                "x-api-key": api_key,
                                "anthropic-version": "2023-06-01",
                                "content-type": "application/json",
                            },
                            json={
                                "model": "claude-sonnet-4-20250514",
                                "max_tokens": 1,
                                "messages": [{"role": "user", "content": "hi"}],
                            },
                        )
                    ok = resp.status_code == 200
                    return JSONResponse(
                        content={
                            "provider": provider,
                            "ok": ok,
                            "status_code": resp.status_code,
                        }
                    )
                except (httpx.HTTPError, OSError) as e:
                    logger.debug("Anthropic provider test failed: %s", e)
                    return JSONResponse(
                        content={
                            "provider": provider,
                            "ok": False,
                            "error": str(e),
                        }
                    )

            elif provider == "openai":
                api_key = os.environ.get("OPENAI_API_KEY", "")
                if not api_key:
                    return JSONResponse(
                        content={
                            "provider": provider,
                            "ok": False,
                            "error": "OPENAI_API_KEY not set",
                        }
                    )
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        resp = await client.get(
                            "https://api.openai.com/v1/models",
                            headers={
                                "Authorization": f"Bearer {api_key}",
                            },
                        )
                    ok = resp.status_code == 200
                    return JSONResponse(
                        content={
                            "provider": provider,
                            "ok": ok,
                            "status_code": resp.status_code,
                        }
                    )
                except (httpx.HTTPError, OSError) as e:
                    logger.debug("OpenAI provider test failed: %s", e)
                    return JSONResponse(
                        content={
                            "provider": provider,
                            "ok": False,
                            "error": str(e),
                        }
                    )
            else:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": f"Unknown provider: {provider}. "
                        "Use 'anthropic' or 'openai'."
                    },
                )

    def _setup_bridge_routes(self) -> None:
        """Set up Bridge API routes for session management."""

        @self._core_router.get("/sessions")
        async def list_sessions() -> list[dict[str, Any]]:
            """List all active sessions across all apps."""
            from amplifier_distro.server.services import get_services

            try:
                services = get_services()
            except RuntimeError:
                return []

            return [
                {
                    "session_id": s.session_id,
                    "project_id": s.project_id,
                    "working_dir": s.working_dir,
                    "is_active": s.is_active,
                    "created_by_app": s.created_by_app,
                    "description": s.description,
                }
                for s in services.backend.list_active_sessions()
            ]

        @self._core_router.post(
            "/bridge/session",
            response_model=None,
            dependencies=[Depends(verify_api_key)],
        )
        async def create_session(request: Request) -> JSONResponse:
            """Create an Amplifier session via the shared backend."""
            from amplifier_distro.server.services import get_services

            body = await request.json()
            try:
                services = get_services()
                info = await services.backend.create_session(
                    working_dir=body.get("working_dir", "."),
                    bundle_name=body.get("bundle_name"),
                    description=body.get("description", ""),
                    surface="api",
                )
                return JSONResponse(
                    content={
                        "session_id": info.session_id,
                        "project_id": info.project_id,
                        "working_dir": info.working_dir,
                    }
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Session creation failed: %s", e, exc_info=True)
                return JSONResponse(
                    status_code=500,
                    content={"error": str(e), "type": type(e).__name__},
                )

        @self._core_router.post(
            "/bridge/execute", dependencies=[Depends(verify_api_key)]
        )
        async def execute_prompt(request: Request) -> JSONResponse:
            """Execute a prompt on an existing session."""
            from amplifier_distro.server.services import get_services

            body = await request.json()
            session_id = body.get("session_id")
            prompt = body.get("prompt")
            if not session_id or not prompt:
                return JSONResponse(
                    status_code=400,
                    content={"error": "session_id and prompt are required"},
                )
            try:
                services = get_services()
                response = await services.backend.send_message(session_id, prompt)
                return JSONResponse(
                    content={
                        "session_id": session_id,
                        "response": response,
                    }
                )
            except ValueError as e:
                return JSONResponse(
                    status_code=404,
                    content={"error": str(e)},
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Prompt execution failed: %s", e, exc_info=True)
                return JSONResponse(
                    status_code=500,
                    content={"error": str(e), "type": type(e).__name__},
                )

    def _setup_memory_routes(self) -> None:
        """Set up Memory API routes for cross-interface memory storage."""

        @self._core_router.post(
            "/memory/remember", dependencies=[Depends(verify_api_key)]
        )
        async def memory_remember(request: Request) -> JSONResponse:
            """Store a memory with auto-categorization."""
            from amplifier_distro.server.memory import get_memory_service

            body = await request.json()
            text = body.get("text", "")
            if not text:
                return JSONResponse(
                    status_code=400,
                    content={"error": "text is required"},
                )
            try:
                service = get_memory_service()
                result = service.remember(text)
                return JSONResponse(content=result)
            except (RuntimeError, OSError, ValueError, KeyError) as e:
                logger.warning("Memory remember failed: %s", e, exc_info=True)
                return JSONResponse(
                    status_code=500,
                    content={"error": str(e), "type": type(e).__name__},
                )

        @self._core_router.get("/memory/recall")
        async def memory_recall(q: str = "") -> JSONResponse:
            """Search memories by content, tags, and category."""
            from amplifier_distro.server.memory import get_memory_service

            if not q:
                return JSONResponse(
                    status_code=400,
                    content={"error": "q query parameter is required"},
                )
            try:
                service = get_memory_service()
                results = service.recall(q)
                return JSONResponse(content={"matches": results, "count": len(results)})
            except (RuntimeError, OSError, ValueError, KeyError) as e:
                logger.warning("Memory recall failed: %s", e, exc_info=True)
                return JSONResponse(
                    status_code=500,
                    content={"error": str(e), "type": type(e).__name__},
                )

        @self._core_router.get("/memory/work-status")
        async def memory_work_status() -> JSONResponse:
            """Read the current work log."""
            from amplifier_distro.server.memory import get_memory_service

            try:
                service = get_memory_service()
                result = service.work_status()
                return JSONResponse(content=result)
            except (RuntimeError, OSError, ValueError, KeyError) as e:
                logger.warning("Work status retrieval failed: %s", e, exc_info=True)
                return JSONResponse(
                    status_code=500,
                    content={"error": str(e), "type": type(e).__name__},
                )

        @self._core_router.post(
            "/memory/work-log", dependencies=[Depends(verify_api_key)]
        )
        async def memory_update_work_log(request: Request) -> JSONResponse:
            """Update the work log."""
            from amplifier_distro.server.memory import get_memory_service

            body = await request.json()
            items = body.get("items", [])
            try:
                service = get_memory_service()
                result = service.update_work_log(items)
                return JSONResponse(content=result)
            except (RuntimeError, OSError, ValueError, KeyError) as e:
                logger.warning("Work log update failed: %s", e, exc_info=True)
                return JSONResponse(
                    status_code=500,
                    content={"error": str(e), "type": type(e).__name__},
                )

    def _setup_root_redirect(self) -> None:
        """Phase-aware root: landing page when ready, redirect when not."""

        _landing_page = Path(__file__).parent / "static" / "index.html"

        @self._app.get("/", response_model=None)
        async def root():
            from amplifier_distro.server.apps.settings import compute_phase

            phase = compute_phase()
            if phase == "unconfigured":
                return RedirectResponse(url="/apps/install-wizard/")
            return HTMLResponse(content=_landing_page.read_text())


def create_server(dev_mode: bool = False, **kwargs: Any) -> DistroServer:
    """Factory function to create and configure the server.

    This is the main entry point for starting the server.

    Args:
        dev_mode: If True, skip wizard and use existing environment.

    Usage:
        server = create_server()

        # Auto-discover apps
        server.discover_apps(Path("./apps"))

        # Run with uvicorn
        import uvicorn
        uvicorn.run(server.app, host="0.0.0.0", port=8400)
    """
    return DistroServer(dev_mode=dev_mode, **kwargs)
