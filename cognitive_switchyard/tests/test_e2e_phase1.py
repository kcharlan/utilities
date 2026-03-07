from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cognitive_switchyard.config import SessionConfig, ensure_directories, session_dir, session_subdirs
from cognitive_switchyard.models import Session, SessionStatus, Task, TaskStatus
from cognitive_switchyard.orchestrator import Orchestrator
from cognitive_switchyard.pack_loader import bootstrap_packs
from cognitive_switchyard.scheduler import load_resolution
from cognitive_switchyard.state import StateStore


@pytest.fixture
def e2e_env(tmp_path, monkeypatch):
    home = tmp_path / ".cognitive_switchyard"
    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("cognitive_switchyard.config.SESSIONS_DIR", home / "sessions")
    monkeypatch.setattr("cognitive_switchyard.config.PACKS_DIR", home / "packs")
    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_DB", home / "cognitive_switchyard.db")
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.PACKS_DIR", home / "packs")
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.BUILTIN_PACKS_DIR", Path(__file__).resolve().parent.parent / "packs")

    ensure_directories()
    bootstrap_packs()

    session_id = "e2e-test-001"
    config = SessionConfig(
        pack_name="test-echo",
        session_name="E2E Test",
        num_workers=2,
        poll_interval=1,
        task_idle_timeout=30,
        session_max_timeout=60,
    )

    store = StateStore(db_path=home / "cognitive_switchyard.db")
    store.connect()
    store.create_session(
        Session(
            id=session_id,
            name="E2E Test",
            pack_name="test-echo",
            config_json=json.dumps(config.__dict__),
            status=SessionStatus.CREATED,
            created_at=datetime.now(timezone.utc),
        )
    )

    dirs = session_subdirs(session_id)
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)

    fixtures = Path(__file__).parent / "fixtures" / "echo_session"
    for plan_file in (fixtures / "ready").glob("*.plan.md"):
        shutil.copy2(plan_file, dirs["ready"])
    shutil.copy2(fixtures / "resolution.json", session_dir(session_id) / "resolution.json")

    constraints_map = {constraint.task_id: constraint for constraint in load_resolution(session_dir(session_id) / "resolution.json")}
    for plan_file in sorted(dirs["ready"].glob("*.plan.md")):
        task_id = store._extract_task_id_from_filename(plan_file.name)
        constraint = constraints_map.get(task_id)
        store.create_task(
            Task(
                id=task_id,
                session_id=session_id,
                title=plan_file.stem,
                status=TaskStatus.READY,
                plan_filename=plan_file.name,
                depends_on=constraint.depends_on if constraint else [],
                anti_affinity=constraint.anti_affinity if constraint else [],
                exec_order=constraint.exec_order if constraint else 1,
                created_at=datetime.now(timezone.utc),
            )
        )

    yield store, session_id, dirs
    store.close()


class TestEndToEndPhase1:
    def test_full_pipeline(self, e2e_env) -> None:
        store, session_id, dirs = e2e_env
        tasks = store.list_tasks(session_id)
        assert len(tasks) == 2
        assert all(task.status == TaskStatus.READY for task in tasks)

        Orchestrator(session_id, store).run_foreground()

        assert store.get_session(session_id).status == SessionStatus.COMPLETED
        assert store.get_task(session_id, "001").status == TaskStatus.DONE
        assert store.get_task(session_id, "002").status == TaskStatus.DONE

        done_files = list(dirs["done"].glob("*"))
        plan_files = [file_path for file_path in done_files if file_path.suffix == ".md"]
        status_files = [file_path for file_path in done_files if file_path.name.endswith(".status")]
        assert len(plan_files) == 2
        assert len(status_files) == 2
        assert list(dirs["ready"].glob("*.plan.md")) == []

    def test_session_trimming(self, e2e_env) -> None:
        store, session_id, _ = e2e_env
        Orchestrator(session_id, store).run_foreground()

        base = session_dir(session_id)
        assert (base / "summary.json").exists()
        assert (base / "RELEASE_NOTES.md").exists()
        assert "Plans Included" in (base / "RELEASE_NOTES.md").read_text()
        assert not (base / "intake").exists()
        assert not (base / "ready").exists()
        assert not (base / "workers").exists()
