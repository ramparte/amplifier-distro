"""Example App - demonstrates the app plugin pattern.

To create your own app:
1. Create a directory under server/apps/
2. Add __init__.py that exports a `manifest` AppManifest
3. Define your routes on a FastAPI APIRouter
4. The server auto-discovers and mounts your app
"""

from fastapi import APIRouter

from amplifier_distro.server.app import AppManifest

router = APIRouter()


@router.get("/")
async def index() -> dict[str, str]:
    """Example app root."""
    return {"message": "Hello from the example app", "app": "example"}


@router.get("/echo/{text}")
async def echo(text: str) -> dict[str, str]:
    """Echo back the given text."""
    return {"echo": text}


manifest = AppManifest(
    name="example",
    description="Example app demonstrating the plugin pattern",
    version="0.1.0",
    router=router,
)
