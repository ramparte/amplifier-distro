# Fix: Thread Routing Cross-Contamination (Issue #54)

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Prevent two `@amp new` commands in the same Slack channel from overwriting each other's session routing key, causing messages in thread A to be routed to session B.

**Architecture:** The bug lives entirely in the routing table update path. `create_session()` correctly stores sessions under a bare `channel_id` key when no thread exists yet — that key just never gets upgraded after the bot's reply creates the thread. The fix adds a `rekey_mapping()` method to `SlackSessionManager` and calls it from `_handle_command_message()` immediately after `post_message()` returns the new thread's `ts`. No data model changes needed; the composite-key infrastructure already works.

**Tech Stack:** Python 3.12, pytest + asyncio.run(), Starlette, `MemorySlackClient` for in-process testing

> ⚠️ **Scope boundary:** Fix Bug 1 (thread routing) ONLY.
> - Bug 2 (duplicate CWD) → issue #53
> - Bug 3 (transcript overwrite on resume) → issue #52
>
> 🔖 **Future migration note:** When PR #49 (SurfaceSessionRegistry) lands, the
> bare-key pop-and-reinsert pattern in `rekey_mapping()` will need a mechanical
> translation to the registry's `rekey()` API. Leave a comment in the code so
> the PR author can find it.

---

## How the bug happens (read this first)

```
User types /amp new   →  handle_slash_command()  →  create_session("C_HUB", thread_ts=None)
                                                       └─ stored as key "C_HUB"

Bot replies to Slack   →  _handle_command_message()  →  post_message(thread_ts=None)
                                                          returns ts="16000.000001"
                                                          *** ts is currently discarded ***

User types /amp new again  →  create_session("C_HUB", thread_ts=None)
                                └─ stored as key "C_HUB"  ← OVERWRITES session A!

Message arrives in thread A  →  get_mapping("C_HUB", "16000.000001")
                                  ├─ "C_HUB:16000.000001" not found
                                  └─ "C_HUB" found → returns session B  ← WRONG SESSION
```

After the fix, `_handle_command_message()` captures the returned `ts` and calls
`rekey_mapping("C_HUB", "16000.000001")`, which atomically moves the entry from
key `"C_HUB"` to key `"C_HUB:16000.000001"`. The second `/amp new` then creates
a fresh bare-key entry for session B, and the two sessions never collide.

---

## Task 1: Add `rekey_mapping()` to `SlackSessionManager`

**Files:**
- Modify: `tests/test_slack_bridge.py` — add 2 unit tests to `TestSlackSessionManager`
- Modify: `src/amplifier_distro/server/apps/slack/sessions.py` — add `rekey_mapping()` method

---

### Step 1: Write the failing tests

Open `tests/test_slack_bridge.py`. Find the end of the `TestSlackSessionManager`
class (currently the last method is `test_list_user_sessions` ending around line 605).
Add the following two test methods **inside** that class, right after `test_list_user_sessions`:

```python
    def test_rekey_mapping_moves_bare_key_to_thread_key(self, session_manager):
        """rekey_mapping() upgrades bare channel_id key to channel_id:thread_ts."""
        # Simulate a session created before the thread exists (slash command path:
        # thread_ts=None means create_session stores it under the bare channel key).
        asyncio.run(session_manager.create_session("C_HUB", None, "U1", "rekey test"))

        # Precondition: bare key exists, composite key does not.
        assert session_manager.get_mapping("C_HUB") is not None
        assert session_manager.get_mapping("C_HUB", "1234567890.000001") is None

        # The bot has now posted its reply and we know the new thread's ts.
        session_manager.rekey_mapping("C_HUB", "1234567890.000001")

        # Bare key must be gone.
        assert session_manager.get_mapping("C_HUB") is None

        # Composite key must resolve to the same session, with thread_ts updated.
        mapping = session_manager.get_mapping("C_HUB", "1234567890.000001")
        assert mapping is not None
        assert mapping.thread_ts == "1234567890.000001"
        assert mapping.description == "rekey test"

    def test_rekey_mapping_no_op_when_key_missing(self, session_manager):
        """rekey_mapping() is safe when the bare key doesn't exist — no exception."""
        # Should log a warning and return without raising.
        session_manager.rekey_mapping("C_NONEXISTENT", "ts.0")
        assert session_manager.get_mapping("C_NONEXISTENT") is None
```

---

### Step 2: Run the tests — verify they FAIL

```
uv run python -m pytest tests/test_slack_bridge.py::TestSlackSessionManager::test_rekey_mapping_moves_bare_key_to_thread_key tests/test_slack_bridge.py::TestSlackSessionManager::test_rekey_mapping_no_op_when_key_missing -v
```

**Expected output** (both must fail, not error):
```
FAILED tests/test_slack_bridge.py::TestSlackSessionManager::test_rekey_mapping_moves_bare_key_to_thread_key
FAILED tests/test_slack_bridge.py::TestSlackSessionManager::test_rekey_mapping_no_op_when_key_missing
AttributeError: 'SlackSessionManager' object has no attribute 'rekey_mapping'
```

If you see `ERROR` instead of `FAILED`, recheck the indentation — the new methods must be
inside the `TestSlackSessionManager` class, not at module level.

---

### Step 3: Implement `rekey_mapping()` in `sessions.py`

Open `src/amplifier_distro/server/apps/slack/sessions.py`. The file currently ends at
line 369 with the last line of `list_user_sessions()`. Append the new method **inside
the `SlackSessionManager` class**, immediately after `list_user_sessions()`.

The existing `list_user_sessions()` ends with:
```python
    def list_user_sessions(self, user_id: str) -> list[SessionMapping]:
        """List active sessions for a specific user."""
        return [
            m
            for m in self._mappings.values()
            if m.created_by == user_id and m.is_active
        ]
```

Add this directly after it (same indentation level — 4 spaces, inside the class):

```python
    def rekey_mapping(self, channel_id: str, thread_ts: str) -> None:
        """Re-key a bare channel mapping to a composite channel_id:thread_ts key.

        Called immediately after post_message() creates the reply thread for a
        'new' command. Without this upgrade, a second 'new' command in the same
        channel stores its session under the same bare channel_id key, silently
        overwriting the first session's routing entry (issue #54).

        Only targets the bare channel_id key. If no such key exists (e.g., the
        session was already thread-scoped), logs a warning and returns safely.

        Migration note (PR #49 — SurfaceSessionRegistry): When SurfaceSessionRegistry
        lands, replace the bare _mappings pop-and-reinsert here with a call to
        registry.rekey(old_key, new_key).
        """
        mapping = self._mappings.pop(channel_id, None)
        if mapping is None:
            logger.warning(
                f"rekey_mapping: no bare-channel mapping found for {channel_id!r}"
            )
            return

        mapping.thread_ts = thread_ts
        new_key = f"{channel_id}:{thread_ts}"
        self._mappings[new_key] = mapping
        self._save_sessions()
        logger.info(
            f"Re-keyed session {mapping.session_id} "
            f"from {channel_id!r} to {new_key!r}"
        )
```

---

### Step 4: Run the tests — verify they PASS

```
uv run python -m pytest tests/test_slack_bridge.py::TestSlackSessionManager::test_rekey_mapping_moves_bare_key_to_thread_key tests/test_slack_bridge.py::TestSlackSessionManager::test_rekey_mapping_no_op_when_key_missing -v
```

**Expected output:**
```
PASSED tests/test_slack_bridge.py::TestSlackSessionManager::test_rekey_mapping_moves_bare_key_to_thread_key
PASSED tests/test_slack_bridge.py::TestSlackSessionManager::test_rekey_mapping_no_op_when_key_missing
2 passed in ...
```

---

### Step 5: Run the full test suite — verify no regressions

```
uv run python -m pytest tests/ -x -q
```

**Expected:** All existing tests continue to pass. The count increases by exactly 2.
If anything breaks, stop here and investigate before committing.

---

### Step 6: Commit

```
git add src/amplifier_distro/server/apps/slack/sessions.py tests/test_slack_bridge.py
git commit -m "fix: add rekey_mapping() to SlackSessionManager (issue #54)"
```

---

## Task 2: Capture `posted_ts` and call `rekey_mapping()` in `_handle_command_message()`

**Files:**
- Modify: `tests/test_slack_bridge.py` — add `TestThreadRoutingFix` class at the bottom
- Modify: `src/amplifier_distro/server/apps/slack/events.py` — modify `_handle_command_message()`

---

### Step 1: Write the failing integration test

Open `tests/test_slack_bridge.py`. Scroll to the very bottom of the file (currently line 1608).
Add the following new test class after the last line:

```python


# --- Thread Routing Fix Tests (Issue #54) ---


class TestThreadRoutingFix:
    """Regression tests for issue #54: thread routing cross-contamination.

    Bug: Two @amp new commands in the same channel both map to the bare
    channel_id key. The second create_session() overwrites the first's entry,
    so messages in thread A get routed to session B.

    These tests drive through the full SlackEventHandler pipeline (not just
    the session manager) to confirm the wiring between _handle_command_message()
    and rekey_mapping() is correct end-to-end.
    """

    def _make_handler(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        from amplifier_distro.server.apps.slack.events import SlackEventHandler

        return SlackEventHandler(
            slack_client, session_manager, command_handler, slack_config
        )

    def _app_mention_payload(self, text, channel="C_HUB", user="U1", ts="1.0"):
        """Build an app_mention event payload (no thread_ts — top-level command)."""
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

    def test_two_new_commands_in_same_channel_dont_overwrite(
        self, slack_client, session_manager, command_handler, slack_config
    ):
        """Two @amp new commands in the same channel get independent routing keys.

        Before the fix: the second create_session() writes under the same bare
        channel_id key as the first, destroying the first's routing entry. All
        subsequent messages in thread A would silently land in session B.

        After the fix: each session is re-keyed to its own thread_ts immediately
        after the bot posts its reply, so get_mapping(channel, thread_ts_A) and
        get_mapping(channel, thread_ts_B) return two distinct session mappings.

        How we find thread_ts_A and thread_ts_B: when create_thread=True the bot
        calls post_message(thread_ts=None), which makes MemorySlackClient create a
        fresh top-level message. That message's .ts IS the new thread's identifier.
        We read it from slack_client.sent_messages[] after each command.
        """
        handler = self._make_handler(
            slack_client, session_manager, command_handler, slack_config
        )

        # --- First @amp new ---
        asyncio.run(
            handler.handle_event_payload(
                self._app_mention_payload(
                    "<@U_AMP_BOT> new first session", ts="100.000001"
                )
            )
        )
        # The bot's reply for a thread-creating command has thread_ts=None.
        # MemorySlackClient.post_message() assigns and returns a unique ts; that
        # ts becomes the anchor of the new Slack thread.
        assert len(slack_client.sent_messages) >= 1, (
            "Bot must post at least one message in response to @amp new"
        )
        first_reply = slack_client.sent_messages[0]
        assert first_reply.thread_ts is None, (
            "First @amp new reply must start a brand-new thread (thread_ts=None). "
            "If thread_ts is not None the session was already in a thread and the "
            "cross-contamination scenario does not apply."
        )
        thread_ts_A = first_reply.ts

        # --- Second @amp new ---
        asyncio.run(
            handler.handle_event_payload(
                self._app_mention_payload(
                    "<@U_AMP_BOT> new second session", ts="200.000001"
                )
            )
        )
        assert len(slack_client.sent_messages) >= 2, (
            "Bot must post a reply for the second @amp new as well"
        )
        second_reply = slack_client.sent_messages[1]
        assert second_reply.thread_ts is None, (
            "Second @amp new reply must also start a brand-new thread"
        )
        thread_ts_B = second_reply.ts

        # Sanity check: the two threads are distinct (MemorySlackClient auto-increments ts).
        assert thread_ts_A != thread_ts_B

        # --- Verify the routing table ---

        # After both re-keys the bare "C_HUB" entry must not exist.
        # If it does exist, the second /new silently clobbered session A.
        assert session_manager.get_mapping("C_HUB") is None, (
            "Bare 'C_HUB' routing key must be gone after re-keying. "
            "Its presence means the second @amp new overwrote session A's entry."
        )

        # Each thread ts must resolve to its own independent session.
        mapping_A = session_manager.get_mapping("C_HUB", thread_ts_A)
        mapping_B = session_manager.get_mapping("C_HUB", thread_ts_B)

        assert mapping_A is not None, (
            f"No routing entry found for thread_ts_A={thread_ts_A!r}. "
            "Session A was lost — this is the cross-contamination bug."
        )
        assert mapping_B is not None, (
            f"No routing entry found for thread_ts_B={thread_ts_B!r}. "
            "Session B was not registered correctly."
        )
        assert mapping_A.session_id != mapping_B.session_id, (
            "Session A and session B must be different objects. "
            "If they match, session A's routing entry was overwritten by session B."
        )
```

---

### Step 2: Run the test — verify it FAILS

```
uv run python -m pytest tests/test_slack_bridge.py::TestThreadRoutingFix::test_two_new_commands_in_same_channel_dont_overwrite -v
```

**Expected failure message:**
```
FAILED tests/test_slack_bridge.py::TestThreadRoutingFix::test_two_new_commands_in_same_channel_dont_overwrite
AssertionError: Bare 'C_HUB' routing key must be gone after re-keying. ...
```

The test must fail on the `get_mapping("C_HUB") is None` assertion, not before it.
If it fails earlier (e.g., `len(sent_messages) >= 1` is False), something is wrong
with the test setup — stop and investigate before continuing.

---

### Step 3: Fix `_handle_command_message()` in `events.py`

Open `src/amplifier_distro/server/apps/slack/events.py`. Find `_handle_command_message()`
(starts at line 204). You will replace the block from `# Determine where to reply`
through the final `await self._safe_react(...)` call (lines 222–261).

**Find this exact block** (copy it character-for-character to make sure you have the right place):

```python
        # Determine where to reply
        reply_thread = message.thread_ts or message.ts
        if result.create_thread:
            reply_thread = None  # Will create a new thread from the reply

        # Send the response, with fallback for blocks failures
        try:
            if result.blocks:
                await self._client.post_message(
                    message.channel_id,
                    text=result.text or "Amplifier",
                    thread_ts=reply_thread,
                    blocks=result.blocks,
                )
            elif result.text:
                for chunk in SlackFormatter.split_message(result.text):
                    await self._client.post_message(
                        message.channel_id,
                        text=chunk,
                        thread_ts=reply_thread,
                    )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to send blocks, falling back to plain text", exc_info=True
            )
            # Fallback: send blocks content as plain text
            fallback = result.text or self._blocks_to_plaintext(result.blocks)
            if fallback:
                try:
                    for chunk in SlackFormatter.split_message(fallback):
                        await self._client.post_message(
                            message.channel_id,
                            text=chunk,
                            thread_ts=reply_thread,
                        )
                except Exception:
                    logger.exception("Fallback plain-text send also failed")

        # Done reaction (best-effort, never fatal)
        await self._safe_react(message.channel_id, message.ts, "white_check_mark")
```

**Replace it with this** (three changes: add `posted_ts` declaration, capture the
return value of every `post_message()` call, and add the `rekey_mapping()` call
after the try/except block):

```python
        # Determine where to reply
        reply_thread = message.thread_ts or message.ts
        if result.create_thread:
            reply_thread = None  # Will create a new thread from the reply

        # Send the response, with fallback for blocks failures.
        # Capture the ts of the first post_message() so we can re-key the session
        # mapping from bare channel_id to channel_id:thread_ts (issue #54).
        posted_ts: str | None = None
        try:
            if result.blocks:
                posted_ts = await self._client.post_message(
                    message.channel_id,
                    text=result.text or "Amplifier",
                    thread_ts=reply_thread,
                    blocks=result.blocks,
                )
            elif result.text:
                for chunk in SlackFormatter.split_message(result.text):
                    ts = await self._client.post_message(
                        message.channel_id,
                        text=chunk,
                        thread_ts=reply_thread,
                    )
                    if posted_ts is None:
                        posted_ts = ts  # Capture ts of the first (thread-creating) post
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to send blocks, falling back to plain text", exc_info=True
            )
            # Fallback: send blocks content as plain text
            fallback = result.text or self._blocks_to_plaintext(result.blocks)
            if fallback:
                try:
                    for chunk in SlackFormatter.split_message(fallback):
                        ts = await self._client.post_message(
                            message.channel_id,
                            text=chunk,
                            thread_ts=reply_thread,
                        )
                        if posted_ts is None:
                            posted_ts = ts
                except Exception:
                    logger.exception("Fallback plain-text send also failed")

        # Re-key the session mapping from bare channel_id to the new thread_ts.
        # This prevents a second /new command from overwriting the first session's
        # routing entry (issue #54).
        if result.create_thread and posted_ts is not None:
            self._sessions.rekey_mapping(message.channel_id, posted_ts)

        # Done reaction (best-effort, never fatal)
        await self._safe_react(message.channel_id, message.ts, "white_check_mark")
```

> **Diff summary:** 6 lines changed, 8 lines added.
> - `posted_ts: str | None = None` — declared before the try block
> - `await self._client.post_message(...)` → `posted_ts = await ...` (blocks branch)
> - `await self._client.post_message(...)` → `ts = await ...; if posted_ts is None: posted_ts = ts` (text branch, both primary and fallback)
> - New block after the try/except: `if result.create_thread and posted_ts is not None: self._sessions.rekey_mapping(...)`

---

### Step 4: Run the integration test — verify it PASSES

```
uv run python -m pytest tests/test_slack_bridge.py::TestThreadRoutingFix::test_two_new_commands_in_same_channel_dont_overwrite -v
```

**Expected output:**
```
PASSED tests/test_slack_bridge.py::TestThreadRoutingFix::test_two_new_commands_in_same_channel_dont_overwrite
1 passed in ...
```

---

### Step 5: Run the full test suite — verify no regressions

```
uv run python -m pytest tests/ -x -q
```

**Expected:** All tests pass. The count increases by exactly 3 compared to the
original baseline (2 unit tests from Task 1 + 1 integration test from Task 2).

Pay particular attention to:
- `TestSlackEventHandler` — all existing event handler tests must still pass
- `TestEventPipelineIntegration` — `test_new_via_event` must still pass
- `TestSlackSessionManager` — all session routing tests must still pass

If `test_new_via_event` fails, the change to `_handle_command_message()` introduced
a regression in the normal (non-cross-contamination) new-session path. Stop and
investigate.

---

### Step 6: Commit

```
git add src/amplifier_distro/server/apps/slack/events.py tests/test_slack_bridge.py
git commit -m "fix: rekey session mapping after thread creation, prevents cross-contamination (issue #54)"
```

---

## Done — verify the complete fix

Run the targeted tests one final time to confirm both tasks are green together:

```
uv run python -m pytest \
  tests/test_slack_bridge.py::TestSlackSessionManager::test_rekey_mapping_moves_bare_key_to_thread_key \
  tests/test_slack_bridge.py::TestSlackSessionManager::test_rekey_mapping_no_op_when_key_missing \
  tests/test_slack_bridge.py::TestThreadRoutingFix::test_two_new_commands_in_same_channel_dont_overwrite \
  -v
```

**Expected:**
```
PASSED ...test_rekey_mapping_moves_bare_key_to_thread_key
PASSED ...test_rekey_mapping_no_op_when_key_missing
PASSED ...test_two_new_commands_in_same_channel_dont_overwrite
3 passed in ...
```

---

## Quick reference: what changed and why

| File | Change | Why |
|------|--------|-----|
| `sessions.py` | Added `rekey_mapping(channel_id, thread_ts)` | Provides the atomic re-key operation: pop bare key, update `mapping.thread_ts`, re-insert under composite key, persist |
| `events.py` | Captured `posted_ts` from `post_message()` and added `rekey_mapping()` call | Wires the re-key into the message-send path, triggered only when `result.create_thread is True` (i.e., `/new` from a top-level channel message with `thread_per_session=True`) |
| `tests/test_slack_bridge.py` | 2 unit tests + 1 integration test | Unit tests pin the `rekey_mapping()` contract; integration test reproduces the exact cross-contamination scenario from the bug report |
