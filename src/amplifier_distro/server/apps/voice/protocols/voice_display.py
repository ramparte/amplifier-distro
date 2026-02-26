"""Voice display system for formatting and filtering messages for speech output."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class DisplayLevel(Enum):
    """Display level for voice messages."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"
    DEBUG = "debug"


@dataclass
class VoiceDisplayMessage:
    """A message formatted for voice display output."""

    level: DisplayLevel
    message: str
    spoken_text: str
    should_speak: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "level": self.level.value,
            "message": self.message,
            "spoken_text": self.spoken_text,
            "should_speak": self.should_speak,
        }


class VoiceDisplaySystem:
    """Formats and filters display messages for speech output."""

    def __init__(self, message_callback: Callable | None = None) -> None:
        self._callback = message_callback
        self.suppressed_patterns: list[str] = ["debug:", "trace:", "[internal]"]

    async def display(
        self,
        message: str,
        level: str = "info",
        nesting: int = 0,
    ) -> VoiceDisplayMessage:
        """Format a message and optionally speak it via the callback."""
        parsed_level = self._parse_level(level)
        should_speak = self._should_speak(message, parsed_level)
        spoken_text = (
            self._to_spoken_format(message, parsed_level) if should_speak else ""
        )

        result = VoiceDisplayMessage(
            level=parsed_level,
            message=message,
            spoken_text=spoken_text,
            should_speak=should_speak,
        )

        if self._callback is not None and should_speak:
            await self._callback(result)

        return result

    def _parse_level(self, level: str) -> DisplayLevel:
        """Parse a string level into a DisplayLevel enum."""
        try:
            return DisplayLevel(level.lower())
        except ValueError:
            return DisplayLevel.INFO

    def _should_speak(self, message: str, level: DisplayLevel) -> bool:
        """Determine whether a message should be spoken aloud."""
        if level == DisplayLevel.DEBUG:
            return False
        if len(message) < 3:
            return False
        lower = message.lower()
        for pattern in self.suppressed_patterns:
            if pattern.lower() in lower:
                return False
        return True

    def _to_spoken_format(self, message: str, level: DisplayLevel) -> str:
        """Convert a display message to a speech-friendly format."""
        # Strip visual symbols and collapse whitespace
        text = message
        text = text.replace("...", " ")
        text = text.replace("=>", " ")
        text = text.replace("->", " ")
        text = text.replace("|", " ")
        text = re.sub(r"\s+", " ", text).strip()

        # Add level-appropriate prefix if needed
        lower = text.lower()
        if level == DisplayLevel.ERROR:
            if not any(kw in lower for kw in ("error", "failed", "problem")):
                text = f"Error: {text}"
        elif level == DisplayLevel.WARNING:
            if not any(kw in lower for kw in ("warning", "caution", "note")):
                text = f"Note: {text}"

        # Truncate at 200 chars at sentence boundary
        if len(text) > 200:
            text = self._truncate_at_sentence(text, 200)

        return text

    def _truncate_at_sentence(self, text: str, max_len: int) -> str:
        """Truncate text at a sentence boundary within max_len chars."""
        sentences = text.split(". ")
        result = ""
        for i, sentence in enumerate(sentences):
            candidate = sentence if i == 0 else result + ". " + sentence
            if len(candidate) <= max_len:
                result = candidate
            else:
                break

        if result:
            # Ensure it ends with a period
            if not result.endswith("."):
                result = result + "."
            return result

        # Fallback: truncate at last word boundary
        truncated = text[:max_len].rsplit(" ", 1)[0]
        return truncated

    def set_callback(self, callback: Callable) -> None:
        """Set the message callback."""
        self._callback = callback

    def add_suppressed_pattern(self, pattern: str) -> None:
        """Add a pattern to the suppressed patterns list."""
        self.suppressed_patterns.append(pattern)
