"""Chat preferences — stored in ~/.amplifier/chat-preferences.json.

Schema:
    default_bundle: str | None       — bundle name to use for new sessions
    default_behaviors: list[str]     — behaviors active by default
    show_thinking: bool              — show thinking blocks in UI
    default_cwd: str                 — default working directory for new sessions
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from amplifier_distro.conventions import AMPLIFIER_HOME

logger = logging.getLogger(__name__)

_PREFS_FILENAME = "chat-preferences.json"
_PREFS_PATH: Path | None = None  # Overridable in tests


def _get_prefs_path() -> Path:
    if _PREFS_PATH is not None:
        return _PREFS_PATH
    return Path(AMPLIFIER_HOME).expanduser() / _PREFS_FILENAME


_DEFAULTS: dict[str, Any] = {
    "default_bundle": None,
    "default_behaviors": [],
    "show_thinking": False,
    "default_cwd": "~",
}


def load_preferences() -> dict[str, Any]:
    """Load preferences from disk, returning defaults if file missing."""
    path = _get_prefs_path()
    prefs = copy.deepcopy(_DEFAULTS)  # deep copy to prevent list mutation
    if path.exists():
        try:
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            prefs.update({k: v for k, v in on_disk.items() if v is not None})
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read preferences from %s", path, exc_info=True)
    return prefs


def save_preferences(updates: dict[str, Any]) -> dict[str, Any]:
    """Apply partial updates and write to disk. Returns updated preferences."""
    current = load_preferences()
    for key, value in updates.items():
        if key in _DEFAULTS and value is not None:
            current[key] = value
    path = _get_prefs_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except OSError:
        logger.warning("Could not write preferences to %s", path, exc_info=True)
    return current
