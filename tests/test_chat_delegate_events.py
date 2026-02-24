"""Tests that delegate:* events are registered on the streaming hook."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

DELEGATE_EVENTS = [
    "delegate:agent_spawned",
    "delegate:agent_resumed",
    "delegate:agent_completed",
    "delegate:error",
]


class TestDelegateEventRegistration:
    @pytest.mark.asyncio
    async def test_delegate_events_registered_on_create_session(self):
        """After create_session, all delegate:* events are registered on the hook."""
        from amplifier_distro.bridge import BridgeConfig, LocalBridge

        registered_events: list[str] = []

        mock_hooks = MagicMock()
        mock_hooks.register = MagicMock(
            side_effect=lambda event, handler, priority, name: registered_events.append(
                event
            )
        )

        mock_coordinator = MagicMock()
        mock_coordinator.hooks = mock_hooks
        mock_coordinator.session_id = "delegate-test"

        mock_session = MagicMock()
        mock_session.coordinator = mock_coordinator

        mock_prepared = MagicMock()
        mock_prepared.create_session = AsyncMock(return_value=mock_session)
        mock_prepared.mount_plan = {}

        mock_bundle = MagicMock()
        mock_bundle.prepare = AsyncMock(return_value=mock_prepared)

        bridge = LocalBridge.__new__(LocalBridge)
        bridge._config = {}

        with (
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(AsyncMock(return_value=mock_bundle), MagicMock()),
            ),
            patch(
                "amplifier_distro.bridge.LocalBridge._resolve_distro_bundle",
                return_value="test-bundle",
            ),
            patch(
                "amplifier_distro.bridge.LocalBridge.get_project_id",
                return_value="test-project",
            ),
            patch(
                "amplifier_distro.bridge.LocalBridge.get_handoff",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("amplifier_distro.bridge.LocalBridge._inject_providers"),
            patch("amplifier_distro.bridge._write_session_info"),
            patch("amplifier_distro.transcript_persistence.register_transcript_hooks"),
            patch("amplifier_core.events.ALL_EVENTS", ["content_block:start"]),
        ):
            config = BridgeConfig(working_dir=__import__("pathlib").Path("/tmp"))
            await bridge.create_session(config)

        for event in DELEGATE_EVENTS:
            assert event in registered_events, (
                f"delegate event '{event}' not registered. "
                f"Registered: {[e for e in registered_events if 'delegate' in e]}"
            )

    @pytest.mark.asyncio
    async def test_delegate_events_registered_on_resume_session(self, tmp_path):
        """After resume_session, all delegate:* events are registered on the hook."""
        from amplifier_distro.bridge import BridgeConfig, LocalBridge

        session_id = "test-resume-session"
        # Create the directory structure that resume_session() discovers
        session_dir = tmp_path / "projects" / "test-project" / "sessions" / session_id
        session_dir.mkdir(parents=True)

        registered_events: list[str] = []

        mock_hooks = MagicMock()
        mock_hooks.register = MagicMock(
            side_effect=lambda event, handler, priority, name: registered_events.append(
                event
            )
        )

        mock_coordinator = MagicMock()
        mock_coordinator.hooks = mock_hooks
        mock_coordinator.session_id = session_id

        mock_session = MagicMock()
        mock_session.coordinator = mock_coordinator

        mock_prepared = MagicMock()
        mock_prepared.create_session = AsyncMock(return_value=mock_session)
        mock_prepared.mount_plan = {}

        mock_bundle = MagicMock()
        mock_bundle.prepare = AsyncMock(return_value=mock_prepared)

        bridge = LocalBridge.__new__(LocalBridge)
        bridge._config = {}

        with (
            patch("amplifier_distro.bridge.AMPLIFIER_HOME", str(tmp_path)),
            patch(
                "amplifier_distro.bridge._read_session_info_working_dir",
                return_value=None,
            ),
            patch("amplifier_distro.bridge._write_session_info"),
            patch(
                "amplifier_distro.bridge._require_foundation",
                return_value=(AsyncMock(return_value=mock_bundle), MagicMock()),
            ),
            patch(
                "amplifier_distro.bridge.LocalBridge._resolve_distro_bundle",
                return_value="test-bundle",
            ),
            patch("amplifier_distro.bridge.LocalBridge._inject_providers"),
            patch("amplifier_distro.transcript_persistence.register_transcript_hooks"),
            patch("amplifier_core.events.ALL_EVENTS", ["content_block:start"]),
        ):
            config = BridgeConfig(working_dir=__import__("pathlib").Path("/tmp"))
            await bridge.resume_session(session_id, config)

        for event in DELEGATE_EVENTS:
            assert event in registered_events, (
                f"delegate event '{event}' not registered. "
                f"Registered: {[e for e in registered_events if 'delegate' in e]}"
            )
