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
    DISTRO_BUNDLE_DIR,
    DISTRO_BUNDLE_FILENAME,
    HANDOFF_FILENAME,
    PROJECTS_DIR,
    TRANSCRIPT_FILENAME,
)

logger = logging.getLogger(__name__)


def _encode_cwd(working_dir: Path) -> str:
    """Encode working directory to project directory name.

    Matches the convention used by amplifier-core:
    /home/user/dev/project -> -home-user-dev-project
    """
    return str(working_dir.resolve()).replace("/", "-")


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
    # Resolved session directory on disk (set by create/resume)
    _session_dir: Path | None = field(repr=False, default=None)

    async def run(self, prompt: str) -> str:
        """Send a prompt and get the response."""
        if self._session is None:
            raise RuntimeError("Session not initialized")
        result: str = await self._session.execute(prompt)
        return result

    async def cleanup(self) -> None:
        """Clean up session resources."""
        if self._session is not None:
            try:
                await self._session.cleanup()
            except Exception:  # noqa: BLE001
                logger.warning("Error during session cleanup", exc_info=True)

    def set_approval_system(self, approval_system: Any) -> None:
        """Set the approval system on the session's coordinator."""
        if self._session is not None and hasattr(self._session, "coordinator"):
            self._session.coordinator.approval_system = approval_system

    def get_mounted(self, category: str) -> list:
        """Get mounted modules by category (e.g., 'tools', 'hooks')."""
        if self._session is not None and hasattr(self._session, "coordinator"):
            return self._session.coordinator.get_mounted(category)
        return []


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

    @staticmethod
    def _resolve_distro_bundle(bundle_name_override: str | None) -> str:
        """Resolve the bundle reference to load.

        Resolution order:
        1. Explicit *bundle_name_override* (from BridgeConfig.bundle_name)
        2. Convention-path file: ``~/.amplifier/bundles/distro.yaml``
        3. Fallback: ``bundle.active`` from distro.yaml config
        4. RuntimeError if nothing found
        """
        if bundle_name_override:
            return bundle_name_override

        # Convention path (generated by install wizard)
        path = (
            Path(AMPLIFIER_HOME).expanduser()
            / DISTRO_BUNDLE_DIR
            / DISTRO_BUNDLE_FILENAME
        )
        if path.exists():
            return str(path)

        # Fallback: check distro.yaml bundle.active setting
        from amplifier_distro.config import load_config

        try:
            config = load_config()
            active = config.bundle.active
            if active:
                logger.info(
                    "Convention bundle not found at %s; "
                    "falling back to bundle.active=%r from distro.yaml",
                    path,
                    active,
                )
                return active
        except Exception:  # noqa: BLE001
            logger.debug("Could not load distro config for bundle fallback")

        raise RuntimeError(
            f"No distro bundle found at {path} and no bundle.active "
            "configured in distro.yaml. "
            "Run the install wizard or 'amp distro init' to set up."
        )

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
        bundle_ref = self._resolve_distro_bundle(config.bundle_name)

        # 5. Get project ID and check for handoff
        project_id = self.get_project_id(config.working_dir)
        handoff = await self.get_handoff(project_id)
        inject = list(config.inject_context or [])
        if handoff:
            inject.append(f"Previous session context:\n{handoff.summary}")

        # 6. Load and prepare bundle
        registry = BundleRegistry()
        try:
            bundle = await load_bundle(bundle_ref, registry=registry)
        except Exception as e:
            raise RuntimeError(
                f"Failed to load distro bundle at {bundle_ref}: {e}\n"
                "If you edited this file manually, check for YAML syntax errors.\n"
                "To regenerate: amp distro init"
            ) from e
        prepared = await bundle.prepare()

        # 6b. Inject providers into mount plan if bundle doesn't have them.
        # User bundles (e.g. my-amplifier) typically omit providers; the app
        # layer adds the provider the user selected.  BridgeConfig carries that.
        self._inject_providers(prepared.mount_plan, config.provider_preferences)

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

        sid = session.coordinator.session_id
        session_dir = (
            Path(AMPLIFIER_HOME).expanduser()
            / PROJECTS_DIR
            / _encode_cwd(config.working_dir)
            / "sessions"
            / sid
        )

        logger.info(
            "Session created: id=%s project=%s bundle=%s",
            sid,
            project_id,
            bundle_ref,
        )

        return SessionHandle(
            session_id=sid,
            project_id=project_id,
            working_dir=config.working_dir,
            _session=session,
            _session_dir=session_dir,
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
            # Sessions live under <project_dir>/sessions/<session_id>/
            sessions_subdir = project_dir / "sessions"
            search_dir = sessions_subdir if sessions_subdir.is_dir() else project_dir
            for candidate in search_dir.iterdir():
                if not candidate.is_dir():
                    continue
                if candidate.name == session_id or candidate.name.startswith(
                    session_id
                ):
                    matches.append((project_dir.name, candidate))

        if not matches:
            raise FileNotFoundError(f"Session not found: {session_id}")
        if len(matches) > 1:
            # Prefer exact match over prefix matches (sub-sessions share UUID prefix)
            exact = [m for m in matches if m[1].name == session_id]
            if len(exact) == 1:
                matches = exact
            else:
                ids = [m[1].name for m in matches]
                raise ValueError(
                    f"Ambiguous session prefix '{session_id}' matches: {ids}"
                )

        project_id, session_dir = matches[0]
        logger.info(
            "Found session to resume: id=%s project=%s dir=%s",
            session_id,
            project_id,
            session_dir,
        )

        # 2. Load foundation
        load_bundle, BundleRegistry = _require_foundation()

        # 3. Determine bundle
        bundle_ref = self._resolve_distro_bundle(config.bundle_name)

        # 4. Load and prepare bundle
        registry = BundleRegistry()
        try:
            bundle = await load_bundle(bundle_ref, registry=registry)
        except Exception as e:
            raise RuntimeError(
                f"Failed to load distro bundle at {bundle_ref}: {e}\n"
                "If you edited this file manually, check for YAML syntax errors.\n"
                "To regenerate: amp distro init"
            ) from e
        prepared = await bundle.prepare()

        # 4b. Inject providers (same as create_session)
        self._inject_providers(prepared.mount_plan, config.provider_preferences)

        # 5. Create protocol adapters (same as create_session)
        from amplifier_distro.bridge_protocols import (
            BridgeApprovalSystem,
            BridgeDisplaySystem,
            BridgeStreamingHook,
        )

        display = config.display or BridgeDisplaySystem()
        approval = BridgeApprovalSystem(auto_approve=True)
        streaming = BridgeStreamingHook(on_event=config.on_stream)

        # 6. Create session (preserving original session ID)
        session = await prepared.create_session(
            session_id=session_id,
            is_resumed=True,
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
        #
        # Fixes applied (issues #23, #25):
        #  - Stream file line-by-line instead of read_text() to avoid
        #    loading multi-MB transcripts into memory at once.
        #  - Pass through all message fields (the transcript is self-
        #    authored data; the context module handles token budgeting
        #    via compaction at request time).
        #  - Strip orphaned tool messages that would cause provider 400s
        #    if the session was interrupted mid-tool-call.
        transcript_file = session_dir / TRANSCRIPT_FILENAME
        if transcript_file.exists():
            try:
                messages: list[dict[str, Any]] = []
                with transcript_file.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except (json.JSONDecodeError, ValueError):
                            # Skip malformed lines (e.g. truncated by crash)
                            logger.debug("Skipping malformed transcript line")
                            continue
                        if isinstance(entry, dict) and entry.get("role"):
                            messages.append(entry)

                # Strip orphaned tool results from the front (from a
                # session that was interrupted mid-tool-call sequence).
                # Orphaned tool messages without a preceding
                # assistant+tool_calls cause provider 400 errors.
                while messages and messages[0].get("role") == "tool":
                    messages.pop(0)

                # Strip trailing assistant+tool_calls whose tool results
                # were never written (session crashed mid-execution).
                while (
                    messages
                    and messages[-1].get("role") == "assistant"
                    and messages[-1].get("tool_calls")
                ):
                    messages.pop()

                if messages:
                    try:
                        await session.coordinator.context.set_messages(messages)
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
            bundle_ref,
        )

        return SessionHandle(
            session_id=session.coordinator.session_id,
            project_id=project_id,
            working_dir=config.working_dir,
            _session=session,
            _session_dir=session_dir,
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
        if handle._session_dir:
            session_dir = handle._session_dir
        else:
            # Fallback: scan for session directory (handles both old and new paths)
            session_dir = (
                Path(AMPLIFIER_HOME).expanduser()
                / PROJECTS_DIR
                / handle.project_id
                / "sessions"
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
        """Find most recent handoff for project.

        Searches all project directories (which are encoded CWD paths)
        and looks inside their ``sessions/`` subdirectory for handoff files.
        Matches project_id as a substring of the directory name so that
        logical names like ``"amplifier-distro"`` match encoded paths like
        ``-home-user-dev-amplifier-distro``.
        """
        projects_path = Path(AMPLIFIER_HOME).expanduser() / PROJECTS_DIR
        if not projects_path.exists():
            return None

        # Find project directories that contain the project_id
        project_dirs: list[Path] = []
        for d in projects_path.iterdir():
            if not d.is_dir():
                continue
            if d.name == project_id or project_id in d.name:
                project_dirs.append(d)

        if not project_dirs:
            return None

        # Search for most recent handoff across matching project dirs
        for project_dir in project_dirs:
            sessions_subdir = project_dir / "sessions"
            search_dir = sessions_subdir if sessions_subdir.is_dir() else project_dir

            sessions = sorted(
                (d for d in search_dir.iterdir() if d.is_dir()),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
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

    def _inject_providers(
        self,
        mount_plan: dict[str, Any],
        provider_preferences: list[dict[str, str]] | None,
    ) -> None:
        """Inject provider modules into mount_plan when the bundle has none.

        Many user bundles (especially personal ones composed via includes)
        don't carry a ``providers:`` section -- they rely on the app layer
        to decide which provider to mount.  This method bridges that gap
        by translating ``BridgeConfig.provider_preferences`` into concrete
        mount-plan entries.

        If the bundle *already* has providers, this is a no-op so we never
        override explicit bundle-level provider configuration.
        """
        # Nothing to do if bundle already has providers
        if mount_plan.get("providers"):
            return

        from amplifier_distro.features import PROVIDERS, resolve_provider

        prefs = provider_preferences or []
        if not prefs:
            # Fall back to distro.yaml default provider
            distro = self._load_distro_config()
            default = distro.get("default_provider", "anthropic")
            prefs = [{"provider": default}]

        providers: list[dict[str, Any]] = []
        for i, pref in enumerate(prefs):
            raw_name = pref.get("provider", "")
            # resolve_provider returns canonical key (e.g. "anthropic")
            canonical = resolve_provider(raw_name)
            info = PROVIDERS.get(canonical)
            if info is None:
                logger.warning(
                    "Unknown provider '%s' (resolved: '%s'), skipping",
                    raw_name,
                    canonical,
                )
                continue

            entry: dict[str, Any] = {"module": info.module_id}
            if info.source_url:
                entry["source"] = info.source_url
            cfg: dict[str, Any] = {"priority": i + 1}

            model = pref.get("model")
            if model:
                cfg["default_model"] = model
            elif info.default_model:
                cfg["default_model"] = info.default_model

            if info.base_url:
                cfg["base_url"] = info.base_url

            entry["config"] = cfg
            providers.append(entry)

        if providers:
            mount_plan["providers"] = providers
            logger.info(
                "Injected %d provider(s) into mount plan: %s",
                len(providers),
                [p["module"] for p in providers],
            )

    def _load_distro_config(self) -> dict[str, Any]:
        """Load distro.yaml, cached."""
        if self._config is None:
            from amplifier_distro.config import load_config

            config = load_config()
            self._config = config.model_dump()
        return self._config
