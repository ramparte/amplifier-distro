"""Amplifier Bridge - Session Creation API

The Bridge is the single interface through which all Amplifier surfaces
(CLI, TUI, Voice, Web, Server) create and manage sessions. It composes
amplifier-foundation primitives into a clean, distro-aware API.

Architecture:
    Interface (CLI/TUI/Voice/Web)
        → Bridge API (this module)
            → amplifier-foundation (load_bundle, prepare, create_session)
            → distro.yaml (config)

No interface should import amplifier-core or amplifier-foundation directly
for session creation. They go through the Bridge.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# Convention constants — will move to conventions.py when that module exists
AMPLIFIER_HOME = "~/.amplifier"
PROJECTS_DIR = "projects"
HANDOFF_FILENAME = "handoff.md"


@dataclass
class BridgeConfig:
    """Configuration for creating a session through the Bridge."""

    # Working directory (determines project context)
    working_dir: Path = field(default_factory=Path.cwd)
    # Bundle override (None = use distro.yaml default)
    bundle_name: str | None = None
    # Provider overrides
    provider_preferences: list[dict[str, str]] | None = None
    # Additional context to inject (e.g., handoff from previous session)
    inject_context: list[str] | None = None
    # Whether to run preflight before creating session
    run_preflight: bool = True
    # Session display/UI callbacks (interface-specific)
    display: Any = None
    # Streaming callback
    on_stream: Any = None


@dataclass
class SessionHandle:
    """A handle to an active Amplifier session.

    This is what the Bridge returns. Interfaces use this to interact
    with the session without needing to know about amplifier-core internals.
    """

    session_id: str
    project_id: str
    working_dir: Path
    # The actual AmplifierSession (typed as Any to avoid hard dep on core)
    _session: Any = field(repr=False, default=None)

    async def run(self, prompt: str) -> str:
        """Send a prompt and get the response."""
        if self._session is None:
            raise RuntimeError("Session not initialized")
        # Delegate to the actual session's orchestrator
        result: str = await self._session.run(prompt)
        return result

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        """Send a prompt and stream the response."""
        if self._session is None:
            raise RuntimeError("Session not initialized")
        async for chunk in self._session.run_streaming(prompt):
            yield chunk


@dataclass
class HandoffSummary:
    """Summary generated at session end for continuity."""

    session_id: str
    project_id: str
    summary: str
    key_decisions: list[str]
    open_questions: list[str]
    files_modified: list[str]
    timestamp: str


@runtime_checkable
class AmplifierBridge(Protocol):
    """The Bridge protocol - what every interface calls."""

    async def create_session(self, config: BridgeConfig | None = None) -> SessionHandle:
        """Create a new Amplifier session.

        This is the main entry point. It:
        1. Reads distro.yaml for defaults
        2. Runs preflight checks (if enabled)
        3. Loads and prepares the bundle
        4. Injects handoff context from previous session (if available)
        5. Creates the AmplifierSession
        6. Returns a SessionHandle
        """
        ...

    async def resume_session(
        self, session_id: str, config: BridgeConfig | None = None
    ) -> SessionHandle:
        """Resume an existing session by ID."""
        ...

    async def end_session(self, handle: SessionHandle) -> HandoffSummary | None:
        """End a session and generate handoff.

        This:
        1. Generates a handoff summary (if session had meaningful work)
        2. Writes handoff.md to the session directory
        3. Cleans up resources
        4. Returns the summary (or None if session was trivial)
        """
        ...

    async def get_handoff(self, project_id: str) -> HandoffSummary | None:
        """Get the most recent handoff for a project.

        Looks for handoff.md in the most recent session directory
        for the given project.
        """
        ...

    def get_config(self) -> dict[str, Any]:
        """Get the current distro configuration."""
        ...

    def get_project_id(self, working_dir: Path | None = None) -> str:
        """Derive project ID from working directory.

        Uses workspace_root from distro.yaml to determine the project
        slug. E.g., ~/dev/amplifier-distro → "amplifier-distro"
        """
        ...


class LocalBridge:
    """Concrete Bridge implementation for local usage.

    This is the standard implementation that reads local distro.yaml,
    uses local filesystem for sessions, and calls amplifier-foundation
    directly.

    The distro server wraps this same bridge and exposes it over HTTP
    for remote interfaces.
    """

    def __init__(self) -> None:
        self._config: dict[str, Any] | None = None

    async def create_session(self, config: BridgeConfig | None = None) -> SessionHandle:
        """Create a session using local amplifier-foundation."""
        if config is None:
            config = BridgeConfig()

        # 1. Load distro config
        distro = self._load_distro_config()

        # 2. Run preflight (if enabled)
        if config.run_preflight and distro.get("preflight", {}).get("enabled", True):
            from amplifier_distro.preflight import run_preflight

            report = run_preflight()
            if not report.passed and distro.get("preflight", {}).get("mode") == "block":
                failures = [c.message for c in report.checks if not c.passed]
                raise RuntimeError(f"Preflight failed: {'; '.join(failures)}")

        # 3. Determine bundle
        bundle_name = config.bundle_name or distro.get("bundle", {}).get(
            "active", "my-amplifier"
        )

        # 4. Get project ID
        project_id = self.get_project_id(config.working_dir)

        # 5. Check for handoff from previous session
        handoff = await self.get_handoff(project_id)
        inject = list(config.inject_context or [])
        if handoff:
            inject.append(f"Previous session context:\n{handoff.summary}")

        # 6. Load bundle and create session
        # NOTE: Actual amplifier-foundation integration goes here.
        # For now, this is the API contract. Implementation requires
        # amplifier-foundation imports which we defer until runtime.
        _ = bundle_name  # used when foundation integration lands
        _ = inject  # used when foundation integration lands
        session_id = f"bridge-{project_id}-placeholder"

        return SessionHandle(
            session_id=session_id,
            project_id=project_id,
            working_dir=config.working_dir,
            _session=None,  # Will be real AmplifierSession
        )

    async def resume_session(
        self, session_id: str, config: BridgeConfig | None = None
    ) -> SessionHandle:
        """Resume an existing session."""
        raise NotImplementedError("Session resume not yet implemented")

    async def end_session(self, handle: SessionHandle) -> HandoffSummary | None:
        """End session and write handoff."""
        # TODO: Generate summary using LLM
        # TODO: Write handoff.md to session directory
        return None

    async def get_handoff(self, project_id: str) -> HandoffSummary | None:
        """Find most recent handoff for project."""
        projects_path = Path(AMPLIFIER_HOME).expanduser() / PROJECTS_DIR / project_id
        if not projects_path.exists():
            return None

        # Find most recent session with a handoff
        sessions = sorted(
            projects_path.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for session_dir in sessions:
            handoff_file = session_dir / HANDOFF_FILENAME
            if handoff_file.exists():
                content = handoff_file.read_text()
                return HandoffSummary(
                    session_id=session_dir.name,
                    project_id=project_id,
                    summary=content,
                    key_decisions=[],
                    open_questions=[],
                    files_modified=[],
                    timestamp=str(session_dir.stat().st_mtime),
                )
        return None

    def get_config(self) -> dict[str, Any]:
        """Get distro config as dict."""
        return self._load_distro_config()

    def get_project_id(self, working_dir: Path | None = None) -> str:
        """Derive project ID from working directory."""
        cwd = working_dir or Path.cwd()
        distro = self._load_distro_config()
        workspace = Path(distro.get("workspace_root", "~/dev")).expanduser()

        try:
            relative = cwd.relative_to(workspace)
            # First component is the project
            return str(relative.parts[0]) if relative.parts else cwd.name
        except ValueError:
            # Not under workspace — use directory name
            return cwd.name

    def _load_distro_config(self) -> dict[str, Any]:
        """Load distro.yaml, cached."""
        if self._config is None:
            from amplifier_distro.config import load_config

            config = load_config()
            self._config = config.model_dump()
        return self._config
