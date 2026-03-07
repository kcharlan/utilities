from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pytest

from cognitive_switchyard.config import SessionConfig, session_subdirs
from cognitive_switchyard.models import Session, SessionStatus, TaskStatus
from cognitive_switchyard.orchestrator import Orchestrator
from cognitive_switchyard.state import StateStore


@pytest.fixture
def planning_env(tmp_path, monkeypatch):
    home = tmp_path / ".cognitive_switchyard"
    sessions = home / "sessions"
    packs = home / "packs"
    db_path = home / "cognitive_switchyard.db"

    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("cognitive_switchyard.config.SESSIONS_DIR", sessions)
    monkeypatch.setattr("cognitive_switchyard.config.PACKS_DIR", packs)
    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_DB", db_path)
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.PACKS_DIR", packs)

    pack_dir = packs / "test-plan"
    (pack_dir / "scripts").mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(
        "name: test-plan\n"
        "description: Test planning pack\n"
        "phases:\n"
        "  planning:\n"
        "    enabled: true\n"
        "    executor: script\n"
        "    script: scripts/plan\n"
        "    max_instances: 3\n"
        "  resolution:\n"
        "    enabled: false\n"
        "  execution:\n"
        "    executor: shell\n"
        "    command: scripts/execute\n"
    )
    (pack_dir / "scripts" / "execute").write_text("#!/bin/bash\nexit 0\n")
    (pack_dir / "scripts" / "execute").chmod(0o755)
    planner_script = pack_dir / "scripts" / "plan"
    planner_script.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "INPUT=\"$1\"\n"
        "STAGING=\"$2\"\n"
        "REVIEW=\"$3\"\n"
        "BASE=$(basename \"$INPUT\" .md)\n"
        "MARKER=\"$STAGING/${BASE}.marker\"\n"
        "touch \"$MARKER\"\n"
        "EXPECTED=$(sed -n 's/^PARALLEL_BATCH=//p' \"$INPUT\" | head -1)\n"
        "if [ -n \"$EXPECTED\" ]; then\n"
        "  END_TIME=$((SECONDS+2))\n"
        "  while [ \"$(find \"$STAGING\" -name '*.marker' | wc -l | tr -d ' ')\" -lt \"$EXPECTED\" ]; do\n"
        "    [ \"$SECONDS\" -ge \"$END_TIME\" ] && break\n"
        "    sleep 0.05\n"
        "  done\n"
        "fi\n"
        "if grep -q 'REVIEW_ME' \"$INPUT\"; then\n"
        "  cat > \"$REVIEW/${BASE}.plan.md\" <<EOF\n"
        "---\nPLAN_ID: ${BASE%%_*}\n---\n# Plan ${BASE%%_*}: Needs Review\nEOF\n"
        "else\n"
        "  cat > \"$STAGING/${BASE}.plan.md\" <<EOF\n"
        "---\nPLAN_ID: ${BASE%%_*}\nDEPENDS_ON: none\nEXEC_ORDER: 1\n---\n# Plan ${BASE%%_*}: Planned Task\nEOF\n"
        "fi\n"
        "rm -f \"$MARKER\"\n"
    )
    planner_script.chmod(0o755)

    store = StateStore(db_path=db_path)
    store.connect()
    session_id = "planning-001"
    config = SessionConfig(pack_name="test-plan", session_name="Planning Test", num_workers=1, poll_interval=1)
    store.create_session(
        Session(
            id=session_id,
            name="Planning Test",
            pack_name="test-plan",
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


class TestPlanningPhase:
    def test_planning_moves_intake_to_staging(self, planning_env) -> None:
        store, session_id, dirs = planning_env
        (dirs["intake"] / "001_first.md").write_text("Implement thing\n")

        orchestrator = Orchestrator(session_id, store)
        orchestrator._initialize()
        orchestrator._run_planning_phase()

        staged = list(dirs["staging"].glob("*.plan.md"))
        assert len(staged) == 1
        assert not list(dirs["intake"].glob("*.md"))
        assert not list(dirs["claimed"].glob("*.md"))
        task = store.get_task(session_id, "001")
        assert task is not None
        assert task.status == TaskStatus.STAGED
        assert task.plan_filename == "001_first.plan.md"

    def test_planning_can_route_to_review(self, planning_env) -> None:
        store, session_id, dirs = planning_env
        (dirs["intake"] / "002_review.md").write_text("REVIEW_ME\n")

        orchestrator = Orchestrator(session_id, store)
        orchestrator._initialize()
        orchestrator._run_planning_phase()

        review = list(dirs["review"].glob("*.plan.md"))
        assert len(review) == 1
        task = store.get_task(session_id, "002")
        assert task is not None
        assert task.status == TaskStatus.REVIEW

    def test_planning_runs_in_parallel_batches(self, planning_env) -> None:
        store, session_id, dirs = planning_env
        for idx in range(3):
            (dirs["intake"] / f"00{idx + 1}_parallel.md").write_text("PARALLEL_BATCH=3\n")

        orchestrator = Orchestrator(session_id, store)
        orchestrator._initialize()

        started = time.monotonic()
        orchestrator._run_planning_phase()
        elapsed = time.monotonic() - started

        assert elapsed < 1.0
        assert len(list(dirs["staging"].glob("*.plan.md"))) == 3
