from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cognitive_switchyard.config import SessionConfig, session_dir, session_subdirs
from cognitive_switchyard.models import Session, SessionStatus, Task, TaskStatus
from cognitive_switchyard.orchestrator import Orchestrator
from cognitive_switchyard.state import StateStore


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    home = tmp_path / ".cognitive_switchyard"
    sessions = home / "sessions"
    packs = home / "packs"
    db_path = home / "cognitive_switchyard.db"

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "branch", "-M", "dev"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "demo.txt").write_text("base\n")
    subprocess.run(["git", "add", "demo.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    monkeypatch.chdir(repo)
    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("cognitive_switchyard.config.SESSIONS_DIR", sessions)
    monkeypatch.setattr("cognitive_switchyard.config.PACKS_DIR", packs)
    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_DB", db_path)
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.PACKS_DIR", packs)

    pack_dir = packs / "isolated-pack"
    scripts_dir = pack_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    reference_scripts = Path(__file__).resolve().parent.parent / "packs" / "claude-code" / "scripts"
    shutil.copy2(reference_scripts / "isolate_start", scripts_dir / "isolate_start")
    shutil.copy2(reference_scripts / "isolate_end", scripts_dir / "isolate_end")
    (scripts_dir / "isolate_start").chmod(0o755)
    (scripts_dir / "isolate_end").chmod(0o755)
    (scripts_dir / "execute").write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "PLAN_FILE=\"$1\"\n"
        "STATUS_FILE=\"${PLAN_FILE%.plan.md}.status\"\n"
        "if grep -q 'BLOCK_ME' \"$PLAN_FILE\"; then\n"
        "  cat > \"$STATUS_FILE\" <<EOF\n"
        "STATUS: blocked\n"
        "COMMITS: none\n"
        "TESTS_RAN: none\n"
        "TEST_RESULT: fail\n"
        "BLOCKED_REASON: synthetic blocker\n"
        "EOF\n"
        "  exit 1\n"
        "fi\n"
        "cat > \"$STATUS_FILE\" <<EOF\n"
        "STATUS: done\n"
        "COMMITS: none\n"
        "TESTS_RAN: none\n"
        "TEST_RESULT: pass\n"
        "EOF\n"
    )
    (scripts_dir / "execute").chmod(0o755)
    (pack_dir / "pack.yaml").write_text(
        "name: isolated-pack\n"
        "description: Isolated execution test pack\n"
        "phases:\n"
        "  planning:\n"
        "    enabled: false\n"
        "  resolution:\n"
        "    enabled: false\n"
        "  execution:\n"
        "    executor: shell\n"
        "    command: scripts/execute\n"
        "    max_workers: 1\n"
        "isolation:\n"
        "  type: git-worktree\n"
        "  setup: scripts/isolate_start\n"
        "  teardown: scripts/isolate_end\n"
    )

    store = StateStore(db_path=db_path)
    store.connect()
    yield store, repo
    store.close()


def _create_session(store: StateStore, session_id: str, pack_name: str) -> None:
    config = SessionConfig(
        pack_name=pack_name,
        session_name="Isolated Runtime Test",
        num_workers=1,
        poll_interval=1,
        task_idle_timeout=30,
        session_max_timeout=60,
    )
    store.create_session(
        Session(
            id=session_id,
            name="Isolated Runtime Test",
            pack_name=pack_name,
            config_json=json.dumps(config.__dict__),
            status=SessionStatus.CREATED,
            created_at=datetime.now(timezone.utc),
        )
    )
    dirs = session_subdirs(session_id)
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    (dirs["workers"] / "0").mkdir(parents=True, exist_ok=True)


def test_blocked_tasks_preserve_worktrees(isolated_env) -> None:
    store, _ = isolated_env
    session_id = "isolated-001"
    _create_session(store, session_id, "isolated-pack")
    dirs = session_subdirs(session_id)
    (dirs["ready"] / "001_task.plan.md").write_text("---\nPLAN_ID: 001\n---\n# Plan 001\nBLOCK_ME\n")
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

    Orchestrator(session_id, store).run_foreground()

    worktree_root = session_dir(session_id) / "worktrees"
    assert worktree_root.exists()
    assert any(worktree_root.iterdir())
    assert (dirs["blocked"] / "001_task.plan.md").exists()
    assert store.get_task(session_id, "001").status == TaskStatus.BLOCKED


def test_recovery_returns_isolated_work_to_ready_and_cleans_worktrees(isolated_env) -> None:
    store, repo = isolated_env
    session_id = "isolated-002"
    _create_session(store, session_id, "isolated-pack")
    dirs = session_subdirs(session_id)
    slot_dir = dirs["workers"] / "0"
    plan_path = slot_dir / "001_task.plan.md"
    plan_path.write_text("---\nPLAN_ID: 001\n---\n# Plan 001\n")
    (slot_dir / "001_task.status").write_text(
        "STATUS: done\nCOMMITS: none\nTESTS_RAN: none\nTEST_RESULT: pass\n"
    )
    store.create_task(
        Task(
            id="001",
            session_id=session_id,
            title="Task 001",
            status=TaskStatus.ACTIVE,
            plan_filename="001_task.plan.md",
            created_at=datetime.now(timezone.utc),
        )
    )

    start = subprocess.run(
        [
            str(Path(__file__).resolve().parent.parent / "packs" / "claude-code" / "scripts" / "isolate_start"),
            "0",
            "001",
            str(session_dir(session_id)),
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    worktree = Path(start.stdout.strip())
    assert worktree.exists()

    orchestrator = Orchestrator(session_id, store)
    orchestrator._initialize()
    orchestrator._run_recovery()

    assert (dirs["ready"] / "001_task.plan.md").exists()
    assert not worktree.exists()
    assert store.get_task(session_id, "001").status == TaskStatus.READY
