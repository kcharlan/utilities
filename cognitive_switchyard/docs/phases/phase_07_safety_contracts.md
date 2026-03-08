# Phase 07: Safety Contracts

**Design doc:** `docs/cognitive_switchyard_design.md` (Sections 7.3–7.4, 4.3)

## Spec

Add timeout enforcement, kill sequences, and status-conditional cleanup behavior. These are safety-critical behaviors where subtle bugs cause data loss or runaway processes. This phase tests the behavioral contracts that span the orchestrator, worker manager, and pack hooks.

### Files to modify

- `switchyard/orchestrator.py` — Add timeout enforcement to the main loop.
- `switchyard/worker_manager.py` — Ensure kill sequence is correct (SIGTERM → 5s grace → SIGKILL).

### Timeout enforcement (three independent timeouts)

Added to the orchestrator's main loop iteration, after collecting completed workers and before dispatching new tasks.

**Task idle timeout** (`task_idle`, default 300s from pack config):
- For each active slot, check `pool.seconds_since_last_output(slot)`.
- At 80% of threshold: broadcast an `alert` event ("No output for Xs (timeout at Ys)"). The worker card enters "problem" state.
- At 100% of threshold: kill the process, move task to `blocked/` with reason "Killed: no output for Xs", call `isolate_end` with status `"blocked"`.
- Any stdout/stderr output resets the idle timer (already implemented in worker manager's `read_new_output`).

**Task hard timeout** (`task_max`, default 0 = disabled):
- For each active slot, check `pool.elapsed(slot)`.
- If `task_max > 0` and elapsed >= task_max: kill, move to `blocked/` with reason "Killed: exceeded max task time Xs", call `isolate_end` with `"blocked"`.

**Session timeout** (`session_max`, default 14400s / 4 hours):
- Check total session elapsed time.
- If `session_max > 0` and session elapsed >= session_max: kill ALL active workers, set session status to `"aborted"` (not `"completed"`), set `abort_reason`. This preserves full artifacts for debugging (no trimming).

**Interaction**: Task idle and task max are independent — whichever fires first wins. Session timeout overrides both and kills everything. A task killed by idle/hard timeout moves to `blocked/` and the session continues (slot is freed, other tasks keep running). A session timeout stops everything.

### Kill sequence

`WorkerPool.kill(slot, reason)` must implement:
1. Send SIGTERM to the process.
2. Wait up to 5 seconds for the process to exit.
3. If still alive after 5 seconds, send SIGKILL.
4. Record the kill reason in the slot state.

### Cleanup-by-status in isolate_end

The pack's `isolate_end` hook receives `$4 = status` which is either `"done"` or `"blocked"`. The orchestrator MUST pass the correct status:
- On task success (sidecar STATUS: done, exit 0): pass `"done"`. The hook merges results.
- On task failure, timeout kill, or crash recovery of incomplete work: pass `"blocked"`. The hook cleans up without merging.
- The orchestrator must NEVER pass `"done"` when the task actually failed. This would cause the hook to merge bad results into the main workspace.

### Auto-fix bounded retry

The auto-fix loop must be bounded by `auto_fix.max_attempts`. After exhausting all attempts:
- Task moves to `blocked/` permanently.
- The reason includes the attempt count: "Auto-fix failed after N attempts."
- No further retries occur for this task.

### Constraint enforcement edge cases

- A task with a dependency on a blocked task must be proactively moved to `blocked/` (tested in Phase 05, but the cascading effect needs testing here: if t1 blocks, and t2 depends on t1, and t3 depends on t2, then BOTH t2 AND t3 should eventually be blocked).

## Acceptance tests

```python
# tests/test_phase07_safety_contracts.py
import asyncio
import os
import signal
import stat
import subprocess
import time
import yaml
import pytest
from pathlib import Path

from switchyard.models import Session, Task
from switchyard.config import ensure_dirs
from switchyard.state import (
    init_db, create_session, create_task, get_task, list_tasks,
    get_session, create_session_dirs, create_worker_slots,
)
from switchyard.orchestrator import Orchestrator
from switchyard.worker_manager import WorkerPool


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


def _create_pack(packs_dir, execute_script, extra_config=None):
    pack_dir = packs_dir / "test-echo"
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "scripts").mkdir(exist_ok=True)
    execute = pack_dir / "scripts" / "execute.sh"
    execute.write_text(execute_script)
    execute.chmod(execute.stat().st_mode | stat.S_IEXEC)
    config = {
        "name": "test-echo", "description": "Test", "version": "1.0.0",
        "phases": {"execution": {"enabled": True, "executor": "shell", "command": "scripts/execute.sh", "max_workers": 2}},
        "isolation": {"type": "none"},
    }
    if extra_config:
        config.update(extra_config)
    (pack_dir / "pack.yaml").write_text(yaml.dump(config))
    return pack_dir


async def _setup(tmp_path, task_specs, session_config=None):
    await init_db()
    cfg = {"workers": 1, "poll_interval": 0.2, **(session_config or {})}
    session = Session(id="s1", name="test", pack="test-echo", status="running", config=cfg, created_at="2026-01-01T00:00:00Z")
    await create_session(session)
    session_path = await create_session_dirs("s1")
    await create_worker_slots("s1", cfg.get("workers", 1))
    for tid, title, deps, aa, eo in task_specs:
        task = Task(id=tid, session_id="s1", title=title, status="ready",
                    depends_on=deps, anti_affinity=aa, exec_order=eo, created_at="2026-01-01T00:00:00Z")
        await create_task(task)
        (session_path / "ready" / f"{tid}.plan.md").write_text(f"# {title}")
    return session_path


# --- Kill sequence ---

def test_kill_sigterm_then_sigkill(tmp_path):
    """Kill sequence: SIGTERM first, SIGKILL if still alive after 5s."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "workers").mkdir()
    pool = WorkerPool(num_slots=1, log_dir=log_dir)

    # Process that traps SIGTERM and ignores it
    proc = subprocess.Popen(
        ["bash", "-c", "trap '' TERM; sleep 60"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    pool.dispatch(0, "t1", proc)
    pool.kill(0, "test kill")  # should escalate to SIGKILL
    assert proc.poll() is not None  # process must be dead


# --- Task idle timeout ---

@pytest.mark.asyncio
async def test_idle_timeout_kills_silent_task(tmp_path):
    """A task that produces no output for task_idle seconds should be killed and blocked."""
    packs_dir = tmp_path / ".switchyard" / "packs"
    _create_pack(packs_dir, '#!/bin/bash\nsleep 60\n',
                 extra_config={"timeouts": {"task_idle": 1}})  # 1 second for testing
    await _setup(tmp_path, [("t1", "Silent task", [], [], 1)], {"task_idle": 1})

    orch = Orchestrator("s1", "test-echo", {"workers": 1, "poll_interval": 0.2, "task_idle": 1})
    orch.start()
    for _ in range(30):
        time.sleep(0.3)
        t1 = await get_task("s1", "t1")
        if t1.status == "blocked":
            break
    orch.stop()

    t1 = await get_task("s1", "t1")
    assert t1.status == "blocked"


# --- Task hard timeout ---

@pytest.mark.asyncio
async def test_hard_timeout_kills_long_task(tmp_path):
    """A task exceeding task_max wall-clock time should be killed."""
    packs_dir = tmp_path / ".switchyard" / "packs"
    # Task that produces output (to avoid idle timeout) but runs forever
    _create_pack(packs_dir, '#!/bin/bash\nwhile true; do echo alive; sleep 0.2; done\n',
                 extra_config={"timeouts": {"task_max": 1}})
    await _setup(tmp_path, [("t1", "Long task", [], [], 1)], {"task_max": 1})

    orch = Orchestrator("s1", "test-echo", {"workers": 1, "poll_interval": 0.2, "task_max": 1})
    orch.start()
    for _ in range(30):
        time.sleep(0.3)
        t1 = await get_task("s1", "t1")
        if t1.status == "blocked":
            break
    orch.stop()

    t1 = await get_task("s1", "t1")
    assert t1.status == "blocked"


# --- Session timeout ---

@pytest.mark.asyncio
async def test_session_timeout_aborts_everything(tmp_path):
    """Session timeout kills all workers and sets session to aborted, NOT completed."""
    packs_dir = tmp_path / ".switchyard" / "packs"
    _create_pack(packs_dir, '#!/bin/bash\nwhile true; do echo alive; sleep 0.2; done\n')
    await _setup(tmp_path, [("t1", "Task 1", [], [], 1)], {"session_max": 1})

    orch = Orchestrator("s1", "test-echo", {"workers": 1, "poll_interval": 0.2, "session_max": 1})
    orch.start()
    for _ in range(30):
        time.sleep(0.3)
        s = await get_session("s1")
        if s.status == "aborted":
            break
    orch.stop()

    s = await get_session("s1")
    assert s.status == "aborted"  # NOT "completed"
    assert s.abort_reason is not None


# --- Cleanup-by-status ---

@pytest.mark.asyncio
async def test_isolate_end_called_with_blocked_on_failure(tmp_path):
    """When a task fails, isolate_end must be called with status 'blocked', not 'done'."""
    packs_dir = tmp_path / ".switchyard" / "packs"
    pack_dir = _create_pack(packs_dir, '#!/bin/bash\nexit 1\n')

    # Add isolate_end that records what status it was called with
    isolate_end = pack_dir / "scripts" / "isolate_end.sh"
    marker = tmp_path / "isolate_end_status.txt"
    isolate_end.write_text(f'#!/bin/bash\necho "$4" > {marker}\n')
    isolate_end.chmod(isolate_end.stat().st_mode | stat.S_IEXEC)

    pack_yaml = yaml.safe_load((pack_dir / "pack.yaml").read_text())
    pack_yaml["isolation"] = {"type": "none", "teardown": "scripts/isolate_end.sh"}
    (pack_dir / "pack.yaml").write_text(yaml.dump(pack_yaml))

    await _setup(tmp_path, [("t1", "Failing task", [], [], 1)])

    orch = Orchestrator("s1", "test-echo", {"workers": 1, "poll_interval": 0.2})
    orch.start()
    for _ in range(30):
        time.sleep(0.3)
        s = await get_session("s1")
        if s.status == "completed":
            break
    orch.stop()

    assert marker.exists()
    assert marker.read_text().strip() == "blocked"


# --- Cascading dependency blocks ---

@pytest.mark.asyncio
async def test_cascading_blocked_deps(tmp_path):
    """If t1 is blocked, t2 (depends on t1) and t3 (depends on t2) should both become blocked."""
    packs_dir = tmp_path / ".switchyard" / "packs"
    _create_pack(packs_dir, '#!/bin/bash\nexit 1\n')
    await _setup(tmp_path, [
        ("t1", "Will fail", [], [], 1),
        ("t2", "Depends on t1", ["t1"], [], 2),
        ("t3", "Depends on t2", ["t2"], [], 3),
    ])

    orch = Orchestrator("s1", "test-echo", {"workers": 1, "poll_interval": 0.2})
    orch.start()
    for _ in range(50):
        time.sleep(0.2)
        s = await get_session("s1")
        if s.status == "completed":
            break
    orch.stop()

    t1 = await get_task("s1", "t1")
    t2 = await get_task("s1", "t2")
    t3 = await get_task("s1", "t3")
    assert t1.status == "blocked"
    assert t2.status == "blocked"
    assert t3.status == "blocked"
```
