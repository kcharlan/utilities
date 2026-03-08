# Phase 4: Worker Manager

## Spec

Build the subprocess lifecycle manager that dispatches tasks to worker slots, captures output, parses progress, and enforces timeouts. The worker manager owns the subprocesses — the orchestrator tells it what to run, it handles the how.

### Dependencies from prior phases

- `switchyard/models.py` — `Task`, `WorkerSlot` dataclasses.
- `switchyard/pack_loader.py` — `PackConfig`, `run_hook()`, `parse_progress_line()`, `parse_status_sidecar()`.
- `switchyard/config.py` — path constants.

### Files to create

**`switchyard/worker_manager.py`**:

**`WorkerProcess` dataclass:**
```
WorkerProcess(
    slot_number: int,
    task_id: str,
    process: subprocess.Popen,
    workspace: str,
    log_path: str,
    started_at: float,        # time.monotonic()
    last_output_at: float,    # time.monotonic(), updated on each stdout/stderr line
    current_phase: Optional[str],
    phase_current: int,
    phase_total: int,
    detail: Optional[str],    # Latest detail progress message
)
```

**`WorkerManager(num_slots: int, session_dir: str, pack: PackConfig)`:**

- Constructor creates `num_slots` internal slots (0 to num_slots-1), all idle.

- **`dispatch(slot_number: int, task: Task) -> WorkerProcess`:**
  - Calls `run_hook(pack, "isolate_start", [str(slot_number), task.id, session_dir])`. Reads workspace path from stdout (stripped).
  - Copies the task's plan file from `ready/<task_id>.plan.md` to the workspace.
  - Opens log file at `session_dir/logs/workers/<slot_number>.log` for writing.
  - Launches the executor subprocess via `subprocess.Popen`:
    - For shell executors: `run_hook` equivalent but non-blocking — `[script_path, plan_file_path, workspace]`, cwd=workspace, stdout=PIPE, stderr=STDOUT.
    - Stores the `WorkerProcess` in the slot.
  - Returns the `WorkerProcess`.

- **`poll(slot_number: int) -> Optional[dict]`:**
  - Reads any available stdout lines from the process (non-blocking).
  - For each line:
    - Writes to the log file.
    - Updates `last_output_at`.
    - Calls `parse_progress_line()`. If it returns a phase update, updates `current_phase`, `phase_current`, `phase_total`. If detail, updates `detail`.
  - Checks if process has terminated (`process.poll()`).
  - If terminated, returns `{"finished": True, "returncode": int}`.
  - If still running, returns `{"finished": False, "lines": [new_lines]}`.
  - Returns `None` if slot is idle.

- **`collect(slot_number: int) -> dict`:**
  - Called after `poll` indicates finished.
  - Reads the status sidecar file from the workspace (plan file path with `.status` extension).
  - Returns `{"status": "done"|"blocked", "sidecar": parsed_dict, "returncode": int}`.
  - If no sidecar exists or sidecar is malformed, returns `{"status": "blocked", "sidecar": {}, "reason": "No valid status sidecar"}`.
  - Closes the log file handle.
  - Clears the slot (marks idle).

- **`kill(slot_number: int, reason: str)`:**
  - Sends SIGTERM to the process.
  - Waits up to 5 seconds.
  - If still alive, sends SIGKILL.
  - Writes reason to log file.
  - Clears the slot.

- **`check_timeouts(task_idle: int, task_max: int) -> list[dict]`:**
  - Checks all active slots against timeout thresholds.
  - Returns list of events: `{"slot": int, "task_id": str, "type": "warning"|"kill", "reason": str}`.
  - Warning at 80% of `task_idle` threshold (only if `task_idle > 0`).
  - Kill at 100% of `task_idle` (no output for `task_idle` seconds).
  - Kill at `task_max` wall-clock seconds (only if `task_max > 0`).
  - Does NOT call `kill()` itself — returns the events. The orchestrator decides what to do.

- **`idle_slots() -> list[int]`:** Returns slot numbers that have no active process.

- **`active_slots() -> list[int]`:** Returns slot numbers with active processes.

- **`get_worker(slot_number: int) -> Optional[WorkerProcess]`:** Returns the WorkerProcess or None if idle.

- **`cleanup_all()`:** Kills all active processes (SIGTERM/SIGKILL), closes all log files.

### Non-blocking stdout reads

Use `os.set_blocking(process.stdout.fileno(), False)` after Popen to enable non-blocking reads in `poll()`. Read available bytes with `os.read()`, split by newline, buffer incomplete lines.

## Acceptance tests

```python
"""tests/test_phase04_worker_manager.py"""
import os
import stat
import time
from pathlib import Path

import pytest


def _make_test_pack(tmp_path, execute_script, isolate_start_script=None):
    """Create a minimal pack with custom execute script."""
    pack_dir = tmp_path / "packs" / "test"
    pack_dir.mkdir(parents=True)
    scripts_dir = pack_dir / "scripts"
    scripts_dir.mkdir()

    # pack.yaml
    (pack_dir / "pack.yaml").write_text(
        "name: test\ndescription: test\nversion: '1'\n"
        "phases:\n  execution:\n    enabled: true\n    executor: shell\n"
        "    command: scripts/execute\n    max_workers: 4\n"
        "isolation:\n  type: none\n  setup: scripts/isolate_start\n"
        "  teardown: scripts/isolate_end\n"
    )

    # isolate_start: just echo the workspace path
    iso_start = isolate_start_script or "#!/bin/bash\necho \"$3/workers/$1\"\nmkdir -p \"$3/workers/$1\""
    _write_script(scripts_dir / "isolate_start", iso_start)

    # isolate_end: no-op
    _write_script(scripts_dir / "isolate_end", "#!/bin/bash\nexit 0")

    # execute
    _write_script(scripts_dir / "execute", execute_script)

    return pack_dir


def _write_script(path, content):
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _make_session_dir(tmp_path):
    session_dir = tmp_path / "session"
    for d in ["ready", "workers", "done", "blocked", "logs", "logs/workers"]:
        (session_dir / d).mkdir(parents=True, exist_ok=True)
    return session_dir


def _make_task_file(session_dir, task_id, content="# Test task\n"):
    plan = session_dir / "ready" / f"{task_id}.plan.md"
    plan.write_text(content)
    return plan


@pytest.fixture
def pack(tmp_path, monkeypatch):
    """Pack with a fast-completing executor that writes a status sidecar."""
    script = (
        "#!/bin/bash\n"
        "echo '##PROGRESS## $2 | Phase: running | 1/1'\n"  # $2 won't expand but doesn't matter
        "echo 'doing work'\n"
        "echo 'STATUS: done' > \"${1%.plan.md}.status\"\n"
        "echo 'TESTS_RAN: none' >> \"${1%.plan.md}.status\"\n"
        "echo 'TEST_RESULT: skip' >> \"${1%.plan.md}.status\"\n"
    )
    pack_dir = _make_test_pack(tmp_path, script)
    from switchyard import config
    monkeypatch.setattr(config, "PACKS_DIR", str(tmp_path / "packs"))
    from switchyard.pack_loader import load_pack
    return load_pack("test")


# --- dispatch and poll ---

def test_dispatch_starts_process(pack, tmp_path):
    from switchyard.models import Task
    from switchyard.worker_manager import WorkerManager

    session_dir = _make_session_dir(tmp_path)
    _make_task_file(session_dir, "001")
    task = Task(id="001", session_id="s1", title="test", status="ready",
                depends_on=[], anti_affinity=[], exec_order=0,
                created_at="2026-01-01T00:00:00Z")

    wm = WorkerManager(2, str(session_dir), pack)
    try:
        wp = wm.dispatch(0, task)
        assert wp.slot_number == 0
        assert wp.task_id == "001"
        assert wm.idle_slots() == [1]
        assert wm.active_slots() == [0]
    finally:
        wm.cleanup_all()


def test_poll_and_collect_completed_task(pack, tmp_path):
    from switchyard.models import Task
    from switchyard.worker_manager import WorkerManager

    session_dir = _make_session_dir(tmp_path)
    _make_task_file(session_dir, "001")
    task = Task(id="001", session_id="s1", title="test", status="ready",
                depends_on=[], anti_affinity=[], exec_order=0,
                created_at="2026-01-01T00:00:00Z")

    wm = WorkerManager(2, str(session_dir), pack)
    try:
        wm.dispatch(0, task)
        # Wait for completion (fast script)
        for _ in range(50):
            result = wm.poll(0)
            if result and result.get("finished"):
                break
            time.sleep(0.1)
        else:
            pytest.fail("Task did not finish in time")

        collected = wm.collect(0)
        assert collected["status"] == "done"
        assert 0 in wm.idle_slots()
    finally:
        wm.cleanup_all()


def test_collect_without_sidecar_returns_blocked(tmp_path, monkeypatch):
    """If executor finishes but writes no sidecar, task is blocked."""
    script = "#!/bin/bash\necho 'no sidecar written'"
    pack_dir = _make_test_pack(tmp_path, script)
    from switchyard import config
    monkeypatch.setattr(config, "PACKS_DIR", str(tmp_path / "packs"))
    from switchyard.pack_loader import load_pack
    from switchyard.models import Task
    from switchyard.worker_manager import WorkerManager

    pk = load_pack("test")
    session_dir = _make_session_dir(tmp_path)
    _make_task_file(session_dir, "001")
    task = Task(id="001", session_id="s1", title="test", status="ready",
                depends_on=[], anti_affinity=[], exec_order=0,
                created_at="2026-01-01T00:00:00Z")

    wm = WorkerManager(1, str(session_dir), pk)
    try:
        wm.dispatch(0, task)
        for _ in range(50):
            result = wm.poll(0)
            if result and result.get("finished"):
                break
            time.sleep(0.1)
        collected = wm.collect(0)
        assert collected["status"] == "blocked"
    finally:
        wm.cleanup_all()


def test_poll_idle_slot_returns_none(pack, tmp_path):
    from switchyard.worker_manager import WorkerManager
    session_dir = _make_session_dir(tmp_path)
    wm = WorkerManager(2, str(session_dir), pack)
    assert wm.poll(0) is None


# --- kill ---

def test_kill_terminates_long_running(tmp_path, monkeypatch):
    script = "#!/bin/bash\nwhile true; do echo alive; sleep 0.1; done"
    pack_dir = _make_test_pack(tmp_path, script)
    from switchyard import config
    monkeypatch.setattr(config, "PACKS_DIR", str(tmp_path / "packs"))
    from switchyard.pack_loader import load_pack
    from switchyard.models import Task
    from switchyard.worker_manager import WorkerManager

    pk = load_pack("test")
    session_dir = _make_session_dir(tmp_path)
    _make_task_file(session_dir, "001")
    task = Task(id="001", session_id="s1", title="test", status="ready",
                depends_on=[], anti_affinity=[], exec_order=0,
                created_at="2026-01-01T00:00:00Z")

    wm = WorkerManager(1, str(session_dir), pk)
    wm.dispatch(0, task)
    time.sleep(0.3)
    wm.kill(0, "test kill")
    assert 0 in wm.idle_slots()


# --- timeout detection ---

def test_check_timeouts_idle_warning(tmp_path, monkeypatch):
    """After 80% of idle timeout with no output, warning is returned."""
    script = "#!/bin/bash\nsleep 30"
    pack_dir = _make_test_pack(tmp_path, script)
    from switchyard import config
    monkeypatch.setattr(config, "PACKS_DIR", str(tmp_path / "packs"))
    from switchyard.pack_loader import load_pack
    from switchyard.models import Task
    from switchyard.worker_manager import WorkerManager

    pk = load_pack("test")
    session_dir = _make_session_dir(tmp_path)
    _make_task_file(session_dir, "001")
    task = Task(id="001", session_id="s1", title="test", status="ready",
                depends_on=[], anti_affinity=[], exec_order=0,
                created_at="2026-01-01T00:00:00Z")

    wm = WorkerManager(1, str(session_dir), pk)
    try:
        wp = wm.dispatch(0, task)
        # Backdate last_output_at to simulate 80%+ of 10s idle timeout
        wp.last_output_at = time.monotonic() - 9
        events = wm.check_timeouts(task_idle=10, task_max=0)
        warnings = [e for e in events if e["type"] == "warning"]
        assert len(warnings) >= 1
    finally:
        wm.cleanup_all()


def test_check_timeouts_idle_kill(tmp_path, monkeypatch):
    """At 100% of idle timeout, kill event is returned."""
    script = "#!/bin/bash\nsleep 30"
    pack_dir = _make_test_pack(tmp_path, script)
    from switchyard import config
    monkeypatch.setattr(config, "PACKS_DIR", str(tmp_path / "packs"))
    from switchyard.pack_loader import load_pack
    from switchyard.models import Task
    from switchyard.worker_manager import WorkerManager

    pk = load_pack("test")
    session_dir = _make_session_dir(tmp_path)
    _make_task_file(session_dir, "001")
    task = Task(id="001", session_id="s1", title="test", status="ready",
                depends_on=[], anti_affinity=[], exec_order=0,
                created_at="2026-01-01T00:00:00Z")

    wm = WorkerManager(1, str(session_dir), pk)
    try:
        wp = wm.dispatch(0, task)
        # Backdate to exceed idle timeout
        wp.last_output_at = time.monotonic() - 11
        events = wm.check_timeouts(task_idle=10, task_max=0)
        kills = [e for e in events if e["type"] == "kill"]
        assert len(kills) == 1
    finally:
        wm.cleanup_all()
```
