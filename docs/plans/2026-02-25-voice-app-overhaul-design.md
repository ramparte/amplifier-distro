# Voice App Full Overhaul Design

## Goal

Replace the current `__init__.py` monolith with a full-capability voice app that is a proper peer to the chat app in the distro — bringing in deep Amplifier session integration, semantic VAD with manual response gating, working tool calling, session persistence and resumption, connection health monitoring, and a two-level cancellation system.

## Background

The existing voice app at `server/apps/voice/__init__.py` is a thin (~490 line) WebRTC broker built against the OpenAI Realtime API beta. It works as a signaling layer — the backend brokers session token creation and SDP exchange, audio flows browser ↔ OpenAI — but it has several critical deficiencies:

- **Tool calling is dead code.** `AMPLIFIER_TOOLS` are advertised to OpenAI when `tools_enabled=True`, but the browser JavaScript has no handler for `response.function_call` events. No tools actually execute.
- **Beta API.** The GA OpenAI Realtime API uses different endpoints (`/client_secrets`, `/calls`) and a different session structure. There are no backward compatibility requirements; we build on GA only.
- **No session persistence.** Voice conversations are invisible to the rest of the system. Transcripts are lost on disconnect. There is no resumption path.
- **Semantic VAD absent.** The current frontend sets `server_vad` and leaves it there. The model interrupts on any background audio. The manual response gate (`create_response: false`) that prevents noise-triggered responses is not implemented.
- **No connection health monitoring.** OpenAI Realtime sessions have a hard 60-minute limit. There is no proactive handling of this or any other disconnect scenario.
- **No cancellation.** There is no way to stop a running Amplifier operation from the voice interface.

**Reference materials used in this design:**

| Repo | Role |
|---|---|
| `amplifier-voice` at `../amplifier-voice` | Capability reference — full feature set to adapt |
| `feat/chat-app` branch | Structural reference — the distro pattern being established by Samuel |
| `SESSION-ARCHITECTURE-NOTES.md` | Session architecture constraints — must use shared `FoundationBackend` via `get_services()` |

## Approach

**Full overhaul.** Maximum fidelity port of `amplifier-voice` adapted to distro conventions. The app may graduate out of distro at some point and should be built to stand on its own. No simplification for the sake of fitting a smaller footprint.

`amplifier-voice` is the **capability reference**: semantic VAD, async tool queuing, session persistence and resumption, connection health, two-level cancellation, voice keyword detection, TTS-optimised display.

`feat/chat-app` is the **structural reference**: `AppManifest` registration, `get_services()` for the shared backend, `_require_api_key` auth pattern, explicit static file routes (no `StaticFiles` mount), Preact + HTM with a committed `vendor.js` (no Node, no build step).

The key architectural departure from `amplifier-voice` is session identity. `amplifier-voice` creates its own session UUID and maintains a mapping to Amplifier sessions. The distro's `SESSION-ARCHITECTURE-NOTES.md` is explicit: always use the shared `FoundationBackend` via `get_services()`, never create a standalone bridge. We therefore use the **Amplifier session ID as the primary key everywhere** — no parallel session world, no mapping table.

## Architecture

The voice app is a multi-file Python module registered as an `AppManifest`, auto-discovered at startup and mounted at `/apps/voice/`. It runs three transport protocols simultaneously:

- **HTTP (REST):** Signaling (`/session`, `/sdp`), session lifecycle (`/sessions/*`), tool execution (`/tools/execute`), cancellation (`/cancel`), status (`/api/status`).
- **SSE:** Amplifier event stream (`/events`) — Amplifier events translated to browser-consumable JSON by `EventStreamingHook`.
- **WebRTC (via OpenAI):** Audio flows browser ↔ OpenAI directly. The backend never touches audio.

The **Amplifier session** (managed by `services.backend`) is the single source of truth for agent execution context, tool call history, and cross-surface continuity. The **`VoiceConversation`** record is a surface overlay stored at `~/.amplifier/voice-sessions/{amplifier_session_id}/` — it tracks voice-specific data the shared system cannot: audio durations, OpenAI disconnect metadata, the speech transcript for the UI, and formatted context for OpenAI Realtime injection on resumption.

Cross-surface continuity follows naturally from this identity model. A chat session resumed in voice creates a `VoiceConversation` for the existing `amplifier_session_id` and injects prior context into OpenAI Realtime. A voice session resumed in chat opens a WebSocket to the existing Amplifier session — no migration needed.

Session visibility requires no additional registry. Voice sessions created through `services.backend.create_session()` are automatically visible in `/api/sessions` via the shared `FoundationBackend` — that is sufficient. No further registry integration is planned.

## Components

**File structure:**

```
server/apps/voice/
├── __init__.py          # routes + AppManifest — thin handlers only, no API call logic
├── realtime.py          # NEW: GA API client — client_secrets + calls endpoints isolated here
├── connection.py        # VoiceConnection — per-conversation lifecycle manager
├── translator.py        # VoiceEventTranslator — OpenAI ↔ browser event translation
├── protocols/
│   ├── event_streaming.py   # EventStreamingHook
│   ├── voice_display.py     # VoiceDisplaySystem
│   └── voice_approval.py    # VoiceApprovalSystem
├── transcript/
│   ├── models.py            # VoiceConversation, TranscriptEntry
│   └── repository.py        # VoiceConversationRepository
└── static/
    ├── index.html
    └── vendor.js
```

---

### `__init__.py` — Routes & AppManifest

Registers the app via `AppManifest`. Owns all HTTP routes and the SSE endpoint. Thin handlers only — no OpenAI API call logic. Delegates to `realtime.py` for all GA API calls, `VoiceConnection` for session lifecycle, and `VoiceConversationRepository` for persistence.

**Routes:**

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | No | Serves `static/index.html` |
| `GET` | `/static/vendor.js` | No | Serves vendored Preact + HTM |
| `GET` | `/api/status` | No | App health, settings, model info |
| `GET` | `/session` | Yes | Creates OpenAI Realtime client secret |
| `POST` | `/sdp` | No | Forwards SDP offer to OpenAI, returns answer |
| `GET` | `/events` | No | SSE stream — drains `EventStreamingHook` queue |
| `POST` | `/sessions` | Yes | Creates voice conversation record |
| `POST` | `/sessions/{id}/resume` | Yes | Reconnect path: fresh secret + context |
| `POST` | `/sessions/{id}/transcript` | Yes | Batch transcript sync from browser |
| `POST` | `/sessions/{id}/end` | Yes | Explicit end (or 60-min limit) |
| `GET` | `/sessions` | Yes | List past conversations |
| `POST` | `/tools/execute` | Yes | Execute a tool call from the voice model |
| `POST` | `/cancel` | Yes | Cancel running Amplifier operations |

Auth follows `feat/chat-app` exactly: `_require_api_key` reads `config.server.api_key`. When unset, auth is skipped entirely — zero friction for personal use, secure when deployed.

Static file serving uses two explicit route handlers returning file content directly. No `StaticFiles` mount. 404 fallbacks for missing files so tests don't break.

---

---

### `realtime.py` — GA API Client

Isolates all OpenAI GA Realtime API calls from the route handlers. Route handlers in `__init__.py` call these functions and return the results — no OpenAI API logic lives in the routes themselves. This matches the `amplifier-voice/voice_server/realtime.py` pattern and keeps the stub extension clean for CI (`stub.py` mocks these two functions, not the route handlers).

**Two exported functions:**

```python
async def create_client_secret(config: VoiceConfig) -> str:
    """POSTs to /v1/realtime/client_secrets. Returns the ephemeral token value (str)."""

async def exchange_sdp(sdp_offer: str, ephemeral_token: str, model: str) -> str:
    """POSTs to /v1/realtime/calls. Returns the SDP answer string."""
```

`create_client_secret` constructs the session payload (model, instructions, tools, VAD config) and POSTs it to `/v1/realtime/client_secrets`, returning only the `client_secret.value` string. `exchange_sdp` forwards the browser's SDP offer to `/v1/realtime/calls` using the ephemeral token as the bearer credential and returns the SDP answer.

---

### `connection.py` — VoiceConnection

Per-conversation WebRTC lifecycle manager. One instance per active voice conversation. Owns the `EventStreamingHook` queue wired to `services.backend.create_session()`. Manages the Amplifier session lifecycle: `create_session()` → `mark_disconnected()` → `reconnect()` → `end_session()`.

Tracks active child sessions (delegate calls) for the `StopButton` display. Cancellation routes through `backend.cancel_session()`.

#### Spawn Capability (Protocol Boundary Point 4)

After `services.backend.create_session()` returns, the spawn capability must be registered on the session's coordinator before the first `session.execute()` call. This is how the Amplifier orchestrator knows to route `delegate` tool sub-session creation through the shared `FoundationBackend` — without it, delegate calls silently fail or spawn sessions outside the shared backend entirely.

```python
async def _spawn_child_session(config: dict) -> AmplifierSession:
    """Routes delegate tool sub-session creation through shared backend."""
    child_info = await services.backend.create_session(
        app_name="voice",
        working_dir=config.get("cwd", workspace_root),
        event_queue=self._event_queue,  # child events flow to same SSE stream
    )
    return child_info.session

session.coordinator.register_capability("spawn", _spawn_child_session)
```

**Why this is critical:** The voice model's primary tool is `delegate` — all heavy work (file ops, web search, code execution) routes through Amplifier specialist agents. Without the spawn capability registered, delegate calls silently fail or bypass the shared backend entirely: no hooks, no observability, no session tracking. This is the mechanism that makes `delegate` work in the distro context.

**Failure mode without it:** `delegate` tool calls return errors or the Amplifier coordinator throws when attempting to spawn a child session.

**`session_cwd`:** Always pass `VoiceSettings.workspace_root` (from `AMPLIFIER_WORKSPACE_ROOT`) explicitly when creating sessions — both parent and child. Without it, filesystem tools see the server's working directory, not the user's project.

---

### `translator.py` — VoiceEventTranslator

Translates between the OpenAI Realtime wire protocol (from/to data channel) and the client wire protocol (from/to browser). Pure transformation logic — no I/O, no state beyond block type tracking. Fully unit-testable with table-driven tests.

---

### `protocols/event_streaming.py` — EventStreamingHook

Ported from `amplifier-voice` as-is. The distro's existing `BridgeStreamingHook` is a thin stub; this is a full 24-event translation layer.

Subscribes to Amplifier canonical events and translates to SSE-friendly JSON with stable naming:

| Amplifier event | Wire message type |
|---|---|
| `tool:pre` | `tool_call` |
| `tool:post` | `tool_result` |
| `content_block:delta` | `content_delta` |
| `content_block:stop` | `content_stop` |
| `session:fork` | `session_fork` |
| `orchestrator:complete` | `orchestrator_complete` |
| `cancel:requested` | `cancel_requested` |
| `cancel:completed` | `cancel_completed` |
| *(+ 16 more)* | |

Maintains `_current_blocks: dict[int, str]` state so deltas know their block type. Strips base64 image payloads over 1000 chars. Wired via `event_queue` parameter on `BridgeBackend.create_session()` — same pattern as chat-app.

#### Hook Cleanup

`EventStreamingHook` is registered per-session (per `VoiceConnection`) and must be unregistered in a `finally` block on teardown. The registration returns an unregister callable — store it on `VoiceConnection` at session creation time and call it unconditionally:

```python
async def teardown(self):
    try:
        await services.backend.mark_disconnected(self._amplifier_session_id)
        await self._repository.update_status("disconnected")
    finally:
        if self._hook_unregister:
            self._hook_unregister()  # Always clean up registered hooks
        self._event_queue = None
```

Without this, dead hook registrations accumulate across reconnects and fire against closed queues.

---

### `protocols/voice_display.py` — VoiceDisplaySystem

Transforms Amplifier display messages written for screens into TTS-optimised output. Wires as the `display` parameter on `BridgeConfig` when creating the voice session.

Transformations applied in order:
1. Strip visual symbols: `=>`, `->`, `|`, `...`, markdown headers, code fences
2. Truncate to 200 characters at sentence boundary (`.`, `!`, `?`)
3. Add severity prefix: `"Error: ..."`, `"Warning: ..."`, `"Note: ..."`
4. Suppress debug/internal patterns via `should_speak=False` (debug prefixes, stack traces, JSON blobs)

Spoken prompt generation for approvals: `"May I write to config.json?"` — sent to the OpenAI Realtime session as a spoken instruction.

---

### `protocols/voice_approval.py` — VoiceApprovalSystem

Tool approval gating adapted to the voice context. Classification logic from `amplifier-voice` kept intact; async contract replaced with the distro's `asyncio.Event` pattern from `BridgeApprovalSystem`.

**Auto-approved silently (`SAFE_TOOLS`):** `read_file`, `web_search`, `web_fetch`, `git_log`, `git_status`, `glob`, `grep`, `list_directory`, `LSP`, `python_check`

**Require confirmation (`DANGEROUS_TOOLS`):** `bash`, `write_file`, `edit_file`, `delete_file`, `apply_patch`, `git_push`, `git_commit`, `git_reset`

Approval flow:
1. `request_approval(tool_name, args)` — pushes approval request into SSE event queue, creates `asyncio.Event`, awaits it
2. Browser receives SSE event, shows spoken prompt and confirmation UI
3. User approves/denies via voice or UI
4. `handle_response(approved)` — sets the event, unblocks `request_approval()`

`VoiceEventHook` from `amplifier-voice` is **dropped**. It was dead code — subscribed to event names (`tool_start`, `content_delta`) that don't match Amplifier's actual canonical names (`tool:pre`, `content_block:delta`). Its spoken narration concept is absorbed into `VoiceDisplaySystem`.

---

### `transcript/models.py` — VoiceConversation & TranscriptEntry

Ported from `amplifier-voice` with one structural change: `VoiceSession` is renamed `VoiceConversation` and its `id` field is the Amplifier session ID.

**`VoiceConversation` fields:**

```python
@dataclass
class VoiceConversation:
    id: str                      # amplifier_session_id — primary key
    title: str                   # auto-generated from first message
    status: str                  # active | disconnected | ended
    created_at: datetime
    updated_at: datetime
    ended_at: datetime | None
    end_reason: str | None       # session_limit | network_error | user_ended | idle_timeout | error
    duration_seconds: float | None
    first_message: str | None    # preview for session picker
    last_message: str | None
    tool_call_count: int
    reconnect_count: int
    disconnect_history: list[DisconnectEvent]
```

**`TranscriptEntry` fields:**

```python
@dataclass
class TranscriptEntry:
    id: str
    conversation_id: str
    role: str                    # user | assistant | tool_call | tool_result
    content: str
    audio_duration_ms: int | None  # voice-specific, no equivalent in Foundation
    created_at: datetime
    item_id: str | None          # OpenAI conversation item ID for resumption
```

---

### `transcript/repository.py` — VoiceConversationRepository

Manages persistence at `~/.amplifier/voice-sessions/`.

**Disk layout:**
```
~/.amplifier/voice-sessions/
    index.json                             # fast listing: [{id, title, status, created_at, first_message}]
    {amplifier_session_id}/
        conversation.json                  # full VoiceConversation (atomic .tmp → rename write)
        transcript.jsonl                   # TranscriptEntry records, append-only
```

**Two fixes over `amplifier-voice` original:**

1. `index.json` is **not** rewritten on every `add_entry()`. It updates only on `create_conversation()`, `end_conversation()`, and explicit status changes. Individual speech turns do not touch the index.

2. `get_resumption_context()` **no longer silently drops tool calls.** Tool exchanges are included in OpenAI format so resumed sessions know what the agent did:

```python
# Tool call in resumption context
{"type": "function_call", "name": "delegate", "call_id": "call_abc", "arguments": "{...}"}
{"type": "function_call_output", "call_id": "call_abc", "output": "..."}
```

---

### `static/index.html` + `static/vendor.js` — Preact Frontend

No Node, no build step. `vendor.js` is committed: Preact 10 + HTM + marked.js (for rendering tool output in transcript bubbles). Globals: `window.preact`, `window.html`, `window.marked`. Follows `feat/chat-app` pattern exactly.

## Data Flow

### Session Start

```
Browser: POST /sessions
  → VoiceConversationRepository.create_conversation(amplifier_session_id)
  → services.backend.create_session(
        app_name="voice",
        event_queue=hook.queue)       ← EventStreamingHook wired here
  → return { session_id: amplifier_session_id }

Browser: GET /session
  → POST /v1/realtime/client_secrets  (GA endpoint)
      { "session": { "type": "realtime", "model": "gpt-realtime",
                     "instructions": "...", "tools": [...] } }
  → return { value: "ek_..." }

Browser: POST /sdp  (with SDP offer body)
  → POST /v1/realtime/calls           (GA endpoint)
  → return SDP answer

Browser: data channel open
  → session.update #1: server_vad + noise reduction + transcription (gpt-4o-transcribe, lang=en)
  → [100ms delay]
  → session.update #2: semantic_vad, eagerness=low, create_response=false, interrupt_response=true
```

### Conversation Turn

```
User speaks → semantic_vad detects end-of-turn
  → transcription.item.completed fires
  → useChatMessages checks shouldAutoRespond()
  → if true: data channel → response.create

OpenAI streams response
  → response.audio_transcript.delta
      → messageRef.current.textContent += delta   (zero Preact rerenders)
  → response.audio_transcript.done
      → React state update (finalizes bubble)

Tool call in response:
  → response.output_item.added { item.type: "function_call" }
  → if voice-control tool (pause_replies, resume_replies, cancel_current_task):
      → handled in browser immediately
  → else:
      → POST /tools/execute { name, arguments, call_id }
          → handle.run(instruction)   ← plain string in, plain string out
          → Amplifier events flow through EventStreamingHook → SSE → browser debug panel
          → return ToolResult
      → data channel → conversation.item.create { type: "function_call_output", ... }
      → data channel → response.create
```

### `/tools/execute` Route — `handle.run()` Contract

**`SessionHandle.run(prompt: str) -> str`** — plain string in, plain string out. There is no `execute()` method on `SessionHandle`; that lives on the underlying `AmplifierSession` which the handle wraps and hides.

When the OpenAI Realtime model calls `delegate` with an instruction string, the route calls `handle.run(instruction)` directly. No wrapping, no formatting, no structured payload. The string returned is the tool result sent back to the OpenAI data channel.

```python
# /tools/execute route (simplified)
async def execute_tool(request: ToolExecuteRequest) -> ToolResult:
    if request.tool_name == "delegate":
        instruction = request.arguments.get("instruction", "")
        result = await handle.run(instruction)   # ← plain string
        return ToolResult(success=True, output=result)
```

The bridge handles all session state, context injection, and provider delegation internally. The route is intentionally dumb.

---

### Tool Set Exposed to OpenAI Realtime

The voice model is a conversational interface, not a shell. Following `APPLICATION_INTEGRATION_GUIDE.md` Pattern D — "Only expose `delegate` and a few lookup tools to the voice model" — the `AMPLIFIER_TOOLS` list in `__init__.py` must be exactly these four tools:

| Tool | Handled by | Notes |
|---|---|---|
| `delegate` | Server → `services.backend.execute()` | All real work routes through here |
| `cancel_current_task` | Server → `backend.cancel_session()` | Two-level cancel |
| `pause_replies` | Browser (intercepted before server) | Sub-100ms, no round-trip |
| `resume_replies` | Browser (intercepted before server) | Sub-100ms, no round-trip |

No `run_command`. No `search_files`. No `read_file`. If the voice model needs to read a file or run a command, it calls `delegate` with an instruction and the appropriate Amplifier specialist agent handles it — with full observability, hook firing, and session tracking. Exposing filesystem or shell tools directly to a conversational interface bypasses the Amplifier agent loop entirely: no hooks, no observability, no delegation.

### Async Tool Queuing (race condition prevention)

```
Tool result arrives while model is mid-response:
  → push to pendingToolAnnouncements queue

response.done event:
  → if pendingToolAnnouncements.length > 0:
      → flush with response.create carrying pending context
  → else: normal completion
```

### Transcript Sync

```
Every 5 entries  OR  beforeunload (navigator.sendBeacon):
  → POST /sessions/{id}/transcript
      { entries: [{ role, content, audio_duration_ms, item_id, ... }] }
  → VoiceConversationRepository.add_entries(id, entries)
```

### Session Resumption

```
WebRTC drops:
  → services.backend.mark_disconnected(amplifier_session_id)
  → repository.update_status("disconnected")
  → ConnectionHealthManager records disconnect reason

Browser reconnects:
  → POST /sessions/{id}/resume
      → services.backend.reconnect(amplifier_session_id)
      → repository.get_resumption_context(id)
          → returns OpenAI-format conversation items (including tool calls)
      → POST /v1/realtime/client_secrets  → fresh client_secret
      → return { client_secret, context_to_inject: [...conversation items] }

Browser:
  → new WebRTC connection with fresh secret
  → conversation.item.create for each context item (injects history)
  → session.update (semantic_vad, create_response=false)
```

### Session End

```
Explicit end OR 60-minute limit reached:
  → services.backend.end_session(amplifier_session_id)    ← permanent tombstone
  → repository.end_conversation(id, reason="user_ended" | "session_limit")
  → data channel close
```

## Error Handling

**OpenAI 60-minute hard limit:** `ConnectionHealthManager` fires a warning at 55 minutes. The client can proactively call `POST /sessions/{id}/end` with `reason: "session_limit"` and start a fresh conversation with context injected. If the warning is missed, OpenAI hard-cuts the connection at 60 minutes — treated as a network disconnect with `end_reason: "session_limit"` inferred from session age.

**`conversation_already_has_active_response`:** Handled by the async tool queue. Tool results that arrive while the model is mid-response are queued. On `response.done` the queue flushes. This prevents silent tool result drops.

**Disconnect reason classification:** When a disconnect occurs, `ConnectionHealthManager` infers cause from metrics:
- Session age ≥ 58 minutes → `session_limit`
- No OpenAI events for > 30s with recent user speech → `network_error`
- No user speech for > 2 minutes → `idle_timeout`
- Active tool call at disconnect time → `error`

Reason is stored on `VoiceConversation` and surfaced in the session picker UI.

**Path traversal:** Any route taking a session ID that touches `~/.amplifier/voice-sessions/` validates with `re.compile(r"^[a-zA-Z0-9_\-]+$")` before filesystem access.

**TURN server absent:** ICE/WebRTC will fail in symmetric NAT environments (some corporate networks, cloud VMs). Google STUN only. Noted in `/api/status` response and with a `TODO` comment in the signaling code for easy future discovery.

## Connection Health & Reconnection

`ConnectionHealthManager` is a pure logic class with no UI concerns. Runs checks every 5 seconds.

**Warning thresholds:**

| Threshold | Condition | Action |
|---|---|---|
| 30 seconds | No OpenAI events received | Stale connection warning to UI |
| 2 minutes | No user speech | Idle warning to UI |
| 55 minutes | Session age | Proactive session limit warning |

**Reconnection strategies** (configurable in `ConnectionHealthPanel` at runtime):

| Strategy | Behaviour |
|---|---|
| `manual` | User clicks reconnect (default) |
| `auto_immediate` | Reconnects instantly on disconnect |
| `auto_delayed` | Reconnects after 3 seconds (good for brief blips) |
| `proactive` | Schedules reconnect at 55-minute mark before hard limit |

`useConnectionHealth` wraps the manager as a Preact hook. `ConnectionHealthPanel` is collapsible by default and shows all metrics live: session duration, idle time, last event timestamp, reconnect count, disconnect history.

## Cancellation System

**Two trigger paths, one execution path:**

```
UI path:
  StopButton (single click → graceful, double-click → immediate)
    → POST /cancel { immediate: bool }
    → backend.cancel_session(amplifier_session_id, immediate)

Voice model path:
  User: "actually stop that" / "forget it"
    → OpenAI invokes cancel_current_task function tool
    → POST /tools/execute { name: "cancel_current_task", ... }
    → backend.cancel_session(amplifier_session_id, immediate=false)
```

**State propagation via SSE:**

```
cancel_requested  →  browser: StopButton enters "stopping..." state
cancel_completed  →  browser: StopButton resets
```

The two-event pattern prevents a second execution starting before the first has actually stopped.

`StopButton` shows the names of currently running tools and active agent count, sourced from `session:fork` / `orchestrator:complete` SSE events emitted by `EventStreamingHook`. Example displays: `"Delegating to explorer..."`, `"2 agents running"`.

## Voice Keywords

`useVoiceKeywords` scans every transcription before `useChatMessages` processes it.

**Default keyword mappings:**

| Spoken phrase | Action |
|---|---|
| `"Hey Amplifier, go ahead"` / `"Hey Amplifier, your turn"` | `triggerResponse()` |
| `"Hey Amplifier, pause replies"` | Enter pause-replies mode |
| `"Hey Amplifier, resume"` | Exit pause-replies mode |
| `"Hey Amplifier, mute"` | Mute microphone |
| `"Hey Amplifier, unmute"` | Unmute microphone |

Matching uses two strategies: direct substring match and word-sequence match (allows words between). 2-second debounce prevents double-fires when the model itself says a trigger phrase in its response.

The wake word (`"Hey Amplifier"`) derives from `VoiceSettings.assistant_name` — a new field added to distro settings. Renaming the assistant automatically updates all keyword triggers with no code changes.

```python
# distro_settings.py — add to VoiceSettings dataclass
assistant_name: str = "Amplifier"
# Exported as: AMPLIFIER_VOICE_ASSISTANT_NAME
```

**Settings flow:** `distro_settings.py` → `export_to_env()` → `AMPLIFIER_VOICE_ASSISTANT_NAME` env var → read by voice app at startup → passed into `useVoiceKeywords` as the wake word prefix. All keyword phrases are constructed at runtime from this value, so renaming requires no code changes.

## Security

Follows `feat/chat-app` exactly.

**API key (`config.server.api_key`):** Optional. When unset, auth is skipped entirely — zero friction for personal use. When set, protected endpoints require `X-Api-Key` header, compared with `hmac.compare_digest`.

**Protected endpoints:**

| Endpoint | Reason |
|---|---|
| `GET /session` | Creates OpenAI Realtime sessions — costs real money |
| `POST /sessions` and `POST /sessions/*` | Session lifecycle and transcript sync |
| `GET /sessions` | Conversation history |
| `POST /tools/execute` | Executes Amplifier tools |
| `POST /cancel` | Cancellation |

**Unprotected:** `GET /` (HTML), `GET /static/vendor.js`, `GET /api/status`, `POST /sdp` (SDP is not sensitive; the `client_secret` from `/session` is the actual credential).

**CSRF Origin check on `GET /events` (SSE):** Even on localhost, a malicious page could subscribe to the Amplifier event stream. Only `localhost` and `127.0.0.1` origins allowed. Requests with no `Origin` header (non-browser clients, curl) pass through.

```python
# TODO: If voice app is ever network-exposed (multi-user, remote access),
# GET /session creating OpenAI Realtime sessions unauthenticated becomes a
# real threat. The _require_api_key dependency is already in place — ensure
# config.server.api_key is set before exposing this to a network.
```

```python
# TODO: No TURN server configured. ICE/WebRTC will fail in symmetric NAT
# environments (some corporate networks, cloud VMs). STUN only for now.
# TURN requires infrastructure; out of scope for this iteration.
```

## Frontend Architecture

### Component Tree

```
VoiceApp (root)
├── SessionPicker          — browse/resume past conversations, titles from first message
├── StatusHeader           — voice badge (WebRTC), tools badge (server health), session ID
├── ErrorBanner            — conditional, dismissible
├── TranscriptDisplay      — scrollable: user speech, assistant text, tool status
│   └── MessageBubble      — per-turn, streaming via direct DOM mutation (bypass Preact)
├── ControlsPanel
│   ├── ConnectButton      — Start / Disconnect
│   ├── StopButton         — cancel Amplifier ops (graceful/immediate), shows tool names + count
│   └── MicrophoneControls — mute / pause-replies / trigger-response with visual state
└── ConnectionHealthPanel  — collapsible debug panel
```

### State Management

Preact's own `useState` / `useReducer` / `useContext`. No Zustand. Shared state (connection status, session, conversation list) lives in a root `useReducer` passed via context.

**Two-track streaming pattern:** Reactive state for UI renders. Mutable `useRef` for zero-rerender streaming. Incoming `response.audio_transcript.delta` events go directly to `messageRef.current.textContent +=` — Preact never touches them mid-stream. Finalisation (state update that triggers rerender) happens only on `response.audio_transcript.done`.

### Custom Hooks

`useVoiceChat` is the orchestrating hook:

```
useVoiceChat
├── useWebRTC              — RTCPeerConnection lifecycle, data channel, SDP exchange
├── useChatMessages        — transcription handling, response.create gating
├── useConnectionHealth    — health manager, reconnection strategies
├── useServerHealth        — polls /api/status for server availability
├── useMicrophoneControl   — mute, pause-replies, visual states
├── useVoiceKeywords       — wake word and command detection
├── useCancellation        — POST /cancel, StopButton state
└── useAmplifierEvents     — SSE consumer for EventStreamingHook stream
```

Each hook is independently focused with no UI concerns. Composition over monolith.

## Testing Strategy

### Unit Tests (pure, no I/O)

| Subject | What to test |
|---|---|
| `VoiceEventTranslator` | Table-driven: input event dict → expected wire message |
| `EventStreamingHook` | Feed raw Amplifier events, assert translated SSE messages; verify `_current_blocks` state tracking |
| `VoiceDisplaySystem` | Screen-formatted strings → TTS output; truncation at sentence boundaries; symbol stripping; suppressed patterns |
| `VoiceApprovalSystem` | Safe/dangerous classification; spoken prompt generation; asyncio.Event unblocking |
| `VoiceConversationRepository` | File I/O with `tmp_path`: create, add entries, end, resume; JSONL append correctness; atomic `conversation.json` write |
| `VoiceConversation` / `TranscriptEntry` | Serialisation round-trips; `from_dict` resilience with unknown keys |

### HTTP Route Tests (via `TestClient`)

| Route | What to test |
|---|---|
| `GET /session` | API key enforcement when configured; correct GA response structure; mock OpenAI `/client_secrets` |
| `POST /sdp` | Relays SDP offer to mock OpenAI `/calls` endpoint; returns SDP answer |
| `POST /sessions` | Creates conversation record; returns amplifier session id |
| `POST /sessions/{id}/resume` | Reconnect path: returns `client_secret` + `context_to_inject`; tool calls present in context |
| `POST /sessions/{id}/transcript` | Stores entries; `index.json` not rewritten on entry add |
| `POST /sessions/{id}/end` | Marks ended; sets `end_reason` |
| `GET /sessions` | Returns conversation list from index |
| `GET /api/status` | Correct fields reflecting `VoiceSettings` |

### Stub Mode

Extend existing `stub.py` for GA API endpoint shapes (`/client_secrets`, `/calls`). The full server runs in CI without OpenAI credentials — same as today.

### Explicitly Not Tested

WebRTC connection establishment, audio pipeline, Preact frontend behaviour, actual OpenAI Realtime API responses. Tested manually or in integration testing with real credentials.

## Open Questions

None. All design decisions were resolved during review.

## Implementation Order

Each phase is independently mergeable and adds testable value. Phases 1 and 2 have zero FastAPI dependencies — pure logic, fast tests.

```
PREREQUISITE
  ├── Confirm feat/chat-app merge into lean-experience-server  OR
  ├── Branch voice work off feat/chat-app directly
  └── Verify handle.run() signature ✅ (confirmed: plain string, SessionHandle.run)

PHASE 1 — Data layer (no FastAPI deps, pure I/O)
  1a. distro_settings.py: add VoiceSettings.assistant_name
  1b. voice/realtime.py: GA API client (create_client_secret + exchange_sdp)
  1c. voice/transcript/models.py: VoiceConversation, TranscriptEntry
  1d. voice/transcript/repository.py: VoiceConversationRepository
  Tests: repository unit tests with tmp_path; realtime.py with httpx mock

PHASE 2 — Protocol layer (no FastAPI deps)
  2a. voice/protocols/event_streaming.py: EventStreamingHook (port from amplifier-voice)
  2b. voice/protocols/voice_display.py: VoiceDisplaySystem
  2c. voice/protocols/voice_approval.py: VoiceApprovalSystem
  Tests: table-driven unit tests for all three

PHASE 3 — Connection + translation core
  3a. voice/translator.py: VoiceEventTranslator
  3b. voice/connection.py: VoiceConnection (lifecycle, spawn capability, hook cleanup, cancellation)
  Tests: translator unit tests; VoiceConnection lifecycle tests with MockBackend

PHASE 4 — Routes (replaces current __init__.py entirely)
  4a. voice/__init__.py: all routes per design doc, AppManifest, stub mode extension
  Tests: full route test suite via TestClient

PHASE 5 — Frontend (manual testing only)
  5a. Committed vendor.js: Preact 10 + HTM + marked.js
  5b. voice/static/index.html: Preact app — full hook/component tree from design doc
  Manual: test with real OpenAI credentials
```

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Full overhaul | User requirement; app may graduate out of distro |
| API version | GA only, no backward compat | Clean break; no legacy constraints |
| Frontend | Preact + HTM, vendored `vendor.js` | Matches chat-app pattern; no Node or build step |
| Session identity | `VoiceConversation.id == amplifier_session_id` | No parallel session world; enables cross-surface continuity |
| Session backend | Shared `services.backend` via `get_services()` | Mandated by `SESSION-ARCHITECTURE-NOTES.md` |
| `VoiceSessionStore` | Eliminated | ID equality makes mapping unnecessary |
| Structural reference | `feat/chat-app` | Establishes the distro patterns to follow |
| Capability reference | `amplifier-voice` | Full feature set to adapt |
| `VoiceEventHook` | Dropped | Dead code; wrong event names; replaced by `VoiceDisplaySystem` |
| `VoiceApprovalSystem` async | Replaced with `asyncio.Event` | Matches distro's `BridgeApprovalSystem` contract |
| Auth | `config.server.api_key`, optional | Matches chat-app; zero friction for personal use |
| `VoiceSettings.assistant_name` | New field, default `"Amplifier"` | Wake word configurable without code changes |
| Wake word | Derived from `VoiceSettings.assistant_name` | Configurable; rename assistant without touching code |
| `realtime.py` separate module | Isolated GA API calls | Thin routes, clean CI stub extension, matches `amplifier-voice` structure |
| `handle.run()` contract | Plain string in, plain string out | No `execute()` on `SessionHandle`; bridge handles all session state internally |
| TURN server | Not in scope | Infrastructure dependency; `TODO` in code for future discovery |
| Semantic VAD | Two-stage init (server_vad → semantic_vad, 100ms) | GA API constraint; `semantic_vad` can't be initial type on WebRTC |
| `create_response` | `false` (manual gating) | Prevents background noise from triggering model responses |
| Spawn capability | Register on coordinator post-create | Routes delegate sub-sessions through shared backend |
| Tool set (OpenAI) | `delegate` + 3 voice-control tools only | No direct file/shell access; Pattern D from integration guide |
| Hook cleanup | Unregister callable stored, called in `finally` | Prevents dead hook accumulation across reconnects |
| `session_cwd` | Always from `VoiceSettings.workspace_root` | Filesystem tools need explicit workspace, not server cwd |
