# Transcript Persistence Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Write `transcript.jsonl` during server sessions so that `resume_session()` can replay conversation history after a server restart.

**Architecture:** Two save layers work together. An incremental hook registered on `tool:post` and `orchestrator:complete` fires during execution, persisting progress between tool calls. A belt-and-suspenders end-of-turn flush in `BridgeBackend.send_message()` saves after `handle.run()` returns. Both layers use the same `write_transcript()` function backed by `atomic_write()` for crash safety.

**Tech Stack:** Python 3.13, amplifier-core hooks API, amplifier-foundation `sanitize_message()`, amplifier-distro `atomic_write()`, pytest with unittest.mock.

---

### Task 1: Create `write_transcript()` and its tests

**Files:**
- Create: `src/amplifier_distro/transcript_persistence.py`
- Create: `tests/test_transcript_persistence.py`

**Step 1: Write the failing test for `write_transcript`**

Add the test file with the first test class:

```python
# tests/test_transcript_persistence.py
"""Tests for transcript persistence during server sessions.

Covers:
- write_transcript: JSONL writing, role filtering, sanitization, atomic write
- TranscriptSaveHook: debounce, best-effort, event handling
- register_transcript_hooks: registration on both events
- flush_transcript: end-of-turn save
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestWriteTranscript:
    """Verify write_transcript writes valid JSONL and filters roles."""

    def test_writes_valid_jsonl(self, tmp_path: Path) -> None:
        """Messages are written as one JSON object per line."""
        from amplifier_distro.transcript_persistence import write_transcript

        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        write_transcript(tmp_path, messages)

        transcript = tmp_path / "transcript.jsonl"
        assert transcript.exists()
        lines = [
            json.loads(line)
            for line in transcript.read_text().strip().split("\n")
        ]
        assert len(lines) == 2
        assert lines[0] == {"role": "user", "content": "hello"}
        assert lines[1] == {"role": "assistant", "content": "hi there"}

    def test_filters_system_and_developer_roles(self, tmp_path: Path) -> None:
        """System and developer messages are excluded from transcript."""
        from amplifier_distro.transcript_persistence import write_transcript

        messages = [
            {"role": "system", "content": "you are helpful"},
            {"role": "developer", "content": "context injection"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        write_transcript(tmp_path, messages)

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.loads(line)
            for line in transcript.read_text().strip().split("\n")
        ]
        assert len(lines) == 2
        assert lines[0]["role"] == "user"
        assert lines[1]["role"] == "assistant"

    def test_keeps_tool_role(self, tmp_path: Path) -> None:
        """Tool messages are preserved in transcript."""
        from amplifier_distro.transcript_persistence import write_transcript

        messages = [
            {"role": "user", "content": "list files"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "bash", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "file1.py"},
            {"role": "assistant", "content": "I found file1.py"},
        ]
        write_transcript(tmp_path, messages)

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.loads(line)
            for line in transcript.read_text().strip().split("\n")
        ]
        assert len(lines) == 4
        assert lines[2]["role"] == "tool"

    def test_empty_messages_writes_empty_file(self, tmp_path: Path) -> None:
        """Empty message list produces an empty file (not no file)."""
        from amplifier_distro.transcript_persistence import write_transcript

        write_transcript(tmp_path, [])

        transcript = tmp_path / "transcript.jsonl"
        assert transcript.exists()
        assert transcript.read_text() == ""

    def test_creates_session_dir_if_missing(self, tmp_path: Path) -> None:
        """Parent directories are created if they don't exist."""
        from amplifier_distro.transcript_persistence import write_transcript

        deep_dir = tmp_path / "projects" / "test" / "sessions" / "abc123"
        write_transcript(deep_dir, [{"role": "user", "content": "hi"}])

        assert (deep_dir / "transcript.jsonl").exists()

    def test_uses_atomic_write(self, tmp_path: Path) -> None:
        """write_transcript delegates to fileutil.atomic_write."""
        from amplifier_distro.transcript_persistence import write_transcript

        with patch(
            "amplifier_distro.transcript_persistence.atomic_write"
        ) as mock_aw:
            write_transcript(
                tmp_path, [{"role": "user", "content": "hello"}]
            )

        mock_aw.assert_called_once()
        call_args = mock_aw.call_args
        assert call_args[0][0] == tmp_path / "transcript.jsonl"
        assert isinstance(call_args[0][1], str)

    def test_preserves_content_null(self, tmp_path: Path) -> None:
        """Assistant tool-call messages with content:null preserve the field.

        This is critical: providers reject tool-call messages missing content.
        """
        from amplifier_distro.transcript_persistence import write_transcript

        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": "{}"}}],
            },
        ]
        write_transcript(tmp_path, messages)

        transcript = tmp_path / "transcript.jsonl"
        parsed = json.loads(transcript.read_text().strip())
        assert "content" in parsed, "content:null must be preserved, not dropped"
        assert parsed["content"] is None

    def test_handles_unicode(self, tmp_path: Path) -> None:
        """Unicode content survives the write round-trip."""
        from amplifier_distro.transcript_persistence import write_transcript

        messages = [{"role": "user", "content": "Fix the \u65e5\u672c\u8a9e handling \ud83d\udd27"}]
        write_transcript(tmp_path, messages)

        transcript = tmp_path / "transcript.jsonl"
        parsed = json.loads(transcript.read_text().strip())
        assert "\u65e5\u672c\u8a9e" in parsed["content"]

    def test_readable_by_resume_session_reader(self, tmp_path: Path) -> None:
        """Output is compatible with bridge.py resume_session() transcript reader.

        This is the round-trip test: write_transcript output must be parseable
        by the same line-by-line JSON reader used in resume_session() step 8.
        """
        from amplifier_distro.transcript_persistence import write_transcript

        messages = [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "bash", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
            {"role": "assistant", "content": "done"},
        ]
        write_transcript(tmp_path, messages)

        # Read back using the same logic as bridge.py resume_session() step 8
        transcript = tmp_path / "transcript.jsonl"
        loaded: list[dict] = []
        with transcript.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if isinstance(entry, dict) and entry.get("role"):
                    loaded.append(entry)

        assert len(loaded) == 4
        assert loaded[0]["role"] == "user"
        assert loaded[1]["tool_calls"][0]["id"] == "c1"
        assert loaded[2]["role"] == "tool"
        assert loaded[3]["content"] == "done"
```

**Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/test_transcript_persistence.py::TestWriteTranscript -x -v
```

Expected: `ModuleNotFoundError: No module named 'amplifier_distro.transcript_persistence'`

**Step 3: Write the `write_transcript` function**

Create the new module with just the `write_transcript` function first:

```python
# src/amplifier_distro/transcript_persistence.py
"""Transcript persistence for distro server sessions.

Registers hooks on tool:post and orchestrator:complete that write
transcript.jsonl incrementally during execution. Mirrors the CLI's
IncrementalSaveHook pattern using distro's own atomic_write.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from amplifier_distro.conventions import TRANSCRIPT_FILENAME
from amplifier_distro.fileutil import atomic_write

logger = logging.getLogger(__name__)

_EXCLUDED_ROLES = frozenset({"system", "developer"})


def _sanitize(msg: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a message for JSON persistence.

    Wraps amplifier_foundation.sanitize_message() with a fallback for
    environments where foundation is not installed, and patches back
    content:null which sanitize_message drops (providers need it on
    tool-call messages).
    """
    try:
        from amplifier_foundation import sanitize_message
    except ImportError:
        sanitize_message = None  # type: ignore[assignment]

    had_content_null = "content" in msg and msg["content"] is None

    if sanitize_message is not None:
        sanitized = sanitize_message(msg)
    else:
        sanitized = msg if isinstance(msg, dict) else {}

    # Restore content:null -- sanitize_message strips None values but
    # providers reject tool-call messages missing the content field.
    if had_content_null and "content" not in sanitized:
        sanitized["content"] = None

    return sanitized


def write_transcript(session_dir: Path, messages: list[dict[str, Any]]) -> None:
    """Write messages to transcript.jsonl, filtering system/developer roles.

    Full rewrite (not append) -- context compaction can change earlier messages.
    Uses atomic_write for crash safety.

    Args:
        session_dir: Directory to write transcript.jsonl into.
        messages: List of message dicts from context.get_messages().
    """
    lines: list[str] = []
    for msg in messages:
        msg_dict = msg if isinstance(msg, dict) else getattr(msg, "model_dump", lambda: msg)()
        if msg_dict.get("role") in _EXCLUDED_ROLES:
            continue
        sanitized = _sanitize(msg_dict)
        lines.append(json.dumps(sanitized, ensure_ascii=False))

    content = "\n".join(lines) + "\n" if lines else ""
    session_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(session_dir / TRANSCRIPT_FILENAME, content)
```

**Step 4: Run tests to verify they pass**

```bash
uv run python -m pytest tests/test_transcript_persistence.py::TestWriteTranscript -x -v
```

Expected: All 9 tests PASS.

**Step 5: Commit**

```bash
git add src/amplifier_distro/transcript_persistence.py tests/test_transcript_persistence.py
git commit -m "feat: add write_transcript() for server session persistence

Writes transcript.jsonl using atomic_write with role filtering
(system/developer excluded) and sanitization. Preserves content:null
on tool-call messages which sanitize_message would otherwise drop."
```

---

### Task 2: Add `TranscriptSaveHook` and its tests

**Files:**
- Modify: `tests/test_transcript_persistence.py` (add test class)
- Modify: `src/amplifier_distro/transcript_persistence.py` (add hook class)

**Step 1: Write the failing tests for `TranscriptSaveHook`**

Append to `tests/test_transcript_persistence.py`, after the `TestWriteTranscript` class:

```python
# --- Helper for hook tests ---------------------------------------------------

def _make_mock_session(messages: list[dict] | None = None) -> MagicMock:
    """Create a mock session with coordinator.get('context').get_messages().

    Mirrors the CLI pattern: hooks access context via coordinator.get('context'),
    not coordinator.context directly.
    """
    session = MagicMock()
    context = MagicMock()
    context.get_messages = AsyncMock(return_value=messages or [])
    session.coordinator.get = MagicMock(return_value=context)
    return session


class TestTranscriptSaveHook:
    """Verify hook debounce, best-effort, and event handling."""

    def test_writes_on_new_messages(self, tmp_path: Path) -> None:
        """Hook writes transcript when message count increases."""
        from amplifier_distro.transcript_persistence import TranscriptSaveHook

        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        session = _make_mock_session(messages)
        hook = TranscriptSaveHook(session, tmp_path)

        result = asyncio.run(hook("tool:post", {}))

        transcript = tmp_path / "transcript.jsonl"
        assert transcript.exists()
        assert result.action == "continue"

    def test_debounce_skips_when_count_unchanged(self, tmp_path: Path) -> None:
        """Hook skips write when message count hasn't changed."""
        from amplifier_distro.transcript_persistence import TranscriptSaveHook

        messages = [{"role": "user", "content": "hello"}]
        session = _make_mock_session(messages)
        hook = TranscriptSaveHook(session, tmp_path)

        # First call: writes
        asyncio.run(hook("tool:post", {}))
        assert (tmp_path / "transcript.jsonl").exists()

        # Second call with same count: should not re-write
        with patch(
            "amplifier_distro.transcript_persistence.write_transcript"
        ) as mock_wt:
            asyncio.run(hook("tool:post", {}))
        mock_wt.assert_not_called()

    def test_debounce_writes_when_count_increases(self, tmp_path: Path) -> None:
        """Hook writes again when message count increases between calls."""
        from amplifier_distro.transcript_persistence import TranscriptSaveHook

        session = _make_mock_session([{"role": "user", "content": "hello"}])
        hook = TranscriptSaveHook(session, tmp_path)

        # First call
        asyncio.run(hook("tool:post", {}))
        assert hook._last_count == 1

        # Update messages (simulating new messages after tool call)
        new_messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        context = session.coordinator.get("context")
        context.get_messages = AsyncMock(return_value=new_messages)

        # Second call with increased count
        asyncio.run(hook("orchestrator:complete", {}))
        assert hook._last_count == 2

    def test_best_effort_exception_does_not_propagate(self, tmp_path: Path) -> None:
        """Hook catches exceptions and returns continue -- never fails the loop."""
        from amplifier_distro.transcript_persistence import TranscriptSaveHook

        session = _make_mock_session()
        # Make get_messages raise
        context = session.coordinator.get("context")
        context.get_messages = AsyncMock(side_effect=RuntimeError("boom"))
        hook = TranscriptSaveHook(session, tmp_path)

        result = asyncio.run(hook("tool:post", {}))

        assert result.action == "continue"

    def test_handles_missing_context_module(self, tmp_path: Path) -> None:
        """Hook gracefully handles coordinator.get('context') returning None."""
        from amplifier_distro.transcript_persistence import TranscriptSaveHook

        session = MagicMock()
        session.coordinator.get = MagicMock(return_value=None)
        hook = TranscriptSaveHook(session, tmp_path)

        result = asyncio.run(hook("tool:post", {}))

        assert result.action == "continue"
        assert not (tmp_path / "transcript.jsonl").exists()

    def test_filters_system_roles(self, tmp_path: Path) -> None:
        """Hook filters system/developer from written transcript."""
        from amplifier_distro.transcript_persistence import TranscriptSaveHook

        messages = [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "hello"},
        ]
        session = _make_mock_session(messages)
        hook = TranscriptSaveHook(session, tmp_path)

        asyncio.run(hook("tool:post", {}))

        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.loads(line)
            for line in transcript.read_text().strip().split("\n")
        ]
        assert len(lines) == 1
        assert lines[0]["role"] == "user"

    def test_works_with_orchestrator_complete_event(self, tmp_path: Path) -> None:
        """Hook fires correctly on orchestrator:complete (not just tool:post)."""
        from amplifier_distro.transcript_persistence import TranscriptSaveHook

        messages = [{"role": "user", "content": "hello"}]
        session = _make_mock_session(messages)
        hook = TranscriptSaveHook(session, tmp_path)

        result = asyncio.run(hook("orchestrator:complete", {}))

        assert (tmp_path / "transcript.jsonl").exists()
        assert result.action == "continue"
```

**Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/test_transcript_persistence.py::TestTranscriptSaveHook -x -v
```

Expected: `ImportError` -- `TranscriptSaveHook` does not exist yet.

**Step 3: Write `TranscriptSaveHook`**

Add to `src/amplifier_distro/transcript_persistence.py`, after `_EXCLUDED_ROLES` and before `_sanitize()`:

```python
_PRIORITY = 900
```

Then add after the `write_transcript` function:

```python
class TranscriptSaveHook:
    """Persists transcript.jsonl incrementally during execution.

    Registered on tool:post (mid-turn durability) and
    orchestrator:complete (end-of-turn, catches no-tool turns).
    Debounces by message count -- skips write if unchanged.
    Best-effort: never fails the agent loop.
    """

    def __init__(self, session: Any, session_dir: Path) -> None:
        self._session = session
        self._session_dir = session_dir
        self._last_count = 0

    async def __call__(self, event: str, data: dict[str, Any]) -> Any:
        from amplifier_core.models import HookResult

        try:
            context = self._session.coordinator.get("context")
            if not context or not hasattr(context, "get_messages"):
                return HookResult(action="continue")

            messages = await context.get_messages()
            count = len(messages)

            # Debounce: skip if message count unchanged
            if count <= self._last_count:
                return HookResult(action="continue")

            self._last_count = count
            write_transcript(self._session_dir, messages)

        except Exception:  # noqa: BLE001
            logger.warning("Transcript save failed", exc_info=True)

        return HookResult(action="continue")
```

**Step 4: Run tests to verify they pass**

```bash
uv run python -m pytest tests/test_transcript_persistence.py::TestTranscriptSaveHook -x -v
```

Expected: All 7 tests PASS.

**Step 5: Commit**

```bash
git add src/amplifier_distro/transcript_persistence.py tests/test_transcript_persistence.py
git commit -m "feat: add TranscriptSaveHook with debounce-by-message-count

Hook registered on tool:post and orchestrator:complete (priority 900).
Debounces by tracking message count -- skips write if unchanged.
Best-effort: exceptions are logged but never fail the agent loop."
```

---

### Task 3: Add `register_transcript_hooks()` and `flush_transcript()` with tests

**Files:**
- Modify: `tests/test_transcript_persistence.py` (add test classes)
- Modify: `src/amplifier_distro/transcript_persistence.py` (add functions)

**Step 1: Write the failing tests**

Append to `tests/test_transcript_persistence.py`:

```python
class TestRegisterTranscriptHooks:
    """Verify hook registration on both events."""

    def test_registers_on_tool_post_and_orchestrator_complete(self) -> None:
        """Both tool:post and orchestrator:complete hooks are registered."""
        from amplifier_distro.transcript_persistence import register_transcript_hooks

        session = MagicMock()
        session.coordinator.hooks.register = MagicMock()
        session_dir = Path("/tmp/fake-session")

        register_transcript_hooks(session, session_dir)

        calls = session.coordinator.hooks.register.call_args_list
        assert len(calls) == 2

        events_registered = set()
        for call in calls:
            events_registered.add(call.kwargs.get("event", call[1].get("event") if len(call) > 1 else None))
        assert "tool:post" in events_registered
        assert "orchestrator:complete" in events_registered

    def test_registers_at_priority_900(self) -> None:
        """Hooks use priority 900 (after streaming at 100, before trace at 1000)."""
        from amplifier_distro.transcript_persistence import register_transcript_hooks

        session = MagicMock()
        session.coordinator.hooks.register = MagicMock()
        session_dir = Path("/tmp/fake-session")

        register_transcript_hooks(session, session_dir)

        for call in session.coordinator.hooks.register.call_args_list:
            priority = call.kwargs.get("priority")
            assert priority == 900

    def test_same_handler_for_both_events(self) -> None:
        """Both events share the same hook instance (for debounce to work)."""
        from amplifier_distro.transcript_persistence import register_transcript_hooks

        session = MagicMock()
        session.coordinator.hooks.register = MagicMock()
        session_dir = Path("/tmp/fake-session")

        register_transcript_hooks(session, session_dir)

        calls = session.coordinator.hooks.register.call_args_list
        handler_0 = calls[0].kwargs.get("handler")
        handler_1 = calls[1].kwargs.get("handler")
        assert handler_0 is handler_1

    def test_silently_noops_if_hooks_unavailable(self) -> None:
        """No exception if session has no hooks API."""
        from amplifier_distro.transcript_persistence import register_transcript_hooks

        session = MagicMock(spec=[])  # no attributes at all
        session_dir = Path("/tmp/fake-session")

        # Must not raise
        register_transcript_hooks(session, session_dir)


class TestFlushTranscript:
    """Verify end-of-turn flush."""

    def test_writes_transcript(self, tmp_path: Path) -> None:
        """flush_transcript writes transcript.jsonl."""
        from amplifier_distro.transcript_persistence import flush_transcript

        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        session = _make_mock_session(messages)

        asyncio.run(flush_transcript(session, tmp_path))

        transcript = tmp_path / "transcript.jsonl"
        assert transcript.exists()
        lines = transcript.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_noops_if_no_messages(self, tmp_path: Path) -> None:
        """flush_transcript is a no-op when there are no messages."""
        from amplifier_distro.transcript_persistence import flush_transcript

        session = _make_mock_session([])

        asyncio.run(flush_transcript(session, tmp_path))

        transcript = tmp_path / "transcript.jsonl"
        assert not transcript.exists()

    def test_noops_if_context_unavailable(self, tmp_path: Path) -> None:
        """flush_transcript handles missing context gracefully."""
        from amplifier_distro.transcript_persistence import flush_transcript

        session = MagicMock()
        session.coordinator.get = MagicMock(return_value=None)

        asyncio.run(flush_transcript(session, tmp_path))

        assert not (tmp_path / "transcript.jsonl").exists()

    def test_best_effort_exception_does_not_propagate(self, tmp_path: Path) -> None:
        """flush_transcript catches all exceptions."""
        from amplifier_distro.transcript_persistence import flush_transcript

        session = _make_mock_session()
        context = session.coordinator.get("context")
        context.get_messages = AsyncMock(side_effect=RuntimeError("boom"))

        # Must not raise
        asyncio.run(flush_transcript(session, tmp_path))
```

**Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/test_transcript_persistence.py::TestRegisterTranscriptHooks tests/test_transcript_persistence.py::TestFlushTranscript -x -v
```

Expected: `ImportError` -- functions don't exist yet.

**Step 3: Write `register_transcript_hooks` and `flush_transcript`**

Add to `src/amplifier_distro/transcript_persistence.py`, after the `TranscriptSaveHook` class:

```python
def register_transcript_hooks(session: Any, session_dir: Path) -> None:
    """Register transcript persistence hooks on a session.

    Safe to call on both fresh and resumed sessions.
    Silently no-ops if hooks API is unavailable.
    """
    try:
        hook = TranscriptSaveHook(session, session_dir)
        hooks = session.coordinator.hooks
        hooks.register(
            event="tool:post",
            handler=hook,
            priority=_PRIORITY,
            name="bridge-transcript:tool:post",
        )
        hooks.register(
            event="orchestrator:complete",
            handler=hook,
            priority=_PRIORITY,
            name="bridge-transcript:orchestrator:complete",
        )
        logger.debug("Transcript hooks registered -> %s", session_dir / TRANSCRIPT_FILENAME)
    except (AttributeError, TypeError, Exception):  # noqa: BLE001
        logger.debug("Could not register transcript hooks", exc_info=True)


async def flush_transcript(session: Any, session_dir: Path) -> None:
    """One-shot transcript save. Called after handle.run() as belt-and-suspenders.

    Async because context.get_messages() is async.
    """
    try:
        context = session.coordinator.get("context")
        if not context or not hasattr(context, "get_messages"):
            return
        messages = await context.get_messages()
        if messages:
            write_transcript(session_dir, messages)
    except Exception:  # noqa: BLE001
        logger.warning("End-of-turn transcript flush failed", exc_info=True)
```

**Step 4: Run all transcript persistence tests**

```bash
uv run python -m pytest tests/test_transcript_persistence.py -x -v
```

Expected: All tests PASS (20 tests total across 4 classes).

**Step 5: Run existing tests to confirm no regressions**

```bash
uv run python -m pytest tests/ -x -q
```

Expected: Full suite passes. No existing files were modified.

**Step 6: Commit**

```bash
git add src/amplifier_distro/transcript_persistence.py tests/test_transcript_persistence.py
git commit -m "feat: add register_transcript_hooks() and flush_transcript()

register_transcript_hooks: registers a single TranscriptSaveHook instance
on both tool:post and orchestrator:complete at priority 900.

flush_transcript: async one-shot save for belt-and-suspenders after
handle.run() returns. Best-effort -- never propagates exceptions."
```

---

### Task 4: Register hooks in `bridge.py`

**Files:**
- Modify: `src/amplifier_distro/bridge.py` (two insertions)

**Step 1: Verify the existing bridge tests pass (baseline)**

```bash
uv run python -m pytest tests/test_bridge.py tests/test_bridge_resume.py -x -q
```

Expected: All pass.

**Step 2: Add hook registration to `create_session()`**

In `src/amplifier_distro/bridge.py`, in the `create_session()` method, find the `session_dir` computation block (lines 362-368):

```python
        session_dir = (
            Path(AMPLIFIER_HOME).expanduser()
            / PROJECTS_DIR
            / _encode_cwd(config.working_dir)
            / "sessions"
            / sid
        )
```

Insert **after** this block and **before** the `logger.info(` call on line 370:

```python
        # 9b. Register transcript persistence hooks
        try:
            from amplifier_distro.transcript_persistence import register_transcript_hooks

            register_transcript_hooks(session, session_dir)
        except Exception:  # noqa: BLE001
            logger.debug("Could not register transcript persistence hooks")
```

Important: The hook must be registered **after** `session_dir` is computed (it needs the path) and **after** the streaming hooks (step 9) which must fire first at priority 100.

**Step 3: Add hook registration to `resume_session()`**

In `src/amplifier_distro/bridge.py`, in the `resume_session()` method, find the streaming hooks block (step 7, lines 478-495). Insert **after** the closing `except` of that block (line 495) and **before** the transcript loading block (step 8, line 497 comment):

```python
        # 7b. Register transcript persistence hooks
        try:
            from amplifier_distro.transcript_persistence import register_transcript_hooks

            register_transcript_hooks(session, session_dir)
        except Exception:  # noqa: BLE001
            logger.debug("Could not register transcript persistence hooks")
```

Note: `session_dir` is already available here from step 1 (line 429).

**Step 4: Run bridge tests to verify no regressions**

```bash
uv run python -m pytest tests/test_bridge.py tests/test_bridge_resume.py -x -v
```

Expected: All pass. The existing `_mock_foundation()` in `test_bridge_resume.py` (line 55) already sets `mock_session.coordinator.hooks.register = MagicMock()`, so the new `register_transcript_hooks()` call succeeds silently in tests. In `test_bridge.py`, `MagicMock()` auto-creates attributes, so it also works.

**Step 5: Run full test suite**

```bash
uv run python -m pytest tests/ -x -q
```

Expected: Full suite passes.

**Step 6: Commit**

```bash
git add src/amplifier_distro/bridge.py
git commit -m "feat: register transcript hooks in create_session and resume_session

Registers TranscriptSaveHook on both tool:post and orchestrator:complete
in both create_session() (step 9b) and resume_session() (step 7b).
Best-effort: failure to register is logged and does not block session creation."
```

---

### Task 5: Add end-of-turn flush in `session_backend.py`

**Files:**
- Modify: `src/amplifier_distro/server/session_backend.py:203-219` (`BridgeBackend.send_message`)

**Step 1: Verify baseline**

```bash
uv run python -m pytest tests/test_services.py -x -q
```

Expected: All pass.

**Step 2: Add `flush_transcript` call to `send_message()`**

In `src/amplifier_distro/server/session_backend.py`, find `BridgeBackend.send_message()` (line 203). The current last line is:

```python
        return await handle.run(message)
```

Replace that single line (line 219) with:

```python
        result = await handle.run(message)

        # End-of-turn transcript save (belt-and-suspenders)
        if handle._session is not None and handle._session_dir is not None:
            try:
                from amplifier_distro.transcript_persistence import flush_transcript

                await flush_transcript(handle._session, handle._session_dir)
            except Exception:  # noqa: BLE001
                logger.warning("End-of-turn transcript flush failed", exc_info=True)

        return result
```

**Step 3: Run tests to verify**

```bash
uv run python -m pytest tests/test_services.py -x -v
```

Expected: All pass. `MockBackend.send_message()` is unaffected (different class). `BridgeBackend` is not exercised by unit tests directly, but the change is guarded by try/except.

**Step 4: Run full suite**

```bash
uv run python -m pytest tests/ -x -q
```

Expected: Full suite passes.

**Step 5: Commit**

```bash
git add src/amplifier_distro/server/session_backend.py
git commit -m "feat: add end-of-turn transcript flush in BridgeBackend.send_message

Belt-and-suspenders: calls flush_transcript() after handle.run() returns.
Catches any failure so it never affects the response to the caller."
```

---

### Task 6: Full suite verification and cleanup

**Files:**
- No new files. Verification only.

**Step 1: Run full test suite**

```bash
uv run python -m pytest tests/ -x -q
```

Expected: All tests pass, including the new `test_transcript_persistence.py`.

**Step 2: Run code quality checks**

```bash
uv run python -m ruff check src/amplifier_distro/transcript_persistence.py
uv run python -m ruff format --check src/amplifier_distro/transcript_persistence.py
```

Expected: No issues.

**Step 3: Verify the new module is importable**

```bash
uv run python -c "from amplifier_distro.transcript_persistence import write_transcript, TranscriptSaveHook, register_transcript_hooks, flush_transcript; print('All exports OK')"
```

Expected: `All exports OK`

**Step 4: Count lines added**

```bash
wc -l src/amplifier_distro/transcript_persistence.py
```

Expected: ~110 lines (the complete module).

**Step 5: Final commit (if any linting fixes needed)**

```bash
git add -A
git status
# If clean, no commit needed. If fixes were applied:
git commit -m "chore: lint fixes for transcript persistence"
```

---

## Reference: Complete `transcript_persistence.py`

For implementer convenience, here is the expected final state of the module:

```python
"""Transcript persistence for distro server sessions.

Registers hooks on tool:post and orchestrator:complete that write
transcript.jsonl incrementally during execution. Mirrors the CLI's
IncrementalSaveHook pattern using distro's own atomic_write.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from amplifier_distro.conventions import TRANSCRIPT_FILENAME
from amplifier_distro.fileutil import atomic_write

logger = logging.getLogger(__name__)

_PRIORITY = 900
_EXCLUDED_ROLES = frozenset({"system", "developer"})


def _sanitize(msg: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a message for JSON persistence.

    Wraps amplifier_foundation.sanitize_message() with a fallback for
    environments where foundation is not installed, and patches back
    content:null which sanitize_message drops (providers need it on
    tool-call messages).
    """
    try:
        from amplifier_foundation import sanitize_message
    except ImportError:
        sanitize_message = None  # type: ignore[assignment]

    had_content_null = "content" in msg and msg["content"] is None

    if sanitize_message is not None:
        sanitized = sanitize_message(msg)
    else:
        sanitized = msg if isinstance(msg, dict) else {}

    # Restore content:null -- sanitize_message strips None values but
    # providers reject tool-call messages missing the content field.
    if had_content_null and "content" not in sanitized:
        sanitized["content"] = None

    return sanitized


def write_transcript(session_dir: Path, messages: list[dict[str, Any]]) -> None:
    """Write messages to transcript.jsonl, filtering system/developer roles.

    Full rewrite (not append) -- context compaction can change earlier messages.
    Uses atomic_write for crash safety.

    Args:
        session_dir: Directory to write transcript.jsonl into.
        messages: List of message dicts from context.get_messages().
    """
    lines: list[str] = []
    for msg in messages:
        msg_dict = msg if isinstance(msg, dict) else getattr(msg, "model_dump", lambda: msg)()
        if msg_dict.get("role") in _EXCLUDED_ROLES:
            continue
        sanitized = _sanitize(msg_dict)
        lines.append(json.dumps(sanitized, ensure_ascii=False))

    content = "\n".join(lines) + "\n" if lines else ""
    session_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(session_dir / TRANSCRIPT_FILENAME, content)


class TranscriptSaveHook:
    """Persists transcript.jsonl incrementally during execution.

    Registered on tool:post (mid-turn durability) and
    orchestrator:complete (end-of-turn, catches no-tool turns).
    Debounces by message count -- skips write if unchanged.
    Best-effort: never fails the agent loop.
    """

    def __init__(self, session: Any, session_dir: Path) -> None:
        self._session = session
        self._session_dir = session_dir
        self._last_count = 0

    async def __call__(self, event: str, data: dict[str, Any]) -> Any:
        from amplifier_core.models import HookResult

        try:
            context = self._session.coordinator.get("context")
            if not context or not hasattr(context, "get_messages"):
                return HookResult(action="continue")

            messages = await context.get_messages()
            count = len(messages)

            # Debounce: skip if message count unchanged
            if count <= self._last_count:
                return HookResult(action="continue")

            self._last_count = count
            write_transcript(self._session_dir, messages)

        except Exception:  # noqa: BLE001
            logger.warning("Transcript save failed", exc_info=True)

        return HookResult(action="continue")


def register_transcript_hooks(session: Any, session_dir: Path) -> None:
    """Register transcript persistence hooks on a session.

    Safe to call on both fresh and resumed sessions.
    Silently no-ops if hooks API is unavailable.
    """
    try:
        hook = TranscriptSaveHook(session, session_dir)
        hooks = session.coordinator.hooks
        hooks.register(
            event="tool:post",
            handler=hook,
            priority=_PRIORITY,
            name="bridge-transcript:tool:post",
        )
        hooks.register(
            event="orchestrator:complete",
            handler=hook,
            priority=_PRIORITY,
            name="bridge-transcript:orchestrator:complete",
        )
        logger.debug("Transcript hooks registered -> %s", session_dir / TRANSCRIPT_FILENAME)
    except (AttributeError, TypeError, Exception):  # noqa: BLE001
        logger.debug("Could not register transcript hooks", exc_info=True)


async def flush_transcript(session: Any, session_dir: Path) -> None:
    """One-shot transcript save. Called after handle.run() as belt-and-suspenders.

    Async because context.get_messages() is async.
    """
    try:
        context = session.coordinator.get("context")
        if not context or not hasattr(context, "get_messages"):
            return
        messages = await context.get_messages()
        if messages:
            write_transcript(session_dir, messages)
    except Exception:  # noqa: BLE001
        logger.warning("End-of-turn transcript flush failed", exc_info=True)
```

---

## Key Decisions for Implementer

| Decision | Rationale |
|----------|-----------|
| `coordinator.get("context")` not `coordinator.context` | Matches CLI's `incremental_save.py` hook pattern (line 81). The `get()` API returns None if the module isn't mounted, avoiding AttributeError. |
| `_sanitize()` wrapper preserves `content:null` | `sanitize_message()` drops None values from dicts. Tool-call messages NEED `content: null` -- providers reject messages without it. |
| Full rewrite, not append | Context compaction can change earlier messages. Append-only would diverge from the in-memory state. |
| `asyncio.run()` in tests, not `@pytest.mark.asyncio` | Matches existing test patterns in `test_bridge.py` (line 100, 330) and `test_bridge_resume.py` (line 99). |
| Hook registration after `session_dir` computation | In `create_session()`, `session_dir` is computed at lines 362-368 -- hook registration must go after, not at the step 9 position. |
| `register_transcript_hooks` in `resume_session` goes before transcript loading (step 8) | The hook must be active before the first `handle.run()` call. Transcript loading (step 8) is a one-time setup that doesn't trigger hooks. |
| Lazy import of `amplifier_core.models.HookResult` inside `__call__` | Matches `bridge_protocols.py` pattern (line 138). Avoids hard import dependency at module level. |

## Run Commands

```bash
# Task 1: write_transcript tests
uv run python -m pytest tests/test_transcript_persistence.py::TestWriteTranscript -x -v

# Task 2: TranscriptSaveHook tests
uv run python -m pytest tests/test_transcript_persistence.py::TestTranscriptSaveHook -x -v

# Task 3: register + flush tests
uv run python -m pytest tests/test_transcript_persistence.py -x -v

# Task 4: bridge integration
uv run python -m pytest tests/test_bridge.py tests/test_bridge_resume.py -x -v

# Task 5: session backend
uv run python -m pytest tests/test_services.py -x -v

# Full suite
uv run python -m pytest tests/ -x -q
```
