"""Tests for the Slack bridge.

Covers: models, config, client, formatter, discovery, backend,
session management, commands, events, and HTTP endpoints.
"""

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

# --- Fixtures ---


@pytest.fixture
def slack_client():
    """Create a fresh MemorySlackClient."""
    from amplifier_distro.server.apps.slack.client import MemorySlackClient

    return MemorySlackClient()


@pytest.fixture
def mock_backend():
    """Create a fresh MockBackend."""
    from amplifier_distro.server.apps.slack.backend import MockBackend

    return MockBackend()


@pytest.fixture
def slack_config():
    """Create a test SlackConfig."""
    from amplifier_distro.server.apps.slack.config import SlackConfig

    return SlackConfig(
        hub_channel_id="C_HUB",
        hub_channel_name="amplifier",
        simulator_mode=True,
        bot_name="amp",
    )


@pytest.fixture
def session_manager(slack_client, mock_backend, slack_config):
    """Create a SlackSessionManager with test dependencies."""
    from amplifier_distro.server.apps.slack.sessions import SlackSessionManager

    return SlackSessionManager(slack_client, mock_backend, slack_config)


@pytest.fixture
def discovery(tmp_path):
    """Create an AmplifierDiscovery pointed at a temp directory."""
    from amplifier_distro.server.apps.slack.discovery import AmplifierDiscovery

    return AmplifierDiscovery(amplifier_home=str(tmp_path))


@pytest.fixture
def command_handler(session_manager, discovery, slack_config):
    """Create a CommandHandler with test dependencies."""
    from amplifier_distro.server.apps.slack.commands import CommandHandler

    return CommandHandler(session_manager, discovery, slack_config)


@pytest.fixture
def bridge_client(slack_client, mock_backend, slack_config, discovery):
    """Create a TestClient for the Slack bridge HTTP endpoints."""
    from amplifier_distro.server.app import DistroServer
    from amplifier_distro.server.apps.slack import _state, initialize, manifest

    # Clear any previous state
    _state.clear()

    server = DistroServer()

    # Initialize with injected test dependencies
    initialize(
        config=slack_config,
        client=slack_client,
        backend=mock_backend,
        discovery=discovery,
    )

    server.register_app(manifest)
    return TestClient(server.app)


# --- Model Tests ---


class TestSlackModels:
    """Test data models for correctness and edge cases."""

    def test_slack_message_conversation_key_top_level(self):
        from amplifier_distro.server.apps.slack.models import SlackMessage

        msg = SlackMessage(channel_id="C123", user_id="U1", text="hi", ts="1.0")
        assert msg.conversation_key == "C123"
        assert not msg.is_threaded

    def test_slack_message_conversation_key_threaded(self):
        from amplifier_distro.server.apps.slack.models import SlackMessage

        msg = SlackMessage(
            channel_id="C123", user_id="U1", text="hi", ts="2.0", thread_ts="1.0"
        )
        assert msg.conversation_key == "C123:1.0"
        assert msg.is_threaded

    def test_session_mapping_conversation_key(self):
        from amplifier_distro.server.apps.slack.models import SessionMapping

        m1 = SessionMapping(session_id="s1", channel_id="C1")
        assert m1.conversation_key == "C1"

        m2 = SessionMapping(session_id="s2", channel_id="C1", thread_ts="1.0")
        assert m2.conversation_key == "C1:1.0"

    def test_session_mapping_defaults(self):
        from amplifier_distro.server.apps.slack.models import SessionMapping

        m = SessionMapping(session_id="test", channel_id="C1")
        assert m.is_active is True
        assert m.created_at  # Should have a default timestamp
        assert m.last_active

    def test_channel_type_enum(self):
        from amplifier_distro.server.apps.slack.models import ChannelType

        assert ChannelType.HUB == "hub"
        assert ChannelType.SESSION == "session"


# --- Config Tests ---


class TestSlackConfig:
    """Test configuration loading and mode detection."""

    def test_default_config(self):
        from amplifier_distro.server.apps.slack.config import SlackConfig

        cfg = SlackConfig()
        assert not cfg.is_configured
        assert cfg.mode == "unconfigured"

    def test_simulator_mode(self):
        from amplifier_distro.server.apps.slack.config import SlackConfig

        cfg = SlackConfig(simulator_mode=True)
        assert cfg.mode == "simulator"

    def test_live_mode(self):
        from amplifier_distro.server.apps.slack.config import SlackConfig

        cfg = SlackConfig(bot_token="xoxb-test", signing_secret="secret")
        assert cfg.is_configured
        assert cfg.mode == "events-api"

    def test_from_env(self):
        from amplifier_distro.server.apps.slack.config import SlackConfig

        env = {
            "SLACK_BOT_TOKEN": "xoxb-from-env",
            "SLACK_SIGNING_SECRET": "env-secret",
            "SLACK_HUB_CHANNEL_ID": "C_ENV",
            "SLACK_SIMULATOR_MODE": "true",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = SlackConfig.from_env()
        assert cfg.bot_token == "xoxb-from-env"
        assert cfg.signing_secret == "env-secret"
        assert cfg.hub_channel_id == "C_ENV"
        assert cfg.simulator_mode is True


# --- Client Tests ---


class TestMemorySlackClient:
    """Test the in-memory Slack client."""

    def test_post_message(self, slack_client):
        ts = asyncio.run(slack_client.post_message("C1", "hello"))
        assert ts  # Non-empty timestamp
        assert len(slack_client.sent_messages) == 1
        assert slack_client.sent_messages[0].text == "hello"
        assert slack_client.sent_messages[0].channel == "C1"

    def test_post_threaded_message(self, slack_client):
        asyncio.run(slack_client.post_message("C1", "reply", thread_ts="parent.ts"))
        assert len(slack_client.sent_messages) == 1
        assert slack_client.sent_messages[0].thread_ts == "parent.ts"

    def test_update_message(self, slack_client):
        asyncio.run(slack_client.update_message("C1", "1.0", "updated"))
        assert len(slack_client.updated_messages) == 1
        assert slack_client.updated_messages[0]["text"] == "updated"

    def test_create_channel(self, slack_client):
        ch = asyncio.run(slack_client.create_channel("test-channel", topic="Test"))
        assert ch.name == "test-channel"
        assert ch.topic == "Test"
        assert ch.id.startswith("C")
        # Should be retrievable
        info = asyncio.run(slack_client.get_channel_info(ch.id))
        assert info is not None
        assert info.name == "test-channel"

    def test_get_nonexistent_channel(self, slack_client):
        info = asyncio.run(slack_client.get_channel_info("C_FAKE"))
        assert info is None

    def test_add_reaction(self, slack_client):
        asyncio.run(slack_client.add_reaction("C1", "1.0", "thumbsup"))
        assert len(slack_client.reactions) == 1
        assert slack_client.reactions[0]["emoji"] == "thumbsup"

    def test_get_bot_user_id(self, slack_client):
        uid = asyncio.run(slack_client.get_bot_user_id())
        assert uid == "U_AMP_BOT"

    def test_seed_channel(self, slack_client):
        from amplifier_distro.server.apps.slack.models import SlackChannel

        ch = SlackChannel(id="C_SEED", name="seeded")
        slack_client.seed_channel(ch)
        info = asyncio.run(slack_client.get_channel_info("C_SEED"))
        assert info is not None
        assert info.name == "seeded"

    def test_on_message_sent_callback(self, slack_client):
        captured = []
        slack_client.on_message_sent = lambda msg: captured.append(msg)
        asyncio.run(slack_client.post_message("C1", "watched"))
        assert len(captured) == 1
        assert captured[0].text == "watched"


# --- Formatter Tests ---


class TestSlackFormatter:
    """Test markdown to Slack mrkdwn conversion and message splitting."""

    def test_bold_conversion(self):
        from amplifier_distro.server.apps.slack.formatter import SlackFormatter

        assert SlackFormatter.markdown_to_slack("**bold**") == "*bold*"

    def test_strikethrough_conversion(self):
        from amplifier_distro.server.apps.slack.formatter import SlackFormatter

        assert SlackFormatter.markdown_to_slack("~~strike~~") == "~strike~"

    def test_link_conversion(self):
        from amplifier_distro.server.apps.slack.formatter import SlackFormatter

        result = SlackFormatter.markdown_to_slack("[click here](https://example.com)")
        assert result == "<https://example.com|click here>"

    def test_header_conversion(self):
        from amplifier_distro.server.apps.slack.formatter import SlackFormatter

        assert SlackFormatter.markdown_to_slack("## My Header") == "*My Header*"

    def test_bullet_conversion(self):
        from amplifier_distro.server.apps.slack.formatter import SlackFormatter

        result = SlackFormatter.markdown_to_slack("- item one\n- item two")
        assert "item one" in result
        assert "item two" in result

    def test_empty_string(self):
        from amplifier_distro.server.apps.slack.formatter import SlackFormatter

        assert SlackFormatter.markdown_to_slack("") == ""

    def test_split_short_message(self):
        from amplifier_distro.server.apps.slack.formatter import SlackFormatter

        result = SlackFormatter.split_message("short", max_length=100)
        assert result == ["short"]

    def test_split_long_message(self):
        from amplifier_distro.server.apps.slack.formatter import SlackFormatter

        text = "paragraph one\n\nparagraph two\n\nparagraph three"
        result = SlackFormatter.split_message(text, max_length=25)
        assert len(result) >= 2
        combined = "\n".join(result)
        assert "paragraph one" in combined
        assert "paragraph three" in combined

    def test_format_session_list_empty(self):
        from amplifier_distro.server.apps.slack.formatter import SlackFormatter

        blocks = SlackFormatter.format_session_list([])
        assert any("No sessions" in str(b) for b in blocks)

    def test_format_session_list_with_data(self):
        from amplifier_distro.server.apps.slack.formatter import SlackFormatter

        sessions = [
            {
                "session_id": "abc12345-full-uuid",
                "project": "test-project",
                "date_str": "02/08 10:00",
                "name": "My Session",
                "description": "test desc",
            },
        ]
        blocks = SlackFormatter.format_session_list(sessions)
        assert len(blocks) >= 2  # Header + at least one section
        assert any("connect_session" in str(b) for b in blocks)

    def test_format_help(self):
        from amplifier_distro.server.apps.slack.formatter import SlackFormatter

        blocks = SlackFormatter.format_help()
        text = str(blocks)
        assert "list" in text
        assert "new" in text
        assert "connect" in text

    def test_format_error(self):
        from amplifier_distro.server.apps.slack.formatter import SlackFormatter

        blocks = SlackFormatter.format_error("something broke")
        assert any("something broke" in str(b) for b in blocks)

    def test_format_status(self):
        from amplifier_distro.server.apps.slack.formatter import SlackFormatter

        blocks = SlackFormatter.format_status("abc123", project="proj", is_active=True)
        text = str(blocks)
        assert "abc123" in text
        assert "Active" in text


# --- Discovery Tests ---


class TestAmplifierDiscovery:
    """Test session and project discovery from the filesystem.

    Uses a temp directory structure mimicking ~/.amplifier/projects/.
    """

    def _create_session(
        self, base: Path, project_path: str, session_id: str, name: str = ""
    ):
        """Helper to create a fake session on disk."""
        encoded = project_path.replace("/", "-")
        sessions_dir = base / "projects" / encoded / "sessions" / session_id
        sessions_dir.mkdir(parents=True, exist_ok=True)

        # Write transcript (required)
        (sessions_dir / "transcript.jsonl").write_text(
            '{"role":"user","content":"test"}\n'
        )

        # Write metadata if name provided
        if name:
            (sessions_dir / "metadata.json").write_text(
                json.dumps({"name": name, "description": f"desc for {name}"})
            )

    def test_list_sessions_empty(self, discovery):
        assert discovery.list_sessions() == []

    def test_list_sessions(self, tmp_path, discovery):
        self._create_session(tmp_path, "/home/sam/project-a", "sess-001", name="First")
        self._create_session(tmp_path, "/home/sam/project-b", "sess-002", name="Second")

        sessions = discovery.list_sessions()
        assert len(sessions) == 2
        names = {s.name for s in sessions}
        assert "First" in names
        assert "Second" in names

    def test_list_sessions_skips_sub_sessions(self, tmp_path, discovery):
        self._create_session(tmp_path, "/home/sam/proj", "main-uuid-1234")
        self._create_session(
            tmp_path, "/home/sam/proj", "main-uuid_sub-agent"
        )  # Sub-session

        sessions = discovery.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].session_id == "main-uuid-1234"

    def test_list_sessions_requires_transcript(self, tmp_path, discovery):
        encoded = "-home-sam-proj"
        d = tmp_path / "projects" / encoded / "sessions" / "no-transcript"
        d.mkdir(parents=True)

        sessions = discovery.list_sessions()
        assert len(sessions) == 0

    def test_list_sessions_project_filter(self, tmp_path, discovery):
        self._create_session(tmp_path, "/home/sam/alpha", "s1")
        self._create_session(tmp_path, "/home/sam/beta", "s2")

        alpha_sessions = discovery.list_sessions(project_filter="alpha")
        assert len(alpha_sessions) == 1
        assert alpha_sessions[0].project == "alpha"

    def test_get_session(self, tmp_path, discovery):
        self._create_session(tmp_path, "/home/sam/proj", "target-uuid", name="Target")

        session = discovery.get_session("target-uuid")
        assert session is not None
        assert session.name == "Target"
        assert session.project == "proj"

    def test_get_session_not_found(self, discovery):
        assert discovery.get_session("nonexistent") is None

    def test_list_projects(self, tmp_path, discovery):
        # NOTE: The encoding replaces ALL hyphens with slashes, so project
        # names must not contain hyphens (they'd decode as path separators).
        self._create_session(tmp_path, "/home/sam/alpha", "s1")
        self._create_session(tmp_path, "/home/sam/alpha", "s2")
        self._create_session(tmp_path, "/home/sam/beta", "s3")

        projects = discovery.list_projects()
        assert len(projects) == 2
        by_name = {p.project_name: p for p in projects}
        assert by_name["alpha"].session_count == 2
        assert by_name["beta"].session_count == 1

    def test_decode_project_path(self):
        from amplifier_distro.server.apps.slack.discovery import AmplifierDiscovery

        assert (
            AmplifierDiscovery._decode_project_path("-home-sam-dev") == "/home/sam/dev"
        )

    def test_extract_project_name(self):
        from amplifier_distro.server.apps.slack.discovery import AmplifierDiscovery

        assert (
            AmplifierDiscovery._extract_project_name("/home/sam/dev/my-project")
            == "my-project"
        )


# --- Backend Tests ---


class TestMockBackend:
    """Test the mock session backend."""

    def test_create_session(self, mock_backend):
        info = asyncio.run(mock_backend.create_session(description="test"))
        assert info.session_id.startswith("mock-session-")
        assert info.is_active

    def test_send_message_echo(self, mock_backend):
        info = asyncio.run(mock_backend.create_session())
        response = asyncio.run(mock_backend.send_message(info.session_id, "hello"))
        assert "hello" in response

    def test_send_message_custom_fn(self, mock_backend):
        mock_backend.set_response_fn(lambda sid, msg: f"Custom: {msg}")
        info = asyncio.run(mock_backend.create_session())
        response = asyncio.run(mock_backend.send_message(info.session_id, "test"))
        assert response == "Custom: test"

    def test_send_message_unknown_session(self, mock_backend):
        with pytest.raises(ValueError, match="Unknown session"):
            asyncio.run(mock_backend.send_message("fake-id", "hello"))

    def test_end_session(self, mock_backend):
        info = asyncio.run(mock_backend.create_session())
        asyncio.run(mock_backend.end_session(info.session_id))
        info2 = asyncio.run(mock_backend.get_session_info(info.session_id))
        assert info2 is not None
        assert not info2.is_active

    def test_list_active_sessions(self, mock_backend):
        asyncio.run(mock_backend.create_session())
        asyncio.run(mock_backend.create_session())
        info3 = asyncio.run(mock_backend.create_session())
        asyncio.run(mock_backend.end_session(info3.session_id))

        active = mock_backend.list_active_sessions()
        assert len(active) == 2

    def test_calls_recorded(self, mock_backend):
        asyncio.run(mock_backend.create_session(description="tracked"))
        assert len(mock_backend.calls) == 1
        assert mock_backend.calls[0]["method"] == "create_session"
        assert mock_backend.calls[0]["description"] == "tracked"


# --- Session Manager Tests ---


class TestSlackSessionManager:
    """Test the Slack-to-Amplifier session routing table."""

    def test_create_session(self, session_manager):
        mapping = asyncio.run(
            session_manager.create_session("C_HUB", "thread.1", "U1", "test session")
        )
        assert mapping.session_id.startswith("mock-session-")
        assert mapping.channel_id == "C_HUB"
        assert mapping.thread_ts == "thread.1"
        assert mapping.description == "test session"

    def test_get_mapping(self, session_manager):
        asyncio.run(session_manager.create_session("C1", "t1", "U1"))

        found = session_manager.get_mapping("C1", "t1")
        assert found is not None

        not_found = session_manager.get_mapping("C1", "t999")
        assert not_found is None

    def test_route_message(self, session_manager):
        from amplifier_distro.server.apps.slack.models import SlackMessage

        asyncio.run(session_manager.create_session("C1", "t1", "U1"))

        msg = SlackMessage(
            channel_id="C1", user_id="U1", text="hello amp", ts="2.0", thread_ts="t1"
        )
        response = asyncio.run(session_manager.route_message(msg))
        assert response is not None
        assert "hello amp" in response  # Mock echoes the message

    def test_route_message_no_mapping(self, session_manager):
        from amplifier_distro.server.apps.slack.models import SlackMessage

        msg = SlackMessage(channel_id="C_UNKNOWN", user_id="U1", text="lost", ts="1.0")
        response = asyncio.run(session_manager.route_message(msg))
        assert response is None

    def test_end_session(self, session_manager):
        from amplifier_distro.server.apps.slack.models import SlackMessage

        asyncio.run(session_manager.create_session("C1", "t1", "U1"))

        ended = asyncio.run(session_manager.end_session("C1", "t1"))
        assert ended is True

        # Routing should now return None (inactive)
        msg = SlackMessage(
            channel_id="C1",
            user_id="U1",
            text="after end",
            ts="3.0",
            thread_ts="t1",
        )
        response = asyncio.run(session_manager.route_message(msg))
        assert response is None

    def test_session_limit(self, session_manager, slack_config):
        slack_config.max_sessions_per_user = 2
        asyncio.run(session_manager.create_session("C1", "t1", "U1"))
        asyncio.run(session_manager.create_session("C1", "t2", "U1"))

        with pytest.raises(ValueError, match="Session limit"):
            asyncio.run(session_manager.create_session("C1", "t3", "U1"))

    def test_breakout_to_channel(self, session_manager):
        asyncio.run(
            session_manager.create_session("C_HUB", "t1", "U1", "breakout test")
        )

        new_ch = asyncio.run(session_manager.breakout_to_channel("C_HUB", "t1"))
        assert new_ch is not None
        assert new_ch.name.startswith("amp-")

        # Old mapping should be gone, new one should exist
        old = session_manager.get_mapping("C_HUB", "t1")
        assert old is None

        new = session_manager.get_mapping(new_ch.id)
        assert new is not None

    def test_list_active(self, session_manager):
        asyncio.run(session_manager.create_session("C1", "t1", "U1"))
        asyncio.run(session_manager.create_session("C1", "t2", "U2"))

        active = session_manager.list_active()
        assert len(active) == 2

    def test_list_user_sessions(self, session_manager):
        asyncio.run(session_manager.create_session("C1", "t1", "U1"))
        asyncio.run(session_manager.create_session("C1", "t2", "U1"))
        asyncio.run(session_manager.create_session("C1", "t3", "U2"))

        u1_sessions = session_manager.list_user_sessions("U1")
        assert len(u1_sessions) == 2
        u2_sessions = session_manager.list_user_sessions("U2")
        assert len(u2_sessions) == 1


# --- Command Handler Tests ---


class TestCommandHandler:
    """Test command parsing and execution."""

    def test_parse_command_with_mention(self, command_handler):
        cmd, args = command_handler.parse_command("<@U_BOT> list", "U_BOT")
        assert cmd == "list"
        assert args == []

    def test_parse_command_with_args(self, command_handler):
        cmd, args = command_handler.parse_command("<@U_BOT> connect abc123", "U_BOT")
        assert cmd == "connect"
        assert args == ["abc123"]

    def test_parse_command_alias(self, command_handler):
        cmd, _ = command_handler.parse_command("<@U_BOT> ls", "U_BOT")
        assert cmd == "list"

        cmd, _ = command_handler.parse_command("<@U_BOT> start", "U_BOT")
        assert cmd == "new"

        cmd, _ = command_handler.parse_command("<@U_BOT> ?", "U_BOT")
        assert cmd == "help"

    def test_parse_empty_command(self, command_handler):
        cmd, args = command_handler.parse_command("<@U_BOT>", "U_BOT")
        assert cmd == "help"

    def test_cmd_help(self, command_handler):
        from amplifier_distro.server.apps.slack.commands import CommandContext

        ctx = CommandContext(channel_id="C1", user_id="U1")
        result = asyncio.run(command_handler.handle("help", [], ctx))
        assert result.blocks is not None
        assert len(result.blocks) >= 1

    def test_cmd_new(self, command_handler):
        from amplifier_distro.server.apps.slack.commands import CommandContext

        ctx = CommandContext(channel_id="C_HUB", user_id="U1", thread_ts=None)
        result = asyncio.run(command_handler.handle("new", ["my", "session"], ctx))
        assert "Started new session" in result.text

    def test_cmd_status_no_session(self, command_handler):
        from amplifier_distro.server.apps.slack.commands import CommandContext

        ctx = CommandContext(channel_id="C1", user_id="U1")
        result = asyncio.run(command_handler.handle("status", [], ctx))
        assert "No active sessions" in result.text

    def test_cmd_end_no_session(self, command_handler):
        from amplifier_distro.server.apps.slack.commands import CommandContext

        ctx = CommandContext(channel_id="C1", user_id="U1")
        result = asyncio.run(command_handler.handle("end", [], ctx))
        assert "No active session" in result.text

    def test_cmd_unknown(self, command_handler):
        from amplifier_distro.server.apps.slack.commands import CommandContext

        ctx = CommandContext(channel_id="C1", user_id="U1")
        result = asyncio.run(command_handler.handle("bogus", [], ctx))
        assert "Unknown command" in result.text

    def test_cmd_discover(self, command_handler):
        from amplifier_distro.server.apps.slack.commands import CommandContext

        ctx = CommandContext(channel_id="C1", user_id="U1")
        result = asyncio.run(command_handler.handle("discover", [], ctx))
        assert "No local sessions" in result.text

    def test_cmd_connect_no_args(self, command_handler):
        from amplifier_distro.server.apps.slack.commands import CommandContext

        ctx = CommandContext(channel_id="C1", user_id="U1")
        result = asyncio.run(command_handler.handle("connect", [], ctx))
        assert "Usage" in result.text


# --- Events Handler Tests ---


class TestSlackEventHandler:
    """Test Slack event handling and dispatch."""

    def _make_handler(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        from amplifier_distro.server.apps.slack.events import SlackEventHandler

        return SlackEventHandler(
            slack_client, session_manager, command_handler, slack_config
        )

    def test_url_verification(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )
        result = asyncio.run(
            handler.handle_event_payload(
                {
                    "type": "url_verification",
                    "challenge": "test_challenge_123",
                }
            )
        )
        assert result["challenge"] == "test_challenge_123"

    def test_message_event_command(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )

        result = asyncio.run(
            handler.handle_event_payload(
                {
                    "type": "event_callback",
                    "event": {
                        "type": "app_mention",
                        "text": "<@U_AMP_BOT> help",
                        "user": "U1",
                        "channel": "C_HUB",
                        "ts": "1.0",
                    },
                }
            )
        )
        assert result == {"ok": True}
        # Should have sent a response message
        assert len(slack_client.sent_messages) >= 1

    def test_ignores_bot_messages(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )

        asyncio.run(
            handler.handle_event_payload(
                {
                    "type": "event_callback",
                    "event": {
                        "type": "message",
                        "bot_id": "B123",
                        "text": "bot loop prevention",
                        "channel": "C1",
                        "ts": "1.0",
                    },
                }
            )
        )
        assert len(slack_client.sent_messages) == 0

    def test_signature_verification_simulator_mode(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )
        # In simulator mode, verification should pass
        assert handler.verify_signature(b"body", "0", "v0=fake") is True

    def test_session_message_routing(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )

        # Create a session first
        asyncio.run(session_manager.create_session("C1", "t1", "U1"))

        # Send a message in that thread (not mentioning bot)
        asyncio.run(
            handler.handle_event_payload(
                {
                    "type": "event_callback",
                    "event": {
                        "type": "message",
                        "text": "what is the meaning of life",
                        "user": "U1",
                        "channel": "C1",
                        "thread_ts": "t1",
                        "ts": "2.0",
                    },
                }
            )
        )
        # Should have sent a response (mock echo)
        assert len(slack_client.sent_messages) >= 1


# --- HTTP Endpoint Tests ---


class TestSlackBridgeEndpoints:
    """Test the FastAPI HTTP endpoints."""

    def test_bridge_status(self, bridge_client):
        resp = bridge_client.get("/apps/slack/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["mode"] == "simulator"

    def test_list_sessions_empty(self, bridge_client):
        resp = bridge_client.get("/apps/slack/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_discover_empty(self, bridge_client):
        resp = bridge_client.get("/apps/slack/discover")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_projects_empty(self, bridge_client):
        resp = bridge_client.get("/apps/slack/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_events_url_verification(self, bridge_client):
        resp = bridge_client.post(
            "/apps/slack/events",
            json={"type": "url_verification", "challenge": "abc"},
        )
        assert resp.status_code == 200
        assert resp.json()["challenge"] == "abc"

    def test_events_message(self, bridge_client):
        resp = bridge_client.post(
            "/apps/slack/events",
            json={
                "type": "event_callback",
                "event": {
                    "type": "app_mention",
                    "text": "<@U_AMP_BOT> help",
                    "user": "U1",
                    "channel": "C1",
                    "ts": "1.0",
                },
            },
        )
        assert resp.status_code == 200

    def test_slash_command(self, bridge_client):
        resp = bridge_client.post(
            "/apps/slack/commands/amp",
            data={
                "text": "help",
                "user_id": "U1",
                "user_name": "testuser",
                "channel_id": "C1",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "blocks" in data or "text" in data


# --- Config File Tests ---


class TestSlackConfigFile:
    """Test SlackConfig loading from keys.yaml + distro.yaml + env.

    Opinion #11: secrets in keys.yaml, config in distro.yaml.
    """

    def test_from_env_only(self):
        """Config loads from env vars when no config files."""
        from amplifier_distro.server.apps.slack.config import SlackConfig

        with patch.dict(
            os.environ,
            {
                "SLACK_BOT_TOKEN": "xoxb-env",
                "SLACK_APP_TOKEN": "xapp-env",
                "SLACK_SOCKET_MODE": "true",
            },
            clear=False,
        ):
            cfg = SlackConfig.from_env()
            assert cfg.bot_token == "xoxb-env"
            assert cfg.app_token == "xapp-env"
            assert cfg.socket_mode is True

    def test_from_files(self, tmp_path):
        """Config loads from keys.yaml + distro.yaml when no env vars."""
        from amplifier_distro.server.apps.slack import config as config_mod

        # Write keys.yaml (secrets)
        keys_file = tmp_path / "keys.yaml"
        keys_file.write_text("SLACK_BOT_TOKEN: xoxb-file\nSLACK_APP_TOKEN: xapp-file\n")

        # Write distro.yaml (config)
        distro_file = tmp_path / "distro.yaml"
        distro_file.write_text(
            "slack:\n"
            "  hub_channel_id: C_FILE\n"
            "  hub_channel_name: test-channel\n"
            "  socket_mode: true\n"
        )

        # Patch the home path to use our temp dir
        original = config_mod._amplifier_home
        config_mod._amplifier_home = lambda: tmp_path
        try:
            # Clear env vars that would override
            env = {
                "SLACK_BOT_TOKEN": "",
                "SLACK_APP_TOKEN": "",
                "SLACK_HUB_CHANNEL_ID": "",
                "SLACK_SOCKET_MODE": "",
                "SLACK_SIGNING_SECRET": "",
                "SLACK_SIMULATOR_MODE": "",
                "SLACK_HUB_CHANNEL_NAME": "",
            }
            with patch.dict(os.environ, env, clear=False):
                cfg = config_mod.SlackConfig.from_env()
                assert cfg.bot_token == "xoxb-file"
                assert cfg.app_token == "xapp-file"
                assert cfg.hub_channel_id == "C_FILE"
                assert cfg.socket_mode is True
        finally:
            config_mod._amplifier_home = original

    def test_env_overrides_file(self, tmp_path):
        """Env vars take priority over keys.yaml values."""
        from amplifier_distro.server.apps.slack import config as config_mod

        # Write keys.yaml with a different token
        keys_file = tmp_path / "keys.yaml"
        keys_file.write_text("SLACK_BOT_TOKEN: xoxb-file\n")

        original = config_mod._amplifier_home
        config_mod._amplifier_home = lambda: tmp_path
        try:
            with patch.dict(
                os.environ,
                {"SLACK_BOT_TOKEN": "xoxb-env"},
                clear=False,
            ):
                cfg = config_mod.SlackConfig.from_env()
                assert cfg.bot_token == "xoxb-env"
        finally:
            config_mod._amplifier_home = original


# --- Setup Module Tests ---


class TestSlackSetup:
    """Test the Slack bridge setup/install module.

    Opinion #11: secrets in keys.yaml, config in distro.yaml.
    """

    def test_setup_status_unconfigured(self, bridge_client):
        """Setup status shows unconfigured when no tokens."""
        resp = bridge_client.get("/apps/slack/setup/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "steps" in data
        assert "configured" in data
        assert isinstance(data["config_path"], str)
        assert isinstance(data["keys_path"], str)

    def test_setup_manifest(self, bridge_client):
        """Manifest endpoint returns valid app manifest."""
        resp = bridge_client.get("/apps/slack/setup/manifest")
        assert resp.status_code == 200
        data = resp.json()
        assert "manifest" in data
        assert "manifest_yaml" in data
        assert "instructions" in data
        assert "create_url" in data

        # Verify manifest structure
        m = data["manifest"]
        assert m["features"]["bot_user"]["always_online"] is True
        assert "app_mentions:read" in m["oauth_config"]["scopes"]["bot"]
        assert m["settings"]["socket_mode_enabled"] is True

    def test_validate_bad_prefix(self, bridge_client):
        """Validate rejects tokens with wrong prefix."""
        resp = bridge_client.post(
            "/apps/slack/setup/validate",
            json={"bot_token": "not-a-valid-token"},
        )
        assert resp.status_code == 400

    def test_configure_saves_to_keys_and_distro(self, bridge_client, tmp_path):
        """Configure persists secrets to keys.yaml, config to distro.yaml."""
        from amplifier_distro.server.apps.slack import setup

        # Redirect home path to temp dir
        original = setup._amplifier_home
        setup._amplifier_home = lambda: tmp_path
        try:
            resp = bridge_client.post(
                "/apps/slack/setup/configure",
                json={
                    "bot_token": "xoxb-test-token",
                    "app_token": "xapp-test-token",
                    "hub_channel_id": "C_TEST",
                    "hub_channel_name": "test-channel",
                    "socket_mode": True,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "saved"
            assert data["mode"] == "socket"

            import yaml

            # Verify secrets in keys.yaml
            keys = yaml.safe_load((tmp_path / "keys.yaml").read_text())
            assert keys["SLACK_BOT_TOKEN"] == "xoxb-test-token"
            assert keys["SLACK_APP_TOKEN"] == "xapp-test-token"

            # Verify config in distro.yaml
            distro = yaml.safe_load((tmp_path / "distro.yaml").read_text())
            assert distro["slack"]["hub_channel_id"] == "C_TEST"
            assert distro["slack"]["hub_channel_name"] == "test-channel"
            assert distro["slack"]["socket_mode"] is True
        finally:
            setup._amplifier_home = original

    def test_channels_no_token(self, bridge_client):
        """Channels endpoint requires a bot token."""
        with patch.dict(os.environ, {"SLACK_BOT_TOKEN": ""}, clear=False):
            resp = bridge_client.get("/apps/slack/setup/channels")
            assert resp.status_code == 400

    def test_test_no_token(self, bridge_client):
        """Test endpoint requires a bot token."""
        from amplifier_distro.server.apps.slack import setup

        # Ensure no keys file returns empty
        original = setup._amplifier_home
        setup._amplifier_home = lambda: Path("/tmp/nonexistent-slack-test")
        try:
            with patch.dict(os.environ, {"SLACK_BOT_TOKEN": ""}, clear=False):
                resp = bridge_client.post(
                    "/apps/slack/setup/test",
                    json={},
                )
                assert resp.status_code == 400
        finally:
            setup._amplifier_home = original


# --- Setup Config Persistence Tests ---


class TestSlackSetupHelpers:
    """Test setup module helper functions (keys.yaml + distro.yaml)."""

    def test_save_and_load_keys(self, tmp_path):
        """Round-trip: save keys then load them back."""
        from amplifier_distro.server.apps.slack import setup

        original = setup._amplifier_home
        setup._amplifier_home = lambda: tmp_path
        try:
            setup._save_keys(
                {
                    "SLACK_BOT_TOKEN": "xoxb-round-trip",
                    "SLACK_APP_TOKEN": "xapp-round-trip",
                }
            )
            loaded = setup.load_keys()
            assert loaded["SLACK_BOT_TOKEN"] == "xoxb-round-trip"
            assert loaded["SLACK_APP_TOKEN"] == "xapp-round-trip"
        finally:
            setup._amplifier_home = original

    def test_save_and_load_distro_slack(self, tmp_path):
        """Round-trip: save slack config to distro.yaml then load it back."""
        from amplifier_distro.server.apps.slack import setup

        original = setup._amplifier_home
        setup._amplifier_home = lambda: tmp_path
        try:
            setup._save_distro_slack(
                {
                    "hub_channel_id": "C_RT",
                    "hub_channel_name": "test",
                    "socket_mode": True,
                }
            )
            loaded = setup.load_distro_slack()
            assert loaded["hub_channel_id"] == "C_RT"
            assert loaded["hub_channel_name"] == "test"
            assert loaded["socket_mode"] is True
        finally:
            setup._amplifier_home = original

    def test_distro_slack_preserves_other_sections(self, tmp_path):
        """Writing slack: section preserves other distro.yaml sections."""
        import yaml

        from amplifier_distro.server.apps.slack import setup

        original = setup._amplifier_home
        setup._amplifier_home = lambda: tmp_path

        # Pre-populate distro.yaml with existing content
        distro_path = tmp_path / "distro.yaml"
        distro_path.write_text(
            yaml.dump(
                {"workspace_root": "~/dev", "identity": {"github_handle": "test"}},
                default_flow_style=False,
            )
        )

        try:
            setup._save_distro_slack({"hub_channel_id": "C_NEW"})
            loaded = yaml.safe_load(distro_path.read_text())
            # Existing sections preserved
            assert loaded["workspace_root"] == "~/dev"
            assert loaded["identity"]["github_handle"] == "test"
            # New section added
            assert loaded["slack"]["hub_channel_id"] == "C_NEW"
        finally:
            setup._amplifier_home = original

    def test_load_missing_config(self, tmp_path):
        """Loading from non-existent paths returns empty dict."""
        from amplifier_distro.server.apps.slack import setup

        original = setup._amplifier_home
        setup._amplifier_home = lambda: tmp_path / "nonexistent"
        try:
            assert setup.load_keys() == {}
            assert setup.load_distro_slack() == {}
        finally:
            setup._amplifier_home = original

    def test_keys_file_permissions(self, tmp_path):
        """keys.yaml is written with chmod 600 (owner-only)."""
        from amplifier_distro.server.apps.slack import setup

        original = setup._amplifier_home
        setup._amplifier_home = lambda: tmp_path
        try:
            setup._save_keys({"SLACK_BOT_TOKEN": "xoxb-perms"})
            path = tmp_path / "keys.yaml"
            assert path.exists()
            mode = oct(path.stat().st_mode & 0o777)
            assert mode == "0o600"
        finally:
            setup._amplifier_home = original


# --- Event Deduplication Tests ---


class TestSocketModeDedup:
    """Test event deduplication in SocketModeAdapter."""

    def test_dedup_prevents_double_processing(self):
        """Same channel:ts should be deduplicated."""
        from amplifier_distro.server.apps.slack.socket_mode import (
            SocketModeAdapter,
        )

        adapter = SocketModeAdapter.__new__(SocketModeAdapter)
        adapter._seen_events = {}

        assert adapter._is_duplicate("C1:1.0") is False
        assert adapter._is_duplicate("C1:1.0") is True

    def test_dedup_different_messages_pass(self):
        """Different channel:ts pairs are not duplicates."""
        from amplifier_distro.server.apps.slack.socket_mode import (
            SocketModeAdapter,
        )

        adapter = SocketModeAdapter.__new__(SocketModeAdapter)
        adapter._seen_events = {}

        assert adapter._is_duplicate("C1:1.0") is False
        assert adapter._is_duplicate("C1:2.0") is False
        assert adapter._is_duplicate("C2:1.0") is False


# --- Command Routing Fix Tests ---


class TestCommandRoutingFix:
    """Test that command routing works for all mention formats.

    The bug: Slack sends mentions as <@U123> or <@U123|displayname>.
    The old regex only matched <@U123>, so <@U123|name> commands
    were not stripped, causing all commands to appear "unknown".
    """

    def test_parse_command_with_display_name_mention(self, command_handler):
        """<@U_BOT|amp> list should parse correctly."""
        cmd, args = command_handler.parse_command("<@U_BOT|amp> list", "U_BOT")
        assert cmd == "list"
        assert args == []

    def test_parse_command_with_display_name_and_args(self, command_handler):
        """<@U_BOT|SlackBridge> connect abc123 should parse correctly."""
        cmd, args = command_handler.parse_command(
            "<@U_BOT|SlackBridge> connect abc123", "U_BOT"
        )
        assert cmd == "connect"
        assert args == ["abc123"]

    def test_parse_command_display_name_only(self, command_handler):
        """Just mentioning <@U_BOT|amp> with no command should default to help."""
        cmd, args = command_handler.parse_command("<@U_BOT|amp>", "U_BOT")
        assert cmd == "help"
        assert args == []

    def test_parse_command_standard_mention(self, command_handler):
        """Standard <@U_BOT> still works (regression guard)."""
        cmd, args = command_handler.parse_command("<@U_BOT> status", "U_BOT")
        assert cmd == "status"
        assert args == []

    def test_disconnect_alias(self, command_handler):
        """disconnect should alias to end."""
        cmd, _ = command_handler.parse_command("<@U_BOT> disconnect", "U_BOT")
        assert cmd == "end"


# --- Integration Tests: Full Event Pipeline ---


class TestEventPipelineIntegration:
    """Integration tests routing each command through the full event pipeline.

    Each test sends a Slack event payload through handle_event_payload()
    and verifies the bridge responds correctly.
    """

    def _make_handler(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        from amplifier_distro.server.apps.slack.events import SlackEventHandler

        return SlackEventHandler(
            slack_client, session_manager, command_handler, slack_config
        )

    def _app_mention_payload(self, text, channel="C_HUB", user="U1", ts="1.0"):
        """Build an app_mention event payload."""
        return {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "text": text,
                "user": user,
                "channel": channel,
                "ts": ts,
            },
        }

    def test_help_via_event(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )
        asyncio.run(
            handler.handle_event_payload(self._app_mention_payload("<@U_AMP_BOT> help"))
        )
        assert len(slack_client.sent_messages) >= 1
        # Help response uses blocks
        sent = slack_client.sent_messages[0]
        assert sent.channel == "C_HUB"

    def test_list_via_event(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )
        asyncio.run(
            handler.handle_event_payload(self._app_mention_payload("<@U_AMP_BOT> list"))
        )
        assert len(slack_client.sent_messages) >= 1

    def test_new_via_event(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )
        asyncio.run(
            handler.handle_event_payload(
                self._app_mention_payload("<@U_AMP_BOT> new my test session")
            )
        )
        assert len(slack_client.sent_messages) >= 1
        text = slack_client.sent_messages[0].text
        assert "Started" in text or "session" in text.lower()

    def test_status_via_event(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )
        asyncio.run(
            handler.handle_event_payload(
                self._app_mention_payload("<@U_AMP_BOT> status")
            )
        )
        assert len(slack_client.sent_messages) >= 1

    def test_discover_via_event(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )
        asyncio.run(
            handler.handle_event_payload(
                self._app_mention_payload("<@U_AMP_BOT> discover")
            )
        )
        assert len(slack_client.sent_messages) >= 1

    def test_sessions_via_event(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )
        asyncio.run(
            handler.handle_event_payload(
                self._app_mention_payload("<@U_AMP_BOT> sessions")
            )
        )
        assert len(slack_client.sent_messages) >= 1

    def test_config_via_event(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )
        asyncio.run(
            handler.handle_event_payload(
                self._app_mention_payload("<@U_AMP_BOT> config")
            )
        )
        assert len(slack_client.sent_messages) >= 1
        text = slack_client.sent_messages[0].text
        assert "Configuration" in text

    def test_connect_via_event(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )
        asyncio.run(
            handler.handle_event_payload(
                self._app_mention_payload("<@U_AMP_BOT> connect abc123")
            )
        )
        assert len(slack_client.sent_messages) >= 1

    def test_disconnect_via_event(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )
        asyncio.run(
            handler.handle_event_payload(
                self._app_mention_payload("<@U_AMP_BOT> disconnect")
            )
        )
        assert len(slack_client.sent_messages) >= 1
        text = slack_client.sent_messages[0].text
        assert "No active session" in text

    def test_display_name_mention_routes_correctly(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        """Slack mentions with |displayname should route to the right command."""
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )
        asyncio.run(
            handler.handle_event_payload(
                self._app_mention_payload("<@U_AMP_BOT|amp> list")
            )
        )
        assert len(slack_client.sent_messages) >= 1


# --- Edge Case Tests ---


class TestCommandEdgeCases:
    """Test edge cases in command parsing and handling."""

    def test_empty_message_text(self, command_handler):
        """Empty text should parse to help."""
        cmd, args = command_handler.parse_command("", "U_BOT")
        assert cmd == "help"
        assert args == []

    def test_whitespace_only_message(self, command_handler):
        """Whitespace-only text should parse to help."""
        cmd, args = command_handler.parse_command("   ", "U_BOT")
        assert cmd == "help"
        assert args == []

    def test_unknown_command_response(self, command_handler):
        from amplifier_distro.server.apps.slack.commands import CommandContext

        ctx = CommandContext(channel_id="C1", user_id="U1")
        result = asyncio.run(command_handler.handle("xyzzy", [], ctx))
        assert "Unknown command" in result.text
        assert "help" in result.text.lower()

    def test_malformed_mention_treated_as_text(self, command_handler):
        """Partial mentions like <@U_BOT should not crash."""
        cmd, args = command_handler.parse_command("<@U_BOT list", "U_BOT")
        # The regex won't match a malformed mention, so it becomes the first word
        assert cmd is not None  # Should not crash

    def test_mention_with_extra_spaces(self, command_handler):
        """Extra spaces between mention and command should work."""
        cmd, args = command_handler.parse_command("<@U_BOT>   list  ", "U_BOT")
        assert cmd == "list"
        assert args == []

    def test_cmd_sessions_empty(self, command_handler):
        """Sessions command with no active sessions."""
        from amplifier_distro.server.apps.slack.commands import CommandContext

        ctx = CommandContext(channel_id="C1", user_id="U1")
        result = asyncio.run(command_handler.handle("sessions", [], ctx))
        assert "No active" in result.text

    def test_cmd_config_shows_bot_name(self, command_handler):
        """Config command includes bot name."""
        from amplifier_distro.server.apps.slack.commands import CommandContext

        ctx = CommandContext(channel_id="C1", user_id="U1")
        result = asyncio.run(command_handler.handle("config", [], ctx))
        assert "amp" in result.text  # bot_name from slack_config fixture


# --- Session Persistence Tests ---


class TestSessionPersistence:
    """Test session persistence to JSON file."""

    def test_save_and_load_round_trip(
        self, slack_client, mock_backend, slack_config, tmp_path
    ):
        """Sessions saved to disk are loaded back on new manager creation."""
        from amplifier_distro.server.apps.slack.sessions import SlackSessionManager

        persist_path = tmp_path / "slack-sessions.json"

        # Create manager with persistence, add a session
        mgr1 = SlackSessionManager(
            slack_client, mock_backend, slack_config, persistence_path=persist_path
        )
        asyncio.run(mgr1.create_session("C1", "t1", "U1", "persisted session"))

        # Verify file was written
        assert persist_path.exists()
        data = json.loads(persist_path.read_text())
        assert len(data) == 1
        assert data[0]["channel_id"] == "C1"
        assert data[0]["thread_ts"] == "t1"
        assert data[0]["description"] == "persisted session"

        # Create a NEW manager pointing at same file - should load the session
        mgr2 = SlackSessionManager(
            slack_client, mock_backend, slack_config, persistence_path=persist_path
        )
        loaded = mgr2.get_mapping("C1", "t1")
        assert loaded is not None
        assert loaded.description == "persisted session"
        assert loaded.channel_id == "C1"
        assert loaded.is_active is True

    def test_persistence_survives_end_session(
        self, slack_client, mock_backend, slack_config, tmp_path
    ):
        """Ending a session is persisted (is_active=False)."""
        from amplifier_distro.server.apps.slack.sessions import SlackSessionManager

        persist_path = tmp_path / "slack-sessions.json"
        mgr = SlackSessionManager(
            slack_client, mock_backend, slack_config, persistence_path=persist_path
        )
        asyncio.run(mgr.create_session("C1", "t1", "U1"))
        asyncio.run(mgr.end_session("C1", "t1"))

        # Reload and verify
        mgr2 = SlackSessionManager(
            slack_client, mock_backend, slack_config, persistence_path=persist_path
        )
        loaded = mgr2.get_mapping("C1", "t1")
        assert loaded is not None
        assert loaded.is_active is False

    def test_persistence_no_file_on_startup(
        self, slack_client, mock_backend, slack_config, tmp_path
    ):
        """Manager starts cleanly when no persistence file exists."""
        from amplifier_distro.server.apps.slack.sessions import SlackSessionManager

        persist_path = tmp_path / "nonexistent" / "slack-sessions.json"
        mgr = SlackSessionManager(
            slack_client, mock_backend, slack_config, persistence_path=persist_path
        )
        assert mgr.list_active() == []

    def test_persistence_disabled_when_none(
        self, slack_client, mock_backend, slack_config, tmp_path
    ):
        """When persistence_path is None, no file operations occur."""
        from amplifier_distro.server.apps.slack.sessions import SlackSessionManager

        mgr = SlackSessionManager(
            slack_client, mock_backend, slack_config, persistence_path=None
        )
        asyncio.run(mgr.create_session("C1", "t1", "U1"))
        # No file should be created anywhere in tmp_path
        assert list(tmp_path.iterdir()) == []

    def test_persistence_includes_all_fields(
        self, slack_client, mock_backend, slack_config, tmp_path
    ):
        """Persisted JSON includes all required session fields."""
        from amplifier_distro.server.apps.slack.sessions import SlackSessionManager

        persist_path = tmp_path / "slack-sessions.json"
        mgr = SlackSessionManager(
            slack_client, mock_backend, slack_config, persistence_path=persist_path
        )
        asyncio.run(mgr.create_session("C1", "t1", "U1", "full fields test"))

        data = json.loads(persist_path.read_text())
        record = data[0]
        required_fields = {
            "session_id",
            "channel_id",
            "thread_ts",
            "created_at",
            "last_active",
        }
        for field in required_fields:
            assert field in record, f"Missing field: {field}"

    def test_persistence_handles_corrupt_file(
        self, slack_client, mock_backend, slack_config, tmp_path
    ):
        """Manager handles corrupt persistence file gracefully."""
        from amplifier_distro.server.apps.slack.sessions import SlackSessionManager

        persist_path = tmp_path / "slack-sessions.json"
        persist_path.write_text("NOT VALID JSON {{{{")

        # Should not raise, just log a warning and start empty
        mgr = SlackSessionManager(
            slack_client, mock_backend, slack_config, persistence_path=persist_path
        )
        assert mgr.list_active() == []

    def test_default_persistence_path_uses_conventions(self):
        """The default persistence path is built from conventions constants."""
        from amplifier_distro.conventions import (
            AMPLIFIER_HOME,
            SERVER_DIR,
            SLACK_SESSIONS_FILENAME,
        )
        from amplifier_distro.server.apps.slack.sessions import (
            _default_persistence_path,
        )

        path = _default_persistence_path()
        assert (
            path
            == Path(AMPLIFIER_HOME).expanduser() / SERVER_DIR / SLACK_SESSIONS_FILENAME
        )
