from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from cognitive_switchyard.config import SessionConfig, session_dir, session_subdirs
from cognitive_switchyard.models import Session, SessionStatus, Task, TaskStatus
from cognitive_switchyard.orchestrator import Orchestrator
from cognitive_switchyard.resolution import parse_list_field, parse_plan_frontmatter, resolve_passthrough
from cognitive_switchyard.state import StateStore


def test_parse_list_field() -> None:
    assert parse_list_field("none") == []
    assert parse_list_field("001, 002") == ["001", "002"]
    assert parse_list_field(["001", "002"]) == ["001", "002"]


def test_parse_plan_frontmatter(tmp_path) -> None:
    plan = tmp_path / "001_example.plan.md"
    plan.write_text("---\nPLAN_ID: 001\nDEPENDS_ON: 002, 003\nEXEC_ORDER: 2\n---\n# Plan 001\n")
    metadata = parse_plan_frontmatter(plan)
    assert metadata["PLAN_ID"] == "001"
    assert metadata["DEPENDS_ON"] == "002, 003"
    assert metadata["EXEC_ORDER"] == "2"


def test_resolve_passthrough_moves_plans_and_writes_resolution(tmp_path) -> None:
    staging = tmp_path / "staging"
    ready = tmp_path / "ready"
    staging.mkdir()
    ready.mkdir()
    resolution_path = tmp_path / "resolution.json"
    (staging / "001_alpha.plan.md").write_text(
        "---\nPLAN_ID: 001\nDEPENDS_ON: none\nANTI_AFFINITY: 002\nEXEC_ORDER: 1\n---\n# Plan 001: Alpha\n"
    )
    (staging / "002_beta.plan.md").write_text(
        "---\nPLAN_ID: 002\nDEPENDS_ON: 001\nANTI_AFFINITY: none\nEXEC_ORDER: 2\n---\n# Plan 002: Beta\n"
    )

    resolution = resolve_passthrough(staging, ready, resolution_path)
    assert resolution_path.exists()
    assert len(list(ready.glob("*.plan.md"))) == 2
    assert list(staging.glob("*.plan.md")) == []
    assert resolution["tasks"][0]["anti_affinity"] == ["002"]
    assert resolution["tasks"][1]["depends_on"] == ["001"]


@pytest.fixture
def resolution_env(tmp_path, monkeypatch):
    home = tmp_path / ".cognitive_switchyard"
    sessions = home / "sessions"
    packs = home / "packs"
    db_path = home / "cognitive_switchyard.db"

    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("cognitive_switchyard.config.SESSIONS_DIR", sessions)
    monkeypatch.setattr("cognitive_switchyard.config.PACKS_DIR", packs)
    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_DB", db_path)
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.PACKS_DIR", packs)

    pack_dir = packs / "test-resolve"
    (pack_dir / "scripts").mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(
        "name: test-resolve\n"
        "description: Test resolver pack\n"
        "phases:\n"
        "  planning:\n"
        "    enabled: false\n"
        "  resolution:\n"
        "    enabled: true\n"
        "    executor: passthrough\n"
        "  execution:\n"
        "    executor: shell\n"
        "    command: scripts/execute\n"
    )
    execute = pack_dir / "scripts" / "execute"
    execute.write_text("#!/bin/bash\nexit 0\n")
    execute.chmod(0o755)

    store = StateStore(db_path=db_path)
    store.connect()
    session_id = "resolve-001"
    config = SessionConfig(pack_name="test-resolve", session_name="Resolution Test", num_workers=1, poll_interval=1)
    store.create_session(
        Session(
            id=session_id,
            name="Resolution Test",
            pack_name="test-resolve",
            config_json=json.dumps(config.__dict__),
            status=SessionStatus.CREATED,
            created_at=datetime.now(timezone.utc),
        )
    )
    dirs = session_subdirs(session_id)
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    yield store, session_id, dirs
    store.close()


class TestResolutionPhase:
    def test_orchestrator_resolution_updates_db(self, resolution_env) -> None:
        store, session_id, dirs = resolution_env
        (dirs["staging"] / "001_alpha.plan.md").write_text(
            "---\nPLAN_ID: 001\nDEPENDS_ON: none\nANTI_AFFINITY: 002\nEXEC_ORDER: 1\n---\n# Plan 001: Alpha\n"
        )
        (dirs["staging"] / "002_beta.plan.md").write_text(
            "---\nPLAN_ID: 002\nDEPENDS_ON: 001\nANTI_AFFINITY: none\nEXEC_ORDER: 2\n---\n# Plan 002: Beta\n"
        )
        store.create_task(Task(id="001", session_id=session_id, title="Alpha", status=TaskStatus.STAGED, created_at=datetime.now(timezone.utc)))
        store.create_task(Task(id="002", session_id=session_id, title="Beta", status=TaskStatus.STAGED, created_at=datetime.now(timezone.utc)))

        orchestrator = Orchestrator(session_id, store)
        orchestrator._initialize()
        orchestrator._run_resolution_phase()

        assert (session_dir(session_id) / "resolution.json").exists()
        task1 = store.get_task(session_id, "001")
        task2 = store.get_task(session_id, "002")
        assert task1.status == TaskStatus.READY
        assert task1.anti_affinity == ["002"]
        assert task2.status == TaskStatus.READY
        assert task2.depends_on == ["001"]
