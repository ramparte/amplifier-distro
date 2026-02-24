"""Tests for the rebuilt BridgeApprovalSystem."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_distro.bridge_protocols import BridgeApprovalSystem


class TestBridgeApprovalSystemAutoApprove:
    @pytest.mark.asyncio
    async def test_auto_approve_returns_first_option(self):
        approval = BridgeApprovalSystem(auto_approve=True)
        result = await approval.request_approval("Allow?", ["allow", "deny"])
        assert result == "allow"

    @pytest.mark.asyncio
    async def test_auto_approve_empty_options_returns_allow(self):
        approval = BridgeApprovalSystem(auto_approve=True)
        result = await approval.request_approval("Allow?", [])
        assert result == "allow"


class TestBridgeApprovalSystemInteractive:
    @pytest.mark.asyncio
    async def test_request_blocks_until_handle_response(self):
        """request_approval blocks until handle_response is called."""
        approval = BridgeApprovalSystem(auto_approve=False)

        async def responder():
            await asyncio.sleep(0.01)  # Let request_approval start
            for req_id in list(approval._pending.keys()):
                approval.handle_response(req_id, "allow")

        result, _ = await asyncio.gather(
            approval.request_approval("Allow tool?", ["allow", "deny"]),
            responder(),
        )
        assert result == "allow"

    @pytest.mark.asyncio
    async def test_handle_response_returns_true_for_valid_id(self):
        approval = BridgeApprovalSystem(auto_approve=False)

        async def background():
            await asyncio.sleep(0.01)
            req_id = next(iter(approval._pending.keys()))
            return approval.handle_response(req_id, "deny")

        _, ok = await asyncio.gather(
            approval.request_approval("?", ["allow", "deny"], timeout=1.0),
            background(),
        )
        assert ok is True

    @pytest.mark.asyncio
    async def test_handle_response_returns_false_for_unknown_id(self):
        approval = BridgeApprovalSystem(auto_approve=False)
        result = approval.handle_response("no-such-id", "allow")
        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_returns_default(self):
        approval = BridgeApprovalSystem(auto_approve=False)
        result = await approval.request_approval(
            "Allow?", ["allow", "deny"], timeout=0.05, default="deny"
        )
        assert result == "deny"

    @pytest.mark.asyncio
    async def test_on_approval_request_callback_called(self):
        """on_approval_request callback fires with request details."""
        callback = AsyncMock()
        approval = BridgeApprovalSystem(
            auto_approve=False,
            on_approval_request=callback,
        )

        async def background():
            await asyncio.sleep(0.01)
            for req_id in list(approval._pending.keys()):
                approval.handle_response(req_id, "allow")

        await asyncio.gather(
            approval.request_approval("Allow?", ["allow", "deny"]),
            background(),
        )

        callback.assert_awaited_once()
        call_kwargs = callback.call_args
        # callback receives (request_id, prompt, options, timeout, default)
        assert "allow" in call_kwargs.args[2]


class TestBridgeBackendResolveApproval:
    def test_resolve_approval_delegates_to_session_approval(self):
        from amplifier_distro.server.session_backend import BridgeBackend

        mock_approval = MagicMock()
        mock_approval.handle_response = MagicMock(return_value=True)

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {"s001": MagicMock()}
        backend._approval_systems = {"s001": mock_approval}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()

        result = backend.resolve_approval("s001", "req-001", "allow")
        assert result is True
        mock_approval.handle_response.assert_called_once_with("req-001", "allow")

    def test_resolve_approval_unknown_session_returns_false(self):
        from amplifier_distro.server.session_backend import BridgeBackend

        backend = BridgeBackend.__new__(BridgeBackend)
        backend._sessions = {}
        backend._approval_systems = {}
        backend._reconnect_locks = {}
        backend._session_queues = {}
        backend._worker_tasks = {}
        backend._ended_sessions = set()

        result = backend.resolve_approval("no-session", "req-001", "allow")
        assert result is False
