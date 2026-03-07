from __future__ import annotations

import sys
import time

import pytest

from cognitive_switchyard.models import Task, TaskStatus
from cognitive_switchyard.worker_manager import ManagedWorker, WorkerManager


@pytest.fixture
def log_dir(tmp_path):
    directory = tmp_path / "logs"
    directory.mkdir()
    return directory


@pytest.fixture
def worker(log_dir):
    return ManagedWorker(session_id="s1", slot_number=0, log_dir=log_dir)


@pytest.fixture
def sample_task():
    return Task(
        id="001",
        session_id="s1",
        title="Echo Test",
        status=TaskStatus.ACTIVE,
        plan_filename="001_echo.plan.md",
    )


class TestManagedWorker:
    def test_starts_idle(self, worker) -> None:
        assert worker.is_idle
        assert not worker.is_alive

    def test_launch_and_complete(self, worker, sample_task, tmp_path) -> None:
        worker.launch(task=sample_task, cmd=[sys.executable, "-c", "print('hello from worker')"], cwd=tmp_path)
        assert not worker.is_idle
        for _ in range(20):
            if worker.check_finished():
                break
            time.sleep(0.1)
        assert worker.check_finished()
        assert worker.exit_code() == 0
        assert any("hello from worker" in line for line in worker.poll_output())
        worker.cleanup()
        assert worker.is_idle

    def test_launch_when_busy_raises(self, worker, sample_task, tmp_path) -> None:
        worker.launch(
            task=sample_task,
            cmd=[sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=tmp_path,
        )
        with pytest.raises(RuntimeError, match="not idle"):
            worker.launch(task=sample_task, cmd=["echo"], cwd=tmp_path)
        worker.kill("test cleanup")
        worker.cleanup()

    def test_kill(self, worker, sample_task, tmp_path) -> None:
        worker.launch(
            task=sample_task,
            cmd=[sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=tmp_path,
        )
        assert worker.is_alive
        worker.kill("test")
        assert worker.check_finished()
        worker.cleanup()
        assert worker.is_idle

    def test_elapsed_seconds(self, worker, sample_task, tmp_path) -> None:
        worker.launch(
            task=sample_task,
            cmd=[sys.executable, "-c", "import time; time.sleep(0.2)"],
            cwd=tmp_path,
        )
        time.sleep(0.1)
        assert worker.elapsed_seconds >= 0.1
        worker.kill("cleanup")
        worker.cleanup()

    def test_read_status_sidecar(self, worker, tmp_path) -> None:
        (tmp_path / "001_echo.status").write_text(
            "STATUS: done\nCOMMITS: abc123\nTESTS_RAN: targeted\nTEST_RESULT: pass\n"
        )
        sidecar = worker.read_status_sidecar(tmp_path)
        assert sidecar.status == "done"
        assert sidecar.commits == "abc123"

    def test_read_status_sidecar_missing(self, worker, tmp_path) -> None:
        assert worker.read_status_sidecar(tmp_path).status == "blocked"


class TestWorkerManager:
    def test_initial_state(self, tmp_path) -> None:
        manager = WorkerManager("s1", 3, tmp_path / "logs")
        assert len(manager.workers) == 3
        assert len(manager.idle_slots()) == 3
        assert len(manager.active_slots()) == 0

    def test_launch_reduces_idle(self, tmp_path) -> None:
        manager = WorkerManager("s1", 2, tmp_path / "logs")
        task = Task(id="001", session_id="s1", title="T", status=TaskStatus.ACTIVE, plan_filename="001_t.plan.md")
        manager.workers[0].launch(
            task=task,
            cmd=[sys.executable, "-c", "import time; time.sleep(5)"],
            cwd=tmp_path,
        )
        assert len(manager.idle_slots()) == 1
        assert len(manager.active_slots()) == 1
        manager.kill_all("test cleanup")
        manager.cleanup_all()

    def test_kill_all(self, tmp_path) -> None:
        manager = WorkerManager("s1", 2, tmp_path / "logs")
        for i in range(2):
            task = Task(
                id=f"00{i}",
                session_id="s1",
                title=f"T{i}",
                status=TaskStatus.ACTIVE,
                plan_filename=f"00{i}_t.plan.md",
            )
            manager.workers[i].launch(
                task=task,
                cmd=[sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=tmp_path,
            )
        assert len(manager.active_slots()) == 2
        manager.kill_all("abort")
        manager.cleanup_all()
        assert len(manager.idle_slots()) == 2
