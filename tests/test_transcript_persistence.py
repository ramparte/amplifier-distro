# tests/test_transcript_persistence.py
"""Tests for transcript persistence during server sessions.

Covers:
- write_transcript: JSONL writing, role filtering, sanitization, atomic write
- TranscriptSaveHook: debounce, best-effort, event handling
- register_transcript_hooks: registration on both events
- flush_transcript: end-of-turn save
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


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
            json.loads(line) for line in transcript.read_text().strip().split("\n")
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
            json.loads(line) for line in transcript.read_text().strip().split("\n")
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
            json.loads(line) for line in transcript.read_text().strip().split("\n")
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

        with patch("amplifier_distro.transcript_persistence.atomic_write") as mock_aw:
            write_transcript(tmp_path, [{"role": "user", "content": "hello"}])

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
                "tool_calls": [
                    {"id": "c1", "function": {"name": "f", "arguments": "{}"}}
                ],
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

        messages = [
            {
                "role": "user",
                "content": "Fix the \u65e5\u672c\u8a9e handling \U0001f527",
            }
        ]
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
