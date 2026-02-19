# Fix Zombie Sessions & Test Gaps Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Fix the Slack zombie session bug (#31), align MockBackend with BridgeBackend semantics, and close the session lifecycle test gaps. The zombie bug was independently filed as #31 (P0) and was re-confirmed during the 8-model swarm review of #27 (duplicated logic). #27 is a separate code structure question (deferred); this plan fixes the real bugs.

**Architecture:** Three surgical fixes, no new abstractions. (1) MockBackend.send_message rejects ended sessions with ValueError, matching BridgeBackend. (2) SlackSessionManager.route_message catches ValueError specifically to deactivate dead sessions, matching Web Chat's pattern. (3) New lifecycle tests cover the create->end->send sequence across backend, Slack, and Web Chat. A stale migration note referencing the abandoned SurfaceSessionRegistry PR is removed.

**Tech Stack:** Python 3.12, pytest, asyncio, FastAPI TestClient, unittest.mock

**Swarm review status:** Plan reviewed by 8 models (Opus 4.6, Sonnet 4.6, Opus 4.5, GPT-5.2-pro, GPT-5.3-pro, GPT-5.2, Gemini 2.5 Pro, Gemini 3 Pro). Two blockers and four suggestions incorporated into this revision.

**Out of scope (deferred):**
- Send-after-resume testing — sessions don't currently support explicit resume, so no code path to test. Revisit when resume is implemented.
- `get_session_info` behavioral parity (MockBackend returns inactive info, BridgeBackend returns None) — pre-existing asymmetry, not introduced by this change.

---

## Baseline

- **Branch:** `main` at `c176900`
- **Relevant test files:** `tests/test_services.py`, `tests/test_slack_bridge.py`, `tests/test_web_chat.py`
- **Relevant test results:** 182 passed, 2 failed (pre-existing `TestSocketModeDedup` failures — `ModuleNotFoundError` for `slack_sdk`, not regressions)
- **Run command:** `uv run --extra dev python -m pytest tests/test_services.py tests/test_slack_bridge.py tests/test_web_chat.py -q`
- **All new tests must pass. No new failures allowed.**

---

## Task 1: Fix MockBackend to reject sends to ended sessions

**Commit: Tasks 1a + 1b together (never commit a RED tree)**

**Files:**
- Modify: `tests/test_services.py`
- Modify: `src/amplifier_distro/server/session_backend.py:121-123`

### Step 1a: Add the failing test to `TestMockBackendOperations`

Open `tests/test_services.py`. At the end of class `TestMockBackendOperations` (after the `test_message_history` method, around line 209), add:

```python
    @pytest.mark.asyncio
    async def test_send_to_unknown_session_still_raises(self, backend):
        """Verify existing behavior: truly unknown session IDs raise ValueError."""
        with pytest.raises(ValueError, match="Unknown session"):
            await backend.send_message("completely-fake-id", "hello")
```

### Step 1b: Fix `MockBackend.send_message()`

Open `src/amplifier_distro/server/session_backend.py`. Find lines 121-123:

```python
    async def send_message(self, session_id: str, message: str) -> str:
        if session_id not in self._sessions:
            raise ValueError(f"Unknown session: {session_id}")
```

Replace with:

```python
    async def send_message(self, session_id: str, message: str) -> str:
        info = self._sessions.get(session_id)
        if info is None or not info.is_active:
            raise ValueError(f"Unknown session: {session_id}")
```

This is a 1-line logic change: instead of `session_id not in self._sessions`, we fetch the `SessionInfo` and also reject inactive sessions. This matches `BridgeBackend` semantics where `end_session()` pops the handle, making subsequent `send_message()` calls fail with `ValueError`.

### Step 1c: Run tests to verify

```bash
# New test should pass
uv run --extra dev python -m pytest tests/test_services.py::TestMockBackendOperations::test_send_to_unknown_session_still_raises -v

# All MockBackend tests should pass — no regressions
uv run --extra dev python -m pytest tests/test_services.py -v

# Slack tests should still pass (mapping.is_active guard at line 277 protects them)
uv run --extra dev python -m pytest tests/test_slack_bridge.py -q
```

### Step 1d: Commit

```
fix: MockBackend.send_message rejects ended sessions with ValueError

Aligns MockBackend with BridgeBackend semantics. After end_session(),
send_message() now raises ValueError instead of silently succeeding.
This ensures tests using MockBackend can detect zombie session bugs
that would manifest in production with BridgeBackend.

Part of #31 (zombie session fix) and #27 (test parity gap).
```

---

## Task 2: Fix Slack zombie session bug (with failing test first)

**Commit: Tasks 2a + 2b together (RED + GREEN in one commit)**

**Files:**
- Modify: `tests/test_slack_bridge.py`
- Modify: `src/amplifier_distro/server/apps/slack/sessions.py:284-292`

### Step 2a: Add failing test class at end of `tests/test_slack_bridge.py`

Open `tests/test_slack_bridge.py`. At the very end of the file (after line 1755), add:

```python


# --- Zombie Session Bug Fix Tests ---


class TestZombieSessionFix:
    """Test that dead sessions are deactivated, not left as zombies.

    Bug: route_message() catches ALL exceptions from backend.send_message()
    with a bare 'except Exception' and returns a generic error string, but
    never deactivates the mapping. A session whose backend handle is lost
    (BridgeBackend raises ValueError) persists as is_active=True forever,
    eventually blocking new session creation via max_sessions_per_user.

    Fix: catch ValueError specifically (= session permanently dead),
    deactivate the mapping, and save. Keep the broad except Exception
    for transient errors (network, timeout) where retry may succeed.
    """

    def test_route_message_valueerror_deactivates_mapping(
        self, session_manager, mock_backend
    ):
        """ValueError from backend.send_message deactivates the mapping."""
        from amplifier_distro.server.apps.slack.models import SlackMessage

        # Create a session
        mapping = asyncio.run(
            session_manager.create_session("C1", "t1", "U1", "zombie test")
        )
        assert mapping.is_active is True

        # End the session on the backend (simulates lost handle).
        # After Task 1's fix, MockBackend.send_message raises ValueError
        # for ended sessions — matching BridgeBackend production behavior.
        asyncio.run(mock_backend.end_session(mapping.session_id))

        msg = SlackMessage(
            channel_id="C1", user_id="U1", text="hello", ts="2.0", thread_ts="t1"
        )
        response = asyncio.run(session_manager.route_message(msg))

        # Mapping must be deactivated
        updated = session_manager.get_mapping("C1", "t1")
        assert updated is not None
        assert updated.is_active is False, (
            "Mapping should be deactivated after ValueError from backend"
        )

        # Response should tell the user the session is dead
        assert response is not None
        assert "session has ended" in response.lower()

    def test_route_message_transient_error_keeps_mapping_active(
        self, session_manager, mock_backend
    ):
        """RuntimeError (transient) must NOT deactivate the mapping."""
        from amplifier_distro.server.apps.slack.models import SlackMessage

        asyncio.run(session_manager.create_session("C1", "t1", "U1"))

        # Make the backend raise RuntimeError (= transient failure).
        # Use set_response_fn because we need a non-ValueError exception
        # while the session is still active on the backend.
        def transient_failure(sid, msg):
            raise RuntimeError("network timeout")

        mock_backend.set_response_fn(transient_failure)

        msg = SlackMessage(
            channel_id="C1", user_id="U1", text="hello", ts="2.0", thread_ts="t1"
        )
        response = asyncio.run(session_manager.route_message(msg))

        # Mapping must stay active (transient error, may recover)
        mapping = session_manager.get_mapping("C1", "t1")
        assert mapping is not None
        assert mapping.is_active is True, (
            "Transient errors must not deactivate the mapping"
        )

        # Response should be the generic error
        assert response is not None
        assert "Error" in response

    def test_zombie_session_freed_from_limit(
        self, session_manager, mock_backend, slack_config
    ):
        """After a zombie is deactivated, the user can create a new session."""
        from amplifier_distro.server.apps.slack.models import SlackMessage

        slack_config.max_sessions_per_user = 1

        # Create session (uses the 1 allowed slot)
        mapping_a = asyncio.run(
            session_manager.create_session("C1", "t1", "U1", "session A")
        )

        # Verify limit is hit
        with pytest.raises(ValueError, match="Session limit"):
            asyncio.run(
                session_manager.create_session("C1", "t2", "U1", "session B")
            )

        # Kill the session via backend end (simulates dead handle)
        asyncio.run(mock_backend.end_session(mapping_a.session_id))

        msg = SlackMessage(
            channel_id="C1", user_id="U1", text="ping", ts="3.0", thread_ts="t1"
        )
        asyncio.run(session_manager.route_message(msg))

        # Now the slot should be free — new session should succeed
        mapping_b = asyncio.run(
            session_manager.create_session("C1", "t2", "U1", "session B")
        )
        assert mapping_b.session_id is not None
        assert mapping_b.is_active is True
```

### Step 2b: Verify the zombie test FAILS, then fix `route_message()`

```bash
# This should FAIL (current code has bare except Exception, never deactivates)
uv run --extra dev python -m pytest tests/test_slack_bridge.py::TestZombieSessionFix::test_route_message_valueerror_deactivates_mapping -v
```

Now fix the production code. Open `src/amplifier_distro/server/apps/slack/sessions.py`. Find lines 284-292:

```python
        # Send to backend
        try:
            response = await self._backend.send_message(
                mapping.session_id, message.text
            )
            return response
        except Exception:
            logger.exception(f"Error routing message to session {mapping.session_id}")
            return "Error: Failed to get response from Amplifier session."
```

Replace with:

```python
        # Send to backend
        try:
            response = await self._backend.send_message(
                mapping.session_id, message.text
            )
            return response
        except ValueError:
            # Session is permanently dead (backend can't find or reconnect it).
            # Deactivate the mapping so the user isn't stuck in a zombie loop
            # and their max_sessions_per_user slot is freed.
            mapping.is_active = False
            self._save_sessions()
            logger.warning(
                "Session %s is dead, deactivated mapping for %s",
                mapping.session_id,
                mapping.conversation_key,
            )
            return "Session has ended. Start a new one with `/amp new`."
        except Exception:
            logger.exception(f"Error routing message to session {mapping.session_id}")
            return "Error: Failed to get response from Amplifier session."
```

### Step 2c: Verify all zombie tests pass

```bash
# All three zombie tests should PASS
uv run --extra dev python -m pytest tests/test_slack_bridge.py::TestZombieSessionFix -v

# All Slack tests — no regressions
uv run --extra dev python -m pytest tests/test_slack_bridge.py -q
```

### Step 2d: Commit

```
fix: deactivate Slack session mapping when backend reports session dead

route_message() now catches ValueError specifically (= session permanently
dead) and sets mapping.is_active=False. This prevents zombie sessions from
persisting forever and blocking new session creation via max_sessions_per_user.

Transient errors (RuntimeError, ConnectionError, etc.) still keep the mapping
active so retry can succeed.

Matches the pattern already used by Web Chat (web_chat/__init__.py line 297).

Fixes #31 (P0: zombie session mappings). Also addresses the error
handling inconsistency surfaced by the swarm review of #27.
```

---

## Task 3: Add Web Chat lifecycle tests

**Files:**
- Modify: `tests/test_web_chat.py`

### Step 3a: Add a new test class at the end of the file

Open `tests/test_web_chat.py`. At the very end of the file (after line 305), add:

```python


class TestWebChatSessionLifecycle:
    """Test the full create -> end -> chat lifecycle.

    Web Chat correctly clears _active_session_id on ValueError (line 297-299
    of web_chat/__init__.py). These tests document and guard that behavior.
    """

    def test_chat_after_end_returns_409(self, webchat_client: TestClient):
        """Chat after ending session returns 409 (no active session)."""
        # Create session
        webchat_client.post("/apps/web-chat/api/session", json={})
        # End it
        webchat_client.post("/apps/web-chat/api/end")
        # Chat should fail with 409
        response = webchat_client.post(
            "/apps/web-chat/api/chat",
            json={"message": "hello after end"},
        )
        assert response.status_code == 409
        data = response.json()
        assert data["session_connected"] is False

    def test_chat_valueerror_clears_session(self, webchat_client: TestClient):
        """When backend.send_message raises ValueError, session is cleared.

        This is the Web Chat equivalent of the Slack zombie fix -- it already
        works correctly. This test guards against regression.
        """
        from amplifier_distro.server.services import get_services

        # Create session
        create_resp = webchat_client.post(
            "/apps/web-chat/api/session", json={}
        )
        session_id = create_resp.json()["session_id"]

        # Mark the session as inactive on the backend (simulates lost handle).
        # This is sync-safe: MockBackend has no loop-bound state, so direct
        # mutation avoids asyncio.run() conflicts with TestClient's event loop.
        backend = get_services().backend
        backend._sessions[session_id].is_active = False

        # Chat should get 409 because ValueError triggers session cleanup
        response = webchat_client.post(
            "/apps/web-chat/api/chat",
            json={"message": "hello to dead session"},
        )
        assert response.status_code == 409
        data = response.json()
        assert data["session_connected"] is False

        # Verify session status also shows disconnected
        status = webchat_client.get("/apps/web-chat/api/session").json()
        assert status["connected"] is False
```

### Step 3b: Run the new tests

```bash
uv run --extra dev python -m pytest tests/test_web_chat.py::TestWebChatSessionLifecycle -v
```

Expected: Both tests **PASS**. `test_chat_after_end_returns_409` tests the normal flow. `test_chat_valueerror_clears_session` works because (a) Task 1 made MockBackend raise ValueError for ended sessions, and (b) Web Chat already catches ValueError and clears `_active_session_id`.

### Step 3c: Run all Web Chat tests — no regressions

```bash
uv run --extra dev python -m pytest tests/test_web_chat.py -q
```

### Step 3d: Commit

```
test: add Web Chat session lifecycle tests

Documents and guards the create->end->chat sequence and the ValueError
cleanup path. Web Chat already handles this correctly -- these tests
prevent regression.

Part of #27 test gap closure.
```

---

## Task 4: Add backend contract tests

**Files:**
- Modify: `tests/test_services.py`

### Step 4a: Add a new test class at the end of the file

Open `tests/test_services.py`. At the very end of the file (after line 419), add:

```python


class TestSessionBackendContract:
    """Document the behavioral contract between surfaces and backends.

    These tests codify the exception semantics that all SessionBackend
    implementations must follow:
    - ValueError from send_message = session is permanently dead
    - Surfaces should deactivate their routing entry on ValueError

    Note: test_get_session_info_after_end_shows_inactive is MockBackend-specific.
    BridgeBackend returns None for ended sessions (handle is popped).
    """

    @pytest.fixture
    def backend(self):
        return MockBackend()

    @pytest.mark.asyncio
    async def test_create_end_send_raises_valueerror(self, backend):
        """The canonical lifecycle: create -> end -> send must raise ValueError.

        This is the contract that surfaces (Slack, Web Chat) rely on to detect
        dead sessions. If this test fails, zombie session detection breaks.
        """
        info = await backend.create_session(description="contract test")
        assert info.is_active is True

        await backend.end_session(info.session_id)

        with pytest.raises(ValueError, match="Unknown session"):
            await backend.send_message(info.session_id, "should fail")

    @pytest.mark.asyncio
    async def test_end_session_is_idempotent(self, backend):
        """Ending an already-ended session must not raise."""
        info = await backend.create_session()
        await backend.end_session(info.session_id)
        # Second end should not raise
        await backend.end_session(info.session_id)

    @pytest.mark.asyncio
    async def test_get_session_info_after_end_shows_inactive(self, backend):
        """get_session_info on ended session returns info with is_active=False.

        NOTE: This is MockBackend-specific behavior. BridgeBackend returns None
        for ended sessions because the handle is popped from _sessions.
        """
        info = await backend.create_session()
        await backend.end_session(info.session_id)

        result = await backend.get_session_info(info.session_id)
        assert result is not None
        assert result.is_active is False

    @pytest.mark.asyncio
    async def test_ended_session_not_in_active_list(self, backend):
        """Ended sessions must not appear in list_active_sessions."""
        info = await backend.create_session()
        await backend.end_session(info.session_id)

        active = backend.list_active_sessions()
        active_ids = [s.session_id for s in active]
        assert info.session_id not in active_ids
```

### Step 4b: Run the new tests

```bash
uv run --extra dev python -m pytest tests/test_services.py::TestSessionBackendContract -v
```

Expected: All four tests **PASS** (they all rely on the MockBackend fix from Task 1).

### Step 4c: Run the full services test suite

```bash
uv run --extra dev python -m pytest tests/test_services.py -q
```

### Step 4d: Commit

```
test: add SessionBackend behavioral contract tests

Documents the exception contract that surfaces rely on:
- ValueError from send_message = session permanently dead
- end_session is idempotent
- Ended sessions show is_active=False in info, absent from active list

Part of #27 test gap closure.
```

---

## Task 5: Remove stale migration note

**Files:**
- Modify: `src/amplifier_distro/server/apps/slack/sessions.py:384-386`

### Step 5a: Remove the migration note

Open `src/amplifier_distro/server/apps/slack/sessions.py`. Find lines 383-386 inside the `rekey_mapping` docstring:

```python
        Migration note (PR #49 — SurfaceSessionRegistry): When SurfaceSessionRegistry
        lands, replace the bare _mappings pop-and-reinsert here with a call to
        registry.rekey(old_key, new_key).
```

Delete those three lines entirely. The SurfaceSessionRegistry is not being built (PRs #49 and #50 will be closed). The migration note is stale and misleading.

The `rekey_mapping` docstring should end at line 382:

```python
        Only targets the bare channel_id key. If no such key exists (e.g., the
        session was already thread-scoped), logs a warning and returns safely.
        """
```

### Step 5b: Verify tests still pass

```bash
uv run --extra dev python -m pytest tests/test_slack_bridge.py::TestSlackSessionManager::test_rekey_mapping_moves_bare_key_to_thread_key -v
```

### Step 5c: Commit

```
chore: remove stale SurfaceSessionRegistry migration note

The note in rekey_mapping() referenced PR #49 (SurfaceSessionRegistry)
which is being closed per the 8-model swarm review verdict on #27.
The registry is not being built -- remove the breadcrumb.
```

---

## Task 6: Final verification

**Files:** None (verification only)

### Step 6a: Run all three test files together

```bash
uv run --extra dev python -m pytest tests/test_services.py tests/test_slack_bridge.py tests/test_web_chat.py -q
```

Expected: All tests pass except the 2 pre-existing `TestSocketModeDedup` failures (unchanged from baseline).

### Step 6b: Run the full test suite

```bash
uv run --extra dev python -m pytest tests/ -q
```

Expected: Same as project baseline. No new failures.

### Step 6c: Run code quality checks

```bash
python_check(paths=["src/amplifier_distro/server/session_backend.py", "src/amplifier_distro/server/apps/slack/sessions.py", "tests/test_services.py", "tests/test_slack_bridge.py", "tests/test_web_chat.py"])
```

Expected: No errors. Warnings OK.

---

## Task 7: Issue/PR cleanup

**This task is manual GitHub operations, not code changes.**

### Step 7a: Close PR #49 with comment

Close PR #49 (SurfaceSessionRegistry core) with this comment:

> Closing per the 8-model swarm review of #27. The unanimous verdict: the "duplication" between Slack and Web Chat is ~9 lines of `backend.*()` calls -- everything else is surface-specific policy (routing, persistence, limits, error handling). Extracting a shared registry would force policy alignment where surfaces intentionally diverge.
>
> The real bugs (Slack zombie sessions, MockBackend parity gap, missing lifecycle tests) are being fixed directly.

### Step 7b: Close PR #50 with comment

Close PR #50 (web chat session list) with this comment:

> Closing -- this depends on PR #49 which is being closed per the #27 swarm review.

### Step 7c: Close issue #31

Close issue #31 (P0: Zombie session mappings) with this comment:

> Fixed. `route_message()` now catches `ValueError` specifically and deactivates dead mappings, freeing the user's `max_sessions_per_user` slot. MockBackend also aligned with BridgeBackend so tests can catch this class of bug.

### Step 7d: Update issue #27

Add a comment to issue #27:

> **Swarm review verdict (8 models, unanimous):** Do not extract `SurfaceSessionRegistry`.
>
> The "duplication" is ~9 lines of shared `backend.*()` calls. Everything else (routing, persistence, limits, error handling) is surface-specific policy. A shared registry would be a 250+ line abstraction with a 28:1 abstraction-to-deduplication ratio.
>
> The zombie session bug (#31) that was originally motivating this work has been fixed directly — no shared abstraction needed.
>
> **Trigger to revisit:** When a 3rd surface arrives with composite routing needs (not email — email is inherently one-shot, not session-based).

Relabel the issue: remove `enhancement`, add `deferred`.

---

## Summary

| Task | Type | Files Changed | Tests Added |
|------|------|--------------|-------------|
| 1 | Fix + Test | `session_backend.py`, `test_services.py` | 1 |
| 2 | Fix + Test | `slack/sessions.py`, `test_slack_bridge.py` | 3 |
| 3 | Test | `test_web_chat.py` | 2 |
| 4 | Test | `test_services.py` | 4 |
| 5 | Chore | `slack/sessions.py` | -- |
| 6 | Verify | -- | -- |
| 7 | Cleanup | GitHub (PRs, issue) | -- |

**Commits:** 5 (Tasks 1, 2, 3, 4, 5 — each leaves the tree green)

**Total: 2 production files changed (~6 lines each), 10 new tests, 0 new files created.**

---

## Swarm Review Changelog

Changes incorporated from the 8-model plan review:

| Change | Source | What |
|--------|--------|------|
| **Blocker fix** | Sonnet 4.6 | Test 11: replaced `asyncio.run(backend.end_session())` with direct `backend._sessions[id].is_active = False` to avoid event loop crash in TestClient |
| **Blocker fix** | Sonnet 4.6, Gemini 3 Pro | Test 7: replaced generator-throw lambda hack with `mock_backend.end_session()` to test the actual production chain |
| **Commit structure** | GPT-5.2-pro | Merged RED+GREEN into single commits (never commit a failing test to the tree) |
| **Test dedup** | Sonnet 4.6, GPT-5.2-pro, Gemini 2.5 Pro | Removed duplicate `test_send_after_end_raises_valueerror` from Task 1; contract test in Task 4 covers it |
| **Log improvement** | GPT-5.3-pro | Added `conversation_key` to Slack warning log and use `%s` lazy formatting |
| **Assertion tightened** | Gemini 3 Pro | Changed `"new" or "ended"` to `"session has ended"` in response assertion |
| **Verification** | GPT-5.2-pro | Added `python_check` to Task 6 alongside pytest |
| **Completeness** | GPT-5.2 | Added explicit out-of-scope section for send-after-resume and get_session_info parity |
| **Completeness** | GPT-5.2 | Added note that `test_get_session_info_after_end` is MockBackend-specific |
