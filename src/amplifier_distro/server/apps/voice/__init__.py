"""Voice App - Amplifier voice interface via OpenAI Realtime API.

Architecture:
    Browser (vanilla JS)
        -> WebRTC audio (Opus codec)
        -> OpenAI Realtime API (direct connection, no audio through server)
            -> Native speech-to-speech (no separate STT/TTS)
            -> Function calling for tools
        <- Audio response streamed back via WebRTC

    Backend (this module):
        GET  /           - Voice UI page
        GET  /session    - Create ephemeral client_secret from OpenAI
        POST /sdp        - Exchange WebRTC SDP offer/answer via OpenAI
        POST /tools/execute - Execute an Amplifier tool on behalf of voice
        GET  /api/status - Voice service status

Key insight: The browser connects DIRECTLY to OpenAI via WebRTC for audio.
The backend only brokers session creation (ephemeral token) and SDP exchange.
No audio flows through our server.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from amplifier_distro.server.app import AppManifest, verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter()

# OpenAI Realtime API endpoints
OPENAI_REALTIME_BASE = "https://api.openai.com/v1/realtime"
OPENAI_SESSION_ENDPOINT = f"{OPENAI_REALTIME_BASE}/sessions"

# Default system prompt when none is configured
_DEFAULT_INSTRUCTIONS = (
    "You are Amplifier, a helpful voice assistant with access to developer tools. "
    "You can run commands, search and read files, and help with coding tasks. "
    "Keep responses concise and conversational."
)

# Maximum file read size (1 MB)
_MAX_FILE_READ_BYTES = 1_048_576

# Subprocess timeout (30 seconds)
_COMMAND_TIMEOUT_SECONDS = 30

# Tool definitions for OpenAI function calling
AMPLIFIER_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "run_command",
        "description": "Execute a shell command and return its output.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "type": "function",
        "name": "search_files",
        "description": "Search for files matching a glob pattern.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match (e.g. '**/*.py').",
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Base directory to search from. Defaults to workspace root."
                    ),
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "type": "function",
        "name": "read_file",
        "description": "Read the contents of a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to read.",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "type": "function",
        "name": "web_search",
        "description": "Search the web for information.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
            },
            "required": ["query"],
        },
    },
]


def _get_openai_api_key() -> str | None:
    """Read OPENAI_API_KEY from environment.

    The server startup exports keys.yaml values into env vars,
    so we just read from os.environ.
    """
    return os.environ.get("OPENAI_API_KEY")


def _get_voice_config() -> dict[str, Any]:
    """Load voice config from distro.yaml, with safe defaults."""
    try:
        from amplifier_distro.config import load_config

        cfg = load_config()
        return {
            "voice": cfg.voice.voice,
            "model": cfg.voice.model,
            "instructions": cfg.voice.instructions,
            "tools_enabled": cfg.voice.tools_enabled,
        }
    except (ImportError, AttributeError, OSError):
        logger.debug("Could not load voice config, using defaults")
        return {
            "voice": "ash",
            "model": "gpt-4o-realtime-preview",
            "instructions": "",
            "tools_enabled": False,
        }


def _get_workspace_root() -> Path:
    """Resolve workspace root from config, falling back to home dir."""
    try:
        from amplifier_distro.config import load_config

        cfg = load_config()
        return Path(cfg.workspace_root).expanduser().resolve()
    except (ImportError, AttributeError, OSError):
        return Path.home()


@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Voice interface page."""
    # TODO: voice.html needs updating to handle tool calls from OpenAI
    # and relay them to POST /tools/execute (TASK-13)
    html_path = Path(__file__).parent / "voice.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(
        content="<h1>Amplifier Voice</h1><p>voice.html not found.</p>",
        status_code=500,
    )


@router.get("/session")
async def create_session() -> JSONResponse:
    """Create an ephemeral client secret from OpenAI Realtime API.

    Calls POST https://api.openai.com/v1/realtime/sessions to get
    a short-lived token the browser uses for WebRTC auth.

    Returns:
        JSON with client_secret.value and client_secret.expires_at
    """
    from amplifier_distro.server.stub import is_stub_mode, stub_voice_session

    if is_stub_mode():
        return JSONResponse(content=stub_voice_session())

    api_key = _get_openai_api_key()
    if not api_key:
        return JSONResponse(
            status_code=503,
            content={
                "error": "OPENAI_API_KEY not configured",
                "detail": "Set your OpenAI API key in keys.yaml or environment.",
            },
        )

    vcfg = _get_voice_config()

    instructions = vcfg["instructions"] or _DEFAULT_INSTRUCTIONS

    payload: dict[str, Any] = {
        "model": vcfg["model"],
        "voice": vcfg["voice"],
        "modalities": ["audio", "text"],
        "instructions": instructions,
    }

    if vcfg["tools_enabled"]:
        payload["tools"] = AMPLIFIER_TOOLS
        payload["tool_choice"] = "auto"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                OPENAI_SESSION_ENDPOINT,
                json=payload,
                headers=headers,
            )

        if resp.status_code != 200:
            logger.error(
                "OpenAI session creation failed: %d - %s",
                resp.status_code,
                resp.text,
            )
            return JSONResponse(
                status_code=resp.status_code,
                content={
                    "error": "OpenAI session creation failed",
                    "detail": resp.text,
                },
            )

        data = resp.json()
        logger.info("Voice session created successfully")
        return JSONResponse(content=data)

    except httpx.TimeoutException:
        logger.exception("Timeout connecting to OpenAI Realtime API")
        return JSONResponse(
            status_code=504,
            content={"error": "Timeout connecting to OpenAI"},
        )

    except httpx.HTTPError as exc:
        logger.exception("HTTP error calling OpenAI: %s", exc.__class__.__name__)
        return JSONResponse(
            status_code=502,
            content={"error": f"HTTP error: {exc}"},
        )


@router.post("/sdp", response_model=None)
async def exchange_sdp(request: Request) -> PlainTextResponse | JSONResponse:
    """Exchange WebRTC SDP offer/answer via OpenAI.

    The browser sends its SDP offer here along with an Authorization
    header containing the ephemeral token from /session.
    We relay this to OpenAI and return the SDP answer.

    Headers required:
        Authorization: Bearer <ephemeral_token>
        Content-Type: application/sdp

    Body: Raw SDP offer text

    Returns:
        SDP answer from OpenAI (text/sdp)
    """
    from amplifier_distro.server.stub import is_stub_mode, stub_voice_sdp

    if is_stub_mode():
        return PlainTextResponse(content=stub_voice_sdp(), media_type="application/sdp")

    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        return JSONResponse(
            status_code=401,
            content={"error": "Authorization header required"},
        )

    offer_sdp = await request.body()
    if not offer_sdp:
        return JSONResponse(
            status_code=400,
            content={"error": "SDP offer body required"},
        )

    vcfg = _get_voice_config()
    sdp_url = f"{OPENAI_REALTIME_BASE}?model={vcfg['model']}"

    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/sdp",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                sdp_url,
                content=offer_sdp,
                headers=headers,
            )

        if resp.status_code != 200:
            logger.error(
                "OpenAI SDP exchange failed: %d - %s",
                resp.status_code,
                resp.text,
            )
            return JSONResponse(
                status_code=resp.status_code,
                content={
                    "error": "OpenAI SDP exchange failed",
                    "detail": resp.text,
                },
            )

        logger.info("SDP exchange successful")
        return PlainTextResponse(
            content=resp.text,
            media_type="application/sdp",
        )

    except httpx.TimeoutException:
        logger.exception("Timeout during SDP exchange with OpenAI")
        return JSONResponse(
            status_code=504,
            content={"error": "Timeout during SDP exchange"},
        )

    except httpx.HTTPError as exc:
        logger.exception("HTTP error during SDP exchange: %s", exc.__class__.__name__)
        return JSONResponse(
            status_code=502,
            content={"error": f"HTTP error: {exc}"},
        )


# ------------------------------------------------------------------ #
#  Tool Execution                                                      #
# ------------------------------------------------------------------ #


async def _execute_run_command(arguments: dict[str, Any]) -> str:
    """Execute a shell command with timeout and return output."""
    command = arguments.get("command", "")
    if not command:
        return "Error: no command provided."

    workspace = _get_workspace_root()
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(workspace),
        )
        stdout, _ = await asyncio.wait_for(
            proc.communicate(),
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
        output = stdout.decode(errors="replace").strip() if stdout else ""
        if proc.returncode != 0:
            prefix = f"[exit {proc.returncode}]"
            return f"{prefix}\n{output}" if output else prefix
        return output or "(no output)"
    except TimeoutError:
        return f"Error: command timed out after {_COMMAND_TIMEOUT_SECONDS}s."
    except OSError as exc:
        return f"Error running command: {exc}"


async def _execute_search_files(arguments: dict[str, Any]) -> str:
    """Search for files matching a glob pattern."""
    pattern = arguments.get("pattern", "")
    if not pattern:
        return "Error: no pattern provided."

    base = arguments.get("path", "")
    search_root = Path(base).expanduser().resolve() if base else _get_workspace_root()

    if not search_root.is_dir():
        return f"Error: directory not found: {search_root}"

    try:
        matches = sorted(search_root.glob(pattern))[:100]  # cap results
        if not matches:
            return f"No files matching '{pattern}' in {search_root}"
        lines = [str(m.relative_to(search_root)) for m in matches]
        if len(matches) == 100:
            suffix = f"\n... ({len(matches)} shown, capped at 100)"
        else:
            suffix = ""
        return "\n".join(lines) + suffix
    except OSError as exc:
        return f"Error searching files: {exc}"


async def _execute_read_file(arguments: dict[str, Any]) -> str:
    """Read file contents with a size guard."""
    file_path = arguments.get("file_path", "")
    if not file_path:
        return "Error: no file_path provided."

    target = Path(file_path).expanduser().resolve()
    if not target.is_file():
        return f"Error: file not found: {file_path}"

    try:
        size = target.stat().st_size
        if size > _MAX_FILE_READ_BYTES:
            return (
                f"Error: file is {size:,} bytes, exceeding the "
                f"{_MAX_FILE_READ_BYTES:,} byte limit. Use run_command with "
                f"head/tail to read portions."
            )
        return target.read_text(errors="replace")
    except OSError as exc:
        return f"Error reading file: {exc}"


async def _execute_web_search(arguments: dict[str, Any]) -> str:
    """Web search stub - requires a full Amplifier session."""
    query = arguments.get("query", "")
    return (
        f"Web search for '{query}' is not available in the voice bridge. "
        "Start a full Amplifier session to use web search."
    )


_TOOL_HANDLERS: dict[str, Any] = {
    "run_command": _execute_run_command,
    "search_files": _execute_search_files,
    "read_file": _execute_read_file,
    "web_search": _execute_web_search,
}


@router.post("/tools/execute", dependencies=[Depends(verify_api_key)])
async def execute_tool(request: Request) -> JSONResponse:
    """Execute an Amplifier tool on behalf of the voice session.

    Called by the browser when OpenAI's function calling returns a tool
    invocation. The browser relays the function name and arguments here,
    we execute via the bridge, and return the result for the browser to
    send back to OpenAI.
    """
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON body."},
        )

    name: str = body.get("name", "")
    arguments: dict[str, Any] = body.get("arguments", {})

    if not name:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing 'name' field."},
        )

    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        return JSONResponse(
            status_code=400,
            content={"error": f"Unknown tool: {name}"},
        )

    logger.info("Executing voice tool: %s", name)
    try:
        result = await handler(arguments)
        return JSONResponse(content={"result": result})
    except Exception:
        logger.exception("Tool execution failed: %s", name)
        return JSONResponse(
            status_code=500,
            content={"error": f"Tool '{name}' execution failed."},
        )


@router.get("/api/status")
async def voice_status() -> dict[str, Any]:
    """Voice service status."""
    api_key = _get_openai_api_key()
    vcfg = _get_voice_config()

    return {
        "status": "ready" if api_key else "unconfigured",
        "api_key_set": bool(api_key),
        "model": vcfg["model"],
        "voice": vcfg["voice"],
        "tools_enabled": vcfg["tools_enabled"],
        "message": (
            "Voice service ready."
            if api_key
            else "OPENAI_API_KEY not set. Configure it in keys.yaml."
        ),
    }


manifest = AppManifest(
    name="voice",
    description="Amplifier voice interface via OpenAI Realtime API",
    version="0.3.0",
    router=router,
)
