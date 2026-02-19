"""Session store for web chat.

Provides WebChatSession (dataclass) and WebChatSessionStore (in-memory dict
with optional atomic JSON persistence).

Mirrors the pattern used by SlackSessionManager in server/apps/slack/sessions.py
but stripped of all Slack-specific routing complexity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class WebChatSession:
    """One entry in the web chat session registry.

    created_at / last_active are ISO-format UTC strings.
    extra holds arbitrary metadata (e.g. project_id) for forward compatibility.
    """

    session_id: str
    description: str
    created_at: str
    last_active: str
    is_active: bool = True
    extra: dict = field(default_factory=dict)
