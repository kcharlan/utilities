# Phase 01: Models, Config, and State Store

**Design doc:** `docs/cognitive_switchyard_design.md`

## Spec

Build the foundational data layer: dataclasses, configuration management, SQLite schema, and file-as-state directory management.

### Files to create

- `switchyard/models.py` — All dataclasses
- `switchyard/config.py` — Config loading/saving, path constants, defaults
- `switchyard/state.py` — SQLite operations and file-as-state directory management
- `switchyard/__init__.py` — Empty (package marker)

### Data models (`models.py`)

Dataclasses (frozen where possible):

- **`Session`**: `id: str`, `name: str`, `pack: str`, `status: str`, `config: dict`, `created_at: str`, `started_at: Optional[str]`, `completed_at: Optional[str]`, `abort_reason: Optional[str]`. Valid statuses: `created`, `planning`, `resolving`, `running`, `paused`, `verifying`, `completed`, `aborted`.
- **`Task`**: `id: str`, `session_id: str`, `title: str`, `status: str`, `phase: Optional[str]`, `worker_slot: Optional[int]`, `depends_on: list[str]`, `anti_affinity: list[str]`, `exec_order: int`, `created_at: str`, `started_at: Optional[str]`, `completed_at: Optional[str]`. Valid statuses: `intake`, `planning`, `staged`, `review`, `ready`, `active`, `done`, `blocked`.
- **`WorkerSlot`**: `slot_number: int`, `session_id: str`, `status: str`, `current_task_id: Optional[str]`. Valid statuses: `idle`, `active`.
- **`Event`**: `id: Optional[int]`, `session_id: str`, `timestamp: str`, `event_type: str`, `task_id: Optional[str]`, `message: str`.

### Configuration (`config.py`)

- `SWITCHYARD_HOME = ~/.switchyard`
- `SWITCHYARD_VENV = ~/.switchyard_venv`
- `DB_PATH = ~/.switchyard/switchyard.db`
- `PACKS_DIR = ~/.switchyard/packs`
- `SESSIONS_DIR = ~/.switchyard/sessions`
- `CONFIG_PATH = ~/.switchyard/config.yaml`
- `load_config() -> dict` — Read `config.yaml`, return dict with defaults applied. Defaults: `retention_days: 30`, `default_planners: 3`, `default_workers: 3`, `default_pack: ""`.
- `save_config(config: dict)` — Write dict to `config.yaml`.
- `ensure_dirs()` — Create `SWITCHYARD_HOME`, `PACKS_DIR`, `SESSIONS_DIR` if missing.

### State store (`state.py`)

All functions are `async` using `aiosqlite`.

**SQLite schema** (4 tables):
- `sessions` — mirrors Session dataclass
- `tasks` — mirrors Task dataclass, `depends_on` and `anti_affinity` stored as JSON arrays
- `worker_slots` — mirrors WorkerSlot
- `events` — mirrors Event, auto-increment id

**Functions:**
- `init_db()` — Create tables if not exist, enable WAL mode.
- `create_session(session: Session)`, `get_session(id)`, `update_session(id, **fields)`, `list_sessions()`.
- `create_task(task: Task)`, `get_task(session_id, task_id)`, `update_task(session_id, task_id, **fields)`, `list_tasks(session_id, status=None)`.
- `create_worker_slots(session_id, count)`, `get_worker_slots(session_id)`, `update_worker_slot(session_id, slot_number, **fields)`.
- `add_event(event: Event)`, `list_events(session_id, limit=100)`.
- `delete_session(session_id)` — Delete all rows for a session (sessions, tasks, worker_slots, events).

**File-as-state directories:**
- `create_session_dirs(session_id: str) -> Path` — Create the full directory tree under `SESSIONS_DIR/<session_id>/`: `intake/`, `claimed/`, `staging/`, `review/`, `ready/`, `workers/`, `done/`, `blocked/`, `logs/`, `logs/workers/`.
- `get_task_status_from_filesystem(session_id: str, task_filename: str) -> Optional[str]` — Scan state directories to find which one contains the file. Returns the status string (e.g., `"ready"`, `"done"`) or None.

**Session trimming:**
- `trim_completed_session(session_id: str)` — For successfully completed sessions only: write `summary.json` (session metadata + per-task final statuses), then delete all directories except `summary.json`, `resolution.json`, and `logs/session.log`. Must NOT trim if any task is in `blocked` status.

## Acceptance tests

```python
# tests/test_phase01_models_config_state.py
import asyncio
import json
import os
import yaml
import pytest
from pathlib import Path

from switchyard.models import Session, Task, WorkerSlot, Event
from switchyard.config import (
    load_config, save_config, ensure_dirs,
    SWITCHYARD_HOME, DB_PATH, CONFIG_PATH,
)
from switchyard.state import (
    init_db, create_session, get_session, update_session, list_sessions,
    create_task, get_task, update_task, list_tasks,
    create_session_dirs, get_task_status_from_filesystem,
    trim_completed_session, delete_session, add_event, list_events,
    create_worker_slots, get_worker_slots, update_worker_slot,
)


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    """Redirect all switchyard paths to tmp_path for test isolation."""
    monkeypatch.setattr("switchyard.config.SWITCHYARD_HOME", tmp_path / ".switchyard")
    monkeypatch.setattr("switchyard.config.DB_PATH", tmp_path / ".switchyard" / "switchyard.db")
    monkeypatch.setattr("switchyard.config.CONFIG_PATH", tmp_path / ".switchyard" / "config.yaml")
    monkeypatch.setattr("switchyard.config.PACKS_DIR", tmp_path / ".switchyard" / "packs")
    monkeypatch.setattr("switchyard.config.SESSIONS_DIR", tmp_path / ".switchyard" / "sessions")
    monkeypatch.setattr("switchyard.state.DB_PATH", tmp_path / ".switchyard" / "switchyard.db")
    monkeypatch.setattr("switchyard.state.SESSIONS_DIR", tmp_path / ".switchyard" / "sessions")
    ensure_dirs()


# --- Models ---

def test_session_valid_statuses():
    s = Session(id="s1", name="test", pack="echo", status="created", config={}, created_at="2026-01-01T00:00:00Z")
    assert s.status == "created"


def test_task_stores_constraints():
    t = Task(id="t1", session_id="s1", title="Fix bug", status="ready",
             depends_on=["t0"], anti_affinity=["t2"], exec_order=3, created_at="2026-01-01T00:00:00Z")
    assert t.depends_on == ["t0"]
    assert t.anti_affinity == ["t2"]
    assert t.exec_order == 3


# --- Config ---

def test_config_defaults_when_no_file():
    cfg = load_config()
    assert cfg["retention_days"] == 30
    assert cfg["default_workers"] == 3
    assert cfg["default_planners"] == 3


def test_config_roundtrip():
    save_config({"retention_days": 7, "default_workers": 5, "default_planners": 2, "default_pack": "my-pack"})
    cfg = load_config()
    assert cfg["retention_days"] == 7
    assert cfg["default_pack"] == "my-pack"


def test_ensure_dirs_creates_all(tmp_path, monkeypatch):
    home = tmp_path / "fresh"
    monkeypatch.setattr("switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("switchyard.config.PACKS_DIR", home / "packs")
    monkeypatch.setattr("switchyard.config.SESSIONS_DIR", home / "sessions")
    ensure_dirs()
    assert (home / "packs").is_dir()
    assert (home / "sessions").is_dir()


# --- State Store (SQLite) ---

@pytest.mark.asyncio
async def test_session_crud():
    await init_db()
    s = Session(id="s1", name="test-run", pack="echo", status="created", config={"workers": 2}, created_at="2026-01-01T00:00:00Z")
    await create_session(s)
    got = await get_session("s1")
    assert got.name == "test-run"
    assert got.config == {"workers": 2}
    await update_session("s1", status="running")
    got = await get_session("s1")
    assert got.status == "running"


@pytest.mark.asyncio
async def test_task_crud_with_json_constraints():
    await init_db()
    s = Session(id="s1", name="test", pack="echo", status="created", config={}, created_at="2026-01-01T00:00:00Z")
    await create_session(s)
    t = Task(id="t1", session_id="s1", title="Task one", status="ready",
             depends_on=["t0"], anti_affinity=["t2", "t3"], exec_order=2, created_at="2026-01-01T00:00:00Z")
    await create_task(t)
    got = await get_task("s1", "t1")
    assert got.depends_on == ["t0"]
    assert got.anti_affinity == ["t2", "t3"]


@pytest.mark.asyncio
async def test_list_tasks_by_status():
    await init_db()
    s = Session(id="s1", name="test", pack="echo", status="running", config={}, created_at="2026-01-01T00:00:00Z")
    await create_session(s)
    await create_task(Task(id="t1", session_id="s1", title="A", status="ready", depends_on=[], anti_affinity=[], exec_order=1, created_at="2026-01-01T00:00:00Z"))
    await create_task(Task(id="t2", session_id="s1", title="B", status="done", depends_on=[], anti_affinity=[], exec_order=2, created_at="2026-01-01T00:00:00Z"))
    ready = await list_tasks("s1", status="ready")
    assert len(ready) == 1
    assert ready[0].id == "t1"


@pytest.mark.asyncio
async def test_delete_session_cascades():
    await init_db()
    s = Session(id="s1", name="test", pack="echo", status="completed", config={}, created_at="2026-01-01T00:00:00Z")
    await create_session(s)
    await create_task(Task(id="t1", session_id="s1", title="A", status="done", depends_on=[], anti_affinity=[], exec_order=1, created_at="2026-01-01T00:00:00Z"))
    await add_event(Event(id=None, session_id="s1", timestamp="2026-01-01T00:00:00Z", event_type="created", task_id=None, message="Session created"))
    await delete_session("s1")
    assert await get_session("s1") is None
    assert await list_tasks("s1") == []
    assert await list_events("s1") == []


# --- File-as-state ---

@pytest.mark.asyncio
async def test_create_session_dirs(tmp_path, monkeypatch):
    sessions_dir = tmp_path / ".switchyard" / "sessions"
    monkeypatch.setattr("switchyard.state.SESSIONS_DIR", sessions_dir)
    session_path = await create_session_dirs("test-session")
    for subdir in ["intake", "claimed", "staging", "review", "ready", "workers", "done", "blocked", "logs"]:
        assert (session_path / subdir).is_dir(), f"Missing directory: {subdir}"
    assert (session_path / "logs" / "workers").is_dir()


@pytest.mark.asyncio
async def test_get_task_status_from_filesystem(tmp_path, monkeypatch):
    sessions_dir = tmp_path / ".switchyard" / "sessions"
    monkeypatch.setattr("switchyard.state.SESSIONS_DIR", sessions_dir)
    session_path = await create_session_dirs("s1")
    (session_path / "ready" / "task_001.plan.md").write_text("plan content")
    status = await get_task_status_from_filesystem("s1", "task_001.plan.md")
    assert status == "ready"


@pytest.mark.asyncio
async def test_get_task_status_returns_none_for_missing(tmp_path, monkeypatch):
    sessions_dir = tmp_path / ".switchyard" / "sessions"
    monkeypatch.setattr("switchyard.state.SESSIONS_DIR", sessions_dir)
    await create_session_dirs("s1")
    status = await get_task_status_from_filesystem("s1", "nonexistent.plan.md")
    assert status is None


# --- Session trimming ---

@pytest.mark.asyncio
async def test_trim_completed_session_keeps_summary(tmp_path, monkeypatch):
    sessions_dir = tmp_path / ".switchyard" / "sessions"
    monkeypatch.setattr("switchyard.state.SESSIONS_DIR", sessions_dir)
    await init_db()
    s = Session(id="s1", name="test", pack="echo", status="completed", config={}, created_at="2026-01-01T00:00:00Z", completed_at="2026-01-01T01:00:00Z")
    await create_session(s)
    await create_task(Task(id="t1", session_id="s1", title="A", status="done", depends_on=[], anti_affinity=[], exec_order=1, created_at="2026-01-01T00:00:00Z"))
    session_path = await create_session_dirs("s1")
    (session_path / "done" / "task.plan.md").write_text("done")
    (session_path / "resolution.json").write_text("{}")
    (session_path / "logs" / "session.log").write_text("log")
    await trim_completed_session("s1")
    assert (session_path / "summary.json").exists()
    assert (session_path / "resolution.json").exists()
    assert (session_path / "logs" / "session.log").exists()
    assert not (session_path / "done").exists()
    assert not (session_path / "intake").exists()


@pytest.mark.asyncio
async def test_trim_refuses_if_blocked_tasks(tmp_path, monkeypatch):
    """Trimming must NOT run if any task is blocked -- artifacts needed for debugging."""
    sessions_dir = tmp_path / ".switchyard" / "sessions"
    monkeypatch.setattr("switchyard.state.SESSIONS_DIR", sessions_dir)
    await init_db()
    s = Session(id="s1", name="test", pack="echo", status="completed", config={}, created_at="2026-01-01T00:00:00Z")
    await create_session(s)
    await create_task(Task(id="t1", session_id="s1", title="A", status="done", depends_on=[], anti_affinity=[], exec_order=1, created_at="2026-01-01T00:00:00Z"))
    await create_task(Task(id="t2", session_id="s1", title="B", status="blocked", depends_on=[], anti_affinity=[], exec_order=2, created_at="2026-01-01T00:00:00Z"))
    session_path = await create_session_dirs("s1")
    (session_path / "done" / "t1.plan.md").write_text("done")
    (session_path / "blocked" / "t2.plan.md").write_text("blocked")
    await trim_completed_session("s1")
    # Artifacts must still exist -- trimming was refused
    assert (session_path / "done" / "t1.plan.md").exists()
    assert (session_path / "blocked" / "t2.plan.md").exists()
    assert not (session_path / "summary.json").exists()
```
