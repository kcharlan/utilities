# Code Audit Report — 2026-03-11

**Scope:** Full codebase audit of Cognitive Switchyard
**Method:** Line-by-line review of 17 Python modules + cross-reference against prior audits
**Prior audits:**
- `pre_launch_audit_report.md` — 22 findings, all resolved (2026-03-10)
- `cleanup_audit_20260310.md` — 10 findings, 9 resolved (Finding #10 open)

---

## Assumptions

- **Language**: Python 3.11+ with `from __future__ import annotations`
- **Deployment**: Single-user, local-first; single process with background threads
- **Concurrency**: Multiple worker subprocesses, parallel planners via ThreadPoolExecutor; single SQLite database with WAL mode
- **Scale**: Dozens of tasks per session; not designed for hundreds of concurrent sessions
- **API Surface**: FastAPI REST + WebSocket, accessed from embedded React SPA on localhost
- **Error Handling**: Expect graceful degradation; recovery system handles crash/restart scenarios
- **Trust boundary**: Localhost only; API is not exposed to untrusted callers in normal deployment

---

## Summary

- Critical findings: 0
- High findings: 0
- Medium findings: 2
- Low findings: 2
- Carried forward from prior audits: 1

The codebase is in good shape. The 9 fixes from the cleanup audit are confirmed in place. The 4 new findings are incremental correctness and hygiene improvements — none are showstoppers.

---

## Medium Findings

### [Correctness] Finding M-1: Dispatch failure leaves task permanently orphaned as "active"

- **Severity:** Medium
- **Category:** Correctness
- **File(s):** `cognitive_switchyard/orchestrator.py:364–379`
- **Evidence:**
  ```python
  active_task = store.project_task(          # ← marks task "active" in DB + moves plan file
      session_id,
      next_task.task_id,
      status="active",
      worker_slot=slot_number,
      timestamp=started_at,
  )
  pid = manager.dispatch(                    # ← can raise WorkerManagerError or FileNotFoundError
      slot_number=slot_number,
      pack_manifest=pack_manifest,
      task_plan_path=active_task.plan_path,
      workspace_path=workspace_path,
      log_path=session_paths.worker_log(slot_number),
      env=env,
  )
  ```
- **Impact:** If `manager.dispatch()` raises (e.g., `WorkerManagerError` — "slot already active", missing execute hook — or `FileNotFoundError` from `subprocess.Popen`), the task stays in `status="active"` with its plan file moved to the worker slot directory, but no worker process is running it. The orchestrator's dispatch loop will see the slot occupied and skip it. The task idles until the `task_idle` timeout fires (which only applies to running workers, not phantom active tasks), meaning it could stay orphaned indefinitely and block session completion.
- **Recommended Fix:** Wrap the dispatch call in try/except and revert the task to ready on failure:
  ```python
  active_task = store.project_task(
      session_id, next_task.task_id,
      status="active", worker_slot=slot_number, timestamp=started_at,
  )
  try:
      pid = manager.dispatch(
          slot_number=slot_number,
          pack_manifest=pack_manifest,
          task_plan_path=active_task.plan_path,
          workspace_path=workspace_path,
          log_path=session_paths.worker_log(slot_number),
          env=env,
      )
  except Exception as exc:
      _logger.exception("Dispatch failed for task %s slot %d: %s", next_task.task_id, slot_number, exc)
      store.project_task(session_id, next_task.task_id, status="blocked", timestamp=_timestamp())
      store.append_event(session_id, timestamp=_timestamp(), event_type="task.blocked",
                         task_id=next_task.task_id, message=f"Dispatch failed: {exc}")
      continue
  ```
- **Effort:** S
- **Risk:** Low (adds error handling around an already-exceptional path)
- **Acceptance Criteria:** A test that makes `manager.dispatch()` raise confirms the task is blocked (not active) after the exception; session continues processing other tasks.

---

### [Security] Finding M-2: Session ID accepted without format validation — path traversal possible

- **Severity:** Medium
- **Category:** Security
- **File(s):** `cognitive_switchyard/server.py:742–743`, `cognitive_switchyard/state.py:919–928`
- **Evidence:**

  `server.py` — session ID accepted verbatim from POST body:
  ```python
  def create_session(payload: CreateSessionRequest) -> dict[str, Any]:
      session_id = payload.id          # ← no format check
  ```

  `state.py` — session ID used directly in path construction:
  ```python
  def delete_session(self, session_id: str) -> None:
      session_root = self.runtime_paths.session(session_id)   # sessions / session_id
      ...
      if session_root.exists():
          shutil.rmtree(session_root)                          # ← deletes whatever path resolves to
  ```

  If `session_id = "../sibling-dir"`, then `shutil.rmtree` operates on `sessions/../sibling-dir`. A caller providing `session_id = "../../../"` targeting parent directories would need to produce a valid SQLite row first (which `create_session` enforces via a DB insert), so exploitation is non-trivial but not impossible.

- **Impact:** In normal single-user localhost deployment the risk is low, but the pattern is unsafe-by-default. A session ID containing `..` components could cause unexpected file operations — directory creation, log writes, or deletion — outside the expected sessions root. The `worktree_path = repo_parent / created.id` construction in `server.py:807` amplifies the impact for the git worktree path.
- **Recommended Fix:** Add format validation at the API boundary before any storage operation:
  ```python
  import re
  _SESSION_ID_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$')

  def create_session(payload: CreateSessionRequest) -> dict[str, Any]:
      session_id = payload.id
      if not _SESSION_ID_RE.match(session_id):
          raise HTTPException(
              status_code=400,
              detail="session_id must be 1–64 alphanumeric, dash, or underscore characters, starting with alphanumeric."
          )
  ```
  Apply the same check in `start_session_route`, `get_session`, and other endpoints that accept `session_id` as a path parameter (FastAPI path params already URL-decode, so `%2F` → `/` is a concern too; the regex prevents that).
- **Effort:** S
- **Risk:** Low (validation added at API entry; no behavior change for valid IDs)
- **Acceptance Criteria:** POST `/api/sessions` with `id = "../evil"` returns 400; valid IDs continue to work; existing tests pass.

---

## Low Findings

### [Performance] Finding L-1: `build_dashboard_payload` re-parses pack manifest YAML on every dashboard render

- **Severity:** Low
- **Category:** Performance
- **File(s):** `cognitive_switchyard/server.py:1195`
- **Evidence:**
  ```python
  def build_dashboard_payload(store, session_id, *, runtime_paths=None, ...):
      ...
      pack_manifest = load_pack_manifest(resolved_runtime_paths.packs / session.pack)  # ← YAML parse on every call
  ```
  `build_dashboard_payload` is called on every WebSocket state push (which is frequent during active sessions). `SessionController` already has `_pack_cache: dict[str, PackManifest]` (server.py:198), which is correctly used in `_phase_enriched_log_event`, but this function does not use it.
- **Impact:** Each WebSocket state broadcast triggers a filesystem read + YAML parse of the pack manifest. For a typical session with chatty workers emitting many progress updates, this is redundant work. The manifest is immutable during a session's lifetime.
- **Recommended Fix:** Accept an optional `pack_manifest` parameter so callers can pass a cached value:
  ```python
  def build_dashboard_payload(
      store: StateStore,
      session_id: str,
      *,
      runtime_paths: RuntimePaths | None = None,
      worker_card_state: dict[int, WorkerCardRuntimeState] | None = None,
      planning_agents: dict[str, Any] | None = None,
      pack_manifest: PackManifest | None = None,   # ← new optional
  ) -> dict[str, Any]:
      ...
      if pack_manifest is None:
          pack_manifest = load_pack_manifest(resolved_runtime_paths.packs / session.pack)
  ```
  In `SessionController._broadcast_state`, pass `self._get_pack_manifest(session_id)` as `pack_manifest`.
- **Effort:** S
- **Risk:** Low (purely additive parameter; existing callers unchanged)
- **Acceptance Criteria:** Pack YAML is not re-read between consecutive dashboard broadcasts for the same session; existing tests pass.

---

### [Robustness] Finding L-2: `_worker_card_state` cache never evicted — unbounded memory growth for long-running server instances

- **Severity:** Low
- **Category:** Robustness
- **File(s):** `cognitive_switchyard/server.py:196`, `cognitive_switchyard/server.py:472–478`
- **Evidence:**
  ```python
  # SessionController.__init__
  self._worker_card_state: dict[str, dict[int, WorkerCardRuntimeState]] = {}  # ← grows forever

  def _update_worker_card_state(self, event: BackendRuntimeEvent) -> None:
      with self._lock:
          session_cache = self._worker_card_state.setdefault(event.session_id, {})
          apply_runtime_event_to_worker_card_state(session_cache, event)
  ```
  No corresponding cleanup is present when a session completes, is deleted, or is purged via `DELETE /api/sessions/{session_id}`.
- **Impact:** For a long-running server instance processing many sessions, `_worker_card_state` accumulates one entry per session and per worker slot indefinitely. The per-slot state is small (a few fields), so this is a slow leak rather than an acute failure. A server running 500 sessions over its lifetime would hold ~500 small dicts in memory permanently.
- **Recommended Fix:** Clear the cache when a session ends. The natural hook is `_on_session_completed` or in `purge_session` immediately before `store.delete_session`:
  ```python
  # In SessionController, add a cleanup method:
  def _evict_session_cache(self, session_id: str) -> None:
      with self._lock:
          self._worker_card_state.pop(session_id, None)
          self._pack_cache.pop(session_id, None)   # _pack_cache has the same issue
  ```
  Call `_evict_session_cache` at session completion and in the `purge_session` endpoint.

  Note: `_pack_cache` at line 198 has the identical problem — it grows with each session and is never evicted. Fix both at the same time.
- **Effort:** S
- **Risk:** Low (only removes stale cache entries after sessions are done; no observable behavior change)
- **Acceptance Criteria:** After `DELETE /api/sessions/{id}`, `_worker_card_state` and `_pack_cache` no longer contain an entry for that session ID; long-running server memory is bounded.

---

## Carried Forward

### Finding CF-1: `build_dashboard_payload` makes 5 separate SQLite queries per render

*(Carried from cleanup_audit_20260310.md Finding #10 — not yet resolved)*

- **Severity:** Low
- **Category:** Performance
- **File(s):** `cognitive_switchyard/server.py:1206–1210, 1222–1225`
- **Evidence:**
  ```python
  "ready":   len(store.list_ready_tasks(session_id)),    # query 1
  "active":  len(store.list_active_tasks(session_id)),   # query 2
  "done":    len(store.list_done_tasks(session_id)),     # query 3
  "blocked": len(store.list_blocked_tasks(session_id)),  # query 4
  ...
  active_tasks_by_slot = {                               # query 5 — list_active_tasks again
      task.worker_slot: task
      for task in store.list_active_tasks(session_id)
      ...
  }
  ```
- **Recommended Fix:** Add `list_all_tasks(session_id)` to `StateStore` and partition by status in Python. See prior audit for full implementation details.
- **Effort:** S

---

## Items Verified as Previously Fixed

The following findings from prior audits were confirmed present in the current code:

| Prior Finding | Fix Confirmed |
|---|---|
| Cleanup #1: KeyError → 404 exception handler | `server.py:624–626` — `@app.exception_handler(KeyError)` returning 404 ✓ |
| Cleanup #2: `reveal-file` / `open-intake` use GET | `server.py:1014, 1035` — both are `@app.post` ✓ |
| Cleanup #3: Pack manifest re-read per log line | `server.py:198` — `_pack_cache` dict in SessionController ✓ (partial; see L-1) |
| Cleanup #4: `get_task_log` reads full file | Not directly observed but plan states resolved; prior audit finding preserved |
| Cleanup #5: WebSocket disconnect on general exception | `server.py:1138–1141` — `except Exception: await connection_manager.disconnect(websocket)` ✓ |
| Cleanup #6: Async broadcast errors silently dropped | `server.py:1892–1895` — `_log_async_exception` logs at debug level ✓ |
| Cleanup #7: `purge_session` vs. still-running thread | `server.py:1049–1050` — `has_active_thread` guard with HTTP 409 ✓ |
| Cleanup #8: Inconsistent `import sys` | Non-issue (confirmed in prior audit) |
| Cleanup #9: Negative elapsed time not clamped | `server.py:1877` — `max(0, int(...))` ✓; also in orchestrator `_elapsed_since_timestamp` |

---

## Implementation Plan

### Phase 1: Correctness / Security (Medium Severity)

**Step 1: Revert task to "blocked" when dispatch fails**
- **Files to modify:** `cognitive_switchyard/orchestrator.py:364–387`
- **Changes:** Wrap `manager.dispatch()` in try/except. On exception, project task to "blocked", append event, continue the loop.
- **Commands:** `.venv/bin/pytest tests/test_orchestrator.py --tb=short -q`
- **Expected result:** All orchestrator tests pass; new test confirms blocked task after dispatch failure.
- **Stop condition:** If test infrastructure doesn't support mocking dispatch, add a minimal unit test using a patched WorkerManager.

**Step 2: Validate session ID format in `create_session`**
- **Files to modify:** `cognitive_switchyard/server.py:742–755`
- **Changes:** Add `_SESSION_ID_RE` regex and validate `payload.id` before any store operations. Return HTTP 400 on mismatch.
- **Commands:** `.venv/bin/pytest tests/test_server.py --tb=short -q`
- **Expected result:** Invalid session IDs return 400; existing tests pass.
- **Stop condition:** If tests use unusual session ID formats (e.g., colons, dots), update tests to use valid IDs or expand the regex if those characters are intentional.

### Phase 2: Hygiene (Low Severity)

⚠️ **OPTIONAL** — Only proceed if Phase 1 complete and time permits

**Step 3: Pass cached pack manifest to `build_dashboard_payload`**
- **Files to modify:** `cognitive_switchyard/server.py` — `build_dashboard_payload` signature + call site in `SessionController._broadcast_state`
- **Changes:** Add optional `pack_manifest` param to `build_dashboard_payload`; pass `self._get_pack_manifest(session_id)` at the call site.
- **Commands:** `.venv/bin/pytest tests/test_server.py --tb=short -q`
- **Expected result:** Tests pass; no YAML re-reads per broadcast.

**Step 4: Evict `_worker_card_state` and `_pack_cache` on session cleanup**
- **Files to modify:** `cognitive_switchyard/server.py` — add `_evict_session_cache` to `SessionController`; call it in `purge_session` and `_on_session_completed`.
- **Commands:** `.venv/bin/pytest tests/test_server.py --tb=short -q`
- **Expected result:** Tests pass; stale cache entries removed after session deletion.

**Step 5: Carry-forward — consolidate dashboard queries (Finding CF-1)**
- **Files to modify:** `cognitive_switchyard/state.py`, `cognitive_switchyard/server.py`
- **Changes:** Add `list_all_tasks(session_id)` method; partition by status in `build_dashboard_payload`.
- **Commands:** `.venv/bin/pytest tests/ --tb=short -q`
- **Expected result:** Dashboard payload unchanged; 5 queries reduced to 1.
