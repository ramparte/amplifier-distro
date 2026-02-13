"""Data models for the email bridge."""

from __future__ import annotations

from dataclasses import dataclass
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
    """Maps an email thread to an Amplifier session."""

    session_id: str
    thread_id: str
    sender_address: str
    subject: str
    created_at: str | None = None
    last_activity: str | None = None
    message_count: int = 0

    def __post_init__(self) -> None:
        now = datetime.now(UTC).isoformat()
        if self.created_at is None:
            self.created_at = now
        if self.last_activity is None:
            self.last_activity = now
