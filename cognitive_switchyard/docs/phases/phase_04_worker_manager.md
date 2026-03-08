# Phase 04: Worker Manager

**Design doc:** `docs/cognitive_switchyard_design.md`

## Spec

Build the worker slot management and subprocess lifecycle system. The worker manager owns a fixed pool of numbered slots, launches subprocesses in each slot, captures stdout/stderr to log files, and parses progress markers from executor output.

### Files to create

- `switchyard/worker_manager.py`

### Dependencies from prior phases

- `switchyard/models.py` — `WorkerSlot`, `Task` dataclasses

### Worker slot pool

- `WorkerPool` class. Constructor takes `num_slots: int` and `log_dir: Path`.
- `slots: list[SlotState]` — Internal state per slot. Each `SlotState` tracks: `slot_number: int`, `status: str` (`"idle"` or `"active"`), `process: Optional[subprocess.Popen]`, `task_id: Optional[str]`, `log_file: Optional[IO]`, `started_at: Optional[float]` (monotonic time), `last_output_at: Optional[float]` (monotonic time, updated on any stdout/stderr), `current_phase: Optional[str]`, `phase_num: Optional[int]`, `phase_total: Optional[int]`, `detail: Optional[str]`.

### Slot lifecycle

- `idle_slots() -> list[int]` — Return slot numbers where status is `"idle"`.
- `active_slots() -> list[int]` — Return slot numbers where status is `"active"`.
- `dispatch(slot_number: int, task_id: str, process: subprocess.Popen)` — Assign a task to a slot. Set status to `"active"`, record start time, open log file at `log_dir/workers/{slot_number}.log` (append mode), start capturing stdout/stderr from the Popen. The caller (orchestrator) creates the Popen via pack_loader's `run_hook_async`; the worker manager just manages it.
- `is_finished(slot_number: int) -> bool` — Check if the slot's process has terminated (via `poll()`).
- `collect(slot_number: int) -> dict` — Called after `is_finished` returns True. Returns `{"task_id": str, "returncode": int, "elapsed": float}`. Resets the slot to `"idle"`.
- `kill(slot_number: int, reason: str)` — Send SIGTERM to the process, wait up to 5 seconds, send SIGKILL if still alive. Log the kill reason. Mark slot as needing collection.
- `read_new_output(slot_number: int) -> list[str]` — Non-blocking read of any new lines from the process's stdout. Each line is also written to the slot's log file. Updates `last_output_at` on any output.

### Progress parsing

- `parse_progress_line(line: str) -> Optional[dict]` — Parse a `##PROGRESS##` line. Two formats:
  - Phase: `##PROGRESS## <task_id> | Phase: <name> | <N>/<total>` → `{"type": "phase", "task_id": str, "phase": str, "phase_num": int, "phase_total": int}`
  - Detail: `##PROGRESS## <task_id> | Detail: <message>` → `{"type": "detail", "task_id": str, "detail": str}`
  - Returns None for non-progress lines.

When a progress line is parsed during `read_new_output`, the slot's `current_phase`, `phase_num`, `phase_total`, and/or `detail` fields are updated automatically.

### Elapsed and idle tracking

- `seconds_since_last_output(slot_number: int) -> float` — Seconds since the last stdout/stderr line was received. Uses monotonic clock.
- `elapsed(slot_number: int) -> float` — Seconds since the task was dispatched.

### Status sidecar parsing

- `parse_status_sidecar(path: Path) -> dict` — Parse a key-value status sidecar file (format from design doc Section 4.4). Returns dict with keys: `STATUS`, `COMMITS`, `TESTS_RAN`, `TEST_RESULT`, `BLOCKED_REASON`, `NOTES`. All values are strings. Missing keys have empty-string values.

## Acceptance tests

```python
# tests/test_phase04_worker_manager.py
import os
import signal
import subprocess
import time
import pytest
from pathlib import Path

from switchyard.worker_manager import WorkerPool, parse_progress_line, parse_status_sidecar


@pytest.fixture
def pool(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "workers").mkdir()
    return WorkerPool(num_slots=3, log_dir=log_dir)


# --- Slot lifecycle ---

def test_initial_slots_all_idle(pool):
    assert pool.idle_slots() == [0, 1, 2]
    assert pool.active_slots() == []


def test_dispatch_marks_active(pool):
    proc = subprocess.Popen(["sleep", "10"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        pool.dispatch(0, "t1", proc)
        assert 0 not in pool.idle_slots()
        assert 0 in pool.active_slots()
    finally:
        proc.kill()
        proc.wait()


def test_collect_resets_to_idle(pool, tmp_path):
    proc = subprocess.Popen(["echo", "hello"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pool.dispatch(0, "t1", proc)
    proc.wait()  # ensure finished
    assert pool.is_finished(0)
    result = pool.collect(0)
    assert result["task_id"] == "t1"
    assert result["returncode"] == 0
    assert result["elapsed"] >= 0
    assert 0 in pool.idle_slots()


def test_is_finished_false_while_running(pool):
    proc = subprocess.Popen(["sleep", "10"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        pool.dispatch(0, "t1", proc)
        assert pool.is_finished(0) is False
    finally:
        proc.kill()
        proc.wait()


# --- Kill ---

def test_kill_terminates_process(pool):
    proc = subprocess.Popen(["sleep", "60"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pool.dispatch(0, "t1", proc)
    pool.kill(0, "test kill")
    # Process should be dead
    assert proc.poll() is not None


# --- Output capture ---

def test_read_new_output_captures_lines(pool, tmp_path):
    proc = subprocess.Popen(
        ["bash", "-c", "echo line1; echo line2; echo line3"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    pool.dispatch(0, "t1", proc)
    proc.wait()
    time.sleep(0.1)  # let output buffer
    lines = pool.read_new_output(0)
    assert "line1" in "\n".join(lines)
    # Log file should also contain the output
    log_path = tmp_path / "logs" / "workers" / "0.log"
    assert log_path.exists()
    assert "line1" in log_path.read_text()


def test_read_new_output_updates_last_output_time(pool):
    proc = subprocess.Popen(["echo", "hi"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pool.dispatch(0, "t1", proc)
    proc.wait()
    time.sleep(0.05)
    pool.read_new_output(0)
    assert pool.seconds_since_last_output(0) < 2.0


# --- Progress parsing ---

def test_parse_phase_progress():
    line = "##PROGRESS## t1 | Phase: implementing | 3/5"
    result = parse_progress_line(line)
    assert result["type"] == "phase"
    assert result["task_id"] == "t1"
    assert result["phase"] == "implementing"
    assert result["phase_num"] == 3
    assert result["phase_total"] == 5


def test_parse_detail_progress():
    line = "##PROGRESS## t1 | Detail: Processing chunk 3/9"
    result = parse_progress_line(line)
    assert result["type"] == "detail"
    assert result["detail"] == "Processing chunk 3/9"


def test_parse_non_progress_line():
    assert parse_progress_line("just a regular log line") is None


def test_progress_updates_slot_state(pool):
    proc = subprocess.Popen(
        ["bash", "-c", "echo '##PROGRESS## t1 | Phase: testing | 2/4'"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    pool.dispatch(0, "t1", proc)
    proc.wait()
    time.sleep(0.05)
    pool.read_new_output(0)
    slot = pool.slots[0]
    assert slot.current_phase == "testing"
    assert slot.phase_num == 2
    assert slot.phase_total == 4


# --- Status sidecar parsing ---

def test_parse_status_sidecar_done(tmp_path):
    sidecar = tmp_path / "task.status"
    sidecar.write_text("STATUS: done\nCOMMITS: abc123,def456\nTESTS_RAN: full\nTEST_RESULT: pass\n")
    result = parse_status_sidecar(sidecar)
    assert result["STATUS"] == "done"
    assert result["COMMITS"] == "abc123,def456"


def test_parse_status_sidecar_blocked(tmp_path):
    sidecar = tmp_path / "task.status"
    sidecar.write_text("STATUS: blocked\nBLOCKED_REASON: Test suite failed\n")
    result = parse_status_sidecar(sidecar)
    assert result["STATUS"] == "blocked"
    assert result["BLOCKED_REASON"] == "Test suite failed"


def test_parse_status_sidecar_missing_keys(tmp_path):
    sidecar = tmp_path / "task.status"
    sidecar.write_text("STATUS: done\n")
    result = parse_status_sidecar(sidecar)
    assert result["COMMITS"] == ""
    assert result["NOTES"] == ""


# --- Elapsed tracking ---

def test_elapsed_increases(pool):
    proc = subprocess.Popen(["sleep", "10"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        pool.dispatch(0, "t1", proc)
        time.sleep(0.1)
        assert pool.elapsed(0) >= 0.1
    finally:
        proc.kill()
        proc.wait()
```
