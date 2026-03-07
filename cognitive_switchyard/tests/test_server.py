from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from cognitive_switchyard.config import SessionConfig, session_dir, session_subdirs
from cognitive_switchyard.models import Session, SessionStatus, Task, TaskStatus
from cognitive_switchyard.server import app
from cognitive_switchyard.state import StateStore


def _client_env(tmp_path, monkeypatch):
    home = tmp_path / ".cognitive_switchyard"
    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("cognitive_switchyard.config.SESSIONS_DIR", home / "sessions")
    monkeypatch.setattr("cognitive_switchyard.config.PACKS_DIR", home / "packs")
    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_DB", home / "cognitive_switchyard.db")
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.SESSIONS_DIR", home / "sessions")
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.PACKS_DIR", home / "packs")
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.SWITCHYARD_DB", home / "cognitive_switchyard.db")
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.BUILTIN_PACKS_DIR", Path(__file__).resolve().parent.parent / "packs")
    return home


def test_index(tmp_path, monkeypatch) -> None:
    _client_env(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "COGNITIVE SWITCHYARD" in response.text
        assert "ReactDOM" in response.text


def test_list_packs(tmp_path, monkeypatch) -> None:
    _client_env(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/packs")
        assert response.status_code == 200
        data = response.json()
        assert any(pack["name"] == "test-echo" for pack in data)
        detail = client.get("/api/packs/test-echo")
        assert detail.status_code == 200
        assert detail.json()["phases"]["execution"]["executor"] == "shell"


def test_pack_preflight(tmp_path, monkeypatch) -> None:
    _client_env(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/packs/test-echo/preflight")
        assert response.status_code == 200
        assert response.json()["ok"] is True


def test_settings_round_trip(tmp_path, monkeypatch) -> None:
    _client_env(tmp_path, monkeypatch)
    with TestClient(app) as client:
        assert client.put("/api/settings", json={"retention_days": 14, "default_workers": 3}).status_code == 200
        response = client.get("/api/settings")
        assert response.status_code == 200
        assert response.json()["retention_days"] == 14
        assert response.json()["default_workers"] == 3


def test_session_create_and_get(tmp_path, monkeypatch) -> None:
    _client_env(tmp_path, monkeypatch)
    with TestClient(app) as client:
        create = client.post("/api/sessions", json={"pack_name": "test-echo", "name": "API Session"})
        assert create.status_code == 200
        session_id = create.json()["session_id"]

        get_response = client.get(f"/api/sessions/{session_id}")
        assert get_response.status_code == 200
        payload = get_response.json()
        assert payload["session"]["name"] == "API Session"
        assert payload["pipeline"]["ready"] == 0
        assert payload["paths"]["intake"].endswith("/intake")


def test_tasks_dashboard_dag_and_retry(tmp_path, monkeypatch) -> None:
    home = _client_env(tmp_path, monkeypatch)
    with TestClient(app) as client:
        session_id = client.post("/api/sessions", json={"pack_name": "test-echo", "name": "Task API"}).json()["session_id"]
        store: StateStore = app.state.sync_store
        dirs = session_subdirs(session_id)
        (dirs["blocked"] / "001_blocked.plan.md").write_text("---\nPLAN_ID: 001\n---\n# Plan 001: Blocked\n")
        (dirs["blocked"] / "001_blocked.status").write_text("STATUS: blocked\nBLOCKED_REASON: needs retry\n")
        (session_dir(session_id) / "resolution.json").write_text(json.dumps({"tasks": [{"task_id": "001"}], "groups": [], "conflicts": [], "notes": ""}))
        store.create_task(
            Task(
                id="001",
                session_id=session_id,
                title="Blocked",
                status=TaskStatus.BLOCKED,
                plan_filename="001_blocked.plan.md",
                created_at=datetime.now(timezone.utc),
            )
        )

        assert client.get(f"/api/sessions/{session_id}/tasks").status_code == 200
        task_detail = client.get(f"/api/sessions/{session_id}/tasks/001").json()
        assert task_detail["status"] == "blocked"
        assert task_detail["status_sidecar"]["blocked_reason"] == "needs retry"
        assert client.get(f"/api/sessions/{session_id}/dag").json()["tasks"][0]["task_id"] == "001"
        dashboard = client.get(f"/api/sessions/{session_id}/dashboard")
        assert dashboard.status_code == 200
        assert "workers" in dashboard.json()

        retry = client.post(f"/api/sessions/{session_id}/tasks/001/retry")
        assert retry.status_code == 200
        assert (dirs["ready"] / "001_blocked.plan.md").exists()


def test_task_log_and_intake_listing(tmp_path, monkeypatch) -> None:
    _client_env(tmp_path, monkeypatch)
    with TestClient(app) as client:
        session_id = client.post("/api/sessions", json={"pack_name": "test-echo"}).json()["session_id"]
        dirs = session_subdirs(session_id)
        (dirs["intake"] / "001_note.md").write_text("hello\n")
        (dirs["logs"] / "001_note.log").write_text("line one\nline two\n")
        store: StateStore = app.state.sync_store
        store.create_task(
            Task(
                id="001",
                session_id=session_id,
                title="Note",
                status=TaskStatus.INTAKE,
                created_at=datetime.now(timezone.utc),
            )
        )

        intake = client.get(f"/api/sessions/{session_id}/intake")
        assert intake.status_code == 200
        assert any(entry["name"] == "001_note.md" for entry in intake.json())

        log_resp = client.get(f"/api/sessions/{session_id}/tasks/001/log")
        assert log_resp.status_code == 200
        assert "line one" in log_resp.json()["content"]


def test_open_and_reveal_file(tmp_path, monkeypatch) -> None:
    _client_env(tmp_path, monkeypatch)
    called: list[list[str]] = []

    class DummyPopen:
        def __init__(self, cmd, *args, **kwargs):
            called.append(cmd)

    monkeypatch.setattr("cognitive_switchyard.server.subprocess.Popen", DummyPopen)
    with TestClient(app) as client:
        session_id = client.post("/api/sessions", json={"pack_name": "test-echo"}).json()["session_id"]
        intake_open = client.get(f"/api/sessions/{session_id}/open-intake")
        assert intake_open.status_code == 204

        target = session_subdirs(session_id)["intake"] / "001_note.md"
        target.write_text("hello")
        reveal = client.get(
            f"/api/sessions/{session_id}/reveal-file",
            params={"path": str(target.relative_to(session_dir(session_id)))},
        )
        assert reveal.status_code == 204
        assert called[0][0] == "open"
        assert called[1][:2] == ["open", "-R"]


def test_retention_purge_runs_on_startup(tmp_path, monkeypatch) -> None:
    home = _client_env(tmp_path, monkeypatch)
    store = StateStore(db_path=home / "cognitive_switchyard.db")
    store.connect()
    session_id = "old-session"
    store.create_session(
        Session(
            id=session_id,
            name="Old Session",
            pack_name="test-echo",
            config_json=json.dumps(SessionConfig(pack_name="test-echo", session_name="Old").__dict__),
            status=SessionStatus.COMPLETED,
            created_at=datetime.now(timezone.utc),
        )
    )
    store.update_session_status(
        session_id,
        SessionStatus.COMPLETED,
        completed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    session_subdirs(session_id)["intake"].mkdir(parents=True, exist_ok=True)
    store.close()

    config_path = home / "config.yaml"
    config_path.write_text("retention_days: 30\ndefault_planners: 1\ndefault_workers: 1\ndefault_pack: test-echo\n")

    with TestClient(app) as client:
        response = client.get("/api/sessions")
        assert response.status_code == 200
        assert all(entry["session"]["id"] != session_id for entry in response.json())


def test_pause_resume_abort_delete_and_purge(tmp_path, monkeypatch) -> None:
    _client_env(tmp_path, monkeypatch)
    with TestClient(app) as client:
        session_id = client.post("/api/sessions", json={"pack_name": "test-echo"}).json()["session_id"]
        assert client.post(f"/api/sessions/{session_id}/pause").status_code == 200
        assert client.post(f"/api/sessions/{session_id}/resume").status_code == 200
        assert client.post(f"/api/sessions/{session_id}/abort").status_code == 200
        assert client.delete(f"/api/sessions/{session_id}").status_code == 200

        second_id = client.post("/api/sessions", json={"pack_name": "test-echo"}).json()["session_id"]
        store: StateStore = app.state.sync_store
        store.update_session_status(second_id, SessionStatus.COMPLETED, completed_at=datetime.now(timezone.utc))
        purge = client.delete("/api/sessions")
        assert purge.status_code == 200
        assert purge.json()["purged"] >= 1


def test_start_endpoint_launches_orchestrator(tmp_path, monkeypatch) -> None:
    _client_env(tmp_path, monkeypatch)
    started: list[str] = []

    class DummyOrchestrator:
        def __init__(self, session_id, store, event_loop=None, ws_broadcast=None):
            self.session_id = session_id

        def start_background(self):
            started.append(self.session_id)

        def stop(self):
            return None

    monkeypatch.setattr("cognitive_switchyard.server.Orchestrator", DummyOrchestrator)
    with TestClient(app) as client:
        session_id = client.post("/api/sessions", json={"pack_name": "test-echo"}).json()["session_id"]
        response = client.post(f"/api/sessions/{session_id}/start")
        assert response.status_code == 200
        assert started == [session_id]
