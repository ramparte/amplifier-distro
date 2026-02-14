"""Tests for the email bridge.

Covers all modules: models, client, formatter, sessions,
commands, events, poller, config, setup routes, and the FastAPI app/routes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from amplifier_distro.server.apps.email.client import (
    EmailClient,
    MemoryEmailClient,
    _extract_body,
    _parse_address,
    _parse_gmail_message,
)
from amplifier_distro.server.apps.email.commands import ALIASES, CommandHandler
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

# -- Fixtures --


@pytest.fixture()
def config() -> EmailConfig:
    return EmailConfig(
        agent_address="agent@test.com",
        agent_name="TestBot",
        simulator_mode=True,
        max_sessions_per_user=3,
    )


@pytest.fixture()
def client() -> MemoryEmailClient:
    return MemoryEmailClient(agent_address="agent@test.com")


@pytest.fixture()
def backend() -> MockBackend:
    return MockBackend()


@pytest.fixture()
def session_manager(
    client: MemoryEmailClient, backend: MockBackend, config: EmailConfig, tmp_path: Path
) -> EmailSessionManager:
    """Session manager with persistence redirected to tmp_path."""
    mgr = EmailSessionManager(client, backend, config)
    # Override persistence path to avoid touching real filesystem
    mgr._sessions_path = lambda: tmp_path / "email-sessions.json"  # type: ignore[assignment]
    return mgr


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


# =====================================================================
#  1. MODELS
# =====================================================================


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

    def test_conversation_key_with_thread(self) -> None:
        m = SessionMapping(
            session_id="s1", thread_id="t1", sender_address="u@a.com", subject="Test"
        )
        assert m.conversation_key == "t1"

    def test_conversation_key_fallback(self) -> None:
        m = SessionMapping(
            session_id="s1", thread_id="", sender_address="u@a.com", subject="Test"
        )
        assert m.conversation_key == "u@a.com:Test"


# =====================================================================
#  2. CLIENT
# =====================================================================


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


# =====================================================================
#  3. FORMATTER
# =====================================================================


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

    def test_includes_session_id_when_provided(self, config: EmailConfig) -> None:
        result = format_response("Hi", config, session_id="test-session-123")
        assert "Session: test-session-123" in result
        assert "Sent by" in result

    def test_no_session_id_when_not_provided(self, config: EmailConfig) -> None:
        result = format_response("Hi", config)
        assert "Session:" not in result


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


# =====================================================================
#  4. CONFIG
# =====================================================================


class TestEmailConfig:
    def test_defaults(self) -> None:
        cfg = EmailConfig()
        assert cfg.agent_address == ""
        assert cfg.agent_name == "Amplifier"
        assert cfg.poll_interval_seconds == 30
        assert cfg.max_sessions_per_user == 10
        assert cfg.simulator_mode is False

    def test_effective_send_as_fallback(self) -> None:
        cfg = EmailConfig(agent_address="agent@test.com")
        assert cfg.effective_send_as == "agent@test.com"

    def test_effective_send_as_override(self) -> None:
        cfg = EmailConfig(agent_address="agent@test.com", send_as="custom@test.com")
        assert cfg.effective_send_as == "custom@test.com"

    def test_is_configured_false(self) -> None:
        cfg = EmailConfig()
        assert cfg.is_configured is False

    def test_is_configured_true(self) -> None:
        cfg = EmailConfig(
            gmail_client_id="id",
            gmail_client_secret="secret",
            gmail_refresh_token="token",
            agent_address="a@b.com",
        )
        assert cfg.is_configured is True

    def test_mode_simulator(self) -> None:
        cfg = EmailConfig(simulator_mode=True)
        assert cfg.mode == "simulator"

    def test_mode_configured(self) -> None:
        cfg = EmailConfig(
            gmail_client_id="id",
            gmail_client_secret="s",
            gmail_refresh_token="t",
            agent_address="a@b.com",
        )
        assert cfg.mode == "gmail-api"

    def test_mode_unconfigured(self) -> None:
        cfg = EmailConfig()
        assert cfg.mode == "unconfigured"

    def test_from_env_uses_env_vars(self) -> None:
        env = {
            "GMAIL_CLIENT_ID": "env-id",
            "GMAIL_CLIENT_SECRET": "env-secret",
            "GMAIL_REFRESH_TOKEN": "env-token",
            "EMAIL_AGENT_ADDRESS": "env@test.com",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = EmailConfig.from_env()
        assert cfg.gmail_client_id == "env-id"
        assert cfg.agent_address == "env@test.com"


# =====================================================================
#  5. SESSIONS
# =====================================================================


class TestEmailSessionManager:
    @pytest.mark.asyncio()
    async def test_get_or_create_creates_new(
        self, session_manager: EmailSessionManager
    ) -> None:
        msg = _make_msg(thread_id="t1")
        mapping = await session_manager.get_or_create_session(msg)
        assert mapping.session_id.startswith("mock-session-")
        assert mapping.thread_id == "t1"
        assert mapping.sender_address == "user@example.com"

    @pytest.mark.asyncio()
    async def test_get_or_create_returns_existing(
        self, session_manager: EmailSessionManager
    ) -> None:
        msg = _make_msg(thread_id="t1")
        m1 = await session_manager.get_or_create_session(msg)
        m2 = await session_manager.get_or_create_session(msg)
        assert m1.session_id == m2.session_id

    @pytest.mark.asyncio()
    async def test_get_or_create_increments_count(
        self, session_manager: EmailSessionManager
    ) -> None:
        msg = _make_msg(thread_id="t1")
        await session_manager.get_or_create_session(msg)
        await session_manager.get_or_create_session(msg)
        mapping = session_manager.get_by_thread("t1")
        assert mapping is not None
        # First call sets count=1, second call increments to 2
        assert mapping.message_count == 2

    @pytest.mark.asyncio()
    async def test_get_by_thread_exists(
        self, session_manager: EmailSessionManager
    ) -> None:
        msg = _make_msg(thread_id="t1")
        await session_manager.get_or_create_session(msg)
        assert session_manager.get_by_thread("t1") is not None

    def test_get_by_thread_not_found(
        self, session_manager: EmailSessionManager
    ) -> None:
        assert session_manager.get_by_thread("nonexistent") is None

    @pytest.mark.asyncio()
    async def test_send_message(self, session_manager: EmailSessionManager) -> None:
        msg = _make_msg(thread_id="t1")
        mapping = await session_manager.get_or_create_session(msg)
        response = await session_manager.send_message(mapping.session_id, "Hello")
        assert "Hello" in response  # MockBackend echoes

    @pytest.mark.asyncio()
    async def test_end_session(self, session_manager: EmailSessionManager) -> None:
        msg = _make_msg(thread_id="t1")
        await session_manager.get_or_create_session(msg)
        result = await session_manager.end_session("t1")
        assert result is True
        assert session_manager.get_by_thread("t1") is None

    @pytest.mark.asyncio()
    async def test_end_session_removes_from_active(
        self, session_manager: EmailSessionManager
    ) -> None:
        msg = _make_msg(thread_id="t1")
        await session_manager.get_or_create_session(msg)
        await session_manager.end_session("t1")
        assert session_manager.list_active() == []

    @pytest.mark.asyncio()
    async def test_end_session_nonexistent(
        self, session_manager: EmailSessionManager
    ) -> None:
        result = await session_manager.end_session("nonexistent")
        assert result is False

    def test_list_active_empty(self, session_manager: EmailSessionManager) -> None:
        assert session_manager.list_active() == []

    @pytest.mark.asyncio()
    async def test_list_active_multiple(
        self, session_manager: EmailSessionManager
    ) -> None:
        await session_manager.get_or_create_session(_make_msg(thread_id="t1"))
        await session_manager.get_or_create_session(
            _make_msg(thread_id="t2", from_addr="other@test.com")
        )
        assert len(session_manager.list_active()) == 2

    @pytest.mark.asyncio()
    async def test_max_sessions_auto_ends_oldest(
        self, session_manager: EmailSessionManager, config: EmailConfig
    ) -> None:
        """When max sessions reached, oldest is auto-ended."""
        sender = "user@example.com"
        for i in range(config.max_sessions_per_user):
            await session_manager.get_or_create_session(
                _make_msg(
                    thread_id=f"t{i}",
                    from_addr=sender,
                    subject=f"S{i}",
                )
            )
        # Next session auto-ends the oldest
        await session_manager.get_or_create_session(
            _make_msg(thread_id="t-new", from_addr=sender, subject="New")
        )
        # Should have max_sessions_per_user sessions (oldest was ended)
        active = session_manager.list_for_sender(sender)
        assert len(active) == config.max_sessions_per_user

    @pytest.mark.asyncio()
    async def test_max_sessions_different_senders(
        self, session_manager: EmailSessionManager, config: EmailConfig
    ) -> None:
        for i in range(config.max_sessions_per_user):
            await session_manager.get_or_create_session(
                _make_msg(thread_id=f"ta{i}", from_addr="a@a.com")
            )
        # Different sender should still work
        mapping = await session_manager.get_or_create_session(
            _make_msg(thread_id="tb1", from_addr="b@b.com")
        )
        assert mapping.sender_address == "b@b.com"

    @pytest.mark.asyncio()
    async def test_connect_session(self, session_manager: EmailSessionManager) -> None:
        mapping = await session_manager.connect_session(
            thread_id="t1",
            session_id="existing-session-123",
            sender_address="u@a.com",
        )
        assert mapping.session_id == "existing-session-123"
        assert mapping.thread_id == "t1"
        assert session_manager.get_by_thread("t1") is not None

    @pytest.mark.asyncio()
    async def test_get_by_session_id(
        self, session_manager: EmailSessionManager
    ) -> None:
        msg = _make_msg(thread_id="t1")
        m = await session_manager.get_or_create_session(msg)
        found = session_manager.get_by_session_id(m.session_id)
        assert found is not None
        assert found.thread_id == "t1"

    def test_get_by_session_id_not_found(
        self, session_manager: EmailSessionManager
    ) -> None:
        assert session_manager.get_by_session_id("nonexistent") is None

    @pytest.mark.asyncio()
    async def test_list_for_sender(self, session_manager: EmailSessionManager) -> None:
        await session_manager.get_or_create_session(
            _make_msg(thread_id="t1", from_addr="a@a.com")
        )
        await session_manager.get_or_create_session(
            _make_msg(thread_id="t2", from_addr="b@b.com")
        )
        assert len(session_manager.list_for_sender("a@a.com")) == 1

    @pytest.mark.asyncio()
    async def test_persistence(
        self, session_manager: EmailSessionManager, tmp_path: Path
    ) -> None:
        """Sessions are persisted to JSON file."""
        await session_manager.get_or_create_session(_make_msg(thread_id="t1"))
        path = session_manager._sessions_path()
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["thread_id"] == "t1"


# =====================================================================
#  6. COMMANDS
# =====================================================================


class TestCommandHandler:
    def test_is_command_true(self, command_handler: CommandHandler) -> None:
        assert command_handler.is_command("/amp help") is True

    def test_is_command_false(self, command_handler: CommandHandler) -> None:
        assert command_handler.is_command("Hello") is False

    def test_is_command_partial(self, command_handler: CommandHandler) -> None:
        assert command_handler.is_command("/amplifier") is False

    def test_is_command_with_whitespace(self, command_handler: CommandHandler) -> None:
        assert command_handler.is_command("  /amp help  ") is True

    def test_is_command_bare(self, command_handler: CommandHandler) -> None:
        assert command_handler.is_command("/amp") is True

    def test_is_command_skips_quoted_reply(
        self, command_handler: CommandHandler
    ) -> None:
        text = "> Previous reply\n> More quote\n/amp help"
        assert command_handler.is_command(text) is True

    def test_is_command_not_in_quote(self, command_handler: CommandHandler) -> None:
        text = "> /amp help\nRegular text"
        assert command_handler.is_command(text) is False

    def test_parse_command_help(self, command_handler: CommandHandler) -> None:
        cmd, args = command_handler.parse_command("/amp help")
        assert cmd == "help"
        assert args == []

    def test_parse_command_list(self, command_handler: CommandHandler) -> None:
        cmd, _args = command_handler.parse_command("/amp list")
        assert cmd == "list"

    def test_parse_command_new_with_args(self, command_handler: CommandHandler) -> None:
        cmd, args = command_handler.parse_command("/amp new My Topic")
        assert cmd == "new"
        assert args == ["My", "Topic"]

    def test_parse_command_bare_amp(self, command_handler: CommandHandler) -> None:
        cmd, _args = command_handler.parse_command("/amp")
        assert cmd == "help"

    def test_parse_command_alias_ls(self, command_handler: CommandHandler) -> None:
        cmd, _args = command_handler.parse_command("/amp ls")
        assert cmd == "list"

    def test_parse_command_alias_quit(self, command_handler: CommandHandler) -> None:
        cmd, _args = command_handler.parse_command("/amp quit")
        assert cmd == "end"

    def test_parse_command_alias_close(self, command_handler: CommandHandler) -> None:
        cmd, _args = command_handler.parse_command("/amp close")
        assert cmd == "end"

    def test_parse_command_alias_link(self, command_handler: CommandHandler) -> None:
        cmd, _ = command_handler.parse_command("/amp link")
        assert cmd == "connect"

    def test_parse_command_alias_detach(self, command_handler: CommandHandler) -> None:
        cmd, _ = command_handler.parse_command("/amp detach")
        assert cmd == "disconnect"

    def test_all_aliases_resolve(self) -> None:
        """Verify all aliases map to real commands."""
        real_commands = {
            "help",
            "list",
            "sessions",
            "new",
            "status",
            "end",
            "connect",
            "disconnect",
            "config",
        }
        for alias, target in ALIASES.items():
            assert target in real_commands, f"Alias {alias} -> {target} is invalid"

    @pytest.mark.asyncio()
    async def test_handle_help(self, command_handler: CommandHandler) -> None:
        result = await command_handler.handle("help", [], "u@a.com", "t1")
        assert "Email Bridge Commands" in result
        assert "/amp help" in result

    @pytest.mark.asyncio()
    async def test_handle_list_empty(self, command_handler: CommandHandler) -> None:
        result = await command_handler.handle("list", [], "u@a.com", "t1")
        assert "No active" in result

    @pytest.mark.asyncio()
    async def test_handle_list_with_sessions(
        self,
        command_handler: CommandHandler,
        session_manager: EmailSessionManager,
    ) -> None:
        await session_manager.get_or_create_session(
            _make_msg(thread_id="t1", subject="MyTopic")
        )
        result = await command_handler.handle("list", [], "u@a.com", "t1")
        assert "Active sessions" in result
        assert "MyTopic" in result

    @pytest.mark.asyncio()
    async def test_handle_new(self, command_handler: CommandHandler) -> None:
        result = await command_handler.handle("new", ["My", "Subject"], "u@a.com", "t1")
        assert "Session started" in result

    @pytest.mark.asyncio()
    async def test_handle_new_replaces_existing(
        self,
        command_handler: CommandHandler,
        session_manager: EmailSessionManager,
    ) -> None:
        """Starting a new session on a thread with existing session ends the old one."""
        await session_manager.get_or_create_session(_make_msg(thread_id="t1"))
        old_id = session_manager.get_by_thread("t1").session_id  # type: ignore[union-attr]
        result = await command_handler.handle("new", ["Fresh"], "u@a.com", "t1")
        assert "Session started" in result
        new_mapping = session_manager.get_by_thread("t1")
        assert new_mapping is not None
        assert new_mapping.session_id != old_id

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
        await session_manager.get_or_create_session(
            _make_msg(thread_id="t1", subject="Topic")
        )
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
        await session_manager.get_or_create_session(_make_msg(thread_id="t1"))
        result = await command_handler.handle("end", [], "u@a.com", "t1")
        assert "ended" in result

    @pytest.mark.asyncio()
    async def test_handle_connect_no_args(
        self, command_handler: CommandHandler
    ) -> None:
        result = await command_handler.handle("connect", [], "u@a.com", "t1")
        assert "Usage" in result

    @pytest.mark.asyncio()
    async def test_handle_disconnect_no_session(
        self, command_handler: CommandHandler
    ) -> None:
        result = await command_handler.handle("disconnect", [], "u@a.com", "t1")
        assert "No session connected" in result

    @pytest.mark.asyncio()
    async def test_handle_disconnect_with_session(
        self,
        command_handler: CommandHandler,
        session_manager: EmailSessionManager,
    ) -> None:
        await session_manager.get_or_create_session(_make_msg(thread_id="t1"))
        result = await command_handler.handle("disconnect", [], "u@a.com", "t1")
        assert "Disconnected" in result
        # Thread mapping removed but session still referenced
        assert session_manager.get_by_thread("t1") is None

    @pytest.mark.asyncio()
    async def test_handle_config(self, command_handler: CommandHandler) -> None:
        result = await command_handler.handle("config", [], "u@a.com", "t1")
        assert "Email Bridge Configuration" in result
        assert "agent@test.com" in result

    @pytest.mark.asyncio()
    async def test_handle_unknown(self, command_handler: CommandHandler) -> None:
        result = await command_handler.handle("foobar", [], "u@a.com", "t1")
        assert "Unknown command" in result


# =====================================================================
#  7. EVENTS
# =====================================================================


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
    async def test_skip_empty_body(
        self,
        event_handler: EmailEventHandler,
        client: MemoryEmailClient,
    ) -> None:
        msg = _make_msg(body_text="")
        await event_handler.handle_incoming_email(msg)
        assert len(client.sent) == 0

    @pytest.mark.asyncio()
    async def test_skip_whitespace_body(
        self,
        event_handler: EmailEventHandler,
        client: MemoryEmailClient,
    ) -> None:
        msg = _make_msg(body_text="   \n  \n  ")
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
        assert "Email Bridge Commands" in client.sent[0]["body_text"]

    @pytest.mark.asyncio()
    async def test_handle_existing_session(
        self,
        event_handler: EmailEventHandler,
        session_manager: EmailSessionManager,
        client: MemoryEmailClient,
    ) -> None:
        # Create session first
        await session_manager.get_or_create_session(_make_msg(thread_id="thread-1"))
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
        assert session_manager.get_by_thread("thread-1") is not None
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
    async def test_reply_html_format(
        self,
        event_handler: EmailEventHandler,
        client: MemoryEmailClient,
    ) -> None:
        msg = _make_msg(body_text="Hello")
        await event_handler.handle_incoming_email(msg)
        assert "<html>" in client.sent[0]["body_html"]
        assert "Sent by" in client.sent[0]["body_html"]

    @pytest.mark.asyncio()
    async def test_new_session_increments_count(
        self,
        event_handler: EmailEventHandler,
        session_manager: EmailSessionManager,
    ) -> None:
        msg = _make_msg(body_text="Initial message")
        await event_handler.handle_incoming_email(msg)
        mapping = session_manager.get_by_thread("thread-1")
        assert mapping is not None
        # get_or_create_session sets count=1 on creation,
        # then send_message doesn't touch it
        assert mapping.message_count >= 1

    @pytest.mark.asyncio()
    async def test_truncates_long_messages(
        self,
        event_handler: EmailEventHandler,
        client: MemoryEmailClient,
        config: EmailConfig,
    ) -> None:
        long_body = "x" * (config.max_message_length + 100)
        msg = _make_msg(body_text=long_body)
        await event_handler.handle_incoming_email(msg)
        # Should still process and reply (may split into multiple emails)
        assert len(client.sent) >= 1

    @pytest.mark.asyncio()
    async def test_error_handling(
        self,
        event_handler: EmailEventHandler,
        session_manager: EmailSessionManager,
        client: MemoryEmailClient,
    ) -> None:
        """Errors in session handling result in error reply, not crash."""
        # Override send_message to raise
        original = session_manager.send_message

        async def failing_send(session_id: str, text: str) -> str:
            raise RuntimeError("Backend failure")

        session_manager.send_message = failing_send  # type: ignore[assignment]
        msg = _make_msg(body_text="Hello")
        await event_handler.handle_incoming_email(msg)
        assert len(client.sent) == 1
        assert "error" in client.sent[0]["body_text"].lower()
        session_manager.send_message = original  # type: ignore[assignment]


# =====================================================================
#  8. POLLER
# =====================================================================


class TestEmailPoller:
    def test_not_running_initially(self, poller: EmailPoller) -> None:
        assert poller.is_running is False

    @pytest.mark.asyncio()
    async def test_start(self, poller: EmailPoller) -> None:
        try:
            poller.start()
            assert poller.is_running is True
        finally:
            poller.stop()

    @pytest.mark.asyncio()
    async def test_stop(self, poller: EmailPoller) -> None:
        poller.start()
        poller.stop()
        assert poller.is_running is False

    @pytest.mark.asyncio()
    async def test_start_idempotent(self, poller: EmailPoller) -> None:
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
    async def test_poll_once_handles_fetch_error(
        self, poller: EmailPoller, client: MemoryEmailClient
    ) -> None:
        original_fetch = client.fetch_new_emails

        async def failing_fetch(since_message_id: str = "") -> list:
            raise ConnectionError("Network error")

        client.fetch_new_emails = failing_fetch  # type: ignore[assignment]
        count = await poller.poll_once()
        assert count == 0
        client.fetch_new_emails = original_fetch  # type: ignore[assignment]


# =====================================================================
#  9. APP INIT AND ROUTES
# =====================================================================


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
        assert "poller" in state
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
    def _setup_app(self):  # type: ignore[override]
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
    async def test_poll_once_route(self) -> None:
        from fastapi import FastAPI

        from amplifier_distro.server.apps.email import router

        app = FastAPI()
        app.include_router(router, prefix="/email")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/email/poll/once")
        assert resp.status_code == 200
        assert resp.json()["processed"] == 0

    @pytest.mark.asyncio()
    async def test_send_route(self) -> None:
        from fastapi import FastAPI

        from amplifier_distro.server.apps.email import router

        app = FastAPI()
        app.include_router(router, prefix="/email")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/email/send",
                json={"to": "someone@test.com", "subject": "Hi", "body": "Hello"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "sent"

    @pytest.mark.asyncio()
    async def test_send_route_missing_fields(self) -> None:
        from fastapi import FastAPI

        from amplifier_distro.server.apps.email import router

        app = FastAPI()
        app.include_router(router, prefix="/email")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/email/send", json={"to": "", "body": ""})
        assert resp.status_code == 200
        assert "error" in resp.json()


# =====================================================================
#  10. SETUP ROUTES
# =====================================================================


class TestSetupRoutes:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path):  # type: ignore[override]
        """Redirect config paths to tmp_path for isolation."""
        import amplifier_distro.server.apps.email as email_app

        cfg = EmailConfig(
            agent_address="agent@test.com",
            simulator_mode=True,
        )
        email_app.initialize(
            config=cfg,
            client=MemoryEmailClient(),
            backend=MockBackend(),
        )

        # Patch setup module paths
        self._tmp = tmp_path
        from amplifier_distro.server.apps.email import setup

        self._orig_home = setup._amplifier_home
        setup._amplifier_home = lambda: tmp_path  # type: ignore[assignment]

        # Save and clear Gmail env vars to prevent leaking between tests
        _env_keys = [
            "GMAIL_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GMAIL_REFRESH_TOKEN",
            "EMAIL_AGENT_ADDRESS",
            "EMAIL_AGENT_NAME",
        ]
        _saved_env = {k: os.environ.pop(k, None) for k in _env_keys}

        yield  # type: ignore[misc]

        # Restore env vars
        for k, v in _saved_env.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        setup._amplifier_home = self._orig_home
        email_app._state.clear()

    def _app(self):
        from fastapi import FastAPI

        from amplifier_distro.server.apps.email import router

        app = FastAPI()
        app.include_router(router, prefix="/email")
        return app

    @pytest.mark.asyncio()
    async def test_setup_status(self) -> None:
        app = self._app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/email/setup/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "configured" in data
        assert "steps" in data

    @pytest.mark.asyncio()
    async def test_setup_configure_saves_keys(self) -> None:
        app = self._app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/email/setup/configure",
                json={
                    "gmail_client_id": "test-client-id",
                    "gmail_client_secret": "test-secret",
                    "gmail_refresh_token": "test-token",
                    "agent_address": "agent@test.com",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved"

        # Verify keys were persisted
        import yaml

        keys_path = self._tmp / "keys.yaml"
        assert keys_path.exists()
        keys = yaml.safe_load(keys_path.read_text())
        assert keys["GMAIL_CLIENT_ID"] == "test-client-id"

    @pytest.mark.asyncio()
    async def test_setup_configure_saves_distro_yaml(self) -> None:
        app = self._app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            await ac.post(
                "/email/setup/configure",
                json={
                    "gmail_client_id": "id",
                    "gmail_client_secret": "secret",
                    "agent_address": "agent@test.com",
                    "agent_name": "MyBot",
                },
            )

        import yaml

        distro_path = self._tmp / "distro.yaml"
        assert distro_path.exists()
        data = yaml.safe_load(distro_path.read_text())
        assert data["email"]["agent_address"] == "agent@test.com"
        assert data["email"]["agent_name"] == "MyBot"

    @pytest.mark.asyncio()
    async def test_setup_oauth_start_no_client_id(self) -> None:
        app = self._app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/email/setup/oauth/start")
        data = resp.json()
        assert "error" in data

    @pytest.mark.asyncio()
    async def test_setup_oauth_start_with_client_id(self) -> None:
        """After configuring client_id, oauth/start returns auth URL."""
        app = self._app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # First configure the client ID
            await ac.post(
                "/email/setup/configure",
                json={
                    "gmail_client_id": "test-client-id",
                    "gmail_client_secret": "test-secret",
                    "agent_address": "a@b.com",
                },
            )
            resp = await ac.get("/email/setup/oauth/start")
        data = resp.json()
        assert "auth_url" in data
        assert "test-client-id" in data["auth_url"]

    @pytest.mark.asyncio()
    async def test_setup_instructions(self) -> None:
        app = self._app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/email/setup/instructions")
        data = resp.json()
        assert "steps" in data
        assert len(data["steps"]) >= 5

    @pytest.mark.asyncio()
    async def test_setup_test_not_configured(self) -> None:
        app = self._app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/email/setup/test")
        data = resp.json()
        assert "error" in data
