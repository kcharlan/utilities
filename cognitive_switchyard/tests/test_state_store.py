from __future__ import annotations

from pathlib import Path

import pytest

from cognitive_switchyard.config import build_runtime_paths
from cognitive_switchyard.models import SessionEvent, TaskPlan
from cognitive_switchyard.state import StateStore, initialize_state_store


def _read_fixture(repo_root: Path, relative_path: str) -> str:
    return (repo_root / relative_path).read_text(encoding="utf-8")


def _build_store(tmp_path: Path) -> tuple[StateStore, object]:
    runtime_paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(runtime_paths)
    return store, runtime_paths


def test_initialize_state_store_is_idempotent(tmp_path: Path) -> None:
    runtime_paths = build_runtime_paths(home=tmp_path)

    first = initialize_state_store(runtime_paths)
    second = initialize_state_store(runtime_paths)

    assert first.database_path == runtime_paths.database
    assert second.database_path == runtime_paths.database
    assert runtime_paths.database.exists()
    assert runtime_paths.sessions.exists()


def test_create_session_materializes_canonical_session_layout(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)

    session = store.create_session(
        session_id="session-003",
        name="Packet 03 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)

    assert session.id == "session-003"
    assert session.status == "created"
    assert session_paths.root.exists()
    assert session_paths.ready.exists()
    assert session_paths.logs.exists()
    assert session_paths.worker_logs.exists()
    assert session_paths.resolution == session_paths.root / "resolution.json"
    assert session_paths.session_log == session_paths.logs / "session.log"
    assert session_paths.verify_log == session_paths.logs / "verify.log"
    assert session_paths.worker_log(2) == session_paths.worker_logs / "2.log"


def test_register_task_plan_persists_scheduler_fields(
    tmp_path: Path, repo_root: Path
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="session-003",
        name="Packet 03 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )
    plan_text = _read_fixture(
        repo_root, "tests/fixtures/tasks/plan_with_constraints.plan.md"
    )
    plan = TaskPlan(
        task_id="039",
        title="Fix chunk progress counter double-counting during cross-model verification",
        depends_on=("021d", "022"),
        anti_affinity=("043",),
        exec_order=7,
        full_test_after=True,
        body="## Problem\n\nProgress can exceed 100% during verification.\n",
    )

    task = store.register_task_plan(
        session_id="session-003",
        plan=plan,
        plan_text=plan_text,
        created_at="2026-03-09T10:01:00Z",
    )
    ready_tasks = store.list_ready_tasks("session-003")
    task_path = runtime_paths.session_paths("session-003").ready / "039.plan.md"

    assert task.task_id == "039"
    assert task.depends_on == ("021d", "022")
    assert task.anti_affinity == ("043",)
    assert task.exec_order == 7
    assert task.full_test_after is True
    assert task.status == "ready"
    assert task.plan_path == task_path
    assert ready_tasks == (task,)
    assert task_path.read_text(encoding="utf-8") == plan_text


def test_register_task_plan_rejects_missing_session_without_writing_plan_file(
    tmp_path: Path, repo_root: Path
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    plan_text = _read_fixture(
        repo_root, "tests/fixtures/tasks/plan_with_constraints.plan.md"
    )
    plan = TaskPlan(
        task_id="039",
        title="Fix chunk progress counter double-counting during cross-model verification",
    )

    with pytest.raises(KeyError, match="Unknown session: session-003"):
        store.register_task_plan(
            session_id="session-003",
            plan=plan,
            plan_text=plan_text,
            created_at="2026-03-09T10:01:00Z",
        )

    task_path = runtime_paths.session_paths("session-003").ready / "039.plan.md"
    assert not task_path.exists()
    assert not runtime_paths.session_paths("session-003").root.exists()


def test_register_task_plan_rejects_duplicate_task_without_overwriting_plan(
    tmp_path: Path, repo_root: Path
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="session-003",
        name="Packet 03 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )
    original_plan_text = _read_fixture(
        repo_root, "tests/fixtures/tasks/plan_with_constraints.plan.md"
    )
    updated_plan_text = original_plan_text + "\nDuplicate write should not land.\n"
    plan = TaskPlan(
        task_id="039",
        title="Fix chunk progress counter double-counting during cross-model verification",
    )

    store.register_task_plan(
        session_id="session-003",
        plan=plan,
        plan_text=original_plan_text,
        created_at="2026-03-09T10:01:00Z",
    )

    with pytest.raises(KeyError, match="Task already exists: session-003/039"):
        store.register_task_plan(
            session_id="session-003",
            plan=plan,
            plan_text=updated_plan_text,
            created_at="2026-03-09T10:02:00Z",
        )

    task_path = runtime_paths.session_paths("session-003").ready / "039.plan.md"
    assert task_path.read_text(encoding="utf-8") == original_plan_text


def test_project_task_between_ready_worker_done_and_blocked_states(
    tmp_path: Path, repo_root: Path
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="session-003",
        name="Packet 03 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )
    plan_text = _read_fixture(
        repo_root, "tests/fixtures/tasks/plan_with_constraints.plan.md"
    )
    plan = TaskPlan(
        task_id="039",
        title="Fix chunk progress counter double-counting during cross-model verification",
        depends_on=("021d", "022"),
        anti_affinity=("043",),
        exec_order=7,
        full_test_after=True,
        body="## Problem\n\nProgress can exceed 100% during verification.\n",
    )
    store.register_task_plan(
        session_id="session-003",
        plan=plan,
        plan_text=plan_text,
        created_at="2026-03-09T10:01:00Z",
    )

    active = store.project_task(
        "session-003",
        "039",
        status="active",
        worker_slot=1,
        timestamp="2026-03-09T10:02:00Z",
    )
    active_path = runtime_paths.session_paths("session-003").workers / "1" / "039.plan.md"
    assert active.status == "active"
    assert active.worker_slot == 1
    assert active.plan_path == active_path
    assert active_path.exists()
    assert store.list_ready_tasks("session-003") == ()
    assert store.list_active_tasks("session-003") == (active,)
    assert store.list_worker_slots("session-003")[0].current_task_id == "039"

    done = store.project_task(
        "session-003",
        "039",
        status="done",
        timestamp="2026-03-09T10:03:00Z",
    )
    done_path = runtime_paths.session_paths("session-003").done / "039.plan.md"
    assert done.status == "done"
    assert done.worker_slot is None
    assert done.plan_path == done_path
    assert done_path.exists()
    assert store.list_active_tasks("session-003") == ()
    assert store.list_done_tasks("session-003") == (done,)
    assert store.list_worker_slots("session-003")[0].status == "idle"

    blocked = store.project_task(
        "session-003",
        "039",
        status="blocked",
        timestamp="2026-03-09T10:04:00Z",
    )
    blocked_path = runtime_paths.session_paths("session-003").blocked / "039.plan.md"
    assert blocked.status == "blocked"
    assert blocked.plan_path == blocked_path
    assert blocked_path.exists()
    assert store.get_task("session-003", "039") == blocked


def test_project_task_rejects_worker_slot_outside_active_state(
    tmp_path: Path, repo_root: Path
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="session-003",
        name="Packet 03 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )
    plan_text = _read_fixture(
        repo_root, "tests/fixtures/tasks/plan_with_constraints.plan.md"
    )
    plan = TaskPlan(
        task_id="039",
        title="Fix chunk progress counter double-counting during cross-model verification",
    )
    task = store.register_task_plan(
        session_id="session-003",
        plan=plan,
        plan_text=plan_text,
        created_at="2026-03-09T10:01:00Z",
    )

    with pytest.raises(
        ValueError,
        match="worker_slot is only valid when status is active",
    ):
        store.project_task("session-003", "039", status="ready", worker_slot=1)

    assert store.get_task("session-003", "039") == task
    assert task.plan_path == runtime_paths.session_paths("session-003").ready / "039.plan.md"


def test_append_and_list_session_events_in_timestamp_order(tmp_path: Path) -> None:
    store, _runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="session-003",
        name="Packet 03 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )

    later = store.append_event(
        "session-003",
        timestamp="2026-03-09T10:03:00Z",
        event_type="task.done",
        message="Task 039 completed.",
        task_id="039",
    )
    earlier = store.append_event(
        "session-003",
        timestamp="2026-03-09T10:01:00Z",
        event_type="session.created",
        message="Session initialized.",
    )

    assert later == SessionEvent(
        session_id="session-003",
        timestamp="2026-03-09T10:03:00Z",
        event_type="task.done",
        task_id="039",
        message="Task 039 completed.",
    )
    assert store.list_events("session-003") == (
        earlier,
        later,
    )
