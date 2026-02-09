# Slack Bridge: Architecture, Setup, and Lessons Learned

This file captures everything a future session needs to know about the Slack
bridge -- what it is, how it works, how to set up the Slack app, and what
went wrong so we don't repeat mistakes.

---

## What This Is

The Slack bridge connects a Slack workspace to Amplifier sessions running on the
distro server. Users talk to a bot in Slack; the bot routes messages to Amplifier
sessions and returns responses. It's one of several "app plugins" for the distro
server (alongside web-chat, install-wizard, etc.).

**Location**: `src/amplifier_distro/server/apps/slack/`

**Three operating modes**:

| Mode | How it works | When to use |
|------|-------------|-------------|
| **Socket Mode** | Server opens WebSocket TO Slack (outbound) | Production. No public URL needed. |
| **Events API** | Slack POSTs webhooks to our endpoint (inbound) | When you have a public URL (Tailscale, ngrok) |
| **Simulator** | In-memory fake Slack with browser UI | Local testing without any Slack credentials |

Socket Mode is the primary mode. It's what we use.

---

## Architecture (Message Flow)

```
Slack WebSocket --> SocketModeAdapter._process_frames()
  |-- _ack(envelope_id)          <-- immediate (Slack retries if >3s)
  |-- skip own/bot messages
  '-- wrap as event_callback payload
        |
        v
SlackEventHandler.handle_event_payload()
  |-- url_verification --> return challenge
  '-- event_callback --> _dispatch_event()
        |-- app_mention --> always treated as command
        '-- message --> _handle_message()
              |-- skip bots/edits/deletes
              |-- if mentions bot --> CommandHandler.handle()
              |-- if has session mapping --> SessionManager.route_message()
              |     '-- Backend.send_message() --> response text
              '-- else --> ignore (no response)
                    |
                    v
        Response via SlackClient.post_message() (threaded reply)
        with hourglass --> checkmark reaction lifecycle
```

**Key files** (13 source files, ~2400 lines total):

| File | Purpose |
|------|---------|
| `__init__.py` | FastAPI routes, startup/shutdown, dependency wiring |
| `config.py` | `SlackConfig` dataclass, env var loading |
| `socket_mode.py` | Raw aiohttp WebSocket adapter (replaces slack_bolt) |
| `events.py` | Event dispatch, signature verification, message routing |
| `commands.py` | 9 registered commands (help, list, new, connect, etc.) |
| `client.py` | `SlackClient` protocol + HTTP and in-memory implementations |
| `sessions.py` | Session mapping table (Slack conversation <-> Amplifier session) |
| `backend.py` | `SessionBackend` protocol + mock and bridge implementations |
| `models.py` | Core data structures (SessionMapping, SlackMessage, etc.) |
| `formatter.py` | Markdown-to-Slack-mrkdwn conversion, message splitting |
| `discovery.py` | Local filesystem scanner for existing Amplifier sessions |
| `simulator.py` | Browser test UI with WebSocket hub |
| `static/simulator.html` | Simulator browser interface |

**Test file**: `tests/test_slack_bridge.py` (871 lines, 9 test classes)

---

## Slack App Setup (The Hard Part)

This is the manual process we went through. A future session should automate
this into the install-wizard or a setup script.

### Step 1: Create the Slack App

1. Go to https://api.slack.com/apps
2. Click "Create New App" > "From scratch"
3. Name it (e.g. "SlackBridge" or "Amplifier")
4. Select the workspace

### Step 2: Enable Socket Mode

1. In the app settings, go to **Socket Mode** (left sidebar)
2. Toggle it ON
3. It will prompt you to create an **App-Level Token** with scope `connections:write`
4. Name the token (e.g. "socket-mode-token")
5. Copy the `xapp-...` token -- this is `SLACK_APP_TOKEN`

### Step 3: Set Bot Scopes (OAuth & Permissions)

Go to **OAuth & Permissions** > **Scopes** > **Bot Token Scopes** and add:

**Required scopes**:
- `app_mentions:read` -- receive @mention events
- `channels:history` -- read messages in public channels
- `channels:read` -- list channels
- `chat:write` -- post messages
- `reactions:write` -- add emoji reactions (hourglass/checkmark UX)

**For breakout channels** (optional but recommended):
- `channels:manage` -- create channels for session breakout
- `channels:join` -- join channels the bot creates

**For private channels** (if hub channel is private):
- `groups:history` -- read messages in private channels
- `groups:read` -- list private channels

### Step 4: Subscribe to Events

Go to **Event Subscriptions** > Toggle ON.

Under **Subscribe to bot events**, add:
- `app_mention` -- fires when someone @mentions the bot
- `message.channels` -- fires on any message in channels the bot is in

(For private channels, also add `message.groups`.)

### Step 5: Install the App to Workspace

1. Go to **Install App** (left sidebar)
2. Click "Install to Workspace"
3. Authorize the requested scopes
4. Copy the **Bot User OAuth Token** (`xoxb-...`) -- this is `SLACK_BOT_TOKEN`

### Step 6: Get the Signing Secret

1. Go to **Basic Information** > **App Credentials**
2. Copy the **Signing Secret** -- this is `SLACK_SIGNING_SECRET`

### Step 7: Create the Hub Channel

1. In Slack, create a channel called `#amplifier` (or whatever you prefer)
2. **Invite the bot** to the channel: `/invite @SlackBridge`
3. Get the channel ID:
   - Right-click the channel name > "View channel details"
   - The channel ID is at the bottom (starts with `C`)
   - Or use the API: `curl -H "Authorization: Bearer xoxb-..." https://slack.com/api/conversations.list`

### Step 8: Configure Environment

Create `.env` in the distro project root:

```bash
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=fd273...
SLACK_HUB_CHANNEL_ID=C0AELA8PM6C
SLACK_HUB_CHANNEL_NAME=amplifier
SLACK_SOCKET_MODE=true
```

### Step 9: Start the Server

```bash
source .env
uv run python -c "
from pathlib import Path
from amplifier_distro.server.app import create_server
server = create_server(dev_mode=True)
server.discover_apps(Path('src/amplifier_distro/server/apps'))
import uvicorn
uvicorn.run(server.app, host='127.0.0.1', port=8400)
"
```

---

## Lessons Learned (Pain Points and Gotchas)

### 1. slack_bolt Silently Drops Events

**Problem**: The `slack_bolt` library's `AsyncSocketModeHandler` silently
dropped all events in our configuration. No errors, no logs, just silence.
We spent significant time debugging this.

**Solution**: Replaced `slack_bolt` entirely with a direct aiohttp WebSocket
implementation in `socket_mode.py`. This gives us full control over the
connection lifecycle and frame handling. The raw implementation is ~200 lines
and handles: hello, disconnect/reconnect, events_api, and envelope acking.

**Rule**: Don't use slack_bolt for Socket Mode. Our custom adapter is simpler
and actually works.

### 2. Slack Requires Ack Within 3 Seconds

Socket Mode envelopes must be acknowledged within 3 seconds or Slack will
retry delivery. Our adapter acks immediately on receipt, before processing.

### 3. Bot Self-Message Filtering

The bot receives events for its own messages. Without filtering, this creates
infinite loops. We filter by checking `user == self._bot_user_id` in the
socket adapter (before the event even reaches the handler).

### 4. The Channel ID vs Channel Name Distinction

Slack APIs require the channel ID (e.g., `C0AELA8PM6C`), not the channel
name (e.g., `amplifier`). Getting the channel ID from the Slack UI is
non-obvious -- it's buried in "View channel details" at the bottom.

### 5. Scopes Must Be Set BEFORE Installation

If you add scopes after installing the app, you need to **reinstall** it
for the new scopes to take effect. The OAuth & Permissions page will show
a banner saying "You've changed scopes, please reinstall."

### 6. Event Subscriptions Need Specific Scopes

- `message.channels` requires `channels:history`
- `message.groups` requires `groups:history`
- `app_mention` requires `app_mentions:read`

If you subscribe to an event without the matching scope, Slack won't
deliver that event type.

### 7. Private vs Public Channels

We originally wanted the `#amplifier` channel to be private. Private channels
need different scopes (`groups:*` instead of `channels:*`) and different
event subscriptions (`message.groups` instead of `message.channels`).

### 8. Socket Mode App Token vs Bot Token

These are two different tokens with different prefixes:
- **App Token** (`xapp-...`): Used only for the Socket Mode WebSocket handshake
  (`apps.connections.open`). Created in Socket Mode settings.
- **Bot Token** (`xoxb-...`): Used for ALL Slack Web API calls (posting messages,
  reading channels, etc.). Created during app installation.

Both are required for Socket Mode.

### 9. WebSocket Connection Lifecycle

The `apps.connections.open` API returns a WebSocket URL with a one-time ticket.
Each call generates a new URL. On disconnect, you must call the API again for
a fresh URL -- you can't reconnect to the same one.

Our adapter handles this with exponential backoff (1s -> 60s max).

### 10. Reconnect Frames

Slack sends `{"type": "disconnect", "reason": "..."}` frames before dropping
the connection (e.g., for server-side deployments). Our adapter treats these
as graceful reconnect triggers rather than errors.

---

## What Needs to Be Automated (Setup Wizard Vision)

The manual setup above has ~15 steps across two different UIs (Slack admin
and our server). A future install-wizard flow should:

1. **Detect if Slack is configured** by checking for env vars / config file
2. **Guide token collection** with direct links to the right Slack admin pages
3. **Validate tokens** by calling `auth.test` and `conversations.info`
4. **Auto-detect channel ID** from channel name using `conversations.list`
5. **Verify event subscriptions** by checking the app manifest
6. **Test end-to-end** by posting a message and watching for the echo event
7. **Generate .env / config** with all the right values

Ideally this would be a recipe or an interactive CLI flow in `amp-distro setup slack`.

**Slack App Manifest**: Slack supports a declarative app manifest (YAML/JSON)
that can pre-configure scopes, event subscriptions, and Socket Mode in one
shot. Investigate using `https://api.slack.com/apps?new_app=1` with a
manifest URL to make app creation one-click.

Example manifest structure:
```yaml
display_information:
  name: Amplifier Bridge
  description: Connects Slack to Amplifier AI sessions
features:
  bot_user:
    display_name: slackbridge
    always_online: true
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - channels:history
      - channels:read
      - chat:write
      - reactions:write
      - channels:manage
      - channels:join
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.channels
  socket_mode_enabled: true
```

---

## Current State (as of 2026-02-09)

- Socket Mode adapter working end-to-end (events flowing, bot responding)
- 9 commands registered (help, list, projects, new, connect, status, breakout, end, discover)
- Simulator mode working for offline testing
- `BridgeBackend` (connection to real Amplifier sessions) is stubbed but not yet wired
- Session mappings are in-memory only (lost on restart)
- `slack-bolt` is still in pyproject.toml dependencies but unused by Socket Mode

**Next steps**:
1. Wire `BridgeBackend` to real Amplifier sessions via `LocalBridge`
2. Add persistence for session mappings (survive restarts)
3. Build automated setup wizard
4. Handle `interactive` frames (Block Kit button callbacks)
5. Consider removing `slack-bolt` dependency entirely

---

## Environment Variables Reference

| Variable | Prefix | Required For | Description |
|----------|--------|-------------|-------------|
| `SLACK_BOT_TOKEN` | `xoxb-` | All modes | Bot User OAuth Token |
| `SLACK_APP_TOKEN` | `xapp-` | Socket Mode | App-level token (connections:write) |
| `SLACK_SIGNING_SECRET` | (hex) | Events API | HMAC signature verification |
| `SLACK_HUB_CHANNEL_ID` | `C` | All modes | Channel ID for the hub |
| `SLACK_HUB_CHANNEL_NAME` | | Optional | Human-readable name (default: "amplifier") |
| `SLACK_SOCKET_MODE` | | Optional | "true" to enable Socket Mode |
| `SLACK_SIMULATOR_MODE` | | Optional | "true" for offline testing |

---

## Testing

**Unit tests**: `uv run pytest tests/test_slack_bridge.py -v`

All tests use dependency injection -- `MemorySlackClient` + `MockBackend` are
injected via `initialize()`, no real Slack credentials needed.

**Live testing**: Start the server with real credentials in `.env`, send
messages in the Slack channel, watch server logs.

**Simulator**: Start server without credentials (or with `SLACK_SIMULATOR_MODE=true`),
visit `http://localhost:8400/apps/slack/simulator` in a browser.
