from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from cognitive_switchyard.config import SessionConfig, session_dir, session_subdirs
from cognitive_switchyard.models import EventType, Session, SessionStatus, Task, TaskStatus
from cognitive_switchyard.orchestrator import Orchestrator
from cognitive_switchyard.state import StateStore


@pytest.fixture
def autofix_env(tmp_path, monkeypatch):
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


def _create_session(store: StateStore, session_id: str, pack_name: str) -> None:
    config = SessionConfig(
        pack_name=pack_name,
        session_name="Auto Fix Test",
        num_workers=1,
        poll_interval=1,
        verification_interval=1,
        auto_fix_enabled=True,
        auto_fix_max_attempts=2,
        task_idle_timeout=30,
        session_max_timeout=60,
    )
    store.create_session(
        Session(
            id=session_id,
            name="Auto Fix Test",
            pack_name=pack_name,
            config_json=json.dumps(config.__dict__),
            status=SessionStatus.CREATED,
            created_at=datetime.now(timezone.utc),
        )
    )


class TestAutoFix:
    def test_task_failure_can_be_requeued_by_fixer(self, autofix_env) -> None:
        _, _, packs, db_path = autofix_env
        pack_dir = packs / "fix-task-pack"
        (pack_dir / "scripts").mkdir(parents=True)
        (pack_dir / "pack.yaml").write_text(
            "name: fix-task-pack\n"
            "description: Task auto-fix test\n"
            "phases:\n"
            "  planning:\n"
            "    enabled: false\n"
            "  resolution:\n"
            "    enabled: false\n"
            "  execution:\n"
            "    executor: shell\n"
            "    command: scripts/execute\n"
            "    max_workers: 1\n"
            "auto_fix:\n"
            "  enabled: true\n"
            "  max_attempts: 2\n"
            "  script: scripts/fix\n"
        )
        execute = pack_dir / "scripts" / "execute"
        execute.write_text(
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            "PLAN_FILE=\"$1\"\n"
            "WORKSPACE=\"$2\"\n"
            "MARKER=\"$WORKSPACE/.fixed\"\n"
            "if [ ! -f \"$MARKER\" ]; then\n"
            "  cat > \"${PLAN_FILE%.plan.md}.status\" <<EOF\n"
            "STATUS: blocked\n"
            "COMMITS: none\n"
            "TESTS_RAN: none\n"
            "TEST_RESULT: fail\n"
            "BLOCKED_REASON: first run failure\n"
            "EOF\n"
            "  exit 1\n"
            "fi\n"
            "cat > \"${PLAN_FILE%.plan.md}.status\" <<EOF\n"
            "STATUS: done\n"
            "COMMITS: none\n"
            "TESTS_RAN: none\n"
            "TEST_RESULT: skip\n"
            "EOF\n"
        )
        execute.chmod(0o755)
        fixer = pack_dir / "scripts" / "fix"
        fixer.write_text(
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            "CONTEXT=\"$1\"\n"
            "SESSION_DIR=\"$2\"\n"
            "SOURCE_DIR=\"$4\"\n"
            "touch \"$SOURCE_DIR/.fixed\"\n"
            "echo \"$CONTEXT\" > \"$SESSION_DIR/fixer-called.txt\"\n"
        )
        fixer.chmod(0o755)

        store = StateStore(db_path=db_path)
        store.connect()
        session_id = "fix-task-001"
        _create_session(store, session_id, "fix-task-pack")
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
            assert store.get_task(session_id, "001").status == TaskStatus.DONE
            events = store.list_events(session_id, limit=50)
            assert any(event.event_type == EventType.FIX_SUCCEEDED for event in events)
            assert (session_dir(session_id) / "fixer-called.txt").exists()
        finally:
            store.close()

    def test_verification_auto_fix_enriches_context_between_attempts(self, autofix_env) -> None:
        _, _, packs, db_path = autofix_env
        pack_dir = packs / "fix-verify-pack"
        (pack_dir / "scripts").mkdir(parents=True)
        (pack_dir / "pack.yaml").write_text(
            "name: fix-verify-pack\n"
            "description: Verification auto-fix test\n"
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
            "    interval: 1\n"
            "auto_fix:\n"
            "  enabled: true\n"
            "  max_attempts: 2\n"
            "  script: scripts/fix\n"
        )
        execute = pack_dir / "scripts" / "execute"
        execute.write_text(
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            "PLAN_FILE=\"$1\"\n"
            "cat > \"${PLAN_FILE%.plan.md}.status\" <<EOF\n"
            "STATUS: done\n"
            "COMMITS: none\n"
            "TESTS_RAN: none\n"
            "TEST_RESULT: skip\n"
            "EOF\n"
        )
        execute.chmod(0o755)
        verify = pack_dir / "scripts" / "verify"
        verify.write_text(
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            "SESSION_DIR=\"$1\"\n"
            "if [ -f \"$SESSION_DIR/verified.ok\" ]; then\n"
            "  exit 0\n"
            "fi\n"
            "echo 'verify still failing' >&2\n"
            "exit 1\n"
        )
        verify.chmod(0o755)
        fixer = pack_dir / "scripts" / "fix"
        fixer.write_text(
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            "CONTEXT=\"$1\"\n"
            "SESSION_DIR=\"$2\"\n"
            "SOURCE_DIR=\"$4\"\n"
            "COUNT_FILE=\"$SESSION_DIR/fix-count.txt\"\n"
            "COUNT=0\n"
            "if [ -f \"$COUNT_FILE\" ]; then COUNT=$(cat \"$COUNT_FILE\"); fi\n"
            "COUNT=$((COUNT+1))\n"
            "echo \"$COUNT\" > \"$COUNT_FILE\"\n"
            "cp \"$CONTEXT\" \"$SESSION_DIR/context-$COUNT.txt\"\n"
            "if [ \"$COUNT\" -eq 1 ]; then\n"
            "  echo 'first fixer failure' >&2\n"
            "  exit 1\n"
            "fi\n"
            "touch \"$SESSION_DIR/verified.ok\"\n"
        )
        fixer.chmod(0o755)

        store = StateStore(db_path=db_path)
        store.connect()
        session_id = "fix-verify-001"
        _create_session(store, session_id, "fix-verify-pack")
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
            assert store.get_session(session_id).status == SessionStatus.COMPLETED
            first = (session_dir(session_id) / "context-1.txt").read_text()
            second = (session_dir(session_id) / "context-2.txt").read_text()
            assert "verify still failing" in first
            assert "PREVIOUS_ATTEMPT_CONTEXT" in second
            assert "first fixer failure" in second
        finally:
            store.close()
