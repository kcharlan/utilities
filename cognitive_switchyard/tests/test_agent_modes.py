from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cognitive_switchyard.config import SessionConfig, session_dir, session_subdirs
from cognitive_switchyard.models import Session, SessionStatus, Task, TaskStatus
from cognitive_switchyard.orchestrator import Orchestrator
from cognitive_switchyard.state import StateStore


@pytest.fixture
def agent_env(tmp_path, monkeypatch):
    home = tmp_path / ".cognitive_switchyard"
    sessions = home / "sessions"
    packs = home / "packs"
    db_path = home / "cognitive_switchyard.db"

    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("cognitive_switchyard.config.SESSIONS_DIR", sessions)
    monkeypatch.setattr("cognitive_switchyard.config.PACKS_DIR", packs)
    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_DB", db_path)
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.SESSIONS_DIR", sessions)
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.PACKS_DIR", packs)
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.SWITCHYARD_DB", db_path)

    fake_agent = tmp_path / "fake-claude"
    fake_agent.write_text(
        """#!/usr/bin/env python3
import json
import os
import shutil
import sys
from pathlib import Path

prompt = ""
for index, arg in enumerate(sys.argv):
    if arg == "-p" and index + 1 < len(sys.argv):
        prompt = sys.argv[index + 1]
        break

context = {}
marker = "## SWITCHYARD_CONTEXT"
if marker in prompt:
    for raw_line in prompt.split(marker, 1)[1].splitlines():
        line = raw_line.strip()
        if not line or ": " not in line:
            continue
        key, value = line.split(": ", 1)
        context[key.strip()] = value.strip()

mode = context.get("MODE")
if mode == "planning":
    intake = Path(context["INTAKE_FILE"])
    target_dir = Path(context["REVIEW_DIR"] if "REVIEW_ME" in intake.read_text() else context["STAGING_DIR"])
    task_id = intake.stem.split("_", 1)[0]
    plan_path = target_dir / f"{intake.stem}.plan.md"
    plan_path.write_text(
        f"---\\nPLAN_ID: {task_id}\\nDEPENDS_ON: none\\nEXEC_ORDER: 1\\n---\\n# Plan {task_id}: Agent Planned\\n"
    )
    sys.exit(0)

if mode == "resolution":
    staging = Path(context["STAGING_DIR"])
    ready = Path(context["READY_DIR"])
    tasks = []
    for plan_path in sorted(staging.glob("*.plan.md")):
        task_id = plan_path.stem.split("_", 1)[0]
        shutil.move(str(plan_path), str(ready / plan_path.name))
        tasks.append({"task_id": task_id, "depends_on": [], "anti_affinity": [], "exec_order": 1})
    Path(context["RESOLUTION_PATH"]).write_text(
        json.dumps(
            {
                "resolved_at": "2026-03-07T00:00:00+00:00",
                "tasks": tasks,
                "groups": [],
                "conflicts": [],
                "notes": "fake agent resolution",
            }
        )
    )
    sys.exit(0)

if mode == "execution":
    task_id = context["TASK_ID"]
    print(f"##PROGRESS## {task_id} | Phase: implementing | 1/2")
    print(f"##PROGRESS## {task_id} | Detail: fake agent working")
    Path(context["STATUS_FILE"]).write_text(
        "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: none\\nTEST_RESULT: skip\\n"
    )
    sys.exit(0)

if mode == "auto_fix":
    session_dir = Path(context["SESSION_DIR"])
    session_dir.joinpath("agent-fix-called.txt").write_text(Path(context["CONTEXT_FILE"]).read_text())
    session_dir.joinpath("verified.ok").write_text("ok\\n")
    sys.exit(0)

print("unknown mode", file=sys.stderr)
sys.exit(1)
"""
    )
    fake_agent.chmod(0o755)
    monkeypatch.setenv("COGNITIVE_SWITCHYARD_AGENT_BIN", str(fake_agent))

    return packs, db_path


def _create_session(store: StateStore, session_id: str, pack_name: str, **overrides) -> None:
    config = SessionConfig(
        pack_name=pack_name,
        session_name=overrides.pop("session_name", "Agent Test"),
        num_workers=overrides.pop("num_workers", 1),
        num_planners=overrides.pop("num_planners", 1),
        poll_interval=overrides.pop("poll_interval", 1),
        verification_interval=overrides.pop("verification_interval", 1),
        auto_fix_enabled=overrides.pop("auto_fix_enabled", False),
        auto_fix_max_attempts=overrides.pop("auto_fix_max_attempts", 2),
        task_idle_timeout=overrides.pop("task_idle_timeout", 30),
        session_max_timeout=overrides.pop("session_max_timeout", 60),
        **overrides,
    )
    store.create_session(
        Session(
            id=session_id,
            name=config.session_name,
            pack_name=pack_name,
            config_json=json.dumps(config.__dict__),
            status=SessionStatus.CREATED,
            created_at=datetime.now(timezone.utc),
        )
    )


def test_agent_planning_and_resolution(agent_env) -> None:
    packs, db_path = agent_env
    pack_dir = packs / "agent-plan-pack"
    (pack_dir / "prompts").mkdir(parents=True)
    (pack_dir / "scripts").mkdir()
    (pack_dir / "pack.yaml").write_text(
        "name: agent-plan-pack\n"
        "description: Agent planning pack\n"
        "phases:\n"
        "  planning:\n"
        "    enabled: true\n"
        "    executor: agent\n"
        "    model: opus\n"
        "    prompt: prompts/planner.md\n"
        "  resolution:\n"
        "    enabled: true\n"
        "    executor: agent\n"
        "    model: opus\n"
        "    prompt: prompts/resolver.md\n"
        "  execution:\n"
        "    executor: shell\n"
        "    command: scripts/execute\n"
    )
    (pack_dir / "prompts" / "planner.md").write_text("Planner prompt\n")
    (pack_dir / "prompts" / "resolver.md").write_text("Resolver prompt\n")
    execute = pack_dir / "scripts" / "execute"
    execute.write_text("#!/bin/bash\nexit 0\n")
    execute.chmod(0o755)

    store = StateStore(db_path=db_path)
    store.connect()
    session_id = "agent-plan-001"
    _create_session(store, session_id, "agent-plan-pack")
    dirs = session_subdirs(session_id)
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    (dirs["intake"] / "001_first.md").write_text("Implement thing\n")

    try:
        orchestrator = Orchestrator(session_id, store)
        orchestrator._initialize()
        orchestrator._run_planning_phase()
        assert (dirs["staging"] / "001_first.plan.md").exists()

        orchestrator._run_resolution_phase()
        assert (dirs["ready"] / "001_first.plan.md").exists()
        resolution = json.loads((session_dir(session_id) / "resolution.json").read_text())
        assert resolution["tasks"][0]["task_id"] == "001"
        task = store.get_task(session_id, "001")
        assert task is not None
        assert task.status == TaskStatus.READY
    finally:
        store.close()


def test_agent_execution_dispatches_and_completes(agent_env) -> None:
    packs, db_path = agent_env
    pack_dir = packs / "agent-exec-pack"
    (pack_dir / "prompts").mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(
        "name: agent-exec-pack\n"
        "description: Agent execution pack\n"
        "phases:\n"
        "  planning:\n"
        "    enabled: false\n"
        "  resolution:\n"
        "    enabled: false\n"
        "  execution:\n"
        "    executor: agent\n"
        "    model: sonnet\n"
        "    prompt: prompts/worker.md\n"
        "    max_workers: 1\n"
    )
    (pack_dir / "prompts" / "worker.md").write_text("Worker prompt\n")

    store = StateStore(db_path=db_path)
    store.connect()
    session_id = "agent-exec-001"
    _create_session(store, session_id, "agent-exec-pack")
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
        task = store.get_task(session_id, "001")
        assert task is not None
        assert task.status == TaskStatus.DONE
        assert "fake agent working" in (session_dir(session_id) / "done" / "001_task.log").read_text()
    finally:
        store.close()


def test_agent_auto_fix_handles_verification_failure(agent_env) -> None:
    packs, db_path = agent_env
    pack_dir = packs / "agent-fix-pack"
    (pack_dir / "prompts").mkdir(parents=True)
    (pack_dir / "scripts").mkdir()
    (pack_dir / "pack.yaml").write_text(
        "name: agent-fix-pack\n"
        "description: Agent auto-fix pack\n"
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
        "  model: opus\n"
        "  prompt: prompts/fixer.md\n"
    )
    (pack_dir / "prompts" / "fixer.md").write_text("Fixer prompt\n")
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

    store = StateStore(db_path=db_path)
    store.connect()
    session_id = "agent-fix-001"
    _create_session(
        store,
        session_id,
        "agent-fix-pack",
        auto_fix_enabled=True,
        auto_fix_max_attempts=2,
        verification_interval=1,
    )
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
        assert (session_dir(session_id) / "agent-fix-called.txt").exists()
    finally:
        store.close()
