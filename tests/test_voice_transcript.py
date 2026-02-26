"""Tests for voice transcript models: VoiceConversation, TranscriptEntry, DisconnectEvent."""

from __future__ import annotations

from datetime import datetime, timezone


class TestVoiceConversation:
    """Tests for VoiceConversation dataclass."""

    def _make_conversation(self, **kwargs):
        from amplifier_distro.server.apps.voice.transcript.models import VoiceConversation

        defaults = {
            "id": "session-abc-123",
            "title": "Test Conversation",
            "status": "active",
            "created_at": datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            "updated_at": datetime(2024, 1, 15, 10, 5, 0, tzinfo=timezone.utc),
        }
        defaults.update(kwargs)
        return VoiceConversation(**defaults)

    def test_round_trip_to_dict_from_dict(self) -> None:
        """VoiceConversation survives to_dict/from_dict round-trip."""
        from amplifier_distro.server.apps.voice.transcript.models import VoiceConversation

        conv = self._make_conversation(
            ended_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            end_reason="user_ended",
            duration_seconds=1800.5,
            first_message="Hello",
            last_message="Goodbye",
            tool_call_count=3,
            reconnect_count=1,
        )
        d = conv.to_dict()
        restored = VoiceConversation.from_dict(d)

        assert restored.id == conv.id
        assert restored.title == conv.title
        assert restored.status == conv.status
        assert restored.ended_at == conv.ended_at
        assert restored.end_reason == conv.end_reason
        assert restored.duration_seconds == conv.duration_seconds
        assert restored.first_message == conv.first_message
        assert restored.last_message == conv.last_message
        assert restored.tool_call_count == conv.tool_call_count
        assert restored.reconnect_count == conv.reconnect_count

    def test_omits_none_values_in_to_dict(self) -> None:
        """to_dict() omits keys with None values (ended_at, end_reason, duration_seconds)."""
        conv = self._make_conversation()  # no ended_at, end_reason, duration_seconds

        d = conv.to_dict()

        assert "ended_at" not in d
        assert "end_reason" not in d
        assert "duration_seconds" not in d
        # Non-None fields should still be present
        assert "id" in d
        assert "title" in d
        assert "status" in d

    def test_from_dict_ignores_unknown_keys(self) -> None:
        """from_dict() silently ignores unknown keys."""
        from amplifier_distro.server.apps.voice.transcript.models import VoiceConversation

        data = {
            "id": "session-xyz",
            "title": "Test",
            "status": "active",
            "created_at": "2024-01-15T10:00:00+00:00",
            "updated_at": "2024-01-15T10:05:00+00:00",
            "unknown_field": "should be ignored",
            "another_unknown": 42,
        }
        # Should not raise
        conv = VoiceConversation.from_dict(data)
        assert conv.id == "session-xyz"
        assert conv.title == "Test"

    def test_end_reason_valid_values(self) -> None:
        """end_reason accepts all valid values."""
        valid_reasons = [
            "session_limit",
            "network_error",
            "user_ended",
            "idle_timeout",
            "error",
        ]
        for reason in valid_reasons:
            conv = self._make_conversation(end_reason=reason)
            assert conv.end_reason == reason


class TestTranscriptEntry:
    """Tests for TranscriptEntry dataclass."""

    def _make_entry(self, **kwargs):
        from amplifier_distro.server.apps.voice.transcript.models import TranscriptEntry

        defaults = {
            "id": "entry-001",
            "conversation_id": "session-abc-123",
            "role": "user",
            "content": "Hello, how are you?",
            "created_at": datetime(2024, 1, 15, 10, 1, 0, tzinfo=timezone.utc),
        }
        defaults.update(kwargs)
        return TranscriptEntry(**defaults)

    def test_round_trip_to_dict_from_dict(self) -> None:
        """TranscriptEntry survives to_dict/from_dict round-trip."""
        from amplifier_distro.server.apps.voice.transcript.models import TranscriptEntry

        entry = self._make_entry(
            role="assistant",
            content="I am doing well, thank you!",
            audio_duration_ms=3500,
            item_id="item-abc",
        )
        d = entry.to_dict()
        restored = TranscriptEntry.from_dict(d)

        assert restored.id == entry.id
        assert restored.conversation_id == entry.conversation_id
        assert restored.role == entry.role
        assert restored.content == entry.content
        assert restored.audio_duration_ms == entry.audio_duration_ms
        assert restored.item_id == entry.item_id
        assert restored.created_at == entry.created_at

    def test_from_dict_ignores_unknown_keys(self) -> None:
        """from_dict() silently ignores unknown keys."""
        from amplifier_distro.server.apps.voice.transcript.models import TranscriptEntry

        data = {
            "id": "entry-002",
            "conversation_id": "session-xyz",
            "role": "user",
            "content": "Hi there",
            "created_at": "2024-01-15T10:01:00+00:00",
            "totally_unknown": "ignore me",
            "future_field": {"nested": True},
        }
        entry = TranscriptEntry.from_dict(data)
        assert entry.id == "entry-002"
        assert entry.content == "Hi there"

    def test_tool_call_entry_has_call_id_and_tool_name(self) -> None:
        """tool_call role entry stores call_id and tool_name."""
        entry = self._make_entry(
            role="tool_call",
            content='{"action": "search"}',
            call_id="call-xyz-789",
            tool_name="web_search",
        )
        d = entry.to_dict()

        assert d["role"] == "tool_call"
        assert d["call_id"] == "call-xyz-789"
        assert d["tool_name"] == "web_search"

        # Verify round-trip preserves these
        from amplifier_distro.server.apps.voice.transcript.models import TranscriptEntry

        restored = TranscriptEntry.from_dict(d)
        assert restored.call_id == "call-xyz-789"
        assert restored.tool_name == "web_search"


class TestNewEntryId:
    """Tests for new_entry_id() helper function."""

    def test_returns_string(self) -> None:
        from amplifier_distro.server.apps.voice.transcript.models import new_entry_id

        result = new_entry_id()
        assert isinstance(result, str)

    def test_returns_unique_values(self) -> None:
        from amplifier_distro.server.apps.voice.transcript.models import new_entry_id

        ids = {new_entry_id() for _ in range(10)}
        assert len(ids) == 10


class TestDisconnectEvent:
    """Tests for DisconnectEvent dataclass."""

    def test_round_trip_to_dict_from_dict(self) -> None:
        from amplifier_distro.server.apps.voice.transcript.models import DisconnectEvent

        event = DisconnectEvent(timestamp="2024-01-15T10:10:00Z", reason="network_error", reconnected=True)
        d = event.to_dict()
        restored = DisconnectEvent.from_dict(d)

        assert restored.timestamp == event.timestamp
        assert restored.reason == event.reason
        assert restored.reconnected == event.reconnected

    def test_default_reconnected_is_false(self) -> None:
        from amplifier_distro.server.apps.voice.transcript.models import DisconnectEvent

        event = DisconnectEvent(timestamp="2024-01-15T10:10:00Z", reason="idle_timeout")
        assert event.reconnected is False
