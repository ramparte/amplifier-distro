"""Session backend - abstracts Amplifier session interaction.

The canonical implementation now lives at server/session_backend.py.
This module re-exports everything for backward compatibility so that
existing imports (tests, other Slack modules) continue to work.

For new code, prefer importing from:
    from amplifier_distro.server.session_backend import SessionBackend, SessionInfo
"""

from __future__ import annotations

# Re-export everything from the server-level module
from amplifier_distro.server.session_backend import (
    BridgeBackend,
    MockBackend,
    SessionBackend,
    SessionInfo,
)

__all__ = [
    "BridgeBackend",
    "MockBackend",
    "SessionBackend",
    "SessionInfo",
]
