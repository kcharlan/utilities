from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from cognitive_switchyard.config import SessionConfig, session_subdirs
from cognitive_switchyard.models import EventType, Session, SessionStatus, Task, TaskStatus
from cognitive_switchyard.orchestrator import Orchestrator
from cognitive_switchyard.state import StateStore


@pytest.fixture
def setup_session(tmp_path, monkeypatch):
    home = tmp_path / ".cognitive_switchyard"
    sessions = home / "sessions"
    packs = home / "packs"
    db_path = home / "cognitive_switchyard.db"

    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("cognitive_switchyard.config.SESSIONS_DIR", sessions)
    monkeypatch.setattr("cognitive_switchyard.config.PACKS_DIR", packs)
    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_DB", db_path)
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.PACKS_DIR", packs)

    pack_dir = packs / "test-echo"
    (pack_dir / "scripts").mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(
        "name: test-echo\n"
        "description: Test pack\n"
        "phases:\n"
        "  execution:\n"
        "    executor: shell\n"
        "    command: scripts/execute\n"
        "    max_workers: 2\n"
    )
    execute_script = pack_dir / "scripts" / "execute"
    execute_script.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "PLAN_FILE=\"$1\"\n"
        "PLAN_ID=$(basename \"$PLAN_FILE\" | cut -d_ -f1)\n"
        "echo \"##PROGRESS## $PLAN_ID | Phase: executing | 1/1\"\n"
        "echo \"Executing task $PLAN_ID\"\n"
        "sleep 0.5\n"
        "STATUS_FILE=\"${PLAN_FILE%.plan.md}.status\"\n"
        "echo \"STATUS: done\" > \"$STATUS_FILE\"\n"
        "echo \"COMMITS: none\" >> \"$STATUS_FILE\"\n"
        "echo \"TESTS_RAN: none\" >> \"$STATUS_FILE\"\n"
        "echo \"TEST_RESULT: skip\" >> \"$STATUS_FILE\"\n"
    )
    execute_script.chmod(0o755)

    session_id = "test-001"
    config = SessionConfig(
        pack_name="test-echo",
        session_name="Test Run",
        num_workers=2,
        poll_interval=1,
        task_idle_timeout=30,
        task_max_timeout=0,
        session_max_timeout=60,
    )

    store = StateStore(db_path=db_path)
    store.connect()
    store.create_session(
        Session(
            id=session_id,
            name="Test Run",
            pack_name="test-echo",
            config_json=json.dumps(config.__dict__),
            status=SessionStatus.CREATED,
            created_at=datetime.now(timezone.utc),
        )
    )

    dirs = session_subdirs(session_id)
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    for slot in range(2):
        (dirs["workers"] / str(slot)).mkdir(exist_ok=True)

    return store, session_id, dirs, config


class TestOrchestratorBasic:
    def test_no_tasks_completes_immediately(self, setup_session) -> None:
        store, session_id, _, _ = setup_session
        Orchestrator(session_id, store).run_foreground()
        assert store.get_session(session_id).status == SessionStatus.COMPLETED

    def test_single_task_dispatch_and_complete(self, setup_session) -> None:
        store, session_id, dirs, _ = setup_session
        plan_file = dirs["ready"] / "001_echo_test.plan.md"
        plan_file.write_text("---\nPLAN_ID: 001\n---\n# Plan 001: Echo Test\n")
        (dirs["ready"].parent / "resolution.json").write_text(
            json.dumps(
                {
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                    "tasks": [{"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 1}],
                    "groups": [],
                    "conflicts": [],
                }
            )
        )
        store.create_task(
            Task(
                id="001",
                session_id=session_id,
                title="Echo Test",
                status=TaskStatus.READY,
                plan_filename="001_echo_test.plan.md",
                created_at=datetime.now(timezone.utc),
            )
        )

        Orchestrator(session_id, store).run_foreground()
        assert store.get_task(session_id, "001").status == TaskStatus.DONE
        assert store.get_session(session_id).status == SessionStatus.COMPLETED
        assert not plan_file.exists()
        assert len(list(dirs["done"].glob("*.plan.md"))) == 1

    def test_two_tasks_parallel(self, setup_session) -> None:
        store, session_id, dirs, _ = setup_session
        for tid in ["001", "002"]:
            (dirs["ready"] / f"{tid}_echo.plan.md").write_text(f"---\nPLAN_ID: {tid}\n---\n# Plan {tid}\n")
            store.create_task(
                Task(
                    id=tid,
                    session_id=session_id,
                    title=f"Task {tid}",
                    status=TaskStatus.READY,
                    plan_filename=f"{tid}_echo.plan.md",
                    created_at=datetime.now(timezone.utc),
                )
            )

        (dirs["ready"].parent / "resolution.json").write_text(
            json.dumps(
                {
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                    "tasks": [
                        {"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 1},
                        {"task_id": "002", "depends_on": [], "anti_affinity": [], "exec_order": 1},
                    ],
                    "groups": [],
                    "conflicts": [],
                }
            )
        )

        Orchestrator(session_id, store).run_foreground()
        assert store.get_task(session_id, "001").status == TaskStatus.DONE
        assert store.get_task(session_id, "002").status == TaskStatus.DONE
        assert store.get_session(session_id).status == SessionStatus.COMPLETED

    def test_dependency_ordering(self, setup_session) -> None:
        store, session_id, dirs, _ = setup_session
        for tid in ["001", "002"]:
            (dirs["ready"] / f"{tid}_echo.plan.md").write_text(f"---\nPLAN_ID: {tid}\n---\n# Plan {tid}\n")
            store.create_task(
                Task(
                    id=tid,
                    session_id=session_id,
                    title=f"Task {tid}",
                    status=TaskStatus.READY,
                    plan_filename=f"{tid}_echo.plan.md",
                    depends_on=["001"] if tid == "002" else [],
                    created_at=datetime.now(timezone.utc),
                )
            )

        (dirs["ready"].parent / "resolution.json").write_text(
            json.dumps(
                {
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                    "tasks": [
                        {"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 1},
                        {"task_id": "002", "depends_on": ["001"], "anti_affinity": [], "exec_order": 2},
                    ],
                    "groups": [],
                    "conflicts": [],
                }
            )
        )

        Orchestrator(session_id, store).run_foreground()
        assert store.get_task(session_id, "001").status == TaskStatus.DONE
        assert store.get_task(session_id, "002").status == TaskStatus.DONE

        events = store.list_events(session_id, limit=100)
        dispatch_events = [event for event in events if event.event_type == EventType.TASK_DISPATCHED]
        complete_events = [event for event in events if event.event_type == EventType.TASK_COMPLETED]
        first_complete = next(event for event in complete_events if event.task_id == "001")
        second_dispatch = next(event for event in dispatch_events if event.task_id == "002")
        assert first_complete.timestamp <= second_dispatch.timestamp


class TestOrchestratorRecovery:
    def test_recovery_returns_orphaned_plan_to_ready(self, setup_session) -> None:
        store, session_id, dirs, _ = setup_session
        plan = dirs["workers"] / "0" / "001_orphan.plan.md"
        plan.write_text("---\nPLAN_ID: 001\n---\n# Plan 001\n")
        store.create_task(
            Task(
                id="001",
                session_id=session_id,
                title="Orphan",
                status=TaskStatus.ACTIVE,
                plan_filename="001_orphan.plan.md",
                created_at=datetime.now(timezone.utc),
            )
        )

        orchestrator = Orchestrator(session_id, store)
        orchestrator._initialize()
        orchestrator._run_recovery()
        assert (dirs["ready"] / "001_orphan.plan.md").exists()
        assert not plan.exists()
        assert store.get_task(session_id, "001").status == TaskStatus.READY

    def test_recovery_collects_completed_orphan(self, setup_session) -> None:
        store, session_id, dirs, _ = setup_session
        slot_dir = dirs["workers"] / "0"
        plan = slot_dir / "001_done.plan.md"
        plan.write_text("---\nPLAN_ID: 001\n---\n# Plan 001\n")
        (slot_dir / "001_done.status").write_text(
            "STATUS: done\nCOMMITS: abc\nTESTS_RAN: targeted\nTEST_RESULT: pass\n"
        )
        store.create_task(
            Task(
                id="001",
                session_id=session_id,
                title="Done Orphan",
                status=TaskStatus.ACTIVE,
                plan_filename="001_done.plan.md",
                created_at=datetime.now(timezone.utc),
            )
        )

        orchestrator = Orchestrator(session_id, store)
        orchestrator._initialize()
        orchestrator._run_recovery()
        assert (dirs["done"] / "001_done.plan.md").exists()
        assert not plan.exists()
