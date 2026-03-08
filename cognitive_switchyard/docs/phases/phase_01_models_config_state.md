# Phase 1: Models, Config, and State Store

## Spec

Create the foundational data layer: dataclasses, configuration, SQLite schema, and session directory management.

### Files to create

**`switchyard/__init__.py`** — Empty package init.

**`switchyard/models.py`** — Dataclasses (not ORM, plain `@dataclass`):

- `Session(id: str, name: str, pack: str, status: str, config: dict, created_at: str, completed_at: Optional[str], abort_reason: Optional[str])` — `status` is one of: `created`, `planning`, `resolving`, `running`, `paused`, `verifying`, `completed`, `aborted`.
- `Task(id: str, session_id: str, title: str, status: str, phase: Optional[str], worker_slot: Optional[int], depends_on: list[str], anti_affinity: list[str], exec_order: int, created_at: str, started_at: Optional[str], completed_at: Optional[str])` — `status` is one of: `intake`, `planning`, `staged`, `review`, `ready`, `active`, `done`, `blocked`.
- `WorkerSlot(session_id: str, slot_number: int, status: str, current_task_id: Optional[str])` — `status`: `idle`, `active`.
- `Event(session_id: str, timestamp: str, event_type: str, task_id: Optional[str], message: str)`.

**`switchyard/config.py`** — Configuration and path management:

- `SWITCHYARD_HOME` = `~/.switchyard/` (expanduser).
- `DB_PATH` = `~/.switchyard/switchyard.db`.
- `PACKS_DIR` = `~/.switchyard/packs/`.
- `SESSIONS_DIR` = `~/.switchyard/sessions/`.
- `CONFIG_PATH` = `~/.switchyard/config.yaml`.
- `VENV_DIR` = `~/.switchyard_venv/`.
- `DEFAULT_CONFIG = {"retention_days": 30, "default_planners": 3, "default_workers": 3, "default_pack": "claude-code"}`.
- `load_config() -> dict` — Read `config.yaml`, return merged with defaults. Create file with defaults if missing.
- `save_config(cfg: dict)` — Write to `config.yaml`.
- `ensure_directories()` — Create `SWITCHYARD_HOME`, `PACKS_DIR`, `SESSIONS_DIR` if they don't exist.

**`switchyard/state.py`** — SQLite state store (synchronous `sqlite3`, not async — async is only needed in the server layer):

- `StateStore(db_path: str)` — constructor opens/creates the database, calls `_init_schema()`.
- `_init_schema()` — Creates tables if not exist:
  - `sessions` (id TEXT PK, name, pack, status, config TEXT as JSON, created_at, completed_at, abort_reason)
  - `tasks` (id TEXT, session_id TEXT, title, status, phase, worker_slot INTEGER, depends_on TEXT as JSON list, anti_affinity TEXT as JSON list, exec_order INTEGER DEFAULT 0, created_at, started_at, completed_at, PK(id, session_id))
  - `worker_slots` (session_id TEXT, slot_number INTEGER, status TEXT DEFAULT 'idle', current_task_id TEXT, PK(session_id, slot_number))
  - `events` (id INTEGER PK AUTOINCREMENT, session_id, timestamp, event_type, task_id, message)
- `create_session(session: Session) -> Session`
- `get_session(session_id: str) -> Optional[Session]`
- `list_sessions() -> list[Session]`
- `update_session(session_id: str, **fields)` — Update only specified fields. Validates `status` against allowed values.
- `create_task(task: Task) -> Task`
- `get_task(session_id: str, task_id: str) -> Optional[Task]`
- `list_tasks(session_id: str, status: Optional[str] = None) -> list[Task]`
- `update_task(session_id: str, task_id: str, **fields)` — Update only specified fields.
- `create_worker_slots(session_id: str, count: int)` — Insert N slots (0 to count-1).
- `get_worker_slots(session_id: str) -> list[WorkerSlot]`
- `update_worker_slot(session_id: str, slot_number: int, **fields)`
- `add_event(event: Event)`
- `list_events(session_id: str, limit: int = 100) -> list[Event]`
- `close()` — Close the DB connection.

All JSON list fields (`depends_on`, `anti_affinity`, `config`) are stored as JSON strings and deserialized on read.

**Session directory creation** — `state.py` also provides:
- `create_session_dirs(session_id: str) -> Path` — Creates `~/.switchyard/sessions/<session_id>/` with subdirectories: `intake/`, `claimed/`, `staging/`, `review/`, `ready/`, `workers/`, `done/`, `blocked/`, `logs/`, `logs/workers/`. Returns session root path.

## Acceptance tests

```python
"""tests/test_phase01_models_config_state.py"""
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def sw_home(tmp_path):
    """Redirect all switchyard paths to tmp_path."""
    home = tmp_path / ".switchyard"
    home.mkdir()
    return home


@pytest.fixture
def store(sw_home):
    from switchyard.state import StateStore
    db_path = str(sw_home / "test.db")
    s = StateStore(db_path)
    yield s
    s.close()


# --- Models ---

def test_session_valid_statuses():
    from switchyard.models import Session
    for st in ["created", "planning", "resolving", "running", "paused",
               "verifying", "completed", "aborted"]:
        s = Session(id="s1", name="n", pack="p", status=st, config={},
                    created_at="2026-01-01T00:00:00Z")
        assert s.status == st


def test_task_valid_statuses():
    from switchyard.models import Task
    for st in ["intake", "planning", "staged", "review", "ready",
               "active", "done", "blocked"]:
        t = Task(id="t1", session_id="s1", title="x", status=st,
                 depends_on=[], anti_affinity=[], exec_order=0,
                 created_at="2026-01-01T00:00:00Z")
        assert t.status == st


# --- Config ---

def test_load_config_creates_default_if_missing(tmp_path, monkeypatch):
    from switchyard import config
    cfg_path = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "CONFIG_PATH", str(cfg_path))
    result = config.load_config()
    assert result["retention_days"] == 30
    assert result["default_workers"] == 3
    assert cfg_path.exists()


def test_save_and_reload_config(tmp_path, monkeypatch):
    from switchyard import config
    cfg_path = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "CONFIG_PATH", str(cfg_path))
    config.save_config({"retention_days": 7, "default_pack": "ffmpeg"})
    loaded = config.load_config()
    assert loaded["retention_days"] == 7
    assert loaded["default_pack"] == "ffmpeg"
    # Defaults for missing keys are merged in
    assert loaded["default_workers"] == 3


def test_ensure_directories(tmp_path, monkeypatch):
    from switchyard import config
    home = tmp_path / ".switchyard"
    monkeypatch.setattr(config, "SWITCHYARD_HOME", str(home))
    monkeypatch.setattr(config, "PACKS_DIR", str(home / "packs"))
    monkeypatch.setattr(config, "SESSIONS_DIR", str(home / "sessions"))
    config.ensure_directories()
    assert (home / "packs").is_dir()
    assert (home / "sessions").is_dir()


# --- State Store: Sessions ---

def test_create_and_get_session(store):
    from switchyard.models import Session
    s = Session(id="s1", name="test-run", pack="echo", status="created",
                config={"workers": 2}, created_at="2026-01-01T00:00:00Z")
    store.create_session(s)
    got = store.get_session("s1")
    assert got is not None
    assert got.name == "test-run"
    assert got.config == {"workers": 2}


def test_get_nonexistent_session(store):
    assert store.get_session("nope") is None


def test_update_session_fields(store):
    from switchyard.models import Session
    s = Session(id="s1", name="test", pack="echo", status="created",
                config={}, created_at="2026-01-01T00:00:00Z")
    store.create_session(s)
    store.update_session("s1", status="running")
    got = store.get_session("s1")
    assert got.status == "running"
    assert got.name == "test"  # unchanged


def test_update_session_rejects_invalid_status(store):
    from switchyard.models import Session
    s = Session(id="s1", name="t", pack="e", status="created",
                config={}, created_at="2026-01-01T00:00:00Z")
    store.create_session(s)
    with pytest.raises(ValueError):
        store.update_session("s1", status="invalid_status")


def test_list_sessions(store):
    from switchyard.models import Session
    for i in range(3):
        store.create_session(Session(
            id=f"s{i}", name=f"run-{i}", pack="echo", status="created",
            config={}, created_at="2026-01-01T00:00:00Z"))
    assert len(store.list_sessions()) == 3


# --- State Store: Tasks ---

def test_create_and_get_task(store):
    from switchyard.models import Session, Task
    store.create_session(Session(id="s1", name="t", pack="e",
                                 status="created", config={},
                                 created_at="2026-01-01T00:00:00Z"))
    task = Task(id="001", session_id="s1", title="Fix bug",
                status="intake", depends_on=["002"],
                anti_affinity=["003"], exec_order=1,
                created_at="2026-01-01T00:00:00Z")
    store.create_task(task)
    got = store.get_task("s1", "001")
    assert got.title == "Fix bug"
    assert got.depends_on == ["002"]
    assert got.anti_affinity == ["003"]


def test_list_tasks_with_status_filter(store):
    from switchyard.models import Session, Task
    store.create_session(Session(id="s1", name="t", pack="e",
                                 status="created", config={},
                                 created_at="2026-01-01T00:00:00Z"))
    for i, st in enumerate(["ready", "ready", "active", "done"]):
        store.create_task(Task(
            id=f"{i:03d}", session_id="s1", title=f"task-{i}",
            status=st, depends_on=[], anti_affinity=[], exec_order=0,
            created_at="2026-01-01T00:00:00Z"))
    assert len(store.list_tasks("s1", status="ready")) == 2
    assert len(store.list_tasks("s1")) == 4


def test_update_task_fields(store):
    from switchyard.models import Session, Task
    store.create_session(Session(id="s1", name="t", pack="e",
                                 status="created", config={},
                                 created_at="2026-01-01T00:00:00Z"))
    store.create_task(Task(id="001", session_id="s1", title="x",
                           status="ready", depends_on=[], anti_affinity=[],
                           exec_order=0, created_at="2026-01-01T00:00:00Z"))
    store.update_task("s1", "001", status="active", worker_slot=2)
    got = store.get_task("s1", "001")
    assert got.status == "active"
    assert got.worker_slot == 2


# --- State Store: Worker Slots ---

def test_create_and_get_worker_slots(store):
    from switchyard.models import Session
    store.create_session(Session(id="s1", name="t", pack="e",
                                 status="created", config={},
                                 created_at="2026-01-01T00:00:00Z"))
    store.create_worker_slots("s1", 4)
    slots = store.get_worker_slots("s1")
    assert len(slots) == 4
    assert all(s.status == "idle" for s in slots)
    assert [s.slot_number for s in slots] == [0, 1, 2, 3]


def test_update_worker_slot(store):
    from switchyard.models import Session
    store.create_session(Session(id="s1", name="t", pack="e",
                                 status="created", config={},
                                 created_at="2026-01-01T00:00:00Z"))
    store.create_worker_slots("s1", 2)
    store.update_worker_slot("s1", 0, status="active", current_task_id="001")
    slots = store.get_worker_slots("s1")
    assert slots[0].status == "active"
    assert slots[0].current_task_id == "001"
    assert slots[1].status == "idle"


# --- State Store: Events ---

def test_add_and_list_events(store):
    from switchyard.models import Session, Event
    store.create_session(Session(id="s1", name="t", pack="e",
                                 status="created", config={},
                                 created_at="2026-01-01T00:00:00Z"))
    for i in range(5):
        store.add_event(Event(
            session_id="s1", timestamp=f"2026-01-01T00:0{i}:00Z",
            event_type="dispatch", task_id=f"{i:03d}",
            message=f"Dispatched task {i}"))
    events = store.list_events("s1", limit=3)
    assert len(events) == 3


# --- Session directories ---

def test_create_session_dirs(tmp_path, monkeypatch):
    from switchyard import config
    from switchyard.state import create_session_dirs
    monkeypatch.setattr(config, "SESSIONS_DIR", str(tmp_path / "sessions"))
    os.makedirs(tmp_path / "sessions")
    root = create_session_dirs("sess-001")
    for subdir in ["intake", "claimed", "staging", "review", "ready",
                   "workers", "done", "blocked", "logs", "logs/workers"]:
        assert (root / subdir).is_dir(), f"Missing: {subdir}"


def test_create_session_dirs_idempotent(tmp_path, monkeypatch):
    from switchyard import config
    from switchyard.state import create_session_dirs
    monkeypatch.setattr(config, "SESSIONS_DIR", str(tmp_path / "sessions"))
    os.makedirs(tmp_path / "sessions")
    root1 = create_session_dirs("sess-001")
    root2 = create_session_dirs("sess-001")
    assert root1 == root2
```
