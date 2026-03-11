from __future__ import annotations

from pathlib import Path

from cognitive_switchyard.config import build_runtime_paths, session_subdirs


def test_runtime_paths_use_canonical_cognitive_switchyard_names(tmp_path: Path) -> None:
    paths = build_runtime_paths(home=tmp_path)

    assert paths.home == tmp_path / ".cognitive_switchyard"
    assert paths.bootstrap_venv == tmp_path / ".cognitive_switchyard_venv"
    assert paths.database == tmp_path / ".cognitive_switchyard" / "cognitive_switchyard.db"
    assert paths.config == tmp_path / ".cognitive_switchyard" / "config.yaml"
    assert paths.packs == tmp_path / ".cognitive_switchyard" / "packs"
    assert paths.sessions == tmp_path / ".cognitive_switchyard" / "sessions"
    assert paths.session("session-123") == tmp_path / ".cognitive_switchyard" / "sessions" / "session-123"


def test_session_subdirs_match_design_doc_exactly() -> None:
    assert session_subdirs() == (
        "intake",
        "claimed",
        "staging",
        "review",
        "ready",
        "workers",
        "done",
        "blocked",
        "logs",
        "logs/workers",
    )


def test_session_paths_expose_reserved_artifact_locations(tmp_path: Path) -> None:
    runtime_paths = build_runtime_paths(home=tmp_path)
    session_paths = runtime_paths.session_paths("session-123")

    assert session_paths.root == tmp_path / ".cognitive_switchyard" / "sessions" / "session-123"
    assert session_paths.resolution == session_paths.root / "resolution.json"
    assert session_paths.session_log == session_paths.logs / "session.log"
    assert session_paths.verify_log == session_paths.logs / "verify.log"
    assert session_paths.worker_dir(1) == session_paths.workers / "1"
    assert session_paths.worker_log(1) == session_paths.worker_logs / "1.log"
    assert session_paths.plan_path("039", status="ready") == session_paths.ready / "039.plan.md"
    assert (
        session_paths.plan_path("039", status="active", worker_slot=1)
        == session_paths.workers / "1" / "039.plan.md"
    )
