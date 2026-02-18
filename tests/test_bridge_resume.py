"""Tests for LocalBridge.resume_session() transcript replay.

Covers the transcript loading logic in step 8 of resume_session():
- Streaming line-by-line file reading
- Per-line JSON error handling (malformed lines skipped)
- Full message field passthrough (no allowlist filtering)
- Orphan tool-message stripping (front and back)
- Injection via context.set_messages()
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from amplifier_distro.bridge import BridgeConfig, LocalBridge

# -- Helpers ----------------------------------------------------------------

SESSION_ID = "test-session-00000000"
PROJECT_NAME = "test-project"


def _write_transcript(session_dir: Path, lines: Sequence[dict | str]) -> Path:
    """Write a transcript.jsonl file into *session_dir*.

    Each element in *lines* is either a dict (serialised as JSON) or a
    raw string (written verbatim, useful for malformed-line tests).
    """
    transcript = session_dir / "transcript.jsonl"
    with transcript.open("w", encoding="utf-8") as f:
        for entry in lines:
            if isinstance(entry, dict):
                f.write(json.dumps(entry) + "\n")
            else:
                f.write(entry + "\n")
    return transcript


def _make_session_dir(tmp_path: Path) -> Path:
    """Create the directory tree that resume_session() expects."""
    session_dir = tmp_path / PROJECT_NAME / "sessions" / SESSION_ID
    session_dir.mkdir(parents=True)
    return session_dir


def _mock_foundation():
    """Return (mock_load_bundle, mock_registry_cls, mock_session)."""
    mock_session = MagicMock()
    mock_session.coordinator.session_id = SESSION_ID
    mock_session.coordinator.context.set_messages = AsyncMock()
    mock_session.coordinator.hooks.register = MagicMock()

    mock_prepared = AsyncMock()
    mock_prepared.create_session = AsyncMock(return_value=mock_session)

    mock_bundle = AsyncMock()
    mock_bundle.prepare = AsyncMock(return_value=mock_prepared)

    mock_load_bundle = AsyncMock(return_value=mock_bundle)
    mock_registry_cls = MagicMock()

    return mock_load_bundle, mock_registry_cls, mock_session


def _run_resume(tmp_path: Path, transcript_lines: Sequence[dict | str] | None) -> list:
    """End-to-end helper: write transcript, run resume, return injected messages.

    Returns the list passed to ``context.set_messages()``, or an empty list
    if ``set_messages`` was never called.
    """
    session_dir = _make_session_dir(tmp_path)
    if transcript_lines is not None:
        _write_transcript(session_dir, transcript_lines)

    mock_load, mock_reg, mock_session = _mock_foundation()
    set_messages: AsyncMock = mock_session.coordinator.context.set_messages

    bridge = LocalBridge()
    config = BridgeConfig(working_dir=tmp_path)

    with (
        patch(
            "amplifier_distro.bridge._require_foundation",
            return_value=(mock_load, mock_reg),
        ),
        patch(
            "amplifier_distro.bridge.AMPLIFIER_HOME",
            str(tmp_path),
        ),
        patch(
            "amplifier_distro.bridge.PROJECTS_DIR",
            PROJECT_NAME,
        ),
    ):
        asyncio.run(bridge.resume_session(SESSION_ID, config))

    if set_messages.called:
        return list(set_messages.call_args[0][0])
    return []


# -- Tests ------------------------------------------------------------------


class TestTranscriptReplayHappyPath:
    """Basic transcript loading and injection."""

    def test_simple_conversation_injected(self, tmp_path):
        """A plain user/assistant transcript is fully replayed."""
        lines = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 2
        assert result[0] == {"role": "user", "content": "hello"}
        assert result[1] == {"role": "assistant", "content": "hi there"}

    def test_tool_call_round_trip_preserved(self, tmp_path):
        """A full tool-call sequence (assistant->tool->assistant) is preserved."""
        lines = [
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
        result = _run_resume(tmp_path, lines)
        assert len(result) == 4
        assert result[1]["tool_calls"][0]["id"] == "call_1"
        assert result[2]["tool_call_id"] == "call_1"

    def test_all_fields_passed_through(self, tmp_path):
        """Arbitrary message fields are preserved (no allowlist filtering)."""
        msg = {
            "role": "assistant",
            "content": "refused",
            "refusal": "I can't do that",
            "custom_field": 42,
            "annotations": [{"url": "https://example.com"}],
        }
        result = _run_resume(tmp_path, [msg])
        assert result == [msg]  # exact equality catches ANY dropped field

    def test_tool_message_fields_passed_through(self, tmp_path):
        """Extra fields on tool messages survive (not just assistant)."""
        lines = [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "f", "arguments": "{}"}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "content": "ok",
                "custom_metadata": {"latency_ms": 42},
            },
            {"role": "assistant", "content": "done"},
        ]
        result = _run_resume(tmp_path, lines)
        assert result[2]["custom_metadata"] == {"latency_ms": 42}

    def test_all_messages_sent_no_windowing(self, tmp_path):
        """All messages are sent -- no artificial cap or windowing."""
        n = 1001  # well above any plausible window constant
        lines = [{"role": "user", "content": f"msg {i}"} for i in range(n)]
        result = _run_resume(tmp_path, lines)
        assert len(result) == n
        # Verify ordering — a windowing impl might keep only the *last* N
        assert result[0]["content"] == "msg 0"
        assert result[-1]["content"] == f"msg {n - 1}"


class TestTranscriptMalformedLines:
    """Per-line JSON error handling."""

    def test_malformed_lines_skipped(self, tmp_path):
        """Bad JSON lines are skipped; valid lines still processed."""
        lines = [
            {"role": "user", "content": "before"},
            "this is not valid json{{{",
            {"role": "assistant", "content": "after"},
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 2
        assert result[0]["content"] == "before"
        assert result[1]["content"] == "after"

    def test_empty_lines_skipped(self, tmp_path):
        """Blank lines (empty or whitespace-only) are ignored."""
        session_dir = _make_session_dir(tmp_path)
        transcript = session_dir / "transcript.jsonl"
        transcript.write_text(
            '\n  \n{"role": "user", "content": "hi"}\n\n',
            encoding="utf-8",
        )

        mock_load, mock_reg, mock_session = _mock_foundation()
        set_messages = mock_session.coordinator.context.set_messages
        bridge = LocalBridge()
        config = BridgeConfig(working_dir=tmp_path)

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", PROJECT_NAME),
        ):
            asyncio.run(bridge.resume_session(SESSION_ID, config))

        assert set_messages.called
        assert len(set_messages.call_args[0][0]) == 1

    def test_all_lines_malformed_means_no_injection(self, tmp_path):
        """If every line is bad JSON, set_messages is never called."""
        lines = ["bad{", "also bad[", "nope"]
        session_dir = _make_session_dir(tmp_path)
        _write_transcript(session_dir, lines)

        mock_load, mock_reg, mock_session = _mock_foundation()
        set_messages = mock_session.coordinator.context.set_messages
        bridge = LocalBridge()
        config = BridgeConfig(working_dir=tmp_path)

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", PROJECT_NAME),
        ):
            asyncio.run(bridge.resume_session(SESSION_ID, config))

        assert not set_messages.called

    def test_entries_without_role_skipped(self, tmp_path):
        """JSON objects missing the 'role' key are dropped."""
        lines = [
            {"content": "no role here"},
            {"role": "user", "content": "valid"},
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 1
        assert result[0]["role"] == "user"


class TestOrphanToolStripping:
    """Orphaned tool messages stripped from both ends."""

    def test_leading_tool_messages_stripped(self, tmp_path):
        """Tool messages at the start (no preceding assistant) are removed."""
        lines = [
            {"role": "tool", "tool_call_id": "orphan_1", "content": "result1"},
            {"role": "tool", "tool_call_id": "orphan_2", "content": "result2"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 2
        assert result[0]["role"] == "user"

    def test_trailing_assistant_with_tool_calls_stripped(self, tmp_path):
        """Trailing assistant+tool_calls (session crashed mid-exec) is removed."""
        lines = [
            {"role": "user", "content": "do something"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call_99", "function": {"name": "bash"}}],
            },
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_trailing_assistant_without_tool_calls_kept(self, tmp_path):
        """A normal trailing assistant message (no tool_calls) is preserved."""
        lines = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello back"},
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 2
        assert result[1]["content"] == "hello back"

    def test_all_tool_messages_means_no_injection(self, tmp_path):
        """If every message is an orphaned tool result, nothing is injected."""
        lines = [
            {"role": "tool", "tool_call_id": "c1", "content": "r1"},
            {"role": "tool", "tool_call_id": "c2", "content": "r2"},
        ]
        result = _run_resume(tmp_path, lines)
        assert result == []

    def test_both_ends_stripped_simultaneously(self, tmp_path):
        """Orphans at both front and back are stripped in one pass."""
        lines = [
            {"role": "tool", "tool_call_id": "orphan", "content": "x"},
            {"role": "user", "content": "middle"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "dangling"}],
            },
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "middle"}

    # -- Trailing tool messages are KEPT (may be valid complete round trips) -

    def test_trailing_tool_messages_kept(self, tmp_path):
        """Trailing tool results are passed through — the provider and context
        module decide validity, not the bridge (mechanism, not policy)."""
        lines = [
            {"role": "user", "content": "run two commands"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "bash", "arguments": "{}"}},
                    {"id": "c2", "function": {"name": "bash", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
            # c2 never came back — but bridge doesn't cascade-strip
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[2]["role"] == "tool"

    def test_trailing_assistant_tool_calls_stripped_tool_results_kept(self, tmp_path):
        """Only the dangling assistant+tool_calls is stripped; the preceding
        complete tool round trip is preserved."""
        lines = [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "f", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "done"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c2", "function": {"name": "g", "arguments": "{}"}}
                ],
            },
            # c2 crash — only the dangling assistant is stripped
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "tool"

    # -- P0: Valid JSON non-dict lines ------------------------------------

    def test_valid_json_non_dict_skipped(self, tmp_path):
        """Valid JSON that isn't an object (string, array, number) is skipped."""
        lines = [
            '"just a string"',
            "[1, 2, 3]",
            "42",
            "true",
            "null",
            json.dumps({"role": "user", "content": "real message"}),
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 1
        assert result[0]["content"] == "real message"

    # -- P2: Falsy role values and edge-case tool_calls -------------------

    def test_empty_string_role_skipped(self, tmp_path):
        """role: '' is falsy — entry is dropped."""
        lines = [
            {"role": "", "content": "ghost"},
            {"role": "user", "content": "real"},
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 1
        assert result[0]["content"] == "real"

    def test_trailing_assistant_with_empty_tool_calls_kept(self, tmp_path):
        """tool_calls: [] is falsy — message is NOT stripped."""
        lines = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "done", "tool_calls": []},
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 2
        assert result[1]["tool_calls"] == []

    def test_multiple_trailing_assistant_tool_calls_all_stripped(self, tmp_path):
        """Multiple consecutive trailing assistant+tool_calls are all removed."""
        lines = [
            {"role": "user", "content": "start"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "a", "arguments": "{}"}}
                ],
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c2", "function": {"name": "b", "arguments": "{}"}}
                ],
            },
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 1
        assert result[0]["role"] == "user"


class TestSetMessagesGracefulDegradation:
    """The set_messages call handles unavailable context APIs."""

    def test_set_messages_attribute_error_handled(self, tmp_path):
        """Resume succeeds even if context.set_messages raises AttributeError."""
        session_dir = _make_session_dir(tmp_path)
        _write_transcript(session_dir, [{"role": "user", "content": "hi"}])

        mock_load, mock_reg, mock_session = _mock_foundation()
        mock_session.coordinator.context.set_messages = AsyncMock(
            side_effect=AttributeError("no set_messages"),
        )
        bridge = LocalBridge()
        config = BridgeConfig(working_dir=tmp_path)

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", PROJECT_NAME),
        ):
            handle = asyncio.run(bridge.resume_session(SESSION_ID, config))

        assert handle is not None

    def test_set_messages_type_error_handled(self, tmp_path):
        """Resume succeeds even if context.set_messages raises TypeError."""
        session_dir = _make_session_dir(tmp_path)
        _write_transcript(session_dir, [{"role": "user", "content": "hi"}])

        mock_load, mock_reg, mock_session = _mock_foundation()
        mock_session.coordinator.context.set_messages = AsyncMock(
            side_effect=TypeError("wrong arg type"),
        )
        bridge = LocalBridge()
        config = BridgeConfig(working_dir=tmp_path)

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", PROJECT_NAME),
        ):
            handle = asyncio.run(bridge.resume_session(SESSION_ID, config))

        assert handle is not None


class TestEmptyAndMissingTranscript:
    """Edge cases: no file, empty file."""

    def test_missing_transcript_file(self, tmp_path):
        """Resume succeeds even if transcript.jsonl does not exist."""
        _make_session_dir(tmp_path)  # dir exists, but no transcript file

        mock_load, mock_reg, mock_session = _mock_foundation()
        set_messages = mock_session.coordinator.context.set_messages
        bridge = LocalBridge()
        config = BridgeConfig(working_dir=tmp_path)

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", PROJECT_NAME),
        ):
            handle = asyncio.run(bridge.resume_session(SESSION_ID, config))

        assert handle is not None
        assert not set_messages.called

    def test_empty_transcript_file(self, tmp_path):
        """An empty transcript.jsonl results in no injection."""
        result = _run_resume(tmp_path, [])
        assert result == []


class TestSetMessagesApiContract:
    """Verify the correct context API method is called."""

    def test_uses_set_messages_not_add_messages(self, tmp_path):
        """Resume uses set_messages (full replace), not add_messages (append).

        add_messages exists in create_session (line 352) -- this guards
        against a copy-paste regression.
        """
        session_dir = _make_session_dir(tmp_path)
        _write_transcript(
            session_dir,
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
        )

        mock_load, mock_reg, mock_session = _mock_foundation()
        ctx = mock_session.coordinator.context
        ctx.set_messages = AsyncMock()
        ctx.add_messages = AsyncMock()

        bridge = LocalBridge()
        config = BridgeConfig(working_dir=tmp_path)

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(mock_load, mock_reg),
            ),
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch("amplifier_distro.bridge.PROJECTS_DIR", PROJECT_NAME),
        ):
            asyncio.run(bridge.resume_session(SESSION_ID, config))

        assert ctx.set_messages.called, "Expected set_messages (full replace)"
        assert not ctx.add_messages.called, (
            "add_messages should NOT be used -- resume replaces, not appends"
        )


class TestContentFormats:
    """Message content can be a string, None, or a list of typed blocks."""

    def test_anthropic_content_blocks_preserved(self, tmp_path):
        """Content as a list of typed blocks (Anthropic/vision format)
        must pass through without coercion to string."""
        lines = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "data": "..."}},
                    {"type": "text", "text": "What is this image?"},
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "It appears to be a diagram."},
                ],
            },
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 2
        assert isinstance(result[0]["content"], list)
        assert len(result[0]["content"]) == 2
        assert result[0]["content"][0]["type"] == "image"
        assert isinstance(result[1]["content"], list)

    def test_unicode_content_preserved(self, tmp_path):
        """Unicode in messages (emoji, CJK, RTL) survives round-trip."""
        lines = [
            {"role": "user", "content": "Fix the 日本語 handling 🔧"},
            {"role": "assistant", "content": "تم الإصلاح — done ✅"},
        ]
        result = _run_resume(tmp_path, lines)
        assert len(result) == 2
        assert "日本語" in result[0]["content"]
        assert "تم" in result[1]["content"]
        assert "✅" in result[1]["content"]


class TestTranscriptFileErrors:
    """Outer except clause: resume succeeds even if transcript is unreadable."""

    def test_permission_denied_still_resumes(self, tmp_path):
        """If transcript exists but is unreadable, resume succeeds
        without injecting messages (outer except catches OSError)."""
        session_dir = _make_session_dir(tmp_path)
        transcript = session_dir / "transcript.jsonl"
        transcript.write_text('{"role": "user", "content": "hi"}\n')
        transcript.chmod(0o000)

        mock_load, mock_reg, mock_session = _mock_foundation()
        set_messages = mock_session.coordinator.context.set_messages
        bridge = LocalBridge()
        config = BridgeConfig(working_dir=tmp_path)

        try:
            with (
                patch(
                    "amplifier_distro.bridge._require_foundation",
                    return_value=(mock_load, mock_reg),
                ),
                patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
                patch("amplifier_distro.bridge.PROJECTS_DIR", PROJECT_NAME),
            ):
                handle = asyncio.run(bridge.resume_session(SESSION_ID, config))

            assert handle is not None
            assert not set_messages.called
        finally:
            transcript.chmod(0o644)  # restore for tmp_path cleanup


class TestSingleMessageEdgeCases:
    """Single-message transcripts that interact with orphan stripping."""

    def test_single_user_message(self, tmp_path):
        """A transcript with just one user message is injected as-is."""
        result = _run_resume(tmp_path, [{"role": "user", "content": "hello"}])
        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "hello"}

    def test_single_tool_message_stripped_to_empty(self, tmp_path):
        """A single orphaned tool message is stripped -> no injection."""
        result = _run_resume(
            tmp_path,
            [{"role": "tool", "tool_call_id": "c1", "content": "orphan"}],
        )
        assert result == []

    def test_single_assistant_with_tool_calls_stripped_to_empty(self, tmp_path):
        """A single dangling assistant+tool_calls is stripped -> no injection."""
        result = _run_resume(
            tmp_path,
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "call_1"}],
                },
            ],
        )
        assert result == []

    def test_single_assistant_without_tool_calls_kept(self, tmp_path):
        """A single plain assistant message is preserved."""
        result = _run_resume(
            tmp_path,
            [{"role": "assistant", "content": "I remember everything"}],
        )
        assert len(result) == 1
        assert result[0]["content"] == "I remember everything"
