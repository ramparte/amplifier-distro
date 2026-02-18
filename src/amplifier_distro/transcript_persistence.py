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
        msg_dict = (
            msg if isinstance(msg, dict) else getattr(msg, "model_dump", lambda: msg)()
        )
        if msg_dict.get("role") in _EXCLUDED_ROLES:
            continue
        sanitized = _sanitize(msg_dict)
        lines.append(json.dumps(sanitized, ensure_ascii=False))

    content = "\n".join(lines) + "\n" if lines else ""
    session_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(session_dir / TRANSCRIPT_FILENAME, content)
