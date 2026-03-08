# Phase 5: Orchestrator Loop, File-as-State, and Crash Recovery

## Spec

Build the main orchestration loop that ties together the scheduler, worker manager, pack loader, and state store. This phase adds file-as-state management (moving task files between directories), the dispatch loop, phase transitions, and crash recovery on restart.

### Dependencies from prior phases

- `switchyard/models.py` — All dataclasses.
- `switchyard/config.py` — Path constants, `load_config()`.
- `switchyard/state.py` — `StateStore`, `create_session_dirs()`.
- `switchyard/pack_loader.py` — `PackConfig`, `load_pack()`, `run_hook()`, `parse_status_sidecar()`, `check_executable_bits()`, `run_preflight()`.
- `switchyard/scheduler.py` — `next_eligible()`, `all_eligible()`, `validate_constraint_graph()`, `load_constraint_graph()`, `apply_constraints()`.
- `switchyard/worker_manager.py` — `WorkerManager`.

### Files to create

**`switchyard/orchestrator.py`**:

**`Orchestrator(session_id: str, store: StateStore, pack: PackConfig, broadcast_fn: Optional[Callable] = None)`:**

Constructor takes session ID, state store, loaded pack config, and an optional broadcast callback for pushing state changes to the UI (WebSocket). The broadcast function signature is `broadcast_fn(event_type: str, data: dict)`.

**Core loop — `run(poll_interval: float = 1.0)`:**
Runs the main dispatch loop. This is a blocking call intended to run in a background thread. Loop body (each iteration):

1. **Poll workers** — For each active slot, call `worker_manager.poll()`. If finished, call `worker_manager.collect()`, then `run_hook("isolate_end", ...)`. Move task file: on success → `done/`, on failure → enter auto-fix or → `blocked/`. Update state store. Broadcast `task_status_change`.
2. **Check timeouts** — Call `worker_manager.check_timeouts()`. For kill events: call `worker_manager.kill()`, run `isolate_end` with "blocked", move task to `blocked/`. For warnings: broadcast alert.
3. **Dispatch** — For each idle slot, call `scheduler.all_eligible()` with current `done_ids` and `active_ids` from state store. Dispatch the next eligible task: move file from `ready/` to `workers/<slot>/`, call `worker_manager.dispatch()`, update state store.
4. **Check session completion** — If no tasks in `ready`, `active`, or `planning`/`staged` status, and at least one task exists, set session to `completed`. Run post-completion trimming.
5. **Session timeout** — If `session_max > 0` and elapsed exceeds it, kill all workers, set session `aborted`.
6. Sleep `poll_interval`.

Loop exits when session status is `completed`, `aborted`, or `paused`.

**File-as-state operations (private methods):**

- `_move_task_file(task_id: str, from_dir: str, to_dir: str)` — Atomic `os.rename()` of `<task_id>.plan.md`. If source doesn't exist (race condition, already moved), log and skip (idempotent).
- `_task_file_location(task_id: str) -> Optional[str]` — Scan state directories to find which directory contains `<task_id>.plan.md`. Returns directory name or None.
- `_sync_db_from_filesystem()` — Scan all state directories, compare with database, fix any mismatches. Filesystem is source of truth.

**Crash recovery — `recover()`:**
Called on startup before entering the main loop. Must be called explicitly by the CLI entry point.

1. **Orphaned workers** — Scan `workers/<N>/` for plan files. For each:
   - If a `.status` sidecar exists with `STATUS: done`: run `isolate_end` with "done", move to `done/`.
   - Otherwise: run `isolate_end` with "blocked", move plan back to `ready/` (infrastructure failure, not task failure).
2. **Orphaned claims** — Move any plan files in `claimed/` back to `intake/`.
3. **Partial resolution** — If `resolution.json` exists but is incomplete (can't parse), delete it. Move any plan in `ready/` without constraint metadata back to `staging/`.
4. **DB reconciliation** — Call `_sync_db_from_filesystem()`.
5. **Zombie processes** — Check for PID files in the session directory. Kill any still-running processes.

**Post-completion trimming — `_trim_session()`:**
On successful completion (all tasks done, zero blocked):
- Write `summary.json` with: session metadata, per-task final status, timing, worker utilization.
- Delete: `intake/`, `claimed/`, `staging/`, `ready/`, `workers/`, `done/`, `blocked/`, `logs/workers/`, verification logs.
- Keep: `summary.json`, `resolution.json`, `logs/session.log`.

**Session event logging:**
All state transitions are logged via `store.add_event()` and written to `logs/session.log`.

**`pause()` / `resume()` / `abort()`:**
- `pause()` — Sets a flag. Loop stops dispatching new tasks but continues polling active workers.
- `resume()` — Clears pause flag, loop resumes dispatching.
- `abort()` — Kills all active workers, moves active tasks to `blocked/`, sets session `aborted`.

## Acceptance tests

```python
"""tests/test_phase05_orchestrator.py"""
import json
import os
import shutil
import stat
import threading
import time
from pathlib import Path

import pytest


def _write_script(path, content):
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _setup_test_env(tmp_path, monkeypatch, execute_script=None, num_tasks=2):
    """Create a full test environment with pack, session, and tasks."""
    from switchyard import config
    from switchyard.state import StateStore, create_session_dirs
    from switchyard.pack_loader import load_pack
    from switchyard.models import Session, Task

    # Redirect paths
    home = tmp_path / ".switchyard"
    home.mkdir()
    monkeypatch.setattr(config, "SWITCHYARD_HOME", str(home))
    monkeypatch.setattr(config, "PACKS_DIR", str(home / "packs"))
    monkeypatch.setattr(config, "SESSIONS_DIR", str(home / "sessions"))
    (home / "packs").mkdir()
    (home / "sessions").mkdir()

    # Create pack
    pack_dir = home / "packs" / "test"
    pack_dir.mkdir()
    scripts_dir = pack_dir / "scripts"
    scripts_dir.mkdir()

    if execute_script is None:
        execute_script = (
            '#!/bin/bash\n'
            'echo "##PROGRESS## $(basename $1 .plan.md) | Phase: running | 1/1"\n'
            'echo "working"\n'
            'SIDECAR="${1%.plan.md}.status"\n'
            'echo "STATUS: done" > "$SIDECAR"\n'
            'echo "TESTS_RAN: none" >> "$SIDECAR"\n'
            'echo "TEST_RESULT: skip" >> "$SIDECAR"\n'
        )

    (pack_dir / "pack.yaml").write_text(
        "name: test\ndescription: test\nversion: '1'\n"
        "phases:\n  execution:\n    enabled: true\n    executor: shell\n"
        "    command: scripts/execute\n    max_workers: 4\n"
        "isolation:\n  type: none\n  setup: scripts/isolate_start\n"
        "  teardown: scripts/isolate_end\n"
    )
    _write_script(scripts_dir / "isolate_start",
                  '#!/bin/bash\nWD="$3/workers/$1"\nmkdir -p "$WD"\necho "$WD"')
    _write_script(scripts_dir / "isolate_end", "#!/bin/bash\nexit 0")
    _write_script(scripts_dir / "execute", execute_script)

    pack = load_pack("test")

    # Create state store and session
    store = StateStore(str(home / "test.db"))
    session = Session(id="s1", name="test-run", pack="test", status="running",
                      config={"max_workers": 2}, created_at="2026-01-01T00:00:00Z")
    store.create_session(session)
    store.create_worker_slots("s1", 2)

    session_dir = create_session_dirs("s1")

    # Create tasks in ready/
    for i in range(num_tasks):
        tid = f"{i:03d}"
        (session_dir / "ready" / f"{tid}.plan.md").write_text(f"# Task {tid}\nDo thing {i}\n")
        store.create_task(Task(
            id=tid, session_id="s1", title=f"Task {tid}", status="ready",
            depends_on=[], anti_affinity=[], exec_order=i,
            created_at="2026-01-01T00:00:00Z"))

    return store, pack, session_dir


# --- Core dispatch + completion ---

def test_orchestrator_runs_tasks_to_completion(tmp_path, monkeypatch):
    store, pack, session_dir = _setup_test_env(tmp_path, monkeypatch, num_tasks=3)
    from switchyard.orchestrator import Orchestrator

    orch = Orchestrator("s1", store, pack)
    # Run in thread with timeout
    t = threading.Thread(target=orch.run, kwargs={"poll_interval": 0.2})
    t.start()
    t.join(timeout=15)
    if t.is_alive():
        orch.abort()
        t.join(timeout=5)
        pytest.fail("Orchestrator did not complete in time")

    session = store.get_session("s1")
    assert session.status == "completed"
    done_tasks = store.list_tasks("s1", status="done")
    assert len(done_tasks) == 3


def test_orchestrator_respects_dependencies(tmp_path, monkeypatch):
    store, pack, session_dir = _setup_test_env(tmp_path, monkeypatch, num_tasks=2)
    # Task 001 depends on task 000
    store.update_task("s1", "001", depends_on=["000"])
    from switchyard.orchestrator import Orchestrator

    events = []
    def capture(event_type, data):
        if event_type == "task_status_change":
            events.append(data)

    orch = Orchestrator("s1", store, pack, broadcast_fn=capture)
    t = threading.Thread(target=orch.run, kwargs={"poll_interval": 0.2})
    t.start()
    t.join(timeout=15)
    if t.is_alive():
        orch.abort()
        t.join(timeout=5)

    # Verify 000 completed before 001 started
    done_events = [e for e in events if e.get("new_status") == "done"]
    active_events = [e for e in events if e.get("new_status") == "active"]

    t000_done = next((i for i, e in enumerate(events) if e.get("task_id") == "000" and e.get("new_status") == "done"), None)
    t001_active = next((i for i, e in enumerate(events) if e.get("task_id") == "001" and e.get("new_status") == "active"), None)

    assert t000_done is not None
    assert t001_active is not None
    assert t000_done < t001_active


# --- File-as-state ---

def test_task_files_move_through_directories(tmp_path, monkeypatch):
    store, pack, session_dir = _setup_test_env(tmp_path, monkeypatch, num_tasks=1)
    from switchyard.orchestrator import Orchestrator

    orch = Orchestrator("s1", store, pack)
    t = threading.Thread(target=orch.run, kwargs={"poll_interval": 0.2})
    t.start()
    t.join(timeout=10)
    if t.is_alive():
        orch.abort()
        t.join(timeout=5)

    # After completion, plan file should be in done/
    assert (session_dir / "done" / "000.plan.md").exists()
    assert not (session_dir / "ready" / "000.plan.md").exists()


# --- Crash recovery ---

def test_recover_orphaned_worker_completed(tmp_path, monkeypatch):
    """Task left in workers/ with done sidecar should be recovered to done/."""
    store, pack, session_dir = _setup_test_env(tmp_path, monkeypatch, num_tasks=1)
    from switchyard.orchestrator import Orchestrator

    # Simulate crash: move task to worker slot, write done sidecar
    worker_dir = session_dir / "workers" / "0"
    worker_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(session_dir / "ready" / "000.plan.md"), str(worker_dir / "000.plan.md"))
    (worker_dir / "000.status").write_text("STATUS: done\nTESTS_RAN: none\nTEST_RESULT: skip\n")
    store.update_task("s1", "000", status="active", worker_slot=0)

    orch = Orchestrator("s1", store, pack)
    orch.recover()

    # Task should now be in done/
    assert (session_dir / "done" / "000.plan.md").exists()
    task = store.get_task("s1", "000")
    assert task.status == "done"


def test_recover_orphaned_worker_incomplete(tmp_path, monkeypatch):
    """Task left in workers/ with NO sidecar should return to ready/."""
    store, pack, session_dir = _setup_test_env(tmp_path, monkeypatch, num_tasks=1)
    from switchyard.orchestrator import Orchestrator

    worker_dir = session_dir / "workers" / "0"
    worker_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(session_dir / "ready" / "000.plan.md"), str(worker_dir / "000.plan.md"))
    store.update_task("s1", "000", status="active", worker_slot=0)

    orch = Orchestrator("s1", store, pack)
    orch.recover()

    # Task should be back in ready/ (infrastructure failure, not task failure)
    assert (session_dir / "ready" / "000.plan.md").exists()
    task = store.get_task("s1", "000")
    assert task.status == "ready"


def test_recover_orphaned_claimed(tmp_path, monkeypatch):
    """Files in claimed/ should return to intake/ on recovery."""
    store, pack, session_dir = _setup_test_env(tmp_path, monkeypatch, num_tasks=0)
    from switchyard.orchestrator import Orchestrator

    (session_dir / "claimed").mkdir(exist_ok=True)
    (session_dir / "claimed" / "099.plan.md").write_text("# Task 099\n")

    orch = Orchestrator("s1", store, pack)
    orch.recover()

    assert (session_dir / "intake" / "099.plan.md").exists()
    assert not (session_dir / "claimed" / "099.plan.md").exists()


# --- Post-completion trimming ---

def test_trim_on_successful_completion(tmp_path, monkeypatch):
    store, pack, session_dir = _setup_test_env(tmp_path, monkeypatch, num_tasks=1)
    from switchyard.orchestrator import Orchestrator

    orch = Orchestrator("s1", store, pack)
    t = threading.Thread(target=orch.run, kwargs={"poll_interval": 0.2})
    t.start()
    t.join(timeout=10)
    if t.is_alive():
        orch.abort()
        t.join(timeout=5)

    # After successful completion, trimming should have occurred
    assert (session_dir / "summary.json").exists()
    assert not (session_dir / "intake").exists()
    assert not (session_dir / "workers").exists()
    assert (session_dir / "logs" / "session.log").exists()


def test_no_trim_on_blocked_session(tmp_path, monkeypatch):
    """Sessions with blocked tasks should NOT be trimmed."""
    execute_script = (
        '#!/bin/bash\n'
        'echo "failing"\n'
        'SIDECAR="${1%.plan.md}.status"\n'
        'echo "STATUS: blocked" > "$SIDECAR"\n'
        'echo "BLOCKED_REASON: intentional failure" >> "$SIDECAR"\n'
    )
    store, pack, session_dir = _setup_test_env(
        tmp_path, monkeypatch, execute_script=execute_script, num_tasks=1)
    from switchyard.orchestrator import Orchestrator

    orch = Orchestrator("s1", store, pack)
    t = threading.Thread(target=orch.run, kwargs={"poll_interval": 0.2})
    t.start()
    t.join(timeout=10)
    if t.is_alive():
        orch.abort()
        t.join(timeout=5)

    # Session should NOT be trimmed (has blocked tasks)
    assert not (session_dir / "summary.json").exists()
    assert (session_dir / "blocked").exists()


# --- Abort ---

def test_abort_kills_workers(tmp_path, monkeypatch):
    execute_script = "#!/bin/bash\nwhile true; do echo working; sleep 0.1; done"
    store, pack, session_dir = _setup_test_env(
        tmp_path, monkeypatch, execute_script=execute_script, num_tasks=1)
    from switchyard.orchestrator import Orchestrator

    orch = Orchestrator("s1", store, pack)
    t = threading.Thread(target=orch.run, kwargs={"poll_interval": 0.2})
    t.start()
    time.sleep(1)  # Let it dispatch
    orch.abort()
    t.join(timeout=5)

    session = store.get_session("s1")
    assert session.status == "aborted"
```
