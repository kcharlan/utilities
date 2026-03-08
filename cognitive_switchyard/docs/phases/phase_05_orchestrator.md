# Phase 05: Orchestrator Core

**Design doc:** `docs/cognitive_switchyard_design.md`

## Spec

Build the main orchestration loop that drives the pipeline from planning through execution. The orchestrator runs in a background thread, polls for state changes, dispatches eligible tasks, collects completed work, triggers verification, and manages the auto-fix retry loop.

### Files to create

- `switchyard/orchestrator.py`

### Dependencies from prior phases

- `switchyard/models.py` — Session, Task, WorkerSlot, Event
- `switchyard/config.py` — path constants
- `switchyard/state.py` — all async DB functions, `create_session_dirs`, `get_task_status_from_filesystem`, `trim_completed_session`
- `switchyard/pack_loader.py` — `load_pack`, `run_hook`, `run_hook_async`, `run_preflight`, `check_executable_bits`
- `switchyard/scheduler.py` — `is_eligible`, `next_eligible`, `all_eligible`, `has_unresolvable_deps`, `load_constraint_graph`
- `switchyard/worker_manager.py` — `WorkerPool`, `parse_status_sidecar`

### Orchestrator class

`class Orchestrator`:

- `__init__(self, session_id: str, pack_name: str, config: dict)` — Load pack config, initialize worker pool, set up event loop bridge for async DB calls from the background thread.
- `start(self)` — Launch the orchestration loop in a background thread. The method itself returns immediately.
- `stop(self)` — Signal the loop to stop. Block until the thread joins.
- `pause(self)` — Set a flag that prevents new dispatches. Active workers continue running.
- `resume(self)` — Clear the pause flag.
- `abort(self)` — Kill all active workers, mark session as `aborted`, stop the loop.

### Main loop (pseudocode from design doc Section 7.3)

Each iteration:

1. **Collect completed workers.** For each active slot where `is_finished()` is True:
   - Read status sidecar from the worker's task directory.
   - If `STATUS: done`: call pack's `isolate_end` hook with status `"done"`, move task file to `done/`, update DB task status to `"done"`.
   - If `STATUS: blocked` or no sidecar or non-zero exit: call `isolate_end` with `"blocked"`, move task to `blocked/`, update DB.
   - Call `pool.collect(slot)` to free the slot.
   - Broadcast `task_status_change` event.
   - Check if verification should trigger (see below).

2. **Check for permanently blocked tasks.** For each `ready` task, call `has_unresolvable_deps`. If True, move to `blocked/` with reason "Dependency X is blocked."

3. **Dispatch eligible tasks.** If not paused, for each idle slot:
   - Call `next_eligible(ready_tasks, all_tasks)`.
   - If a task is found: call `isolate_start` hook, call `run_hook_async` for execute hook, call `pool.dispatch()`, move task file to `workers/<N>/`, update DB to `active`.

4. **Check for session completion.** If no tasks are `ready`, `active`, `planning`, `staged`, or `review`, the session is complete:
   - If any tasks are `blocked`: set session status to `completed` (not all succeeded, but the session ran to exhaustion).
   - If all tasks are `done`: set session status to `completed`, call `trim_completed_session`.

5. **Sleep** for `poll_interval` seconds (default 2).

### Verification triggers

Verification runs when `phases.verification.enabled` is True in the pack config. It triggers:
- After every N completed tasks (N = `phases.verification.interval`, default 4).
- When the session completes (all tasks done or blocked).

When triggered:
- Pause new dispatches.
- Wait for all active workers to finish (poll until `active_slots()` is empty).
- Set session status to `"verifying"`.
- Run the pack's `verify` command via `run_hook`.
- If verification passes (exit 0): resume dispatching, set session back to `"running"`.
- If verification fails: enter auto-fix loop (if enabled) or set session status to `"completed"` with verification failure noted.

### Auto-fix loop

When a task fails (STATUS: blocked) or verification fails, and `auto_fix.enabled` is True:
- Re-dispatch the task with the fixer prompt instead of the worker prompt.
- After fix attempt: independently verify (re-run verification, do NOT trust fixer's self-report).
- If fix succeeds: task moves to `done/`.
- If fix fails: increment attempt counter. If `< max_attempts`, retry. If `>= max_attempts`, task stays `blocked/`.

### Event broadcasting

The orchestrator maintains a callback: `on_event: Optional[Callable[[dict], None]]`. The server (Phase 08) registers a callback that pushes events to WebSocket clients. For this phase, events are logged to `session.log` in the session's `logs/` directory. Event types: `task_status_change`, `session_status_change`, `log_line`, `progress_detail`, `alert`.

### Session log

All events are written to `logs/session.log` as JSON lines (one JSON object per line). This provides a durable audit trail independent of the WebSocket.

## Acceptance tests

```python
# tests/test_phase05_orchestrator.py
import asyncio
import json
import os
import shutil
import stat
import time
import yaml
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from switchyard.models import Session, Task
from switchyard.config import ensure_dirs
from switchyard.state import (
    init_db, create_session, create_task, get_task, update_task,
    list_tasks, get_session, create_session_dirs, create_worker_slots,
)
from switchyard.orchestrator import Orchestrator


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    home = tmp_path / ".switchyard"
    monkeypatch.setattr("switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("switchyard.config.DB_PATH", home / "switchyard.db")
    monkeypatch.setattr("switchyard.config.CONFIG_PATH", home / "config.yaml")
    monkeypatch.setattr("switchyard.config.PACKS_DIR", home / "packs")
    monkeypatch.setattr("switchyard.config.SESSIONS_DIR", home / "sessions")
    monkeypatch.setattr("switchyard.state.DB_PATH", home / "switchyard.db")
    monkeypatch.setattr("switchyard.state.SESSIONS_DIR", home / "sessions")
    monkeypatch.setattr("switchyard.pack_loader.PACKS_DIR", home / "packs")
    ensure_dirs()


def _create_echo_pack(packs_dir, with_isolation=False):
    """Create a minimal echo pack for testing."""
    pack_dir = packs_dir / "test-echo"
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "scripts").mkdir(exist_ok=True)

    # Execute script: echo task content and write status sidecar
    execute = pack_dir / "scripts" / "execute.sh"
    execute.write_text('#!/bin/bash\ncat "$1"\nSIDECAR="${1%.plan.md}.status"\necho "STATUS: done" > "$SIDECAR"\necho "COMMITS: none" >> "$SIDECAR"\necho "TESTS_RAN: none" >> "$SIDECAR"\necho "TEST_RESULT: skip" >> "$SIDECAR"\n')
    execute.chmod(execute.stat().st_mode | stat.S_IEXEC)

    config = {
        "name": "test-echo",
        "description": "Test pack",
        "version": "1.0.0",
        "phases": {
            "execution": {"enabled": True, "executor": "shell", "command": "scripts/execute.sh", "max_workers": 2},
        },
        "isolation": {"type": "none"},
    }
    (pack_dir / "pack.yaml").write_text(yaml.dump(config))
    return pack_dir


async def _setup_session_with_tasks(tmp_path, task_specs):
    """Create a session with tasks in ready/ directory. task_specs: list of (id, title, depends_on, anti_affinity, exec_order)."""
    await init_db()
    session = Session(id="s1", name="test", pack="test-echo", status="running", config={"workers": 2}, created_at="2026-01-01T00:00:00Z")
    await create_session(session)
    session_path = await create_session_dirs("s1")
    await create_worker_slots("s1", 2)

    for tid, title, deps, aa, eo in task_specs:
        task = Task(id=tid, session_id="s1", title=title, status="ready",
                    depends_on=deps, anti_affinity=aa, exec_order=eo, created_at="2026-01-01T00:00:00Z")
        await create_task(task)
        (session_path / "ready" / f"{tid}.plan.md").write_text(f"# {title}\nDo the thing.")

    return session_path


@pytest.mark.asyncio
async def test_orchestrator_dispatches_and_completes(tmp_path):
    packs_dir = tmp_path / ".switchyard" / "packs"
    _create_echo_pack(packs_dir)
    await _setup_session_with_tasks(tmp_path, [
        ("t1", "Task 1", [], [], 1),
        ("t2", "Task 2", [], [], 2),
    ])

    orch = Orchestrator("s1", "test-echo", {"workers": 2, "poll_interval": 0.2})
    orch.start()
    # Wait for completion (max 10s)
    for _ in range(50):
        time.sleep(0.2)
        s = await get_session("s1")
        if s.status == "completed":
            break
    orch.stop()

    t1 = await get_task("s1", "t1")
    t2 = await get_task("s1", "t2")
    assert t1.status == "done"
    assert t2.status == "done"


@pytest.mark.asyncio
async def test_orchestrator_respects_depends_on(tmp_path):
    """t2 depends on t1 — t2 must not start until t1 is done."""
    packs_dir = tmp_path / ".switchyard" / "packs"
    _create_echo_pack(packs_dir)
    await _setup_session_with_tasks(tmp_path, [
        ("t1", "Task 1", [], [], 1),
        ("t2", "Task 2", ["t1"], [], 2),
    ])

    events = []
    orch = Orchestrator("s1", "test-echo", {"workers": 2, "poll_interval": 0.2})
    orch.on_event = lambda e: events.append(e)
    orch.start()
    for _ in range(50):
        time.sleep(0.2)
        s = await get_session("s1")
        if s.status == "completed":
            break
    orch.stop()

    # Both should complete
    t1 = await get_task("s1", "t1")
    t2 = await get_task("s1", "t2")
    assert t1.status == "done"
    assert t2.status == "done"
    # t2 must have started after t1 completed
    assert t2.started_at >= t1.completed_at


@pytest.mark.asyncio
async def test_orchestrator_pause_prevents_dispatch(tmp_path):
    packs_dir = tmp_path / ".switchyard" / "packs"
    _create_echo_pack(packs_dir)
    await _setup_session_with_tasks(tmp_path, [
        ("t1", "Task 1", [], [], 1),
    ])

    orch = Orchestrator("s1", "test-echo", {"workers": 2, "poll_interval": 0.2})
    orch.pause()
    orch.start()
    time.sleep(1.0)  # let a few poll cycles run
    t1 = await get_task("s1", "t1")
    assert t1.status == "ready"  # should NOT have been dispatched
    orch.stop()


@pytest.mark.asyncio
async def test_orchestrator_abort_kills_workers(tmp_path):
    packs_dir = tmp_path / ".switchyard" / "packs"
    pack_dir = _create_echo_pack(packs_dir)
    # Replace execute with a slow script
    execute = pack_dir / "scripts" / "execute.sh"
    execute.write_text('#!/bin/bash\nsleep 60\n')
    execute.chmod(execute.stat().st_mode | stat.S_IEXEC)

    await _setup_session_with_tasks(tmp_path, [("t1", "Task 1", [], [], 1)])

    orch = Orchestrator("s1", "test-echo", {"workers": 1, "poll_interval": 0.2})
    orch.start()
    time.sleep(0.5)  # let dispatch happen
    orch.abort()
    s = await get_session("s1")
    assert s.status == "aborted"


@pytest.mark.asyncio
async def test_blocked_task_when_executor_fails(tmp_path):
    packs_dir = tmp_path / ".switchyard" / "packs"
    pack_dir = _create_echo_pack(packs_dir)
    # Replace execute with a failing script
    execute = pack_dir / "scripts" / "execute.sh"
    execute.write_text('#!/bin/bash\nexit 1\n')
    execute.chmod(execute.stat().st_mode | stat.S_IEXEC)

    await _setup_session_with_tasks(tmp_path, [("t1", "Task 1", [], [], 1)])

    orch = Orchestrator("s1", "test-echo", {"workers": 1, "poll_interval": 0.2})
    orch.start()
    for _ in range(50):
        time.sleep(0.2)
        s = await get_session("s1")
        if s.status == "completed":
            break
    orch.stop()

    t1 = await get_task("s1", "t1")
    assert t1.status == "blocked"


@pytest.mark.asyncio
async def test_session_log_written(tmp_path):
    packs_dir = tmp_path / ".switchyard" / "packs"
    _create_echo_pack(packs_dir)
    await _setup_session_with_tasks(tmp_path, [("t1", "Task 1", [], [], 1)])

    orch = Orchestrator("s1", "test-echo", {"workers": 1, "poll_interval": 0.2})
    orch.start()
    for _ in range(50):
        time.sleep(0.2)
        s = await get_session("s1")
        if s.status == "completed":
            break
    orch.stop()

    log_path = tmp_path / ".switchyard" / "sessions" / "s1" / "logs" / "session.log"
    assert log_path.exists()
    lines = log_path.read_text().strip().split("\n")
    events = [json.loads(line) for line in lines]
    event_types = {e["event_type"] for e in events}
    assert "task_status_change" in event_types
```
