"""Server-level session backend - shared across all apps.

The SessionBackend protocol defines how any server app (web-chat, Slack,
voice, etc.) creates and interacts with Amplifier sessions. The server
owns ONE backend instance and shares it with all apps.

Implementations:
- MockBackend: Echo/canned responses (testing, dev/simulator mode)
- BridgeBackend: Real sessions via LocalBridge (production)

History: Originally lived in server/apps/slack/backend.py. Promoted to
server level so all apps share a single session pool.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class SessionInfo:
    """Information about a backend session."""

    session_id: str
    project_id: str = ""
    working_dir: str = ""
    is_active: bool = True
    # Which app created this session (e.g., "web-chat", "slack", "voice")
    created_by_app: str = ""
    description: str = ""


@runtime_checkable
class SessionBackend(Protocol):
    """Protocol for Amplifier session interaction.

    This is the contract that all session backends implement.
    Apps get a backend instance from ServerServices and use it
    to create, message, and manage sessions.
    """

    async def create_session(
        self,
        working_dir: str = "~",
        bundle_name: str | None = None,
        description: str = "",
    ) -> SessionInfo:
        """Create a new Amplifier session. Returns session info."""
        ...

    async def send_message(self, session_id: str, message: str) -> str:
        """Send a message to a session. Returns the response text."""
        ...

    async def end_session(self, session_id: str) -> None:
        """End a session and clean up."""
        ...

    async def get_session_info(self, session_id: str) -> SessionInfo | None:
        """Get info about an active session."""
        ...

    def list_active_sessions(self) -> list[SessionInfo]:
        """List all active sessions managed by this backend."""
        ...


class MockBackend:
    """Mock backend for testing and simulation.

    Returns echo responses or configurable canned responses.
    Tracks all interactions for test assertions.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._session_counter: int = 0
        self._message_history: dict[str, list[dict[str, str]]] = {}
        # Configurable response handler
        self._response_fn: Any = None
        # Recorded calls for test assertions
        self.calls: list[dict[str, Any]] = []

    def set_response_fn(self, fn: Any) -> None:
        """Set a custom response function: (session_id, message) -> response."""
        self._response_fn = fn

    async def create_session(
        self,
        working_dir: str = "~",
        bundle_name: str | None = None,
        description: str = "",
    ) -> SessionInfo:
        self._session_counter += 1
        session_id = f"mock-session-{self._session_counter:04d}"
        info = SessionInfo(
            session_id=session_id,
            project_id=f"mock-project-{self._session_counter}",
            working_dir=working_dir,
            is_active=True,
            description=description,
        )
        self._sessions[session_id] = info
        self._message_history[session_id] = []
        self.calls.append(
            {
                "method": "create_session",
                "working_dir": working_dir,
                "bundle_name": bundle_name,
                "description": description,
                "result": session_id,
            }
        )
        return info

    async def send_message(self, session_id: str, message: str) -> str:
        info = self._sessions.get(session_id)
        if info is None or not info.is_active:
            raise ValueError(f"Unknown session: {session_id}")

        self._message_history[session_id].append({"role": "user", "content": message})
        self.calls.append(
            {
                "method": "send_message",
                "session_id": session_id,
                "message": message,
            }
        )

        # Use custom response function if set
        if self._response_fn:
            response = self._response_fn(session_id, message)
        else:
            response = f"[Mock response to: {message}]"

        self._message_history[session_id].append(
            {"role": "assistant", "content": response}
        )
        return response

    async def end_session(self, session_id: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id].is_active = False
        self.calls.append({"method": "end_session", "session_id": session_id})

    async def get_session_info(self, session_id: str) -> SessionInfo | None:
        return self._sessions.get(session_id)

    def list_active_sessions(self) -> list[SessionInfo]:
        return [s for s in self._sessions.values() if s.is_active]

    def get_message_history(self, session_id: str) -> list[dict[str, str]]:
        """Get the full message history for a session (testing helper)."""
        return self._message_history.get(session_id, [])


class BridgeBackend:
    """Real backend using LocalBridge for Amplifier sessions.

    This connects to the actual Amplifier runtime via the distro bridge.
    Used in production mode.

    NOTE: Requires amplifier-foundation to be available at runtime.
    """

    def __init__(self) -> None:
        from amplifier_distro.bridge import LocalBridge

        self._bridge = LocalBridge()
        self._sessions: dict[str, Any] = {}  # session_id -> SessionHandle
        self._reconnect_locks: dict[str, asyncio.Lock] = {}
        # Per-session FIFO queues for serializing handle.run() calls
        self._session_queues: dict[str, asyncio.Queue] = {}
        # Worker tasks draining each session queue
        self._worker_tasks: dict[str, asyncio.Task] = {}
        # Tombstone: sessions that were intentionally ended (blocks reconnect)
        self._ended_sessions: set[str] = set()

    async def create_session(
        self,
        working_dir: str = "~",
        bundle_name: str | None = None,
        description: str = "",
    ) -> SessionInfo:
        from pathlib import Path

        from amplifier_distro.bridge import BridgeConfig

        config = BridgeConfig(
            working_dir=Path(working_dir).expanduser(),
            bundle_name=bundle_name,
            run_preflight=False,  # Server already validated
        )
        handle = await self._bridge.create_session(config)
        self._sessions[handle.session_id] = handle

        # Pre-start the session worker so the first message doesn't pay
        # the task-creation overhead, and so the worker is available for
        # reconnect paths that also route through the queue.
        queue: asyncio.Queue = asyncio.Queue()
        self._session_queues[handle.session_id] = queue
        self._worker_tasks[handle.session_id] = asyncio.create_task(
            self._session_worker(handle.session_id)
        )

        return SessionInfo(
            session_id=handle.session_id,
            project_id=handle.project_id,
            working_dir=str(handle.working_dir),
            is_active=True,
            description=description,
        )

    async def send_message(self, session_id: str, message: str) -> str:
        handle = self._sessions.get(session_id)
        if handle is None:
            # Session handle lost (server restart). Use per-session lock
            # to prevent concurrent reconnects for the same session_id.
            lock = self._reconnect_locks.setdefault(session_id, asyncio.Lock())
            try:
                async with lock:
                    # Double-check: another coroutine may have reconnected
                    # while we waited for the lock.
                    handle = self._sessions.get(session_id)
                    if handle is None:
                        handle = await self._reconnect(session_id)
            finally:
                # Clean up lock entry on both success and failure paths
                self._reconnect_locks.pop(session_id, None)

        # Route through the per-session queue so concurrent calls serialize
        if session_id not in self._session_queues:
            self._session_queues[session_id] = asyncio.Queue()
        if (
            session_id not in self._worker_tasks
            or self._worker_tasks[session_id].done()
        ):
            self._worker_tasks[session_id] = asyncio.create_task(
                self._session_worker(session_id)
            )

        loop = asyncio.get_event_loop()
        future: asyncio.Future[str] = loop.create_future()
        await self._session_queues[session_id].put((message, future))
        return await future

    async def _reconnect(self, session_id: str) -> Any:
        """Attempt to resume a session whose handle was lost (e.g. after restart).

        On success the handle is cached so subsequent messages don't pay
        the resume cost again.  On failure the original ValueError is raised
        so callers see the same error they would have before.
        """
        if session_id in self._ended_sessions:
            raise ValueError(
                f"Session {session_id} was intentionally ended"
                " and cannot be reconnected"
            )
        logger.info(f"Attempting to reconnect lost session {session_id}")
        try:
            handle = await self._bridge.resume_session(session_id)
            self._sessions[session_id] = handle
            logger.info(f"Reconnected session {session_id}")
            return handle
        except (FileNotFoundError, ValueError, RuntimeError, OSError) as err:
            logger.warning(f"Failed to reconnect session {session_id}", exc_info=True)
            raise ValueError(f"Unknown session: {session_id}") from err

    async def _session_worker(self, session_id: str) -> None:
        """Drain the session queue, running handle.run() calls sequentially.

        Receives (message, future) tuples from the queue.  A ``None``
        sentinel signals the worker to exit cleanly (used by end_session
        and stop).  On CancelledError, drains remaining futures with
        cancellation so callers don't wait forever.
        """
        queue = self._session_queues[session_id]
        while True:
            try:
                item = await queue.get()
            except asyncio.CancelledError:
                # Drain remaining items and cancel their futures
                while not queue.empty():
                    try:
                        pending_item = queue.get_nowait()
                        if pending_item is not None:
                            _, fut = pending_item
                            if not fut.done():
                                fut.cancel()
                        queue.task_done()
                    except asyncio.QueueEmpty:
                        break
                raise

            if item is None:
                # Sentinel — exit cleanly
                queue.task_done()
                break

            message, future = item
            try:
                handle = self._sessions.get(session_id)
                if handle is None:
                    future.set_exception(
                        ValueError(f"Session {session_id} handle not found")
                    )
                else:
                    result = await handle.run(message)
                    if not future.done():
                        future.set_result(result)
            except asyncio.CancelledError:
                if not future.done():
                    future.cancel()
                # No task_done() here — finally handles it for all paths
                raise
            except Exception as exc:  # noqa: BLE001
                if not future.done():
                    future.set_exception(exc)
            finally:
                queue.task_done()  # exactly one call per item, all exit paths

    async def end_session(self, session_id: str) -> None:
        # Tombstone first — prevents _reconnect() from reviving this session
        self._ended_sessions.add(session_id)

        # Pop handle before signalling the worker so the worker sees no handle
        # and rejects any racing messages with ValueError
        handle = self._sessions.pop(session_id, None)

        # Signal worker to exit cleanly via sentinel
        queue = self._session_queues.get(session_id)
        if queue is not None:
            await queue.put(None)

        # Wait up to 5 s for in-flight work to drain
        worker = self._worker_tasks.get(session_id)
        if worker is not None and not worker.done():
            try:
                await asyncio.wait_for(asyncio.shield(worker), timeout=5.0)
            except TimeoutError:
                logger.warning(
                    "Session worker %s did not drain in 5s, cancelling", session_id
                )
                worker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker

        # Drain any remaining queued futures (unlikely but safe)
        if queue is not None:
            while not queue.empty():
                try:
                    item = queue.get_nowait()
                    if item is not None:
                        _, fut = item
                        if not fut.done():
                            fut.cancel()
                except asyncio.QueueEmpty:
                    break

        # Clean up references
        self._session_queues.pop(session_id, None)
        self._worker_tasks.pop(session_id, None)

        if handle:
            await self._bridge.end_session(handle)

    async def stop(self) -> None:
        """Gracefully stop all session workers.

        Sends the None sentinel to every active queue, then waits up to
        10 s for workers to drain.  Remaining workers are cancelled.
        Must be called during server shutdown.
        """
        for queue in list(self._session_queues.values()):
            await queue.put(None)

        if self._worker_tasks:
            workers = [t for t in self._worker_tasks.values() if not t.done()]
            if workers:
                _, still_pending = await asyncio.wait(workers, timeout=10.0)
                for task in still_pending:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

        self._session_queues.clear()
        self._worker_tasks.clear()

    async def get_session_info(self, session_id: str) -> SessionInfo | None:
        handle = self._sessions.get(session_id)
        if handle is None:
            return None
        return SessionInfo(
            session_id=handle.session_id,
            project_id=handle.project_id,
            working_dir=str(handle.working_dir),
        )

    def list_active_sessions(self) -> list[SessionInfo]:
        return [
            SessionInfo(
                session_id=h.session_id,
                project_id=h.project_id,
                working_dir=str(h.working_dir),
            )
            for h in self._sessions.values()
        ]
