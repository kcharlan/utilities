from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cognitive_switchyard.models import Event, EventType, Session, SessionStatus, Task, TaskStatus, WorkerStatus
from cognitive_switchyard.state import StateStore


@pytest.fixture
def store(tmp_path):
    state_store = StateStore(db_path=tmp_path / "test.db")
    state_store.connect()
    yield state_store
    state_store.close()


@pytest.fixture
def session_id() -> str:
    return "test-session-001"


@pytest.fixture
def sample_session(session_id) -> Session:
    return Session(
        id=session_id,
        name="Test Run",
        pack_name="test-echo",
        config_json="{}",
        status=SessionStatus.CREATED,
        created_at=datetime.now(timezone.utc),
    )


class TestSessionCRUD:
    def test_create_and_get(self, store, sample_session) -> None:
        store.create_session(sample_session)
        got = store.get_session(sample_session.id)
        assert got is not None
        assert got.name == "Test Run"
        assert got.status == SessionStatus.CREATED

    def test_get_nonexistent(self, store) -> None:
        assert store.get_session("nope") is None

    def test_list_sessions(self, store, sample_session) -> None:
        store.create_session(sample_session)
        assert len(store.list_sessions()) == 1

    def test_update_status_unconditional(self, store, sample_session) -> None:
        store.create_session(sample_session)
        assert store.update_session_status(sample_session.id, SessionStatus.RUNNING)
        assert store.get_session(sample_session.id).status == SessionStatus.RUNNING

    def test_update_status_conditional_match(self, store, sample_session) -> None:
        store.create_session(sample_session)
        assert store.update_session_status(
            sample_session.id,
            SessionStatus.RUNNING,
            expected_status=SessionStatus.CREATED,
        )

    def test_update_status_conditional_mismatch(self, store, sample_session) -> None:
        store.create_session(sample_session)
        assert not store.update_session_status(
            sample_session.id,
            SessionStatus.RUNNING,
            expected_status=SessionStatus.PAUSED,
        )
        assert store.get_session(sample_session.id).status == SessionStatus.CREATED

    def test_delete_session(self, store, sample_session) -> None:
        store.create_session(sample_session)
        assert store.delete_session(sample_session.id)
        assert store.get_session(sample_session.id) is None


class TestTaskCRUD:
    def test_create_and_get(self, store, sample_session, session_id) -> None:
        store.create_session(sample_session)
        task = Task(
            id="001",
            session_id=session_id,
            title="Test Task",
            status=TaskStatus.READY,
            depends_on=["002"],
            anti_affinity=["003"],
            exec_order=1,
            plan_filename="001_test.plan.md",
            created_at=datetime.now(timezone.utc),
        )
        store.create_task(task)
        got = store.get_task(session_id, "001")
        assert got is not None
        assert got.title == "Test Task"
        assert got.depends_on == ["002"]
        assert got.anti_affinity == ["003"]

    def test_list_tasks_by_status(self, store, sample_session, session_id) -> None:
        store.create_session(sample_session)
        for tid, status in [("001", TaskStatus.READY), ("002", TaskStatus.DONE), ("003", TaskStatus.READY)]:
            store.create_task(Task(id=tid, session_id=session_id, title=f"Task {tid}", status=status))
        assert len(store.list_tasks(session_id, status=TaskStatus.READY)) == 2
        assert len(store.list_tasks(session_id)) == 3

    def test_update_task_conditional(self, store, sample_session, session_id) -> None:
        store.create_session(sample_session)
        store.create_task(Task(id="001", session_id=session_id, title="T", status=TaskStatus.READY))
        assert store.update_task_status(
            session_id,
            "001",
            TaskStatus.ACTIVE,
            expected_status=TaskStatus.READY,
            worker_slot=0,
        )
        got = store.get_task(session_id, "001")
        assert got.status == TaskStatus.ACTIVE
        assert got.worker_slot == 0
        assert not store.update_task_status(
            session_id,
            "001",
            TaskStatus.DONE,
            expected_status=TaskStatus.READY,
        )


class TestWorkerSlots:
    def test_create_and_get(self, store, sample_session, session_id) -> None:
        store.create_session(sample_session)
        store.create_worker_slots(session_id, 3)
        slots = store.get_worker_slots(session_id)
        assert len(slots) == 3
        assert all(slot.status == WorkerStatus.IDLE for slot in slots)

    def test_update_slot(self, store, sample_session, session_id) -> None:
        store.create_session(sample_session)
        store.create_worker_slots(session_id, 2)
        store.update_worker_slot(session_id, 0, WorkerStatus.ACTIVE, current_task_id="001", pid=12345)
        slots = store.get_worker_slots(session_id)
        assert slots[0].status == WorkerStatus.ACTIVE
        assert slots[0].current_task_id == "001"
        assert slots[0].pid == 12345


class TestEvents:
    def test_add_and_list(self, store, sample_session, session_id) -> None:
        store.create_session(sample_session)
        store.add_event(
            Event(
                session_id=session_id,
                timestamp=datetime.now(timezone.utc),
                event_type=EventType.TASK_DISPATCHED,
                task_id="001",
                worker_slot=0,
                message="Dispatched task 001 to slot 0",
            )
        )
        events = store.list_events(session_id)
        assert len(events) == 1
        assert events[0].event_type == EventType.TASK_DISPATCHED


class TestPipelineCounts:
    def test_counts(self, store, sample_session, session_id) -> None:
        store.create_session(sample_session)
        for tid, status in [
            ("001", TaskStatus.READY),
            ("002", TaskStatus.READY),
            ("003", TaskStatus.ACTIVE),
            ("004", TaskStatus.DONE),
        ]:
            store.create_task(Task(id=tid, session_id=session_id, title=f"T{tid}", status=status))
        counts = store.pipeline_counts(session_id)
        assert counts["ready"] == 2
        assert counts["active"] == 1
        assert counts["done"] == 1
        assert counts["blocked"] == 0


class TestFilenameParser:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("001_some_slug.plan.md", "001"),
            ("023a_task_name.plan.md", "023a"),
            ("023-b_task_name.plan.md", "023b"),
            ("040_schema_editor.plan.md", "040"),
        ],
    )
    def test_extract_task_id(self, filename, expected) -> None:
        assert StateStore._extract_task_id_from_filename(filename) == expected


class TestReconciliation:
    def test_reconcile_from_filesystem(self, store, sample_session, session_id, tmp_path, monkeypatch) -> None:
        store.create_session(sample_session)
        store.create_task(
            Task(id="001", session_id=session_id, title="T1", status=TaskStatus.READY, plan_filename="001_t1.plan.md")
        )
        store.create_task(
            Task(id="002", session_id=session_id, title="T2", status=TaskStatus.READY, plan_filename="002_t2.plan.md")
        )

        base = tmp_path / "sessions" / session_id
        done_dir = base / "done"
        ready_dir = base / "ready"
        done_dir.mkdir(parents=True)
        ready_dir.mkdir(parents=True)
        (done_dir / "001_t1.plan.md").write_text("plan content")
        (ready_dir / "002_t2.plan.md").write_text("plan content")

        def mock_subdirs(sid):
            session_base = tmp_path / "sessions" / sid
            return {
                "intake": session_base / "intake",
                "claimed": session_base / "claimed",
                "staging": session_base / "staging",
                "review": session_base / "review",
                "ready": session_base / "ready",
                "workers": session_base / "workers",
                "done": session_base / "done",
                "blocked": session_base / "blocked",
                "logs": session_base / "logs",
                "logs_workers": session_base / "logs" / "workers",
            }

        monkeypatch.setattr("cognitive_switchyard.state.config.session_subdirs", mock_subdirs)
        store.reconcile_tasks_from_filesystem(session_id)
        assert store.get_task(session_id, "001").status == TaskStatus.DONE
        assert store.get_task(session_id, "002").status == TaskStatus.READY
