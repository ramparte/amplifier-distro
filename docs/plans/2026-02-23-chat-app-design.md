# Chat App Design

## Goal

Build a new FastAPI plugin app (`server/apps/chat/`) that replaces `web_chat`'s blocking HTTP pattern with a WebSocket-based streaming chat UI, mounted at `/apps/chat/`.

## Background

`web_chat` uses a blocking HTTP request/response pattern that cannot stream kernel events to the browser in real time. The `BridgeStreamingHook` already fires on every kernel event and `BridgeConfig.on_stream` already exists as a callback field — but today both broadcast to nobody. The infrastructure is ready; the `chat` app is the first consumer. Users opt in; `web_chat` stays untouched.

## Approach

Single WebSocket transport per session. One WebSocket connection = one Amplifier session. `BridgeBackend` is reused unchanged — the only wiring required is `BridgeConfig.on_stream = queue.put_nowait`, which connects the existing event broadcast to a per-connection `asyncio.Queue`. A small set of backend gap fixes (all backwards-compatible) unlocks cancellation, approvals, sub-agent events, behaviors, and display messages for all apps — not just `chat`.

Frontend uses Preact 10 + HTM + marked.js vendored into `static/vendor.js` (~65KB, committed to repo). Zero npm/node required: `uv tool install -e ".[all]" .` gives a working UI immediately — consistent with the single-file pattern used by all other distro apps.

## Architecture

### New vs Existing

**Existing (unchanged):**
- `BridgeBackend` (`server/session_backend.py`) — shared across slack, voice, web_chat, chat
- `BridgeStreamingHook` (`bridge_protocols.py`) — registered for ALL_EVENTS, fires on every kernel event, currently broadcasting to nobody
- `BridgeConfig.on_stream` — exists as a callback field, always `None` today
- `BridgeApprovalSystem` — exists but skeleton (always auto-approves)
- `AppManifest` (`server/app.py`) — plugin manifest system

**New (in `server/apps/chat/`):**
- `AppManifest(name="chat")` — auto-discovered, mounted at `/apps/chat/`
- `ChatConnection` — one per WebSocket connection; manages auth, receive loop, event fanout loop
- `SessionEventTranslator` (`translator.py`) — maps kernel event names/payloads to wire protocol
- `@router.websocket("/ws")` — the WebSocket endpoint
- REST routes: session list, transcript history, preferences
- `static/index.html` + `static/vendor.js` — Preact frontend

## Data Flow

```
Browser WebSocket ──► /apps/chat/ws
                           │
                      ChatConnection (one per WS connection)
                      ├── auth_handshake()
                      │     reads distro.yaml server.api_key
                      │     first msg: {"type":"auth","token":"..."}
                      │     response: {"type":"auth_ok"} or close(4001)
                      │
                      ├── receive_loop (reads client messages)
                      │     create_session → backend.create_session()
                      │     prompt         → backend.execute() [background task]
                      │     cancel         → backend.cancel_session()
                      │     approval_resp  → backend.resolve_approval()
                      │     command        → route to handler
                      │     ping           → send pong
                      │
                      ├── event_fanout_loop (drains queue → client)
                      │     while True:
                      │       raw = await event_queue.get()
                      │       msg = translator.translate(raw)
                      │       await ws.send_json(msg)
                      │
                      └── asyncio.Queue ◄── BridgeConfig.on_stream = queue.put_nowait

                           │
                      BridgeBackend (existing, minimal changes)
                           │
                      AmplifierSession / kernel events
```

The critical wiring: `BridgeConfig.on_stream = queue.put_nowait` is the single line that connects the existing broadcasting infrastructure to a consumer for the first time.

## Components

### `ChatConnection`

One instance per WebSocket connection. Owns:
- `auth_handshake()` — validates token from `distro.yaml server.api_key`
- `receive_loop` — reads client messages and dispatches to backend
- `event_fanout_loop` — drains `asyncio.Queue` and writes translated events to WebSocket
- `asyncio.Queue` — wired to `BridgeConfig.on_stream`

### `SessionEventTranslator` (`translator.py`)

Maps raw kernel events to the wire protocol. Lives in the `chat` app — `BridgeBackend` stays protocol-agnostic.

**Event translation map:**

| Backend fires | Wire protocol |
|---|---|
| `content_block:start` | `content_start` |
| `content_block:delta` | `content_delta` |
| `content_block:end` | `content_end` |
| `thinking:delta` | `thinking_delta` |
| `tool:pre` | `tool_call` (tool_input → arguments) |
| `tool:post` | `tool_result` (result.output → output) |
| `delegate:agent_spawned` | `session_fork` (with parent_tool_call_id correlation) |
| `orchestrator:complete` | `prompt_complete` |
| `cancel:completed` | `execution_cancelled` |
| `BridgeDisplaySystem` | `display_message` (via direct queue push) |

**Block index remapping:** Server resets block index to 0 after each `tool_result`. Translator tracks `cycle_count` (increments per `tool_result`) and uses `${cycle}-${serverIndex}` as a composite key mapped to a stable `local_index`. Enables direct DOM access during streaming across index resets.

**`parent_tool_call_id` correlation:** Translator tracks the last `tool:pre` event for `delegate`/`task` tools. On `delegate:agent_spawned`, injects that `tool_call_id` as `parent_tool_call_id`.

### REST Routes

- `GET /apps/chat/sessions` — list active sessions
- `GET /apps/chat/sessions/{id}/transcript` — transcript history
- `GET /apps/chat/preferences` — user preferences
- `GET /apps/chat/vendor.js` — vendored frontend bundle

### Frontend (`static/index.html` + `static/vendor.js`)

Preact 10 + HTM + marked.js. No build step. `vendor.js` is committed to the repo.

## Event Protocol

### Server → Client

| Event | When | Key fields |
|---|---|---|
| `auth_ok` | Auth success | — |
| `session_created` | Session bound | session_id, bundle, cwd |
| `content_start` | New block | block_type (text/thinking/tool_use), index |
| `content_delta` | Text streaming | delta, index |
| `content_end` | Block done | index |
| `thinking_delta` | Thinking streaming | delta |
| `thinking_final` | Thinking done | content |
| `tool_call` | Tool starting | tool_call_id, tool_name, arguments |
| `tool_result` | Tool done | tool_call_id, success, output, error |
| `session_fork` | Sub-agent spawned | parent_id, child_id, parent_tool_call_id, agent |
| `display_message` | System info | level, message, source |
| `approval_request` | Needs approval | id, prompt, options, timeout, default |
| `approval_timeout` | Auto-resolved | id, applied_choice |
| `prompt_complete` | Turn done | turn_count |
| `execution_error` | Error | error |
| `execution_cancelled` | Cancelled | — |
| `command_result` | Slash command response | command, result |
| `pong` | Keepalive | — |

### Client → Server

| Message | When | Key fields |
|---|---|---|
| `auth` | First message | token |
| `create_session` | Start/resume | bundle, behaviors, cwd, resume_session_id, show_thinking |
| `prompt` | User sends message | content, images (base64 array) |
| `approval_response` | User approves tool | id, choice |
| `cancel` | Stop button | level (graceful/immediate) |
| `command` | Slash command | name, args |
| `ping` | Keepalive | — |

## Backend Gap Fixes

Minimal, backwards-compatible changes that benefit all apps (slack, voice, web_chat, chat):

| Fix | Location | Impact |
|---|---|---|
| `on_stream` wiring in `create_session` | `session_backend.py` | Enables all streaming |
| Register `delegate:*` on `BridgeStreamingHook` | `bridge_protocols.py` | Enables sub-agent events |
| `SessionHandle.cancel(level)` | `session_backend.py` | Enables stop button |
| `BridgeBackend.cancel_session()` | `session_backend.py` | Enables stop button |
| `BridgeApprovalSystem` asyncio.Event rebuild | `bridge_protocols.py` | Enables approval modal |
| `behaviors` param in `BridgeConfig` | `bridge.py` | Enables behavior selection |
| `show_thinking` param in `BridgeConfig` | `bridge.py` | Enables thinking toggle |
| `BridgeDisplaySystem.on_message` → queue | `session_backend.py` | Enables display messages |

## Frontend Component Architecture

```
ChatApp
├── refs: wsMapRef, orderCounterRef, blockMapRef,
│         cycleRef, toolMapRef, subSessionRefs, childSessionToToolCallRef
│
├── state: sessions (Map<sessionId,SessionState>), activeSessionId,
│          wsStatus, pendingApproval, chronoItems
│
├── SessionPanel (collapsible sidebar)
│   ├── session cards: name, 📁 cwd, status badge, turn count, timestamp
│   │   ├── ⟳ badge = tool running in background
│   │   ├── 🔔 badge = approval pending in background
│   │   └── ✗ badge = execution errored
│   └── [+ New Session] button
│
├── Header
│   ├── ● connection dot (green/yellow/red)
│   ├── 📁 ~/path/to/cwd  (clickable → inline CWD editor)
│   ├── turn count
│   ├── [Focus] toggle (opt-in, off by default)
│   └── [Sessions] toggle
│
├── ChatContainer (active session)
│   ├── Default mode: single chronological timeline
│   │   └── MessageList (sorted by .order)
│   │       ├── TextBlock — direct DOM mutation, streaming cursor CSS
│   │       ├── ThinkingBlock — collapsible, 60-char preview, pulsing dots
│   │       └── ToolCallCard
│   │           ├── Header: status icon + tool name + arg preview
│   │           ├── Expanded: full args JSON + truncated result
│   │           └── SubSessionView (if delegation)
│   │               └── nested MessageList (own blockMap, cycleRef, orderCounter)
│   │
│   └── Focus mode: two-column split
│       ├── Left: text blocks only + [🔧] inline markers where tools ran
│       └── Right: ActivityPanel (thinking + tools + sub-agents, auto-scroll)
│
├── InputArea
│   ├── auto-resize textarea (max 200px)
│   ├── image paste / drag-drop → base64 preview thumbnails
│   ├── Enter=send, Shift+Enter=newline
│   ├── slash command interceptor
│   └── [Send] / [■ Stop] button
│
└── ApprovalModal (blocking overlay when pendingApproval !== null)
    ├── prompt text
    ├── countdown progress bar (CSS animation, 5min default)
    └── option buttons (Deny=red, Allow once=blue, Allow always=green)
```

### State Management (Two Tiers)

**Tier 1 — Reactive (`useState`, triggers re-renders):**
- `sessions: Map<sessionId, SessionState>` — structural changes (new session, status change)
- `activeSessionId` — which session renders
- `wsStatus` — connection dot colour
- `pendingApproval` — approval modal visibility
- `chronoItems` — structural events (new block, new tool, tool status change)

**Tier 2 — Refs (`useRef`, zero re-renders):**
- `blockMapRef` — `{cycleKey → localItemId}` for block index mapping
- `cycleRef` — increments per `tool_result` (handles server block index resets)
- `orderCounterRef` — shared counter for text blocks and tool cards
- `toolMapRef` — `{tool_call_id → chronoItem.id}`
- `subSessionRefs` — per sub-session isolated refs
- `childSessionToToolCallRef` — FIFO queue for `parent_tool_call_id` correlation

**Streaming text — direct DOM mutation (no re-renders):**
```javascript
// content_delta handler:
const el = document.getElementById(itemId);
if (el) el.textContent += delta;
// Zero Preact involvement during streaming
```

## UI Modes

### Default Mode

Single chronological timeline. Text blocks, thinking blocks, and tool cards interleaved by shared `order` counter.

### Focus Mode (opt-in, off by default)

Two-column layout:
- **Left (main pane):** Text blocks only. Clean reading experience. Inline `[🔧]` markers at positions where tools ran link eye to the right panel.
- **Right (activity panel):** Thinking blocks + tool cards + sub-agent sessions. Auto-scrolls independently.

## Multi-Session

Multiple sessions stay alive simultaneously. Switching sessions changes `activeSessionId`. Background sessions keep their WebSocket alive and accumulate events silently. Status badges in the sidebar surface background activity (`⟳`, `🔔`, `✗`). Each session has its own independent `ChatConnection` — the backend has no awareness of multi-session coordination.

## Image Attachments

- Input supports paste from clipboard and drag-drop onto textarea
- Images base64-encoded in browser; preview thumbnails shown before sending
- Sent as `{"type": "prompt", "content": "...", "images": ["base64...", ...]}`
- Backend threads images through `BridgeBackend.execute(prompt, images=[...])`
- Works with Anthropic and OpenAI providers (both support vision)

## Slash Commands

### Client-Side (never reach server)

| Command | Action |
|---|---|
| `/help` | Shows command list as system message |
| `/clear` | Clears visible conversation (session stays alive) |
| `/focus` | Toggles focus mode |
| `/thinking on\|off` | Toggles thinking block visibility |

### Server-Side (routed via `{"type": "command", ...}`)

| Command | Action |
|---|---|
| `/status` | Returns session status, bundle, turn count |
| `/tools` | Lists available tools in current bundle |
| `/agents` | Lists available agents |
| `/modes` | Lists available Amplifier modes |
| `/mode <name>` | Sets Amplifier mode on session |
| `/bundle <name>` | Reconfigures session with new bundle |
| `/cwd <path>` | Changes working directory |

## Mobile / Responsive

Two breakpoints, designed from day one:
- **Desktop (>768px):** Sidebar visible, optional focus mode right panel
- **Mobile (≤768px):** Sidebar as slide-in drawer (hamburger), focus mode disabled (screen too narrow), touch-friendly tap targets, large textarea

## Error Handling

| Scenario | Handling |
|---|---|
| WebSocket disconnect | Session stays alive in BridgeBackend |
| Browser reconnect | `create_session` with `resume_session_id` re-wires event queue |
| Background execution error | `✗` badge in sidebar |
| Background approval request | `🔔` badge in sidebar |
| Auth failure | WebSocket close code 4001; client shows login prompt |

## Testing Strategy

- **Backend gap fixes:** Unit tests in `tests/test_chat_*.py` for each fix
- **WebSocket endpoint:** Integration tests via FastAPI `TestClient` WebSocket support
- **`SessionEventTranslator`:** Unit tested with mock kernel events covering index remapping, cycle counting, and `parent_tool_call_id` correlation
- **Frontend:** Manual validation in early phases; Playwright E2E added in Phase 5+

## Open Questions

None — all design decisions above are validated and agreed upon.

## Out of Scope

- Migrating existing `web_chat` users (`web_chat` stays; users opt in to `chat`)
- Committing node_modules (`vendor.js` is committed; the build toolchain is not)
