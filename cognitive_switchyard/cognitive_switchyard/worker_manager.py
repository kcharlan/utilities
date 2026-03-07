from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Optional

from cognitive_switchyard.models import StatusSidecar, Task
from cognitive_switchyard.watcher import StatusFileWatcher

logger = logging.getLogger(__name__)

KILL_GRACE_PERIOD = 5


class ManagedWorker:
    """Represents one worker slot and its subprocess."""

    def __init__(self, session_id: str, slot_number: int, log_dir: Path):
        self.session_id = session_id
        self.slot_number = slot_number
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.process: Optional[subprocess.Popen[str]] = None
        self.task: Optional[Task] = None
        self.task_started_at: Optional[datetime] = None
        self.last_output_at: Optional[datetime] = None
        self.log_file_handle: Optional[IO[str]] = None
        self.log_path: Optional[Path] = None
        self.workspace_path: Optional[Path] = None
        self._read_handle: Optional[IO[str]] = None
        self._read_pos = 0

    @property
    def is_idle(self) -> bool:
        return self.process is None

    @property
    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def elapsed_seconds(self) -> float:
        if self.task_started_at is None:
            return 0.0
        return (datetime.now(timezone.utc) - self.task_started_at).total_seconds()

    @property
    def idle_seconds(self) -> float:
        if self.last_output_at is None:
            return self.elapsed_seconds
        return (datetime.now(timezone.utc) - self.last_output_at).total_seconds()

    def launch(
        self,
        task: Task,
        cmd: list[str],
        cwd: Path,
        workspace_path: Optional[Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> None:
        if not self.is_idle:
            raise RuntimeError(
                f"Worker slot {self.slot_number} is not idle "
                f"(running task {self.task.id if self.task else '?'})"
            )

        self.task = task
        self.workspace_path = workspace_path
        now = datetime.now(timezone.utc)
        self.task_started_at = now
        self.last_output_at = now

        log_stem = task.plan_filename.replace(".plan.md", "") if task.plan_filename else task.id
        self.log_path = self.log_dir / f"{log_stem}.log"
        self.log_file_handle = self.log_path.open("w", buffering=1)

        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        logger.info("Slot %d launching task %s", self.slot_number, task.id)
        self.process = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=self.log_file_handle,
            stderr=subprocess.STDOUT,
            env=process_env,
            text=True,
            start_new_session=True,
        )

    def poll_output(self) -> list[str]:
        if self.log_path is None or not self.log_path.exists():
            return []

        if self.log_file_handle and not self.log_file_handle.closed:
            try:
                self.log_file_handle.flush()
            except (OSError, ValueError):
                pass

        if self._read_handle is None:
            self._read_handle = self.log_path.open()
            self._read_pos = 0

        self._read_handle.seek(self._read_pos)
        content = self._read_handle.read()
        self._read_pos = self._read_handle.tell()
        if not content:
            return []

        self.last_output_at = datetime.now(timezone.utc)
        return content.splitlines()

    def check_finished(self) -> bool:
        return self.process is None or self.process.poll() is not None

    def exit_code(self) -> Optional[int]:
        return None if self.process is None else self.process.poll()

    def kill(self, reason: str = "") -> None:
        if self.process is None or not self.is_alive:
            return

        pid = self.process.pid
        logger.warning(
            "Slot %d killing task %s (pid=%s, reason=%s)",
            self.slot_number,
            self.task.id if self.task else "?",
            pid,
            reason,
        )

        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (PermissionError, ProcessLookupError):
            return

        deadline = time.monotonic() + KILL_GRACE_PERIOD
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                return
            time.sleep(0.1)

        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (PermissionError, ProcessLookupError):
            pass

        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.error("Slot %d process failed to die after SIGKILL", self.slot_number)

    def cleanup(self) -> None:
        if self.log_file_handle and not self.log_file_handle.closed:
            self.log_file_handle.close()
        if self._read_handle and not self._read_handle.closed:
            self._read_handle.close()

        self.process = None
        self.task = None
        self.task_started_at = None
        self.last_output_at = None
        self.log_file_handle = None
        self.workspace_path = None
        self._read_handle = None
        self._read_pos = 0

    def read_status_sidecar(self, slot_dir: Path) -> StatusSidecar:
        status_path = StatusFileWatcher(slot_dir).find_status_file()
        if status_path is None:
            return StatusSidecar()
        return StatusSidecar.from_file(status_path)


class WorkerManager:
    """Manage all worker slots for a session."""

    def __init__(self, session_id: str, num_workers: int, base_log_dir: Path):
        self.session_id = session_id
        slot_log_dir = base_log_dir / "workers"
        self.workers = [
            ManagedWorker(session_id, slot_number, slot_log_dir)
            for slot_number in range(num_workers)
        ]

    def idle_slots(self) -> list[ManagedWorker]:
        return [worker for worker in self.workers if worker.is_idle]

    def active_slots(self) -> list[ManagedWorker]:
        return [worker for worker in self.workers if not worker.is_idle]

    def finished_slots(self) -> list[ManagedWorker]:
        return [worker for worker in self.workers if not worker.is_idle and worker.check_finished()]

    def kill_all(self, reason: str = "session abort") -> None:
        for worker in self.active_slots():
            worker.kill(reason)

    def cleanup_all(self) -> None:
        for worker in self.workers:
            if not worker.is_idle:
                worker.cleanup()
