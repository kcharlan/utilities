# Phase 09: FastAPI Server, REST API, and WebSocket

**Design doc:** `docs/cognitive_switchyard_design.md` (Sections 6.5, 6.6, 7.1, 7.5)

## Spec

Build the FastAPI server with all REST endpoints, WebSocket manager for live updates, and the file-system watcher for intake directory changes. The server serves the embedded React SPA (Phase 10) at `/` and provides the API backend.

### Files to create

- `switchyard/server.py` — FastAPI app, all routes, WebSocket handler, lifespan
- `switchyard/watcher.py` — File system watcher for intake directory

### Dependencies from prior phases

- `switchyard/state.py` — all async DB functions
- `switchyard/pack_loader.py` — `list_packs`, `load_pack`, `validate_pack`, `check_executable_bits`, `run_preflight`
- `switchyard/orchestrator.py` — `Orchestrator` class
- `switchyard/config.py` — path constants, `load_config`, `save_config`
- `switchyard/models.py` — dataclasses
- `switchyard/html_template.py` — `get_html()` function (Phase 10; for this phase, stub it with a placeholder HTML string)

### Server setup

- FastAPI app with lifespan handler (not deprecated `@app.on_event`).
- On startup: call `init_db()`, initialize connection manager.
- Port selection: use `find_free_port(start_port)` pattern from CLAUDE.md. Default start port: 8200.
- The `serve` CLI subcommand (registered in Phase 08) calls `uvicorn.run(app, host="127.0.0.1", port=port)`.
- Auto-open browser on startup (background thread, after server is listening).

### REST API endpoints

All endpoints from design doc Section 6.6:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serve the React SPA HTML |
| GET | `/api/packs` | List available packs (`list_packs()`) |
| GET | `/api/packs/{name}` | Pack details (full pack.yaml content) |
| POST | `/api/sessions` | Create a new session. Body: `{name, pack, config}`. Creates DB row + session dirs. Returns session object. |
| GET | `/api/sessions` | List all sessions |
| GET | `/api/sessions/{id}` | Session details + current state |
| POST | `/api/sessions/{id}/start` | Run preflight checks, snapshot intake, begin orchestration. Returns 400 if preflight fails. |
| POST | `/api/sessions/{id}/pause` | Pause dispatch |
| POST | `/api/sessions/{id}/resume` | Resume dispatch |
| POST | `/api/sessions/{id}/abort` | Abort session |
| GET | `/api/sessions/{id}/tasks` | Task list with status and constraints |
| GET | `/api/sessions/{id}/tasks/{tid}` | Task detail |
| GET | `/api/sessions/{id}/tasks/{tid}/log` | Task log content. Query params: `offset` (line number), `limit` (max lines). |
| GET | `/api/sessions/{id}/dag` | Constraint graph JSON (read `resolution.json`) |
| GET | `/api/sessions/{id}/dashboard` | Dashboard summary: pipeline counts, worker states, elapsed time |
| POST | `/api/sessions/{id}/tasks/{tid}/retry` | Re-queue a blocked task to ready/ |
| GET | `/api/sessions/{id}/intake` | List intake directory contents |
| GET | `/api/sessions/{id}/open-intake` | Open intake dir in OS file manager. Returns 204. |
| GET | `/api/sessions/{id}/reveal-file` | Reveal file in OS file manager. Query param: `path` (relative to session dir). Returns 204. Validates path is within session dir (no traversal). |
| DELETE | `/api/sessions/{id}` | Purge completed session. Returns 409 if active. |
| DELETE | `/api/sessions` | Purge all completed sessions. Returns `{deleted: N}`. |
| GET | `/api/settings` | Current global settings |
| PUT | `/api/settings` | Update global settings |

### Path traversal protection

`reveal-file` must validate that the resolved path is within the session directory. Use `Path.resolve()` and check that it starts with the session directory path. Return 400 if traversal detected.

### WebSocket manager (`ConnectionManager`)

- `active_connections: list[WebSocket]`
- `log_subscriptions: dict[int, set[WebSocket]]` — slot number → subscribers
- `connect(ws)` / `disconnect(ws)` — Manage connection lifecycle.
- `broadcast_state(state: dict)` — Push state update to all clients.
- `send_log_line(slot: int, line: str, timestamp: str)` — Push to slot subscribers.
- `broadcast_alert(alert: dict)` — Push to all clients.

Client messages:
- `{"type": "subscribe_logs", "worker_slot": 0}` — Subscribe to a slot's logs.
- `{"type": "unsubscribe_logs", "worker_slot": 0}` — Unsubscribe.

The orchestrator's `on_event` callback is wired to the connection manager to push real-time updates.

### File system watcher (`watcher.py`)

- `IntakeWatcher` class. Constructor takes `intake_dir: Path`, `poll_interval: float = 2.0`.
- `check() -> list[dict]` — Return list of new files since last check. Each entry: `{"filename": str, "size": int, "detected_at": str}`.
- Uses `watchfiles` if available, falls back to polling with `os.listdir()` comparison.

## Acceptance tests

```python
# tests/test_phase09_server_api_websocket.py
import asyncio
import json
import os
import yaml
import stat
import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from switchyard.config import ensure_dirs
from switchyard.state import init_db, create_session, create_task, create_session_dirs
from switchyard.models import Session, Task


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
    # Create a test pack
    pack_dir = home / "packs" / "test-echo"
    pack_dir.mkdir(parents=True)
    (pack_dir / "scripts").mkdir()
    execute = pack_dir / "scripts" / "execute.sh"
    execute.write_text("#!/bin/bash\necho ok\n")
    execute.chmod(execute.stat().st_mode | stat.S_IEXEC)
    config = {"name": "test-echo", "description": "Test", "version": "1.0.0",
              "phases": {"execution": {"enabled": True, "executor": "shell", "command": "scripts/execute.sh"}},
              "isolation": {"type": "none"}}
    (pack_dir / "pack.yaml").write_text(yaml.dump(config))


@pytest.fixture
async def setup_db():
    await init_db()


@pytest.fixture
def client(setup_db):
    from switchyard.server import app
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# --- Pack endpoints ---

@pytest.mark.asyncio
async def test_list_packs(client):
    async with client as c:
        resp = await c.get("/api/packs")
        assert resp.status_code == 200
        packs = resp.json()
        assert any(p["name"] == "test-echo" for p in packs)


@pytest.mark.asyncio
async def test_get_pack_detail(client):
    async with client as c:
        resp = await c.get("/api/packs/test-echo")
        assert resp.status_code == 200
        assert resp.json()["name"] == "test-echo"


@pytest.mark.asyncio
async def test_get_nonexistent_pack(client):
    async with client as c:
        resp = await c.get("/api/packs/nonexistent")
        assert resp.status_code == 404


# --- Session endpoints ---

@pytest.mark.asyncio
async def test_create_session(client):
    async with client as c:
        resp = await c.post("/api/sessions", json={"name": "test-run", "pack": "test-echo", "config": {"workers": 2}})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test-run"
        assert data["status"] == "created"


@pytest.mark.asyncio
async def test_list_sessions(client):
    async with client as c:
        await c.post("/api/sessions", json={"name": "run-1", "pack": "test-echo", "config": {}})
        resp = await c.get("/api/sessions")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_delete_active_session_returns_409(client):
    async with client as c:
        resp = await c.post("/api/sessions", json={"name": "active-run", "pack": "test-echo", "config": {}})
        sid = resp.json()["id"]
        # Session is "created", not "completed" — depends on your definition of "active"
        # But running sessions must return 409
        from switchyard.state import update_session
        await update_session(sid, status="running")
        resp = await c.delete(f"/api/sessions/{sid}")
        assert resp.status_code == 409


# --- Settings endpoints ---

@pytest.mark.asyncio
async def test_get_settings(client):
    async with client as c:
        resp = await c.get("/api/settings")
        assert resp.status_code == 200
        assert "retention_days" in resp.json()


@pytest.mark.asyncio
async def test_update_settings(client):
    async with client as c:
        resp = await c.put("/api/settings", json={"retention_days": 7, "default_workers": 5, "default_planners": 2, "default_pack": ""})
        assert resp.status_code == 200
        resp = await c.get("/api/settings")
        assert resp.json()["retention_days"] == 7


# --- Path traversal protection ---

@pytest.mark.asyncio
async def test_reveal_file_rejects_traversal(client):
    async with client as c:
        resp = await c.post("/api/sessions", json={"name": "sec-test", "pack": "test-echo", "config": {}})
        sid = resp.json()["id"]
        resp = await c.get(f"/api/sessions/{sid}/reveal-file", params={"path": "../../etc/passwd"})
        assert resp.status_code == 400


# --- Dashboard ---

@pytest.mark.asyncio
async def test_dashboard_returns_pipeline_counts(client):
    async with client as c:
        resp = await c.post("/api/sessions", json={"name": "dash-test", "pack": "test-echo", "config": {}})
        sid = resp.json()["id"]
        resp = await c.get(f"/api/sessions/{sid}/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "pipeline" in data


# --- SPA root ---

@pytest.mark.asyncio
async def test_root_serves_html(client):
    async with client as c:
        resp = await c.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


# --- Intake watcher ---

def test_intake_watcher_detects_new_files(tmp_path):
    from switchyard.watcher import IntakeWatcher
    intake_dir = tmp_path / "intake"
    intake_dir.mkdir()
    watcher = IntakeWatcher(intake_dir)
    assert watcher.check() == []
    (intake_dir / "task1.md").write_text("# Task 1")
    new_files = watcher.check()
    assert len(new_files) == 1
    assert new_files[0]["filename"] == "task1.md"


def test_intake_watcher_does_not_report_same_file_twice(tmp_path):
    from switchyard.watcher import IntakeWatcher
    intake_dir = tmp_path / "intake"
    intake_dir.mkdir()
    watcher = IntakeWatcher(intake_dir)
    (intake_dir / "task1.md").write_text("# Task 1")
    watcher.check()
    assert watcher.check() == []  # already reported
```
