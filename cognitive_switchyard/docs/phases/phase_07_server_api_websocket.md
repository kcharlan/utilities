# Phase 7: FastAPI Server, REST API, and WebSocket

## Spec

Build the FastAPI server with all REST endpoints and the WebSocket handler for real-time state broadcasting. The server serves the embedded React SPA (Phase 8), but this phase focuses on the API layer. Use a placeholder HTML page for `GET /`.

### Dependencies from prior phases

- `switchyard/models.py` — All dataclasses.
- `switchyard/config.py` — Path constants, `load_config()`, `save_config()`.
- `switchyard/state.py` — `StateStore`, `create_session_dirs()`.
- `switchyard/pack_loader.py` — `load_pack()`, `list_packs()`, `check_executable_bits()`, `run_preflight()`.
- `switchyard/scheduler.py` — `load_constraint_graph()`.
- `switchyard/orchestrator.py` — `Orchestrator`.

### Files to create

**`switchyard/server.py`** — FastAPI app, routes, WebSocket handler:

**App setup:**
- `app = FastAPI()` with lifespan handler.
- On startup: open StateStore (store instance accessible to routes). On shutdown: close store.
- The orchestrator runs in a background thread, started when a session is started via `POST /api/sessions/{id}/start`.

**REST endpoints (all return JSON):**

| Method | Path | Behavior |
|--------|------|----------|
| `GET /` | Serve the React SPA HTML string (placeholder for Phase 8: `<h1>Cognitive Switchyard</h1>`) |
| `GET /api/packs` | Return `list_packs()` serialized. Each entry: `{name, description, version, phases, timeouts}`. |
| `GET /api/packs/{name}` | Return full pack config. 404 if not found. |
| `POST /api/sessions` | Body: `{name, pack, config: {workers, planners, ...}}`. Creates session + dirs. Returns session object. |
| `GET /api/sessions` | List all sessions. |
| `GET /api/sessions/{id}` | Session detail + current state. 404 if not found. |
| `POST /api/sessions/{id}/start` | Run executable-bit + preflight checks. If pass: scan intake, create tasks, launch orchestrator in background thread. Returns `{status: "started"}` or `{status: "failed", errors: [...]}`. |
| `POST /api/sessions/{id}/pause` | Call `orchestrator.pause()`. |
| `POST /api/sessions/{id}/resume` | Call `orchestrator.resume()`. |
| `POST /api/sessions/{id}/abort` | Call `orchestrator.abort()`. |
| `GET /api/sessions/{id}/tasks` | Task list with status and constraints. Optional query param `?status=ready`. |
| `GET /api/sessions/{id}/tasks/{tid}` | Task detail. |
| `GET /api/sessions/{id}/tasks/{tid}/log` | Read log file content. Query params: `?offset=0&limit=200` for pagination. Returns `{lines: [...], total_lines: int}`. |
| `POST /api/sessions/{id}/tasks/{tid}/retry` | Move task from `blocked/` back to `ready/`. Reset status. |
| `GET /api/sessions/{id}/dag` | Read and return `resolution.json`. 404 if no resolution. |
| `GET /api/sessions/{id}/intake` | List files in intake directory: `[{name, size_bytes, detected_at}]`. |
| `GET /api/sessions/{id}/open-intake` | Open intake dir in OS file manager. Returns 204. |
| `GET /api/sessions/{id}/reveal-file?path=<relative>` | Reveal file in OS file manager. Validates path is within session dir (no traversal: reject `..`). Returns 204. |
| `DELETE /api/sessions/{id}` | Purge completed session. 409 if active. |
| `DELETE /api/sessions` | Purge all completed sessions. Returns `{deleted: int}`. |
| `GET /api/settings` | Return current global settings. |
| `PUT /api/settings` | Update global settings. Body is partial — merges with existing. |

**Path traversal protection** for `reveal-file`: resolve the full path, confirm it starts with the session directory. Return 400 if traversal detected.

**WebSocket handler — `ws://localhost:<port>/ws`:**

**`ConnectionManager` class:**
- `active_connections: list[WebSocket]`
- `log_subscriptions: dict[int, set[WebSocket]]` — slot → subscribers
- `connect(ws)` / `disconnect(ws)`
- `broadcast(message: dict)` — Send to all connections.
- `send_to_slot_subscribers(slot: int, message: dict)` — Send log lines to subscribers of a specific slot.

**Client messages (JSON):**
- `{"type": "subscribe_logs", "worker_slot": 0}` — Subscribe to log streaming for slot.
- `{"type": "unsubscribe_logs", "worker_slot": 0}` — Unsubscribe.

**Server messages (JSON) — pushed via the orchestrator's `broadcast_fn`:**
- `state_update` — Full state snapshot (pipeline counts, worker states).
- `log_line` — Single log line for a worker slot.
- `task_status_change` — Task moved between statuses.
- `progress_detail` — Detail progress text update.
- `alert` — Warning/error notification.

The orchestrator's `broadcast_fn` is wired to `ConnectionManager.broadcast()` when the server starts a session.

**Port selection:**
- Use `find_free_port(start_port)` from `switchyard/config.py` (add this function there).
- Default start port: 8100.
- Log a warning if the resolved port differs from requested.

## Acceptance tests

```python
"""tests/test_phase07_server_api_websocket.py"""
import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    """Set up isolated environment and return the FastAPI test client."""
    from switchyard import config

    home = tmp_path / ".switchyard"
    home.mkdir()
    monkeypatch.setattr(config, "SWITCHYARD_HOME", str(home))
    monkeypatch.setattr(config, "PACKS_DIR", str(home / "packs"))
    monkeypatch.setattr(config, "SESSIONS_DIR", str(home / "sessions"))
    monkeypatch.setattr(config, "DB_PATH", str(home / "test.db"))
    monkeypatch.setattr(config, "CONFIG_PATH", str(home / "config.yaml"))
    (home / "packs").mkdir()
    (home / "sessions").mkdir()

    # Copy test-echo pack
    src = Path(__file__).parent.parent / "switchyard" / "builtin_packs" / "test-echo"
    if src.exists():
        shutil.copytree(str(src), str(home / "packs" / "test-echo"))

    from switchyard.server import create_app
    app = create_app()
    client = TestClient(app)
    return client, home


# --- Packs ---

def test_list_packs(app_env):
    client, _ = app_env
    r = client.get("/api/packs")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    names = [p["name"] for p in data]
    assert "test-echo" in names


def test_get_pack_detail(app_env):
    client, _ = app_env
    r = client.get("/api/packs/test-echo")
    assert r.status_code == 200
    assert r.json()["name"] == "test-echo"


def test_get_pack_not_found(app_env):
    client, _ = app_env
    r = client.get("/api/packs/nonexistent")
    assert r.status_code == 404


# --- Sessions ---

def test_create_session(app_env):
    client, home = app_env
    r = client.post("/api/sessions", json={
        "name": "test-run", "pack": "test-echo", "config": {"workers": 2}})
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "test-run"
    assert data["status"] == "created"
    # Session directory was created
    session_dir = home / "sessions" / data["id"]
    assert (session_dir / "intake").is_dir()


def test_list_sessions(app_env):
    client, _ = app_env
    client.post("/api/sessions", json={"name": "s1", "pack": "test-echo", "config": {}})
    client.post("/api/sessions", json={"name": "s2", "pack": "test-echo", "config": {}})
    r = client.get("/api/sessions")
    assert len(r.json()) == 2


def test_get_session_not_found(app_env):
    client, _ = app_env
    r = client.get("/api/sessions/nonexistent")
    assert r.status_code == 404


def test_delete_active_session_returns_409(app_env):
    client, _ = app_env
    r = client.post("/api/sessions", json={"name": "s1", "pack": "test-echo", "config": {}})
    sid = r.json()["id"]
    # Session is in "created" status — simulate it being "running"
    from switchyard.server import get_store
    get_store().update_session(sid, status="running")
    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 409


# --- Tasks ---

def test_get_tasks_for_session(app_env):
    client, home = app_env
    r = client.post("/api/sessions", json={"name": "s1", "pack": "test-echo", "config": {}})
    sid = r.json()["id"]
    # Add intake files
    session_dir = home / "sessions" / sid
    (session_dir / "intake" / "001.md").write_text("# Task 1\n")

    r = client.get(f"/api/sessions/{sid}/tasks")
    assert r.status_code == 200


# --- Intake ---

def test_list_intake_files(app_env):
    client, home = app_env
    r = client.post("/api/sessions", json={"name": "s1", "pack": "test-echo", "config": {}})
    sid = r.json()["id"]
    session_dir = home / "sessions" / sid
    (session_dir / "intake" / "task1.md").write_text("# Task 1\n")
    (session_dir / "intake" / "task2.md").write_text("# Task 2\n")

    r = client.get(f"/api/sessions/{sid}/intake")
    assert r.status_code == 200
    files = r.json()
    assert len(files) == 2


# --- Settings ---

def test_get_and_update_settings(app_env):
    client, _ = app_env
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert r.json()["retention_days"] == 30

    r = client.put("/api/settings", json={"retention_days": 7})
    assert r.status_code == 200

    r = client.get("/api/settings")
    assert r.json()["retention_days"] == 7
    assert r.json()["default_workers"] == 3  # unchanged default


# --- Path traversal ---

def test_reveal_file_rejects_traversal(app_env):
    client, _ = app_env
    r = client.post("/api/sessions", json={"name": "s1", "pack": "test-echo", "config": {}})
    sid = r.json()["id"]
    r = client.get(f"/api/sessions/{sid}/reveal-file?path=../../etc/passwd")
    assert r.status_code == 400


# --- DAG ---

def test_get_dag_no_resolution(app_env):
    client, _ = app_env
    r = client.post("/api/sessions", json={"name": "s1", "pack": "test-echo", "config": {}})
    sid = r.json()["id"]
    r = client.get(f"/api/sessions/{sid}/dag")
    assert r.status_code == 404


def test_get_dag_with_resolution(app_env):
    client, home = app_env
    r = client.post("/api/sessions", json={"name": "s1", "pack": "test-echo", "config": {}})
    sid = r.json()["id"]
    session_dir = home / "sessions" / sid
    graph = {"tasks": [{"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 1}]}
    (session_dir / "resolution.json").write_text(json.dumps(graph))
    r = client.get(f"/api/sessions/{sid}/dag")
    assert r.status_code == 200
    assert len(r.json()["tasks"]) == 1


# --- WebSocket ---

def test_websocket_connect_and_receive(app_env):
    client, _ = app_env
    with client.websocket_connect("/ws") as ws:
        # Server should accept the connection without error
        # We can't easily test broadcasting without a running orchestrator,
        # but we can verify the connection works
        ws.send_json({"type": "subscribe_logs", "worker_slot": 0})
        # No crash = success for basic connectivity


# --- Retry blocked task ---

def test_retry_blocked_task(app_env):
    client, home = app_env
    r = client.post("/api/sessions", json={"name": "s1", "pack": "test-echo", "config": {}})
    sid = r.json()["id"]
    session_dir = home / "sessions" / sid

    from switchyard.server import get_store
    from switchyard.models import Task
    store = get_store()
    store.create_task(Task(id="001", session_id=sid, title="broken",
                           status="blocked", depends_on=[], anti_affinity=[],
                           exec_order=0, created_at="2026-01-01T00:00:00Z"))
    # Put the plan file in blocked/
    (session_dir / "blocked" / "001.plan.md").write_text("# Task\n")

    r = client.post(f"/api/sessions/{sid}/tasks/001/retry")
    assert r.status_code == 200

    task = store.get_task(sid, "001")
    assert task.status == "ready"
    assert (session_dir / "ready" / "001.plan.md").exists()
```
