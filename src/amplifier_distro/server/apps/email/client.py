"""Email client abstraction.

Provides a protocol and implementations for sending/receiving email.
MemoryEmailClient is used for testing and simulator mode.
GmailClient connects to the Gmail API for production use.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from email.mime.text import MIMEText
from typing import Any, Protocol, runtime_checkable

from .models import EmailAddress, EmailMessage

logger = logging.getLogger(__name__)


@runtime_checkable
class EmailClient(Protocol):
    """Protocol for email operations."""

    async def send_email(
        self,
        to: EmailAddress,
        subject: str,
        body_html: str,
        body_text: str = "",
        in_reply_to: str = "",
        thread_id: str = "",
    ) -> str:
        """Send an email. Returns message_id."""
        ...

    async def fetch_new_emails(self, since_message_id: str = "") -> list[EmailMessage]:
        """Fetch new emails since the given message ID."""
        ...

    async def mark_read(self, message_id: str) -> None:
        """Mark an email as read."""
        ...

    def get_agent_address(self) -> str:
        """Get the agent's email address."""
        ...


class MemoryEmailClient:
    """In-memory email client for testing and simulation."""

    def __init__(self, agent_address: str = "agent@test.com") -> None:
        self._agent_address = agent_address
        self.sent: list[dict[str, Any]] = []
        self.inbox: list[EmailMessage] = []
        self._read: set[str] = set()

    async def send_email(
        self,
        to: EmailAddress,
        subject: str,
        body_html: str,
        body_text: str = "",
        in_reply_to: str = "",
        thread_id: str = "",
    ) -> str:
        msg_id = f"sent-{len(self.sent) + 1}"
        self.sent.append(
            {
                "message_id": msg_id,
                "to": to,
                "subject": subject,
                "body_html": body_html,
                "body_text": body_text,
                "in_reply_to": in_reply_to,
                "thread_id": thread_id,
            }
        )
        return msg_id

    async def fetch_new_emails(self, since_message_id: str = "") -> list[EmailMessage]:
        if not since_message_id:
            return [m for m in self.inbox if m.message_id not in self._read]
        # Return messages after the given ID
        found = False
        result = []
        for m in self.inbox:
            if m.message_id == since_message_id:
                found = True
                continue
            if found and m.message_id not in self._read:
                result.append(m)
        if not found:
            return [m for m in self.inbox if m.message_id not in self._read]
        return result

    async def mark_read(self, message_id: str) -> None:
        self._read.add(message_id)

    def get_agent_address(self) -> str:
        return self._agent_address

    def inject_email(self, message: EmailMessage) -> None:
        """Add an email to the inbox (test helper)."""
        self.inbox.append(message)


def _parse_address(raw: str) -> EmailAddress:
    """Parse 'Name <addr>' or plain 'addr' into EmailAddress."""
    raw = raw.strip()
    if "<" in raw and ">" in raw:
        name = raw[: raw.index("<")].strip().strip('"')
        addr = raw[raw.index("<") + 1 : raw.index(">")].strip()
        return EmailAddress(address=addr, display_name=name)
    return EmailAddress(address=raw)


def _extract_body(payload: dict[str, Any]) -> tuple[str, str]:
    """Extract text and HTML body from Gmail API payload."""
    text = ""
    html = ""

    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    elif mime_type == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    elif "parts" in payload:
        for part in payload["parts"]:
            t, h = _extract_body(part)
            if t:
                text = t
            if h:
                html = h

    return text, html


def _parse_gmail_message(msg: dict[str, Any]) -> EmailMessage:
    """Parse a Gmail API message dict into an EmailMessage."""
    payload = msg.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

    from_addr = _parse_address(headers.get("from", ""))
    to_raw = headers.get("to", "")
    to_addrs = [_parse_address(a) for a in to_raw.split(",") if a.strip()]

    cc_raw = headers.get("cc", "")
    cc_addrs = (
        [_parse_address(a) for a in cc_raw.split(",") if a.strip()] if cc_raw else None
    )

    body_text, body_html = _extract_body(payload)

    labels = msg.get("labelIds", [])

    return EmailMessage(
        message_id=msg.get("id", ""),
        thread_id=msg.get("threadId", ""),
        from_addr=from_addr,
        to_addrs=to_addrs,
        subject=headers.get("subject", ""),
        body_text=body_text,
        body_html=body_html,
        timestamp=headers.get("date", ""),
        cc_addrs=cc_addrs,
        in_reply_to=headers.get("in-reply-to", ""),
        labels=labels,
    )


class GmailClient:
    """Gmail API client for production use."""

    def __init__(self, config: Any) -> None:
        self._config = config
        self._service: Any = None

    def _get_service(self) -> Any:
        """Lazily initialize the Gmail API service.

        Uses refresh_token + client credentials for auto-refresh.
        No access_token needed upfront - the library refreshes it.
        """
        if self._service is None:
            from google.oauth2.credentials import (
                Credentials,  # type: ignore[import-untyped]
            )
            from googleapiclient.discovery import build  # type: ignore[import-untyped]

            creds = Credentials(
                token=None,
                refresh_token=self._config.gmail_refresh_token,
                token_uri="https://oauth2.googleapis.com/token",  # noqa: S106
                client_id=self._config.gmail_client_id,
                client_secret=self._config.gmail_client_secret,
            )
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    async def send_email(
        self,
        to: EmailAddress,
        subject: str,
        body_html: str,
        body_text: str = "",
        in_reply_to: str = "",
        thread_id: str = "",
    ) -> str:
        service = self._get_service()

        msg = MIMEText(body_html, "html")
        msg["to"] = str(to)
        msg["subject"] = subject
        send_as = self._config.send_as or self._config.agent_address
        if send_as:
            msg["from"] = f"{self._config.agent_name} <{send_as}>"
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        body: dict[str, Any] = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id

        result = await asyncio.to_thread(
            service.users().messages().send(userId="me", body=body).execute
        )
        return result.get("id", "")

    async def fetch_new_emails(self, since_message_id: str = "") -> list[EmailMessage]:
        service = self._get_service()

        query = "is:unread"
        results = await asyncio.to_thread(
            service.users().messages().list(userId="me", q=query, maxResults=20).execute
        )

        messages = results.get("messages", [])
        emails = []
        for msg_ref in messages:
            msg = await asyncio.to_thread(
                service.users()
                .messages()
                .get(userId="me", id=msg_ref["id"], format="full")
                .execute
            )
            emails.append(_parse_gmail_message(msg))

        return emails

    async def mark_read(self, message_id: str) -> None:
        service = self._get_service()
        await asyncio.to_thread(
            service.users()
            .messages()
            .modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            )
            .execute
        )

    def get_agent_address(self) -> str:
        return self._config.agent_address
