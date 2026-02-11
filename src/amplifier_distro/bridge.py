"""Amplifier Bridge - Session Creation API

The Bridge is the single interface through which all Amplifier surfaces
(CLI, TUI, Voice, Web, Server) create and manage sessions. It composes
amplifier-foundation primitives into a clean, distro-aware API.

Architecture:
    Interface (CLI/TUI/Voice/Web)
        -> Bridge API (this module)
            -> amplifier-foundation (load_bundle, prepare, create_session)
            -> distro.yaml (config)

No interface should import amplifier-core or amplifier-foundation directly
for session creation. They go through the Bridge.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

    from amplifier_core.session import (
        AmplifierSession,  # type: ignore[import-not-found]
    )

    from amplifier_distro.bridge_protocols import BridgeDisplaySystem

from amplifier_distro.conventions import (
    AMPLIFIER_HOME,
    HANDOFF_FILENAME,
    PROJECTS_DIR,
    TRANSCRIPT_FILENAME,
)

logger = logging.getLogger(__name__)


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
    display: BridgeDisplaySystem | None = None
    # Streaming callback
    on_stream: Callable[[str, dict[str, Any]], Any] | None = None


@dataclass
class SessionHandle:
    """A handle to an active Amplifier session.

    This is what the Bridge returns. Interfaces use this to interact
    with the session without needing to know about amplifier-core internals.
    """

    session_id: str
    project_id: str
    working_dir: Path
    # The actual AmplifierSession (typed via TYPE_CHECKING to avoid hard dep on core)
    _session: AmplifierSession | None = field(repr=False, default=None)

    async def run(self, prompt: str) -> str:
        """Send a prompt and get the response."""
        if self._session is None:
            raise RuntimeError("Session not initialized")
        result: str = await self._session.execute(prompt)
        return result

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        """Send a prompt and stream the response."""
        if self._session is None:
            raise RuntimeError("Session not initialized")
        async for chunk in self._session.run_streaming(prompt):
            yield chunk

    async def cleanup(self) -> None:
        """Clean up session resources."""
        if self._session is not None:
            try:
                await self._session.cleanup()
            except Exception:  # noqa: BLE001
                logger.warning("Error during session cleanup", exc_info=True)


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
        slug. E.g., ~/dev/amplifier-distro -> "amplifier-distro"
        """
        ...


def _require_foundation() -> tuple[Any, Any]:
    """Import amplifier-foundation, raising a clear error if missing.

    Returns (load_bundle, BundleRegistry) tuple.
    """
    try:
        from amplifier_foundation import load_bundle  # type: ignore[import-not-found]
        from amplifier_foundation.registry import (  # type: ignore[import-not-found]
            BundleRegistry,
        )
    except ImportError as e:
        raise RuntimeError(
            "amplifier-foundation is not installed. "
            "Install with: pip install amplifier-foundation"
        ) from e
    return load_bundle, BundleRegistry


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

        # 3. Import foundation (late, so server boots without it)
        load_bundle, BundleRegistry = _require_foundation()

        # 4. Determine bundle
        bundle_name = config.bundle_name or distro.get("bundle", {}).get(
            "active", "my-amplifier"
        )

        # 5. Get project ID and check for handoff
        project_id = self.get_project_id(config.working_dir)
        handoff = await self.get_handoff(project_id)
        inject = list(config.inject_context or [])
        if handoff:
            inject.append(f"Previous session context:\n{handoff.summary}")

        # 6. Load and prepare bundle
        registry = BundleRegistry()
        bundle = await load_bundle(bundle_name, registry=registry)
        prepared = await bundle.prepare()

        # 7. Create protocol adapters
        from amplifier_distro.bridge_protocols import (
            BridgeApprovalSystem,
            BridgeDisplaySystem,
            BridgeStreamingHook,
        )

        display = config.display or BridgeDisplaySystem()
        approval = BridgeApprovalSystem(auto_approve=True)
        streaming = BridgeStreamingHook(on_event=config.on_stream)

        # 8. Create session
        session = await prepared.create_session(
            approval_system=approval,
            display_system=display,
            session_cwd=config.working_dir,
        )

        # 9. Register streaming hook for all events
        try:
            from amplifier_core.events import (  # type: ignore[import-not-found]
                ALL_EVENTS,
            )

            for event in list(ALL_EVENTS):
                session.coordinator.hooks.register(
                    event=event,
                    handler=streaming,
                    priority=100,
                    name=f"bridge-streaming:{event}",
                )
        except (ImportError, AttributeError):
            logger.debug(
                "Could not register streaming hooks"
                " (amplifier-core events not available)"
            )

        # 10. Inject handoff and additional context into session
        if inject:
            try:
                context_text = "\n\n".join(inject)
                session.coordinator.context.add_messages(
                    [{"role": "system", "content": context_text}]
                )
                logger.debug("Injected %d context items into session", len(inject))
            except (AttributeError, TypeError):
                logger.debug(
                    "Could not inject context (coordinator context API not available)"
                )

        logger.info(
            "Session created: id=%s project=%s bundle=%s",
            session.coordinator.session_id,
            project_id,
            bundle_name,
        )

        return SessionHandle(
            session_id=session.coordinator.session_id,
            project_id=project_id,
            working_dir=config.working_dir,
            _session=session,
        )

    async def resume_session(
        self, session_id: str, config: BridgeConfig | None = None
    ) -> SessionHandle:
        """Resume an existing session.

        Finds the session directory by ID (or prefix), loads the bundle,
        creates a new session, and injects the previous transcript as context.
        """
        if config is None:
            config = BridgeConfig()

        # 1. Find the session directory
        projects_path = Path(AMPLIFIER_HOME).expanduser() / PROJECTS_DIR
        if not projects_path.exists():
            raise FileNotFoundError(f"No projects directory found at {projects_path}")

        matches: list[tuple[str, Path]] = []
        for project_dir in projects_path.iterdir():
            if not project_dir.is_dir():
                continue
            for candidate in project_dir.iterdir():
                if not candidate.is_dir():
                    continue
                if candidate.name == session_id or candidate.name.startswith(
                    session_id
                ):
                    matches.append((project_dir.name, candidate))

        if not matches:
            raise FileNotFoundError(f"Session not found: {session_id}")
        if len(matches) > 1:
            ids = [m[1].name for m in matches]
            raise ValueError(f"Ambiguous session prefix '{session_id}' matches: {ids}")

        project_id, session_dir = matches[0]
        logger.info(
            "Found session to resume: id=%s project=%s dir=%s",
            session_id,
            project_id,
            session_dir,
        )

        # 2. Load foundation
        load_bundle, BundleRegistry = _require_foundation()

        # 3. Determine bundle from distro config
        distro = self._load_distro_config()
        bundle_name = config.bundle_name or distro.get("bundle", {}).get(
            "active", "my-amplifier"
        )

        # 4. Load and prepare bundle
        registry = BundleRegistry()
        bundle = await load_bundle(bundle_name, registry=registry)
        prepared = await bundle.prepare()

        # 5. Create protocol adapters (same as create_session)
        from amplifier_distro.bridge_protocols import (
            BridgeApprovalSystem,
            BridgeDisplaySystem,
            BridgeStreamingHook,
        )

        display = config.display or BridgeDisplaySystem()
        approval = BridgeApprovalSystem(auto_approve=True)
        streaming = BridgeStreamingHook(on_event=config.on_stream)

        # 6. Create session
        session = await prepared.create_session(
            approval_system=approval,
            display_system=display,
            session_cwd=config.working_dir,
        )

        # 7. Register streaming hooks
        try:
            from amplifier_core.events import (  # type: ignore[import-not-found]
                ALL_EVENTS,
            )

            for event in list(ALL_EVENTS):
                session.coordinator.hooks.register(
                    event=event,
                    handler=streaming,
                    priority=100,
                    name=f"bridge-streaming:{event}",
                )
        except (ImportError, AttributeError):
            logger.debug(
                "Could not register streaming hooks"
                " (amplifier-core events not available)"
            )

        # 8. Load previous transcript and inject as context
        transcript_file = session_dir / TRANSCRIPT_FILENAME
        if transcript_file.exists():
            try:
                messages = []
                for line in transcript_file.read_text().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    role = entry.get("role", "user")
                    content = entry.get("content", "")
                    if content:
                        messages.append({"role": role, "content": content})

                if messages:
                    try:
                        session.coordinator.context.add_messages(messages)
                        logger.info(
                            "Injected %d messages from previous transcript",
                            len(messages),
                        )
                    except (AttributeError, TypeError):
                        logger.debug(
                            "Could not inject transcript messages"
                            " (context API not available)"
                        )
            except (OSError, json.JSONDecodeError, KeyError, ValueError):
                logger.warning(
                    "Failed to load transcript from %s",
                    transcript_file,
                    exc_info=True,
                )
        else:
            logger.debug("No transcript found at %s", transcript_file)

        logger.info(
            "Session resumed: id=%s project=%s bundle=%s",
            session.coordinator.session_id,
            project_id,
            bundle_name,
        )

        return SessionHandle(
            session_id=session.coordinator.session_id,
            project_id=project_id,
            working_dir=config.working_dir,
            _session=session,
        )

    async def end_session(self, handle: SessionHandle) -> HandoffSummary | None:
        """End session, clean up resources, and write handoff.

        Uses a simple template-based handoff (no LLM call) that records
        session metadata and can be enhanced later.
        """
        # 1. Clean up the session
        await handle.cleanup()

        # 2. Generate handoff summary
        timestamp = datetime.now(UTC).isoformat()
        session_dir = (
            Path(AMPLIFIER_HOME).expanduser()
            / PROJECTS_DIR
            / handle.project_id
            / handle.session_id
        )

        # 3. Build template-based handoff markdown
        summary_lines = [
            "# Session Handoff",
            "",
            f"- **Session ID**: {handle.session_id}",
            f"- **Project**: {handle.project_id}",
            f"- **Timestamp**: {timestamp}",
            f"- **Working Directory**: {handle.working_dir}",
            "",
            "## Summary",
            "",
            "Session ended. See transcript for details.",
        ]

        # Note transcript location if it exists
        transcript_file = session_dir / TRANSCRIPT_FILENAME
        if session_dir.exists() and transcript_file.exists():
            summary_lines += [
                "",
                "## Transcript",
                "",
                f"Transcript available at: `{transcript_file}`",
            ]

        summary_text = "\n".join(summary_lines) + "\n"

        # 4. Write handoff.md to session directory
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            handoff_path = session_dir / HANDOFF_FILENAME
            handoff_path.write_text(summary_text)
            logger.info("Handoff written to %s", handoff_path)
        except OSError:
            logger.warning(
                "Failed to write handoff to %s",
                session_dir,
                exc_info=True,
            )

        # 5. Return HandoffSummary
        return HandoffSummary(
            session_id=handle.session_id,
            project_id=handle.project_id,
            summary=summary_text,
            key_decisions=[],
            open_questions=[],
            files_modified=[],
            timestamp=timestamp,
        )

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
            # Not under workspace - use directory name
            return cwd.name

    def _load_distro_config(self) -> dict[str, Any]:
        """Load distro.yaml, cached."""
        if self._config is None:
            from amplifier_distro.config import load_config

            config = load_config()
            self._config = config.model_dump()
        return self._config
