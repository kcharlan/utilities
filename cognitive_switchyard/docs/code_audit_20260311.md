# Code Audit — 2026-03-11

**Date:** 2026-03-11
**Scope:** Full implementation audit of all 17 modules (~13k lines)
**Prior audits cross-referenced:** pre_launch_audit_report.md (22 findings, all resolved),
cleanup_audit_20260310.md (10 findings, 9 resolved, Finding #10 carried forward)
**Test suite baseline:** 272 tests passing

---

## Assumptions

- **Language**: Python 3.11+ with `from __future__ import annotations`
- **Deployment**: Single-user, local-first; single process with background threads
- **Concurrency**: Multiple worker subprocesses, parallel planners via ThreadPoolExecutor; single SQLite database with WAL mode
- **Scale**: Dozens of tasks per session; not designed for hundreds of concurrent sessions
- **API Surface**: FastAPI REST + WebSocket, accessed from embedded React SPA on localhost
- **Error Handling**: Expect graceful degradation; recovery system handles crash/restart scenarios

---

## Findings

---

### [Security] Finding #1: `shell=True` with pack-controlled command in `run_verification_command`

- **Severity**: Critical
- **Category**: Security
- **File(s)**: `cognitive_switchyard/verification_runtime.py:21-28`
- **Evidence**:
  ```python
  result = subprocess.run(
      command,        # raw str from VerificationConfig.command (pack YAML)
      shell=True,
      ...
  )
  ```
- **Impact**: `command` is a bare string from the pack manifest YAML, passed directly to `/bin/sh`. Any pack author can inject arbitrary shell constructs (`;`, `$(...)`, backtick execution). Because verification runs automatically after task completion, a malicious or compromised pack triggers full RCE as the invoking user with no further user interaction.
- **Recommended Fix**: Replace `shell=True` + bare string with `shell=False` + `shlex.split(command)`. Validate at pack-load time that the command resolves to an executable. If shell features (pipes, redirects) are genuinely required, document the trust boundary explicitly.
- **Effort**: S
- **Risk**: High

---

### [Security] Finding #2: `shell=True` with pack-controlled command in `run_prerequisite_checks`

- **Severity**: High
- **Category**: Security
- **File(s)**: `cognitive_switchyard/hook_runner.py:58-66`
- **Evidence**:
  ```python
  completed = subprocess.run(
      prerequisite.check,   # str from PrerequisiteCheck.check (pack YAML)
      shell=True,
      ...
  )
  ```
- **Impact**: Same vector as Finding #1. `prerequisite.check` comes from the `prerequisites:` section of the pack manifest. This is reachable at preflight, before the session starts, so any machine with a malicious pack is vulnerable even without running a session.
- **Recommended Fix**: Same as Finding #1: `shell=False` + `shlex.split()`. Prerequisite checks are almost always simple command-existence tests (`which git`, `docker info`) which do not require shell features.
- **Effort**: S
- **Risk**: High

---

### [Robustness] Finding #3: No subprocess timeout in `_default_subprocess_runner` (agent_runtime)

- **Severity**: High
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/agent_runtime.py:208-216`
- **Evidence**:
  ```python
  return subprocess.run(
      command,
      cwd=cwd, input=input_text, text=True,
      capture_output=True, check=False, env=env,
      # no timeout= parameter
  )
  ```
- **Impact**: If the Claude CLI process hangs (network stall, waiting for input), the orchestrator thread blocks forever. The `task_idle` / `task_max` timeout values exist in `TimeoutConfig` but are not applied here. A single stuck agent permanently stalls the pipeline with no recovery path.
- **Recommended Fix**: Accept an optional `timeout_seconds` parameter and pass it to `subprocess.run(timeout=...)`. Catch `subprocess.TimeoutExpired`, kill the process, and re-raise as `ClaudeCliRuntimeError`.
- **Effort**: S
- **Risk**: High

---

### [Robustness] Finding #4: No process timeout in `_streaming_subprocess_runner` (agent_runtime)

- **Severity**: High
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/agent_runtime.py:219-276`
- **Evidence**:
  ```python
  proc = subprocess.Popen(...)
  for raw_line in iter(proc.stdout.readline, ""):   # no timeout
      ...
  proc.wait()  # no timeout
  ```
- **Impact**: A child process that stops producing output without exiting blocks the main thread indefinitely at the `readline` loop. The only timeout in this function (`stderr_thread.join(timeout=5.0)`) applies after the stdout loop has already returned. Any orchestration using the streaming runner (the primary runtime path for Claude Code) is vulnerable to hangs.
- **Recommended Fix**: Track a wall-clock start time before the stdout loop. Check elapsed time against `task_max` on each iteration. Alternatively, move stdout reading to a background thread with a shared timeout event and call `proc.communicate(timeout=...)`.
- **Effort**: M
- **Risk**: High

---

### [Robustness] Finding #5: No subprocess timeout on hook/verification runners

- **Severity**: High
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/hook_runner.py:58,102`, `cognitive_switchyard/verification_runtime.py:21`
- **Evidence**: None of the `subprocess.run()` calls in `run_short_lived_hook`, `run_prerequisite_checks`, or `run_verification_command` pass a `timeout=` argument.
- **Impact**: A stalled hook or verification command permanently blocks the orchestrator thread. `run_verification_command` runs on a schedule after every N completed tasks, making this a routine operational risk.
- **Recommended Fix**: Add a caller-supplied `timeout` parameter to `run_short_lived_hook`; derive a timeout from `VerificationConfig` in `run_verification_command`; use a short hard timeout (e.g., 30s) per check in `run_prerequisite_checks`. Catch `subprocess.TimeoutExpired` and return a failed result.
- **Effort**: M
- **Risk**: High

---

### [Correctness] Finding #6: `fixer_executor` uncaught exception leaves session in `auto_fixing` state with workers abandoned

- **Severity**: High
- **Category**: Robustness / Correctness
- **File(s)**: `cognitive_switchyard/orchestrator.py:1030`, `cognitive_switchyard/orchestrator.py:1290`
- **Evidence**:
  ```python
  fix_result = fixer_executor(context)    # bare call — no try/except
  ```
- **Impact**: If `fixer_executor` raises (network timeout, LLM API error, assertion), the exception propagates uncaught through `_attempt_task_auto_fix` or `_run_pending_verification`. The session status is left as `"auto_fixing"` with `verification_pending=True`. The outer `while True` loop in `execute_session` has no top-level `try/except`, so all running worker subprocesses are abandoned without calling `manager.terminate()` or `_finalize_blocked_task`. Those workers continue running indefinitely.
- **Recommended Fix**: Wrap each `fixer_executor(context)` call in `try/except Exception`. On failure: log the exception, call `store.update_session_status(session_id, status="paused")`, reset `verification_pending=False`, and return an appropriate failure result. Add a top-level `try/except` in `execute_session` that terminates all workers before re-raising.
- **Effort**: M
- **Risk**: High

---

### [Correctness] Finding #7: `manager.collect()` unguarded in `_abort_session` drain loop

- **Severity**: High
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/orchestrator.py:1405-1429`
- **Evidence**:
  ```python
  while manager.active_slot_numbers():
      for slot_number in manager.active_slot_numbers():
          result = manager.collect(slot_number)    # no try/except
          _finalize_blocked_task(...)
  ```
- **Impact**: `manager.collect()` can raise `WorkerResultError` or `WorkerStatusSidecarError` (note the normal path at line 745 does catch `WorkerStatusSidecarError`). If any exception escapes, the abort drain loop aborts mid-iteration, leaving remaining active workers unwaited, threads leaked, and the session permanently stuck in `"aborted"` without completing state transitions.
- **Recommended Fix**: Wrap `manager.collect(slot_number)` in `try/except (WorkerManagerError, OSError)` that logs the failure and continues to the next slot.
- **Effort**: S
- **Risk**: Medium

---

### [Correctness] Finding #8: `project_task` moves file before DB commit; rollback failure is silent

- **Severity**: High
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/state.py:342-429`
- **Evidence**:
  ```python
  source_path.replace(target_path)   # filesystem move happens first (line 366)
  ...
  try:
      with self._connect() as connection:
          connection.commit()
  except Exception:
      if moved and target_path.exists():
          target_path.replace(source_path)   # rollback attempt — can fail silently
      raise
  ```
- **Impact**: A crash between the file move and the DB commit leaves the file at `target_path` while the DB row still points to `source_path`. `reconcile_filesystem_projection` should repair this, but only if `target_path` is in a scanned directory. Additionally, if the rollback `replace()` itself raises (e.g., parent directory deleted), the exception is swallowed and the original exception propagates while the filesystem is in a torn state.
- **Recommended Fix**: Wrap the rollback in its own `try/except` and log failures explicitly. Long-term, log the target path to a WAL-like journal before the move so recovery can always undo.
- **Effort**: M
- **Risk**: Medium

---

### [Correctness] Finding #9: `write_session_runtime_state` read-modify-write race under parallel planners

- **Severity**: High
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/state.py:502-586`
- **Evidence**:
  ```python
  current = self.get_session(session_id).runtime_state   # read in connection 1
  next_state = SessionRuntimeState(...)                  # merge in Python
  with self._connect() as connection:
      connection.execute("UPDATE sessions SET runtime_state_json = ? ...", ...)
      connection.commit()                                # write in connection 2
  ```
- **Impact**: Classic read-modify-write without a lock. With parallel planners running via `ThreadPoolExecutor`, two threads can each read the same state, merge independently, and the second write silently overwrites the first. Affected fields include `completed_since_verification`, `auto_fix_attempt`, `run_number`, and `accumulated_elapsed_seconds` — all incremented counters. Concurrent updates cause silently lost increments.
- **Recommended Fix**: Replace the read-modify-write with either a `BEGIN IMMEDIATE` transaction that reads and writes atomically in one connection, or take an application-level `threading.Lock` on `StateStore` for all runtime-state mutations.
- **Effort**: M
- **Risk**: Medium

---

### [Security] Finding #10: Branch name / `from_branch` not validated before git subprocess

- **Severity**: High
- **Category**: Security
- **File(s)**: `cognitive_switchyard/server.py:741-753`
- **Evidence**:
  ```python
  result = subprocess.run(
      ["git", "-C", str(resolved), "branch", payload.branch_name, payload.from_branch],
      ...
  )
  ```
- **Impact**: `subprocess.run` with a list avoids shell injection, but git itself parses arguments. A `from_branch` value like `--orphan` would cause git to create an orphan branch instead of branching from the given ref. A `branch_name` or `from_branch` like `../../outside` could reference refs outside the expected namespace. No validation is applied to either field before use.
- **Recommended Fix**: Validate both fields in the Pydantic model with a regex that only allows `[a-zA-Z0-9._/\-]+` (standard git ref characters). Reject any value that starts with `-`.
- **Effort**: S
- **Risk**: Medium

---

### [Security] Finding #11: Path traversal in `_read_release_notes` via session summary JSON

- **Severity**: High
- **Category**: Security
- **File(s)**: `cognitive_switchyard/server.py:1737-1747`
- **Evidence**:
  ```python
  release_notes_relpath = artifacts.get("release_notes_path", "RELEASE_NOTES.md")
  release_notes_path = runtime_paths.session_paths(session_id).root / release_notes_relpath
  return {"path": release_notes_relpath, "content": release_notes_path.read_text(...)}
  ```
- **Impact**: `release_notes_relpath` is read directly from the session's `summary.json` file. If an agent process (which has filesystem write access to the session directory) tampers with `summary.json`, a path like `../../../../etc/passwd` would be joined with `session_paths.root` and its content served to the frontend. No containment check is applied.
- **Recommended Fix**: After constructing `release_notes_path`, call `.resolve()` on both the path and the session root, then assert `candidate.is_relative_to(session_root)`. Return `None` and log a warning if the check fails.
- **Effort**: S
- **Risk**: Medium

---

### [Correctness] Finding #12: `planning_runtime` error path blocks indefinitely on in-flight LLM calls

- **Severity**: High
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/planning_runtime.py:313-318`
- **Evidence**:
  ```python
  if first_error is not None:
      stop_event.set()
      for future in futures:
          future.result()   # blocks until each planner thread finishes
      raise first_error
  ```
- **Impact**: `stop_event` is set, but `planner_worker` only checks `stop_event` at the top of its while loop. A worker currently blocked inside `planner_agent(...)` (an LLM call that may take minutes) will not observe `stop_event` until the call returns. `future.result()` blocks the orchestrator thread for the full duration of all in-flight LLM calls before re-raising the error. Error propagation is delayed by potentially minutes.
- **Recommended Fix**: Use `executor.shutdown(wait=False, cancel_futures=True)` (Python 3.9+) to cancel pending futures immediately, then `wait(futures, timeout=reasonable_timeout)` for any in-flight calls. Accept that in-flight calls may run to completion, but do not block error propagation on them.
- **Effort**: M
- **Risk**: Medium

---

### [Robustness] Finding #13: `collect()` uses `wait(timeout=0)` which can raise `TimeoutExpired`

- **Severity**: High
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/worker_manager.py:172`
- **Evidence**:
  ```python
  worker.process.wait(timeout=0)
  ```
- **Impact**: `collect()` is only called when `worker.finalized` is True, meaning `process.poll()` already returned non-None. So `wait(timeout=0)` almost always succeeds. However, if for any reason the OS has not yet set `returncode` (pathological but possible on some POSIX implementations), `wait(timeout=0)` raises `subprocess.TimeoutExpired`, which is not caught here. While the `finally` block does run (protecting the `_workers.pop`), the caller receives an unexpected `TimeoutExpired` instead of a `WorkerResultError`, bypassing error-handling logic upstream.
- **Recommended Fix**: Replace `worker.process.wait(timeout=0)` with `worker.process.poll()` or remove it entirely, since `returncode` is already populated when `finalized` is True.
- **Effort**: S
- **Risk**: Low

---

### [Robustness] Finding #14: Log file handle leaked when `dispatch()` fails after `Popen` succeeds

- **Severity**: High
- **Category**: Robustness / Resource Leak
- **File(s)**: `cognitive_switchyard/worker_manager.py:102-136`
- **Evidence**:
  ```python
  process = subprocess.Popen(...)         # process is now running
  log_handle = log_path.open("a", ...)   # can raise OSError (disk full, perms)
  worker = _ActiveWorker(...)             # never reached
  self._workers[slot_number] = worker    # never reached
  self._start_reader_threads(worker)     # never reached
  ```
- **Impact**: If `log_path.open()` raises after `Popen` succeeds, the child process is spawned with `stdout=PIPE` and `stderr=PIPE` but no reader threads are started. The process blocks indefinitely once pipe buffers fill (~64KB on Linux). The orchestrator marks the task blocked, but no `process.kill()` is called — the subprocess is permanently orphaned and never reaped. On low-disk systems this can accumulate silently.
- **Recommended Fix**: Open `log_handle` before `Popen` (so failure prevents the launch), or wrap the post-Popen setup in `try/except` that calls `process.kill()` + `process.wait()` before re-raising.
- **Effort**: S
- **Risk**: Medium

---

### [Security] Finding #15: SQL injection latent risk in `_ensure_column` via f-string DDL

- **Severity**: Medium
- **Category**: Security
- **File(s)**: `cognitive_switchyard/state.py:1293-1305`
- **Evidence**:
  ```python
  def _ensure_column(connection, table_name, column_name, column_sql):
      connection.execute(f"PRAGMA table_info({table_name})")
      connection.execute(
          f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"
      )
  ```
- **Impact**: All three parameters are interpolated into SQL with f-strings. Currently all callers pass string literals, so there is no active exploit path. However, if any future caller passes an externally-derived value (config file, user input, pack metadata), this becomes a direct SQL injection vector. `column_sql` is especially dangerous as it allows arbitrary SQL fragments.
- **Recommended Fix**: Add an allowlist validation at the top of `_ensure_column`: assert `table_name` and `column_name` match `^[A-Za-z_][A-Za-z0-9_]*$` and `column_sql` is one of a fixed set of known-safe type declarations. Fail loudly with `ValueError` if validation fails.
- **Effort**: S
- **Risk**: Low

---

### [Correctness] Finding #16: TOCTOU gap remains in `create_session` — prior fix was incomplete

- **Severity**: Medium
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/state.py:105-138`
- **Evidence**:
  ```python
  # Connection 1 — read + conditional delete
  with self._connect() as connection:
      row = connection.execute("SELECT status FROM sessions ...").fetchone()
      if row is not None:
          self.delete_session(session_id)   # opens a THIRD nested connection
  # Connection 2 — insert (with IntegrityError guard — the prior fix)
  with self._connect() as connection:
      try:
          connection.execute("INSERT INTO sessions ...", ...)
      except sqlite3.IntegrityError: ...
  ```
- **Impact**: The `IntegrityError` guard from the pre-launch fix is present, correctly handling the most common race. However, `delete_session` is called from within connection 1, opening a nested connection — the delete and the re-insert are not atomic. A second concurrent `create_session` call with the same terminal session ID can cause the deletion to happen twice, or the insert to collide with a different concurrent caller with no `IntegrityError`. More importantly, the nested connection adds unpredictable lock ordering in WAL mode.
- **Recommended Fix**: Consolidate the existence check, optional delete, and insert into a single connection using `BEGIN IMMEDIATE`. Move the `pre_delete` callback outside the lock (call it before opening any connection).
- **Effort**: M
- **Risk**: Low
- **Prior audit reference**: Pre-launch audit Finding #3 (FIXED — but the `IntegrityError` guard added by that fix does not fully close the gap)

---

### [Correctness] Finding #17: `register_task_plan` TOCTOU + `IntegrityError` not wrapped as `KeyError`

- **Severity**: Medium
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/state.py:154-228`
- **Evidence**:
  ```python
  # Connection 1 — validation
  with self._connect() as connection:
      if self._task_exists(connection, session_id, plan.task_id): raise ...
  # file I/O
  # Connection 2 — insert (no IntegrityError catch)
  with self._connect() as connection:
      connection.execute("INSERT INTO tasks ...", ...)
  ```
- **Impact**: Between connection 1 and connection 2, another thread can insert the same `(session_id, task_id)`. The `PRIMARY KEY` constraint causes an `IntegrityError` that is not caught, so it propagates as a raw `IntegrityError` instead of the expected `KeyError`. The plan file written to disk may or may not be cleaned up depending on whether the cleanup `except Exception` block fires and succeeds.
- **Recommended Fix**: Wrap the `IntegrityError` from the INSERT and convert to `KeyError`. Consolidate into a single connection to close the TOCTOU window.
- **Effort**: S
- **Risk**: Low

---

### [Robustness] Finding #18: `write_worker_recovery_metadata` non-atomic write; crash leaves partial JSON

- **Severity**: Medium
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/state.py:946-975`
- **Evidence**:
  ```python
  recovery_path.write_text(
      json.dumps({...}) + "\n",
      encoding="utf-8",
  )
  ```
- **Impact**: `Path.write_text` truncates then writes. A crash between truncation and completion leaves partial/empty JSON. `read_worker_recovery_metadata` calls `json.loads()` with no error handling, so a corrupt file causes `json.JSONDecodeError` to abort recovery entirely for all subsequent worker slots in that session.
- **Recommended Fix**: Use the `_atomic_write_text` helper (already defined in `state.py:1286`) which uses a temp file + atomic `replace()`. Additionally, add `try/except (json.JSONDecodeError, KeyError)` in `read_worker_recovery_metadata` to return `None` on corrupt files.
- **Effort**: S
- **Risk**: Low

---

### [Correctness] Finding #19: Recovery loop clears slot metadata after first plan file, not after all

- **Severity**: Medium
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/recovery.py:81,117`
- **Evidence**:
  ```python
  for plan_path in sorted(worker_dir.glob("*.plan.md")):
      task_id = plan_path.name.removesuffix(".plan.md")
      ...
      store.clear_worker_recovery_metadata(session_id, slot_number=slot_number)
      continue  # called on every iteration
  ```
- **Impact**: `clear_worker_recovery_metadata` is called per-iteration, not once after the loop. A worker slot containing multiple `*.plan.md` files (anomalous but possible after a partial recovery) will have its metadata cleared after the first file is processed. Subsequent files in the same slot then use `session_paths.root` as the workspace path (fallback when metadata is absent), so `_run_isolate_end` operates on the wrong directory.
- **Recommended Fix**: Move `store.clear_worker_recovery_metadata(...)` outside and after the `for plan_path in ...` loop.
- **Effort**: S
- **Risk**: Low

---

### [Correctness] Finding #20: `_pid_is_running` subject to PID reuse; `waitpid` only reliable for own children

- **Severity**: Medium
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/recovery.py:288-299`
- **Evidence**:
  ```python
  def _pid_is_running(pid: int) -> bool:
      try:
          os.waitpid(pid, os.WNOHANG)
      except ChildProcessError:
          pass    # not our child — fallthrough
      try:
          os.kill(pid, 0)   # check liveness only
      except OSError:
          return False
      return True
  ```
- **Impact**: `os.waitpid` only succeeds for direct children. For PIDs inherited from a prior orchestrator process (recovery scenario), `waitpid` always raises `ChildProcessError`. The liveness check falls through to `os.kill(pid, 0)`, which is correct — but if the PID was recycled by the OS, `kill(pid, 0)` succeeds for the unrelated new process, and the recovery code will send `SIGTERM`/`SIGKILL` to an innocent process.
- **Recommended Fix**: Document the PID-reuse risk with a comment. On Linux, `/proc/{pid}/cmdline` can be checked to verify process identity. On macOS, `psutil.Process(pid).cmdline()` works if available. At minimum, record the command name at worker launch and cross-check during recovery.
- **Effort**: M
- **Risk**: Low

---

### [Robustness] Finding #21: `reconcile_filesystem_projection` iterates `workers/` without existence guard

- **Severity**: Medium
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/state.py:1015`
- **Evidence**:
  ```python
  for worker_dir in sorted(path for path in session_paths.workers.iterdir() ...):
  ```
- **Impact**: If `session_paths.workers` does not exist (newly-created session, or after partial directory creation), `iterdir()` raises `FileNotFoundError`. The analogous loops in `recovery.py:30` and `cleanup_orphaned_workspaces` both guard with `if not session_paths.workers.is_dir(): return`. This inconsistency makes reconciliation crash on new sessions.
- **Recommended Fix**: Add `if not session_paths.workers.is_dir():` guard before the workers iteration, mirroring the pattern used in `recovery.py`.
- **Effort**: S
- **Risk**: Low

---

### [Security] Finding #22: `trim_successful_session_artifacts` follows symlinks; no out-of-root guard

- **Severity**: Medium
- **Category**: Security
- **File(s)**: `cognitive_switchyard/state.py:732-756`
- **Evidence**:
  ```python
  for path in sorted(session_paths.root.rglob("*"), ...):
      if path.is_file():
          path.unlink()
  ```
- **Impact**: `rglob("*")` follows symlinks by default. If a worker pack's scripts left a hardlink to a file outside the session root, `path.unlink()` would delete that external file. Symlinks themselves are safe (unlinking a symlink removes the link, not the target), but hardlinks are not.
- **Recommended Fix**: After resolving each `path`, assert `path.resolve().is_relative_to(session_paths.root.resolve())`. Skip any path that resolves outside the session root.
- **Effort**: S
- **Risk**: Low

---

### [Correctness] Finding #23: `store.get_task()` unguarded in `_collect_finished_workers`

- **Severity**: Medium
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/orchestrator.py:742`
- **Evidence**:
  ```python
  active_task = store.get_task(session_id, snapshot.task_id)  # raises KeyError if missing
  ```
- **Impact**: If `_task_id_from_path` produces a garbage ID (non-conformant plan filename), or the DB is partially restored, `store.get_task()` raises `KeyError` with no handling. This aborts all of `_collect_finished_workers`, leaving subsequent finished workers uncollected for this poll cycle, and eventually causes the main loop to exit with an unhandled exception while worker subprocesses continue running.
- **Recommended Fix**: Wrap `store.get_task()` in `try/except KeyError`. On failure: log the error, call `manager.collect(slot_number)` anyway to remove the slot, and skip task state transitions.
- **Effort**: S
- **Risk**: Low

---

### [Security] Finding #24: Pack name path traversal in `/api/packs/{name}` endpoint

- **Severity**: Medium
- **Category**: Security
- **File(s)**: `cognitive_switchyard/server.py:656-659`, `server.py:1806-1810`
- **Evidence**:
  ```python
  def _load_runtime_pack(runtime_paths: RuntimePaths, name: str) -> PackManifest:
      pack_path = runtime_paths.packs / name
      if not pack_path.is_dir():
          raise HTTPException(status_code=404, detail="Unknown pack.")
      return load_pack_manifest(pack_path)
  ```
- **Impact**: A request for `/api/packs/../../../etc` constructs a path outside the packs root. The `is_dir()` check acts as a mild filter, but if the path resolves to an existing directory, `load_pack_manifest` attempts to parse it, potentially reading sensitive files.
- **Recommended Fix**: After constructing `pack_path`, resolve it and assert `pack_path.resolve().is_relative_to(runtime_paths.packs.resolve())`. Alternatively, validate `name` with `^[a-zA-Z0-9._-]+$` (no slashes).
- **Effort**: S
- **Risk**: Low

---

### [Correctness] Finding #25: Bulk `purge_completed_sessions` lacks active-thread guard

- **Severity**: Medium
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/server.py:1120-1128`
- **Evidence**:
  ```python
  for session in store.list_sessions():
      if session.status in {"idle", "completed", "aborted"}:
          cleanup_session_worktree_if_needed(session)
          store.delete_session(session.id)  # no thread-alive check
  ```
- **Impact**: The single-session `purge_session` endpoint guards against active threads with `has_active_thread`. The bulk endpoint does not. A session whose background thread is winding down (status set to "idle" but thread still running) can have its DB rows and filesystem deleted while the orchestrator thread is still accessing them. The thread crashes with `KeyError` / `FileNotFoundError`, swallowed by `_run_session`'s outer `try/except`.
- **Recommended Fix**: Skip (log and continue) any session where `session_controller.has_active_thread(session.id)` returns True.
- **Effort**: S
- **Risk**: Low

---

### [Concurrency] Finding #26: `_get_cached_pack_manifest` unsynchronized read-modify-write on cache

- **Severity**: Medium
- **Category**: Concurrency
- **File(s)**: `cognitive_switchyard/server.py:488-495`
- **Evidence**:
  ```python
  def _get_cached_pack_manifest(self, session_id: str) -> PackManifest:
      cached = self._pack_cache.get(session_id)    # no lock
      if cached is not None:
          return cached
      manifest = load_pack_manifest(...)
      self._pack_cache[session_id] = manifest      # no lock
      return manifest
  ```
- **Impact**: `_evict_session_cache` modifies `_pack_cache` under `self._lock`, but `_get_cached_pack_manifest` reads and writes without holding the lock. An eviction can pop a key between the `.get()` returning `None` and the subsequent write, causing a stale entry to be re-inserted for a just-evicted session.
- **Recommended Fix**: Acquire `self._lock` for the entire check-and-set in `_get_cached_pack_manifest`, consistent with how `_evict_session_cache` holds the lock for mutation.
- **Effort**: S
- **Risk**: Low

---

### [Robustness] Finding #27: `_finalize_worker` closes log handle without lock; races with reader thread

- **Severity**: Medium
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/worker_manager.py:349-354`
- **Evidence**:
  ```python
  def _finalize_worker(self, worker: _ActiveWorker) -> None:
      for reader in worker.readers:
          reader.join(timeout=1.0)     # can time out without confirming exit
      worker.log_handle.flush()
      worker.log_handle.close()        # no lock held
      worker.finalized = True          # no lock held
  ```
- **Impact**: After `reader.join(timeout=1.0)`, a reader thread may still be running (the join timed out). That reader can call `worker.log_handle.write()` after `_finalize_worker` has closed the handle, raising `ValueError: I/O operation on closed file` in the reader thread. This exception is silently swallowed in the reader's except-block, truncating the log.
- **Recommended Fix**: After the join, check `reader.is_alive()` and log a warning if True. Acquire `worker.lock` before `flush()`, `close()`, and setting `finalized = True` to make these atomic with respect to lock-holding callers.
- **Effort**: M
- **Risk**: Low

---

### [Correctness] Finding #28: `plan_text` may be unbound in `ArtifactParseError` handler in `planning_runtime`

- **Severity**: Medium
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/planning_runtime.py:243-296`
- **Evidence**:
  ```python
  try:
      plan_text = planner_agent(...)           # line A
      staged_plan = parse_staged_task_plan(plan_text, ...)   # line B
      ...
  except ArtifactParseError:
      error_body = f"```\n{plan_text[:2000]}\n```\n"  # plan_text may be unbound if line A raised
  ```
- **Impact**: `ArtifactParseError` is caught for both lines A and B. If `planner_agent` itself raises `ArtifactParseError`, `plan_text` is unbound in the except handler, causing `UnboundLocalError`. This crashes the worker thread with a confusing error, bypassing the parse-error handling entirely.
- **Recommended Fix**: Initialize `plan_text = ""` before the try block, or split into two separate try/except blocks: one for `planner_agent(...)` and a nested one for `parse_staged_task_plan(...)`.
- **Effort**: S
- **Risk**: Low

---

### [Correctness] Finding #29: Cycle detection leaves stale `visiting` state in `_build_passthrough_resolution`

- **Severity**: Medium
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/planning_runtime.py:511-527`
- **Evidence**:
  ```python
  def depth(task_id):
      if task_id in visiting:
          conflicts.append(f"circular dependency detected at {task_id}")
          return 1   # early return — visiting.remove() for this node never called
      visiting.add(task_id)
      ...
      visiting.remove(task_id)
  ```
- **Impact**: When a cycle is detected, the function returns early without calling `visiting.remove()` for the current node. In long cycles (A→B→C→A), intermediate nodes remain in `visiting`, potentially causing false-positive cycle reports for nodes that appear in other valid dependency chains. In practice, since any cycle causes the resolution phase to fail and the session to pause, the incorrect `exec_order` values never reach execution — but the duplicate conflict messages can obscure the real cycle location.
- **Recommended Fix**: Use the standard DFS coloring approach (white/grey/black). On cycle detection, add the cycle entry to `depth_cache` with a sentinel value to prevent re-traversal. Alternatively, use `itertools.pairwise` on the detected cycle path to report the exact edge.
- **Effort**: M
- **Risk**: Low

---

### [Security] Finding #30: `_load_prompt_bundle` has no path confinement check

- **Severity**: Medium
- **Category**: Security
- **File(s)**: `cognitive_switchyard/agent_runtime.py:301-309`
- **Evidence**:
  ```python
  def _load_prompt_bundle(prompt_path: Path) -> str:
      prompt_text = prompt_path.read_text(encoding="utf-8").strip()
      system_prompt_path = prompt_path.with_name("system.md")
      if not system_prompt_path.is_file():
          return prompt_text
      system_text = system_prompt_path.read_text(encoding="utf-8").strip()
  ```
- **Impact**: `prompt_path` is derived from pack manifest data. While `pack_loader._optional_pack_path` confines paths at load time, `_load_prompt_bundle` itself performs no confinement check and reads whatever `Path` it receives. A future call site that bypasses pack manifest validation (test, refactor) could read arbitrary files.
- **Recommended Fix**: Accept a `pack_root: Path` parameter and assert `prompt_path.resolve().is_relative_to(pack_root)` at the top of the function. Apply the same check to the `system.md` sibling.
- **Effort**: S
- **Risk**: Low

---

### [Security] Finding #31: `_validated_conventional_hook_path` returns unresolved symlink path (TOCTOU)

- **Severity**: Medium
- **Category**: Security
- **File(s)**: `cognitive_switchyard/pack_loader.py:513-522`
- **Evidence**:
  ```python
  def _validated_conventional_hook_path(path, pack_root, hook_name):
      resolved = path.resolve()
      resolved.relative_to(pack_root)   # containment check on resolved path
      return path   # returns UNRESOLVED path
  ```
- **Impact**: The containment check uses `resolved` but the returned value is the unresolved `path` (potentially a symlink). If the symlink target changes between validation and execution (TOCTOU), the hook runs against an unexpected file. Additionally, `_optional_pack_path` (used for manifest-declared paths) returns `resolved`, creating an inconsistency: conventional hooks may be symlinks while manifest paths are always real paths.
- **Recommended Fix**: Return `resolved` instead of `path`.
- **Effort**: S
- **Risk**: Low

---

### [Robustness] Finding #32: No upper bound on `max_workers` / `max_instances` in pack manifest

- **Severity**: Medium
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/pack_loader.py:303,365`
- **Evidence**:
  ```python
  max_instances=_int(planning_data.get("max_instances", 1), ...)
  max_workers=_int(execution_data.get("max_workers", 2), ...)
  ```
- **Impact**: A `pack.yaml` with `max_workers: 9999` is accepted without complaint. If the orchestrator uses this value directly to size a thread pool or semaphore, it can exhaust file descriptors, memory, or API rate limits.
- **Recommended Fix**: Add an upper bound check in `_build_manifest` (e.g., 64 or a configurable cap). Emit a `ValidationFinding` if the value exceeds the bound.
- **Effort**: S
- **Risk**: Low

---

### [Security/Correctness] Finding #33: `yaml.load(BaseLoader)` in `parsers.py` should be `yaml.safe_load`

- **Severity**: Medium
- **Category**: Security / Correctness
- **File(s)**: `cognitive_switchyard/parsers.py:329`
- **Evidence**:
  ```python
  loaded = yaml.load(text, Loader=yaml.BaseLoader)
  ```
- **Impact**: `yaml.BaseLoader` deserializes all scalars as strings (types are not inferred), creating a mismatch with `yaml.safe_load` used in `pack_loader.py`. The bare `yaml.load()` call is also fragile: if the `Loader` argument were accidentally removed during a refactor, older PyYAML versions default to the unsafe `yaml.Loader` (arbitrary object construction from untrusted YAML). The inconsistency with `yaml.safe_load` confuses maintainers and may cause subtle type coercion bugs (e.g., `EXEC_ORDER: 3` parsed as string `"3"` rather than int `3`).
- **Recommended Fix**: Replace with `yaml.safe_load(text)`. Update downstream type coercions that currently rely on all-string output from `BaseLoader` (primarily `_required_int`).
- **Effort**: S
- **Risk**: Low

---

### [Security] Finding #34: ReDoS vector in progress line parser via pack-controlled `progress_format`

- **Severity**: Medium
- **Category**: Security / Performance
- **File(s)**: `cognitive_switchyard/parsers.py:129,202-219`
- **Evidence**:
  ```python
  def _progress_patterns(progress_format, source):
      phase_re = re.compile(rf"^(?:{progress_format})\s+...")
      detail_re = re.compile(rf"^(?:{progress_format})\s+...")
  ```
- **Impact**: `progress_format` comes from pack manifest YAML and is injected into a regex. A crafted pack could supply a pathological pattern (e.g., `(a+)+`) causing catastrophic backtracking on every log line. `pack_loader` validates that the value compiles as a regex but does not guard against ReDoS patterns. Additionally, the compiled patterns are not cached, so `re.compile` is called twice per log line.
- **Recommended Fix**: Add `@functools.lru_cache` to `_progress_patterns`. For the ReDoS concern, restrict `progress_format` to a fixed prefix string (not a full regex), or set a strict length limit and character allowlist.
- **Effort**: S (caching) / L (ReDoS hardening)
- **Risk**: Low

---

### [Robustness] Finding #35: `run_verification_command` log write failure is unhandled

- **Severity**: Medium
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/verification_runtime.py:30-31`
- **Evidence**:
  ```python
  verify_log_path.parent.mkdir(parents=True, exist_ok=True)
  verify_log_path.write_text(output, encoding="utf-8")
  ```
- **Impact**: Both lines can raise `OSError` (disk full, permissions). The exception propagates uncaught, interrupting the verification pipeline. The subprocess already ran and its result is lost.
- **Recommended Fix**: Wrap in `try/except OSError`. On failure: log a warning, set `log_path=None`, and still return a `VerificationRunResult` with the output in memory.
- **Effort**: S
- **Risk**: Low

---

### [Robustness] Finding #36: `_tail_text` raises `UnicodeDecodeError` on non-UTF-8 worker output

- **Severity**: Medium
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/verification_runtime.py:110-114`
- **Evidence**:
  ```python
  return path.read_text(encoding="utf-8")
  ```
- **Impact**: Worker log files are written by external processes (Claude CLI, shell scripts). If any subprocess emits bytes outside UTF-8 (terminal escape sequences, locale-encoded output), `read_text` raises `UnicodeDecodeError`. `build_task_failure_context` fails with an exception at exactly the time recovery context is most needed.
- **Recommended Fix**: Pass `errors="replace"` or `errors="backslashreplace"` to `read_text`. The tail is diagnostic; losing exact bytes is acceptable.
- **Effort**: S
- **Risk**: Low

---

### [Security] Finding #37: Unquoted path components in `ScriptPermissionIssue.fix_command`

- **Severity**: Medium
- **Category**: Security
- **File(s)**: `cognitive_switchyard/hook_runner.py:40`
- **Evidence**:
  ```python
  fix_command=f"chmod +x {canonical_pack_path(pack_manifest.name, relative_path)}",
  ```
- **Impact**: `pack_manifest.name` and `relative_path` are inserted into a shell string without quoting. A pack name containing spaces or shell metacharacters produces a broken or dangerous command. If a user copies and pastes this command into a terminal, the result could be command injection.
- **Recommended Fix**: Use `shlex.quote()` on both components when building `fix_command`.
- **Effort**: S
- **Risk**: Low

---

### [Correctness] Finding #38: Mutable `list` field on `frozen=True` `PackManifest` dataclass

- **Severity**: Medium
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/models.py:102`
- **Evidence**:
  ```python
  @dataclass(frozen=True)
  class PackManifest:
      prerequisites: list[PrerequisiteCheck] = field(default_factory=list)
  ```
- **Impact**: `frozen=True` prevents rebinding the attribute but not mutating the list in-place. Callers that receive a `PackManifest` have an implicit immutability contract that can be silently violated by `manifest.prerequisites.append(...)`. All other collection fields on frozen dataclasses in this file use `tuple`.
- **Recommended Fix**: Change to `tuple[PrerequisiteCheck, ...]` with a `tuple` default. Update callers as needed.
- **Effort**: S
- **Risk**: Low

---

### [Correctness] Finding #39: Mutable `dict` fields on `frozen=True` dataclasses

- **Severity**: Medium
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/models.py:301,338`
- **Evidence**:
  ```python
  @dataclass(frozen=True)
  class SessionConfigOverrides:
      environment: dict[str, str] = field(default_factory=dict)

  @dataclass(frozen=True)
  class EffectiveSessionRuntimeConfig:
      environment: dict[str, str] = field(default_factory=dict)
  ```
- **Impact**: Same class of issue as Finding #38. A caller holding a reference to `.environment` can mutate it, silently altering the environment seen by later code in the same call chain.
- **Recommended Fix**: Use `types.MappingProxyType` as the runtime container, or change the type annotation to `dict[str, str]` while documenting immutability intent with a comment.
- **Effort**: S
- **Risk**: Low

---

### [Robustness] Finding #40: `load_global_config` coerces config values with bare `int()`, no bounds checking

- **Severity**: Medium
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/config.py:184-188`
- **Evidence**:
  ```python
  retention_days=int(values.get("retention_days", 30)),
  default_planners=int(values.get("default_planners", 3)),
  default_workers=int(values.get("default_workers", 3)),
  ```
- **Impact**: Non-integer YAML values (e.g., `"thirty"`, `"30days"`) cause `int()` to raise `ValueError` or `TypeError` with a raw Python traceback instead of an actionable error. Values of `0` or negative numbers are accepted silently and can cause misbehavior (e.g., `default_workers: 0` results in no workers running).
- **Recommended Fix**: Validate that each field is an `int`, positive, and within reasonable bounds after parsing. Raise `ValueError` with a human-readable message including the field name and received value.
- **Effort**: S
- **Risk**: Low

---

### [Security] Finding #41: `bootstrap_if_needed` installs dependencies without hash verification

- **Severity**: Medium
- **Category**: Security
- **File(s)**: `cognitive_switchyard/bootstrap.py:133-141`
- **Evidence**:
  ```python
  subprocess.run(
      [str(python_executable), "-m", "pip", "install", "-r", str(requirements_path)],
      check=True,
  )
  ```
- **Impact**: `pip install -r requirements.txt` with no `--require-hashes` performs no integrity checking. If `requirements.txt` contains unpinned versions or a supply-chain compromise occurs, a different package version could be silently installed. This is the bootstrap installer, so it runs with elevated privilege relative to normal code.
- **Recommended Fix**: Pin all dependencies with hashes in `requirements.txt` and add `--require-hashes` to the pip invocation. Alternatively, use `pip-compile --generate-hashes` to generate a lockfile.
- **Effort**: M
- **Risk**: Low

---

### [Low] Finding #42: `_terminate_pid` SIGKILL failure silently ignored; no logging

- **Severity**: Low
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/recovery.py:265-285`
- **Evidence**: After `os.kill(pid, signal.SIGKILL)`, the function spin-waits for the process to die. If it survives SIGKILL (kernel zombie, PID reuse), the function returns normally with no warning. Recovery proceeds as if termination succeeded.
- **Recommended Fix**: After the spin-wait exits without the process dying, log a warning: `"PID {pid} did not terminate after SIGKILL; proceeding anyway"`.
- **Effort**: S
- **Risk**: Low

---

### [Low] Finding #43: `append_event` log file write outside DB transaction; write failures uncaught

- **Severity**: Low
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/state.py:848-877`
- **Evidence**:
  ```python
  with self._connect() as connection:
      connection.execute("INSERT INTO events ...", ...)
      connection.commit()
  # --- transaction closed ---
  with session_log_path.open("a") as handle:
      handle.write(...)    # no try/except
  ```
- **Impact**: A file write failure (disk full, permissions) after a successful DB commit surfaces as an unhandled exception from the caller of `append_event`. The DB row exists but the log file does not reflect it.
- **Recommended Fix**: Wrap the file write in `try/except OSError` and log a warning. The flat log is auxiliary; the DB is authoritative.
- **Effort**: S
- **Risk**: Low

---

### [Low] Finding #44: `read_worker_recovery_metadata` bare key access with no error handling

- **Severity**: Low
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/state.py:977-993`
- **Evidence**:
  ```python
  payload = json.loads(recovery_path.read_text(...))
  return WorkerRecoveryMetadata(
      task_id=payload["task_id"],          # KeyError if missing
      workspace_path=Path(payload["workspace_path"]),   # KeyError if missing
  )
  ```
- **Impact**: A corrupt or schema-mismatched recovery file causes `KeyError` with no handling, propagating through `recover_execution_session` and aborting recovery entirely. The file remains on disk, causing the same crash on every subsequent recovery attempt.
- **Recommended Fix**: Wrap key accesses in `try/except (json.JSONDecodeError, KeyError, ValueError)`. Log a warning, delete or quarantine the corrupt file, and return `None`.
- **Effort**: S
- **Risk**: Low

---

### [Low] Finding #45: `reconcile_filesystem_projection` does not update `started_at` for recovered active tasks

- **Severity**: Low
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/state.py:1053-1067`
- **Evidence**: The reconcile UPDATE sets `status`, `worker_slot`, `plan_relpath`, and `completed_at` but omits `started_at`. A task found in `workers/<N>/` (status=active) after a crash may have `started_at = NULL` in the DB.
- **Recommended Fix**: In the reconcile update, also set `started_at = COALESCE(started_at, CURRENT_TIMESTAMP)` for active tasks to ensure elapsed-time calculations are non-null after recovery.
- **Effort**: S
- **Risk**: Low

---

### [Low] Finding #46: `verification_started_at` not cleared between auto-fix iterations

- **Severity**: Low
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/orchestrator.py:1272-1334`
- **Evidence**: When an auto-fix loop re-enters `auto_fixing` state after a failed inner verification, `verification_started_at` is not cleared. The stale timestamp (from the previous `verifying` state) remains in the runtime state, causing incorrect duration calculations in the UI for subsequent attempts.
- **Recommended Fix**: Add `verification_started_at=None` to the `write_session_runtime_state` call at the start of each loop iteration (when entering `auto_fixing`).
- **Effort**: S
- **Risk**: Low

---

### [Low] Finding #47: Auto-fix budget effectively doubled across task/verification failure contexts

- **Severity**: Low
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/orchestrator.py:884-936`, `orchestrator.py:1241-1344`
- **Evidence**: `_handle_failed_task` exhausts `auto_fix_max_attempts` for `task_failure` context. If interval verification fires afterward, `_run_pending_verification` runs *another* independent loop of up to `auto_fix_max_attempts` with `auto_fix_context="verification_failure"`. The attempt counter resets.
- **Impact**: Effective maximum fixer invocations is `2 × auto_fix_max_attempts` per task failure — potentially doubling LLM API cost and session duration.
- **Recommended Fix**: Either treat the `task_failure` budget as consumed globally so `verification_failure` starts from `remaining = max_attempts - task_attempts`, or document the separate-budget behavior explicitly with a comment explaining why it is intentional.
- **Effort**: S (doc) / M (counter sharing)
- **Risk**: Low

---

### [Low] Finding #48: `force_reset_session` uses `session_id` in `shutil.rmtree` without format validation

- **Severity**: Low
- **Category**: Security
- **File(s)**: `cognitive_switchyard/server.py:1079-1118`
- **Evidence**:
  ```python
  session_root = runtime_paths.session(session_id)
  if session_root.exists():
      shutil.rmtree(session_root, ignore_errors=True)
  ```
- **Impact**: `force_reset_session` intentionally handles the orphaned-directory case (no DB row). If `session_id` contains path traversal characters (e.g., `../../target`), `runtime_paths.session(session_id)` resolves outside the sessions directory, and `shutil.rmtree` silently attempts to delete it.
- **Recommended Fix**: Add a `_SESSION_ID_RE.match(session_id)` check (consistent with `create_session`) before the rmtree path.
- **Effort**: S
- **Risk**: Low

---

### [Low] Finding #49: `serve` subcommand uses fixed port with no free-port fallback

- **Severity**: Low
- **Category**: Robustness
- **File(s)**: `cognitive_switchyard/cli.py:91-93`
- **Evidence**:
  ```python
  serve_parser.add_argument("--port", type=int, default=8100)
  ```
- **Impact**: The repo's own `CLAUDE.md` mandates: "Never hardcode a single port. Always scan for a free port starting from the preferred default." The `serve` command violates this pattern. If port 8100 is in use, startup fails with a socket error.
- **Recommended Fix**: Apply the `find_free_port(start_port, max_attempts=20)` pattern from the repo `CLAUDE.md` inside `handle_serve`.
- **Effort**: S
- **Risk**: Low

---

### [Low] Finding #50: `_required_int` in `parsers.py` uses `str.isdigit()` incorrectly

- **Severity**: Low
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/parsers.py:387-397`
- **Evidence**:
  ```python
  if isinstance(value, str) and value.isdigit():
      return int(value)
  ```
- **Impact**: `str.isdigit()` returns `False` for negative integers (`"-1"`), causing a confusing `ArtifactParseError` instead of a bounds check. More critically, Unicode superscript digits (e.g., `"²"`) return `True` from `isdigit()`, after which `int("²")` raises an unhandled `ValueError` (not `ArtifactParseError`), propagating as an unexpected exception from the parser.
- **Recommended Fix**: Replace the `isdigit()` guard with `try: return int(value) / except ValueError: pass`.
- **Effort**: S
- **Risk**: Low

---

### [Low] Finding #51: Front matter regex breaks on CRLF line endings

- **Severity**: Low
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/parsers.py:21`
- **Evidence**:
  ```python
  _FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
  ```
- **Impact**: A plan file with Windows-style CRLF line endings (`---\r\n`) fails to match, producing a confusing "missing YAML front matter" error with no indication that line endings are the cause.
- **Recommended Fix**: Allow optional `\r` before `\n`: `r"\A---\r?\n(.*?)\n---\r?\n?"`.
- **Effort**: S
- **Risk**: Low

---

### [Low] Finding #52: `command_needs_bootstrap` index arithmetic can skip subcommand name

- **Severity**: Low
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/bootstrap.py:63-68`
- **Evidence**:
  ```python
  if current in BOOTSTRAP_OPTION_FLAGS:
      index += 2    # consumes flag AND its value
  ```
- **Impact**: If `--runtime-root` appears with no following value (trailing flag), `index += 2` pushes past `len(argv)`. The while-guard prevents `IndexError`, but the subcommand name is never reached and `command_needs_bootstrap` returns `False`, silently skipping bootstrap for commands that require it.
- **Recommended Fix**: Verify `index + 1 < len(argv)` before advancing by 2. Treat a missing value as a malformed invocation.
- **Effort**: S
- **Risk**: Low

---

### [Low] Finding #53: `_PRAGMA journal_mode = WAL` on every connection is redundant

- **Severity**: Low
- **Category**: Performance
- **File(s)**: `cognitive_switchyard/state.py:1154-1161`
- **Evidence**:
  ```python
  connection.execute("PRAGMA journal_mode = WAL")   # in every _connect() call
  ```
- **Impact**: `PRAGMA journal_mode = WAL` is a persistent, database-level setting; it only needs to be set once (already done in `initialize_state_store`). Setting it on every connection adds two pragma round-trips per operation. In Python's `sqlite3` module, executing any non-SELECT SQL in a new connection causes an implicit `BEGIN`, which means every read-only connection holds a read transaction open slightly longer than necessary, potentially interfering with WAL checkpoint progress at high connection rates.
- **Recommended Fix**: Remove `PRAGMA journal_mode = WAL` from `_connect`. Keep `PRAGMA foreign_keys = ON` (which is connection-scoped and must be set on each connection). Add a comment in `initialize_state_store` noting that WAL is a persistent setting.
- **Effort**: S
- **Risk**: Low

---

### [Low] Finding #54: `_serialize_intake_listing` includes `CLAUDE.md`; inconsistent with REST endpoint

- **Severity**: Low
- **Category**: Correctness
- **File(s)**: `cognitive_switchyard/server.py:1691-1715`
- **Evidence**: `get_intake` (REST endpoint) filters `path.name in ("NEXT_SEQUENCE", "CLAUDE.md")`. `_serialize_intake_listing` (bootstrap payload) does not apply this filter. `CLAUDE.md` appears in the initial UI load but disappears on the next refresh.
- **Recommended Fix**: Apply the same `path.name in ("NEXT_SEQUENCE", "CLAUDE.md")` filter in `_serialize_intake_listing`.
- **Effort**: S
- **Risk**: Low

---

### [Low] Finding #55: Model argument not validated before use in Claude CLI command

- **Severity**: Low
- **Category**: Security
- **File(s)**: `cognitive_switchyard/agent_runtime.py:140-147`
- **Evidence**:
  ```python
  command = [self.command, "--dangerously-skip-permissions", "--model", model, "-p", prompt_text]
  ```
- **Impact**: `model` comes from the pack manifest and is passed unvalidated. While the list-form `subprocess` prevents shell injection, a crafted model string could manipulate the Claude CLI's argument parsing (e.g., a value beginning with `--` could be misinterpreted as a flag).
- **Recommended Fix**: Validate `model` against a regex like `^[a-zA-Z0-9._/-]{1,100}$` before constructing the command.
- **Effort**: S
- **Risk**: Low

---

## HTML Template (html_template.py)

All Python interpolation points in `html_template.py` are safely escaped:
1. `__BOOTSTRAP_JSON__`: serialized via `json.dumps` + Unicode-escape of `&`, `<`, `>`, placed in a `type="application/json"` script tag, consumed only via `JSON.parse(textContent)` in JavaScript.
2. `__DESIGN_TOKENS_BLOCK__`: fully static module-level CSS constant; no user-controlled data.

**No findings for `html_template.py`.**

---

## Carried Forward

### From cleanup_audit_20260310.md

**Finding #10: Dashboard query consolidation**
`build_dashboard_payload` in `server.py` calls `list_ready_tasks`, `list_active_tasks`, `list_done_tasks`, `list_blocked_tasks`, and `list_active_tasks` again — 5 separate SQLite queries per dashboard render. Recommended fix: single `list_all_tasks(session_id)` query, partition by status in Python.
- **Status**: Was in Phase 3 (Optional) of the cleanup audit implementation plan. Commit `5f9c4a6` (wip: 002-b) references "CF-1 single task query" — verify whether this was completed before closing.

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 1 |
| High | 14 |
| Medium | 24 |
| Low | 16 |
| **Total** | **55** |

### Top Remediation Priorities

1. **Finding #1** (Critical) — `shell=True` in `run_verification_command`. Address before any production use.
2. **Finding #2** (High) — `shell=True` in `run_prerequisite_checks`.
3. **Findings #3, #4, #5** (High) — Missing subprocess timeouts across `agent_runtime`, `hook_runner`, and `verification_runtime`. Collectively these can cause the orchestrator to hang indefinitely.
4. **Finding #6** (High) — `fixer_executor` exception abandons workers; add top-level error handling in `execute_session`.
5. **Finding #9** (High) — `write_session_runtime_state` lost-update race under parallel planners — silent counter corruption.
6. **Findings #10, #11, #24** (High/Medium) — Path traversal and injection vectors in server endpoints.
7. **Findings #38, #39** (Medium) — Mutable fields on frozen dataclasses; straightforward one-line type changes.
8. **Finding #33** (Medium) — `yaml.load(BaseLoader)` → `yaml.safe_load` for consistency and safety.
