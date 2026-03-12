# Code Audit — 2026-03-11

## Audit Scope

### Files Audited

| Tier | File | Lines | Focus |
|------|------|-------|-------|
| 1 | `cognitive_switchyard/state.py` | 1265 | SQLite, atomicity, concurrency |
| 1 | `cognitive_switchyard/recovery.py` | 350 | Crash recovery, edge cases |
| 1 | `cognitive_switchyard/orchestrator.py` | 1701 | Session lifecycle, threading |
| 1 | `cognitive_switchyard/server.py` | 1895 | WebSocket, REST, path safety |
| 1 | `cognitive_switchyard/worker_manager.py` | 432 | Subprocess lifecycle, cleanup |
| 2 | `cognitive_switchyard/planning_runtime.py` | 636 | Planning, dependency resolution |
| 2 | `cognitive_switchyard/agent_runtime.py` | 309 | Agent subprocess, env handling |
| 2 | `cognitive_switchyard/pack_loader.py` | 628 | Pack validation, path safety |
| 2 | `cognitive_switchyard/parsers.py` | 475 | Artifact parsing |
| 2 | `cognitive_switchyard/hook_runner.py` | 191 | Hook execution, env isolation |
| 2 | `cognitive_switchyard/verification_runtime.py` | 118 | Verification, env handling |
| 3 | `cognitive_switchyard/models.py` | 741 | Data models |
| 3 | `cognitive_switchyard/config.py` | 189 | Configuration |
| 3 | `cognitive_switchyard/cli.py` | 273 | CLI entry points |
| 3 | `cognitive_switchyard/bootstrap.py` | 170 | Self-bootstrap |
| 3 | `cognitive_switchyard/scheduler.py` | 42 | Task scheduling |
| Special | `cognitive_switchyard/html_template.py` | 3586 | XSS vectors in template interpolation only |

### Test Baseline

**Entry state:** 270 passed, 2 failed (pre-existing), 52 warnings — 102.92s

**Pre-existing failures:**
- `tests/test_e2e.py::TestPreflight::test_preflight_fails_without_repo_root[chromium]`
- `tests/test_hook_runner.py::test_builtin_claude_code_preflight_requires_repo_root_for_git_worktree_isolation`

Both failures are related to the claude-code pack preflight script's git worktree isolation check behaving differently when the switchyard is run from within a git repository (the test environment's working directory is itself inside a git repo, causing the check to pass when it should fail).

### Prior Audit Cross-Reference Summary

| Audit | Findings | Resolved | Remaining |
|-------|----------|----------|-----------|
| `pre_launch_audit_report.md` (2026-03-10) | 22 | 22 | 0 |
| `cleanup_audit_20260310.md` (2026-03-10) | 10 | 9 | 1 (Finding #10 — dashboard queries) |
| **This audit** | **23 new** | — | — |

---

## Findings

---

### [Correctness] Finding #1: Event Persistence Inconsistency — DB Committed Before File Write

- **Severity:** High
- **Category:** Correctness / Data Consistency
- **File:** `cognitive_switchyard/state.py` — `append_event` method (~line 814–843)
- **Evidence:**
  ```python
  with self._connect() as connection:
      connection.execute("INSERT INTO events ...", (...))
      connection.commit()  # DB committed first
  # File write happens AFTER commit
  with session_log_path.open("a") as handle:
      handle.write(f"{timestamp} {event_type}...\n")
  ```
- **Impact:** If the process crashes between the DB commit and the file write, the event exists in SQLite but is absent from `session.log`. Any log-based replay, audit, or external log viewer sees an incomplete history. The reconciler relies on filesystem state as source of truth, so post-crash the DB and file diverge permanently.
- **Recommended Fix:** Write to `session.log` first (using a buffered write or the existing `_atomic_write_text` pattern), then commit to the DB. If the DB commit fails, the log file already has the entry — recoverable. If the file write fails, the transaction never committed — also recoverable.
- **Prior Audit Reference:** None
- **Status:** NEW

---

### [Correctness] Finding #2: Incomplete Rollback in `project_task` — File Moved Before DB Update

- **Severity:** High
- **Category:** Correctness / Atomicity
- **File:** `cognitive_switchyard/state.py` — `project_task` method (~line 342–429)
- **Evidence:**
  ```python
  source_path.replace(target_path)  # File moved FIRST
  moved = True
  try:
      with self._connect() as connection:
          # ... DB updates ...
          connection.commit()  # DB commit SECOND
  except Exception:
      if moved and target_path.exists():
          target_path.replace(source_path)  # Rollback attempt
      raise
  ```
- **Impact:** If the DB update fails (lock timeout, constraint violation, disk full), the code attempts to move the file back. If the rollback file move also fails (permission denied, target_path already gone), the exception is silently raised without the original source_path being restored. The task plan file is permanently lost from the expected directory, and the filesystem and DB diverge. The reconciler may later mark it blocked, but the file is gone.
- **Recommended Fix:** Reverse the order — perform the DB update in a transaction first, then move the file on success. This makes the filesystem move a consequence of a committed DB state, which is consistent with "filesystem as recoverable secondary." Alternatively, add explicit error logging and an alert event when the rollback file move itself fails.
- **Prior Audit Reference:** None
- **Status:** NEW

---

### [Correctness] Finding #3: Status Sidecar TOCTOU — `FileNotFoundError` Not Caught in `collect`

- **Severity:** High
- **Category:** Correctness / Concurrency
- **File:** `cognitive_switchyard/worker_manager.py` — `collect` method (~line 192–204)
- **Evidence:**
  ```python
  if not status_path.is_file():          # Check
      raise WorkerStatusSidecarError(...)
  try:
      status = parse_status_sidecar(
          status_path.read_text(encoding="utf-8"),  # Use — file could be gone here
          ...
      )
  except ArtifactParseError as exc:
      raise WorkerStatusSidecarError(...) from exc
  # FileNotFoundError is NOT caught
  ```
- **Impact:** If the status file is deleted between the `is_file()` check and `read_text()` (e.g., by a concurrent recovery run or filesystem event), `FileNotFoundError` propagates uncaught out of `collect()`, crashing the orchestrator's collection loop. The task is never finalized and may be permanently stuck.
- **Recommended Fix:** Include `FileNotFoundError` in the except clause:
  ```python
  except (ArtifactParseError, FileNotFoundError) as exc:
      raise WorkerStatusSidecarError(f"...: {exc}") from exc
  ```
- **Prior Audit Reference:** None
- **Status:** NEW

---

### [Correctness] Finding #4: Worker Timeout Fields Modified Without Lock

- **Severity:** High
- **Category:** Correctness / Thread Safety
- **File:** `cognitive_switchyard/worker_manager.py` — `_enforce_timeouts` and `_terminate_worker` (~line 265–347)
- **Evidence:**
  ```python
  def _enforce_timeouts(self, worker, now):
      if worker.terminate_sent_at is not None:  # No lock
          if now - worker.terminate_sent_at >= ...:
              worker.process.kill()
              worker.kill_escalated = True       # No lock
          return
      # ...
  def _terminate_worker(self, worker, *, ...):
      worker.timed_out = True           # No lock
      worker.timeout_kind = timeout_kind  # No lock
      worker.failure_reason = reason     # No lock
      worker.terminate_sent_at = now     # No lock
      worker.process.terminate()
  ```
  Meanwhile, `_read_stream` holds `worker.lock` while updating `last_output_at`.
- **Impact:** Reader threads hold `worker.lock` to update `last_output_at`; the timeout enforcement path reads and writes overlapping fields without the lock. This is a data race. On CPython the GIL provides some protection for single-attribute writes, but composite condition checks (read `terminate_sent_at`, compare, conditionally write `kill_escalated`) are not atomic and can produce incorrect timeout behavior.
- **Recommended Fix:** Acquire `worker.lock` in `_enforce_timeouts` before reading or writing any worker state fields. Create a lock-held variant of `_terminate_worker` or call it within the lock scope.
- **Prior Audit Reference:** Pre-launch Finding #7 was for `_refresh_worker` — this is a distinct set of unprotected fields in `_enforce_timeouts` and `_terminate_worker`.
- **Status:** NEW

---

### [Correctness] Finding #5: Exception in `_abort_session` Loop Leaves Workers Unfinalized

- **Severity:** High
- **Category:** Correctness / Exception Handling
- **File:** `cognitive_switchyard/orchestrator.py` — `_abort_session` (~line 1351–1382)
- **Evidence:**
  ```python
  while manager.active_slot_numbers():
      for slot_number in manager.active_slot_numbers():
          snapshot = manager.poll(slot_number)
          ...
          if not snapshot.is_finished:
              continue
          result = manager.collect(slot_number)  # Can raise
          _finalize_blocked_task(...)             # Can raise
      if manager.active_slot_numbers():
          time.sleep(poll_interval)
  ```
- **Impact:** If `manager.collect()` or `_finalize_blocked_task()` raises (e.g., from a corrupt status sidecar — see Finding #3), the exception propagates out of the while loop entirely. Remaining active workers are never collected or terminated. Their plan files remain in `workers/<slot>/` and the orchestrator exits in an unclean state. Recovery on next startup will handle the orphaned workers, but the abort path is supposed to be a clean shutdown.
- **Recommended Fix:** Wrap the per-slot body in try/except, log the error, and continue draining other workers. After the loop, re-raise the first exception if needed, or mark the session with an error event.
- **Prior Audit Reference:** None
- **Status:** NEW

---

### [Robustness] Finding #6: Recovery Metadata Write Is Not Atomic

- **Severity:** Medium
- **Category:** Robustness / File System Consistency
- **File:** `cognitive_switchyard/state.py` — `write_worker_recovery_metadata` (~line 912–941)
- **Evidence:**
  ```python
  recovery_path.parent.mkdir(parents=True, exist_ok=True)
  recovery_path.write_text(json.dumps({...}) + "\n", encoding="utf-8")
  # vs. _atomic_write_text() helper that exists in this same file
  ```
- **Impact:** If the process crashes between `mkdir` and the completion of `write_text`, the directory exists but the file is absent or truncated. On recovery, `read_worker_recovery_metadata` checks for `is_file()`, returns `None`, and the slot is treated as if it had no in-progress task. The workspace may remain as an orphan. Low probability but undermines recovery idempotency guarantees.
- **Recommended Fix:** Use the existing `_atomic_write_text()` helper (already present in state.py) instead of `write_text()` directly.
- **Prior Audit Reference:** None
- **Status:** NEW

---

### [Robustness] Finding #7: Recovery Loop Clears Metadata Before Task Is Fully Requeued

- **Severity:** Medium
- **Category:** Robustness / Crash Recovery Safety
- **File:** `cognitive_switchyard/recovery.py` — `recover_execution_session` (~line 16–138)
- **Evidence:**
  ```python
  store.project_task(...)                    # Move plan file + update DB
  store.clear_worker_recovery_metadata(...)  # Delete recovery.json
  # If crash happens between these two, metadata is cleared but task may not be moved
  ```
  More precisely: `project_task` can fail after the file move but before DB commit (see Finding #2). If recovery then calls `clear_worker_recovery_metadata`, the recovery.json is gone. On the next recovery pass, the slot appears empty even though the task is in an inconsistent state.
- **Impact:** A crash-during-recovery scenario leaves the task unreachable by subsequent recovery attempts. `cleanup_orphaned_workspaces` won't find it (no recovery.json) and `reconcile_filesystem_projection` may or may not fix the DB depending on where the plan file landed. The task is effectively lost until manual intervention.
- **Recommended Fix:** Clear the metadata only after `project_task` has successfully committed (both file move and DB update). Alternatively, make metadata clearing the very last step and wrap it in its own try/except so a failure to clear doesn't abort recovery.
- **Prior Audit Reference:** None
- **Status:** NEW

---

### [Robustness] Finding #8: `collect` Flag and `active_slot_numbers` Read Without Lock

- **Severity:** Medium
- **Category:** Robustness / Thread Safety
- **File:** `cognitive_switchyard/worker_manager.py` — `active_slot_numbers` (~line 223–228)
- **Evidence:**
  ```python
  def active_slot_numbers(self) -> tuple[int, ...]:
      return tuple(
          slot_number
          for slot_number, worker in sorted(self._workers.items())
          if not worker.collected  # Read without worker.lock
      )
  ```
  And `collect()` sets `worker.collected = True` at line ~171 without holding `worker.lock` either.
- **Impact:** A worker can be concurrently collected (setting `collected = True`) while `active_slot_numbers` is iterating, causing the slot to appear in the result when it should not. On CPython the GIL makes this a benign race in practice, but it's technically unsafe and will break under free-threaded Python (3.13t+).
- **Recommended Fix:** Acquire `worker.lock` around the `collected` check in `active_slot_numbers`, and in `collect()` before setting `worker.collected = True`.
- **Prior Audit Reference:** Pre-launch Finding #7 was fixed for `_refresh_worker`; this is the same class of issue in a different method.
- **Status:** NEW

---

### [Robustness] Finding #9: Daemon Reader Threads May Write to Closed Log File Handle

- **Severity:** Medium
- **Category:** Robustness / Resource Management
- **File:** `cognitive_switchyard/worker_manager.py` — `_finalize_worker` (~line 349–354) and `_read_stream` (~line 364–379)
- **Evidence:**
  ```python
  def _finalize_worker(self, worker):
      for reader in worker.readers:
          reader.join(timeout=1.0)   # Wait at most 1 second
      worker.log_handle.flush()
      worker.log_handle.close()      # Log file closed
      worker.finalized = True

  def _read_stream(self, worker, stream):
      for raw_line in iter(stream.readline, ""):
          with worker.lock:
              worker.log_handle.write(raw_line)  # Can happen after close
  ```
  Reader threads are daemon threads. After `_finalize_worker` times out the join (1 second), it closes the log handle. If the reader thread is still running (e.g., blocked on a slow readline), the next `write()` raises `ValueError: I/O operation on closed file`.
- **Impact:** Unhandled `ValueError` in the reader thread causes it to terminate silently. Some trailing output lines from the worker subprocess may be lost. The exception is not reported anywhere. Since reader threads are daemons, this is silent.
- **Recommended Fix:** Close the subprocess stdout/stderr pipes before joining reader threads — this causes `readline()` to return `""` immediately, allowing the threads to exit cleanly:
  ```python
  def _finalize_worker(self, worker):
      if worker.process.stdout: worker.process.stdout.close()
      if worker.process.stderr: worker.process.stderr.close()
      for reader in worker.readers:
          reader.join(timeout=5.0)
      worker.log_handle.flush()
      worker.log_handle.close()
      worker.finalized = True
  ```
  Also add a `ValueError` guard in `_read_stream` to handle the race gracefully.
- **Prior Audit Reference:** None
- **Status:** NEW

---

### [Robustness] Finding #10: Missing Session Validation in `retry_task_route`

- **Severity:** Medium
- **Category:** Correctness / API Contract
- **File:** `cognitive_switchyard/server.py` — `retry_task_route` (~line 941–944)
- **Evidence:**
  ```python
  def retry_task_route(session_id: str, task_id: str) -> dict[str, str]:
      store.get_task(session_id, task_id)  # No _ensure_session_exists() call
      session_controller.retry_task(session_id, task_id)
      return {"status": "accepted"}
  ```
  All other task-scoped endpoints call `_ensure_session_exists(store, session_id)` first.
- **Impact:** Requesting `POST /api/sessions/nonexistent/tasks/t/retry` hits `store.get_task()` which raises `KeyError` with a task-level message. The global `KeyError → 404` handler still fires (so it returns 404, not 500), but the error message says "task not found" rather than "session not found" — misleading for the caller.
- **Recommended Fix:** Add `_ensure_session_exists(store, session_id)` as the first line of `retry_task_route`, matching the pattern used by all other session-scoped endpoints.
- **Prior Audit Reference:** Cleanup audit Finding #1 added the KeyError→404 handler; this is a related gap in validation ordering.
- **Status:** NEW

---

### [Robustness] Finding #11: Subprocess Resource Leak in `_default_command_runner`

- **Severity:** Medium
- **Category:** Robustness / Resource Management
- **File:** `cognitive_switchyard/server.py` — `_default_command_runner` (~line 1799–1804)
- **Evidence:**
  ```python
  def _default_command_runner(command: list[str]) -> None:
      subprocess.Popen(
          command,
          stdout=subprocess.DEVNULL,
          stderr=subprocess.DEVNULL,
      )
  ```
  The `Popen` object is returned but never stored, joined, or reaped.
- **Impact:** On macOS, each uncollected `Popen` object leaves a zombie process until the Python GC collects it (which calls `__del__` → `poll()`). Under repeated `reveal-file` or `open-intake` calls, zombies accumulate. The number is bounded by GC cycles, but each zombie holds kernel resources. No functional breakage but degrades over time.
- **Recommended Fix:** Use `start_new_session=True` to detach the process from the parent's process group so the OS reaps it without Python involvement:
  ```python
  subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
  ```
- **Prior Audit Reference:** None
- **Status:** NEW

---

### [Robustness] Finding #12: `verification_runtime.py` Does Not Strip `CLAUDECODE` from Environment

- **Severity:** Medium
- **Category:** Security / Environment Isolation
- **File:** `cognitive_switchyard/verification_runtime.py` (~line 17–28)
- **Evidence:**
  ```python
  # verification_runtime.py
  command_env = os.environ.copy()   # CLAUDECODE is NOT stripped
  if env is not None:
      command_env.update(env)

  # hook_runner.py (correct pattern)
  command_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

  # agent_runtime.py (correct pattern)
  env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
  ```
- **Impact:** When Cognitive Switchyard runs inside Claude Code (which sets `CLAUDECODE=1`), verification scripts inherit `CLAUDECODE`. If a verification script (e.g., a test runner) checks for `CLAUDECODE` to modify behavior, or if it spawns sub-Claude-Code instances that check `CLAUDECODE`, the behavior diverges from hook and agent execution, which both strip the variable. Inconsistent isolation can cause subtle test environment differences.
- **Recommended Fix:** Apply the same filter as `hook_runner.py`:
  ```python
  command_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
  ```
  Consider extracting a shared `_safe_env()` helper to ensure consistency.
- **Prior Audit Reference:** None
- **Status:** NEW

---

### [Robustness] Finding #13: `reconcile_filesystem_projection` Crashes If `workers/` Directory Does Not Exist

- **Severity:** Low
- **Category:** Robustness / Defensive Programming
- **File:** `cognitive_switchyard/state.py` — `reconcile_filesystem_projection` (~line 966–1070)
- **Evidence:**
  ```python
  for worker_dir in sorted(path for path in session_paths.workers.iterdir() ...):
      # iterdir() raises FileNotFoundError if workers/ doesn't exist
  ```
- **Impact:** If a session has no workers directory (e.g., session created but no tasks ever dispatched, or directory deleted during cleanup), `reconcile_filesystem_projection` raises `FileNotFoundError` and aborts. Recovery is blocked. Low probability but easy to hit in test environments or edge-case session states.
- **Recommended Fix:**
  ```python
  if session_paths.workers.is_dir():
      for worker_dir in sorted(path for path in session_paths.workers.iterdir() ...):
          ...
  ```
- **Prior Audit Reference:** None
- **Status:** NEW

---

### [Robustness] Finding #14: `read_worker_recovery_metadata` Raises Uncontextualized `JSONDecodeError`

- **Severity:** Low
- **Category:** Robustness / Error Handling
- **File:** `cognitive_switchyard/state.py` — `read_worker_recovery_metadata` (~line 943–959)
- **Evidence:**
  ```python
  payload = json.loads(recovery_path.read_text(encoding="utf-8"))
  # JSONDecodeError propagates with no context about which file
  return WorkerRecoveryMetadata(
      task_id=payload["task_id"],       # KeyError if missing
      workspace_path=Path(payload["workspace_path"]),  # KeyError if missing
      ...
  )
  ```
- **Impact:** A corrupted or truncated `recovery.json` (partial write, disk corruption) raises `json.JSONDecodeError` or `KeyError` with no indication of which slot or file path caused the failure. Recovery crashes with a cryptic traceback, making triage harder.
- **Recommended Fix:**
  ```python
  try:
      payload = json.loads(recovery_path.read_text(encoding="utf-8"))
      return WorkerRecoveryMetadata(
          task_id=payload["task_id"],
          workspace_path=Path(payload["workspace_path"]),
          pid=payload.get("pid"),
          ...
      )
  except (json.JSONDecodeError, KeyError, ValueError) as exc:
      raise ValueError(f"Corrupted recovery metadata at {recovery_path}: {exc}") from exc
  ```
- **Prior Audit Reference:** None
- **Status:** NEW

---

### [Robustness] Finding #15: Timeout Exceptions from Subprocess Calls Return 500 Instead of Meaningful Error

- **Severity:** Low
- **Category:** Robustness / Error Handling
- **File:** `cognitive_switchyard/server.py` — `_create_session_worktree` (~line 487–516)
- **Evidence:**
  ```python
  git_check = subprocess.run([...], capture_output=True, text=True, timeout=5)
  # subprocess.TimeoutExpired is not caught; propagates as 500
  result = subprocess.run([...], capture_output=True, text=True, timeout=30)
  # same — TimeoutExpired unhandled
  ```
  Contrast with `_run_folder_picker` (line ~1758) which does catch `TimeoutExpired`.
- **Impact:** A slow or hung git operation (network-mounted repo, spinning disk) causes the session creation endpoint to return 500 with a traceback rather than a clean "git operation timed out" message. The UI shows a generic error.
- **Recommended Fix:** Wrap git subprocess calls with `except subprocess.TimeoutExpired` and raise `HTTPException(status_code=408)` with an actionable message.
- **Prior Audit Reference:** None
- **Status:** NEW

---

### [Robustness] Finding #16: Absolute Path in `_resolve_relative_path` Bypasses Containment Check

- **Severity:** Low
- **Category:** Security / Path Validation
- **File:** `cognitive_switchyard/server.py` — `_resolve_relative_path` (~line 1739–1745)
- **Evidence:**
  ```python
  def _resolve_relative_path(session_root: Path, relative_path: str) -> Path:
      candidate = (session_root / relative_path).resolve()
      # If relative_path is "/etc/passwd", Python's pathlib replaces session_root entirely
      try:
          candidate.relative_to(session_root.resolve())
      except ValueError as exc:
          raise HTTPException(status_code=400, detail="Path escapes session root.") from exc
      return candidate
  ```
  In Python's `pathlib`, `Path("/some/base") / "/absolute/path"` yields `Path("/absolute/path")` — the base is discarded. The subsequent `relative_to` check catches this and returns 400, so the containment check still works correctly. However, the check is more fragile than it appears; the behavior depends on `pathlib` internals.
- **Impact:** The containment check is effectively correct today because `relative_to` raises `ValueError` for an absolute path outside the session root. However, if someone refactors this function without understanding the subtlety, they could break the check. Additionally, symlinks inside the session root that point outside would be followed by `.resolve()`, potentially allowing symlink-based escapes.
- **Recommended Fix:** Add an explicit early rejection of absolute paths before the `resolve()` call:
  ```python
  if Path(relative_path).is_absolute():
      raise HTTPException(status_code=400, detail="Absolute paths are not allowed.")
  ```
  Document the symlink behavior in a comment.
- **Prior Audit Reference:** Pre-launch audit confirmed path traversal validation on `reveal-file` is correct; this is a hardening note.
- **Status:** NEW

---

### [Robustness] Finding #17: WebSocket Exception Handler Swallows Unexpected Errors Silently

- **Severity:** Low
- **Category:** Observability / Robustness
- **File:** `cognitive_switchyard/server.py` — `websocket_endpoint` (~line 1098–1101)
- **Evidence:**
  ```python
  except WebSocketDisconnect:
      await connection_manager.disconnect(websocket)
  except Exception:
      await connection_manager.disconnect(websocket)
      # No logging — exception is silently swallowed
  ```
- **Impact:** Bugs in `connection_manager.subscribe_logs()` or other subscription logic are completely invisible. The client sees a disconnect; the operator sees nothing in logs. Makes debugging subscription-related issues very difficult.
- **Recommended Fix:**
  ```python
  except Exception as exc:
      _logger.exception("Unexpected error in WebSocket handler: %s", exc)
      await connection_manager.disconnect(websocket)
  ```
- **Prior Audit Reference:** Cleanup audit Finding #5 added the `except Exception` clause; this finding notes that logging was not added at the same time.
- **Status:** NEW

---

### [Robustness] Finding #18: Reader Thread Exit Lacks Error Handling for Closed File Handle

- **Severity:** Low
- **Category:** Robustness / Resource Management
- **File:** `cognitive_switchyard/worker_manager.py` — `_read_stream` (~line 364–379)
- **Evidence:**
  ```python
  def _read_stream(self, worker, stream):
      for raw_line in iter(stream.readline, ""):
          with worker.lock:
              worker.log_handle.write(raw_line)   # Raises ValueError if log_handle closed
              worker.log_handle.flush()
      stream.close()
  ```
  Related to Finding #9 — if `_finalize_worker` closes the log handle while this thread is still running, the next `write()` raises `ValueError`, crashing the thread silently.
- **Impact:** Trailing output lines from the worker are lost. No error is reported. The `stream.close()` at the end may not execute, leaving the pipe open.
- **Recommended Fix:** Wrap the log write in a `try/except ValueError: break` to handle the race gracefully. Wrap `stream.close()` in a `finally` block.
- **Prior Audit Reference:** None (companion to Finding #9)
- **Status:** NEW

---

### [Performance] Finding #19: Multiple Redundant `process.poll()` Calls per Refresh Cycle

- **Severity:** Low
- **Category:** Performance / Code Clarity
- **File:** `cognitive_switchyard/worker_manager.py` — `poll` and `_refresh_worker` (~line 148, 257, 260)
- **Evidence:**
  ```python
  def _refresh_worker(self, worker):
      exit_code = worker.process.poll()   # First poll
      if exit_code is None:
          self._enforce_timeouts(worker, now)
          exit_code = worker.process.poll()  # Second poll — usually returns None again

  def poll(self, slot_number):
      self._refresh_worker(worker)        # Calls refresh (1-2 polls)
      exit_code = worker.process.poll()   # Third poll
  ```
- **Impact:** `process.poll()` is called 2–3 times per `poll()` invocation. The calls are redundant because `process.returncode` is cached after the process exits — subsequent calls return the same value. Not a correctness issue, but adds unnecessary syscall overhead on the hot polling loop. Also makes the intent harder to read.
- **Recommended Fix:** Cache the result of `process.poll()` in a local variable and reuse it within `_refresh_worker`. Have `poll()` use the return value from `_refresh_worker` instead of re-polling.
- **Prior Audit Reference:** None
- **Status:** NEW

---

### [Performance] Finding #20: SQLite 10-Second Timeout May Be Insufficient During Recovery

- **Severity:** Low
- **Category:** Operational Safety
- **File:** `cognitive_switchyard/state.py` — `_connect` (~line 1119–1127)
- **Evidence:**
  ```python
  connection = sqlite3.connect(self.database_path, timeout=10)
  ```
- **Impact:** During recovery, `reconcile_filesystem_projection` performs a large filesystem scan followed by multiple DB writes in rapid succession. If the orchestrator and API threads are simultaneously writing (e.g., responding to UI polls during recovery), the 10-second WAL timeout may be exceeded, causing `sqlite3.OperationalError: database is locked`. This is unlikely on local SSD but possible on network-mounted storage or slow disks.
- **Recommended Fix:** Separate the filesystem scanning phase (no lock needed) from the DB write phase to minimize transaction duration. Optionally, increase the timeout specifically for bulk recovery operations. Document the timeout assumption in code comments.
- **Prior Audit Reference:** None
- **Status:** NEW

---

### [Correctness] Finding #21: `_elapsed_seconds` Does Not Handle Malformed Timestamp Input

- **Severity:** Low
- **Category:** Robustness / Error Handling
- **File:** `cognitive_switchyard/server.py` — `_elapsed_seconds` (~line 1823–1827)
- **Evidence:**
  ```python
  def _elapsed_seconds(timestamp: str | None) -> int:
      if not timestamp:
          return 0
      started_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
      return max(0, int((datetime.now(UTC) - started_at).total_seconds()))
  ```
- **Impact:** A malformed timestamp string (e.g., from a corrupted DB row or a future schema change) causes `datetime.fromisoformat()` to raise `ValueError`, which propagates up through the dashboard payload builder and returns 500 for the entire session state response.
- **Recommended Fix:**
  ```python
  try:
      started_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
      return max(0, int((datetime.now(UTC) - started_at).total_seconds()))
  except (ValueError, TypeError):
      return 0
  ```
- **Prior Audit Reference:** Cleanup audit Finding #9 added `max(0, ...)` clamping; this is a companion gap.
- **Status:** NEW

---

### [Maintainability] Finding #22: `_default_command_runner` Has No Timeout or Error Logging

- **Severity:** Low
- **Category:** Observability / Maintainability
- **File:** `cognitive_switchyard/server.py` — `_default_command_runner` (~line 1799–1804)
- **Evidence:**
  ```python
  def _default_command_runner(command: list[str]) -> None:
      subprocess.Popen(
          command,
          stdout=subprocess.DEVNULL,
          stderr=subprocess.DEVNULL,
      )
  ```
- **Impact:** If the command fails to launch (e.g., `open` not found, permission denied), the error is silently swallowed. No log message, no user feedback beyond the UI receiving no visible reaction. Combined with Finding #11 (zombie processes), this is a silent failure mode.
- **Recommended Fix:** Wrap in try/except and log a warning:
  ```python
  try:
      subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
  except OSError as exc:
      _logger.warning("Failed to launch command %s: %s", command[0], exc)
  ```
- **Prior Audit Reference:** None
- **Status:** NEW (companion to Finding #11)

---

### [Maintainability] Finding #23: Stale Connection Cleanup Not Logged at Operational Level

- **Severity:** Low
- **Category:** Observability
- **File:** `cognitive_switchyard/server.py` — `ConnectionManager._send_many` (~line 142–155)
- **Evidence:**
  ```python
  except Exception as exc:
      _debug("_send_many: send failed: %s", exc)  # DEBUG only
      stale.append(connection)
  ```
- **Impact:** When a WebSocket connection is forcibly cleaned up due to a send failure, only a DEBUG message is emitted. At normal log levels, stale connection cleanup is completely invisible. If a client-side bug causes repeated connection failures, the operator has no visibility without enabling debug logging.
- **Recommended Fix:**
  ```python
  except Exception as exc:
      _debug("_send_many: send failed: %s", exc)
      _logger.warning("Removing stale WebSocket connection (%s): %s", type(exc).__name__, exc)
      stale.append(connection)
  ```
- **Prior Audit Reference:** None
- **Status:** NEW

---

## Carried Forward

### Cleanup Audit Finding #10: Dashboard Query Consolidation

- **Original:** `cleanup_audit_20260310.md` Finding #10
- **Status:** OPEN — deferred from prior audit
- **File:** `cognitive_switchyard/server.py` — `build_dashboard_payload` (~line 690–698)
- **Issue:** Calls `list_ready_tasks`, `list_active_tasks`, `list_done_tasks`, and `list_blocked_tasks` as four separate SQLite queries, then calls `list_active_tasks` again to build `active_tasks_by_slot` — five total queries per dashboard render.
- **Recommended Fix:** Add `list_all_tasks(session_id)` query, partition by status in Python, building both the status groups and `active_tasks_by_slot` in one pass.
- **Effort:** S (small)

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 5 |
| Medium | 7 |
| Low | 11 |
| **Total (new)** | **23** |
| **Carried forward** | **1** |

### High Severity Quick Reference

| # | Title | File |
|---|-------|------|
| F-1 | Event persistence inconsistency — DB before file | `state.py` |
| F-2 | Incomplete rollback in `project_task` | `state.py` |
| F-3 | Status sidecar TOCTOU — `FileNotFoundError` uncaught | `worker_manager.py` |
| F-4 | Worker timeout fields modified without lock | `worker_manager.py` |
| F-5 | Exception in `_abort_session` loop leaves workers unfinalized | `orchestrator.py` |

### Medium Severity Quick Reference

| # | Title | File |
|---|-------|------|
| F-6 | Recovery metadata write not atomic | `state.py` |
| F-7 | Recovery loop clears metadata before task fully requeued | `recovery.py` |
| F-8 | `collected` flag and `active_slot_numbers` read without lock | `worker_manager.py` |
| F-9 | Daemon reader threads may write to closed log file handle | `worker_manager.py` |
| F-10 | Missing session validation in `retry_task_route` | `server.py` |
| F-11 | Subprocess resource leak in `_default_command_runner` | `server.py` |
| F-12 | `verification_runtime.py` does not strip `CLAUDECODE` | `verification_runtime.py` |

---

## Cross-Reference Matrix

### Pre-Launch Audit (22 findings — all resolved)

| Finding | Title | Confirmed Resolved |
|---------|-------|--------------------|
| #1 | `isolate_end` script does not merge work | ✓ |
| #2 | No SQLite WAL mode | ✓ |
| #3 | TOCTOU race in `create_session` | ✓ |
| #4 | Pack prompts are stubs | ✓ |
| #5 | No `test-echo` pack | ✓ |
| #6 | `_task_id_from_path` fragile heuristic | ✓ |
| #7 | Thread-safety gap in `_refresh_worker` | ✓ (but related new issues F-4, F-8 found) |
| #8 | `reconcile_filesystem_projection` ignores missing tasks | ✓ (but related new issue F-13 found) |
| #9 | Session timeout uses wall-clock | ✓ |
| #10 | `execute` script discards Claude output | ✓ |
| #11 | Double `find_free_port` call | ✓ |
| #12 | No WebSocket reconnection logic | ✓ |
| #13 | REST endpoints accept raw dicts | ✓ |
| #14 | DAG view uses grid layout | ✓ |
| #15 | DAG anti-affinity group backgrounds missing | ✓ |
| #16 | `handleSocketMessage` declared `async` unnecessarily | ✓ |
| #17 | Tailwind CSS loaded but unused | ✓ |
| #18 | Setup View missing timeout fields | ✓ |
| #19 | `config.py` hand-rolled YAML parser | ✓ |
| #20 | Template filename mismatch | ✓ |
| #21 | `verify` script is a no-op | ✓ |
| #22 | `execute` script skips phase 2/5 | ✓ |

### Cleanup Audit (10 findings — 9 resolved, 1 open)

| Finding | Title | Status |
|---------|-------|--------|
| #1 | `get_session` 404 missing on most endpoints | ✓ Resolved |
| #2 | `reveal-file` GET for side-effecting action | ✓ Resolved |
| #3 | `_phase_enriched_log_event` re-reads per log line | ✓ Resolved |
| #4 | `get_task_log` reads entire file into memory | ✓ Resolved |
| #5 | WebSocket disconnect not caught on unexpected exceptions | ✓ Resolved (new F-17 is a companion gap) |
| #6 | `_run_async` silently swallows broadcast exceptions | ✓ Resolved |
| #7 | `delete_session` not protected against running threads | ✓ Resolved |
| #8 | Inconsistent `import sys` placement | ✓ Non-issue confirmed |
| #9 | `_elapsed_since_timestamp` negative elapsed time | ✓ Resolved (new F-21 is a companion gap) |
| #10 | `build_dashboard_payload` 5 SQLite queries | ⚠ OPEN — carried forward |
