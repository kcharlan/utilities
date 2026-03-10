from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent

from fastapi.testclient import TestClient

from cognitive_switchyard.cli import main
from cognitive_switchyard.config import GlobalConfig, build_runtime_paths, write_global_config
from cognitive_switchyard.models import BackendRuntimeEvent, PackManifest, TaskPlan
from cognitive_switchyard.pack_loader import load_pack_manifest
from cognitive_switchyard.server import create_app
from cognitive_switchyard.state import StateStore, initialize_state_store


def _build_store(tmp_path: Path) -> tuple[StateStore, object]:
    runtime_paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(runtime_paths)
    return store, runtime_paths


def _write_runtime_pack(runtime_paths, *, name: str = "claude-code") -> PackManifest:
    pack_root = runtime_paths.packs / name
    scripts_dir = pack_root / "scripts"
    prompts_dir = pack_root / "prompts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    execute_path = scripts_dir / "execute"
    execute_path.write_text(
        dedent(
            """
            #!/usr/bin/env python3
            import sys
            from pathlib import Path

            task_path = Path(sys.argv[1])
            task_id = task_path.name.removesuffix(".plan.md")
            print(f"##PROGRESS## {task_id} | Phase: Execute | 1/1")
            status_path = task_path.with_name(task_id + ".status")
            status_path.write_text(
                "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
                encoding="utf-8",
            )
            """
        ).lstrip(),
        encoding="utf-8",
    )
    execute_path.chmod(execute_path.stat().st_mode | 0o111)
    (prompts_dir / "planner.md").write_text("Plan prompt.\n", encoding="utf-8")
    (prompts_dir / "resolver.md").write_text("Resolve prompt.\n", encoding="utf-8")
    (pack_root / "pack.yaml").write_text(
        dedent(
            f"""
            name: {name}
            description: Packet 11 runtime pack.
            version: 1.2.3

            phases:
              planning:
                enabled: true
                executor: agent
                model: claude-sonnet
                prompt: prompts/planner.md
                max_instances: 2
              resolution:
                enabled: true
                executor: agent
                model: claude-sonnet
                prompt: prompts/resolver.md
              execution:
                enabled: true
                executor: shell
                command: scripts/execute
                max_workers: 2
              verification:
                enabled: false

            timeouts:
              task_idle: 300
              task_max: 0
              session_max: 14400

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return load_pack_manifest(pack_root)


def _write_preflight_runtime_pack(runtime_paths, *, name: str = "claude-code") -> PackManifest:
    pack_root = runtime_paths.packs / name
    scripts_dir = pack_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    execute_path = scripts_dir / "execute"
    execute_path.write_text(
        dedent(
            """
            #!/usr/bin/env python3
            raise SystemExit(0)
            """
        ).lstrip(),
        encoding="utf-8",
    )
    execute_path.chmod(execute_path.stat().st_mode | 0o111)
    preflight_path = scripts_dir / "preflight"
    preflight_path.write_text(
        dedent(
            """
            #!/usr/bin/env python3
            print("pack preflight ok")
            """
        ).lstrip(),
        encoding="utf-8",
    )
    preflight_path.chmod(preflight_path.stat().st_mode | 0o111)
    (pack_root / "pack.yaml").write_text(
        dedent(
            f"""
            name: {name}
            description: Packet 11B preflight pack.
            version: 1.2.3

            prerequisites:
              - name: CLI available
                check: printf 'cli ok\\n'

            phases:
              resolution:
                enabled: true
                executor: passthrough
              execution:
                enabled: true
                executor: shell
                command: scripts/execute
                max_workers: 2
              verification:
                enabled: false

            timeouts:
              task_idle: 300
              task_max: 0
              session_max: 14400

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return load_pack_manifest(pack_root)


def _write_slow_runtime_pack(
    runtime_paths,
    *,
    name: str = "claude-code",
    sleep_seconds: float = 0.2,
) -> PackManifest:
    pack_root = runtime_paths.packs / name
    scripts_dir = pack_root / "scripts"
    prompts_dir = pack_root / "prompts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    execute_path = scripts_dir / "execute"
    execute_path.write_text(
        dedent(
            f"""
            #!/usr/bin/env python3
            import sys
            import time
            from pathlib import Path

            task_path = Path(sys.argv[1])
            task_id = task_path.name.removesuffix(".plan.md")
            print(f"##PROGRESS## {{task_id}} | Phase: Execute | 1/1", flush=True)
            time.sleep({sleep_seconds})
            status_path = task_path.with_name(task_id + ".status")
            status_path.write_text(
                "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
                encoding="utf-8",
            )
            """
        ).lstrip(),
        encoding="utf-8",
    )
    execute_path.chmod(execute_path.stat().st_mode | 0o111)
    (prompts_dir / "planner.md").write_text("Plan prompt.\n", encoding="utf-8")
    (prompts_dir / "resolver.md").write_text("Resolve prompt.\n", encoding="utf-8")
    (pack_root / "pack.yaml").write_text(
        dedent(
            f"""
            name: {name}
            description: Packet 11 slow runtime pack.
            version: 1.2.3

            phases:
              planning:
                enabled: true
                executor: agent
                model: claude-sonnet
                prompt: prompts/planner.md
                max_instances: 1
              resolution:
                enabled: true
                executor: agent
                model: claude-sonnet
                prompt: prompts/resolver.md
              execution:
                enabled: true
                executor: shell
                command: scripts/execute
                max_workers: 1
              verification:
                enabled: false

            timeouts:
              task_idle: 300
              task_max: 0
              session_max: 14400

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return load_pack_manifest(pack_root)


def _write_fixture_runtime_pack(
    runtime_paths,
    *,
    repo_root: Path,
    fixture_name: str,
    name: str = "claude-code",
    max_workers: int = 1,
    task_idle: int = 300,
    task_max: int = 0,
    session_max: int = 14400,
) -> PackManifest:
    pack_root = runtime_paths.packs / name
    scripts_dir = pack_root / "scripts"
    prompts_dir = pack_root / "prompts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = repo_root / "tests" / "fixtures" / "workers" / fixture_name
    execute_path = scripts_dir / fixture_name
    execute_path.write_text(fixture_path.read_text(encoding="utf-8"), encoding="utf-8")
    execute_path.chmod(execute_path.stat().st_mode | 0o111)
    (prompts_dir / "planner.md").write_text("Plan prompt.\n", encoding="utf-8")
    (prompts_dir / "resolver.md").write_text("Resolve prompt.\n", encoding="utf-8")
    (pack_root / "pack.yaml").write_text(
        dedent(
            f"""
            name: {name}
            description: Packet 11 runtime fixture pack.
            version: 1.2.3

            phases:
              resolution:
                enabled: true
                executor: passthrough
              execution:
                enabled: true
                executor: shell
                command: scripts/{fixture_name}
                max_workers: {max_workers}
              verification:
                enabled: false

            timeouts:
              task_idle: {task_idle}
              task_max: {task_max}
              session_max: {session_max}

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return load_pack_manifest(pack_root)


def _register_task(
    store: StateStore,
    session_id: str,
    *,
    task_id: str,
    title: str,
    depends_on: tuple[str, ...] = (),
    anti_affinity: tuple[str, ...] = (),
    exec_order: int = 1,
    full_test_after: bool = False,
) -> None:
    store.register_task_plan(
        session_id=session_id,
        plan=TaskPlan(
            task_id=task_id,
            title=title,
            depends_on=depends_on,
            anti_affinity=anti_affinity,
            exec_order=exec_order,
            full_test_after=full_test_after,
            body=f"# Plan: {title}\n",
        ),
        plan_text=f"# Plan: {title}\n",
        created_at="2026-03-09T10:01:00Z",
    )


class FakeSessionController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def create_session(self, *, session_id: str, name: str, pack: str, config_json: str | None = None):
        self.calls.append(
            ("create_session", session_id, {"name": name, "pack": pack, "config_json": config_json})
        )
        return {"session_id": session_id}

    def start(self, session_id: str) -> None:
        self.calls.append(("start", session_id, None))

    def pause(self, session_id: str) -> None:
        self.calls.append(("pause", session_id, None))

    def resume(self, session_id: str) -> None:
        self.calls.append(("resume", session_id, None))

    def abort(self, session_id: str) -> None:
        self.calls.append(("abort", session_id, None))

    def retry_task(self, session_id: str, task_id: str) -> None:
        self.calls.append(("retry_task", session_id, task_id))


def _wait_until(predicate, *, timeout: float = 2.0, interval: float = 0.02) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition not met before timeout")


def _wait_for_websocket_message(
    websocket,
    predicate,
    *,
    max_messages: int = 32,
) -> dict[str, object]:
    seen: list[dict[str, object]] = []
    for _ in range(max_messages):
        item = websocket.receive_json()
        seen.append(item)
        if predicate(item):
            return item
    raise AssertionError(f"expected websocket message was not received; saw: {seen!r}")


def _timestamp_offset(*, seconds: int) -> str:
    return datetime.fromtimestamp(datetime.now(UTC).timestamp() + seconds, tz=UTC).isoformat().replace(
        "+00:00",
        "Z",
    )


def test_serve_command_scans_to_next_free_port_and_starts_app(tmp_path: Path, monkeypatch) -> None:
    builtin_root = tmp_path / "builtin-source"
    builtin_root.mkdir(parents=True, exist_ok=True)

    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 8100))
    occupied.listen(1)

    captured: dict[str, object] = {}

    def fake_serve_backend(*, runtime_paths, builtin_packs_root, host: str, port: int) -> int:
        captured["runtime_paths"] = runtime_paths
        captured["builtin_packs_root"] = builtin_packs_root
        captured["host"] = host
        captured["port"] = port
        return port

    monkeypatch.setattr("cognitive_switchyard.server.serve_backend", fake_serve_backend)
    try:
        exit_code = main(
            [
                "--runtime-root",
                str(tmp_path),
                "--builtin-packs-root",
                str(builtin_root),
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                "8100",
            ]
        )
    finally:
        occupied.close()

    runtime_paths = build_runtime_paths(home=tmp_path)
    assert exit_code == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8100
    assert captured["runtime_paths"] == runtime_paths
    assert captured["builtin_packs_root"] == builtin_root


def test_get_packs_and_pack_detail_serialize_runtime_manifests(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    manifest = _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    packs_response = client.get("/api/packs")
    detail_response = client.get(f"/api/packs/{manifest.name}")

    assert packs_response.status_code == 200
    assert packs_response.json() == {
        "packs": [
            {
                "name": "claude-code",
                "description": "Packet 11 runtime pack.",
                "version": "1.2.3",
                "max_workers": 2,
                "planning_enabled": True,
                "verification_enabled": False,
            }
        ]
    }
    assert detail_response.status_code == 200
    assert detail_response.json() == {
        "name": "claude-code",
        "description": "Packet 11 runtime pack.",
        "version": "1.2.3",
        "root": str(runtime_paths.packs / "claude-code"),
        "phases": {
            "planning": {
                "enabled": True,
                "executor": "agent",
                "model": "claude-sonnet",
                "prompt": str(runtime_paths.packs / "claude-code" / "prompts" / "planner.md"),
                "max_instances": 2,
            },
            "resolution": {
                "enabled": True,
                "executor": "agent",
                "model": "claude-sonnet",
                "prompt": str(runtime_paths.packs / "claude-code" / "prompts" / "resolver.md"),
                "script": None,
            },
            "execution": {
                "enabled": True,
                "executor": "shell",
                "command": str(runtime_paths.packs / "claude-code" / "scripts" / "execute"),
                "max_workers": 2,
            },
        },
        "timeouts": {"task_idle": 300, "task_max": 0, "session_max": 14400},
    }


def test_create_session_accepts_session_overrides_and_returns_effective_runtime_config(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    response = client.post(
        "/api/sessions",
        json={
            "id": "session-11c-create",
            "name": "Packet 11C create",
            "pack": "claude-code",
            "config": {
                "worker_count": 1,
                "verification_interval": 6,
                "task_idle": 25,
                "task_max": 90,
                "session_max": 600,
                "auto_fix_enabled": True,
                "auto_fix_max_attempts": 4,
                "poll_interval": 0.25,
                "environment": {"API_MODE": "setup", "TRACE_TOKEN": "abc123"},
            },
        },
    )

    assert response.status_code == 201
    payload = response.json()["session"]
    assert payload["config"] == {
        "worker_count": 1,
        "verification_interval": 6,
        "task_idle": 25,
        "task_max": 90,
        "session_max": 600,
        "auto_fix_enabled": True,
        "auto_fix_max_attempts": 4,
        "poll_interval": 0.25,
        "environment": {"API_MODE": "setup", "TRACE_TOKEN": "abc123"},
    }
    assert payload["effective_runtime_config"] == {
        "planner_count": 2,
        "worker_count": 1,
        "verification_interval": 6,
        "timeouts": {"task_idle": 25, "task_max": 90, "session_max": 600},
        "auto_fix": {"enabled": True, "max_attempts": 4},
        "poll_interval": 0.25,
        "environment": {"API_MODE": "setup", "TRACE_TOKEN": "abc123"},
    }
    assert json.loads(store.get_session("session-11c-create").config_json or "{}") == payload["config"]


def test_create_session_accepts_planner_count_override_and_returns_effective_planner_count(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    response = client.post(
        "/api/sessions",
        json={
            "id": "session-11d-create",
            "name": "Packet 11D create",
            "pack": "claude-code",
            "config": {
                "planner_count": 5,
                "worker_count": 1,
            },
        },
    )

    assert response.status_code == 201
    payload = response.json()["session"]
    assert payload["config"] == {
        "planner_count": 5,
        "worker_count": 1,
    }
    assert payload["effective_runtime_config"]["planner_count"] == 2
    assert payload["effective_runtime_config"]["worker_count"] == 1
    assert json.loads(store.get_session("session-11d-create").config_json or "{}") == payload["config"]


def test_session_dashboard_task_and_dag_endpoints_reflect_live_store_state(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-11",
        name="Packet 11 Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at="2026-03-09T10:05:00Z",
    )
    _register_task(store, session.id, task_id="001", title="Ready task", exec_order=2)
    _register_task(
        store,
        session.id,
        task_id="002",
        title="Active task",
        depends_on=("001",),
        anti_affinity=("003",),
        exec_order=1,
        full_test_after=True,
    )
    _register_task(store, session.id, task_id="003", title="Done task", exec_order=3)
    store.project_task(
        session.id,
        "002",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:06:00Z",
    )
    store.project_task(
        session.id,
        "003",
        status="done",
        timestamp="2026-03-09T10:07:00Z",
    )
    store.write_session_runtime_state(
        session.id,
        completed_since_verification=1,
        verification_pending=True,
        verification_reason="interval",
    )
    session_paths = runtime_paths.session_paths(session.id)
    session_paths.worker_log(0).parent.mkdir(parents=True, exist_ok=True)
    session_paths.worker_log(0).write_text("worker output\n", encoding="utf-8")
    session_paths.resolution.write_text(
        dedent(
            """
            {
              "resolved_at": "2026-03-09T10:05:30Z",
              "tasks": [
                {"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 2},
                {"task_id": "002", "depends_on": ["001"], "anti_affinity": ["003"], "exec_order": 1},
                {"task_id": "003", "depends_on": [], "anti_affinity": [], "exec_order": 3}
              ],
              "groups": [],
              "conflicts": [],
              "notes": "Resolved."
            }
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    sessions_response = client.get("/api/sessions")
    session_response = client.get(f"/api/sessions/{session.id}")
    tasks_response = client.get(f"/api/sessions/{session.id}/tasks")
    task_response = client.get(f"/api/sessions/{session.id}/tasks/002")
    dashboard_response = client.get(f"/api/sessions/{session.id}/dashboard")
    dag_response = client.get(f"/api/sessions/{session.id}/dag")

    assert sessions_response.status_code == 200
    assert sessions_response.json()["sessions"][0]["id"] == "session-11"
    assert session_response.status_code == 200
    assert session_response.json()["session"] == {
        "id": "session-11",
        "name": "Packet 11 Session",
        "pack": "claude-code",
        "status": "running",
        "created_at": "2026-03-09T10:00:00Z",
        "started_at": "2026-03-09T10:05:00Z",
        "completed_at": None,
        "config": {},
        "effective_runtime_config": {
            "planner_count": 2,
            "worker_count": 2,
            "verification_interval": 4,
            "timeouts": {"task_idle": 300, "task_max": 0, "session_max": 14400},
            "auto_fix": {"enabled": False, "max_attempts": 2},
            "poll_interval": 0.05,
            "environment": {},
        },
        "runtime_state": {
            "completed_since_verification": 1,
            "verification_pending": True,
            "verification_reason": "interval",
            "auto_fix_context": None,
            "auto_fix_task_id": None,
            "auto_fix_attempt": 0,
            "last_fix_summary": None,
        },
        "summary": None,
    }
    assert tasks_response.status_code == 200
    assert [task["task_id"] for task in tasks_response.json()["tasks"]] == ["002", "001", "003"]
    assert task_response.status_code == 200
    assert task_response.json()["task"] == {
        "task_id": "002",
        "title": "Active task",
        "status": "active",
        "depends_on": ["001"],
        "anti_affinity": ["003"],
        "exec_order": 1,
        "full_test_after": True,
        "worker_slot": 0,
        "plan_path": str(session_paths.worker_dir(0) / "002.plan.md"),
        "log_path": str(session_paths.worker_log(0)),
        "created_at": "2026-03-09T10:01:00Z",
        "started_at": "2026-03-09T10:06:00Z",
        "completed_at": None,
        "history_source": "live",
    }
    assert dashboard_response.status_code == 200
    dashboard_payload = dashboard_response.json()
    assert dashboard_payload == {
        "session": {
            "id": "session-11",
            "status": "running",
            "pack": "claude-code",
            "started_at": "2026-03-09T10:05:00Z",
            "elapsed": dashboard_payload["session"]["elapsed"],
            "config": {},
            "effective_runtime_config": {
                "planner_count": 2,
                "worker_count": 2,
                "verification_interval": 4,
                "timeouts": {"task_idle": 300, "task_max": 0, "session_max": 14400},
                "auto_fix": {"enabled": False, "max_attempts": 2},
                "poll_interval": 0.05,
                "environment": {},
            },
        },
        "pipeline": {
            "intake": 0,
            "planning": 0,
            "staged": 0,
            "review": 0,
            "ready": 1,
            "active": 1,
            "done": 1,
            "blocked": 0,
        },
        "workers": [
            {
                "slot": 0,
                "status": "active",
                "task_id": "002",
                "task_title": "Active task",
                "elapsed": dashboard_payload["workers"][0]["elapsed"],
            },
            {
                "slot": 1,
                "status": "idle",
            },
        ],
    }
    assert dashboard_payload["session"]["elapsed"] >= 0
    assert dashboard_payload["workers"][0]["elapsed"] >= 0
    assert dag_response.status_code == 200
    assert dag_response.json()["tasks"][1] == {
        "task_id": "002",
        "depends_on": ["001"],
        "anti_affinity": ["003"],
        "exec_order": 1,
    }


def test_root_serves_embedded_spa_document_while_preserving_packet11_api_routes(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    root_response = client.get("/")
    packs_response = client.get("/api/packs")
    settings_response = client.get("/api/settings")

    assert root_response.status_code == 200
    assert root_response.headers["content-type"].startswith("text/html")
    assert "<!DOCTYPE html>" in root_response.text
    assert 'id="switchyard-app"' in root_response.text
    assert packs_response.status_code == 200
    assert packs_response.json()["packs"][0]["name"] == "claude-code"
    assert settings_response.status_code == 200
    assert settings_response.json()["settings"]["default_pack"] == "claude-code"


def test_root_bootstrap_payload_supports_setup_monitor_history_and_settings_views_without_extra_requests(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    write_global_config(
        runtime_paths.config,
        GlobalConfig(
            retention_days=14,
            default_planners=4,
            default_workers=2,
            default_pack="claude-code",
        ),
    )
    active_session = store.create_session(
        session_id="session-12-active",
        name="Active Packet 12 Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
        config_json=json.dumps({"planner_count": 1, "worker_count": 1}),
    )
    store.update_session_status(
        active_session.id,
        status="running",
        started_at="2026-03-09T10:05:00Z",
    )
    _register_task(store, active_session.id, task_id="001", title="Monitor task", exec_order=1)
    store.project_task(
        active_session.id,
        "001",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:06:00Z",
    )
    intake_file = runtime_paths.session_paths(active_session.id).intake / "001_monitor.md"
    intake_file.write_text("# Monitor\n", encoding="utf-8")

    store.create_session(
        session_id="session-12-history",
        name="Completed Packet 12 Session",
        pack="claude-code",
        created_at="2026-03-08T10:00:00Z",
    )
    store.update_session_status(
        "session-12-history",
        status="completed",
        started_at="2026-03-08T10:05:00Z",
        completed_at="2026-03-08T10:45:00Z",
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    match = re.search(
        r'<script id="switchyard-bootstrap" type="application/json">(.*?)</script>',
        response.text,
        re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))

    assert payload["views"] == [
        "setup",
        "monitor",
        "task-detail",
        "dag",
        "history",
        "settings",
    ]
    settings = payload["settings"]
    assert settings["retention_days"] == 14
    assert settings["default_planners"] == 4
    assert settings["default_workers"] == 2
    assert settings["default_pack"] == "claude-code"
    assert "runtime_root" in settings
    assert payload["packs"] == [
        {
            "name": "claude-code",
            "description": "Packet 11 runtime pack.",
            "version": "1.2.3",
            "max_workers": 2,
            "planning_enabled": True,
            "verification_enabled": False,
        }
    ]
    assert [session["id"] for session in payload["sessions"]] == [
        "session-12-active",
        "session-12-history",
    ]
    assert payload["current_session"]["id"] == "session-12-active"
    assert payload["current_session"]["status"] == "running"
    assert payload["dashboard"]["session"]["id"] == "session-12-active"
    assert payload["dashboard"]["workers"][0]["task_id"] == "001"
    assert payload["intake"]["locked"] is True
    assert payload["intake"]["files"][0]["filename"] == "001_monitor.md"


def test_root_bootstrap_payload_leaves_current_session_empty_when_only_history_exists(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    store.create_session(
        session_id="session-12-history-only",
        name="History Only Session",
        pack="claude-code",
        created_at="2026-03-08T10:00:00Z",
    )
    store.update_session_status(
        "session-12-history-only",
        status="completed",
        started_at="2026-03-08T10:05:00Z",
        completed_at="2026-03-08T10:45:00Z",
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    match = re.search(
        r'<script id="switchyard-bootstrap" type="application/json">(.*?)</script>',
        response.text,
        re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))

    assert payload["sessions"][0]["id"] == "session-12-history-only"
    assert payload["current_session"] is None
    assert payload["dashboard"] is None
    assert payload["intake"] is None


def test_history_session_serialization_reads_summary_data_after_successful_trim(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-12a-history",
        name="History Summary Session",
        pack="claude-code",
        created_at="2026-03-08T10:00:00Z",
        config_json=json.dumps({"worker_count": 1}, sort_keys=True),
    )
    _register_task(
        store,
        session.id,
        task_id="001",
        title="Successful history task",
        exec_order=2,
    )
    store.project_task(
        session.id,
        "001",
        status="done",
        timestamp="2026-03-08T10:20:00Z",
    )
    store.append_event(
        session.id,
        timestamp="2026-03-08T10:25:00Z",
        event_type="session.completed",
        message="All tasks completed successfully.",
    )
    store.update_session_status(
        session.id,
        status="completed",
        started_at="2026-03-08T10:05:00Z",
        completed_at="2026-03-08T10:25:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    session_paths.resolution.write_text(
        '{"resolved_at":"2026-03-08T10:04:00Z","tasks":[{"task_id":"001","depends_on":[],"anti_affinity":[],"exec_order":2}]}\n',
        encoding="utf-8",
    )
    session_paths.worker_log(0).parent.mkdir(parents=True, exist_ok=True)
    session_paths.worker_log(0).write_text("worker log\n", encoding="utf-8")
    store.write_successful_session_summary(session.id)
    store.trim_successful_session_artifacts(session.id)

    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    sessions_response = client.get("/api/sessions")
    session_response = client.get(f"/api/sessions/{session.id}")
    tasks_response = client.get(f"/api/sessions/{session.id}/tasks")
    task_response = client.get(f"/api/sessions/{session.id}/tasks/001")
    log_response = client.get(f"/api/sessions/{session.id}/tasks/001/log?offset=0&limit=50")
    dashboard_response = client.get(f"/api/sessions/{session.id}/dashboard")

    assert sessions_response.status_code == 200
    listed = sessions_response.json()["sessions"][0]
    assert listed["id"] == session.id
    assert listed["summary"]["session"]["id"] == session.id
    assert listed["summary"]["tasks"][0]["task_id"] == "001"
    assert listed["summary"]["tasks"][0]["status"] == "done"

    detail = session_response.json()["session"]
    assert detail["id"] == session.id
    assert detail["summary"]["session"]["duration_seconds"] == 1200
    assert detail["summary"]["artifacts"] == {
        "summary_path": "summary.json",
        "resolution_path": "resolution.json",
        "session_log_path": "logs/session.log",
    }

    assert tasks_response.json()["tasks"] == [
        {
            "task_id": "001",
            "title": "Successful history task",
            "status": "done",
            "depends_on": [],
            "anti_affinity": [],
            "exec_order": 2,
            "full_test_after": False,
            "worker_slot": None,
            "plan_path": None,
            "log_path": None,
            "created_at": "2026-03-09T10:01:00Z",
            "started_at": None,
            "completed_at": "2026-03-08T10:20:00Z",
            "history_source": "summary",
        }
    ]
    assert task_response.json()["task"]["history_source"] == "summary"
    assert task_response.json()["task"]["plan_path"] is None
    assert log_response.json() == {"path": None, "offset": 0, "content": ""}
    assert dashboard_response.status_code == 200
    assert dashboard_response.json()["session"]["status"] == "completed"
    assert dashboard_response.json()["pipeline"] == {
        "intake": 0,
        "planning": 0,
        "staged": 0,
        "review": 0,
        "ready": 0,
        "active": 0,
        "done": 1,
        "blocked": 0,
    }


def test_trimmed_history_uses_summary_snapshot_instead_of_live_pack_manifest(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-13-history-snapshot",
        name="History Snapshot Session",
        pack="claude-code",
        created_at="2026-03-08T10:00:00Z",
    )
    _register_task(
        store,
        session.id,
        task_id="001",
        title="Snapshot task",
    )
    store.project_task(
        session.id,
        "001",
        status="done",
        timestamp="2026-03-08T10:20:00Z",
    )
    store.update_session_status(
        session.id,
        status="completed",
        started_at="2026-03-08T10:05:00Z",
        completed_at="2026-03-08T10:25:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    session_paths.resolution.write_text('{"tasks":[]}\n', encoding="utf-8")
    store.write_successful_session_summary(session.id)
    store.trim_successful_session_artifacts(session.id)

    (runtime_paths.packs / "claude-code" / "pack.yaml").write_text(
        dedent(
            """
            name: claude-code
            description: Mutated after completion.
            version: 9.9.9

            phases:
              planning:
                enabled: true
                executor: agent
                model: claude-opus
                prompt: prompts/planner.md
                max_instances: 7
              resolution:
                enabled: true
                executor: agent
                model: claude-opus
                prompt: prompts/resolver.md
              execution:
                enabled: true
                executor: shell
                command: scripts/execute
                max_workers: 6
              verification:
                enabled: false

            timeouts:
              task_idle: 15
              task_max: 120
              session_max: 240

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    detail = client.get(f"/api/sessions/{session.id}").json()["session"]
    dashboard = client.get(f"/api/sessions/{session.id}/dashboard").json()

    assert detail["effective_runtime_config"] == {
        "planner_count": 2,
        "worker_count": 2,
        "verification_interval": 4,
        "timeouts": {
            "task_idle": 300,
            "task_max": 0,
            "session_max": 14400,
        },
        "auto_fix": {
            "enabled": False,
            "max_attempts": 2,
        },
        "poll_interval": 0.05,
        "environment": {},
    }
    assert dashboard["session"]["effective_runtime_config"] == detail["effective_runtime_config"]


def test_intake_listing_includes_file_metadata_and_locked_state_for_setup_view(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-11c-intake",
        name="Packet 11C intake",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    draft = session_paths.intake / "001_alpha.md"
    nested = session_paths.intake / "nested" / "002_beta.md"
    late = session_paths.intake / "003_late.md"
    nested.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("# Alpha\n", encoding="utf-8")
    nested.write_text("# Beta\n", encoding="utf-8")
    pre_start_timestamp = datetime(2026, 3, 9, 10, 4, 0, tzinfo=UTC).timestamp()
    os.utime(draft, (pre_start_timestamp, pre_start_timestamp))
    os.utime(nested, (pre_start_timestamp, pre_start_timestamp))

    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    created_response = client.get(f"/api/sessions/{session.id}/intake")
    store.update_session_status(
        session.id,
        status="running",
        started_at="2026-03-09T10:05:00Z",
    )
    late.write_text("# Late\n", encoding="utf-8")
    post_start_timestamp = datetime(2026, 3, 9, 10, 6, 0, tzinfo=UTC).timestamp()
    os.utime(late, (post_start_timestamp, post_start_timestamp))
    locked_response = client.get(f"/api/sessions/{session.id}/intake")

    assert created_response.status_code == 200
    assert created_response.json()["locked"] is False
    assert created_response.json()["files"] == [
        {
            "filename": "001_alpha.md",
            "path": "intake/001_alpha.md",
            "size": len("# Alpha\n".encode("utf-8")),
            "detected_at": created_response.json()["files"][0]["detected_at"],
            "locked": False,
            "in_snapshot": True,
        },
        {
            "filename": "002_beta.md",
            "path": "intake/nested/002_beta.md",
            "size": len("# Beta\n".encode("utf-8")),
            "detected_at": created_response.json()["files"][1]["detected_at"],
            "locked": False,
            "in_snapshot": True,
        },
    ]
    assert locked_response.status_code == 200
    assert locked_response.json()["locked"] is True
    assert locked_response.json()["files"] == [
        {
            "filename": "001_alpha.md",
            "path": "intake/001_alpha.md",
            "size": len("# Alpha\n".encode("utf-8")),
            "detected_at": "2026-03-09T10:04:00Z",
            "locked": True,
            "in_snapshot": True,
        },
        {
            "filename": "003_late.md",
            "path": "intake/003_late.md",
            "size": len("# Late\n".encode("utf-8")),
            "detected_at": "2026-03-09T10:06:00Z",
            "locked": True,
            "in_snapshot": False,
        },
        {
            "filename": "002_beta.md",
            "path": "intake/nested/002_beta.md",
            "size": len("# Beta\n".encode("utf-8")),
            "detected_at": "2026-03-09T10:04:00Z",
            "locked": True,
            "in_snapshot": True,
        },
    ]


def test_dashboard_uses_effective_session_worker_count_not_pack_max_workers(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-11c-dashboard",
        name="Packet 11C dashboard",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
        config_json=json.dumps({"worker_count": 1}),
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at=_timestamp_offset(seconds=-30),
    )
    _register_task(store, session.id, task_id="002", title="Single worker task")
    store.project_task(
        session.id,
        "002",
        status="active",
        worker_slot=0,
        timestamp=_timestamp_offset(seconds=-5),
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    response = client.get(f"/api/sessions/{session.id}/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["effective_runtime_config"]["worker_count"] == 1
    assert payload["workers"] == [
        {
            "slot": 0,
            "status": "active",
            "task_id": "002",
            "task_title": "Single worker task",
            "elapsed": payload["workers"][0]["elapsed"],
        }
    ]


def test_session_preflight_route_reports_permission_and_prerequisite_results_without_starting_execution(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_preflight_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-11b-preflight",
        name="Packet 11B Preflight",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    response = client.post(f"/api/sessions/{session.id}/preflight")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "permission_report": {"ok": True, "issues": []},
        "prerequisite_results": {
            "ok": True,
            "results": [
                {
                    "name": "CLI available",
                    "check": "printf 'cli ok\\n'",
                    "ok": True,
                    "exit_code": 0,
                    "stdout": "cli ok\n",
                    "stderr": "",
                }
            ],
        },
        "preflight_result": {
            "hook_name": "preflight",
            "script_path": str(runtime_paths.packs / "claude-code" / "scripts" / "preflight"),
            "args": [],
            "cwd": str(runtime_paths.packs / "claude-code"),
            "ok": True,
            "exit_code": 0,
            "stdout": "pack preflight ok\n",
            "stderr": "",
        },
    }
    assert store.get_session(session.id).status == "created"


def test_dashboard_payload_includes_configured_idle_workers_and_latest_runtime_progress_fields(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-11b-dashboard",
        name="Packet 11B Dashboard",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at=_timestamp_offset(seconds=-120),
    )
    _register_task(store, session.id, task_id="002", title="Active task")
    store.project_task(
        session.id,
        "002",
        status="active",
        worker_slot=0,
        timestamp=_timestamp_offset(seconds=-45),
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    controller = app.state.controller
    controller._publish_runtime_event(
        BackendRuntimeEvent(
            message_type="log_line",
            session_id=session.id,
            data={
                "worker_slot": 0,
                "task_id": "002",
                "line": "##PROGRESS## 002 | Phase: implementing | 2/5",
                "timestamp": "2026-03-09T10:06:01Z",
            },
        )
    )
    controller._publish_runtime_event(
        BackendRuntimeEvent(
            message_type="progress_detail",
            session_id=session.id,
            data={
                "worker_slot": 0,
                "task_id": "002",
                "detail": "Processing chunk 3/9",
                "timestamp": "2026-03-09T10:06:02Z",
            },
        )
    )
    client = TestClient(app)

    response = client.get(f"/api/sessions/{session.id}/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["id"] == session.id
    assert payload["session"]["status"] == "running"
    assert payload["session"]["elapsed"] >= 100
    assert payload["workers"] == [
        {
            "slot": 0,
            "status": "active",
            "task_id": "002",
            "task_title": "Active task",
            "phase": "implementing",
            "phase_num": 2,
            "phase_total": 5,
            "detail": "Processing chunk 3/9",
            "elapsed": payload["workers"][0]["elapsed"],
        },
        {"slot": 1, "status": "idle"},
    ]
    assert payload["workers"][0]["elapsed"] >= 30


def test_state_update_snapshot_after_runtime_events_preserves_worker_card_fields_for_reconnecting_clients(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-11b-reconnect",
        name="Packet 11B Reconnect",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at=_timestamp_offset(seconds=-90),
    )
    _register_task(store, session.id, task_id="003", title="Reconnect task")
    store.project_task(
        session.id,
        "003",
        status="active",
        worker_slot=0,
        timestamp=_timestamp_offset(seconds=-20),
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    controller = app.state.controller
    controller._publish_runtime_event(
        BackendRuntimeEvent(
            message_type="log_line",
            session_id=session.id,
            data={
                "worker_slot": 0,
                "task_id": "003",
                "line": "##PROGRESS## 003 | Phase: testing | 4/5",
                "timestamp": "2026-03-09T10:06:05Z",
            },
        )
    )
    controller._publish_runtime_event(
        BackendRuntimeEvent(
            message_type="progress_detail",
            session_id=session.id,
            data={
                "worker_slot": 0,
                "task_id": "003",
                "detail": "Running targeted tests",
                "timestamp": "2026-03-09T10:06:06Z",
            },
        )
    )
    client = TestClient(app)

    with client.websocket_connect("/ws") as websocket:
        controller._publish_snapshot(session.id)
        message = _wait_for_websocket_message(
            websocket,
            lambda item: item["type"] == "state_update"
            and item["data"]["session"]["id"] == session.id,
        )

    assert message["data"]["workers"][0]["task_id"] == "003"
    assert message["data"]["workers"][0]["phase"] == "testing"
    assert message["data"]["workers"][0]["phase_num"] == 4
    assert message["data"]["workers"][0]["phase_total"] == 5
    assert message["data"]["workers"][0]["detail"] == "Running targeted tests"


def test_pause_resume_abort_and_retry_routes_delegate_to_background_session_controller(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    store.create_session(
        session_id="session-11-control",
        name="Control Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, "session-11-control", task_id="007", title="Retry me")
    controller = FakeSessionController()
    app = create_app(store=store, runtime_paths=runtime_paths, controller=controller)
    client = TestClient(app)

    pause_response = client.post("/api/sessions/session-11-control/pause")
    resume_response = client.post("/api/sessions/session-11-control/resume")
    abort_response = client.post("/api/sessions/session-11-control/abort")
    retry_response = client.post("/api/sessions/session-11-control/tasks/007/retry")

    assert pause_response.status_code == 202
    assert resume_response.status_code == 202
    assert abort_response.status_code == 202
    assert retry_response.status_code == 202
    assert controller.calls == [
        ("pause", "session-11-control", None),
        ("resume", "session-11-control", None),
        ("abort", "session-11-control", None),
        ("retry_task", "session-11-control", "007"),
    ]


def test_pause_and_abort_routes_control_the_real_background_session_loop(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_slow_runtime_pack(runtime_paths)
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    pause_session = store.create_session(
        session_id="session-11-pause",
        name="Pause Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        pause_session.id,
        status="running",
        started_at=started_at,
    )
    _register_task(store, pause_session.id, task_id="001", title="First task", exec_order=1)
    _register_task(store, pause_session.id, task_id="002", title="Second task", exec_order=2)

    abort_session = store.create_session(
        session_id="session-11-abort",
        name="Abort Session",
        pack="claude-code",
        created_at="2026-03-09T10:10:00Z",
    )
    store.update_session_status(
        abort_session.id,
        status="running",
        started_at=started_at,
    )
    _register_task(store, abort_session.id, task_id="010", title="Abort me", exec_order=1)
    _register_task(store, abort_session.id, task_id="011", title="Still ready", exec_order=2)

    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    start_pause_response = client.post(f"/api/sessions/{pause_session.id}/start")
    assert start_pause_response.status_code == 202
    _wait_until(lambda: store.get_task(pause_session.id, "001").status == "active")

    pause_response = client.post(f"/api/sessions/{pause_session.id}/pause")
    assert pause_response.status_code == 202
    _wait_until(lambda: store.get_task(pause_session.id, "001").status == "done")
    time.sleep(0.3)

    assert store.get_session(pause_session.id).status == "paused"
    assert store.get_task(pause_session.id, "002").status == "ready"

    resume_response = client.post(f"/api/sessions/{pause_session.id}/resume")
    assert resume_response.status_code == 202
    _wait_until(lambda: store.get_session(pause_session.id).status == "completed")
    assert store.get_task(pause_session.id, "002").status == "done"

    start_abort_response = client.post(f"/api/sessions/{abort_session.id}/start")
    assert start_abort_response.status_code == 202
    _wait_until(lambda: store.get_task(abort_session.id, "010").status == "active")

    abort_response = client.post(f"/api/sessions/{abort_session.id}/abort")
    assert abort_response.status_code == 202
    _wait_until(lambda: store.get_task(abort_session.id, "010").status == "blocked")

    assert store.get_session(abort_session.id).status == "aborted"
    assert store.get_task(abort_session.id, "011").status == "ready"


def test_open_intake_and_reveal_file_reject_traversal_outside_session_root(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    store.create_session(
        session_id="session-11-files",
        name="Files Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths("session-11-files")
    inside_file = session_paths.intake / "001.plan.md"
    inside_file.parent.mkdir(parents=True, exist_ok=True)
    inside_file.write_text("# intake\n", encoding="utf-8")
    calls: list[list[str]] = []

    def command_runner(command: list[str]) -> None:
        calls.append(command)

    app = create_app(
        store=store,
        runtime_paths=runtime_paths,
        command_runner=command_runner,
    )
    client = TestClient(app)

    open_response = client.post("/api/sessions/session-11-files/open-intake")
    reveal_response = client.post(
        "/api/sessions/session-11-files/reveal-file",
        params={"path": "intake/001.plan.md"},
    )
    traversal_response = client.post(
        "/api/sessions/session-11-files/reveal-file",
        params={"path": "../outside.txt"},
    )

    assert open_response.status_code == 204
    assert reveal_response.status_code == 204
    assert traversal_response.status_code == 400
    assert calls == [
        ["open", str(session_paths.intake)],
        ["open", "-R", str(inside_file)],
    ]


def test_websocket_broadcasts_state_updates_alerts_and_slot_scoped_log_lines(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)
    manager = app.state.connection_manager

    with client.websocket_connect("/ws") as websocket:
        asyncio.run(
            manager.broadcast_state(
                {
                    "session": {"status": "running", "elapsed": 12},
                    "pipeline": {"ready": 1, "active": 1, "done": 0},
                    "workers": [{"slot": 0, "status": "active", "task_id": "002"}],
                }
            )
        )
        state_message = websocket.receive_json()
        assert state_message["type"] == "state_update"
        assert state_message["data"]["session"]["status"] == "running"

        websocket.send_json({"type": "subscribe_logs", "worker_slot": 0})
        asyncio.run(
            manager.send_log_line(
                0,
                {
                    "worker_slot": 0,
                    "task_id": "002",
                    "line": "##PROGRESS## 002 | Phase: Execute | 1/1",
                    "timestamp": "2026-03-09T10:06:01Z",
                },
            )
        )
        log_message = websocket.receive_json()
        assert log_message == {
            "type": "log_line",
            "data": {
                "worker_slot": 0,
                "task_id": "002",
                "line": "##PROGRESS## 002 | Phase: Execute | 1/1",
                "timestamp": "2026-03-09T10:06:01Z",
            },
        }

        asyncio.run(
            manager.broadcast_task_status_change(
                {
                    "task_id": "002",
                    "old_status": "active",
                    "new_status": "done",
                    "worker_slot": 0,
                    "notes": "Completed.",
                }
            )
        )
        status_message = websocket.receive_json()
        assert status_message["type"] == "task_status_change"

        asyncio.run(
            manager.broadcast_progress_detail(
                {
                    "worker_slot": 0,
                    "task_id": "002",
                    "detail": "Processing chunk 2/3",
                    "timestamp": "2026-03-09T10:06:02Z",
                }
            )
        )
        progress_message = websocket.receive_json()
        assert progress_message == {
            "type": "progress_detail",
            "data": {
                "worker_slot": 0,
                "task_id": "002",
                "detail": "Processing chunk 2/3",
                "timestamp": "2026-03-09T10:06:02Z",
            },
        }

        asyncio.run(
            manager.broadcast_alert(
                {
                    "severity": "error",
                    "task_id": "002",
                    "worker_slot": 0,
                    "message": "No progress for 5 minutes",
                }
            )
        )
        alert_message = websocket.receive_json()
        assert alert_message == {
            "type": "alert",
            "data": {
                "severity": "error",
                "task_id": "002",
                "worker_slot": 0,
                "message": "No progress for 5 minutes",
            },
        }


def test_background_session_websocket_streams_runtime_task_status_changes_before_completion(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_fixture_runtime_pack(
        runtime_paths,
        repo_root=repo_root,
        fixture_name="streaming_worker.py",
    )
    session = store.create_session(
        session_id="session-11a-runtime-status",
        name="Runtime Status Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    _register_task(store, session.id, task_id="039", title="Streaming task")

    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    with client.websocket_connect("/ws") as websocket:
        start_response = client.post(f"/api/sessions/{session.id}/start")
        assert start_response.status_code == 202

        active_status = _wait_for_websocket_message(
            websocket,
            lambda message: message["type"] == "task_status_change"
            and message["data"]["task_id"] == "039"
            and message["data"]["old_status"] == "ready"
            and message["data"]["new_status"] == "active",
        )
        live_state = _wait_for_websocket_message(
            websocket,
            lambda message: message["type"] == "state_update"
            and message["data"]["session"]["id"] == session.id
            and message["data"]["session"]["status"] == "running"
            and message["data"]["pipeline"]["active"] == 1
            and message["data"]["pipeline"]["done"] == 0,
        )

        assert active_status["data"]["worker_slot"] == 0
        assert store.get_session(session.id).status == "running"
        assert live_state["data"]["workers"][0]["task_id"] == "039"

        done_status = _wait_for_websocket_message(
            websocket,
            lambda message: message["type"] == "task_status_change"
            and message["data"]["task_id"] == "039"
            and message["data"]["old_status"] == "active"
            and message["data"]["new_status"] == "done",
        )

        assert done_status["data"]["worker_slot"] == 0
        _wait_until(lambda: store.get_session(session.id).status == "completed")


def test_background_session_websocket_streams_subscribed_log_lines_and_progress_detail_from_real_worker_output(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_fixture_runtime_pack(
        runtime_paths,
        repo_root=repo_root,
        fixture_name="streaming_worker.py",
    )
    session = store.create_session(
        session_id="session-11a-runtime-logs",
        name="Runtime Log Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    _register_task(store, session.id, task_id="039", title="Streaming task")

    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "subscribe_logs", "worker_slot": 0})
        start_response = client.post(f"/api/sessions/{session.id}/start")
        assert start_response.status_code == 202

        log_message = _wait_for_websocket_message(
            websocket,
            lambda message: message["type"] == "log_line"
            and message["data"]["worker_slot"] == 0
            and message["data"]["task_id"] == "039"
            and "Phase: implementing" in message["data"]["line"],
        )
        progress_message = _wait_for_websocket_message(
            websocket,
            lambda message: message["type"] == "progress_detail"
            and message["data"]["worker_slot"] == 0
            and message["data"]["task_id"] == "039"
            and message["data"]["detail"] == "Streaming detail",
        )

        assert log_message["data"]["timestamp"]
        assert progress_message["data"]["timestamp"]


def test_background_session_websocket_emits_timeout_or_problem_alerts_from_runtime_polling(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_fixture_runtime_pack(
        runtime_paths,
        repo_root=repo_root,
        fixture_name="silent_worker.py",
        task_idle=1,
    )
    session = store.create_session(
        session_id="session-11a-runtime-alert",
        name="Runtime Alert Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    _register_task(store, session.id, task_id="039", title="Silent task")

    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    with client.websocket_connect("/ws") as websocket:
        start_response = client.post(f"/api/sessions/{session.id}/start")
        assert start_response.status_code == 202

        alert_message = _wait_for_websocket_message(
            websocket,
            lambda message: message["type"] == "alert"
            and message["data"]["task_id"] == "039"
            and message["data"]["worker_slot"] == 0,
            max_messages=48,
        )

        assert alert_message["data"]["severity"] == "warning"
        assert "No output" in alert_message["data"]["message"]
        _wait_until(lambda: store.get_task(session.id, "039").status == "blocked", timeout=4.0)


def test_backend_start_path_uses_default_claude_runtime_when_agent_callables_are_not_injected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from cognitive_switchyard.models import FixerAttemptResult
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-13-server-default-runtime",
        name="Packet 13 backend default runtime",
        pack="claude-code",
        created_at="2026-03-10T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    (session_paths.intake / "001_feature.md").write_text("# Feature request\n", encoding="utf-8")
    pack_root = runtime_paths.packs / "claude-code"
    scripts_dir = pack_root / "scripts"
    prompts_dir = pack_root / "prompts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    execute_path = scripts_dir / "execute"
    execute_path.write_text(
        dedent(
            """
            #!/usr/bin/env python3
            import sys
            from pathlib import Path

            task_path = Path(sys.argv[1])
            task_id = task_path.name.removesuffix(".plan.md")
            print(f"##PROGRESS## {task_id} | Phase: Execute | 1/1")
            task_path.with_name(task_id + ".status").write_text(
                "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
                encoding="utf-8",
            )
            """
        ).lstrip(),
        encoding="utf-8",
    )
    execute_path.chmod(execute_path.stat().st_mode | 0o111)
    (prompts_dir / "planner.md").write_text("Planner prompt.\n", encoding="utf-8")
    (prompts_dir / "resolver.md").write_text("Resolver prompt.\n", encoding="utf-8")
    (prompts_dir / "fixer.md").write_text("Fixer prompt.\n", encoding="utf-8")
    (pack_root / "pack.yaml").write_text(
        dedent(
            """
            name: claude-code
            description: Packet 13 runtime pack.
            version: 1.2.3

            phases:
              planning:
                enabled: true
                executor: agent
                model: claude-opus
                prompt: prompts/planner.md
                max_instances: 1
              resolution:
                enabled: true
                executor: agent
                model: claude-opus
                prompt: prompts/resolver.md
              execution:
                enabled: true
                executor: shell
                command: scripts/execute
                max_workers: 1
              verification:
                enabled: false

            auto_fix:
              enabled: true
              max_attempts: 2
              model: claude-opus
              prompt: prompts/fixer.md

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )

    from cognitive_switchyard import orchestrator

    captured: dict[str, object] = {}

    class FakeRuntime:
        def planner_agent(self, **kwargs):
            captured["planner"] = kwargs
            return dedent(
                """
                ---
                PLAN_ID: 001
                PRIORITY: normal
                ESTIMATED_SCOPE: src/feature.py
                DEPENDS_ON: none
                FULL_TEST_AFTER: no
                ---

                # Plan: Task 001

                Implement the feature.
                """
            ).lstrip()

        def resolver_agent(self, **kwargs):
            captured["resolver"] = kwargs
            return (
                '{\n'
                '  "resolved_at": "2026-03-10T10:00:00Z",\n'
                '  "tasks": [{"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 1}],\n'
                '  "groups": [],\n'
                '  "conflicts": [],\n'
                '  "notes": "default runtime"\n'
                '}\n'
            )

        def fixer_executor(self, context):
            captured["fixer"] = context.context_type
            return FixerAttemptResult(success=True, summary="fixed")

    monkeypatch.setattr(orchestrator, "build_default_agent_runtime", lambda pack_manifest: FakeRuntime())

    app = create_app(store=store, runtime_paths=runtime_paths)
    app.state.controller._run_session(session.id)

    assert store.get_session(session.id).status == "completed"
    assert captured["planner"]["model"] == "claude-opus"
    assert captured["resolver"]["model"] == "claude-opus"


def test_history_session_detail_includes_release_notes_when_trimmed_session_retains_artifact(
    tmp_path: Path,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-14-history",
        name="Packet 14 history",
        pack="claude-code",
        created_at="2026-03-10T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    session_paths.summary.write_text(
        json.dumps(
            {
                "session": {
                    "id": session.id,
                    "name": session.name,
                    "pack": session.pack,
                    "status": "completed",
                    "created_at": session.created_at,
                    "started_at": "2026-03-10T10:01:00Z",
                    "completed_at": "2026-03-10T10:02:00Z",
                    "duration_seconds": 60,
                    "config": {},
                    "effective_runtime_config": {"worker_count": 1},
                    "runtime_state": {},
                },
                "pipeline": {"ready": 0, "active": 0, "done": 1, "blocked": 0},
                "tasks": [
                    {
                        "task_id": "001",
                        "title": "Ship release notes",
                        "status": "done",
                    }
                ],
                "worker_statistics": {"slots_seen": [0], "configured_worker_count": 1},
                "artifacts": {
                    "summary_path": "summary.json",
                    "resolution_path": "resolution.json",
                    "session_log_path": "logs/session.log",
                    "release_notes_path": "RELEASE_NOTES.md",
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    session_paths.root.joinpath("RELEASE_NOTES.md").write_text(
        "# Release Notes\n\n- Restart the service after deploy.\n",
        encoding="utf-8",
    )
    store.update_session_status(
        session.id,
        status="completed",
        started_at="2026-03-10T10:01:00Z",
        completed_at="2026-03-10T10:02:00Z",
    )
    app = create_app(store=store, runtime_paths=runtime_paths)

    with TestClient(app) as client:
        response = client.get(f"/api/sessions/{session.id}")

    payload = response.json()["session"]

    assert response.status_code == 200
    assert payload["release_notes"]["path"] == "RELEASE_NOTES.md"
    assert "Restart the service after deploy." in payload["release_notes"]["content"]


def test_create_duplicate_session_returns_409(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    body = {"id": "dup-test", "name": "First", "pack": "claude-code"}
    first = client.post("/api/sessions", json=body)
    assert first.status_code == 201

    second = client.post("/api/sessions", json=body)
    assert second.status_code == 409


def test_resolve_path_expands_tilde_and_detects_git(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    # Test with a real directory (tmp_path exists)
    response = client.post("/api/resolve-path", json={"path": str(tmp_path)})
    assert response.status_code == 200
    data = response.json()
    assert data["exists"] is True
    assert data["is_directory"] is True
    assert data["resolved"] == str(tmp_path.resolve())

    # Test with tilde expansion (home dir exists and is a dir)
    tilde_response = client.post("/api/resolve-path", json={"path": "~"})
    assert tilde_response.status_code == 200
    tilde_data = tilde_response.json()
    assert tilde_data["exists"] is True
    assert tilde_data["is_directory"] is True
    assert "~" not in tilde_data["resolved"]

    # Test with nonexistent path
    missing_response = client.post("/api/resolve-path", json={"path": "/nonexistent/path/xyz"})
    assert missing_response.status_code == 200
    missing_data = missing_response.json()
    assert missing_data["exists"] is False

    # Test with empty path
    empty_response = client.post("/api/resolve-path", json={"path": ""})
    assert empty_response.status_code == 400


def test_resolve_path_detects_git_repo(tmp_path: Path) -> None:
    import subprocess
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    # Create a git repo in tmp_path
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    (repo / "README.md").write_text("test")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-b", "test-branch"], capture_output=True, check=True)

    response = client.post("/api/resolve-path", json={"path": str(repo)})
    assert response.status_code == 200
    data = response.json()
    assert data["is_git"] is True
    assert data["branch"] == "test-branch"
    assert data["on_protected_branch"] is False


def test_session_config_environment_persisted(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    body = {
        "id": "env-test",
        "name": "Env Test",
        "pack": "claude-code",
        "config": {
            "environment": {
                "COGNITIVE_SWITCHYARD_REPO_ROOT": "/tmp/my-project"
            }
        },
    }
    response = client.post("/api/sessions", json=body)
    assert response.status_code == 201

    session_response = client.get("/api/sessions/env-test")
    assert session_response.status_code == 200
    config = session_response.json()["session"]["config"]
    assert config["environment"]["COGNITIVE_SWITCHYARD_REPO_ROOT"] == "/tmp/my-project"


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(path)], capture_output=True, check=True)
    (path / "README.md").write_text("test")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], capture_output=True, check=True)


def test_repo_branches_lists_branches(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    repo = tmp_path / "branches-repo"
    _init_git_repo(repo)
    subprocess.run(["git", "-C", str(repo), "branch", "feature-a"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "branch", "feature-b"], capture_output=True, check=True)

    response = client.post("/api/repo-branches", json={"path": str(repo)})
    assert response.status_code == 200
    data = response.json()
    assert "feature-a" in data["branches"]
    assert "feature-b" in data["branches"]
    assert data["current"] in data["branches"]


def test_repo_branches_rejects_non_git_directory(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    plain_dir = tmp_path / "not-git"
    plain_dir.mkdir()

    response = client.post("/api/repo-branches", json={"path": str(plain_dir)})
    assert response.status_code == 400


def test_repo_create_branch_creates_new_branch(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    repo = tmp_path / "create-branch-repo"
    _init_git_repo(repo)

    response = client.post("/api/repo-create-branch", json={
        "repo_path": str(repo),
        "branch_name": "new-feature",
        "from_branch": "main",
    })
    assert response.status_code == 200
    assert response.json()["created"] is True
    assert response.json()["branch"] == "new-feature"

    verify = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "refs/heads/new-feature"],
        capture_output=True, text=True,
    )
    assert verify.returncode == 0


def test_repo_create_branch_rejects_duplicate(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    repo = tmp_path / "dup-branch-repo"
    _init_git_repo(repo)

    response = client.post("/api/repo-create-branch", json={
        "repo_path": str(repo),
        "branch_name": "main",
        "from_branch": "main",
    })
    assert response.status_code == 409


def test_session_worktree_created_on_session_create(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    repo = tmp_path / "worktree-repo"
    _init_git_repo(repo)
    subprocess.run(["git", "-C", str(repo), "branch", "session-branch"], capture_output=True, check=True)

    session_id = "wt-session-01"
    response = client.post("/api/sessions", json={
        "id": session_id,
        "name": "Worktree Test",
        "pack": "claude-code",
        "config": {
            "environment": {
                "COGNITIVE_SWITCHYARD_REPO_ROOT": str(repo),
                "COGNITIVE_SWITCHYARD_BRANCH": "session-branch",
            }
        },
    })
    assert response.status_code == 201
    session = response.json()["session"]
    env = session["config"]["environment"]
    assert env["COGNITIVE_SWITCHYARD_SOURCE_REPO"] == str(repo)
    worktree_path = Path(env["COGNITIVE_SWITCHYARD_REPO_ROOT"])
    assert worktree_path != repo
    assert worktree_path.is_dir()
    assert (worktree_path / "README.md").exists()


def test_session_worktree_cleaned_up_on_delete(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    client = TestClient(app)

    repo = tmp_path / "cleanup-repo"
    _init_git_repo(repo)
    subprocess.run(["git", "-C", str(repo), "branch", "cleanup-branch"], capture_output=True, check=True)

    session_id = "cleanup-session-01"
    response = client.post("/api/sessions", json={
        "id": session_id,
        "name": "Cleanup Test",
        "pack": "claude-code",
        "config": {
            "environment": {
                "COGNITIVE_SWITCHYARD_REPO_ROOT": str(repo),
                "COGNITIVE_SWITCHYARD_BRANCH": "cleanup-branch",
            }
        },
    })
    assert response.status_code == 201
    session = response.json()["session"]
    worktree_path = Path(session["config"]["environment"]["COGNITIVE_SWITCHYARD_REPO_ROOT"])
    assert worktree_path.is_dir()

    delete_response = client.delete(f"/api/sessions/{session_id}")
    assert delete_response.status_code == 200
    assert not worktree_path.exists()
