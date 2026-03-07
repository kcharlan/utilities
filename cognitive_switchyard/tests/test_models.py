from __future__ import annotations

from cognitive_switchyard.models import Constraint, SessionStatus, StatusSidecar, Task, TaskStatus


def test_session_status_values() -> None:
    assert SessionStatus.CREATED == "created"
    assert SessionStatus.RUNNING == "running"
    assert SessionStatus.COMPLETED == "completed"


def test_task_defaults() -> None:
    task = Task(id="001", session_id="s1", title="Test", status=TaskStatus.READY)
    assert task.depends_on == []
    assert task.anti_affinity == []
    assert task.exec_order == 1
    assert task.worker_slot is None


def test_status_sidecar_parse_done() -> None:
    sidecar = StatusSidecar.parse(
        "STATUS: done\n"
        "COMMITS: abc123,def456\n"
        "TESTS_RAN: targeted\n"
        "TEST_RESULT: pass\n"
        "NOTES: All good\n"
    )
    assert sidecar.status == "done"
    assert sidecar.commits == "abc123,def456"
    assert sidecar.tests_ran == "targeted"
    assert sidecar.test_result == "pass"
    assert sidecar.notes == "All good"


def test_status_sidecar_parse_blocked() -> None:
    sidecar = StatusSidecar.parse(
        "STATUS: blocked\n"
        "COMMITS: none\n"
        "TESTS_RAN: targeted\n"
        "TEST_RESULT: fail\n"
        "BLOCKED_REASON: Tests failed after implementation\n"
    )
    assert sidecar.status == "blocked"
    assert sidecar.blocked_reason == "Tests failed after implementation"


def test_status_sidecar_parse_empty() -> None:
    assert StatusSidecar.parse("").status == "blocked"


def test_status_sidecar_parse_malformed() -> None:
    assert StatusSidecar.parse("garbage\nno colons here\n").status == "blocked"


def test_status_sidecar_from_file(tmp_path) -> None:
    sidecar_path = tmp_path / "test.status"
    sidecar_path.write_text("STATUS: done\nCOMMITS: abc\nTESTS_RAN: full\nTEST_RESULT: pass\n")
    sidecar = StatusSidecar.from_file(sidecar_path)
    assert sidecar.status == "done"


def test_status_sidecar_from_missing_file(tmp_path) -> None:
    assert StatusSidecar.from_file(tmp_path / "nonexistent.status").status == "blocked"


def test_constraint_defaults() -> None:
    constraint = Constraint(task_id="001")
    assert constraint.depends_on == []
    assert constraint.exec_order == 1
