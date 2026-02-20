# Web Chat Session Resume — LLM Context Restoration

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** When a user resumes a web-chat session, the LLM immediately receives full transcript context — regardless of whether the server was restarted between sessions.

**Architecture:** `WebChatSessionManager.resume_session()` is promoted from sync to async and calls `await self._backend.resume_session(session_id, working_dir)` after updating the store. `BridgeBackend` gains an explicit `resume_session()` that calls the already-existing `_reconnect()` infrastructure (which injects transcript context). `working_dir` is stored in `WebChatSession.extra` at creation time so the manager can pass it to the backend on resume without reading disk.

**Tech Stack:** Python 3.12, FastAPI, asyncio, pytest. No new dependencies.

---

## Background (read this once, refer back as needed)

The bug: `WebChatSessionManager.resume_session()` only updates the JSON store — it makes no backend call. `BridgeBackend.send_message()` has lazy `_reconnect()` logic that fires on the first message after a restart, but it may fail silently (catches `ValueError` → deactivates the session). The LLM ends up starting fresh.

The fix: call `backend.resume_session()` eagerly on resume, not lazily on send. The bridge infrastructure to inject transcripts already exists in `_reconnect()` — we just need to call it at the right time.

**Scope:** Web-chat side only. `SessionBackend` protocol (the 5-method `Protocol` class at line 38) is **NOT modified**. YAGNI — other surfaces can join later.

---

## Files involved

| File | What changes |
|------|-------------|
| `src/amplifier_distro/server/session_backend.py` | Add `resume_session()` to `MockBackend` and `BridgeBackend` |
| `src/amplifier_distro/server/apps/web_chat/__init__.py` | Store `working_dir` in `extra`; make `resume_session()` async; `await` it in route |
| `tests/test_web_chat_store.py` | New `TestMockBackendResumeSession` class; new manager test; update 3 existing tests |
| `tests/test_web_chat.py` | New test in `TestWebChatSessionResumeAPI` |

---

## Task 1: Store `working_dir` in `extra` at session creation

**Files:**
- Modify: `src/amplifier_distro/server/apps/web_chat/__init__.py`
- Test: `tests/test_web_chat_store.py` (inside `TestWebChatSessionManager`)

### Step 1: Write the failing test

Open `tests/test_web_chat_store.py`. Find the `TestWebChatSessionManager` class. Locate `test_create_session_stores_project_id_in_extra` (around line 314). Add this new test **immediately after it**:

```python
def test_create_session_stores_working_dir_in_extra(self):
    manager, _ = self._make_manager()
    info = asyncio.run(
        manager.create_session(working_dir="/tmp/myproject", description="test")
    )
    stored = manager._store.get(info.session_id)
    assert stored is not None
    assert stored.extra.get("working_dir") == "/tmp/myproject"
```

### Step 2: Run the test — confirm FAIL

```
cd /Users/samule/repo/distro-pr-50
pytest tests/test_web_chat_store.py::TestWebChatSessionManager::test_create_session_stores_working_dir_in_extra -v
```

Expected: **FAIL** — `AssertionError: assert None == '/tmp/myproject'` (key not in `extra` yet).

### Step 3: Write minimal implementation

Open `src/amplifier_distro/server/apps/web_chat/__init__.py`. Find this block at line ~179:

```python
        self._store.add(
            info.session_id,
            description,
            extra={"project_id": info.project_id},
        )
```

Replace it with:

```python
        self._store.add(
            info.session_id,
            description,
            extra={
                "project_id": info.project_id,
                "working_dir": info.working_dir,
            },
        )
```

> **Why `info.working_dir` not `str(info.working_dir)`?** `SessionInfo.working_dir` is already declared as `str`, so no conversion needed.

### Step 4: Run the test — confirm PASS

```
pytest tests/test_web_chat_store.py::TestWebChatSessionManager::test_create_session_stores_working_dir_in_extra -v
```

Expected: **PASS**.

### Step 5: Run the full test suite for this file — confirm no regressions

```
pytest tests/test_web_chat_store.py -v
```

Expected: all tests **PASS**.

### Step 6: Commit

```
git add src/amplifier_distro/server/apps/web_chat/__init__.py tests/test_web_chat_store.py
git commit -m "feat: store working_dir in WebChatSession.extra at creation time"
```

---

## Task 2: Add `resume_session()` to `MockBackend`

**Files:**
- Modify: `src/amplifier_distro/server/session_backend.py`
- Test: `tests/test_web_chat_store.py` (new `TestMockBackendResumeSession` class)

### Step 1: Write the failing tests

Open `tests/test_web_chat_store.py`. Add this new class **at the very end of the file**, after `TestWebChatSessionManager`:

```python
class TestMockBackendResumeSession:
    """Verify MockBackend.resume_session() records the call correctly."""

    def test_resume_session_records_call(self):
        from amplifier_distro.server.session_backend import MockBackend

        backend = MockBackend()
        asyncio.run(backend.resume_session("sess-001", "/tmp/myproject"))
        assert len(backend.calls) == 1
        call = backend.calls[0]
        assert call["method"] == "resume_session"
        assert call["session_id"] == "sess-001"
        assert call["working_dir"] == "/tmp/myproject"

    def test_resume_session_returns_none(self):
        from amplifier_distro.server.session_backend import MockBackend

        backend = MockBackend()
        result = asyncio.run(backend.resume_session("sess-001", "~"))
        assert result is None

    def test_resume_session_does_not_affect_existing_sessions(self):
        """resume_session is a no-op from the MockBackend's session state perspective."""
        from amplifier_distro.server.session_backend import MockBackend

        backend = MockBackend()
        asyncio.run(backend.create_session(working_dir="~", description="existing"))
        session_id = backend.calls[0]["result"]
        before_count = len(backend._sessions)

        asyncio.run(backend.resume_session(session_id, "~"))

        # No new sessions were created
        assert len(backend._sessions) == before_count
```

### Step 2: Run the tests — confirm FAIL

```
pytest tests/test_web_chat_store.py::TestMockBackendResumeSession -v
```

Expected: **FAIL** — `AttributeError: 'MockBackend' object has no attribute 'resume_session'`.

### Step 3: Write minimal implementation

Open `src/amplifier_distro/server/session_backend.py`. Find the `get_message_history` method at the **end of the `MockBackend` class** (line ~157):

```python
    def get_message_history(self, session_id: str) -> list[dict[str, str]]:
        """Get the full message history for a session (testing helper)."""
        return self._message_history.get(session_id, [])
```

Add this method **directly after it** (still inside `MockBackend`, before the blank line that precedes `class BridgeBackend`):

```python
    async def resume_session(self, session_id: str, working_dir: str) -> None:
        """No-op resume for testing. Records the call for assertion."""
        self.calls.append(
            {
                "method": "resume_session",
                "session_id": session_id,
                "working_dir": working_dir,
            }
        )
```

### Step 4: Run the tests — confirm PASS

```
pytest tests/test_web_chat_store.py::TestMockBackendResumeSession -v
```

Expected: all 3 tests **PASS**.

### Step 5: Run the full test suite for this file — confirm no regressions

```
pytest tests/test_web_chat_store.py -v
```

Expected: all tests **PASS**.

### Step 6: Commit

```
git add src/amplifier_distro/server/session_backend.py tests/test_web_chat_store.py
git commit -m "feat: add resume_session() no-op to MockBackend"
```

---

## Task 3: Add `resume_session()` to `BridgeBackend`

**Files:**
- Modify: `src/amplifier_distro/server/session_backend.py`

> **Why no unit test here?** `BridgeBackend` requires a real `LocalBridge` and running Amplifier sessions — that's integration territory. The unit coverage comes from `MockBackend` (Task 2) and the API-level test in Task 5 which exercises the full path via `MockBackend`.

### Step 1: There is no failing test to write for this task

The behavior is verified end-to-end in Task 5. Proceed directly to implementation.

### Step 2: Write the implementation

Open `src/amplifier_distro/server/session_backend.py`. Find the **`list_active_sessions` method at the very end of `BridgeBackend`** (around line 254):

```python
    def list_active_sessions(self) -> list[SessionInfo]:
        return [
            SessionInfo(
                session_id=h.session_id,
                project_id=h.project_id,
                working_dir=str(h.working_dir),
            )
            for h in self._sessions.values()
        ]
```

Add this method **directly after it** (end of file):

```python
    async def resume_session(self, session_id: str, working_dir: str) -> None:
        """Restore the LLM context for a session after a server restart.

        Calls _reconnect() which reads transcript.jsonl and injects the full
        history as context. Safe to call even if the session handle is already
        cached (no-op in that case — _reconnect is only called when handle is
        missing, so we check first).

        Args:
            session_id: The Amplifier session ID to resume.
            working_dir: The working directory (used by the bridge to locate
                the session directory if needed).
        """
        if self._sessions.get(session_id) is None:
            await self._reconnect(session_id)
```

> **Why the `if` guard?** If the server was NOT restarted, the handle is already cached. Calling `_reconnect` would try to resume an already-live session, which is unnecessary. The guard makes this safe to call unconditionally.

> **Note on errors:** If `_reconnect` fails (session data lost, corrupt transcript, etc.), it raises `ValueError`. The route's existing `except ValueError` handler will return a 404 to the client. This is the correct behaviour — can't resume a session that can't be found.

### Step 3: Verify the file is syntactically correct

```
python -c "import ast; ast.parse(open('src/amplifier_distro/server/session_backend.py').read()); print('OK')"
```

Expected: `OK`

### Step 4: Run the backend module's tests — confirm no regressions

```
pytest tests/test_web_chat_store.py::TestMockBackendResumeSession -v
```

Expected: all **PASS** (we didn't touch MockBackend).

### Step 5: Commit

```
git add src/amplifier_distro/server/session_backend.py
git commit -m "feat: add resume_session() to BridgeBackend — calls _reconnect() for transcript injection"
```

---

## Task 4: Make `WebChatSessionManager.resume_session()` async

**Files:**
- Modify: `src/amplifier_distro/server/apps/web_chat/__init__.py`
- Test: `tests/test_web_chat_store.py`

There are **two sub-steps** here: (a) add the new backend-call test that will FAIL, then (b) update the three existing tests that call `resume_session()` synchronously, then (c) implement.

### Step 1: Write the NEW failing test

Open `tests/test_web_chat_store.py`. Find the `TestWebChatSessionManager` class. Locate `test_resume_session_deactivates_current` (the last test in the `resume_session()` section, around line 425). Add this new test **directly after it**:

```python
    def test_resume_session_calls_backend(self):
        """resume_session() must call backend.resume_session() with the correct args."""
        manager, backend = self._make_manager()
        info = asyncio.run(
            manager.create_session(working_dir="/tmp/proj", description="test")
        )
        # Clear the create_session call from the log so we can isolate the resume call
        backend.calls.clear()

        asyncio.run(manager.resume_session(info.session_id))

        resume_calls = [c for c in backend.calls if c["method"] == "resume_session"]
        assert len(resume_calls) == 1
        assert resume_calls[0]["session_id"] == info.session_id
        assert resume_calls[0]["working_dir"] == "/tmp/proj"
```

### Step 2: Run the new test — confirm FAIL

```
pytest tests/test_web_chat_store.py::TestWebChatSessionManager::test_resume_session_calls_backend -v
```

Expected: **FAIL** — `TypeError: object bool can't be used in 'await' expression` (or similar — `resume_session` is still sync and returns a `WebChatSession`, not a coroutine). The asyncio.run() call itself will fail because the method is sync.

> If pytest complains that there's no test with that name, double-check the indentation — the method must be inside `TestWebChatSessionManager`, not at module level.

### Step 3: Update the three existing tests that call `resume_session()` synchronously

These tests currently work because `resume_session` is sync. Once we make it async, they will fail unless we wrap them in `asyncio.run()`. Update them now so they pass in both the before and after states.

Find and replace these three tests in `TestWebChatSessionManager`:

**Test 1** — `test_resume_session_raises_for_unknown_id` (around line 408):

Old:
```python
    def test_resume_session_raises_for_unknown_id(self):
        manager, _ = self._make_manager()
        with pytest.raises(ValueError, match="not found"):
            manager.resume_session("no-such-id")
```

New:
```python
    def test_resume_session_raises_for_unknown_id(self):
        manager, _ = self._make_manager()
        with pytest.raises(ValueError, match="not found"):
            asyncio.run(manager.resume_session("no-such-id"))
```

**Test 2** — `test_resume_session_reactivates_inactive_session` (around line 413):

Old:
```python
        # Resume first
        resumed = manager.resume_session(info1.session_id)
        assert resumed.is_active is True
        assert manager.active_session_id == info1.session_id
```

New:
```python
        # Resume first
        resumed = asyncio.run(manager.resume_session(info1.session_id))
        assert resumed.is_active is True
        assert manager.active_session_id == info1.session_id
```

**Test 3** — `test_resume_session_deactivates_current` (around line 425):

Old:
```python
        manager.resume_session(info1.session_id)
        # Second session should be deactivated
```

New:
```python
        asyncio.run(manager.resume_session(info1.session_id))
        # Second session should be deactivated
```

### Step 4: Run the three updated existing tests — confirm they still PASS

```
pytest tests/test_web_chat_store.py::TestWebChatSessionManager::test_resume_session_raises_for_unknown_id tests/test_web_chat_store.py::TestWebChatSessionManager::test_resume_session_reactivates_inactive_session tests/test_web_chat_store.py::TestWebChatSessionManager::test_resume_session_deactivates_current -v
```

Expected: all 3 **PASS** (the method is still sync, so `asyncio.run()` on a non-coroutine will raise `ValueError: a coroutine was expected`... 

> **Wait — important:** `asyncio.run()` requires a coroutine. If we call `asyncio.run(manager.resume_session("id"))` while `resume_session` is still **sync**, `asyncio.run()` will raise `ValueError: a coroutine was expected`. So these 3 tests will actually **FAIL** after Step 3 until we do the implementation in Step 5. That's fine — we're in RED state. Proceed to Step 5.

### Step 5: Implement — make `resume_session()` async

Open `src/amplifier_distro/server/apps/web_chat/__init__.py`. Find the `resume_session` method (around line 220):

```python
    def resume_session(self, session_id: str) -> WebChatSession:
        """Switch active session to session_id.

        Deactivates the current active session (store only — backend stays alive).
        If session_id is already active, refreshes its last_active
        timestamp (idempotent).
        Raises ValueError if session_id is not found.
        """
        if self._store.get(session_id) is None:
            raise ValueError(f"Session {session_id!r} not found")

        # Deactivate current if it's a different session
        current = self._store.active_session()
        if current and current.session_id != session_id:
            self._store.deactivate(current.session_id)

        return self._store.reactivate(session_id)
```

Replace it entirely with:

```python
    async def resume_session(self, session_id: str) -> WebChatSession:
        """Switch active session to session_id and restore LLM context.

        Deactivates the current active session (store only — backend stays alive).
        Calls backend.resume_session() to inject transcript history into the LLM
        context so the model is not starting fresh after a server restart.
        If session_id is already active, still calls the backend (idempotent —
        BridgeBackend guards against double-reconnect).
        Raises ValueError if session_id is not found.
        """
        store_session = self._store.get(session_id)
        if store_session is None:
            raise ValueError(f"Session {session_id!r} not found")

        # Deactivate current if it's a different session
        current = self._store.active_session()
        if current and current.session_id != session_id:
            self._store.deactivate(current.session_id)

        result = self._store.reactivate(session_id)

        # Restore LLM context by reconnecting on the backend.
        # working_dir comes from extra (stored at creation time in Task 1).
        # Falls back to "~" for sessions created before this change.
        working_dir = store_session.extra.get("working_dir", "~")
        await self._backend.resume_session(session_id, working_dir)

        return result
```

### Step 6: Run ALL four resume-related tests — confirm all PASS

```
pytest tests/test_web_chat_store.py::TestWebChatSessionManager::test_resume_session_raises_for_unknown_id tests/test_web_chat_store.py::TestWebChatSessionManager::test_resume_session_reactivates_inactive_session tests/test_web_chat_store.py::TestWebChatSessionManager::test_resume_session_deactivates_current tests/test_web_chat_store.py::TestWebChatSessionManager::test_resume_session_calls_backend -v
```

Expected: all 4 **PASS**.

### Step 7: Run the full store test suite — confirm no regressions

```
pytest tests/test_web_chat_store.py -v
```

Expected: all tests **PASS**.

### Step 8: Commit

```
git add src/amplifier_distro/server/apps/web_chat/__init__.py tests/test_web_chat_store.py
git commit -m "feat: make WebChatSessionManager.resume_session() async — calls backend for LLM context"
```

---

## Task 5: Update route and add API-level test

**Files:**
- Modify: `src/amplifier_distro/server/apps/web_chat/__init__.py`
- Test: `tests/test_web_chat.py` (inside `TestWebChatSessionResumeAPI`)

### Step 1: Write the failing test

Open `tests/test_web_chat.py`. Find the `TestWebChatSessionResumeAPI` class. Locate `test_resume_currently_active_session_is_idempotent` (the last test in the class, around line 524). Add this new test **directly after it**:

```python
    def test_resume_calls_backend_resume_session(self, webchat_client: TestClient):
        """POST /api/session/resume must call backend.resume_session() for LLM context."""
        from amplifier_distro.server.services import get_services
        from amplifier_distro.server.session_backend import MockBackend

        # Create two sessions so the first is inactive (can be resumed)
        create1 = webchat_client.post(
            "/apps/web-chat/api/session",
            json={"working_dir": "/tmp/proj1", "description": "session one"},
        )
        session_id = create1.json()["session_id"]
        webchat_client.post("/apps/web-chat/api/session", json={})

        # Inspect the backend (MockBackend in dev mode)
        backend = get_services().backend
        assert isinstance(backend, MockBackend), "Expected MockBackend in dev mode"
        backend.calls.clear()  # isolate calls from this point forward

        # Resume the first session
        response = webchat_client.post(
            "/apps/web-chat/api/session/resume",
            json={"session_id": session_id},
        )
        assert response.status_code == 200

        # Verify backend.resume_session() was called with the right args
        resume_calls = [c for c in backend.calls if c["method"] == "resume_session"]
        assert len(resume_calls) == 1, (
            f"Expected exactly 1 resume_session call, got {len(resume_calls)}. "
            f"All calls: {backend.calls}"
        )
        assert resume_calls[0]["session_id"] == session_id
        assert resume_calls[0]["working_dir"] == "/tmp/proj1"
```

### Step 2: Run the test — confirm FAIL

```
pytest tests/test_web_chat.py::TestWebChatSessionResumeAPI::test_resume_calls_backend_resume_session -v
```

Expected: **FAIL** — the route currently calls `manager.resume_session(session_id)` synchronously (no `await`), which after Task 4 now returns a coroutine object instead of executing. FastAPI may raise a `RuntimeError` or the test may see an unexpected 500. Either way, the backend call is never made.

> If FastAPI wraps the coroutine and the response is still 200 (some async frameworks are forgiving), the test will fail on the assertion `assert len(resume_calls) == 1` because no backend call was recorded.

### Step 3: Update the route

Open `src/amplifier_distro/server/apps/web_chat/__init__.py`. Find the `resume_session` route (around line 482):

```python
    try:
        manager = _get_manager()
        session = manager.resume_session(session_id)
        return JSONResponse(
```

Replace `manager.resume_session(session_id)` with `await manager.resume_session(session_id)`:

```python
    try:
        manager = _get_manager()
        session = await manager.resume_session(session_id)
        return JSONResponse(
```

> That is the only change in the route. The route function is already `async def resume_session(request: Request)` so `await` is valid there.

### Step 4: Run the new test — confirm PASS

```
pytest tests/test_web_chat.py::TestWebChatSessionResumeAPI::test_resume_calls_backend_resume_session -v
```

Expected: **PASS**.

### Step 5: Run the full `TestWebChatSessionResumeAPI` class — confirm no regressions

```
pytest tests/test_web_chat.py::TestWebChatSessionResumeAPI -v
```

Expected: all tests **PASS**.

### Step 6: Run both test files in full — final green bar

```
pytest tests/test_web_chat_store.py tests/test_web_chat.py -v
```

Expected: all tests **PASS**. The output should list every test passing — no skips, no failures.

### Step 7: Commit

```
git add src/amplifier_distro/server/apps/web_chat/__init__.py tests/test_web_chat.py
git commit -m "feat: await manager.resume_session() in route — LLM context now restored on resume"
```

---

## Final verification

Run the complete test suite to confirm nothing outside the changed files was disturbed:

```
cd /Users/samule/repo/distro-pr-50
pytest -v
```

Expected: all tests **PASS**. No new failures anywhere.

---

## Summary of all changes

| File | What was changed |
|------|-----------------|
| `src/amplifier_distro/server/session_backend.py` | Added `MockBackend.resume_session()` — records call to `self.calls`, returns `None` |
| `src/amplifier_distro/server/session_backend.py` | Added `BridgeBackend.resume_session()` — calls `_reconnect()` if handle is missing |
| `src/amplifier_distro/server/apps/web_chat/__init__.py` | `create_session()`: added `"working_dir": info.working_dir` to `extra` dict |
| `src/amplifier_distro/server/apps/web_chat/__init__.py` | `resume_session()`: promoted to `async`, added `await self._backend.resume_session(...)` call |
| `src/amplifier_distro/server/apps/web_chat/__init__.py` | Route `POST /api/session/resume`: changed `manager.resume_session(...)` to `await manager.resume_session(...)` |
| `tests/test_web_chat_store.py` | New `TestMockBackendResumeSession` class (3 tests) |
| `tests/test_web_chat_store.py` | `TestWebChatSessionManager`: new `test_resume_session_calls_backend` test |
| `tests/test_web_chat_store.py` | `TestWebChatSessionManager`: updated 3 existing resume tests to use `asyncio.run()` |
| `tests/test_web_chat.py` | `TestWebChatSessionResumeAPI`: new `test_resume_calls_backend_resume_session` test |
