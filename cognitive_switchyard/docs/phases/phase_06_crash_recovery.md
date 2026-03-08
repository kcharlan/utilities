# Phase 06: Crash Recovery and Idempotent Restart

**Design doc:** `docs/cognitive_switchyard_design.md` (Sections 10.1–10.7)

## Spec

Add crash recovery to the orchestrator. On startup, before entering the normal dispatch loop, the orchestrator runs a recovery pass that inspects file-as-state directories and the SQLite database to detect incomplete operations and rolls them back to the last consistent state. The rule: **incomplete work is reverted, completed work is preserved.**

### Files to modify

- `switchyard/orchestrator.py` — Add `recover()` method called at start of `start()` before the main loop.
- `switchyard/state.py` — Add `reconcile_db_with_filesystem(session_id: str)` function.

### Recovery pass (`Orchestrator.recover()`)

Called on startup when session status is `planning`, `resolving`, `running`, `verifying`, or `paused`. The recovery pass handles each scenario based on the session's persisted status:

**Execution phase recovery** (session status `running` or `paused`):

1. **Scan `workers/<N>/` directories** for plan files. Any plan found here was in-flight when the crash occurred.

2. **Completed-but-not-collected**: If a `.status` sidecar file exists alongside the plan and reads `STATUS: done`, the worker finished but the orchestrator crashed before collecting:
   - Run pack's `isolate_end` hook with status `"done"`.
   - Move plan + status to `done/`.
   - Update DB task status to `"done"`.

3. **Incomplete work**: If no sidecar exists, or sidecar reads `STATUS: blocked` or is malformed:
   - Run pack's `isolate_end` hook with status `"blocked"` (cleanup without merge).
   - Move plan file back to `ready/` (NOT `blocked/` — the failure was infrastructure, not task-level).
   - Update DB task status to `"ready"`.
   - The task will be re-dispatched on the next eligible cycle.

4. **Force-clean worker directories**: After processing all worker dirs, ensure each `workers/<N>/` directory is empty.

**Planning phase recovery** (session status `planning`):

1. Plans in `claimed/`: Move back to `intake/`. Partial planner work is discarded.
2. Plans in `staging/`: Leave as-is (complete and valid).
3. Plans in `review/`: Leave as-is (needs human input).

**Resolution phase recovery** (session status `resolving`):

1. Delete partial `resolution.json` if it exists.
2. For each plan in `ready/`: check if it has constraint metadata. If not, move it back to `staging/`.

**Verification phase recovery** (session status `verifying`):

1. Set session status back to `running`. Verification will re-trigger naturally.

### SQLite-filesystem reconciliation

- `reconcile_db_with_filesystem(session_id: str)` — The filesystem is the source of truth. Scan all state directories (`intake/`, `claimed/`, `staging/`, `review/`, `ready/`, `workers/*/`, `done/`, `blocked/`) and compare with DB task statuses. For any mismatch, update the DB to match the filesystem. Log each correction as a warning.

This runs as the final step of recovery, after all file moves are complete.

### Zombie process cleanup

On recovery, check for stale PID files or known process patterns from the previous session. The orchestrator records active worker PIDs in the session directory as `workers/<N>/pid`. On recovery:
- Read each PID file.
- Check if the process is still running (`os.kill(pid, 0)`).
- If running: SIGTERM, wait 5s, SIGKILL.
- Delete the PID file.

## Acceptance tests

```python
# tests/test_phase06_crash_recovery.py
import asyncio
import json
import os
import signal
import stat
import yaml
import pytest
from pathlib import Path

from switchyard.models import Session, Task
from switchyard.config import ensure_dirs
from switchyard.state import (
    init_db, create_session, create_task, get_task, update_task,
    list_tasks, get_session, update_session, create_session_dirs,
    create_worker_slots,
)
from switchyard.orchestrator import Orchestrator
from switchyard.state import reconcile_db_with_filesystem


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


def _create_echo_pack(packs_dir):
    pack_dir = packs_dir / "test-echo"
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "scripts").mkdir(exist_ok=True)
    execute = pack_dir / "scripts" / "execute.sh"
    execute.write_text('#!/bin/bash\ncat "$1"\nSIDECAR="${1%.plan.md}.status"\necho "STATUS: done" > "$SIDECAR"\n')
    execute.chmod(execute.stat().st_mode | stat.S_IEXEC)
    config = {
        "name": "test-echo",
        "description": "Test pack",
        "version": "1.0.0",
        "phases": {"execution": {"enabled": True, "executor": "shell", "command": "scripts/execute.sh", "max_workers": 2}},
        "isolation": {"type": "none"},
    }
    (pack_dir / "pack.yaml").write_text(yaml.dump(config))
    return pack_dir


# --- Execution recovery: completed-but-not-collected ---

@pytest.mark.asyncio
async def test_recovery_collects_completed_worker(tmp_path):
    """If a worker finished (sidecar says done) but orchestrator crashed before collecting,
    recovery should move the task to done/."""
    packs_dir = tmp_path / ".switchyard" / "packs"
    _create_echo_pack(packs_dir)
    await init_db()

    session = Session(id="s1", name="test", pack="test-echo", status="running", config={"workers": 2}, created_at="2026-01-01T00:00:00Z")
    await create_session(session)
    session_path = await create_session_dirs("s1")
    await create_worker_slots("s1", 2)

    # Simulate: task file in worker dir with a "done" sidecar
    task = Task(id="t1", session_id="s1", title="Task 1", status="active",
                depends_on=[], anti_affinity=[], exec_order=1, created_at="2026-01-01T00:00:00Z")
    await create_task(task)
    worker_dir = session_path / "workers" / "0"
    worker_dir.mkdir(parents=True, exist_ok=True)
    (worker_dir / "t1.plan.md").write_text("# Task 1")
    (worker_dir / "t1.status").write_text("STATUS: done\nCOMMITS: abc\n")

    orch = Orchestrator("s1", "test-echo", {"workers": 2, "poll_interval": 0.2})
    await orch.recover()

    assert (session_path / "done" / "t1.plan.md").exists()
    assert not (worker_dir / "t1.plan.md").exists()
    t1 = await get_task("s1", "t1")
    assert t1.status == "done"


# --- Execution recovery: incomplete work ---

@pytest.mark.asyncio
async def test_recovery_reverts_incomplete_worker_to_ready(tmp_path):
    """If a worker was mid-task (no sidecar or blocked sidecar), recovery should
    move the task back to ready/ for re-dispatch, NOT to blocked/."""
    packs_dir = tmp_path / ".switchyard" / "packs"
    _create_echo_pack(packs_dir)
    await init_db()

    session = Session(id="s1", name="test", pack="test-echo", status="running", config={"workers": 2}, created_at="2026-01-01T00:00:00Z")
    await create_session(session)
    session_path = await create_session_dirs("s1")
    await create_worker_slots("s1", 2)

    task = Task(id="t1", session_id="s1", title="Task 1", status="active",
                depends_on=[], anti_affinity=[], exec_order=1, created_at="2026-01-01T00:00:00Z")
    await create_task(task)
    worker_dir = session_path / "workers" / "0"
    worker_dir.mkdir(parents=True, exist_ok=True)
    (worker_dir / "t1.plan.md").write_text("# Task 1")
    # No sidecar file — task was interrupted

    orch = Orchestrator("s1", "test-echo", {"workers": 2, "poll_interval": 0.2})
    await orch.recover()

    assert (session_path / "ready" / "t1.plan.md").exists()
    assert not (worker_dir / "t1.plan.md").exists()
    t1 = await get_task("s1", "t1")
    assert t1.status == "ready"


# --- Planning recovery ---

@pytest.mark.asyncio
async def test_recovery_moves_claimed_back_to_intake(tmp_path):
    packs_dir = tmp_path / ".switchyard" / "packs"
    _create_echo_pack(packs_dir)
    await init_db()

    session = Session(id="s1", name="test", pack="test-echo", status="planning", config={}, created_at="2026-01-01T00:00:00Z")
    await create_session(session)
    session_path = await create_session_dirs("s1")

    (session_path / "claimed" / "t1.md").write_text("# Task 1")
    (session_path / "staging" / "t2.plan.md").write_text("# Task 2 plan")

    orch = Orchestrator("s1", "test-echo", {"workers": 2, "poll_interval": 0.2})
    await orch.recover()

    assert (session_path / "intake" / "t1.md").exists()
    assert not (session_path / "claimed" / "t1.md").exists()
    # Staging items should be untouched
    assert (session_path / "staging" / "t2.plan.md").exists()


# --- Resolution recovery ---

@pytest.mark.asyncio
async def test_recovery_deletes_partial_resolution(tmp_path):
    packs_dir = tmp_path / ".switchyard" / "packs"
    _create_echo_pack(packs_dir)
    await init_db()

    session = Session(id="s1", name="test", pack="test-echo", status="resolving", config={}, created_at="2026-01-01T00:00:00Z")
    await create_session(session)
    session_path = await create_session_dirs("s1")

    (session_path / "resolution.json").write_text("{incomplete")  # partial/corrupt

    orch = Orchestrator("s1", "test-echo", {"workers": 2, "poll_interval": 0.2})
    await orch.recover()

    assert not (session_path / "resolution.json").exists()


# --- DB-filesystem reconciliation ---

@pytest.mark.asyncio
async def test_reconcile_db_matches_filesystem(tmp_path):
    """DB says task is active, but filesystem shows it's in ready/. DB should be corrected."""
    sessions_dir = tmp_path / ".switchyard" / "sessions"
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("switchyard.state.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("switchyard.state.DB_PATH", tmp_path / ".switchyard" / "switchyard.db")
    ensure_dirs()
    await init_db()

    session = Session(id="s1", name="test", pack="test-echo", status="running", config={}, created_at="2026-01-01T00:00:00Z")
    await create_session(session)
    session_path = await create_session_dirs("s1")

    task = Task(id="t1", session_id="s1", title="Task 1", status="active",
                depends_on=[], anti_affinity=[], exec_order=1, created_at="2026-01-01T00:00:00Z")
    await create_task(task)
    # Filesystem says ready
    (session_path / "ready" / "t1.plan.md").write_text("# Task 1")

    await reconcile_db_with_filesystem("s1")

    t1 = await get_task("s1", "t1")
    assert t1.status == "ready"


# --- Verification recovery ---

@pytest.mark.asyncio
async def test_recovery_from_verifying_resets_to_running(tmp_path):
    packs_dir = tmp_path / ".switchyard" / "packs"
    _create_echo_pack(packs_dir)
    await init_db()

    session = Session(id="s1", name="test", pack="test-echo", status="verifying", config={}, created_at="2026-01-01T00:00:00Z")
    await create_session(session)
    await create_session_dirs("s1")

    orch = Orchestrator("s1", "test-echo", {"workers": 2, "poll_interval": 0.2})
    await orch.recover()

    s = await get_session("s1")
    assert s.status == "running"


# --- Paused session stays paused ---

@pytest.mark.asyncio
async def test_recovery_paused_stays_paused(tmp_path):
    """Recovery must not auto-resume a paused session."""
    packs_dir = tmp_path / ".switchyard" / "packs"
    _create_echo_pack(packs_dir)
    await init_db()

    session = Session(id="s1", name="test", pack="test-echo", status="paused", config={}, created_at="2026-01-01T00:00:00Z")
    await create_session(session)
    await create_session_dirs("s1")

    orch = Orchestrator("s1", "test-echo", {"workers": 2, "poll_interval": 0.2})
    await orch.recover()

    s = await get_session("s1")
    # Session should still be paused after recovery (worker cleanup happens, but dispatch stays paused)
    assert s.status in ("paused", "running")
    assert orch._paused is True
```
