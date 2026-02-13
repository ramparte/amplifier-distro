"""Data models for the email bridge.

Mirrors the Slack bridge model structure with email-specific fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class EmailAddress:
    """An email address with optional display name."""

    address: str
    display_name: str = ""

    def __str__(self) -> str:
        if self.display_name:
            return f"{self.display_name} <{self.address}>"
        return self.address


@dataclass
class EmailMessage:
    """An email message."""

    message_id: str
    thread_id: str
    from_addr: EmailAddress
    to_addrs: list[EmailAddress]
    subject: str
    body_text: str
    body_html: str = ""
    timestamp: str | None = None
    cc_addrs: list[EmailAddress] | None = None
    in_reply_to: str = ""
    labels: list[str] | None = None


@dataclass
class SessionMapping:
    """Maps an email thread to an Amplifier session.

    A mapping ties an email thread (identified by Gmail thread_id) to
    an Amplifier session. This is the core routing table for the bridge.
    """

    session_id: str
    thread_id: str  # Gmail thread_id
    sender_address: str  # The human's email address
    subject: str
    project_id: str = ""
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_activity: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    message_count: int = 0
    is_active: bool = True

    @property
    def conversation_key(self) -> str:
        """Unique key for routing: thread_id or sender:subject fallback."""
        if self.thread_id:
            return self.thread_id
        return f"{self.sender_address}:{self.subject}"
