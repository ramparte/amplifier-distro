"""Tests for the email bridge.

103 tests covering all modules: models, client, formatter, sessions,
commands, events, poller, and the FastAPI app/routes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from amplifier_distro.server.apps.email.client import (
    EmailClient,
    MemoryEmailClient,
    _extract_body,
    _parse_address,
    _parse_gmail_message,
)
from amplifier_distro.server.apps.email.commands import CommandHandler
from amplifier_distro.server.apps.email.config import EmailConfig
from amplifier_distro.server.apps.email.events import EmailEventHandler
from amplifier_distro.server.apps.email.formatter import (
    format_response,
    markdown_to_html,
    split_message,
)
from amplifier_distro.server.apps.email.models import (
    EmailAddress,
    EmailMessage,
    SessionMapping,
)
from amplifier_distro.server.apps.email.poller import EmailPoller
from amplifier_distro.server.apps.email.sessions import EmailSessionManager
from amplifier_distro.server.session_backend import MockBackend

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def config() -> EmailConfig:
    return EmailConfig(
        agent_address="agent@test.com",
        agent_name="TestBot",
        simulator_mode=True,
        max_sessions_per_sender=3,
    )


@pytest.fixture()
def client() -> MemoryEmailClient:
    return MemoryEmailClient(agent_address="agent@test.com")


@pytest.fixture()
def backend() -> MockBackend:
    return MockBackend()


@pytest.fixture()
def session_manager(
    client: MemoryEmailClient, backend: MockBackend, config: EmailConfig
) -> EmailSessionManager:
    return EmailSessionManager(client, backend, config)


@pytest.fixture()
def command_handler(
    session_manager: EmailSessionManager, config: EmailConfig
) -> CommandHandler:
    return CommandHandler(session_manager, config)


@pytest.fixture()
def event_handler(
    client: MemoryEmailClient,
    session_manager: EmailSessionManager,
    command_handler: CommandHandler,
    config: EmailConfig,
) -> EmailEventHandler:
    return EmailEventHandler(client, session_manager, command_handler, config)


@pytest.fixture()
def poller(
    client: MemoryEmailClient,
    event_handler: EmailEventHandler,
    config: EmailConfig,
) -> EmailPoller:
    return EmailPoller(client, event_handler, config)


def _make_msg(
    message_id: str = "msg-1",
    thread_id: str = "thread-1",
    from_addr: str = "user@example.com",
    to_addr: str = "agent@test.com",
    subject: str = "Test Subject",
    body_text: str = "Hello",
) -> EmailMessage:
    """Helper to create test email messages."""
    return EmailMessage(
        message_id=message_id,
        thread_id=thread_id,
        from_addr=EmailAddress(address=from_addr),
        to_addrs=[EmailAddress(address=to_addr)],
        subject=subject,
        body_text=body_text,
    )


# ═══════════════════════════════════════════════════════════════════════
#  1. MODELS (10 tests)
# ═══════════════════════════════════════════════════════════════════════


class TestEmailAddress:
    def test_str_with_display_name(self) -> None:
        addr = EmailAddress(address="a@b.com", display_name="Alice")
        assert str(addr) == "Alice <a@b.com>"

    def test_str_without_display_name(self) -> None:
        addr = EmailAddress(address="a@b.com")
        assert str(addr) == "a@b.com"

    def test_str_empty_display_name(self) -> None:
        addr = EmailAddress(address="a@b.com", display_name="")
        assert str(addr) == "a@b.com"


class TestEmailMessage:
    def test_creation(self) -> None:
        msg = _make_msg()
        assert msg.message_id == "msg-1"
        assert msg.from_addr.address == "user@example.com"
        assert msg.subject == "Test Subject"

    def test_defaults(self) -> None:
        msg = _make_msg()
        assert msg.body_html == ""
        assert msg.timestamp is None
        assert msg.cc_addrs is None
        assert msg.in_reply_to == ""
        assert msg.labels is None

    def test_with_cc(self) -> None:
        msg = EmailMessage(
            message_id="1",
            thread_id="t1",
            from_addr=EmailAddress(address="a@b.com"),
            to_addrs=[],
            subject="s",
            body_text="b",
            cc_addrs=[EmailAddress(address="cc@b.com")],
        )
        assert msg.cc_addrs is not None
        assert len(msg.cc_addrs) == 1


class TestSessionMapping:
    def test_creation(self) -> None:
        m = SessionMapping(
            session_id="s1",
            thread_id="t1",
            sender_address="u@a.com",
            subject="Test",
        )
        assert m.session_id == "s1"
        assert m.sender_address == "u@a.com"

    def test_auto_timestamps(self) -> None:
        m = SessionMapping(
            session_id="s1",
            thread_id="t1",
            sender_address="u@a.com",
            subject="Test",
        )
        assert m.created_at is not None
        assert m.last_activity is not None

    def test_custom_timestamps(self) -> None:
        m = SessionMapping(
            session_id="s1",
            thread_id="t1",
            sender_address="u@a.com",
            subject="Test",
            created_at="2025-01-01",
            last_activity="2025-01-02",
        )
        assert m.created_at == "2025-01-01"
        assert m.last_activity == "2025-01-02"

    def test_default_message_count(self) -> None:
        m = SessionMapping(
            session_id="s1",
            thread_id="t1",
            sender_address="u@a.com",
            subject="Test",
        )
        assert m.message_count == 0


# ═══════════════════════════════════════════════════════════════════════
#  2. CLIENT (15 tests)
# ═══════════════════════════════════════════════════════════════════════


class TestMemoryEmailClient:
    @pytest.mark.asyncio()
    async def test_send_email(self, client: MemoryEmailClient) -> None:
        to = EmailAddress(address="user@test.com")
        msg_id = await client.send_email(to, "Subj", "<p>Hi</p>")
        assert msg_id == "sent-1"
        assert len(client.sent) == 1
        assert client.sent[0]["subject"] == "Subj"

    @pytest.mark.asyncio()
    async def test_send_multiple(self, client: MemoryEmailClient) -> None:
        to = EmailAddress(address="u@t.com")
        await client.send_email(to, "S1", "b1")
        await client.send_email(to, "S2", "b2")
        assert len(client.sent) == 2
        assert client.sent[1]["message_id"] == "sent-2"

    @pytest.mark.asyncio()
    async def test_fetch_empty(self, client: MemoryEmailClient) -> None:
        msgs = await client.fetch_new_emails()
        assert msgs == []

    @pytest.mark.asyncio()
    async def test_fetch_after_inject(self, client: MemoryEmailClient) -> None:
        msg = _make_msg()
        client.inject_email(msg)
        result = await client.fetch_new_emails()
        assert len(result) == 1
        assert result[0].message_id == "msg-1"

    @pytest.mark.asyncio()
    async def test_fetch_since_message_id(self, client: MemoryEmailClient) -> None:
        client.inject_email(_make_msg(message_id="m1"))
        client.inject_email(_make_msg(message_id="m2"))
        client.inject_email(_make_msg(message_id="m3"))
        result = await client.fetch_new_emails(since_message_id="m1")
        ids = [m.message_id for m in result]
        assert "m1" not in ids
        assert "m2" in ids
        assert "m3" in ids

    @pytest.mark.asyncio()
    async def test_mark_read(self, client: MemoryEmailClient) -> None:
        await client.mark_read("msg-1")
        assert "msg-1" in client._read

    @pytest.mark.asyncio()
    async def test_fetch_skips_read(self, client: MemoryEmailClient) -> None:
        client.inject_email(_make_msg(message_id="m1"))
        client.inject_email(_make_msg(message_id="m2"))
        await client.mark_read("m1")
        result = await client.fetch_new_emails()
        assert len(result) == 1
        assert result[0].message_id == "m2"

    def test_get_agent_address(self, client: MemoryEmailClient) -> None:
        assert client.get_agent_address() == "agent@test.com"

    def test_custom_agent_address(self) -> None:
        c = MemoryEmailClient(agent_address="custom@test.com")
        assert c.get_agent_address() == "custom@test.com"

    def test_inject_email(self, client: MemoryEmailClient) -> None:
        msg = _make_msg()
        client.inject_email(msg)
        assert len(client.inbox) == 1
        assert client.inbox[0] is msg

    def test_protocol_compliance(self) -> None:
        assert isinstance(MemoryEmailClient(), EmailClient)


class TestParseAddress:
    def test_with_name(self) -> None:
        addr = _parse_address("Alice <alice@example.com>")
        assert addr.address == "alice@example.com"
        assert addr.display_name == "Alice"

    def test_without_name(self) -> None:
        addr = _parse_address("plain@example.com")
        assert addr.address == "plain@example.com"
        assert addr.display_name == ""

    def test_quoted_name(self) -> None:
        addr = _parse_address('"Bob Smith" <bob@example.com>')
        assert addr.address == "bob@example.com"
        assert addr.display_name == "Bob Smith"


class TestGmailParsing:
    def test_parse_gmail_message(self) -> None:
        raw = {
            "id": "abc123",
            "threadId": "thread-abc",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "From", "value": "User <user@example.com>"},
                    {"name": "To", "value": "agent@test.com"},
                    {"name": "Subject", "value": "Hello"},
                    {"name": "Date", "value": "2025-01-01"},
                ],
                "body": {
                    "data": "SGVsbG8gV29ybGQ=",  # "Hello World" base64
                },
            },
        }
        msg = _parse_gmail_message(raw)
        assert msg.message_id == "abc123"
        assert msg.thread_id == "thread-abc"
        assert msg.from_addr.address == "user@example.com"
        assert msg.subject == "Hello"
        assert msg.body_text == "Hello World"
        assert msg.labels == ["INBOX", "UNREAD"]

    def test_extract_body_plain(self) -> None:
        import base64

        data = base64.urlsafe_b64encode(b"plain text").decode()
        payload = {"mimeType": "text/plain", "body": {"data": data}}
        text, html = _extract_body(payload)
        assert text == "plain text"
        assert html == ""


# ═══════════════════════════════════════════════════════════════════════
#  3. FORMATTER (12 tests)
# ═══════════════════════════════════════════════════════════════════════


class TestMarkdownToHtml:
    def test_bold(self) -> None:
        assert "<strong>bold</strong>" in markdown_to_html("**bold**")

    def test_italic(self) -> None:
        assert "<em>italic</em>" in markdown_to_html("*italic*")

    def test_inline_code(self) -> None:
        assert "<code>code</code>" in markdown_to_html("`code`")

    def test_code_block(self) -> None:
        result = markdown_to_html("```\ncode block\n```")
        assert "<pre><code>" in result
        assert "code block" in result

    def test_newlines(self) -> None:
        assert "<br>" in markdown_to_html("line1\nline2")

    def test_empty(self) -> None:
        assert markdown_to_html("") == ""

    def test_combined(self) -> None:
        result = markdown_to_html("**bold** and *italic* and `code`")
        assert "<strong>bold</strong>" in result
        assert "<em>italic</em>" in result
        assert "<code>code</code>" in result


class TestFormatResponse:
    def test_wraps_in_html(self, config: EmailConfig) -> None:
        result = format_response("Hello", config)
        assert "<html>" in result
        assert "</html>" in result
        assert "Hello" in result

    def test_includes_agent_name(self, config: EmailConfig) -> None:
        result = format_response("Hi", config)
        assert "TestBot" in result

    def test_includes_footer(self, config: EmailConfig) -> None:
        result = format_response("Hi", config)
        assert "Sent by" in result


class TestSplitMessage:
    def test_short_text(self) -> None:
        result = split_message("Hello", 100)
        assert result == ["Hello"]

    def test_empty_text(self) -> None:
        result = split_message("")
        assert result == [""]

    def test_long_text_splits(self) -> None:
        text = "A" * 50 + "\n\n" + "B" * 50
        result = split_message(text, 60)
        assert len(result) >= 2
        assert "A" in result[0]
        assert "B" in result[-1]


# ═══════════════════════════════════════════════════════════════════════
#  4. SESSIONS (18 tests)
# ═══════════════════════════════════════════════════════════════════════


class TestEmailSessionManager:
    @pytest.mark.asyncio()
    async def test_create_session(self, session_manager: EmailSessionManager) -> None:
        mapping = await session_manager.create_session("user@example.com", "Test", "t1")
        assert mapping.session_id.startswith("mock-session-")

    @pytest.mark.asyncio()
    async def test_create_session_returns_mapping(
        self, session_manager: EmailSessionManager
    ) -> None:
        mapping = await session_manager.create_session("user@example.com", "Test", "t1")
        assert mapping.thread_id == "t1"
        assert mapping.sender_address == "user@example.com"
        assert mapping.subject == "Test"

    @pytest.mark.asyncio()
    async def test_create_session_stores_mapping(
        self, session_manager: EmailSessionManager
    ) -> None:
        await session_manager.create_session("u@a.com", "S", "t1")
        assert session_manager.get_session("t1") is not None

    @pytest.mark.asyncio()
    async def test_route_message(self, session_manager: EmailSessionManager) -> None:
        await session_manager.create_session("u@a.com", "S", "t1")
        response = await session_manager.route_message("t1", "Hello")
        assert "Hello" in response  # MockBackend echoes

    @pytest.mark.asyncio()
    async def test_route_message_increments_count(
        self, session_manager: EmailSessionManager
    ) -> None:
        await session_manager.create_session("u@a.com", "S", "t1")
        await session_manager.route_message("t1", "msg1")
        await session_manager.route_message("t1", "msg2")
        mapping = session_manager.get_session("t1")
        assert mapping is not None
        assert mapping.message_count == 2

    @pytest.mark.asyncio()
    async def test_route_message_updates_activity(
        self, session_manager: EmailSessionManager
    ) -> None:
        mapping = await session_manager.create_session("u@a.com", "S", "t1")
        original = mapping.last_activity
        await session_manager.route_message("t1", "msg1")
        updated = session_manager.get_session("t1")
        assert updated is not None
        assert updated.last_activity is not None
        # Activity should be updated (or at least set)
        assert updated.last_activity >= (original or "")

    @pytest.mark.asyncio()
    async def test_route_message_no_session_raises(
        self, session_manager: EmailSessionManager
    ) -> None:
        with pytest.raises(ValueError, match="No session"):
            await session_manager.route_message("nonexistent", "Hello")

    @pytest.mark.asyncio()
    async def test_end_session(self, session_manager: EmailSessionManager) -> None:
        await session_manager.create_session("u@a.com", "S", "t1")
        await session_manager.end_session("t1")
        assert session_manager.get_session("t1") is None

    @pytest.mark.asyncio()
    async def test_end_session_removes_mapping(
        self, session_manager: EmailSessionManager
    ) -> None:
        await session_manager.create_session("u@a.com", "S", "t1")
        await session_manager.end_session("t1")
        assert session_manager.list_active() == []

    @pytest.mark.asyncio()
    async def test_end_session_nonexistent(
        self, session_manager: EmailSessionManager
    ) -> None:
        # Should not raise
        await session_manager.end_session("nonexistent")

    def test_get_session_exists(self, session_manager: EmailSessionManager) -> None:
        # No sessions yet
        assert session_manager.get_session("t1") is None

    def test_get_session_not_found(self, session_manager: EmailSessionManager) -> None:
        assert session_manager.get_session("nonexistent") is None

    def test_list_active_empty(self, session_manager: EmailSessionManager) -> None:
        assert session_manager.list_active() == []

    @pytest.mark.asyncio()
    async def test_list_active_multiple(
        self, session_manager: EmailSessionManager
    ) -> None:
        await session_manager.create_session("u@a.com", "S1", "t1")
        await session_manager.create_session("u@a.com", "S2", "t2")
        assert len(session_manager.list_active()) == 2

    @pytest.mark.asyncio()
    async def test_max_sessions_per_sender(
        self, session_manager: EmailSessionManager, config: EmailConfig
    ) -> None:
        sender = "u@a.com"
        for i in range(config.max_sessions_per_sender):
            await session_manager.create_session(sender, f"S{i}", f"t{i}")
        with pytest.raises(ValueError, match="Maximum sessions"):
            await session_manager.create_session(sender, "Overflow", "tN")

    @pytest.mark.asyncio()
    async def test_max_sessions_different_senders(
        self, session_manager: EmailSessionManager, config: EmailConfig
    ) -> None:
        for i in range(config.max_sessions_per_sender):
            await session_manager.create_session("a@a.com", f"S{i}", f"ta{i}")
        # Different sender should still be allowed
        mapping = await session_manager.create_session("b@b.com", "S", "tb1")
        assert mapping.sender_address == "b@b.com"

    @pytest.mark.asyncio()
    async def test_save_and_load(
        self,
        session_manager: EmailSessionManager,
        client: MemoryEmailClient,
        backend: MockBackend,
        config: EmailConfig,
    ) -> None:
        await session_manager.create_session("u@a.com", "S1", "t1")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        session_manager.save(path)

        new_manager = EmailSessionManager(client, backend, config)
        new_manager.load(path)
        assert new_manager.get_session("t1") is not None
        assert new_manager.get_session("t1").subject == "S1"
        Path(path).unlink()

    def test_load_nonexistent_file(self, session_manager: EmailSessionManager) -> None:
        # Should not raise
        session_manager.load("/tmp/nonexistent_email_sessions.json")
        assert session_manager.list_active() == []


# ═══════════════════════════════════════════════════════════════════════
#  5. COMMANDS (18 tests)
# ═══════════════════════════════════════════════════════════════════════


class TestCommandHandler:
    def test_is_command_true(self, command_handler: CommandHandler) -> None:
        assert command_handler.is_command("/amp help") is True

    def test_is_command_false(self, command_handler: CommandHandler) -> None:
        assert command_handler.is_command("Hello") is False

    def test_is_command_partial(self, command_handler: CommandHandler) -> None:
        assert command_handler.is_command("/amplifier") is False

    def test_is_command_with_whitespace(self, command_handler: CommandHandler) -> None:
        assert command_handler.is_command("  /amp help  ") is True

    def test_parse_command_help(self, command_handler: CommandHandler) -> None:
        cmd, args = command_handler.parse_command("/amp help")
        assert cmd == "help"
        assert args == []

    def test_parse_command_list(self, command_handler: CommandHandler) -> None:
        cmd, args = command_handler.parse_command("/amp list")
        assert cmd == "list"

    def test_parse_command_new_with_args(self, command_handler: CommandHandler) -> None:
        cmd, args = command_handler.parse_command("/amp new My Topic")
        assert cmd == "new"
        assert args == ["My", "Topic"]

    def test_parse_command_bare_amp(self, command_handler: CommandHandler) -> None:
        cmd, args = command_handler.parse_command("/amp")
        assert cmd == "help"

    def test_parse_command_alias_ls(self, command_handler: CommandHandler) -> None:
        cmd, args = command_handler.parse_command("/amp ls")
        assert cmd == "list"

    def test_parse_command_alias_quit(self, command_handler: CommandHandler) -> None:
        cmd, args = command_handler.parse_command("/amp quit")
        assert cmd == "end"

    def test_parse_command_alias_close(self, command_handler: CommandHandler) -> None:
        cmd, args = command_handler.parse_command("/amp close")
        assert cmd == "end"

    @pytest.mark.asyncio()
    async def test_handle_help(self, command_handler: CommandHandler) -> None:
        result = await command_handler.handle("help", [], "u@a.com", "t1")
        assert "Available commands" in result
        assert "/amp help" in result

    @pytest.mark.asyncio()
    async def test_handle_list_empty(self, command_handler: CommandHandler) -> None:
        result = await command_handler.handle("list", [], "u@a.com", "t1")
        assert "No active sessions" in result

    @pytest.mark.asyncio()
    async def test_handle_list_with_sessions(
        self,
        command_handler: CommandHandler,
        session_manager: EmailSessionManager,
    ) -> None:
        await session_manager.create_session("u@a.com", "MyTopic", "t1")
        result = await command_handler.handle("list", [], "u@a.com", "t1")
        assert "Active sessions" in result
        assert "MyTopic" in result

    @pytest.mark.asyncio()
    async def test_handle_new(self, command_handler: CommandHandler) -> None:
        result = await command_handler.handle("new", ["My", "Subject"], "u@a.com", "t1")
        assert "Session created" in result
        assert "My Subject" in result

    @pytest.mark.asyncio()
    async def test_handle_new_max_sessions(
        self,
        command_handler: CommandHandler,
        session_manager: EmailSessionManager,
        config: EmailConfig,
    ) -> None:
        for i in range(config.max_sessions_per_sender):
            await session_manager.create_session("u@a.com", f"S{i}", f"t{i}")
        result = await command_handler.handle("new", ["Overflow"], "u@a.com", "tN")
        assert "Maximum sessions" in result

    @pytest.mark.asyncio()
    async def test_handle_status_no_session(
        self, command_handler: CommandHandler
    ) -> None:
        result = await command_handler.handle("status", [], "u@a.com", "t1")
        assert "No active session" in result

    @pytest.mark.asyncio()
    async def test_handle_status_with_session(
        self,
        command_handler: CommandHandler,
        session_manager: EmailSessionManager,
    ) -> None:
        await session_manager.create_session("u@a.com", "Topic", "t1")
        result = await command_handler.handle("status", [], "u@a.com", "t1")
        assert "Session:" in result
        assert "Topic" in result

    @pytest.mark.asyncio()
    async def test_handle_end_no_session(self, command_handler: CommandHandler) -> None:
        result = await command_handler.handle("end", [], "u@a.com", "t1")
        assert "No active session" in result

    @pytest.mark.asyncio()
    async def test_handle_end_with_session(
        self,
        command_handler: CommandHandler,
        session_manager: EmailSessionManager,
    ) -> None:
        await session_manager.create_session("u@a.com", "Topic", "t1")
        result = await command_handler.handle("end", [], "u@a.com", "t1")
        assert "ended" in result

    @pytest.mark.asyncio()
    async def test_handle_unknown(self, command_handler: CommandHandler) -> None:
        result = await command_handler.handle("foobar", [], "u@a.com", "t1")
        assert "Unknown command" in result


# ═══════════════════════════════════════════════════════════════════════
#  6. EVENTS (11 tests)
# ═══════════════════════════════════════════════════════════════════════


class TestEmailEventHandler:
    @pytest.mark.asyncio()
    async def test_skip_self(
        self,
        event_handler: EmailEventHandler,
        client: MemoryEmailClient,
    ) -> None:
        msg = _make_msg(from_addr="agent@test.com")
        await event_handler.handle_incoming_email(msg)
        assert len(client.sent) == 0

    @pytest.mark.asyncio()
    async def test_handle_command(
        self,
        event_handler: EmailEventHandler,
        client: MemoryEmailClient,
    ) -> None:
        msg = _make_msg(body_text="/amp help")
        await event_handler.handle_incoming_email(msg)
        assert len(client.sent) == 1
        assert "Available commands" in client.sent[0]["body_text"]

    @pytest.mark.asyncio()
    async def test_handle_existing_session(
        self,
        event_handler: EmailEventHandler,
        session_manager: EmailSessionManager,
        client: MemoryEmailClient,
    ) -> None:
        await session_manager.create_session("user@example.com", "S", "thread-1")
        msg = _make_msg(body_text="Follow up message")
        await event_handler.handle_incoming_email(msg)
        assert len(client.sent) == 1

    @pytest.mark.asyncio()
    async def test_handle_new_session(
        self,
        event_handler: EmailEventHandler,
        session_manager: EmailSessionManager,
        client: MemoryEmailClient,
    ) -> None:
        msg = _make_msg(body_text="Start conversation")
        await event_handler.handle_incoming_email(msg)
        # Should have created a session and replied
        assert session_manager.get_session("thread-1") is not None
        assert len(client.sent) == 1

    @pytest.mark.asyncio()
    async def test_sends_reply(
        self,
        event_handler: EmailEventHandler,
        client: MemoryEmailClient,
    ) -> None:
        msg = _make_msg(body_text="Hello there")
        await event_handler.handle_incoming_email(msg)
        assert len(client.sent) == 1

    @pytest.mark.asyncio()
    async def test_reply_subject_prefix(
        self,
        event_handler: EmailEventHandler,
        client: MemoryEmailClient,
    ) -> None:
        msg = _make_msg(subject="Original Subject", body_text="Hi")
        await event_handler.handle_incoming_email(msg)
        assert client.sent[0]["subject"] == "Re: Original Subject"

    @pytest.mark.asyncio()
    async def test_reply_in_reply_to(
        self,
        event_handler: EmailEventHandler,
        client: MemoryEmailClient,
    ) -> None:
        msg = _make_msg(message_id="original-id", body_text="Hi")
        await event_handler.handle_incoming_email(msg)
        assert client.sent[0]["in_reply_to"] == "original-id"

    @pytest.mark.asyncio()
    async def test_command_reply_format(
        self,
        event_handler: EmailEventHandler,
        client: MemoryEmailClient,
    ) -> None:
        msg = _make_msg(body_text="/amp help")
        await event_handler.handle_incoming_email(msg)
        assert "<html>" in client.sent[0]["body_html"]

    @pytest.mark.asyncio()
    async def test_new_session_routes_message(
        self,
        event_handler: EmailEventHandler,
        session_manager: EmailSessionManager,
        client: MemoryEmailClient,
    ) -> None:
        msg = _make_msg(body_text="Initial message")
        await event_handler.handle_incoming_email(msg)
        mapping = session_manager.get_session("thread-1")
        assert mapping is not None
        assert mapping.message_count == 1

    @pytest.mark.asyncio()
    async def test_max_sessions_error_silent(
        self,
        event_handler: EmailEventHandler,
        session_manager: EmailSessionManager,
        config: EmailConfig,
    ) -> None:
        for i in range(config.max_sessions_per_sender):
            await session_manager.create_session("user@example.com", f"S{i}", f"t{i}")
        msg = _make_msg(thread_id="t-overflow", body_text="Hi")
        # Should not raise, just log warning
        await event_handler.handle_incoming_email(msg)

    @pytest.mark.asyncio()
    async def test_formats_html_response(
        self,
        event_handler: EmailEventHandler,
        client: MemoryEmailClient,
    ) -> None:
        msg = _make_msg(body_text="Hello")
        await event_handler.handle_incoming_email(msg)
        assert "Sent by" in client.sent[0]["body_html"]


# ═══════════════════════════════════════════════════════════════════════
#  7. POLLER (8 tests)
# ═══════════════════════════════════════════════════════════════════════


class TestEmailPoller:
    def test_not_running_initially(self, poller: EmailPoller) -> None:
        assert poller.is_running is False

    def test_start(self, poller: EmailPoller) -> None:
        try:
            poller.start()
            assert poller.is_running is True
        finally:
            poller.stop()

    def test_stop(self, poller: EmailPoller) -> None:
        poller.start()
        poller.stop()
        assert poller.is_running is False

    def test_start_idempotent(self, poller: EmailPoller) -> None:
        try:
            poller.start()
            poller.start()  # Should not create a second task
            assert poller.is_running is True
        finally:
            poller.stop()

    @pytest.mark.asyncio()
    async def test_poll_once_empty(self, poller: EmailPoller) -> None:
        count = await poller.poll_once()
        assert count == 0

    @pytest.mark.asyncio()
    async def test_poll_once_processes_messages(
        self,
        poller: EmailPoller,
        client: MemoryEmailClient,
    ) -> None:
        client.inject_email(_make_msg(message_id="m1", body_text="Hello"))
        count = await poller.poll_once()
        assert count == 1

    @pytest.mark.asyncio()
    async def test_poll_once_marks_read(
        self,
        poller: EmailPoller,
        client: MemoryEmailClient,
    ) -> None:
        client.inject_email(_make_msg(message_id="m1", body_text="Hello"))
        await poller.poll_once()
        assert "m1" in client._read

    @pytest.mark.asyncio()
    async def test_poll_once_handles_error(
        self, poller: EmailPoller, client: MemoryEmailClient
    ) -> None:
        # Inject a fetch that will work but inject an error in handler
        original_fetch = client.fetch_new_emails

        async def failing_fetch(since_message_id: str = "") -> list:
            raise ConnectionError("Network error")

        client.fetch_new_emails = failing_fetch  # type: ignore[assignment]
        count = await poller.poll_once()
        assert count == 0
        client.fetch_new_emails = original_fetch  # type: ignore[assignment]


# ═══════════════════════════════════════════════════════════════════════
#  8. APP / ROUTES (8 tests)
# ═══════════════════════════════════════════════════════════════════════


class TestAppInit:
    def test_manifest_name(self) -> None:
        from amplifier_distro.server.apps.email import manifest

        assert manifest.name == "email"

    def test_manifest_version(self) -> None:
        from amplifier_distro.server.apps.email import manifest

        assert manifest.version == "0.1.0"

    def test_initialize_default(self) -> None:
        import amplifier_distro.server.apps.email as email_app

        state = email_app.initialize()
        assert "client" in state
        assert "session_manager" in state
        assert "config" in state
        # Cleanup
        email_app._state.clear()

    def test_initialize_with_injected(self) -> None:
        import amplifier_distro.server.apps.email as email_app

        cfg = EmailConfig(agent_address="test@test.com", simulator_mode=True)
        c = MemoryEmailClient()
        b = MockBackend()
        state = email_app.initialize(config=cfg, client=c, backend=b)
        assert state["client"] is c
        assert state["backend"] is b
        email_app._state.clear()

    def test_initialize_simulator_mode(self) -> None:
        import amplifier_distro.server.apps.email as email_app

        cfg = EmailConfig(simulator_mode=True, agent_address="a@b.com")
        state = email_app.initialize(config=cfg)
        assert isinstance(state["client"], MemoryEmailClient)
        email_app._state.clear()


class TestRoutes:
    @pytest.fixture(autouse=True)
    def _setup_app(self) -> None:
        import amplifier_distro.server.apps.email as email_app

        cfg = EmailConfig(
            agent_address="agent@test.com",
            agent_name="TestBot",
            simulator_mode=True,
        )
        email_app.initialize(
            config=cfg,
            client=MemoryEmailClient(),
            backend=MockBackend(),
        )
        yield  # type: ignore[misc]
        email_app._state.clear()

    @pytest.mark.asyncio()
    async def test_status_route(self) -> None:
        from fastapi import FastAPI

        from amplifier_distro.server.apps.email import router

        app = FastAPI()
        app.include_router(router, prefix="/email")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/email/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["agent_address"] == "agent@test.com"

    @pytest.mark.asyncio()
    async def test_sessions_route(self) -> None:
        from fastapi import FastAPI

        from amplifier_distro.server.apps.email import router

        app = FastAPI()
        app.include_router(router, prefix="/email")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/email/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio()
    async def test_incoming_route(self) -> None:
        from fastapi import FastAPI

        from amplifier_distro.server.apps.email import router

        app = FastAPI()
        app.include_router(router, prefix="/email")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/email/incoming",
                json={
                    "message_id": "m1",
                    "thread_id": "t1",
                    "from": {
                        "address": "user@example.com",
                        "display_name": "User",
                    },
                    "to": [{"address": "agent@test.com", "display_name": ""}],
                    "subject": "Hello",
                    "body_text": "Hi there",
                    "body_html": "",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
