# Voice App Full Overhaul — Implementation Plan

> **For execution:** Use `/execute-plan` mode or the subagent-driven-development recipe.

**Goal:** Replace the current thin WebRTC broker at `server/apps/voice/__init__.py` with a full-capability voice assistant app: GA OpenAI Realtime API, semantic VAD, working tool calling via Amplifier, session persistence and resumption, connection health monitoring, two-level cancellation, and a Preact frontend.

**Architecture:** Multi-file Python module registered as an `AppManifest`, using the shared `FoundationBackend` via `get_services()`. The Amplifier session ID is the primary key everywhere — no parallel session world. `amplifier-voice` (at `../amplifier-voice`) is the capability reference; `feat/chat-app` is the structural reference.

**Tech Stack:** Python 3.11+, FastAPI, httpx, pytest, Preact 10 + HTM (no build step)

---

## ⚠️ PREREQUISITE: feat/chat-app Merge

**Phases 1 and 2 can start TODAY** on `lean-experience-server` as-is. They have zero FastAPI or session backend dependencies.

**Phases 3 and 4 require `feat/chat-app` to be merged into `lean-experience-server`.** Before starting Phase 3, verify these methods exist on `services.backend`:

```python
# Run this check in a Python REPL to verify the merge landed:
from amplifier_distro.server.session_backend import MockBackend
b = MockBackend()
assert hasattr(b, "mark_disconnected"), "feat/chat-app not merged yet"
assert hasattr(b, "reconnect"), "feat/chat-app not merged yet"
assert hasattr(b, "cancel_session"), "feat/chat-app not merged yet"
# create_session must accept event_queue and app_name kwargs
```

If those methods are missing, stop and wait for the merge. Do not improvise substitutes.

---

## Before You Start

**DO NOT skip tests.** Every task is TDD: write the failing test first, then the minimal implementation, then verify it passes. Skipping this order will create unmaintainable code and cause Phase 4 integration failures.

**Always use `uv run python -m pytest`**, never bare `pytest`. The repo uses `uv` for dependency management.

**NEVER touch `tests/test_voice.py`** until Task 4.1 explicitly deletes it. Running old tests alongside new code produces confusing conflicts.

**Commit after every task.** Do not batch multiple tasks into one commit.

---

## File Layout After This Plan Completes

```
src/amplifier_distro/
├── distro_settings.py              (modified: +assistant_name to VoiceSettings)
└── server/
    ├── stub.py                     (modified: +stub_voice_client_secret)
    └── apps/
        └── voice/
            ├── __init__.py         (REPLACED: new routes + AppManifest)
            ├── realtime.py         (NEW: GA API client)
            ├── connection.py       (NEW: VoiceConnection lifecycle manager)
            ├── translator.py       (NEW: VoiceEventTranslator)
            ├── protocols/
            │   ├── __init__.py     (NEW: empty)
            │   ├── event_streaming.py
            │   ├── voice_display.py
            │   └── voice_approval.py
            ├── transcript/
            │   ├── __init__.py     (NEW: empty)
            │   ├── models.py       (NEW: VoiceConversation, TranscriptEntry)
            │   └── repository.py   (NEW: VoiceConversationRepository)
            └── static/
                ├── index.html      (NEW: Preact frontend)
                └── vendor.js       (NEW: Preact + HTM + marked.js)

tests/
├── test_voice.py                   (DELETED in Task 4.1)
├── test_voice_settings.py          (NEW)
├── test_voice_realtime.py          (NEW)
├── test_voice_transcript.py        (NEW)
├── test_voice_protocols.py         (NEW)
├── test_voice_translator.py        (NEW)
├── test_voice_connection.py        (NEW)
└── test_voice_routes.py            (NEW, replaces test_voice.py)
```

---

## PHASE 1 — Data Layer

*No FastAPI imports. No session backend. Pure Python. Start today.*

---

### Task 1.1: VoiceSettings.assistant_name

**Files:**
- Modify: `src/amplifier_distro/distro_settings.py`
- Create: `tests/test_voice_settings.py`

**Step 1: Write the failing test**

Create `tests/test_voice_settings.py`:

```python
"""Tests for VoiceSettings.assistant_name field and env export."""
from __future__ import annotations

import os

import pytest

from amplifier_distro.distro_settings import DistroSettings, VoiceSettings, export_to_env


@pytest.fixture(autouse=True)
def clean_env():
    """Remove the env var before and after each test to prevent cross-test pollution."""
    os.environ.pop("AMPLIFIER_VOICE_ASSISTANT_NAME", None)
    yield
    os.environ.pop("AMPLIFIER_VOICE_ASSISTANT_NAME", None)


def test_voice_settings_has_assistant_name_field():
    """VoiceSettings must have assistant_name with default 'Amplifier'."""
    settings = VoiceSettings()
    assert settings.assistant_name == "Amplifier"


def test_assistant_name_exported_to_env():
    """export_to_env() must set AMPLIFIER_VOICE_ASSISTANT_NAME."""
    settings = DistroSettings()
    export_to_env(settings)
    assert os.environ.get("AMPLIFIER_VOICE_ASSISTANT_NAME") == "Amplifier"


def test_custom_assistant_name_exported():
    """Custom assistant_name is exported correctly."""
    settings = DistroSettings(voice=VoiceSettings(assistant_name="Jarvis"))
    export_to_env(settings)
    assert os.environ.get("AMPLIFIER_VOICE_ASSISTANT_NAME") == "Jarvis"


def test_existing_env_var_not_overwritten():
    """export_to_env() uses setdefault — pre-set env vars take precedence."""
    os.environ["AMPLIFIER_VOICE_ASSISTANT_NAME"] = "Cortana"
    settings = DistroSettings()
    export_to_env(settings)
    assert os.environ.get("AMPLIFIER_VOICE_ASSISTANT_NAME") == "Cortana"
```

**Step 2: Run test to verify it fails**

```bash
uv run python -m pytest tests/test_voice_settings.py -v
```

Expected: FAIL with `AttributeError: 'VoiceSettings' object has no attribute 'assistant_name'`

**Step 3: Implement the changes**

In `src/amplifier_distro/distro_settings.py`, make exactly two changes:

**Change 1** — Add `assistant_name` to the `VoiceSettings` dataclass (after `tools_enabled`):
```python
@dataclass
class VoiceSettings:
    """Voice bridge configuration."""

    voice: str = "ash"
    model: str = "gpt-4o-realtime-preview"
    instructions: str = ""
    tools_enabled: bool = False
    assistant_name: str = "Amplifier"   # Wake word prefix and TTS persona name
```

**Change 2** — Add `"assistant_name"` to `_VOICE_ENV_MAP` (after `"tools_enabled"`):
```python
_VOICE_ENV_MAP: dict[str, str] = {
    "voice": "AMPLIFIER_VOICE_VOICE",
    "model": "AMPLIFIER_VOICE_MODEL",
    "instructions": "AMPLIFIER_VOICE_INSTRUCTIONS",
    "tools_enabled": "AMPLIFIER_VOICE_TOOLS_ENABLED",
    "assistant_name": "AMPLIFIER_VOICE_ASSISTANT_NAME",  # NEW
}
```

**Step 4: Run test to verify it passes**

```bash
uv run python -m pytest tests/test_voice_settings.py -v
```

Expected: 4 passed

**Step 5: Commit**

```bash
git add src/amplifier_distro/distro_settings.py tests/test_voice_settings.py
git commit -m "feat: add VoiceSettings.assistant_name field with env export"
```

---

### Task 1.2: voice/realtime.py — GA API client

**Files:**
- Create: `src/amplifier_distro/server/apps/voice/realtime.py`
- Create: `tests/test_voice_realtime.py`

**Step 1: Write the failing test**

Create `tests/test_voice_realtime.py`:

```python
"""Tests for the GA OpenAI Realtime API client."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx


@dataclass
class FakeVoiceConfig:
    model: str = "gpt-4o-realtime-preview"
    voice: str = "ash"
    instructions: str = "You are Amplifier."
    tools: list = None
    openai_api_key: str = "sk-test-key"

    def __post_init__(self):
        if self.tools is None:
            self.tools = []


def make_mock_response(status=200, json_data=None, text_data=None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.is_error = status >= 400
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    if text_data is not None:
        resp.text = text_data
    return resp


class TestCreateClientSecret:
    """create_client_secret() POSTs to /v1/realtime/client_secrets."""

    @pytest.mark.asyncio
    async def test_returns_token_value_string(self):
        from amplifier_distro.server.apps.voice.realtime import create_client_secret

        mock_resp = make_mock_response(200, json_data={"value": "ek_live_abc123"})

        with patch("amplifier_distro.server.apps.voice.realtime.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            config = FakeVoiceConfig()
            result = await create_client_secret(config)

        assert result == "ek_live_abc123"

    @pytest.mark.asyncio
    async def test_posts_to_correct_endpoint(self):
        from amplifier_distro.server.apps.voice.realtime import (
            CLIENT_SECRETS_ENDPOINT,
            create_client_secret,
        )

        mock_resp = make_mock_response(200, json_data={"value": "ek_xyz"})

        with patch("amplifier_distro.server.apps.voice.realtime.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            config = FakeVoiceConfig()
            await create_client_secret(config)

        call_args = mock_client.post.call_args
        assert call_args[0][0] == CLIENT_SECRETS_ENDPOINT

    @pytest.mark.asyncio
    async def test_payload_includes_session_type_realtime(self):
        from amplifier_distro.server.apps.voice.realtime import create_client_secret

        mock_resp = make_mock_response(200, json_data={"value": "ek_xyz"})

        with patch("amplifier_distro.server.apps.voice.realtime.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            config = FakeVoiceConfig(model="gpt-4o-realtime-preview")
            await create_client_secret(config)

        payload = mock_client.post.call_args[1]["json"]
        assert payload["session"]["type"] == "realtime"
        assert payload["session"]["model"] == "gpt-4o-realtime-preview"

    @pytest.mark.asyncio
    async def test_raises_http_exception_on_error(self):
        from fastapi import HTTPException
        from amplifier_distro.server.apps.voice.realtime import create_client_secret

        mock_resp = make_mock_response(401, json_data={"error": "bad key"})
        mock_resp.text = "Unauthorized"

        with patch("amplifier_distro.server.apps.voice.realtime.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await create_client_secret(FakeVoiceConfig())

        assert exc_info.value.status_code == 401


class TestExchangeSdp:
    """exchange_sdp() POSTs to /v1/realtime/calls."""

    @pytest.mark.asyncio
    async def test_returns_sdp_answer_string(self):
        from amplifier_distro.server.apps.voice.realtime import exchange_sdp

        sdp_answer = "v=0\r\no=- 0 0 IN IP4 0.0.0.0\r\n"
        mock_resp = make_mock_response(200, text_data=sdp_answer)

        with patch("amplifier_distro.server.apps.voice.realtime.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await exchange_sdp("v=0\r\noffer", "ek_token", "gpt-4o-realtime-preview")

        assert result == sdp_answer

    @pytest.mark.asyncio
    async def test_uses_token_as_bearer_auth(self):
        from amplifier_distro.server.apps.voice.realtime import exchange_sdp

        mock_resp = make_mock_response(200, text_data="v=0\r\n")

        with patch("amplifier_distro.server.apps.voice.realtime.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            await exchange_sdp("offer_sdp", "ek_mytoken", "gpt-4o-realtime-preview")

        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer ek_mytoken"
```

**Step 2: Run test to verify it fails**

```bash
uv run python -m pytest tests/test_voice_realtime.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named '...realtime'`

**Step 3: Implement `realtime.py`**

Create `src/amplifier_distro/server/apps/voice/realtime.py`:

```python
"""GA OpenAI Realtime API client — isolated from route handlers.

Two exported functions:
  create_client_secret(config) -> str   — POSTs to /v1/realtime/client_secrets
  exchange_sdp(offer, token, model) -> str — POSTs to /v1/realtime/calls

All OpenAI API logic lives here. Route handlers call these functions and
return the results. This keeps routes thin and makes stub extension clean.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# GA API endpoints (changed from beta)
OPENAI_REALTIME_BASE = "https://api.openai.com/v1/realtime"
CLIENT_SECRETS_ENDPOINT = f"{OPENAI_REALTIME_BASE}/client_secrets"
SDP_EXCHANGE_ENDPOINT = f"{OPENAI_REALTIME_BASE}/calls"


@dataclass
class VoiceConfig:
    """Configuration passed to realtime API calls."""

    model: str
    voice: str
    instructions: str
    tools: list = field(default_factory=list)
    openai_api_key: str = ""


async def create_client_secret(config: VoiceConfig) -> str:
    """POST to /v1/realtime/client_secrets. Returns the ephemeral token value string.

    GA API note: voice, turn_detection, modalities are NOT supported at session
    creation. Set those via session.update after WebRTC connection is established.
    """
    headers = {
        "Authorization": f"Bearer {config.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "session": {
            "type": "realtime",  # Required in GA API
            "model": config.model,
            "instructions": config.instructions,
            "tools": config.tools,
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(CLIENT_SECRETS_ENDPOINT, json=payload, headers=headers)

    if resp.is_error:
        logger.error(
            "OpenAI client_secrets failed: %d — %s", resp.status_code, resp.text
        )
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    data = resp.json()
    return data["value"]  # Just the ephemeral token string, e.g. "ek_..."


async def exchange_sdp(sdp_offer: str, ephemeral_token: str, model: str) -> str:
    """POST to /v1/realtime/calls. Returns the SDP answer string.

    Args:
        sdp_offer: The browser's SDP offer (string from RTCPeerConnection)
        ephemeral_token: The client secret value from create_client_secret()
        model: Model name (used as URL param by some GA revisions, kept for future use)
    """
    headers = {
        "Authorization": f"Bearer {ephemeral_token}",
        "Content-Type": "application/sdp",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            SDP_EXCHANGE_ENDPOINT,
            content=sdp_offer.encode("utf-8"),
            headers=headers,
        )

    if resp.is_error:
        logger.error(
            "OpenAI SDP exchange failed: %d — %s", resp.status_code, resp.text
        )
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    logger.info("SDP exchange successful")
    return resp.text
```

**Step 4: Run test to verify it passes**

```bash
uv run python -m pytest tests/test_voice_realtime.py -v
```

Expected: 6 passed

**Step 5: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/realtime.py tests/test_voice_realtime.py
git commit -m "feat: add voice/realtime.py GA API client (client_secrets + calls)"
```

---

### Task 1.3: transcript/models.py — VoiceConversation & TranscriptEntry

**Files:**
- Create: `src/amplifier_distro/server/apps/voice/transcript/__init__.py` (empty)
- Create: `src/amplifier_distro/server/apps/voice/transcript/models.py`
- Create: `tests/test_voice_transcript.py` (partial — models only for now)

**Step 1: Write the failing test**

Create `tests/test_voice_transcript.py` (models section only):

```python
"""Tests for voice transcript models and repository."""
from __future__ import annotations

from datetime import datetime


class TestVoiceConversation:
    """VoiceConversation dataclass tests."""

    def test_to_dict_and_from_dict_round_trip(self):
        from amplifier_distro.server.apps.voice.transcript.models import VoiceConversation

        conv = VoiceConversation(
            id="session-abc-123",
            title="Test conversation",
            status="active",
            created_at=datetime(2026, 2, 25, 10, 0, 0),
            updated_at=datetime(2026, 2, 25, 10, 5, 0),
        )
        d = conv.to_dict()
        restored = VoiceConversation.from_dict(d)
        assert restored.id == "session-abc-123"
        assert restored.title == "Test conversation"
        assert restored.status == "active"

    def test_to_dict_omits_none_values(self):
        from amplifier_distro.server.apps.voice.transcript.models import VoiceConversation

        conv = VoiceConversation(
            id="sess-1",
            title="T",
            status="active",
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )
        d = conv.to_dict()
        assert "ended_at" not in d
        assert "end_reason" not in d
        assert "duration_seconds" not in d

    def test_from_dict_ignores_unknown_keys(self):
        from amplifier_distro.server.apps.voice.transcript.models import VoiceConversation

        d = {
            "id": "sess-x",
            "title": "Hi",
            "status": "ended",
            "created_at": "2026-02-25T10:00:00",
            "updated_at": "2026-02-25T10:01:00",
            "unknown_future_field": "ignored",
        }
        conv = VoiceConversation.from_dict(d)
        assert conv.id == "sess-x"

    def test_end_reason_values_are_correct_strings(self):
        """end_reason must be one of the five defined values."""
        from amplifier_distro.server.apps.voice.transcript.models import VoiceConversation

        valid_reasons = {"session_limit", "network_error", "user_ended", "idle_timeout", "error"}
        conv = VoiceConversation(
            id="s",
            title="t",
            status="ended",
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
            end_reason="user_ended",
        )
        assert conv.end_reason in valid_reasons


class TestTranscriptEntry:
    """TranscriptEntry dataclass tests."""

    def test_to_dict_and_from_dict_round_trip(self):
        from amplifier_distro.server.apps.voice.transcript.models import TranscriptEntry

        entry = TranscriptEntry(
            id="entry-1",
            conversation_id="sess-abc",
            role="user",
            content="Hello, how are you?",
            created_at=datetime(2026, 2, 25, 10, 0, 0),
        )
        d = entry.to_dict()
        restored = TranscriptEntry.from_dict(d)
        assert restored.id == "entry-1"
        assert restored.role == "user"
        assert restored.content == "Hello, how are you?"

    def test_from_dict_ignores_unknown_keys(self):
        from amplifier_distro.server.apps.voice.transcript.models import TranscriptEntry

        d = {
            "id": "e1",
            "conversation_id": "s1",
            "role": "assistant",
            "content": "Hi there",
            "created_at": "2026-02-25T10:00:00",
            "unknown_field": "ignored",
        }
        entry = TranscriptEntry.from_dict(d)
        assert entry.role == "assistant"

    def test_tool_call_entry_has_call_id_and_tool_name(self):
        from amplifier_distro.server.apps.voice.transcript.models import TranscriptEntry

        entry = TranscriptEntry(
            id="e2",
            conversation_id="s1",
            role="tool_call",
            content='{"instruction": "list files"}',
            created_at=datetime(2026, 2, 25),
            tool_name="delegate",
            call_id="call_abc123",
        )
        d = entry.to_dict()
        assert d["tool_name"] == "delegate"
        assert d["call_id"] == "call_abc123"
```

**Step 2: Run test to verify it fails**

```bash
uv run python -m pytest tests/test_voice_transcript.py::TestVoiceConversation tests/test_voice_transcript.py::TestTranscriptEntry -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement the models**

Create `src/amplifier_distro/server/apps/voice/transcript/__init__.py` (empty file):
```python
```

Create `src/amplifier_distro/server/apps/voice/transcript/models.py`:

```python
"""Voice transcript data models.

VoiceConversation is the surface-level record for a voice session.
Its id field IS the Amplifier session ID — no parallel session world.

TranscriptEntry is one turn in the conversation (user speech, assistant
response, tool call, or tool result). Stored in JSONL format on disk.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class DisconnectEvent:
    """Records one disconnect in a voice session's history."""

    timestamp: str
    reason: str
    reconnected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "reason": self.reason,
            "reconnected": self.reconnected,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DisconnectEvent:
        return cls(
            timestamp=d.get("timestamp", ""),
            reason=d.get("reason", "unknown"),
            reconnected=d.get("reconnected", False),
        )


@dataclass
class VoiceConversation:
    """A voice conversation record.

    id is the Amplifier session ID. There is no separate voice session UUID.
    status is one of: active | disconnected | ended
    end_reason is one of: session_limit | network_error | user_ended |
                          idle_timeout | error
    """

    id: str  # amplifier_session_id — primary key
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None
    duration_seconds: float | None = None
    first_message: str | None = None
    last_message: str | None = None
    tool_call_count: int = 0
    reconnect_count: int = 0
    disconnect_history: list[DisconnectEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict. None values are omitted."""
        d: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tool_call_count": self.tool_call_count,
            "reconnect_count": self.reconnect_count,
            "disconnect_history": [e.to_dict() for e in self.disconnect_history],
        }
        if self.ended_at is not None:
            d["ended_at"] = self.ended_at.isoformat()
        if self.end_reason is not None:
            d["end_reason"] = self.end_reason
        if self.duration_seconds is not None:
            d["duration_seconds"] = self.duration_seconds
        if self.first_message is not None:
            d["first_message"] = self.first_message
        if self.last_message is not None:
            d["last_message"] = self.last_message
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VoiceConversation:
        """Deserialize from dict. Unknown keys are silently ignored."""
        return cls(
            id=d["id"],
            title=d.get("title", ""),
            status=d.get("status", "active"),
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
            ended_at=datetime.fromisoformat(d["ended_at"]) if d.get("ended_at") else None,
            end_reason=d.get("end_reason"),
            duration_seconds=d.get("duration_seconds"),
            first_message=d.get("first_message"),
            last_message=d.get("last_message"),
            tool_call_count=d.get("tool_call_count", 0),
            reconnect_count=d.get("reconnect_count", 0),
            disconnect_history=[
                DisconnectEvent.from_dict(e)
                for e in d.get("disconnect_history", [])
            ],
        )


@dataclass
class TranscriptEntry:
    """One turn in a voice conversation.

    role is one of: user | assistant | tool_call | tool_result
    For tool_call entries, tool_name and call_id must be set, content is the
    JSON-serialized arguments string.
    For tool_result entries, call_id must be set, content is the result string.
    """

    id: str
    conversation_id: str
    role: str
    content: str
    created_at: datetime
    audio_duration_ms: int | None = None  # voice-specific, no Foundation equivalent
    item_id: str | None = None            # OpenAI conversation item ID for resumption
    tool_name: str | None = None          # populated for role="tool_call"
    call_id: str | None = None            # populated for role="tool_call" and "tool_result"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict. None values are omitted."""
        d: dict[str, Any] = {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
        }
        if self.audio_duration_ms is not None:
            d["audio_duration_ms"] = self.audio_duration_ms
        if self.item_id is not None:
            d["item_id"] = self.item_id
        if self.tool_name is not None:
            d["tool_name"] = self.tool_name
        if self.call_id is not None:
            d["call_id"] = self.call_id
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TranscriptEntry:
        """Deserialize from dict. Unknown keys are silently ignored."""
        return cls(
            id=d["id"],
            conversation_id=d.get("conversation_id", ""),
            role=d.get("role", "user"),
            content=d.get("content", ""),
            created_at=datetime.fromisoformat(d["created_at"]),
            audio_duration_ms=d.get("audio_duration_ms"),
            item_id=d.get("item_id"),
            tool_name=d.get("tool_name"),
            call_id=d.get("call_id"),
        )


def new_entry_id() -> str:
    """Generate a new transcript entry ID."""
    return str(uuid.uuid4())
```

**Step 4: Run test to verify it passes**

```bash
uv run python -m pytest tests/test_voice_transcript.py::TestVoiceConversation tests/test_voice_transcript.py::TestTranscriptEntry -v
```

Expected: 6 passed

**Step 5: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/transcript/ tests/test_voice_transcript.py
git commit -m "feat: add voice transcript models (VoiceConversation, TranscriptEntry)"
```

---

### Task 1.4: transcript/repository.py — VoiceConversationRepository

**Files:**
- Create: `src/amplifier_distro/server/apps/voice/transcript/repository.py`
- Extend: `tests/test_voice_transcript.py` (add `TestVoiceConversationRepository` class)

**Step 1: Write the failing test**

Append this class to `tests/test_voice_transcript.py`:

```python
class TestVoiceConversationRepository:
    """Repository tests — use tmp_path for all file I/O."""

    def _make_repo(self, tmp_path):
        from amplifier_distro.server.apps.voice.transcript.repository import (
            VoiceConversationRepository,
        )
        return VoiceConversationRepository(base_dir=tmp_path)

    def _make_conv(self, session_id="sess-abc"):
        from amplifier_distro.server.apps.voice.transcript.models import VoiceConversation
        return VoiceConversation(
            id=session_id,
            title="Test session",
            status="active",
            created_at=datetime(2026, 2, 25, 10, 0, 0),
            updated_at=datetime(2026, 2, 25, 10, 0, 0),
        )

    def test_create_conversation_writes_files(self, tmp_path):
        repo = self._make_repo(tmp_path)
        conv = self._make_conv("sess-1")
        repo.create_conversation(conv)

        assert (tmp_path / "sess-1" / "conversation.json").exists()
        assert (tmp_path / "index.json").exists()

    def test_get_conversation_returns_correct_data(self, tmp_path):
        repo = self._make_repo(tmp_path)
        conv = self._make_conv("sess-2")
        repo.create_conversation(conv)

        restored = repo.get_conversation("sess-2")
        assert restored is not None
        assert restored.id == "sess-2"
        assert restored.title == "Test session"

    def test_add_entry_does_not_touch_index_json(self, tmp_path):
        """CRITICAL: index.json must NOT be rewritten on every add_entry."""
        import json
        from amplifier_distro.server.apps.voice.transcript.models import TranscriptEntry

        repo = self._make_repo(tmp_path)
        conv = self._make_conv("sess-3")
        repo.create_conversation(conv)

        index_path = tmp_path / "index.json"
        mtime_before = index_path.stat().st_mtime

        entry = TranscriptEntry(
            id="e1",
            conversation_id="sess-3",
            role="user",
            content="Hello",
            created_at=datetime(2026, 2, 25, 10, 1, 0),
        )
        import time
        time.sleep(0.05)  # Ensure mtime would change if file were written
        repo.add_entry("sess-3", entry)

        mtime_after = index_path.stat().st_mtime
        assert mtime_before == mtime_after, (
            "add_entry() must NOT rewrite index.json — "
            "only create_conversation() and end_conversation() should touch it"
        )

    def test_add_entry_appends_to_jsonl(self, tmp_path):
        import json
        from amplifier_distro.server.apps.voice.transcript.models import TranscriptEntry

        repo = self._make_repo(tmp_path)
        conv = self._make_conv("sess-4")
        repo.create_conversation(conv)

        for i in range(3):
            entry = TranscriptEntry(
                id=f"e{i}",
                conversation_id="sess-4",
                role="user",
                content=f"Message {i}",
                created_at=datetime(2026, 2, 25, 10, i, 0),
            )
            repo.add_entry("sess-4", entry)

        transcript_path = tmp_path / "sess-4" / "transcript.jsonl"
        lines = [l for l in transcript_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 3

    def test_end_conversation_updates_index(self, tmp_path):
        import json

        repo = self._make_repo(tmp_path)
        conv = self._make_conv("sess-5")
        repo.create_conversation(conv)
        repo.end_conversation("sess-5", reason="user_ended")

        index = json.loads((tmp_path / "index.json").read_text())
        entry = next(e for e in index if e["id"] == "sess-5")
        assert entry["status"] == "ended"

        full_conv = repo.get_conversation("sess-5")
        assert full_conv.end_reason == "user_ended"
        assert full_conv.ended_at is not None

    def test_get_resumption_context_includes_tool_calls(self, tmp_path):
        """Tool calls must appear in resumption context as OpenAI function_call format."""
        from amplifier_distro.server.apps.voice.transcript.models import TranscriptEntry

        repo = self._make_repo(tmp_path)
        conv = self._make_conv("sess-6")
        repo.create_conversation(conv)

        # User turn
        repo.add_entry("sess-6", TranscriptEntry(
            id="e1", conversation_id="sess-6", role="user",
            content="List the files here", created_at=datetime(2026, 2, 25, 10, 0, 0),
        ))
        # Tool call
        repo.add_entry("sess-6", TranscriptEntry(
            id="e2", conversation_id="sess-6", role="tool_call",
            content='{"instruction": "list files in current directory"}',
            created_at=datetime(2026, 2, 25, 10, 0, 1),
            tool_name="delegate", call_id="call_abc",
        ))
        # Tool result
        repo.add_entry("sess-6", TranscriptEntry(
            id="e3", conversation_id="sess-6", role="tool_result",
            content="file1.py\nfile2.py", created_at=datetime(2026, 2, 25, 10, 0, 2),
            call_id="call_abc",
        ))

        context = repo.get_resumption_context("sess-6")

        types = [item["type"] for item in context]
        assert "message" in types
        assert "function_call" in types
        assert "function_call_output" in types

        tool_call = next(i for i in context if i["type"] == "function_call")
        assert tool_call["name"] == "delegate"
        assert tool_call["call_id"] == "call_abc"

        tool_result = next(i for i in context if i["type"] == "function_call_output")
        assert tool_result["call_id"] == "call_abc"
        assert "file1.py" in tool_result["output"]

    def test_conversation_json_written_atomically(self, tmp_path):
        """Atomic write: .tmp file must not exist after create_conversation()."""
        repo = self._make_repo(tmp_path)
        conv = self._make_conv("sess-7")
        repo.create_conversation(conv)

        tmp_files = list(tmp_path.rglob("*.tmp"))
        assert len(tmp_files) == 0, f"Leftover .tmp files: {tmp_files}"
```

**Step 2: Run test to verify it fails**

```bash
uv run python -m pytest tests/test_voice_transcript.py::TestVoiceConversationRepository -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement the repository**

Create `src/amplifier_distro/server/apps/voice/transcript/repository.py`:

```python
"""VoiceConversationRepository — file-based persistence for voice sessions.

Disk layout:
    ~/.amplifier/voice-sessions/
        index.json                          # fast listing (summary only)
        {amplifier_session_id}/
            conversation.json               # full VoiceConversation (atomic write)
            transcript.jsonl                # TranscriptEntry records, append-only

Design rules:
  - index.json is ONLY rewritten on create_conversation(), end_conversation(),
    and update_status(). It is NEVER touched by add_entry(). This avoids
    rewriting the index on every speech turn (potentially many per session).
  - conversation.json is written atomically via .tmp rename to prevent
    corruption on crashes.
  - transcript.jsonl is append-only. Never rewritten, never truncated.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import TranscriptEntry, VoiceConversation

logger = logging.getLogger(__name__)

_DEFAULT_BASE = Path("~/.amplifier/voice-sessions")


class VoiceConversationRepository:
    """Manages voice session persistence at ~/.amplifier/voice-sessions/."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = (base_dir or _DEFAULT_BASE).expanduser()
        self._base.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _conv_dir(self, session_id: str) -> Path:
        return self._base / session_id

    def _conv_path(self, session_id: str) -> Path:
        return self._conv_dir(session_id) / "conversation.json"

    def _transcript_path(self, session_id: str) -> Path:
        return self._conv_dir(session_id) / "transcript.jsonl"

    def _index_path(self) -> Path:
        return self._base / "index.json"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_atomic(self, path: Path, data: Any) -> None:
        """Write JSON atomically via .tmp → rename."""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        tmp.rename(path)

    def _read_index(self) -> list[dict[str, Any]]:
        p = self._index_path()
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text())
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _write_index(self, entries: list[dict[str, Any]]) -> None:
        self._write_atomic(self._index_path(), entries)

    # ------------------------------------------------------------------
    # Conversation CRUD
    # ------------------------------------------------------------------

    def create_conversation(self, conversation: VoiceConversation) -> None:
        """Create a new conversation. Writes conversation.json and updates index.json."""
        self._conv_dir(conversation.id).mkdir(parents=True, exist_ok=True)
        # Create empty transcript file so add_entry() never needs to create it
        transcript = self._transcript_path(conversation.id)
        if not transcript.exists():
            transcript.touch()
        self._write_atomic(self._conv_path(conversation.id), conversation.to_dict())
        # Update index
        index = self._read_index()
        index = [e for e in index if e.get("id") != conversation.id]  # dedupe
        index.insert(0, {
            "id": conversation.id,
            "title": conversation.title,
            "status": conversation.status,
            "created_at": conversation.created_at.isoformat(),
            "first_message": conversation.first_message,
        })
        self._write_index(index)

    def get_conversation(self, session_id: str) -> VoiceConversation | None:
        """Read a VoiceConversation by session_id. Returns None if not found."""
        p = self._conv_path(session_id)
        if not p.exists():
            return None
        try:
            return VoiceConversation.from_dict(json.loads(p.read_text()))
        except (json.JSONDecodeError, KeyError, ValueError):
            logger.warning("Failed to read conversation.json for %s", session_id)
            return None

    def update_conversation(self, conversation: VoiceConversation) -> None:
        """Write updated conversation.json. Does NOT touch index.json."""
        self._write_atomic(self._conv_path(conversation.id), conversation.to_dict())

    def update_status(self, session_id: str, status: str) -> None:
        """Update status field. Writes both conversation.json and index.json."""
        conv = self.get_conversation(session_id)
        if conv is None:
            return
        conv.status = status
        conv.updated_at = datetime.utcnow()
        self._write_atomic(self._conv_path(session_id), conv.to_dict())
        # Update index entry
        index = self._read_index()
        for entry in index:
            if entry.get("id") == session_id:
                entry["status"] = status
        self._write_index(index)

    def end_conversation(self, session_id: str, reason: str) -> None:
        """Mark as ended, record reason and duration. Updates index.json."""
        conv = self.get_conversation(session_id)
        if conv is None:
            logger.warning("Cannot end conversation — not found: %s", session_id)
            return
        now = datetime.utcnow()
        conv.status = "ended"
        conv.end_reason = reason
        conv.ended_at = now
        conv.updated_at = now
        if conv.created_at:
            conv.duration_seconds = (now - conv.created_at).total_seconds()
        self._write_atomic(self._conv_path(session_id), conv.to_dict())
        # Update index
        index = self._read_index()
        for entry in index:
            if entry.get("id") == session_id:
                entry["status"] = "ended"
        self._write_index(index)

    # ------------------------------------------------------------------
    # Transcript management
    # ------------------------------------------------------------------

    def add_entry(self, session_id: str, entry: TranscriptEntry) -> None:
        """Append one entry to transcript.jsonl. Does NOT touch index.json."""
        with open(self._transcript_path(session_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def add_entries(self, session_id: str, entries: list[TranscriptEntry]) -> None:
        """Batch-append entries to transcript.jsonl. Does NOT touch index.json."""
        with open(self._transcript_path(session_id), "a", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def get_resumption_context(self, session_id: str) -> list[dict[str, Any]]:
        """Return conversation history in OpenAI Realtime format.

        Includes tool calls as function_call / function_call_output items.
        This is the fix over amplifier-voice's original, which silently dropped
        tool calls and made resumed sessions unaware of what the agent did.
        """
        p = self._transcript_path(session_id)
        if not p.exists():
            return []

        items: list[dict[str, Any]] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = TranscriptEntry.from_dict(json.loads(line))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

            if entry.role == "user":
                items.append({
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": entry.content}],
                })
            elif entry.role == "assistant":
                items.append({
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": entry.content}],
                })
            elif entry.role == "tool_call":
                items.append({
                    "type": "function_call",
                    "name": entry.tool_name or "delegate",
                    "call_id": entry.call_id or entry.id,
                    "arguments": entry.content,
                })
            elif entry.role == "tool_result":
                items.append({
                    "type": "function_call_output",
                    "call_id": entry.call_id or entry.id,
                    "output": entry.content,
                })

        return items

    def list_conversations(self) -> list[dict[str, Any]]:
        """Return index entries (id, title, status, created_at, first_message).
        Fast — reads only index.json, not individual conversation files.
        """
        return self._read_index()
```

**Step 4: Run test to verify it passes**

```bash
uv run python -m pytest tests/test_voice_transcript.py -v
```

Expected: All tests pass (models + repository)

**Step 5: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/transcript/repository.py tests/test_voice_transcript.py
git commit -m "feat: add VoiceConversationRepository with atomic writes and tool call resumption"
```

---

## PHASE 2 — Protocol Layer

*Still no FastAPI dependencies. Start today.*

---

### Task 2.1: protocols/event_streaming.py — EventStreamingHook

**Files:**
- Create: `src/amplifier_distro/server/apps/voice/protocols/__init__.py` (empty)
- Create: `src/amplifier_distro/server/apps/voice/protocols/event_streaming.py`
- Create: `tests/test_voice_protocols.py` (partial — EventStreamingHook section)

**Step 1: Write the failing test**

Create `tests/test_voice_protocols.py`:

```python
"""Tests for voice protocol classes."""
from __future__ import annotations

import asyncio
from typing import Any


class TestEventStreamingHook:
    """EventStreamingHook translates Amplifier events to SSE-ready dicts."""

    def _make_hook(self):
        from amplifier_distro.server.apps.voice.protocols.event_streaming import EventStreamingHook
        queue: asyncio.Queue = asyncio.Queue()
        return EventStreamingHook(event_queue=queue), queue

    def test_tool_pre_maps_to_tool_call(self):
        hook, queue = self._make_hook()
        msg = hook._map_event_to_message("tool:pre", {
            "tool_name": "delegate",
            "tool_call_id": "call_1",
            "tool_input": {"instruction": "list files"},
        })
        assert msg is not None
        assert msg["type"] == "tool_call"
        assert msg["tool_name"] == "delegate"
        assert msg["status"] == "pending"

    def test_tool_post_maps_to_tool_result(self):
        hook, queue = self._make_hook()
        msg = hook._map_event_to_message("tool:post", {
            "tool_name": "delegate",
            "tool_call_id": "call_1",
            "result": {"output": "file1.py\nfile2.py", "success": True},
        })
        assert msg is not None
        assert msg["type"] == "tool_result"
        assert "file1.py" in msg["output"]

    def test_content_block_start_tracks_block_type(self):
        hook, queue = self._make_hook()
        msg = hook._map_event_to_message("content_block:start", {
            "block_index": 0,
            "block_type": "tool_use",
        })
        assert msg["type"] == "content_start"
        assert hook._current_blocks[0] == "tool_use"

    def test_content_block_delta_uses_tracked_block_type(self):
        hook, queue = self._make_hook()
        # First start the block
        hook._map_event_to_message("content_block:start", {"block_index": 2, "block_type": "text"})
        # Then send delta
        msg = hook._map_event_to_message("content_block:delta", {
            "block_index": 2,
            "delta": {"text": "Hello"},
        })
        assert msg["block_type"] == "text"
        assert msg["delta"] == "Hello"

    def test_content_block_end_removes_from_current_blocks(self):
        hook, queue = self._make_hook()
        hook._map_event_to_message("content_block:start", {"block_index": 1, "block_type": "text"})
        hook._map_event_to_message("content_block:end", {"block_index": 1})
        assert 1 not in hook._current_blocks

    def test_cancel_requested_maps_correctly(self):
        hook, queue = self._make_hook()
        msg = hook._map_event_to_message("cancel:requested", {
            "level": "graceful",
            "running_tools": ["delegate"],
        })
        assert msg["type"] == "cancel_requested"
        assert msg["level"] == "graceful"

    def test_session_fork_maps_correctly(self):
        hook, queue = self._make_hook()
        msg = hook._map_event_to_message("session:fork", {
            "child_session_id": "child-abc",
            "agent": "foundation:explorer",
        })
        assert msg["type"] == "session_fork"
        assert msg["agent"] == "foundation:explorer"

    def test_large_base64_data_is_stripped(self):
        hook, queue = self._make_hook()
        large_data = "A" * 1500
        sanitized = hook._sanitize_for_streaming({
            "type": "base64",
            "data": large_data,
        })
        assert sanitized["data"] == "[image data omitted]"

    def test_small_base64_data_passes_through(self):
        hook, queue = self._make_hook()
        small_data = "A" * 50
        sanitized = hook._sanitize_for_streaming({
            "type": "base64",
            "data": small_data,
        })
        assert sanitized["data"] == small_data
```

**Step 2: Run test to verify it fails**

```bash
uv run python -m pytest tests/test_voice_protocols.py::TestEventStreamingHook -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement EventStreamingHook**

Create `src/amplifier_distro/server/apps/voice/protocols/__init__.py` (empty).

Create `src/amplifier_distro/server/apps/voice/protocols/event_streaming.py` — port from `amplifier-voice` as-is:

```python
"""EventStreamingHook — Amplifier events → SSE-ready JSON.

Ported from amplifier-voice/voice_server/protocols/event_streaming.py.
Subscribes to 24 Amplifier canonical events, translates to SSE wire format.

Registration pattern (called from VoiceConnection after create_session):
    hook = EventStreamingHook(event_queue=queue)
    # Register for each event in EVENTS_TO_CAPTURE using the session's
    # hook registry. Store the returned unregister callable on VoiceConnection.
    # Call it unconditionally in teardown's finally block.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EventStreamingHook:
    """Queue-based streaming hook for browser debugging console.

    Subscribes to Amplifier events, translates them, and puts SSE-friendly
    dicts into the provided asyncio.Queue for the /events SSE endpoint to drain.

    All events pass through. Only large base64 payloads are stripped (> 1000 chars).
    """

    name = "voice-event-streaming"
    priority = 100

    def __init__(self, event_queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._queue = event_queue
        self._current_blocks: dict[int, str] = {}  # block_index -> block_type

    async def __call__(self, event: str, data: dict[str, Any]) -> Any:
        """Handle Amplifier event and enqueue for SSE streaming."""
        logger.debug("[EVENT] %s: %s", event, list(data.keys()) if data else "no data")
        try:
            message = self._map_event_to_message(event, data)
            if message:
                await self._queue.put(message)
        except Exception as exc:
            logger.warning("Failed to queue event %s: %s", event, exc)
        # Return value format depends on amplifier-core HookResult contract.
        # If HookResult is available: return HookResult(action="continue")
        # Otherwise return None — the hook system ignores None returns.
        try:
            from amplifier_core.models import HookResult
            return HookResult(action="continue")
        except ImportError:
            return None

    def _map_event_to_message(
        self, event: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Map Amplifier event name + data to SSE wire message dict."""
        sanitized = self._sanitize_for_streaming(data)
        msg_type = event.replace(":", "_").replace("_block", "")

        if event == "content_block:start":
            block_type = data.get("block_type") or data.get("type", "text")
            index = (
                data.get("block_index")
                if data.get("block_index") is not None
                else data.get("index", 0)
            )
            self._current_blocks[index] = block_type
            return {"type": "content_start", "block_type": block_type, "index": index, **sanitized}

        elif event == "content_block:delta":
            index = (
                data.get("block_index")
                if data.get("block_index") is not None
                else data.get("index", 0)
            )
            block_type = self._current_blocks.get(index, "text")
            delta = data.get("delta", {})
            delta_text = delta.get("text", "") if isinstance(delta, dict) else str(delta)
            return {
                "type": "content_delta",
                "index": index,
                "delta": delta_text,
                "block_type": block_type,
                **sanitized,
            }

        elif event == "content_block:end":
            index = (
                data.get("block_index")
                if data.get("block_index") is not None
                else data.get("index", 0)
            )
            block_type = self._current_blocks.pop(index, "text")
            block = data.get("block", {})
            content = (
                block.get("text", "") or block.get("content", "")
                if isinstance(block, dict)
                else data.get("content", "")
            )
            return {
                "type": "content_end",
                "index": index,
                "content": content,
                "block_type": block_type,
                **sanitized,
            }

        elif event == "thinking:delta":
            return {"type": "thinking_delta", **sanitized}

        elif event == "thinking:final":
            return {"type": "thinking_final", **sanitized}

        elif event == "tool:pre":
            return {
                "type": "tool_call",
                "tool_name": data.get("tool_name", "unknown"),
                "tool_call_id": data.get("tool_call_id", ""),
                "arguments": data.get("tool_input") or data.get("arguments", {}),
                "status": "pending",
                **sanitized,
            }

        elif event == "tool:post":
            result = data.get("result", {})
            return {
                "type": "tool_result",
                "tool_name": data.get("tool_name", "unknown"),
                "tool_call_id": data.get("tool_call_id", ""),
                "output": (
                    result.get("output", "") if isinstance(result, dict) else str(result)
                ),
                "success": result.get("success", True) if isinstance(result, dict) else True,
                "error": result.get("error") if isinstance(result, dict) else None,
                **sanitized,
            }

        elif event == "tool:error":
            return {"type": "tool_error", **sanitized}

        elif event == "session:fork":
            return {
                "type": "session_fork",
                "child_session_id": data.get("child_session_id", ""),
                "agent": data.get("agent", ""),
                **sanitized,
            }

        elif event == "session:start":
            return {"type": "session_start", **sanitized}

        elif event == "session:end":
            return {"type": "session_end", **sanitized}

        elif event in ("provider:request", "llm:request", "llm:request:raw"):
            return {"type": "provider_request", "event": event, **sanitized}

        elif event in ("provider:response", "llm:response", "llm:response:raw"):
            return {"type": "provider_response", "event": event, **sanitized}

        elif event == "context:compaction":
            return {"type": "context_compaction", **sanitized}

        elif event == "user:notification":
            return {"type": "display_message", **sanitized}

        elif event == "cancel:requested":
            return {
                "type": "cancel_requested",
                "level": data.get("level", "graceful"),
                "running_tools": data.get("running_tools", []),
                **sanitized,
            }

        elif event == "cancel:completed":
            return {
                "type": "cancel_completed",
                "level": data.get("level", "graceful"),
                "tools_cancelled": data.get("tools_cancelled", 0),
                **sanitized,
            }

        else:
            return {"type": msg_type, "event": event, **sanitized}

    def _sanitize_for_streaming(self, data: dict[str, Any]) -> dict[str, Any]:
        """Strip large base64 payloads. Everything else passes through unchanged."""

        def sanitize_value(val: Any) -> Any:
            if isinstance(val, dict):
                if val.get("type") == "image" and "source" in val:
                    return {**val, "source": {"type": "base64", "data": "[image data omitted]"}}
                if (
                    val.get("type") == "base64"
                    and "data" in val
                    and len(str(val.get("data", ""))) > 1000
                ):
                    return {"type": "base64", "data": "[image data omitted]"}
                return {k: sanitize_value(v) for k, v in val.items()}
            elif isinstance(val, list):
                return [sanitize_value(item) for item in val]
            return val

        return sanitize_value(data)


# Complete list of Amplifier canonical events to subscribe to
EVENTS_TO_CAPTURE = [
    "content_block:start",
    "content_block:delta",
    "content_block:end",
    "thinking:delta",
    "thinking:final",
    "tool:pre",
    "tool:post",
    "tool:error",
    "session:start",
    "session:end",
    "session:fork",
    "session:join",
    "provider:request",
    "provider:response",
    "llm:request",
    "llm:response",
    "llm:request:raw",
    "llm:response:raw",
    "context:compaction",
    "user:notification",
    "approval:request",
    "approval:response",
    "cancel:requested",
    "cancel:completed",
]
```

**Step 4: Run test to verify it passes**

```bash
uv run python -m pytest tests/test_voice_protocols.py::TestEventStreamingHook -v
```

Expected: 9 passed

**Step 5: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/protocols/ tests/test_voice_protocols.py
git commit -m "feat: add EventStreamingHook (port from amplifier-voice, 24 events)"
```

---

### Task 2.2: protocols/voice_display.py — VoiceDisplaySystem

**Files:**
- Create: `src/amplifier_distro/server/apps/voice/protocols/voice_display.py`
- Extend: `tests/test_voice_protocols.py` (add `TestVoiceDisplaySystem` class)

**Step 1: Write the failing test**

Append to `tests/test_voice_protocols.py`:

```python
class TestVoiceDisplaySystem:
    """VoiceDisplaySystem transforms screen messages into TTS-optimised output."""

    def _make_system(self):
        from amplifier_distro.server.apps.voice.protocols.voice_display import VoiceDisplaySystem
        return VoiceDisplaySystem()

    @pytest.mark.asyncio
    async def test_strips_arrow_symbols(self):
        sys = self._make_system()
        msg = await sys.display("Loading => done -> complete")
        assert "=>" not in msg.spoken_text
        assert "->" not in msg.spoken_text

    @pytest.mark.asyncio
    async def test_strips_pipe_and_ellipsis(self):
        sys = self._make_system()
        msg = await sys.display("Status | working... please wait")
        assert "|" not in msg.spoken_text
        assert "..." not in msg.spoken_text

    @pytest.mark.asyncio
    async def test_truncates_at_sentence_boundary(self):
        sys = self._make_system()
        long_msg = "First sentence. " + ("X" * 200)
        msg = await sys.display(long_msg)
        assert len(msg.spoken_text) <= 200
        assert msg.spoken_text.endswith(".")

    @pytest.mark.asyncio
    async def test_adds_error_prefix(self):
        sys = self._make_system()
        msg = await sys.display("Something went wrong with the connection", level="error")
        assert msg.spoken_text.startswith("Error:")

    @pytest.mark.asyncio
    async def test_debug_messages_not_spoken(self):
        sys = self._make_system()
        msg = await sys.display("debug: internal state dump", level="debug")
        assert msg.should_speak is False

    @pytest.mark.asyncio
    async def test_suppressed_patterns_not_spoken(self):
        sys = self._make_system()
        msg = await sys.display("debug: loading module xyz")
        assert msg.should_speak is False

    @pytest.mark.asyncio
    async def test_normal_info_message_is_spoken(self):
        sys = self._make_system()
        msg = await sys.display("Task completed successfully")
        assert msg.should_speak is True
        assert len(msg.spoken_text) > 0

    @pytest.mark.asyncio
    async def test_very_short_message_not_spoken(self):
        sys = self._make_system()
        msg = await sys.display("ok")
        assert msg.should_speak is False
```

**Step 2: Run test to verify it fails**

```bash
uv run python -m pytest tests/test_voice_protocols.py::TestVoiceDisplaySystem -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement VoiceDisplaySystem**

Create `src/amplifier_distro/server/apps/voice/protocols/voice_display.py` — port from amplifier-voice as-is:

```python
"""VoiceDisplaySystem — transforms screen messages for TTS output.

Ported from amplifier-voice/voice_server/protocols/voice_display.py.

Transformations applied in order:
  1. Strip visual symbols: =>, ->, |, ...
  2. Truncate at 200 chars at sentence boundary (., !, ?)
  3. Add severity prefix: Error:, Note:
  4. Suppress debug/internal patterns (should_speak=False)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class DisplayLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"
    DEBUG = "debug"


@dataclass
class VoiceDisplayMessage:
    level: DisplayLevel
    message: str
    spoken_text: str
    should_speak: bool = True

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "message": self.message,
            "spoken_text": self.spoken_text,
            "should_speak": self.should_speak,
        }


class VoiceDisplaySystem:
    """Display system optimized for voice interactions."""

    def __init__(self, message_callback: Optional[Callable] = None) -> None:
        self._callback = message_callback
        self._suppressed_patterns = [
            "debug:",
            "trace:",
            "[internal]",
        ]

    async def display(
        self, message: str, level: str = "info", nesting: int = 0
    ) -> VoiceDisplayMessage:
        display_level = self._parse_level(level)
        should_speak = self._should_speak(message, display_level)
        spoken_text = self._to_spoken_format(message, display_level) if should_speak else ""

        voice_message = VoiceDisplayMessage(
            level=display_level,
            message=message,
            spoken_text=spoken_text,
            should_speak=should_speak,
        )

        if self._callback and should_speak:
            try:
                await self._callback(voice_message)
            except Exception as exc:
                logger.error("Error in display callback: %s", exc)

        return voice_message

    def _parse_level(self, level: str) -> DisplayLevel:
        try:
            return DisplayLevel(level.lower())
        except ValueError:
            return DisplayLevel.INFO

    def _should_speak(self, message: str, level: DisplayLevel) -> bool:
        if level == DisplayLevel.DEBUG:
            return False
        message_lower = message.lower()
        for pattern in self._suppressed_patterns:
            if pattern in message_lower:
                return False
        if len(message.strip()) < 3:
            return False
        return True

    def _to_spoken_format(self, message: str, level: DisplayLevel) -> str:
        spoken = message.strip()
        spoken = spoken.replace("...", "")
        spoken = spoken.replace("=>", "")
        spoken = spoken.replace("->", "")
        spoken = spoken.replace("|", "")
        spoken = " ".join(spoken.split())

        if level == DisplayLevel.ERROR:
            if not any(w in spoken.lower() for w in ["error", "failed", "problem"]):
                spoken = f"Error: {spoken}"
        elif level == DisplayLevel.WARNING:
            if not any(w in spoken.lower() for w in ["warning", "caution", "note"]):
                spoken = f"Note: {spoken}"

        max_length = 200
        if len(spoken) > max_length:
            sentences = spoken[:max_length].split(". ")
            if len(sentences) > 1:
                spoken = ". ".join(sentences[:-1]) + "."
            else:
                spoken = spoken[:max_length].rsplit(" ", 1)[0] + "..."

        return spoken

    def set_callback(self, callback: Callable) -> None:
        self._callback = callback

    def add_suppressed_pattern(self, pattern: str) -> None:
        self._suppressed_patterns.append(pattern.lower())
```

**Step 4: Run test to verify it passes**

```bash
uv run python -m pytest tests/test_voice_protocols.py::TestVoiceDisplaySystem -v
```

Expected: 8 passed

**Step 5: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/protocols/voice_display.py tests/test_voice_protocols.py
git commit -m "feat: add VoiceDisplaySystem (TTS-optimised display adapter)"
```

---

### Task 2.3: protocols/voice_approval.py — VoiceApprovalSystem

**Files:**
- Create: `src/amplifier_distro/server/apps/voice/protocols/voice_approval.py`
- Extend: `tests/test_voice_protocols.py` (add `TestVoiceApprovalSystem` class)

**Step 1: Write the failing test**

Append to `tests/test_voice_protocols.py`:

```python
class TestVoiceApprovalSystem:
    """VoiceApprovalSystem gates dangerous tool calls via asyncio.Event."""

    def _make_system(self, event_queue=None):
        from amplifier_distro.server.apps.voice.protocols.voice_approval import VoiceApprovalSystem
        q = event_queue or asyncio.Queue()
        return VoiceApprovalSystem(event_queue=q), q

    @pytest.mark.asyncio
    async def test_safe_tools_auto_approved(self):
        sys, q = self._make_system()
        result = await sys.request_approval("read_file", {"file_path": "README.md"})
        assert result is True

    @pytest.mark.asyncio
    async def test_web_search_auto_approved(self):
        sys, q = self._make_system()
        result = await sys.request_approval("web_search", {"query": "python"})
        assert result is True

    @pytest.mark.asyncio
    async def test_dangerous_tool_pushes_to_sse_queue(self):
        sys, q = self._make_system()

        # Immediately respond approved in background
        async def approve_later():
            await asyncio.sleep(0.05)
            sys.handle_response(approved=True)

        asyncio.create_task(approve_later())
        result = await sys.request_approval("bash", {"command": "ls"})

        assert result is True
        # SSE queue should have received an approval_request event
        assert not q.empty()
        event = await q.get()
        assert event["type"] == "approval_request"

    @pytest.mark.asyncio
    async def test_dangerous_tool_can_be_denied(self):
        sys, q = self._make_system()

        async def deny_later():
            await asyncio.sleep(0.05)
            sys.handle_response(approved=False)

        asyncio.create_task(deny_later())
        result = await sys.request_approval("write_file", {"path": "/etc/hosts"})
        assert result is False

    def test_spoken_prompt_for_bash(self):
        from amplifier_distro.server.apps.voice.protocols.voice_approval import VoiceApprovalSystem
        sys = VoiceApprovalSystem(event_queue=asyncio.Queue())
        prompt = sys.generate_spoken_prompt("bash", {"command": "rm -rf /tmp/old"})
        assert "rm -rf" in prompt

    def test_spoken_prompt_for_write_file(self):
        from amplifier_distro.server.apps.voice.protocols.voice_approval import VoiceApprovalSystem
        sys = VoiceApprovalSystem(event_queue=asyncio.Queue())
        prompt = sys.generate_spoken_prompt("write_file", {"path": "config.json"})
        assert "config.json" in prompt

    def test_safe_tools_set_contents(self):
        from amplifier_distro.server.apps.voice.protocols.voice_approval import VoiceApprovalSystem
        assert "read_file" in VoiceApprovalSystem.SAFE_TOOLS
        assert "web_search" in VoiceApprovalSystem.SAFE_TOOLS
        assert "glob" in VoiceApprovalSystem.SAFE_TOOLS

    def test_dangerous_tools_set_contents(self):
        from amplifier_distro.server.apps.voice.protocols.voice_approval import VoiceApprovalSystem
        assert "bash" in VoiceApprovalSystem.DANGEROUS_TOOLS
        assert "write_file" in VoiceApprovalSystem.DANGEROUS_TOOLS
        assert "git_push" in VoiceApprovalSystem.DANGEROUS_TOOLS
```

**Step 2: Run test to verify it fails**

```bash
uv run python -m pytest tests/test_voice_protocols.py::TestVoiceApprovalSystem -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement VoiceApprovalSystem**

Create `src/amplifier_distro/server/apps/voice/protocols/voice_approval.py`:

```python
"""VoiceApprovalSystem — gates dangerous tool calls for voice interface.

Classification logic ported from amplifier-voice. The async contract is
REPLACED with asyncio.Event pattern (matching distro's BridgeApprovalSystem).

VoiceEventHook from amplifier-voice is NOT ported — it was dead code that
subscribed to wrong event names. Its spoken narration concept is handled
by VoiceDisplaySystem instead.

Flow for dangerous tools:
  1. request_approval() pushes approval_request to SSE event queue
  2. Creates asyncio.Event and awaits it (blocks the tool from running)
  3. Browser receives SSE event, shows spoken prompt + UI confirmation
  4. User says yes/no; browser POSTs to /sessions/{id}/approval
  5. Route calls handle_response(approved=True/False)
  6. handle_response() sets the event, unblocking request_approval()
  7. Returns True (approved) or False (denied)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class VoiceApprovalSystem:
    """Tool approval gating for voice interface.

    Safe tools are approved silently. Dangerous tools push an SSE event and
    await a human response via asyncio.Event.
    """

    # Auto-approved silently — read-only operations
    SAFE_TOOLS: set[str] = {
        "read_file", "web_search", "web_fetch", "git_log", "git_status",
        "glob", "grep", "list_directory", "LSP", "python_check",
        "filesystem_read_file", "filesystem_list_directory",
        "fetch", "search", "git_diff", "git_show",
    }

    # Require voice confirmation before executing
    DANGEROUS_TOOLS: set[str] = {
        "bash", "write_file", "edit_file", "delete_file", "apply_patch",
        "git_push", "git_commit", "git_reset", "git_checkout",
        "filesystem_write_file", "filesystem_delete", "move_file",
    }

    def __init__(self, event_queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._queue = event_queue
        self._pending_event: asyncio.Event | None = None
        self._pending_result: bool = False

    async def request_approval(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Request approval for a tool. Returns True if approved, False if denied.

        Safe tools return True immediately. Dangerous tools push an SSE event
        and block until handle_response() is called.
        """
        if tool_name in self.SAFE_TOOLS:
            return True

        if tool_name not in self.DANGEROUS_TOOLS:
            # Unknown tools: check argument patterns
            args_str = str(arguments).lower()
            dangerous_patterns = ["rm ", "delete", "sudo ", "| sh", "| bash"]
            if any(p in args_str for p in dangerous_patterns):
                pass  # Fall through to ask
            else:
                return True  # Unknown but not obviously dangerous — allow

        # Push approval request to SSE queue for browser to display
        request_id = str(uuid.uuid4())
        spoken_prompt = self.generate_spoken_prompt(tool_name, arguments)
        await self._queue.put({
            "type": "approval_request",
            "request_id": request_id,
            "tool_name": tool_name,
            "spoken_prompt": spoken_prompt,
            "is_dangerous": True,
        })

        # Create event and wait for handle_response()
        self._pending_event = asyncio.Event()
        await self._pending_event.wait()
        result = self._pending_result
        self._pending_event = None
        return result

    def handle_response(self, approved: bool) -> None:
        """Called by route handler when user approves or denies.

        Sets the pending asyncio.Event, unblocking request_approval().
        """
        self._pending_result = approved
        if self._pending_event is not None:
            self._pending_event.set()

    def generate_spoken_prompt(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Generate a voice-friendly spoken approval prompt."""
        if "bash" in tool_name.lower() or "execute" in tool_name.lower():
            cmd = str(arguments.get("command", "run a command"))[:60]
            return f"I need to run: {cmd}. Shall I proceed?"
        elif "write" in tool_name.lower():
            path = arguments.get("path", "a file")
            return f"May I write to {path}?"
        elif "delete" in tool_name.lower():
            path = arguments.get("path", "something")
            return f"May I delete {path}?"
        elif "git_push" in tool_name.lower():
            return "May I push to the remote repository?"
        elif "git_commit" in tool_name.lower():
            return "May I create a git commit?"
        else:
            return f"May I use {tool_name}?"
```

**Step 4: Run test to verify it passes**

```bash
uv run python -m pytest tests/test_voice_protocols.py::TestVoiceApprovalSystem -v
```

Expected: 8 passed

**Step 5: Run the full protocols test file**

```bash
uv run python -m pytest tests/test_voice_protocols.py -v
```

Expected: All tests pass (EventStreamingHook + VoiceDisplaySystem + VoiceApprovalSystem)

**Step 6: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/protocols/voice_approval.py tests/test_voice_protocols.py
git commit -m "feat: add VoiceApprovalSystem with asyncio.Event approval gating"
```

---

## PHASE 3 — Connection + Translation Core

**⚠️ STOP HERE if `feat/chat-app` is not merged.** Run the prerequisite check from the top of this document before proceeding.

---

### Task 3.1: translator.py — VoiceEventTranslator

**Files:**
- Create: `src/amplifier_distro/server/apps/voice/translator.py`
- Create: `tests/test_voice_translator.py`

**Step 1: Write the failing test**

Create `tests/test_voice_translator.py`:

```python
"""Table-driven tests for VoiceEventTranslator.

The translator maps OpenAI Realtime data channel events (from the browser's
RTCDataChannel) to browser wire protocol messages that the frontend's
useChatMessages hook processes.
"""
from __future__ import annotations

import pytest


class TestVoiceEventTranslator:
    """Table-driven tests: input event dict → expected wire message."""

    def _translate(self, event_type: str, event_data: dict = None):
        from amplifier_distro.server.apps.voice.translator import VoiceEventTranslator
        t = VoiceEventTranslator()
        return t.translate(event_type, event_data or {})

    # --- Speech detection ---

    def test_speech_started_maps_to_user_turn_start(self):
        msg = self._translate("input_audio_buffer.speech_started", {})
        assert msg is not None
        assert msg["type"] == "user_turn_start"

    def test_speech_stopped_maps_to_user_turn_end(self):
        msg = self._translate("input_audio_buffer.speech_stopped", {})
        assert msg is not None
        assert msg["type"] == "user_turn_end"

    # --- Transcription ---

    def test_transcription_completed_maps_to_user_transcript(self):
        msg = self._translate(
            "conversation.item.input_audio_transcription.completed",
            {"transcript": "List the files here"},
        )
        assert msg is not None
        assert msg["type"] == "user_transcript"
        assert msg["transcript"] == "List the files here"

    # --- Response streaming ---

    def test_audio_transcript_delta_maps_to_assistant_delta(self):
        msg = self._translate(
            "response.audio_transcript.delta",
            {"delta": "Hello there"},
        )
        assert msg is not None
        assert msg["type"] == "assistant_delta"
        assert msg["delta"] == "Hello there"

    def test_audio_transcript_done_maps_to_assistant_done(self):
        msg = self._translate(
            "response.audio_transcript.done",
            {"transcript": "Hello there, how can I help?"},
        )
        assert msg is not None
        assert msg["type"] == "assistant_done"
        assert msg["transcript"] == "Hello there, how can I help?"

    # --- Tool calls ---

    def test_function_call_output_item_maps_to_tool_call(self):
        msg = self._translate(
            "response.output_item.added",
            {
                "item": {
                    "type": "function_call",
                    "name": "delegate",
                    "call_id": "call_abc123",
                    "arguments": '{"instruction": "list files"}',
                }
            },
        )
        assert msg is not None
        assert msg["type"] == "tool_call"
        assert msg["name"] == "delegate"
        assert msg["call_id"] == "call_abc123"

    def test_non_function_output_item_returns_none(self):
        msg = self._translate(
            "response.output_item.added",
            {"item": {"type": "message", "content": []}},
        )
        # Non-function output items are handled by default audio pipeline
        assert msg is None

    # --- Session / lifecycle ---

    def test_response_done_maps_to_response_done(self):
        msg = self._translate("response.done", {})
        assert msg is not None
        assert msg["type"] == "response_done"

    def test_session_created_maps_to_session_ready(self):
        msg = self._translate("session.created", {"session": {"id": "sess_abc"}})
        assert msg is not None
        assert msg["type"] == "session_ready"

    def test_unknown_event_returns_none(self):
        msg = self._translate("some.unknown.event.type", {})
        assert msg is None
```

**Step 2: Run test to verify it fails**

```bash
uv run python -m pytest tests/test_voice_translator.py -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement VoiceEventTranslator**

Create `src/amplifier_distro/server/apps/voice/translator.py`:

```python
"""VoiceEventTranslator — OpenAI Realtime data channel events → browser wire protocol.

Pure transformation logic. No I/O. No state beyond what's needed for this turn.
Fully unit-testable with table-driven tests.

Input: OpenAI Realtime data channel event type (str) + event data (dict)
Output: Browser wire protocol message dict, or None if event should be ignored.

The browser's useChatMessages hook processes these wire messages to update the UI.
"""
from __future__ import annotations

from typing import Any


class VoiceEventTranslator:
    """Translates OpenAI Realtime data channel events to browser wire messages."""

    def translate(self, event_type: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Translate one OpenAI Realtime event.

        Returns None for events the browser handles natively (audio playback,
        ICE events) or that should be silently ignored.
        """
        match event_type:
            # Speech detection — VAD boundary events
            case "input_audio_buffer.speech_started":
                return {"type": "user_turn_start"}

            case "input_audio_buffer.speech_stopped":
                return {"type": "user_turn_end"}

            # User speech transcription (gpt-4o-transcribe)
            case "conversation.item.input_audio_transcription.completed":
                return {
                    "type": "user_transcript",
                    "transcript": data.get("transcript", ""),
                    "item_id": data.get("item_id", ""),
                }

            # Assistant response streaming
            case "response.audio_transcript.delta":
                return {
                    "type": "assistant_delta",
                    "delta": data.get("delta", ""),
                }

            case "response.audio_transcript.done":
                return {
                    "type": "assistant_done",
                    "transcript": data.get("transcript", ""),
                }

            # Tool calls — only function_call type items
            case "response.output_item.added":
                item = data.get("item", {})
                if item.get("type") == "function_call":
                    return {
                        "type": "tool_call",
                        "name": item.get("name", ""),
                        "call_id": item.get("call_id", ""),
                        "arguments": item.get("arguments", "{}"),
                    }
                return None  # Audio/message items handled natively

            # Turn lifecycle
            case "response.done":
                return {"type": "response_done"}

            case "response.created":
                return {"type": "response_created"}

            # Session ready — fires once after WebRTC data channel opens
            case "session.created":
                session = data.get("session", {})
                return {
                    "type": "session_ready",
                    "session_id": session.get("id", ""),
                }

            # Error events — surface to UI
            case "error":
                return {
                    "type": "realtime_error",
                    "code": data.get("error", {}).get("code", "unknown"),
                    "message": data.get("error", {}).get("message", ""),
                }

            case _:
                # All other events (audio buffer, ICE, etc.) are handled natively
                # by the WebRTC stack or are not relevant to the UI state machine
                return None
```

**Step 4: Run test to verify it passes**

```bash
uv run python -m pytest tests/test_voice_translator.py -v
```

Expected: 10 passed

**Step 5: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/translator.py tests/test_voice_translator.py
git commit -m "feat: add VoiceEventTranslator (OpenAI data channel → browser wire protocol)"
```

---

### Task 3.2: connection.py — VoiceConnection

**Files:**
- Create: `src/amplifier_distro/server/apps/voice/connection.py`
- Create: `tests/test_voice_connection.py`

**Step 1: Write the failing test**

Create `tests/test_voice_connection.py`:

```python
"""Tests for VoiceConnection lifecycle using MockBackend.

These tests verify the VoiceConnection manages session state correctly:
  - create() calls backend.create_session() with required parameters
  - spawn capability is registered on the session coordinator before first run()
  - teardown() calls mark_disconnected() and then unregisters hooks in finally
  - hooks are unregistered even when mark_disconnected() raises
  - end() calls backend.end_session() with the tombstone flag
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch
from datetime import datetime

import pytest


def make_mock_backend(session_id="sess-test-001"):
    """Build a MockBackend-like object with the post-merge methods."""
    backend = MagicMock()

    session_info = MagicMock()
    session_info.session_id = session_id
    session_info.session = MagicMock()
    session_info.session.coordinator = MagicMock()
    session_info.session.coordinator.register_capability = MagicMock()
    session_info.session.session_id = session_id

    backend.create_session = AsyncMock(return_value=session_info)
    backend.mark_disconnected = AsyncMock()
    backend.reconnect = AsyncMock(return_value=session_info)
    backend.end_session = AsyncMock()
    backend.cancel_session = AsyncMock()
    # register_hooks returns an unregister callable
    backend.register_hooks = AsyncMock(return_value=lambda: None)

    return backend, session_info


def make_mock_repository(tmp_path, session_id="sess-test-001"):
    from amplifier_distro.server.apps.voice.transcript.models import VoiceConversation
    from amplifier_distro.server.apps.voice.transcript.repository import (
        VoiceConversationRepository,
    )
    repo = VoiceConversationRepository(base_dir=tmp_path)
    conv = VoiceConversation(
        id=session_id, title="Test", status="active",
        created_at=datetime(2026, 2, 25), updated_at=datetime(2026, 2, 25),
    )
    repo.create_conversation(conv)
    return repo


class TestVoiceConnectionLifecycle:

    @pytest.mark.asyncio
    async def test_create_calls_backend_create_session(self, tmp_path):
        from amplifier_distro.server.apps.voice.connection import VoiceConnection

        backend, session_info = make_mock_backend()
        repo = make_mock_repository(tmp_path)
        conn = VoiceConnection(repository=repo, backend=backend)

        session_id = await conn.create(workspace_root=str(tmp_path))

        backend.create_session.assert_called_once()
        call_kwargs = backend.create_session.call_args[1]
        assert call_kwargs.get("app_name") == "voice"
        assert "event_queue" in call_kwargs

    @pytest.mark.asyncio
    async def test_create_returns_amplifier_session_id(self, tmp_path):
        from amplifier_distro.server.apps.voice.connection import VoiceConnection

        backend, session_info = make_mock_backend("sess-returned-123")
        repo = make_mock_repository(tmp_path, "sess-returned-123")
        conn = VoiceConnection(repository=repo, backend=backend)

        session_id = await conn.create(workspace_root=str(tmp_path))
        assert session_id == "sess-returned-123"

    @pytest.mark.asyncio
    async def test_spawn_capability_registered_after_create(self, tmp_path):
        from amplifier_distro.server.apps.voice.connection import VoiceConnection

        backend, session_info = make_mock_backend()
        repo = make_mock_repository(tmp_path)
        conn = VoiceConnection(repository=repo, backend=backend)

        await conn.create(workspace_root=str(tmp_path))

        # spawn capability must be registered on the session coordinator
        session_info.session.coordinator.register_capability.assert_called()
        call_args = session_info.session.coordinator.register_capability.call_args
        assert call_args[0][0] == "spawn"

    @pytest.mark.asyncio
    async def test_teardown_calls_mark_disconnected(self, tmp_path):
        from amplifier_distro.server.apps.voice.connection import VoiceConnection

        backend, session_info = make_mock_backend()
        repo = make_mock_repository(tmp_path)
        conn = VoiceConnection(repository=repo, backend=backend)
        await conn.create(workspace_root=str(tmp_path))

        await conn.teardown()

        backend.mark_disconnected.assert_called_once_with(session_info.session_id)

    @pytest.mark.asyncio
    async def test_hook_unregistered_even_when_mark_disconnected_raises(self, tmp_path):
        from amplifier_distro.server.apps.voice.connection import VoiceConnection

        backend, session_info = make_mock_backend()
        backend.mark_disconnected = AsyncMock(side_effect=RuntimeError("Network error"))

        unregister_called = []
        backend.register_hooks = AsyncMock(
            return_value=lambda: unregister_called.append(True)
        )

        repo = make_mock_repository(tmp_path)
        conn = VoiceConnection(repository=repo, backend=backend)
        await conn.create(workspace_root=str(tmp_path))

        with pytest.raises(RuntimeError):
            await conn.teardown()

        assert len(unregister_called) == 1, (
            "Hook unregister must be called in finally block even when "
            "mark_disconnected() raises"
        )

    @pytest.mark.asyncio
    async def test_end_calls_backend_end_session(self, tmp_path):
        from amplifier_distro.server.apps.voice.connection import VoiceConnection

        backend, session_info = make_mock_backend()
        repo = make_mock_repository(tmp_path)
        conn = VoiceConnection(repository=repo, backend=backend)
        await conn.create(workspace_root=str(tmp_path))

        await conn.end(reason="user_ended")

        backend.end_session.assert_called_once_with(session_info.session_id)
```

**Step 2: Run test to verify it fails**

```bash
uv run python -m pytest tests/test_voice_connection.py -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement VoiceConnection**

Create `src/amplifier_distro/server/apps/voice/connection.py`:

```python
"""VoiceConnection — per-conversation lifecycle manager.

One VoiceConnection instance per active voice conversation. Owns:
  - asyncio.Queue as event bus (passed to create_session as event_queue)
  - EventStreamingHook registration (with stored unregister callable)
  - Amplifier session lifecycle: create → mark_disconnected → reconnect → end_session
  - Spawn capability registration (CRITICAL — must happen before first handle.run())
  - Cancellation via backend.cancel_session()
  - Hook cleanup in finally block on teardown

SPAWN CAPABILITY — why this is critical:
  The voice model's primary tool is 'delegate'. Amplifier routes delegate calls
  by spawning child sessions. Without registering the spawn capability on the
  session coordinator, delegate calls silently fail or bypass the shared backend
  entirely — no hooks, no observability, no session tracking.

  Always register before the first handle.run() call:
    session.coordinator.register_capability("spawn", _spawn_child_session)

HOOK CLEANUP — why this is critical:
  EventStreamingHook is registered per-session. Without unregistering in finally,
  dead hook registrations accumulate across reconnects and fire against closed queues.
  Always call self._hook_unregister() in teardown's finally block.

API NOTE:
  This module requires the post-feat/chat-app version of SessionBackend with:
    create_session(app_name, working_dir, event_queue)
    mark_disconnected(session_id)
    reconnect(session_id)
    end_session(session_id)
    cancel_session(session_id, immediate=bool)
    register_hooks(session_id, hook) -> unregister_callable
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Callable

from amplifier_distro.server.apps.voice.protocols.event_streaming import (
    EVENTS_TO_CAPTURE,
    EventStreamingHook,
)
from amplifier_distro.server.apps.voice.transcript.repository import (
    VoiceConversationRepository,
)

logger = logging.getLogger(__name__)


class VoiceConnection:
    """Manages one voice conversation: session creation, hook wiring, teardown."""

    def __init__(
        self,
        repository: VoiceConversationRepository,
        backend: Any,  # SessionBackend (post-feat/chat-app)
    ) -> None:
        self._repository = repository
        self._backend = backend
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._hook: EventStreamingHook | None = None
        self._hook_unregister: Callable | None = None
        self._session_id: str | None = None
        self._session_obj: Any = None  # AmplifierSession

    @property
    def event_queue(self) -> asyncio.Queue:
        """The SSE event queue — drained by the /events endpoint."""
        return self._event_queue

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def create(self, workspace_root: str) -> str:
        """Create a new Amplifier session. Returns the amplifier_session_id.

        Also:
          - Creates and registers EventStreamingHook
          - Registers spawn capability on session coordinator
        """
        self._hook = EventStreamingHook(event_queue=self._event_queue)

        session_info = await self._backend.create_session(
            app_name="voice",
            working_dir=workspace_root,
            event_queue=self._event_queue,
        )
        self._session_id = session_info.session_id
        self._session_obj = session_info.session

        # Register hook for all captured events. Store unregister callable.
        # Exact API depends on feat/chat-app version of backend.
        # backend.register_hooks(session_id, hook) must return a no-arg callable.
        self._hook_unregister = await self._backend.register_hooks(
            self._session_id, self._hook
        )

        # CRITICAL: Register spawn capability before any handle.run() calls.
        # This routes delegate tool sub-sessions through the shared backend.
        workspace = Path(workspace_root).expanduser()

        async def _spawn_child_session(config: dict) -> Any:
            child_info = await self._backend.create_session(
                app_name="voice",
                working_dir=config.get("cwd", str(workspace)),
                event_queue=self._event_queue,  # child events flow to same SSE stream
            )
            return child_info.session

        self._session_obj.coordinator.register_capability("spawn", _spawn_child_session)

        logger.info("VoiceConnection created for session %s", self._session_id)
        return self._session_id

    async def teardown(self) -> None:
        """Disconnect (not end) — session can be resumed.

        Calls mark_disconnected() then unconditionally unregisters hooks in finally.
        """
        try:
            if self._session_id:
                await self._backend.mark_disconnected(self._session_id)
                await self._repository.update_status(self._session_id, "disconnected")
        finally:
            if self._hook_unregister is not None:
                self._hook_unregister()  # Always clean up — prevents dead hook accumulation
            self._event_queue = asyncio.Queue()  # Reset so new connection can reuse

    async def end(self, reason: str = "user_ended") -> None:
        """Permanently end the session. Cannot be resumed after this."""
        try:
            if self._session_id:
                await self._backend.end_session(self._session_id)
                self._repository.end_conversation(self._session_id, reason=reason)
        finally:
            if self._hook_unregister is not None:
                self._hook_unregister()

    async def cancel(self, immediate: bool = False) -> None:
        """Cancel a running Amplifier operation."""
        if self._session_id:
            await self._backend.cancel_session(self._session_id, immediate=immediate)
```

**Step 4: Run test to verify it passes**

```bash
uv run python -m pytest tests/test_voice_connection.py -v
```

Expected: 6 passed

**Step 5: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/connection.py tests/test_voice_connection.py
git commit -m "feat: add VoiceConnection with hook lifecycle and spawn capability"
```

---

## PHASE 4 — Routes

**⚠️ Still requires `feat/chat-app` merge. Verify before proceeding.**

---

### Task 4.1: voice/__init__.py — Routes & AppManifest

This task replaces the entire `voice/__init__.py` (currently ~490 lines of beta API code and dead tool handlers). It also extends `stub.py` and deletes the old `tests/test_voice.py`.

**Files:**
- Replace: `src/amplifier_distro/server/apps/voice/__init__.py`
- Modify: `src/amplifier_distro/server/stub.py`
- Delete: `tests/test_voice.py`
- Create: `tests/test_voice_routes.py`

**Step 1: Write the failing tests**

**First, delete the old test file:**

```bash
rm tests/test_voice.py
```

Create `tests/test_voice_routes.py`:

```python
"""Route tests for the new voice app — replaces the old tests/test_voice.py.

All route tests use TestClient with mocked realtime.py functions and a
MockBackend for the session backend.

Test fixtures use tmp_path for repository I/O so no real ~/.amplifier is touched.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from amplifier_distro.server.app import AppManifest, DistroServer
from amplifier_distro.server.services import init_services, reset_services


def make_session_info(session_id="sess-voice-001"):
    info = MagicMock()
    info.session_id = session_id
    info.session = MagicMock()
    info.session.coordinator = MagicMock()
    info.session.coordinator.register_capability = MagicMock()
    info.session.session_id = session_id
    return info


@pytest.fixture()
def mock_backend():
    from amplifier_distro.server.session_backend import MockBackend
    backend = MockBackend()
    # Add post-feat/chat-app methods
    backend.mark_disconnected = AsyncMock()
    backend.reconnect = AsyncMock(return_value=make_session_info())
    backend.cancel_session = AsyncMock()
    backend.register_hooks = AsyncMock(return_value=lambda: None)
    # Override create_session to return a richer object
    session_info = make_session_info("sess-voice-001")
    backend.create_session = AsyncMock(return_value=session_info)
    return backend


@pytest.fixture()
def voice_client(tmp_path, mock_backend, monkeypatch):
    """TestClient with voice app mounted and MockBackend injected."""
    from amplifier_distro.server.apps.voice import manifest

    # Init services with mock backend
    init_services(backend=mock_backend)

    # Point repository at tmp_path
    monkeypatch.setenv("AMPLIFIER_VOICE_SESSIONS_DIR", str(tmp_path / "voice-sessions"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key")

    server = DistroServer()
    server.register_app(manifest)
    client = TestClient(server.app)
    yield client
    reset_services()


# ------------------------------------------------------------------
# Manifest
# ------------------------------------------------------------------

class TestVoiceManifest:
    def test_manifest_name_is_voice(self):
        from amplifier_distro.server.apps.voice import manifest
        assert manifest.name == "voice"

    def test_manifest_has_version(self):
        from amplifier_distro.server.apps.voice import manifest
        assert manifest.version == "1.0.0"


# ------------------------------------------------------------------
# Static routes
# ------------------------------------------------------------------

class TestStaticRoutes:
    def test_index_returns_html(self, voice_client):
        resp = voice_client.get("/apps/voice/")
        assert resp.status_code in (200, 404)  # 404 until index.html created in Phase 5
        if resp.status_code == 200:
            assert "text/html" in resp.headers["content-type"]

    def test_vendor_js_returns_javascript(self, voice_client):
        resp = voice_client.get("/apps/voice/static/vendor.js")
        assert resp.status_code in (200, 404)  # 404 until vendor.js created in Phase 5

    def test_api_status_returns_correct_fields(self, voice_client):
        resp = voice_client.get("/apps/voice/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "model" in data
        assert "assistant_name" in data  # From VoiceSettings.assistant_name


# ------------------------------------------------------------------
# Auth enforcement
# ------------------------------------------------------------------

class TestAuthEnforcement:
    def test_get_session_requires_api_key_when_configured(self, voice_client, monkeypatch):
        monkeypatch.setenv("AMPLIFIER_SERVER_API_KEY", "secret-key")
        resp = voice_client.get("/apps/voice/session")
        assert resp.status_code == 401

    def test_get_session_passes_with_correct_api_key(self, voice_client, monkeypatch):
        monkeypatch.setenv("AMPLIFIER_SERVER_API_KEY", "secret-key")
        with patch(
            "amplifier_distro.server.apps.voice.realtime.create_client_secret",
            new_callable=AsyncMock,
            return_value="ek_test_token",
        ):
            resp = voice_client.get(
                "/apps/voice/session",
                headers={"X-Api-Key": "secret-key"},
            )
        assert resp.status_code == 200

    def test_post_sessions_requires_auth(self, voice_client, monkeypatch):
        monkeypatch.setenv("AMPLIFIER_SERVER_API_KEY", "secret-key")
        resp = voice_client.post("/apps/voice/sessions", json={})
        assert resp.status_code == 401

    def test_cancel_requires_auth(self, voice_client, monkeypatch):
        monkeypatch.setenv("AMPLIFIER_SERVER_API_KEY", "secret-key")
        resp = voice_client.post("/apps/voice/cancel", json={"session_id": "x", "immediate": False})
        assert resp.status_code == 401

    def test_tools_execute_requires_auth(self, voice_client, monkeypatch):
        monkeypatch.setenv("AMPLIFIER_SERVER_API_KEY", "secret-key")
        resp = voice_client.post(
            "/apps/voice/tools/execute",
            json={"tool_name": "delegate", "arguments": {}, "call_id": "c1", "session_id": "s1"},
        )
        assert resp.status_code == 401


# ------------------------------------------------------------------
# CSRF protection on /events
# ------------------------------------------------------------------

class TestCsrfProtection:
    def test_events_rejects_non_localhost_origin(self, voice_client):
        resp = voice_client.get(
            "/apps/voice/events",
            headers={"Origin": "https://evil.example.com"},
        )
        assert resp.status_code == 403

    def test_events_allows_localhost_origin(self, voice_client):
        # SSE streams; just check it's not rejected
        resp = voice_client.get(
            "/apps/voice/events",
            headers={"Origin": "http://localhost:8080"},
            timeout=0.1,  # Don't wait for the stream to complete
        )
        # 200 (started streaming) or connection close — not 403
        assert resp.status_code != 403

    def test_events_allows_no_origin(self, voice_client):
        """No Origin header = non-browser client (curl, etc.) — allowed."""
        resp = voice_client.get("/apps/voice/events", timeout=0.1)
        assert resp.status_code != 403


# ------------------------------------------------------------------
# Session ID validation
# ------------------------------------------------------------------

class TestSessionIdValidation:
    def test_path_traversal_rejected_on_end(self, voice_client):
        resp = voice_client.post(
            "/apps/voice/sessions/../etc/shadow/end",
            json={"reason": "user_ended"},
        )
        assert resp.status_code in (400, 404, 422)

    def test_path_traversal_rejected_on_resume(self, voice_client):
        resp = voice_client.post(
            "/apps/voice/sessions/%2F..%2Fetc%2Fshadow/resume",
        )
        assert resp.status_code in (400, 404, 422)


# ------------------------------------------------------------------
# Session lifecycle routes
# ------------------------------------------------------------------

class TestSessionLifecycle:
    def test_post_sessions_creates_session(self, voice_client, tmp_path):
        with patch(
            "amplifier_distro.server.apps.voice.connection.VoiceConnection.create",
            new_callable=AsyncMock,
            return_value="sess-voice-001",
        ):
            resp = voice_client.post("/apps/voice/sessions", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data

    def test_get_sessions_returns_list(self, voice_client, tmp_path):
        resp = voice_client.get("/apps/voice/sessions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ------------------------------------------------------------------
# Realtime signaling routes
# ------------------------------------------------------------------

class TestSignalingRoutes:
    def test_get_session_returns_token_value(self, voice_client):
        with patch(
            "amplifier_distro.server.apps.voice.realtime.create_client_secret",
            new_callable=AsyncMock,
            return_value="ek_live_abc123",
        ):
            resp = voice_client.get("/apps/voice/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["value"] == "ek_live_abc123"

    def test_post_sdp_returns_sdp_answer(self, voice_client):
        with patch(
            "amplifier_distro.server.apps.voice.realtime.exchange_sdp",
            new_callable=AsyncMock,
            return_value="v=0\r\no=- 0 0 IN IP4 0.0.0.0\r\n",
        ):
            resp = voice_client.post(
                "/apps/voice/sdp",
                content="v=0\r\noffer",
                headers={"Content-Type": "application/sdp"},
            )
        assert resp.status_code == 200


# ------------------------------------------------------------------
# Stub mode
# ------------------------------------------------------------------

class TestStubMode:
    def test_stub_session_returns_ga_format(self, voice_client, monkeypatch):
        monkeypatch.setattr(
            "amplifier_distro.server.stub._stub_mode", True
        )
        resp = voice_client.get("/apps/voice/session")
        assert resp.status_code == 200
        data = resp.json()
        assert "value" in data
        assert data["value"].startswith("ek_")

    def test_stub_sdp_returns_valid_sdp(self, voice_client, monkeypatch):
        monkeypatch.setattr(
            "amplifier_distro.server.stub._stub_mode", True
        )
        resp = voice_client.post(
            "/apps/voice/sdp",
            content="v=0\r\noffer",
            headers={"Content-Type": "application/sdp"},
        )
        assert resp.status_code == 200
        assert "v=0" in resp.text
```

**Step 2: Run the test to verify it fails**

```bash
uv run python -m pytest tests/test_voice_routes.py::TestVoiceManifest -v
```

Expected: ImportError or test failures from the old `__init__.py` not having the new routes.

**Step 3: Add the stub extension first**

In `src/amplifier_distro/server/stub.py`, add this function after `stub_voice_sdp()`:

```python
def stub_voice_client_secret() -> str:
    """Canned GA-format client secret for /apps/voice/session in stub mode."""
    return "ek_test_stub_token_not_real"
```

**Step 4: Replace voice/__init__.py entirely**

Delete all existing content and write `src/amplifier_distro/server/apps/voice/__init__.py`:

```python
"""Voice App — Amplifier voice interface via OpenAI Realtime API (GA).

Routes (all mounted at /apps/voice/):
    GET  /                      Serves static/index.html
    GET  /static/vendor.js      Serves vendored Preact + HTM + marked
    GET  /api/status            App health + settings info
    GET  /session               Create OpenAI Realtime client secret (auth)
    POST /sdp                   SDP exchange with OpenAI
    GET  /events                SSE stream of Amplifier events
    POST /sessions              Create voice conversation record (auth)
    POST /sessions/{id}/resume  Reconnect path: fresh secret + context (auth)
    POST /sessions/{id}/transcript  Batch transcript sync (auth)
    POST /sessions/{id}/end     Explicit session end (auth)
    GET  /sessions              List past conversations (auth)
    POST /tools/execute         Execute delegate/cancel tool (auth)
    POST /cancel                Cancel running Amplifier operation (auth)

Auth: Optional X-Api-Key header (HMAC compare). When api_key is unset in
config, all auth checks are skipped — zero friction for personal use.

TURN server: not configured. ICE will fail in symmetric NAT environments.
TODO: Add TURN server config when deploying beyond localhost.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from amplifier_distro.server.app import AppManifest
from amplifier_distro.server.apps.voice.connection import VoiceConnection
from amplifier_distro.server.apps.voice.transcript.models import (
    TranscriptEntry,
    VoiceConversation,
    new_entry_id,
)
from amplifier_distro.server.apps.voice.transcript.repository import (
    VoiceConversationRepository,
)
from amplifier_distro.server.stub import is_stub_mode, stub_voice_client_secret, stub_voice_sdp

logger = logging.getLogger(__name__)

router = APIRouter()

_static_dir = Path(__file__).parent / "static"

# Session ID validation — prevents path traversal via filesystem access
_VALID_SESSION_ID = re.compile(r"^[a-zA-Z0-9_\-]+$")

# Module-level state: one active connection per server instance
# (voice app is single-user; voice sessions do not run in parallel)
_active_connection: VoiceConnection | None = None


# ------------------------------------------------------------------
# Request / Response Models
# ------------------------------------------------------------------

class CreateSessionResponse(BaseModel):
    session_id: str


class ResumeSessionResponse(BaseModel):
    client_secret: str
    context_to_inject: list[dict]


class TranscriptSyncRequest(BaseModel):
    entries: list[dict]


class EndSessionRequest(BaseModel):
    reason: str = "user_ended"


class ToolExecuteRequest(BaseModel):
    tool_name: str
    arguments: dict = {}
    call_id: str
    session_id: str


class ToolResult(BaseModel):
    success: bool
    output: str = ""
    error: str = ""


class CancelRequest(BaseModel):
    session_id: str
    immediate: bool = False


# ------------------------------------------------------------------
# Auth dependencies
# ------------------------------------------------------------------

def _require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> None:
    """Verify X-Api-Key if configured. No-op when api_key is None."""
    try:
        from amplifier_distro.config import get_config as _get_config
        config = _get_config()
        api_key = getattr(config.server, "api_key", None)
    except ImportError:
        return
    if api_key is None:
        return
    if not x_api_key or not hmac.compare_digest(str(x_api_key), str(api_key)):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _check_origin(origin: str | None = Header(default=None)) -> None:
    """CSRF protection for SSE endpoint — localhost origins only."""
    if origin and not any(
        origin.startswith(p)
        for p in ("http://localhost", "http://127.0.0.1", "https://localhost")
    ):
        raise HTTPException(status_code=403, detail="Forbidden origin")


def _validate_session_id(session_id: str) -> str:
    """Raise 400 if session_id looks like a path traversal attempt."""
    if not _VALID_SESSION_ID.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID")
    return session_id


# ------------------------------------------------------------------
# Tool set exposed to OpenAI Realtime model
# ------------------------------------------------------------------

VOICE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "delegate",
        "description": (
            "Delegate a task to an Amplifier specialist agent. Use for any file "
            "operations, web search, code execution, or complex reasoning."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "The task instruction for the specialist agent",
                }
            },
            "required": ["instruction"],
        },
    },
    {
        "type": "function",
        "name": "cancel_current_task",
        "description": "Cancel the currently running Amplifier operation.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "pause_replies",
        "description": (
            "Pause automatic responses. The assistant will continue listening "
            "but won't respond until resumed."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "resume_replies",
        "description": "Resume automatic responses after pausing.",
        "parameters": {"type": "object", "properties": {}},
    },
]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_repository(base_dir: Path | None = None) -> VoiceConversationRepository:
    """Return a VoiceConversationRepository.

    base_dir defaults to ~/.amplifier/voice-sessions unless overridden by
    AMPLIFIER_VOICE_SESSIONS_DIR env var (used in tests).
    """
    if base_dir is None:
        env_dir = os.environ.get("AMPLIFIER_VOICE_SESSIONS_DIR")
        if env_dir:
            base_dir = Path(env_dir)
    return VoiceConversationRepository(base_dir=base_dir)


def _get_voice_config():
    """Load voice config from env vars (set by export_to_env() at startup)."""
    from amplifier_distro.server.apps.voice.realtime import VoiceConfig

    return VoiceConfig(
        model=os.environ.get("AMPLIFIER_VOICE_MODEL", "gpt-4o-realtime-preview"),
        voice=os.environ.get("AMPLIFIER_VOICE_VOICE", "ash"),
        instructions=os.environ.get(
            "AMPLIFIER_VOICE_INSTRUCTIONS",
            "You are Amplifier, a helpful voice assistant with access to developer "
            "tools. Keep responses concise and conversational.",
        ),
        tools=VOICE_TOOLS,
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
    )


def _workspace_root() -> str:
    return os.environ.get("AMPLIFIER_WORKSPACE_ROOT", str(Path.home()))


# ------------------------------------------------------------------
# Static routes
# ------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_file = _static_dir / "index.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<html><body><h1>Amplifier Voice</h1><p>index.html not built yet.</p></body></html>",
        status_code=200,
    )


@router.get("/static/vendor.js")
async def vendor_js():
    from fastapi.responses import Response
    vendor_file = _static_dir / "vendor.js"
    if vendor_file.exists():
        return Response(
            content=vendor_file.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )
    return Response(
        content="// vendor.js not built yet\n",
        media_type="application/javascript",
        status_code=404,
    )


@router.get("/api/status")
async def api_status() -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    return {
        "status": "ready" if api_key else "unconfigured",
        "api_key_set": bool(api_key),
        "model": os.environ.get("AMPLIFIER_VOICE_MODEL", "gpt-4o-realtime-preview"),
        "voice": os.environ.get("AMPLIFIER_VOICE_VOICE", "ash"),
        "assistant_name": os.environ.get("AMPLIFIER_VOICE_ASSISTANT_NAME", "Amplifier"),
        # TODO: No TURN server configured. ICE/WebRTC will fail in symmetric NAT
        # environments (some corporate networks, cloud VMs). STUN only for now.
        "turn_server": None,
    }


# ------------------------------------------------------------------
# Signaling routes
# ------------------------------------------------------------------

@router.get("/session", dependencies=[Depends(_require_api_key)])
async def create_session() -> JSONResponse:
    """Create an OpenAI Realtime client secret (GA endpoint)."""
    if is_stub_mode():
        return JSONResponse(content={"value": stub_voice_client_secret()})

    from amplifier_distro.server.apps.voice import realtime
    config = _get_voice_config()
    token = await realtime.create_client_secret(config)
    return JSONResponse(content={"value": token})


@router.post("/sdp")
async def exchange_sdp(request: Request) -> PlainTextResponse | JSONResponse:
    """Forward SDP offer to OpenAI, return SDP answer."""
    if is_stub_mode():
        return PlainTextResponse(content=stub_voice_sdp(), media_type="application/sdp")

    auth_header = request.headers.get("authorization", "")
    offer_body = await request.body()
    if not offer_body:
        return JSONResponse(status_code=400, content={"error": "SDP offer body required"})

    # ephemeral_token is the bearer value from the /session response
    ephemeral_token = auth_header.removeprefix("Bearer ").strip() if auth_header else ""
    vcfg = _get_voice_config()

    from amplifier_distro.server.apps.voice import realtime
    answer = await realtime.exchange_sdp(offer_body.decode("utf-8"), ephemeral_token, vcfg.model)
    return PlainTextResponse(content=answer, media_type="application/sdp")


# ------------------------------------------------------------------
# SSE event stream
# ------------------------------------------------------------------

@router.get("/events", dependencies=[Depends(_check_origin)])
async def events():
    """SSE stream of Amplifier events (from EventStreamingHook queue)."""
    global _active_connection

    async def event_generator():
        if _active_connection is None:
            # No active session — yield a heartbeat every 5s so connection stays alive
            while True:
                yield "data: {\"type\":\"heartbeat\"}\n\n"
                await asyncio.sleep(5)
        else:
            queue = _active_connection.event_queue
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=5.0)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield "data: {\"type\":\"heartbeat\"}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ------------------------------------------------------------------
# Session lifecycle routes
# ------------------------------------------------------------------

@router.post("/sessions", dependencies=[Depends(_require_api_key)])
async def create_voice_session() -> JSONResponse:
    """Create a new voice conversation and Amplifier session."""
    global _active_connection

    from amplifier_distro.server.services import get_services
    services = get_services()
    repo = _get_repository()

    conn = VoiceConnection(repository=repo, backend=services.backend)
    session_id = await conn.create(workspace_root=_workspace_root())
    _active_connection = conn

    # Create VoiceConversation record
    from datetime import datetime
    conv = VoiceConversation(
        id=session_id,
        title="Voice conversation",
        status="active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    repo.create_conversation(conv)

    return JSONResponse(content={"session_id": session_id})


@router.post("/sessions/{session_id}/resume", dependencies=[Depends(_require_api_key)])
async def resume_voice_session(session_id: str) -> JSONResponse:
    """Reconnect path: fresh client secret + context for OpenAI injection."""
    _validate_session_id(session_id)
    global _active_connection

    from amplifier_distro.server.services import get_services
    services = get_services()
    repo = _get_repository()

    # Reconnect the Amplifier session
    await services.backend.reconnect(session_id)

    # Get resumption context (includes tool calls in OpenAI format)
    context = repo.get_resumption_context(session_id)

    # Fresh client secret for new WebRTC connection
    if is_stub_mode():
        token = stub_voice_client_secret()
    else:
        from amplifier_distro.server.apps.voice import realtime
        config = _get_voice_config()
        token = await realtime.create_client_secret(config)

    # Recreate connection object pointing at existing session
    conn = VoiceConnection(repository=repo, backend=services.backend)
    await conn.create(workspace_root=_workspace_root())
    _active_connection = conn

    repo.update_status(session_id, "active")

    return JSONResponse(content={
        "client_secret": token,
        "context_to_inject": context,
    })


@router.post("/sessions/{session_id}/transcript", dependencies=[Depends(_require_api_key)])
async def sync_transcript(session_id: str, body: TranscriptSyncRequest) -> JSONResponse:
    """Batch transcript sync from browser. Does not touch index.json."""
    _validate_session_id(session_id)
    from datetime import datetime
    repo = _get_repository()

    entries = []
    for raw in body.entries:
        entry = TranscriptEntry(
            id=raw.get("id") or new_entry_id(),
            conversation_id=session_id,
            role=raw.get("role", "user"),
            content=raw.get("content", ""),
            created_at=datetime.utcnow(),
            audio_duration_ms=raw.get("audio_duration_ms"),
            item_id=raw.get("item_id"),
            tool_name=raw.get("tool_name"),
            call_id=raw.get("call_id"),
        )
        entries.append(entry)

    repo.add_entries(session_id, entries)
    return JSONResponse(content={"synced": len(entries)})


@router.post("/sessions/{session_id}/end", dependencies=[Depends(_require_api_key)])
async def end_voice_session(session_id: str, body: EndSessionRequest) -> JSONResponse:
    """Permanently end a voice session."""
    _validate_session_id(session_id)
    global _active_connection

    from amplifier_distro.server.services import get_services
    services = get_services()

    await services.backend.end_session(session_id)

    repo = _get_repository()
    repo.end_conversation(session_id, reason=body.reason)

    if _active_connection and _active_connection.session_id == session_id:
        _active_connection = None

    return JSONResponse(content={"ended": True, "reason": body.reason})


@router.get("/sessions", dependencies=[Depends(_require_api_key)])
async def list_sessions() -> JSONResponse:
    """List past voice conversations from index."""
    repo = _get_repository()
    return JSONResponse(content=repo.list_conversations())


# ------------------------------------------------------------------
# Tool execution
# ------------------------------------------------------------------

@router.post("/tools/execute", dependencies=[Depends(_require_api_key)])
async def execute_tool(body: ToolExecuteRequest) -> ToolResult:
    """Execute a tool call from the OpenAI voice model.

    delegate → handle.run(instruction)  [plain string in, plain string out]
    cancel_current_task → backend.cancel_session()
    pause_replies / resume_replies → handled browser-side, should not reach server
    """
    from amplifier_distro.server.services import get_services
    services = get_services()

    if body.tool_name == "delegate":
        instruction = body.arguments.get("instruction", "")
        if not instruction:
            return ToolResult(success=False, error="Missing 'instruction' argument")

        # Get the active session handle
        if _active_connection is None or _active_connection.session_id is None:
            return ToolResult(success=False, error="No active voice session")

        # handle.run() is plain string in, plain string out
        # The bridge handles all session state, context, and provider delegation internally.
        try:
            handle = services.backend._sessions.get(_active_connection.session_id)
            if handle is None:
                return ToolResult(success=False, error="Session handle not found")
            result = await handle.run(instruction)
            return ToolResult(success=True, output=result)
        except Exception as exc:
            logger.exception("delegate tool execution failed")
            return ToolResult(success=False, error=str(exc))

    elif body.tool_name == "cancel_current_task":
        await services.backend.cancel_session(body.session_id, immediate=False)
        return ToolResult(success=True, output="Cancellation requested")

    else:
        return ToolResult(
            success=False,
            error=f"Unknown tool: {body.tool_name}. "
            "pause_replies and resume_replies are handled browser-side.",
        )


# ------------------------------------------------------------------
# Cancellation
# ------------------------------------------------------------------

@router.post("/cancel", dependencies=[Depends(_require_api_key)])
async def cancel_operation(body: CancelRequest) -> JSONResponse:
    """Cancel a running Amplifier operation.

    Single click (immediate=False) → graceful cancel (current tool completes)
    Double click (immediate=True) → hard cancel (interrupt immediately)
    """
    from amplifier_distro.server.services import get_services
    services = get_services()
    await services.backend.cancel_session(body.session_id, immediate=body.immediate)
    return JSONResponse(content={
        "cancelled": True,
        "immediate": body.immediate,
        "session_id": body.session_id,
    })


# ------------------------------------------------------------------
# AppManifest — auto-discovered at server startup
# ------------------------------------------------------------------

manifest = AppManifest(
    name="voice",
    description="Amplifier voice interface via OpenAI Realtime API",
    version="1.0.0",
    router=router,
)
```

**Step 5: Run the route tests**

```bash
uv run python -m pytest tests/test_voice_routes.py -v
```

Expected: Most tests pass. A few may fail if `create_session` signature doesn't match after merge — check error messages and adjust.

**Step 6: Run the full test suite to verify nothing broken**

```bash
uv run python -m pytest tests/ -q --ignore=tests/test_voice.py
```

Expected: No regressions in non-voice tests.

**Step 7: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/__init__.py \
        src/amplifier_distro/server/stub.py \
        tests/test_voice_routes.py
git rm tests/test_voice.py
git commit -m "refactor: replace voice/__init__.py with GA API routes (Phase 4 complete)"
```

---

## PHASE 5 — Frontend (Preact + HTM)

**⚠️ NO AUTOMATED TESTS in this phase.** Each task ends with manual verification instructions. You need real OpenAI credentials and a running server.

Start the server for manual testing:
```bash
uv run amp-distro-server --dev
# Server runs at http://localhost:8100
# Voice app at http://localhost:8100/apps/voice/
```

---

### Task 5.1: Vendor static assets

**Files:**
- Create: `src/amplifier_distro/server/apps/voice/static/` (directory)
- Create: `src/amplifier_distro/server/apps/voice/static/vendor.js`

**Step 1: Create the static directory**

```bash
mkdir -p src/amplifier_distro/server/apps/voice/static
```

**Step 2: Fetch and bundle the vendor libraries**

Run this script to download and bundle all vendor libraries into a single `vendor.js`:

```bash
cd src/amplifier_distro/server/apps/voice/static

# Fetch each library
curl -s https://unpkg.com/preact@10/dist/preact.min.js -o _preact.js
curl -s https://unpkg.com/preact@10/hooks/dist/hooks.module.js -o _hooks.js
curl -s https://cdn.jsdelivr.net/npm/htm@3/dist/htm.module.js -o _htm.js
curl -s https://cdn.jsdelivr.net/npm/marked/marked.min.js -o _marked.js

# Bundle into vendor.js with global exports
cat > vendor.js << 'VENDOREOF'
// vendor.js — Preact 10 + HTM + marked.js bundled for voice app
// Globals: window.preact, window.preactHooks, window.html, window.marked
// No Node or build step required.
VENDOREOF

cat _preact.js >> vendor.js
echo "" >> vendor.js
echo "window.preact = exports;" >> vendor.js
echo "" >> vendor.js
cat _marked.js >> vendor.js
echo "" >> vendor.js
echo "window.marked = marked;" >> vendor.js
echo "" >> vendor.js

# Cleanup temp files
rm -f _preact.js _hooks.js _htm.js _marked.js
```

> **Note:** The above is a simplified bundling approach. For a proper bundle with correct ES module interop, check `feat/chat-app`'s `static/vendor.js` and use the same approach. The critical requirement is that `window.preact` exposes `{h, Component, render, createContext, createRef, Fragment}`, `window.preactHooks` exposes all hooks, `window.html` is HTM bound to h, and `window.marked` is the marked.js parser.

**Manual verification:**

```bash
# Start server
uv run amp-distro-server --dev &

# Check vendor.js is served
curl -I http://localhost:8100/apps/voice/static/vendor.js
# Expected: HTTP/1.1 200 OK, Content-Type: application/javascript
```

**Step 3: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/static/vendor.js
git commit -m "feat: add voice app vendor.js (Preact 10 + HTM + marked)"
```

---

### Task 5.2: index.html — Shell + useWebRTC hook

**Files:**
- Create: `src/amplifier_distro/server/apps/voice/static/index.html`

**Step 1: Create the HTML shell with useWebRTC**

Create `src/amplifier_distro/server/apps/voice/static/index.html` with this content:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Amplifier Voice</title>
  <script src="/apps/voice/static/vendor.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #1a1a1a; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }
    #app { display: flex; flex-direction: column; height: 100%; max-width: 900px; margin: 0 auto; width: 100%; padding: 1rem; }
    .status-header { display: flex; gap: 0.5rem; padding: 0.5rem 0; border-bottom: 1px solid #333; margin-bottom: 1rem; }
    .badge { padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: bold; }
    .badge.connected { background: #1a4731; color: #4ade80; }
    .badge.disconnected { background: #3f1a1a; color: #f87171; }
    .transcript { flex: 1; overflow-y: auto; padding: 1rem 0; display: flex; flex-direction: column; gap: 0.5rem; }
    .bubble { padding: 0.75rem 1rem; border-radius: 12px; max-width: 80%; }
    .bubble.user { background: #2a3a5c; align-self: flex-end; }
    .bubble.assistant { background: #2a2a2a; align-self: flex-start; }
    .controls { display: flex; gap: 0.5rem; padding: 1rem 0; border-top: 1px solid #333; }
    button { padding: 0.5rem 1rem; border-radius: 6px; border: none; cursor: pointer; font-size: 0.9rem; }
    button.primary { background: #4f46e5; color: white; }
    button.danger { background: #dc2626; color: white; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    .error-banner { background: #3f1a1a; border: 1px solid #dc2626; border-radius: 6px; padding: 0.75rem; margin-bottom: 0.5rem; }
  </style>
</head>
<body>
<div id="app"></div>
<script>
const { h, render, createContext } = window.preact;
const { useState, useEffect, useRef, useReducer, useCallback } = window.preactHooks;
const html = window.html;

// ----------------------------------------------------------------
// useWebRTC — RTCPeerConnection lifecycle, data channel, SDP exchange
// ----------------------------------------------------------------
function useWebRTC({ onMessage, onStateChange }) {
  const [rtcState, setRtcState] = useState("idle"); // idle | connecting | connected | disconnected
  const pcRef = useRef(null);
  const dcRef = useRef(null);

  const connect = useCallback(async () => {
    setRtcState("connecting");
    onStateChange("connecting");

    // Get ephemeral token from server
    const sessionResp = await fetch("/apps/voice/session");
    if (!sessionResp.ok) throw new Error("Failed to get client secret");
    const { value: ephemeralToken } = await sessionResp.json();

    // Create peer connection (Google STUN only — no TURN)
    const pc = new RTCPeerConnection({
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
    });
    pcRef.current = pc;

    // Add microphone track
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach(track => pc.addTrack(track, stream));

    // Remote audio output
    pc.ontrack = (e) => {
      const audio = document.createElement("audio");
      audio.srcObject = e.streams[0];
      audio.autoplay = true;
      document.body.appendChild(audio);
    };

    // Data channel for events
    const dc = pc.createDataChannel("oai-events");
    dcRef.current = dc;

    dc.onopen = () => {
      // Stage 1: server_vad + noise reduction + transcription (immediately)
      dc.send(JSON.stringify({
        type: "session.update",
        session: { audio: { input: {
          turn_detection: { type: "server_vad", threshold: 0.5, prefix_padding_ms: 300, silence_duration_ms: 500 },
          noise_reduction: { type: "near_field" },
          transcription: { model: "gpt-4o-transcribe", language: "en" }
        }}}
      }));
      // Stage 2: semantic_vad (100ms delay — GA API constraint: can't be initial type)
      setTimeout(() => {
        dc.send(JSON.stringify({
          type: "session.update",
          session: { audio: { input: {
            turn_detection: { type: "semantic_vad", eagerness: "low", create_response: false, interrupt_response: true }
          }}}
        }));
      }, 100);
    };

    dc.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        onMessage(event);
      } catch {}
    };

    pc.oniceconnectionstatechange = () => {
      if (pc.iceConnectionState === "connected" || pc.iceConnectionState === "completed") {
        setRtcState("connected");
        onStateChange("connected");
      } else if (["disconnected", "failed", "closed"].includes(pc.iceConnectionState)) {
        setRtcState("disconnected");
        onStateChange("disconnected");
      }
    };

    // SDP exchange — wait for ICE gathering (max 2s)
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await new Promise(resolve => {
      if (pc.iceGatheringState === "complete") { resolve(); return; }
      const timer = setTimeout(resolve, 2000);
      pc.onicegatheringstatechange = () => {
        if (pc.iceGatheringState === "complete") { clearTimeout(timer); resolve(); }
      };
    });

    const sdpResp = await fetch("/apps/voice/sdp", {
      method: "POST",
      body: pc.localDescription.sdp,
      headers: { Authorization: `Bearer ${ephemeralToken}`, "Content-Type": "application/sdp" }
    });
    if (!sdpResp.ok) throw new Error("SDP exchange failed");
    const answerSdp = await sdpResp.text();
    await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
  }, [onMessage, onStateChange]);

  const disconnect = useCallback(() => {
    if (dcRef.current) { dcRef.current.close(); dcRef.current = null; }
    if (pcRef.current) { pcRef.current.close(); pcRef.current = null; }
    setRtcState("idle");
    onStateChange("idle");
  }, [onStateChange]);

  const sendDataChannelMessage = useCallback((msg) => {
    if (dcRef.current && dcRef.current.readyState === "open") {
      dcRef.current.send(JSON.stringify(msg));
    }
  }, []);

  return { rtcState, connect, disconnect, sendDataChannelMessage, dcRef };
}

// ----------------------------------------------------------------
// VoiceApp — root component
// ----------------------------------------------------------------
function VoiceApp() {
  const [rtcState, setRtcState] = useState("idle");
  const [messages, setMessages] = useState([]);
  const [error, setError] = useState(null);
  const currentAssistantRef = useRef(null);

  const handleRtcMessage = useCallback((event) => {
    // TODO Phase 5.3: route events to useChatMessages
    console.debug("[RTC]", event.type, event);
  }, []);

  const { connect, disconnect, sendDataChannelMessage } = useWebRTC({
    onMessage: handleRtcMessage,
    onStateChange: setRtcState,
  });

  const handleConnect = async () => {
    try {
      setError(null);
      // Create backend session first
      const resp = await fetch("/apps/voice/sessions", { method: "POST" });
      if (!resp.ok) throw new Error("Failed to create session");
      await connect();
    } catch (err) {
      setError(err.message);
    }
  };

  const isConnected = rtcState === "connected";

  return html`
    <div id="app">
      ${error && html`<div class="error-banner">⚠️ ${error}</div>`}
      <div class="status-header">
        <span class=${"badge " + (isConnected ? "connected" : "disconnected")}>
          ${isConnected ? "🎙️ Connected" : "⚫ Disconnected"}
        </span>
      </div>
      <div class="transcript">
        ${messages.map(m => html`
          <div key=${m.id} class=${"bubble " + m.role}>
            ${m.content}
          </div>
        `)}
      </div>
      <div class="controls">
        ${!isConnected
          ? html`<button class="primary" onClick=${handleConnect}>Start Voice Chat</button>`
          : html`<button class="danger" onClick=${disconnect}>Disconnect</button>`
        }
      </div>
    </div>
  `;
}

render(h(VoiceApp, null), document.getElementById("app"));
</script>
</body>
</html>
```

**Manual verification:**

1. Start server: `uv run amp-distro-server`
2. Open `http://localhost:8100/apps/voice/`
3. Click "Start Voice Chat"
4. Browser requests microphone access — grant it
5. WebRTC should connect (status badge turns green)
6. Speak something — you should hear a response via audio

**Step 2: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/static/index.html
git commit -m "feat: add voice frontend shell with useWebRTC hook and two-stage VAD"
```

---

### Task 5.3: useChatMessages + tool calling loop

**File:**
- Modify: `src/amplifier_distro/server/apps/voice/static/index.html`

**Step 1: Add useChatMessages hook**

Add this hook before `VoiceApp` in `index.html`:

```javascript
// ----------------------------------------------------------------
// useChatMessages — transcript state + tool calling loop
// ----------------------------------------------------------------
function useChatMessages({ sendDataChannelMessage, sessionId }) {
  const [messages, setMessages] = useState([]);
  const [responseInProgress, setResponseInProgress] = useState(false);
  const pendingAnnouncements = useRef([]);
  const messageRefs = useRef({});  // id -> DOM node for direct mutation during streaming
  const currentStreamingId = useRef(null);

  const addUserMessage = useCallback((transcript, itemId) => {
    const id = itemId || Date.now().toString();
    setMessages(prev => [...prev, { id, role: "user", content: transcript }]);
    return id;
  }, []);

  const startAssistantMessage = useCallback(() => {
    const id = Date.now().toString();
    currentStreamingId.current = id;
    setMessages(prev => [...prev, { id, role: "assistant", content: "" }]);
    return id;
  }, []);

  const handleDataChannelEvent = useCallback(async (event) => {
    switch (event.type) {
      case "input_audio_buffer.speech_started":
        // User started speaking — nothing to do yet
        break;

      case "conversation.item.input_audio_transcription.completed":
        addUserMessage(event.transcript, event.item_id);
        // Manual response gate: semantic_vad has create_response: false
        // so we must explicitly send response.create
        if (!responseInProgress) {
          sendDataChannelMessage({ type: "response.create" });
        }
        break;

      case "response.audio_transcript.delta":
        // Direct DOM mutation — zero Preact rerenders during streaming
        if (currentStreamingId.current) {
          const node = messageRefs.current[currentStreamingId.current];
          if (node) node.textContent += event.delta;
        }
        break;

      case "response.audio_transcript.done":
        // Finalize: state update triggers rerender with complete transcript
        if (currentStreamingId.current) {
          const id = currentStreamingId.current;
          setMessages(prev => prev.map(m =>
            m.id === id ? { ...m, content: event.transcript } : m
          ));
          currentStreamingId.current = null;
        }
        break;

      case "response.created":
        setResponseInProgress(true);
        startAssistantMessage();
        break;

      case "response.done":
        setResponseInProgress(false);
        // Flush pending tool announcements
        if (pendingAnnouncements.current.length > 0) {
          const pending = pendingAnnouncements.current.splice(0);
          // Voice model needs response.create to announce tool results
          sendDataChannelMessage({ type: "response.create" });
        }
        break;

      case "response.output_item.added":
        if (event.item?.type === "function_call") {
          const { name, arguments: args, call_id } = event.item;
          // Browser-side voice controls — no server round-trip
          if (name === "pause_replies" || name === "resume_replies") {
            // TODO Phase 5.4: handleVoiceControl(name)
            return;
          }
          // Server-side tool execution
          try {
            const result = await fetch("/apps/voice/tools/execute", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                tool_name: name,
                arguments: JSON.parse(args || "{}"),
                call_id,
                session_id: sessionId,
              }),
            }).then(r => r.json());

            // Send tool result back to OpenAI data channel
            sendDataChannelMessage({
              type: "conversation.item.create",
              item: {
                type: "function_call_output",
                call_id,
                output: result.output || result.error || "",
              },
            });

            // Queue response.create if a response is already in progress
            if (!responseInProgress) {
              sendDataChannelMessage({ type: "response.create" });
            } else {
              pendingAnnouncements.current.push({ call_id, name });
            }
          } catch (err) {
            console.error("Tool execution failed:", err);
          }
        }
        break;
    }
  }, [responseInProgress, sendDataChannelMessage, sessionId, addUserMessage, startAssistantMessage]);

  return { messages, messageRefs, handleDataChannelEvent };
}
```

Wire this into `VoiceApp` — replace the `handleRtcMessage` callback:

```javascript
const [sessionId, setSessionId] = useState(null);
const { messages, messageRefs, handleDataChannelEvent } = useChatMessages({
  sendDataChannelMessage,
  sessionId,
});

const handleRtcMessage = useCallback((event) => {
  handleDataChannelEvent(event);
}, [handleDataChannelEvent]);
```

Update the transcript render to use `messageRefs` for streaming:

```javascript
${messages.map(m => html`
  <div key=${m.id} class=${"bubble " + m.role}
       ref=${node => { if (node) messageRefs.current[m.id] = node; }}>
    ${m.content}
  </div>
`)}
```

**Manual verification:**

1. Connect voice chat
2. Say "Hello, how are you?"
3. Response streams in real-time in the transcript panel
4. Say "delegate a task to list the files in the current directory"
5. Tool call fires — transcript shows delegating, result spoken back

**Step 2: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/static/index.html
git commit -m "feat: add useChatMessages with streaming and async tool calling loop"
```

---

### Task 5.4: useMicrophoneControl + useVoiceKeywords

**File:**
- Modify: `src/amplifier_distro/server/apps/voice/static/index.html`

**Step 1: Fetch assistant name from /api/status**

In `VoiceApp`, add:

```javascript
const [assistantName, setAssistantName] = useState("Amplifier");
useEffect(() => {
  fetch("/apps/voice/api/status")
    .then(r => r.json())
    .then(d => setAssistantName(d.assistant_name || "Amplifier"))
    .catch(() => {});
}, []);
```

**Step 2: Add useMicrophoneControl hook**

```javascript
function useMicrophoneControl({ sendDataChannelMessage }) {
  const [muted, setMuted] = useState(false);
  const [pauseReplies, setPauseReplies] = useState(false);
  const streamRef = useRef(null);

  const setMicStream = useCallback((stream) => { streamRef.current = stream; }, []);

  const toggleMute = useCallback(() => {
    setMuted(prev => {
      const next = !prev;
      if (streamRef.current) {
        streamRef.current.getAudioTracks().forEach(t => { t.enabled = !next; });
      }
      return next;
    });
  }, []);

  const enterPauseReplies = useCallback(() => {
    setPauseReplies(true);
    // Tell model not to auto-respond
    sendDataChannelMessage({
      type: "session.update",
      session: { audio: { input: { turn_detection: { create_response: false } } } }
    });
  }, [sendDataChannelMessage]);

  const exitPauseReplies = useCallback(() => {
    setPauseReplies(false);
    sendDataChannelMessage({
      type: "session.update",
      session: { audio: { input: { turn_detection: { create_response: false } } } }
    });
  }, [sendDataChannelMessage]);

  return { muted, pauseReplies, toggleMute, enterPauseReplies, exitPauseReplies, setMicStream };
}
```

**Step 3: Add useVoiceKeywords hook**

```javascript
function useVoiceKeywords({ assistantName, onTriggerResponse, onPauseReplies, onResumeReplies, onMute, onUnmute }) {
  const lastFiredRef = useRef(0);
  const DEBOUNCE_MS = 2000;

  const checkTranscript = useCallback((transcript) => {
    const now = Date.now();
    if (now - lastFiredRef.current < DEBOUNCE_MS) return;

    const lower = transcript.toLowerCase();
    const wake = `hey ${assistantName.toLowerCase()}`;

    // Fuzzy match: direct substring OR words in sequence
    const hasWake = lower.includes(wake);
    if (!hasWake) return;

    const matchCmd = (cmd) => lower.includes(cmd);

    if (matchCmd("go ahead") || matchCmd("your turn")) {
      lastFiredRef.current = now;
      onTriggerResponse();
    } else if (matchCmd("pause replies")) {
      lastFiredRef.current = now;
      onPauseReplies();
    } else if (matchCmd("resume")) {
      lastFiredRef.current = now;
      onResumeReplies();
    } else if (matchCmd("mute")) {
      lastFiredRef.current = now;
      onMute();
    } else if (matchCmd("unmute")) {
      lastFiredRef.current = now;
      onUnmute();
    }
  }, [assistantName, onTriggerResponse, onPauseReplies, onResumeReplies, onMute, onUnmute]);

  return { checkTranscript };
}
```

Wire `checkTranscript` into `handleDataChannelEvent` in `useChatMessages` — call it for `conversation.item.input_audio_transcription.completed` events before deciding to auto-respond.

**Manual verification:**

1. Connect voice chat
2. Say "Hey Amplifier, pause replies"
3. UI shows paused state indicator
4. Say "Hey Amplifier, resume"
5. UI returns to normal, assistant auto-responds again
6. Say "Hey Amplifier, mute" — microphone mutes

**Step 4: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/static/index.html
git commit -m "feat: add useMicrophoneControl and useVoiceKeywords with wake word detection"
```

---

### Task 5.5: useConnectionHealth + ConnectionHealthPanel

**File:**
- Modify: `src/amplifier_distro/server/apps/voice/static/index.html`

**Step 1: Add ConnectionHealthManager class**

```javascript
// Pure logic, no UI concerns. Instantiated once and passed to useConnectionHealth.
class ConnectionHealthManager {
  constructor() {
    this.sessionStart = null;
    this.lastEventTime = null;
    this.lastSpeechTime = null;
    this.disconnectHistory = [];
    this.reconnectCount = 0;
    this.strategy = "manual"; // manual | auto_immediate | auto_delayed | proactive
  }

  recordEvent() { this.lastEventTime = Date.now(); }
  recordSpeech() { this.lastSpeechTime = Date.now(); this.recordEvent(); }
  startSession() { this.sessionStart = Date.now(); this.lastEventTime = Date.now(); }

  getStatus() {
    const now = Date.now();
    const sessionAge = this.sessionStart ? (now - this.sessionStart) / 1000 : 0;
    const timeSinceEvent = this.lastEventTime ? (now - this.lastEventTime) / 1000 : null;
    const timeSinceSpeech = this.lastSpeechTime ? (now - this.lastSpeechTime) / 1000 : null;

    const warnings = [];
    if (timeSinceEvent !== null && timeSinceEvent > 30) warnings.push("stale");
    if (timeSinceSpeech !== null && timeSinceSpeech > 120) warnings.push("idle");
    if (sessionAge > 55 * 60) warnings.push("session_limit");

    return { sessionAge, timeSinceEvent, timeSinceSpeech, warnings, reconnectCount: this.reconnectCount };
  }

  inferDisconnectReason(sessionAge) {
    if (sessionAge >= 58 * 60) return "session_limit";
    if (this.lastSpeechTime && (Date.now() - this.lastSpeechTime) > 120000) return "idle_timeout";
    return "network_error";
  }
}
```

**Step 2: Add useConnectionHealth hook**

```javascript
function useConnectionHealth({ manager, onProactiveReconnect }) {
  const [status, setStatus] = useState({ sessionAge: 0, warnings: [] });

  useEffect(() => {
    const interval = setInterval(() => {
      const s = manager.getStatus();
      setStatus(s);
      if (s.warnings.includes("session_limit") && manager.strategy === "proactive") {
        onProactiveReconnect();
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [manager, onProactiveReconnect]);

  return status;
}
```

**Step 3: Add ConnectionHealthPanel component**

```javascript
function ConnectionHealthPanel({ status, strategy, onStrategyChange }) {
  const [collapsed, setCollapsed] = useState(true);
  const formatDuration = (s) => {
    if (!s) return "0s";
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
  };

  return html`
    <div style="border: 1px solid #333; border-radius: 6px; padding: 0.5rem; font-size: 0.75rem;">
      <div style="display:flex; justify-content:space-between; cursor:pointer;"
           onClick=${() => setCollapsed(c => !c)}>
        <span>🩺 Connection Health ${status.warnings.length > 0 ? "⚠️" : "✅"}</span>
        <span>${collapsed ? "▼" : "▲"}</span>
      </div>
      ${!collapsed && html`
        <div style="margin-top: 0.5rem; display: grid; gap: 0.25rem;">
          <div>Session age: ${formatDuration(status.sessionAge)}</div>
          <div>Last event: ${status.timeSinceEvent != null ? formatDuration(status.timeSinceEvent) + " ago" : "never"}</div>
          <div>Reconnects: ${status.reconnectCount}</div>
          ${status.warnings.map(w => html`<div style="color:#f87171;">⚠️ ${w}</div>`)}
          <label>Strategy:
            <select value=${strategy} onChange=${e => onStrategyChange(e.target.value)}
                    style="margin-left:0.5rem; background:#333; color:#e0e0e0; border:none; padding:0.25rem;">
              <option value="manual">Manual</option>
              <option value="auto_immediate">Auto immediate</option>
              <option value="auto_delayed">Auto delayed (3s)</option>
              <option value="proactive">Proactive (55min)</option>
            </select>
          </label>
        </div>
      `}
    </div>
  `;
}
```

**Manual verification:**

1. Connect voice chat
2. `ConnectionHealthPanel` appears at bottom — shows session duration incrementing every 5s
3. Click panel header to expand/collapse
4. Change strategy dropdown — updates without reload

**Step 4: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/static/index.html
git commit -m "feat: add useConnectionHealth and ConnectionHealthPanel"
```

---

### Task 5.6: Complete UI — SessionPicker, StopButton, MicrophoneControls, useAmplifierEvents

**File:**
- Modify: `src/amplifier_distro/server/apps/voice/static/index.html`

**Step 1: Add useAmplifierEvents (SSE consumer)**

```javascript
function useAmplifierEvents({ onEvent }) {
  useEffect(() => {
    const es = new EventSource("/apps/voice/events");
    const ICONS = {
      provider_request: "🔼",
      provider_response: "🔽",
      tool_call: "🔧",
      tool_result: "🔧",
      tool_error: "❌",
      session_fork: "🔀",
      cancel_requested: "🛑",
      cancel_completed: "✅",
    };
    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type !== "heartbeat") {
          const icon = ICONS[msg.type] || "📡";
          console.log(`${icon} [${msg.type}]`, msg);
          onEvent(msg);
        }
      } catch {}
    };
    return () => es.close();
  }, [onEvent]);
}
```

**Step 2: Add SessionPicker component**

```javascript
function SessionPicker({ onResume }) {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/apps/voice/sessions")
      .then(r => r.json())
      .then(setSessions)
      .catch(() => setSessions([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return html`<div>Loading sessions...</div>`;
  if (sessions.length === 0) return null;

  return html`
    <div style="margin-bottom: 1rem;">
      <h3 style="font-size: 0.85rem; color: #999; margin-bottom: 0.5rem;">Recent Sessions</h3>
      ${sessions.slice(0, 5).map(s => html`
        <div key=${s.id} style="display:flex; justify-content:space-between; align-items:center;
             padding: 0.5rem; border: 1px solid #333; border-radius: 6px; margin-bottom: 0.25rem;">
          <div>
            <div style="font-size: 0.85rem;">${s.title || "Untitled"}</div>
            <div style="font-size: 0.7rem; color: #666;">${s.status} · ${new Date(s.created_at).toLocaleDateString()}</div>
          </div>
          ${s.status !== "ended" && html`
            <button onClick=${() => onResume(s.id)} style="font-size: 0.75rem; padding: 0.25rem 0.5rem; background: #4f46e5; color: white; border: none; border-radius: 4px; cursor: pointer;">
              Resume
            </button>
          `}
        </div>
      `)}
    </div>
  `;
}
```

**Step 3: Add StopButton component**

```javascript
function StopButton({ sessionId, runningTools, onStop }) {
  const [stopping, setStopping] = useState(false);
  const clickTimeRef = useRef(0);

  const handleClick = async () => {
    const now = Date.now();
    const isDoubleClick = now - clickTimeRef.current < 400;
    clickTimeRef.current = now;

    setStopping(true);
    await fetch("/apps/voice/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, immediate: isDoubleClick }),
    });
  };

  // Reset stopping state when cancel_completed SSE arrives (via onStop callback)
  const label = stopping
    ? "Stopping..."
    : runningTools.length > 0
    ? `Stop (${runningTools[0]})`
    : "Stop";

  return html`
    <button class="danger" disabled=${!sessionId} onClick=${handleClick}>
      ${label}
    </button>
  `;
}
```

**Step 4: Add MicrophoneControls component**

```javascript
function MicrophoneControls({ muted, pauseReplies, onToggleMute, onPauseReplies, onResumeReplies }) {
  return html`
    <div style="display: flex; gap: 0.5rem; align-items: center;">
      <button onClick=${onToggleMute}
              style=${"padding: 0.5rem; border-radius: 6px; border: none; cursor: pointer; "
                + (muted ? "background: #dc2626; color: white;" : "background: #333; color: #e0e0e0;")}>
        ${muted ? "🔇 Muted" : "🎙️ Mic"}
      </button>
      <button onClick=${pauseReplies ? onResumeReplies : onPauseReplies}
              style=${"padding: 0.5rem; border-radius: 6px; border: none; cursor: pointer; "
                + (pauseReplies ? "background: #854d0e; color: white;" : "background: #333; color: #e0e0e0;")}>
        ${pauseReplies ? "▶️ Resume" : "⏸️ Pause"}
      </button>
    </div>
  `;
}
```

**Step 5: Add sendBeacon on page unload**

In `VoiceApp`, add this effect (replace `sessionId` and `pendingEntries` with actual state refs):

```javascript
useEffect(() => {
  const handleUnload = () => {
    if (sessionId) {
      navigator.sendBeacon(
        `/apps/voice/sessions/${sessionId}/transcript`,
        JSON.stringify({ entries: [] })  // flush any pending entries
      );
    }
  };
  window.addEventListener("beforeunload", handleUnload);
  return () => window.removeEventListener("beforeunload", handleUnload);
}, [sessionId]);
```

**Manual verification:**

1. Connect voice chat
2. `SessionPicker` shows past sessions if any exist
3. Click Resume on a past session — context injects and new WebRTC connects
4. While a `delegate` task is running, `StopButton` shows the tool name
5. Single click Stop — graceful cancel (current tool finishes)
6. Double-click Stop — immediate cancel
7. `MicrophoneControls` mute/pause work correctly
8. Browser console shows color-coded Amplifier event log (🔧 🔼 🔽 🔀)
9. Refresh page mid-conversation — transcript preserved in `/sessions`

**Step 6: Commit**

```bash
git add src/amplifier_distro/server/apps/voice/static/index.html
git commit -m "feat: add complete voice UI (SessionPicker, StopButton, MicrophoneControls, SSE events)"
```

---

## Post-Implementation

**Run the full test suite one final time:**

```bash
uv run python -m pytest tests/ -q
```

Expected: All tests pass. No warnings about deprecated APIs.

**Run code quality check on new Python files:**

```bash
uv run python -m ruff check src/amplifier_distro/server/apps/voice/ tests/test_voice_*.py
uv run python -m pyright src/amplifier_distro/server/apps/voice/
```

Fix any issues before marking the branch complete.

**Final summary commit:**

```bash
git commit --allow-empty -m "feat: voice app full overhaul complete (Phases 1-5)"
```

---

## Test File Reference

| Test file | Tests |
|---|---|
| `tests/test_voice_settings.py` | VoiceSettings.assistant_name, export_to_env |
| `tests/test_voice_realtime.py` | create_client_secret payload/response, exchange_sdp auth |
| `tests/test_voice_transcript.py` | VoiceConversation, TranscriptEntry, VoiceConversationRepository |
| `tests/test_voice_protocols.py` | EventStreamingHook, VoiceDisplaySystem, VoiceApprovalSystem |
| `tests/test_voice_translator.py` | VoiceEventTranslator (10 table-driven cases) |
| `tests/test_voice_connection.py` | VoiceConnection lifecycle with MockBackend |
| `tests/test_voice_routes.py` | All HTTP routes, auth, CSRF, session ID validation, stub mode |
