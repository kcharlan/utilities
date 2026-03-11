# Cleanup Audit — 2026-03-10

Fourth audit pass of the Cognitive Switchyard project, following three prior passes that addressed shell script precedence bugs, missing env propagation, error handling gaps, and merge safety.

## Assumptions

- **Language**: Python 3.11+ with `from __future__ import annotations`
- **Deployment**: Single-user, local-first; single process with background threads
- **Concurrency**: Multiple worker subprocesses, parallel planners via ThreadPoolExecutor; single SQLite database with WAL mode
- **Scale**: Dozens of tasks per session; not designed for hundreds of concurrent sessions
- **API Surface**: FastAPI REST + WebSocket, accessed from embedded React SPA on localhost
- **Error Handling**: Expect graceful degradation; recovery system handles crash/restart scenarios

---

## Findings

### [Correctness] Finding #1: `get_session` 404 missing on most endpoints

- **Severity**: Medium
- **Category**: Correctness & Safety
- **Evidence**:
  - `server.py:411-418` — `get_session` endpoint calls `store.get_session()` which raises `KeyError` on unknown session
  - `server.py:451-456` — `get_task_detail` calls `_ensure_session_exists` then `store.get_task()` which raises `KeyError`
  - Multiple endpoints catch `KeyError` from the store but FastAPI converts uncaught `KeyError` to HTTP 500
- **Impact**: Requesting a nonexistent session ID returns 500 instead of 404 on `GET /api/sessions/{session_id}`, `GET /api/sessions/{session_id}/tasks/{task_id}`, and others. The `_ensure_session_exists` helper is used on some endpoints but not all.
- **Recommended Fix**: Add a FastAPI exception handler that maps `KeyError` to 404:
  ```python
  @app.exception_handler(KeyError)
  async def key_error_handler(request, exc):
      return JSONResponse(status_code=404, content={"detail": str(exc)})
  ```
  Or alternatively, wrap each endpoint with try/except. The exception handler approach is simpler and catches all cases consistently.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: `GET /api/sessions/nonexistent` returns 404; `GET /api/sessions/x/tasks/y` returns 404 for missing task; verify with existing test patterns.

---

### [Correctness] Finding #2: `reveal-file` endpoint uses GET for a side-effecting action

- **Severity**: Low
- **Category**: Best Practices & Maintainability
- **Evidence**: `server.py:573-580` — `GET /api/sessions/{session_id}/reveal-file` opens a Finder/file manager window. Similarly `GET /api/sessions/{session_id}/open-intake` at line 566.
- **Impact**: GET should be idempotent and side-effect-free. Browser prefetch, link previews, or proxy caching could trigger unintended file manager launches.
- **Recommended Fix**: Change to `POST`. Update frontend fetch calls.
- **Effort**: S
- **Risk**: Low (changes API method; frontend must match)
- **Acceptance Criteria**: Verify frontend calls updated; GET returns 405.

---

### [Robustness] Finding #3: `_phase_enriched_log_event` re-reads session and pack manifest per log line

- **Severity**: Medium
- **Category**: Performance / Robustness
- **Evidence**: `server.py:299-322` — `_phase_enriched_log_event` calls `self.store.get_session()` and `load_pack_manifest()` for every log line event, which means SQLite reads + YAML parsing per output line.
- **Impact**: Under high worker output rates (many lines/second), this creates unnecessary load on SQLite and filesystem. For a typical session with 2-4 workers, the aggregate cost is meaningful but not crippling. For sessions with chatty workers, it could add latency to the WebSocket broadcast pipeline.
- **Recommended Fix**: Cache the pack manifest per session in the `SessionController`. The pack doesn't change during a session's lifetime:
  ```python
  def _get_pack_manifest(self, session_id: str) -> PackManifest:
      with self._lock:
          if session_id not in self._pack_cache:
              session = self.store.get_session(session_id)
              self._pack_cache[session_id] = load_pack_manifest(
                  self.runtime_paths.packs / session.pack
              )
          return self._pack_cache[session_id]
  ```
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: Worker log events no longer trigger per-line SQLite + YAML reads; existing log streaming tests pass.

---

### [Robustness] Finding #4: `get_task_log` reads entire log file into memory

- **Severity**: Low
- **Category**: Robustness & Resilience
- **Evidence**: `server.py:458-478` — `get_task_log` reads the entire log file with `read_text()`, splits into lines, then slices with `offset:offset+limit`.
- **Impact**: Worker logs can grow large (tens of MB for long-running workers). The full file is loaded into memory even when only requesting a small slice.
- **Recommended Fix**: Use `linecache` or line-by-line reading to only load the requested range. For the typical single-user workload this is unlikely to be a problem, but it's cheap to fix:
  ```python
  with open(log_path, encoding="utf-8") as f:
      lines = []
      for i, line in enumerate(f):
          if i < offset:
              continue
          if i >= offset + limit:
              break
          lines.append(line.rstrip("\n"))
  ```
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: Log endpoint returns same data; memory usage bounded.

---

### [Robustness] Finding #5: WebSocket disconnect not caught on unexpected exceptions

- **Severity**: Medium
- **Category**: Robustness & Resilience
- **Evidence**: `server.py:615-631` — The WebSocket handler catches `WebSocketDisconnect` and `json.JSONDecodeError/ValueError`, but not general exceptions (e.g., `RuntimeError` from Starlette's WebSocket internals when the connection is abruptly closed).
- **Impact**: An unexpected exception in the WebSocket handler could leave the connection in the `active_connections` list, leaking memory and causing broadcast failures.
- **Recommended Fix**: Add a broad exception catch outside the inner loop:
  ```python
  except WebSocketDisconnect:
      await connection_manager.disconnect(websocket)
  except Exception:
      await connection_manager.disconnect(websocket)
  ```
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: WebSocket cleanup occurs on unexpected errors; no stale connections in `active_connections`.

---

### [Correctness] Finding #6: `_run_async` silently swallows exceptions from `future.add_done_callback`

- **Severity**: Low
- **Category**: Robustness & Resilience
- **Evidence**: `server.py:1196` — `future.add_done_callback(lambda completed: completed.exception())` calls `.exception()` which returns the exception but doesn't raise or log it. This prevents the "exception was never retrieved" warning, but actual WebSocket broadcast errors are silently lost.
- **Impact**: If a broadcast fails (e.g., WebSocket connection dropped mid-send), the error is completely invisible. In a single-user, local tool, this is unlikely to cause issues beyond a missed UI update, but it makes debugging broadcast problems harder.
- **Recommended Fix**: Log the exception at debug level:
  ```python
  def _done_callback(completed):
      exc = completed.exception()
      if exc is not None:
          logging.getLogger(__name__).debug("Async broadcast error: %s", exc)
  future.add_done_callback(_done_callback)
  ```
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: Broadcast errors appear in debug logs.

---

### [Correctness] Finding #7: `delete_session` not protected against running sessions with active threads

- **Severity**: Medium
- **Category**: Correctness & Safety
- **Evidence**:
  - `server.py:582-588` — `purge_session` checks `session.status not in {"completed", "aborted"}` before deleting
  - `server.py:180-186` — `abort` just updates the DB status; it does NOT wait for the background thread to finish or terminate workers
  - A sequence of `abort` → immediate `delete` could remove session data while the orchestrator thread is still running and accessing session files
- **Impact**: The orchestrator thread could crash with `FileNotFoundError` when trying to access deleted session paths, or worse, create orphan files. Since `_run_session` is wrapped in a try/except that catches all exceptions, the crash is silently swallowed, but the session directory state becomes inconsistent.
- **Recommended Fix**: The `purge_session` endpoint should check if the session controller's thread is still alive:
  ```python
  with self._lock:
      thread = self._threads.get(session_id)
      if thread is not None and thread.is_alive():
          raise HTTPException(status_code=409, detail="Session thread is still running.")
  ```
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: Deleting a just-aborted session with a still-running thread returns 409.

---

### [Best Practices] Finding #8: Inconsistent `import sys` placement in `cli.py`

- **Severity**: Low
- **Category**: Readability
- **Evidence**: `cli.py:1` imports `sys` at the top level, but the conversation summary mentions that `import sys` was added during a prior audit pass. Checking `server.py:7` shows `import sys` already present. This is fine — just confirming it's consistent.
- **Impact**: None; this is a non-issue upon verification.
- **Status**: No action needed.

---

### [Robustness] Finding #9: `_elapsed_since_timestamp` does not clamp negative elapsed time

- **Severity**: Low
- **Category**: Robustness & Resilience
- **Evidence**: `orchestrator.py:1471-1474` — If `session_started_at` is somehow in the future (NTP clock adjustment, manual timestamp manipulation), `_elapsed_since_timestamp` returns a negative number.
- **Impact**: `_session_monotonic_start` (line 134) would be set ahead of `time.monotonic()`, making the session timeout check at line 138-139 never trigger until the clock catches up. In practice, the session would simply run longer than `session_max` by the amount of clock skew.
- **Recommended Fix**: Clamp to non-negative: `return max(0.0, (datetime.now(UTC) - _parse_timestamp(timestamp)).total_seconds())`
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: Negative elapsed time returns 0.0; session timeout still works correctly on restart.

---

### [Scalability] Finding #10: `build_dashboard_payload` queries task lists 4 times per dashboard render

- **Severity**: Low
- **Category**: Scalability & Capacity
- **Evidence**: `server.py:690-693` — Calls `list_ready_tasks`, `list_active_tasks`, `list_done_tasks`, and `list_blocked_tasks` as four separate SQLite queries. Then `list_active_tasks` is called again at line 695-698 to build `active_tasks_by_slot`.
- **Impact**: 5 SQLite queries per dashboard render (each on a WebSocket state update). For single-user use this is fine, but it's simple to reduce.
- **Recommended Fix**: Use a single `list_all_tasks(session_id)` query and partition in Python.
- **Effort**: S
- **Risk**: Low
- **Workload Assumption**: Single user, up to ~50 tasks per session. This is an optimization opportunity, not a blocker.
- **Acceptance Criteria**: Dashboard renders with fewer SQLite queries; same payload produced.

---

## Implementation Plan

### Phase 1: Correctness Fixes (Medium Severity)

**Step 1: Add KeyError → 404 exception handler**
- **Files to modify**: `cognitive_switchyard/server.py`
- **Changes**: Add a FastAPI exception handler at the `create_app` level:
  ```python
  from fastapi.responses import JSONResponse

  @app.exception_handler(KeyError)
  async def key_error_handler(request, exc):
      return JSONResponse(status_code=404, content={"detail": str(exc)})
  ```
- **Commands**: `.venv/bin/pytest tests/test_server.py --tb=short -q`
- **Expected result**: All server tests pass; nonexistent resource requests return 404
- **Stop condition**: If existing tests rely on KeyError raising 500, update those tests

**Step 2: Catch general exceptions in WebSocket handler**
- **Files to modify**: `cognitive_switchyard/server.py:615-631`
- **Changes**: Add a second except clause after `WebSocketDisconnect`:
  ```python
  except WebSocketDisconnect:
      await connection_manager.disconnect(websocket)
  except Exception:
      await connection_manager.disconnect(websocket)
  ```
- **Commands**: `.venv/bin/pytest tests/test_server.py --tb=short -q`
- **Expected result**: All tests pass

**Step 3: Guard `purge_session` against still-running threads**
- **Files to modify**: `cognitive_switchyard/server.py`
- **Changes**: Before `store.delete_session(session_id)` in `purge_session`, check if the controller has an alive thread for that session. Add a `has_active_thread(session_id)` method to `SessionController`.
- **Commands**: `.venv/bin/pytest tests/test_server.py --tb=short -q`
- **Expected result**: Deleting a just-aborted session with a running thread returns 409

### Phase 2: Robustness Fixes (Medium Severity)

**Step 4: Cache pack manifest in SessionController**
- **Files to modify**: `cognitive_switchyard/server.py`
- **Changes**: Add `_pack_cache: dict[str, PackManifest]` to `SessionController.__init__`. Add `_get_pack_manifest(session_id)` method. Use it in `_phase_enriched_log_event`.
- **Commands**: `.venv/bin/pytest tests/test_server.py --tb=short -q`
- **Expected result**: Tests pass; log line processing no longer re-reads pack YAML

**Step 5: Clamp negative elapsed time**
- **Files to modify**: `cognitive_switchyard/orchestrator.py:1471-1474`
- **Changes**: `return max(0.0, (datetime.now(UTC) - _parse_timestamp(timestamp)).total_seconds())`
- **Commands**: `.venv/bin/pytest tests/test_orchestrator.py --tb=short -q`
- **Expected result**: All orchestrator tests pass

### Phase 3: Optional Improvements (Low Severity)

⚠️ **OPTIONAL** — Only proceed if Phase 1-2 complete and time permits

**Step 6: Change `reveal-file` and `open-intake` to POST**
- **Files to modify**: `cognitive_switchyard/server.py`, `cognitive_switchyard/html_template.py`
- **Changes**: Change `@app.get` to `@app.post` for both endpoints; update frontend fetch calls to use `method: 'POST'`

**Step 7: Stream `get_task_log` instead of full-file read**
- **Files to modify**: `cognitive_switchyard/server.py:458-478`
- **Changes**: Replace `read_text().splitlines()` with line-by-line reading

**Step 8: Log async broadcast errors at debug level**
- **Files to modify**: `cognitive_switchyard/server.py:1196`
- **Changes**: Replace lambda with named callback that logs exceptions

**Step 9: Reduce dashboard query count**
- **Files to modify**: `cognitive_switchyard/state.py`, `cognitive_switchyard/server.py`
- **Changes**: Add `list_all_tasks(session_id)` method; partition by status in `build_dashboard_payload`
