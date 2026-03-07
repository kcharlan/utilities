from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from cognitive_switchyard.config import SessionConfig, session_dir, session_subdirs
from cognitive_switchyard.models import EventType, Session, SessionStatus, Task, TaskStatus
from cognitive_switchyard.orchestrator import Orchestrator
from cognitive_switchyard.state import StateStore


@pytest.fixture
def verification_env(tmp_path, monkeypatch):
    home = tmp_path / ".cognitive_switchyard"
    sessions = home / "sessions"
    packs = home / "packs"
    db_path = home / "cognitive_switchyard.db"

    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("cognitive_switchyard.config.SESSIONS_DIR", sessions)
    monkeypatch.setattr("cognitive_switchyard.config.PACKS_DIR", packs)
    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_DB", db_path)
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.PACKS_DIR", packs)

    yield home, sessions, packs, db_path


def _write_execution_pack(pack_dir, verification_script_body: str, verification_interval: int = 1) -> None:
    (pack_dir / "scripts").mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(
        "name: verify-pack\n"
        "description: Verification test pack\n"
        "phases:\n"
        "  planning:\n"
        "    enabled: false\n"
        "  resolution:\n"
        "    enabled: false\n"
        "  execution:\n"
        "    executor: shell\n"
        "    command: scripts/execute\n"
        "    max_workers: 1\n"
        "  verification:\n"
        "    enabled: true\n"
        "    command: scripts/verify\n"
        f"    interval: {verification_interval}\n"
    )
    execute = pack_dir / "scripts" / "execute"
    execute.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "PLAN_FILE=\"$1\"\n"
        "PLAN_ID=$(basename \"$PLAN_FILE\" | cut -d_ -f1)\n"
        "sleep 0.2\n"
        "cat > \"${PLAN_FILE%.plan.md}.status\" <<EOF\n"
        "STATUS: done\n"
        "COMMITS: none\n"
        "TESTS_RAN: none\n"
        "TEST_RESULT: skip\n"
        "EOF\n"
        "echo \"##PROGRESS## $PLAN_ID | Detail: complete\"\n"
    )
    execute.chmod(0o755)
    verify = pack_dir / "scripts" / "verify"
    verify.write_text(verification_script_body)
    verify.chmod(0o755)


def _create_session(
    store: StateStore,
    session_id: str,
    pack_name: str,
    verification_interval: int = 1,
) -> SessionConfig:
    config = SessionConfig(
        pack_name=pack_name,
        session_name="Verification Test",
        num_workers=1,
        poll_interval=1,
        verification_interval=verification_interval,
        task_idle_timeout=30,
        session_max_timeout=60,
    )
    store.create_session(
        Session(
            id=session_id,
            name="Verification Test",
            pack_name=pack_name,
            config_json=json.dumps(config.__dict__),
            status=SessionStatus.CREATED,
            created_at=datetime.now(timezone.utc),
        )
    )
    return config


class TestVerificationPhase:
    def test_verification_runs_before_next_dispatch(self, verification_env) -> None:
        home, _, packs, db_path = verification_env
        pack_dir = packs / "verify-pack"
        _write_execution_pack(
            pack_dir,
            "#!/bin/bash\nset -euo pipefail\nSESSION_DIR=\"$1\"\n"
            "COUNT_FILE=\"$SESSION_DIR/verify-count.txt\"\n"
            "COUNT=0\n"
            "if [ -f \"$COUNT_FILE\" ]; then COUNT=$(cat \"$COUNT_FILE\"); fi\n"
            "COUNT=$((COUNT+1))\n"
            "echo \"$COUNT\" > \"$COUNT_FILE\"\n",
        )

        store = StateStore(db_path=db_path)
        store.connect()
        session_id = "verify-001"
        _create_session(store, session_id, "verify-pack")
        dirs = session_subdirs(session_id)
        for directory in dirs.values():
            directory.mkdir(parents=True, exist_ok=True)
        for tid in ["001", "002"]:
            (dirs["ready"] / f"{tid}_task.plan.md").write_text(f"---\nPLAN_ID: {tid}\n---\n# Plan {tid}: Task\n")
            store.create_task(
                Task(
                    id=tid,
                    session_id=session_id,
                    title=f"Task {tid}",
                    status=TaskStatus.READY,
                    plan_filename=f"{tid}_task.plan.md",
                    created_at=datetime.now(timezone.utc),
                )
            )

        try:
            Orchestrator(session_id, store).run_foreground()
            count_file = session_dir(session_id) / "verify-count.txt"
            assert count_file.exists()
            assert int(count_file.read_text().strip()) >= 1

            events = store.list_events(session_id, limit=50)
            second_dispatch = next(event for event in events if event.event_type == EventType.TASK_DISPATCHED and event.task_id == "002")
            verify_events = [event for event in events if event.event_type == EventType.VERIFICATION_STARTED]
            assert any(event.timestamp <= second_dispatch.timestamp for event in verify_events)
            assert store.get_session(session_id).status == SessionStatus.COMPLETED
        finally:
            store.close()

    def test_verification_failure_aborts_session(self, verification_env) -> None:
        _, _, packs, db_path = verification_env
        pack_dir = packs / "verify-pack"
        _write_execution_pack(
            pack_dir,
            "#!/bin/bash\nset -euo pipefail\n"
            "echo 'verification failed' >&2\n"
            "exit 1\n",
        )

        store = StateStore(db_path=db_path)
        store.connect()
        session_id = "verify-002"
        _create_session(store, session_id, "verify-pack")
        dirs = session_subdirs(session_id)
        for directory in dirs.values():
            directory.mkdir(parents=True, exist_ok=True)
        (dirs["ready"] / "001_task.plan.md").write_text("---\nPLAN_ID: 001\n---\n# Plan 001: Task\n")
        store.create_task(
            Task(
                id="001",
                session_id=session_id,
                title="Task 001",
                status=TaskStatus.READY,
                plan_filename="001_task.plan.md",
                created_at=datetime.now(timezone.utc),
            )
        )

        try:
            Orchestrator(session_id, store).run_foreground()
            session = store.get_session(session_id)
            assert session.status == SessionStatus.ABORTED
            assert "verification failed" in (session.abort_reason or "")
        finally:
            store.close()

    def test_full_test_after_forces_verification_before_next_dispatch(self, verification_env) -> None:
        home, _, packs, db_path = verification_env
        pack_dir = packs / "verify-pack"
        _write_execution_pack(
            pack_dir,
            "#!/bin/bash\nset -euo pipefail\nSESSION_DIR=\"$1\"\n"
            "COUNT_FILE=\"$SESSION_DIR/verify-count.txt\"\n"
            "COUNT=0\n"
            "if [ -f \"$COUNT_FILE\" ]; then COUNT=$(cat \"$COUNT_FILE\"); fi\n"
            "COUNT=$((COUNT+1))\n"
            "echo \"$COUNT\" > \"$COUNT_FILE\"\n",
            verification_interval=99,
        )

        store = StateStore(db_path=db_path)
        store.connect()
        session_id = "verify-003"
        _create_session(store, session_id, "verify-pack", verification_interval=99)
        dirs = session_subdirs(session_id)
        for directory in dirs.values():
            directory.mkdir(parents=True, exist_ok=True)
        (dirs["ready"] / "001_task.plan.md").write_text(
            "---\nPLAN_ID: 001\nFULL_TEST_AFTER: yes\n---\n# Plan 001: Force Verify\n"
        )
        (dirs["ready"] / "002_task.plan.md").write_text(
            "---\nPLAN_ID: 002\nFULL_TEST_AFTER: no\n---\n# Plan 002: Followup\n"
        )
        for tid in ["001", "002"]:
            store.create_task(
                Task(
                    id=tid,
                    session_id=session_id,
                    title=f"Task {tid}",
                    status=TaskStatus.READY,
                    plan_filename=f"{tid}_task.plan.md",
                    created_at=datetime.now(timezone.utc),
                )
            )

        try:
            Orchestrator(session_id, store).run_foreground()
            events = store.list_events(session_id, limit=50)
            second_dispatch = next(
                event for event in events if event.event_type == EventType.TASK_DISPATCHED and event.task_id == "002"
            )
            verify_events = [event for event in events if event.event_type == EventType.VERIFICATION_STARTED]
            assert any(event.timestamp <= second_dispatch.timestamp for event in verify_events)
        finally:
            store.close()

    def test_final_verification_runs_before_completion(self, verification_env) -> None:
        home, _, packs, db_path = verification_env
        pack_dir = packs / "verify-pack"
        _write_execution_pack(
            pack_dir,
            "#!/bin/bash\nset -euo pipefail\nSESSION_DIR=\"$1\"\n"
            "COUNT_FILE=\"$SESSION_DIR/verify-count.txt\"\n"
            "COUNT=0\n"
            "if [ -f \"$COUNT_FILE\" ]; then COUNT=$(cat \"$COUNT_FILE\"); fi\n"
            "COUNT=$((COUNT+1))\n"
            "echo \"$COUNT\" > \"$COUNT_FILE\"\n",
            verification_interval=99,
        )

        store = StateStore(db_path=db_path)
        store.connect()
        session_id = "verify-004"
        _create_session(store, session_id, "verify-pack", verification_interval=99)
        dirs = session_subdirs(session_id)
        for directory in dirs.values():
            directory.mkdir(parents=True, exist_ok=True)
        (dirs["ready"] / "001_task.plan.md").write_text("---\nPLAN_ID: 001\n---\n# Plan 001: Final Verify\n")
        store.create_task(
            Task(
                id="001",
                session_id=session_id,
                title="Task 001",
                status=TaskStatus.READY,
                plan_filename="001_task.plan.md",
                created_at=datetime.now(timezone.utc),
            )
        )

        try:
            Orchestrator(session_id, store).run_foreground()
            count_file = session_dir(session_id) / "verify-count.txt"
            assert count_file.exists()
            assert int(count_file.read_text().strip()) == 1
            assert store.get_session(session_id).status == SessionStatus.COMPLETED
        finally:
            store.close()
