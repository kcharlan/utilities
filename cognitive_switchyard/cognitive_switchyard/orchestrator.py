from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from cognitive_switchyard.agent_runtime import build_agent_command, load_prompt, render_prompt, run_agent
from cognitive_switchyard.config import (
    PROGRESS_PATTERN,
    SessionConfig,
    session_dir,
    session_subdirs,
)
from cognitive_switchyard.models import (
    Event,
    EventType,
    Session,
    SessionStatus,
    StatusSidecar,
    Task,
    TaskStatus,
    WorkerStatus,
)
from cognitive_switchyard.planner import run_planner_script
from cognitive_switchyard.pack_loader import PackConfig, invoke_hook, load_pack, pack_dir
from cognitive_switchyard.resolution import parse_plan_frontmatter, resolve_passthrough
from cognitive_switchyard.scheduler import count_pending, detect_deadlock, find_next_eligible
from cognitive_switchyard.state import StateStore
from cognitive_switchyard.worker_manager import ManagedWorker, WorkerManager

logger = logging.getLogger(__name__)


class Orchestrator:
    """Main orchestration engine."""

    def __init__(
        self,
        session_id: str,
        store: StateStore,
        event_loop: Optional[asyncio.AbstractEventLoop] = None,
        ws_broadcast: Optional[Callable] = None,
    ):
        self.session_id = session_id
        self.store = store
        self._event_loop = event_loop
        self._ws_broadcast = ws_broadcast
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._session: Optional[Session] = None
        self._config: Optional[SessionConfig] = None
        self._pack: Optional[PackConfig] = None
        self._worker_mgr: Optional[WorkerManager] = None
        self._dirs: Optional[dict[str, Path]] = None

        self._completed_since_verify = 0
        self._total_completed = 0
        self._total_blocked = 0
        self._fix_attempts: dict[str, int] = {}

    def start_background(self) -> threading.Thread:
        self._thread = threading.Thread(
            target=self._run_with_error_handling,
            name=f"orchestrator-{self.session_id}",
            daemon=True,
        )
        self._thread.start()
        return self._thread

    def stop(self, timeout: float = 30) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def run_foreground(self) -> None:
        self._run_with_error_handling()

    def _run_with_error_handling(self) -> None:
        try:
            self._initialize()
            self._run_recovery()
            self._run_planning_phase()
            self._run_resolution_phase()
            self._dispatch_loop()
        except Exception:
            logger.exception("Orchestrator crashed for session %s", self.session_id)
            self._add_event(EventType.ERROR, message="Orchestrator crashed unexpectedly")
            self.store.update_session_status(
                self.session_id,
                SessionStatus.ABORTED,
                abort_reason="Orchestrator crash (check logs)",
                completed_at=datetime.now(timezone.utc),
            )
            raise
        finally:
            if self._worker_mgr:
                self._worker_mgr.kill_all("orchestrator shutdown")
                self._worker_mgr.cleanup_all()

    def _initialize(self) -> None:
        self._session = self.store.get_session(self.session_id)
        if self._session is None:
            raise ValueError(f"Session {self.session_id} not found")

        self._config = SessionConfig(**json.loads(self._session.config_json))
        self._pack = load_pack(self._config.pack_name)
        self._dirs = session_subdirs(self.session_id)

        for directory in self._dirs.values():
            directory.mkdir(parents=True, exist_ok=True)
        for slot in range(self._config.num_workers):
            (self._dirs["workers"] / str(slot)).mkdir(parents=True, exist_ok=True)

        session_log = self._dirs["logs"] / "session.log"
        session_log.parent.mkdir(parents=True, exist_ok=True)
        session_log.touch(exist_ok=True)

        self._worker_mgr = WorkerManager(self.session_id, self._config.num_workers, self._dirs["logs"])
        self.store.create_worker_slots(self.session_id, self._config.num_workers)

    def _run_recovery(self) -> None:
        workers_base = self._dirs["workers"]
        ready_dir = self._dirs["ready"]

        for slot_dir in sorted(workers_base.iterdir()):
            if not slot_dir.is_dir():
                continue
            plan_files = list(slot_dir.glob("*.plan.md"))
            if not plan_files:
                continue

            for plan_file in plan_files:
                status_file = next(iter(slot_dir.glob("*.status")), None)
                if status_file is not None:
                    sidecar = StatusSidecar.from_file(status_file)
                    if sidecar.status == "done":
                        self._move_to_done(plan_file, status_file, slot_dir)
                        continue

                os.rename(str(plan_file), str(ready_dir / plan_file.name))
                for extra in slot_dir.glob("*.status"):
                    extra.unlink()
                for extra in slot_dir.glob("*.log"):
                    extra.unlink()

        self.store.reconcile_tasks_from_filesystem(self.session_id)
        for slot in self.store.get_worker_slots(self.session_id):
            self.store.update_worker_slot(
                self.session_id,
                slot.slot_number,
                WorkerStatus.IDLE,
                current_task_id=None,
                pid=None,
            )

    def _run_planning_phase(self) -> None:
        if not self._pack.planning_enabled:
            return

        intake_files = sorted(path for path in self._dirs["intake"].glob("*.md") if path.is_file())
        if not intake_files:
            return

        self.store.update_session_status(self.session_id, SessionStatus.PLANNING)
        self._add_event(EventType.SESSION_STARTED, message="Planning phase started")

        while not self._stop_event.is_set():
            intake_files = sorted(path for path in self._dirs["intake"].glob("*.md") if path.is_file())
            if not intake_files:
                break

            intake_path = intake_files[0]
            claimed_path = self._dirs["claimed"] / intake_path.name
            os.rename(str(intake_path), str(claimed_path))

            task_id = self.store._extract_task_id_from_filename(claimed_path.name) or claimed_path.stem
            existing = self.store.get_task(self.session_id, task_id)
            created_at = existing.created_at if existing else datetime.now(timezone.utc)
            self.store.upsert_task(
                Task(
                    id=task_id,
                    session_id=self.session_id,
                    title=claimed_path.stem,
                    status=TaskStatus.PLANNING,
                    plan_filename=existing.plan_filename if existing else None,
                    created_at=created_at,
                )
            )

            staging_before = {path.name for path in self._dirs["staging"].glob("*.plan.md")}
            review_before = {path.name for path in self._dirs["review"].glob("*.plan.md")}

            try:
                if self._pack.planning_executor == "script":
                    if not self._pack.planning_script:
                        raise ValueError(f"Pack {self._pack.name} planning executor is script but no script configured")
                    run_planner_script(
                        self._pack.name,
                        self._pack.planning_script,
                        claimed_path,
                        self._dirs["staging"],
                        self._dirs["review"],
                    )
                elif self._pack.planning_executor == "agent":
                    if not self._pack.planning_prompt:
                        raise ValueError(
                            f"Pack {self._pack.name} planning executor is agent but no prompt configured"
                        )
                    result = run_agent(
                        pack_name=self._pack.name,
                        prompt_relative_path=self._pack.planning_prompt,
                        model=self._pack.planning_model,
                        context={
                            "MODE": "planning",
                            "SESSION_ID": self.session_id,
                            "INTAKE_FILE": claimed_path,
                            "STAGING_DIR": self._dirs["staging"],
                            "REVIEW_DIR": self._dirs["review"],
                            "SESSION_DIR": session_dir(self.session_id),
                        },
                        cwd=session_dir(self.session_id),
                        timeout=300,
                        env=self._config.env_vars.copy(),
                    )
                    if result.returncode != 0:
                        raise RuntimeError(
                            result.stderr.strip()
                            or result.stdout.strip()
                            or "planner agent failed"
                        )
                else:
                    raise ValueError(f"Unknown planning executor: {self._pack.planning_executor}")
            finally:
                if claimed_path.exists():
                    claimed_path.unlink()

            produced = self._discover_planning_output(task_id, staging_before, review_before)
            if produced is None:
                raise RuntimeError(f"Planner produced no plan for intake item {intake_path.name}")

            output_path, status = produced
            self.store.upsert_task(
                Task(
                    id=task_id,
                    session_id=self.session_id,
                    title=self._extract_title_from_plan(output_path),
                    status=status,
                    plan_filename=output_path.name,
                    created_at=created_at,
                )
            )

    def _discover_planning_output(
        self,
        task_id: str,
        staging_before: set[str],
        review_before: set[str],
    ) -> Optional[tuple[Path, TaskStatus]]:
        staging_after = [path for path in sorted(self._dirs["staging"].glob("*.plan.md")) if path.name not in staging_before]
        review_after = [path for path in sorted(self._dirs["review"].glob("*.plan.md")) if path.name not in review_before]

        for path in staging_after:
            if self.store._extract_task_id_from_filename(path.name) == task_id:
                return path, TaskStatus.STAGED
        for path in review_after:
            if self.store._extract_task_id_from_filename(path.name) == task_id:
                return path, TaskStatus.REVIEW
        if len(staging_after) == 1:
            return staging_after[0], TaskStatus.STAGED
        if len(review_after) == 1:
            return review_after[0], TaskStatus.REVIEW
        return None

    def _run_resolution_phase(self) -> None:
        staged_plans = sorted(self._dirs["staging"].glob("*.plan.md"))
        if not staged_plans:
            return

        self.store.update_session_status(self.session_id, SessionStatus.RESOLVING)
        resolution_path = session_dir(self.session_id) / "resolution.json"

        if not self._pack.resolution_enabled:
            resolve_passthrough(self._dirs["staging"], self._dirs["ready"], resolution_path)
        elif self._pack.resolution_executor == "passthrough":
            resolve_passthrough(self._dirs["staging"], self._dirs["ready"], resolution_path)
        elif self._pack.resolution_executor == "script":
            if not self._pack.resolution_script:
                raise ValueError(f"Pack {self._pack.name} resolution executor is script but no script configured")
            result = invoke_hook(
                self._pack.name,
                self._pack.resolution_script,
                args=[str(self._dirs["staging"]), str(self._dirs["ready"]), str(resolution_path)],
                timeout=120,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "resolution script failed")
        elif self._pack.resolution_executor == "agent":
            if not self._pack.resolution_prompt:
                raise ValueError(
                    f"Pack {self._pack.name} resolution executor is agent but no prompt configured"
                )
            result = run_agent(
                pack_name=self._pack.name,
                prompt_relative_path=self._pack.resolution_prompt,
                model=self._pack.resolution_model,
                context={
                    "MODE": "resolution",
                    "SESSION_ID": self.session_id,
                    "STAGING_DIR": self._dirs["staging"],
                    "READY_DIR": self._dirs["ready"],
                    "RESOLUTION_PATH": resolution_path,
                    "SESSION_DIR": session_dir(self.session_id),
                },
                cwd=session_dir(self.session_id),
                timeout=300,
                env=self._config.env_vars.copy(),
            )
            if result.returncode != 0:
                raise RuntimeError(
                    result.stderr.strip()
                    or result.stdout.strip()
                    or "resolution agent failed"
                )
        else:
            raise ValueError(f"Unknown resolution executor: {self._pack.resolution_executor}")

        resolution = json.loads(resolution_path.read_text()) if resolution_path.exists() else {"tasks": []}
        constraints_by_id = {entry["task_id"]: entry for entry in resolution.get("tasks", [])}
        for plan_path in sorted(self._dirs["ready"].glob("*.plan.md")):
            task_id = self.store._extract_task_id_from_filename(plan_path.name) or plan_path.stem
            entry = constraints_by_id.get(task_id, {})
            existing = self.store.get_task(self.session_id, task_id)
            created_at = existing.created_at if existing else datetime.now(timezone.utc)
            self.store.upsert_task(
                Task(
                    id=task_id,
                    session_id=self.session_id,
                    title=self._extract_title_from_plan(plan_path),
                    status=TaskStatus.READY,
                    depends_on=entry.get("depends_on", []),
                    anti_affinity=entry.get("anti_affinity", []),
                    exec_order=entry.get("exec_order", 1),
                    plan_filename=plan_path.name,
                    created_at=created_at,
                )
            )

    def _dispatch_loop(self) -> None:
        now = datetime.now(timezone.utc)
        self.store.update_session_status(self.session_id, SessionStatus.RUNNING, started_at=now)
        self._add_event(EventType.SESSION_STARTED, message="Dispatch loop started")

        while not self._stop_event.is_set():
            session = self.store.get_session(self.session_id)
            if session is None:
                break
            if session.status == SessionStatus.PAUSED:
                self._stop_event.wait(timeout=self._config.poll_interval)
                continue
            if session.status in (SessionStatus.COMPLETED, SessionStatus.ABORTED):
                break

            self._collect_finished_workers()
            self._check_verification()
            session = self.store.get_session(self.session_id)
            if session is None or session.status in (SessionStatus.COMPLETED, SessionStatus.ABORTED):
                break
            self._enforce_timeouts()
            self._dispatch_eligible()

            all_tasks = self.store.list_tasks(self.session_id)
            pending = count_pending(all_tasks)
            active_count = len(self._worker_mgr.active_slots())

            if pending == 0 and active_count == 0:
                self._complete_session()
                break

            if active_count == 0 and pending > 0 and detect_deadlock(all_tasks):
                self._add_event(
                    EventType.ERROR,
                    message=f"Deadlock: {pending} tasks pending but none eligible",
                )
                self.store.update_session_status(
                    self.session_id,
                    SessionStatus.ABORTED,
                    abort_reason=f"Deadlock: {pending} pending tasks depend on blocked tasks",
                    completed_at=datetime.now(timezone.utc),
                )
                break

            self._broadcast_state()
            self._stop_event.wait(timeout=self._config.poll_interval)

    def _collect_finished_workers(self) -> None:
        for worker in self._worker_mgr.finished_slots():
            self._handle_worker_completion(worker)

    def _check_verification(self) -> None:
        if not self._pack.verification_enabled:
            return
        if self._completed_since_verify < self._config.verification_interval:
            return
        self._run_verification()

    def _run_verification(self) -> None:
        self.store.update_session_status(self.session_id, SessionStatus.VERIFYING)
        self._add_event(EventType.VERIFICATION_STARTED, message="Verification started")

        while self._worker_mgr.active_slots():
            self._collect_finished_workers()
            self._stop_event.wait(timeout=self._config.poll_interval)

        command = self._pack.verification_command
        if not command:
            raise ValueError(f"Pack {self._pack.name} enables verification without a command")

        if (pack_dir(self._pack.name) / command).exists():
            result = invoke_hook(self._pack.name, command, args=[str(session_dir(self.session_id))], timeout=300)
            returncode = result.returncode
            stdout = result.stdout
            stderr = result.stderr
        else:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(session_dir(self.session_id)),
            )
            returncode = result.returncode
            stdout = result.stdout
            stderr = result.stderr

        if returncode == 0:
            self._completed_since_verify = 0
            self.store.update_session_status(self.session_id, SessionStatus.RUNNING)
            self._add_event(
                EventType.VERIFICATION_PASSED,
                message=stdout.strip() or "Verification passed",
            )
            return

        message = stderr.strip() or stdout.strip() or "Verification failed"
        if self._pack.auto_fix_enabled and self._attempt_verification_auto_fix(message):
            self._completed_since_verify = 0
            self.store.update_session_status(self.session_id, SessionStatus.RUNNING)
            self._run_verification()
            return
        self._add_event(EventType.VERIFICATION_FAILED, message=message)
        self.store.update_session_status(
            self.session_id,
            SessionStatus.ABORTED,
            abort_reason=message,
            completed_at=datetime.now(timezone.utc),
        )

    def _handle_worker_completion(self, worker: ManagedWorker) -> None:
        task = worker.task
        if task is None:
            worker.cleanup()
            return

        slot = worker.slot_number
        slot_dir = self._dirs["workers"] / str(slot)
        sidecar = worker.read_status_sidecar(slot_dir)

        if sidecar.status == "done":
            for file_path in [*slot_dir.glob("*.plan.md"), *slot_dir.glob("*.status"), *slot_dir.glob("*.log")]:
                os.rename(str(file_path), str(self._dirs["done"] / file_path.name))
            if worker.log_path and worker.log_path.exists():
                worker.cleanup()
                if worker.log_path.exists():
                    shutil.move(str(worker.log_path), str(self._dirs["done"] / worker.log_path.name))
            else:
                worker.cleanup()

            self.store.update_task_status(
                self.session_id,
                task.id,
                TaskStatus.DONE,
                expected_status=TaskStatus.ACTIVE,
                completed_at=datetime.now(timezone.utc),
                worker_slot=None,
            )
            self.store.update_worker_slot(
                self.session_id,
                slot,
                WorkerStatus.IDLE,
                current_task_id=None,
                pid=None,
            )
            self._add_event(
                EventType.TASK_COMPLETED,
                task_id=task.id,
                worker_slot=slot,
                message=f"Task completed (commits: {sidecar.commits})",
            )
            self._broadcast_message(
                {
                    "type": "task_status_change",
                    "data": {
                        "session_id": self.session_id,
                        "task_id": task.id,
                        "old_status": TaskStatus.ACTIVE.value,
                        "new_status": TaskStatus.DONE.value,
                        "worker_slot": slot,
                        "notes": sidecar.notes or f"commits: {sidecar.commits}",
                    },
                }
            )
            self._total_completed += 1
            self._completed_since_verify += 1
        else:
            reason = sidecar.blocked_reason or f"Task failed (exit code {worker.exit_code()})"
            if self._pack.auto_fix_enabled and self._attempt_task_auto_fix(worker, reason):
                return
            for file_path in [*slot_dir.glob("*.plan.md"), *slot_dir.glob("*.status"), *slot_dir.glob("*.log")]:
                os.rename(str(file_path), str(self._dirs["blocked"] / file_path.name))
            if worker.log_path and worker.log_path.exists():
                worker.cleanup()
                if worker.log_path.exists():
                    shutil.move(str(worker.log_path), str(self._dirs["blocked"] / worker.log_path.name))
            else:
                worker.cleanup()

            self.store.update_task_status(
                self.session_id,
                task.id,
                TaskStatus.BLOCKED,
                expected_status=TaskStatus.ACTIVE,
                completed_at=datetime.now(timezone.utc),
                worker_slot=None,
                blocked_reason=reason,
            )
            self.store.update_worker_slot(
                self.session_id,
                slot,
                WorkerStatus.IDLE,
                current_task_id=None,
                pid=None,
            )
            self._add_event(
                EventType.TASK_BLOCKED,
                task_id=task.id,
                worker_slot=slot,
                message=reason,
            )
            self._broadcast_message(
                {
                    "type": "task_status_change",
                    "data": {
                        "session_id": self.session_id,
                        "task_id": task.id,
                        "old_status": TaskStatus.ACTIVE.value,
                        "new_status": TaskStatus.BLOCKED.value,
                        "worker_slot": slot,
                        "notes": reason,
                    },
                }
            )
            self._total_blocked += 1

    def _attempt_task_auto_fix(self, worker: ManagedWorker, reason: str) -> bool:
        if worker.task is None:
            return False
        task_id = worker.task.id
        slot_dir = self._dirs["workers"] / str(worker.slot_number)
        success = self._attempt_auto_fix(
            key=task_id,
            mode="task",
            message=reason,
            task=worker.task,
            source_dir=slot_dir,
        )
        if not success:
            return False

        plan_file = next(iter(slot_dir.glob("*.plan.md")), None)
        if plan_file is None:
            return False

        os.rename(str(plan_file), str(self._dirs["ready"] / plan_file.name))
        for status_file in slot_dir.glob("*.status"):
            status_file.unlink()
        for log_file in slot_dir.glob("*.log"):
            shutil.move(str(log_file), str(self._dirs["logs"] / log_file.name))

        if worker.log_path and worker.log_path.exists():
            worker.cleanup()
            if worker.log_path.exists():
                shutil.move(str(worker.log_path), str(self._dirs["logs"] / worker.log_path.name))
        else:
            worker.cleanup()

        self.store.update_task_status(
            self.session_id,
            task_id,
            TaskStatus.READY,
            expected_status=TaskStatus.ACTIVE,
            worker_slot=None,
            blocked_reason="",
        )
        self.store.update_worker_slot(
            self.session_id,
            worker.slot_number,
            WorkerStatus.IDLE,
            current_task_id=None,
            pid=None,
        )
        return True

    def _attempt_verification_auto_fix(self, message: str) -> bool:
        return self._attempt_auto_fix(
            key="__verification__",
            mode="verification",
            message=message,
            task=None,
            source_dir=session_dir(self.session_id),
        )

    def _attempt_auto_fix(
        self,
        *,
        key: str,
        mode: str,
        message: str,
        task: Optional[Task],
        source_dir: Path,
    ) -> bool:
        if not self._pack.auto_fix_script and not self._pack.auto_fix_prompt:
            return False

        previous_context = ""
        attempts = self._fix_attempts.get(key, 0)
        while attempts < self._config.auto_fix_max_attempts:
            attempts += 1
            self._fix_attempts[key] = attempts
            context_path = self._write_fix_context(
                key=key,
                mode=mode,
                attempt=attempts,
                message=message,
                task=task,
                source_dir=source_dir,
                previous_context=previous_context,
            )

            self._add_event(
                EventType.FIX_STARTED,
                task_id=task.id if task else None,
                message=f"{mode} auto-fix attempt {attempts}",
            )
            try:
                if self._pack.auto_fix_script:
                    result = invoke_hook(
                        self._pack.name,
                        self._pack.auto_fix_script,
                        args=[
                            str(context_path),
                            str(session_dir(self.session_id)),
                            task.id if task else "",
                            str(source_dir),
                        ],
                        timeout=300,
                    )
                else:
                    result = run_agent(
                        pack_name=self._pack.name,
                        prompt_relative_path=self._pack.auto_fix_prompt,
                        model=self._pack.auto_fix_model,
                        context={
                            "MODE": "auto_fix",
                            "SESSION_ID": self.session_id,
                            "TASK_ID": task.id if task else "",
                            "CONTEXT_FILE": context_path,
                            "SESSION_DIR": session_dir(self.session_id),
                            "SOURCE_DIR": source_dir,
                        },
                        cwd=session_dir(self.session_id),
                        timeout=300,
                        env=self._config.env_vars.copy(),
                    )
            except Exception as exc:
                previous_context = "\n".join(
                    part for part in [previous_context, f"Fixer exception: {exc}"] if part
                )
                continue

            if result.returncode == 0:
                self._add_event(
                    EventType.FIX_SUCCEEDED,
                    task_id=task.id if task else None,
                    message=f"{mode} auto-fix succeeded on attempt {attempts}",
                )
                return True

            previous_context = "\n".join(
                part for part in [previous_context, result.stderr.strip() or result.stdout.strip()] if part
            )
            self._add_event(
                EventType.FIX_FAILED,
                task_id=task.id if task else None,
                message=f"{mode} auto-fix attempt {attempts} failed",
            )
        return False

    def _write_fix_context(
        self,
        *,
        key: str,
        mode: str,
        attempt: int,
        message: str,
        task: Optional[Task],
        source_dir: Path,
        previous_context: str,
    ) -> Path:
        fixes_dir = self._dirs["logs"] / "fixes"
        fixes_dir.mkdir(parents=True, exist_ok=True)
        context_path = fixes_dir / f"{key.replace('/', '_')}_attempt_{attempt}.txt"

        plan_text = ""
        status_text = ""
        recent_logs = ""
        plan_file = next(iter(source_dir.glob("*.plan.md")), None)
        status_file = next(iter(source_dir.glob("*.status")), None)
        log_file = next(iter(source_dir.glob("*.log")), None)
        if plan_file and plan_file.exists():
            plan_text = plan_file.read_text()
        if status_file and status_file.exists():
            status_text = status_file.read_text()
        if log_file and log_file.exists():
            recent_logs = "\n".join(log_file.read_text().splitlines()[-200:])

        lines = [
            f"MODE: {mode}",
            f"ATTEMPT: {attempt}",
            f"MESSAGE: {message}",
            f"TASK_ID: {task.id if task else ''}",
            "",
            "## PLAN",
            plan_text,
            "",
            "## STATUS",
            status_text,
            "",
            "## LOG_TAIL",
            recent_logs,
        ]
        if previous_context:
            lines.extend(["", "## PREVIOUS_ATTEMPT_CONTEXT", previous_context])

        context_path.write_text("\n".join(lines).strip() + "\n")
        return context_path

    def _dispatch_eligible(self) -> None:
        for worker in self._worker_mgr.idle_slots():
            eligible = find_next_eligible(self.store.list_tasks(self.session_id))
            if eligible is None:
                break
            try:
                self._dispatch_task(worker, eligible)
            except Exception:
                logger.exception("Failed to dispatch task %s to slot %d", eligible.id, worker.slot_number)
                plan_path = self._dirs["workers"] / str(worker.slot_number) / (eligible.plan_filename or "")
                if plan_path.exists():
                    os.rename(str(plan_path), str(self._dirs["ready"] / plan_path.name))
                break

    def _dispatch_task(self, worker: ManagedWorker, task: Task) -> None:
        slot_dir = self._dirs["workers"] / str(worker.slot_number)
        ready_dir = self._dirs["ready"]

        plan_file = None
        for candidate in sorted(ready_dir.glob("*.plan.md")):
            if self.store._extract_task_id_from_filename(candidate.name) == task.id:
                plan_file = candidate
                break
        if plan_file is None:
            raise FileNotFoundError(f"Plan file for task {task.id} not found in {ready_dir}")

        destination = slot_dir / plan_file.name
        os.rename(str(plan_file), str(destination))

        workspace = slot_dir
        if self._pack.isolation_type != "none" and self._pack.isolation_setup:
            result = invoke_hook(
                self._pack.name,
                self._pack.isolation_setup,
                args=[str(worker.slot_number), task.id, str(session_dir(self.session_id))],
                timeout=60,
            )
            if result.returncode != 0:
                os.rename(str(destination), str(plan_file))
                raise RuntimeError(result.stderr.strip() or "isolation setup failed")
            if result.stdout.strip():
                workspace = Path(result.stdout.strip())

        if self._pack.execution_executor == "shell":
            if not self._pack.execution_command:
                raise ValueError(f"Pack {self._pack.name} has shell executor but no command")
            command = [
                str(pack_dir(self._pack.name) / self._pack.execution_command),
                str(destination),
                str(workspace),
            ]
        elif self._pack.execution_executor == "agent":
            if not self._pack.execution_prompt:
                raise ValueError(f"Pack {self._pack.name} has agent executor but no prompt")
            status_path = destination.with_name(destination.name.replace(".plan.md", ".status"))
            prompt = render_prompt(
                load_prompt(self._pack.name, self._pack.execution_prompt),
                {
                    "MODE": "execution",
                    "SESSION_ID": self.session_id,
                    "TASK_ID": task.id,
                    "PLAN_FILE": destination,
                    "WORKSPACE": workspace,
                    "SESSION_DIR": session_dir(self.session_id),
                    "WORKER_SLOT": worker.slot_number,
                    "STATUS_FILE": status_path,
                },
            )
            command = build_agent_command(model=self._pack.execution_model, prompt=prompt)
        else:
            raise ValueError(f"Unknown execution executor: {self._pack.execution_executor}")
        try:
            worker.launch(
                task=task,
                cmd=command,
                cwd=workspace,
                workspace_path=workspace,
                env=self._config.env_vars.copy(),
            )
        except Exception:
            os.rename(str(destination), str(plan_file))
            raise

        self.store.update_task_status(
            self.session_id,
            task.id,
            TaskStatus.ACTIVE,
            expected_status=TaskStatus.READY,
            worker_slot=worker.slot_number,
            started_at=datetime.now(timezone.utc),
        )
        self.store.update_worker_slot(
            self.session_id,
            worker.slot_number,
            WorkerStatus.ACTIVE,
            current_task_id=task.id,
            pid=worker.process.pid if worker.process else None,
        )
        self._add_event(
            EventType.TASK_DISPATCHED,
            task_id=task.id,
            worker_slot=worker.slot_number,
            message=f"Dispatched to slot {worker.slot_number}",
        )

    def _enforce_timeouts(self) -> None:
        for worker in self._worker_mgr.active_slots():
            if worker.task is None:
                continue

            new_lines = worker.poll_output()
            if new_lines:
                for line in new_lines:
                    self._broadcast_message(
                        {
                            "type": "log_line",
                            "data": {
                                "session_id": self.session_id,
                                "worker_slot": worker.slot_number,
                                "task_id": worker.task.id,
                                "line": line,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        }
                    )
                self._parse_progress(worker, new_lines)

            idle_secs = worker.idle_seconds
            wall_secs = worker.elapsed_seconds

            if self._config.task_idle_timeout > 0 and idle_secs >= self._config.task_idle_timeout:
                reason = (
                    f"Killed: no output for {int(idle_secs)}s "
                    f"(timeout: {self._config.task_idle_timeout}s)"
                )
                worker.kill(reason)
                self._add_event(
                    EventType.TIMEOUT_KILL,
                    task_id=worker.task.id,
                    worker_slot=worker.slot_number,
                    message=reason,
                )
            elif (
                self._config.task_idle_timeout > 0
                and idle_secs >= self._config.task_idle_timeout * 0.8
            ):
                self._add_event(
                    EventType.TIMEOUT_WARNING,
                    task_id=worker.task.id,
                    worker_slot=worker.slot_number,
                    message=(
                        f"No output for {int(idle_secs)}s "
                        f"(timeout at {self._config.task_idle_timeout}s)"
                    ),
                )

            if self._config.task_max_timeout > 0 and wall_secs >= self._config.task_max_timeout:
                reason = f"Killed: exceeded max task time {self._config.task_max_timeout}s"
                worker.kill(reason)
                self._add_event(
                    EventType.TIMEOUT_KILL,
                    task_id=worker.task.id,
                    worker_slot=worker.slot_number,
                    message=reason,
                )

        if self._config.session_max_timeout > 0:
            session = self.store.get_session(self.session_id)
            if session and session.started_at:
                elapsed = (datetime.now(timezone.utc) - session.started_at).total_seconds()
                if elapsed >= self._config.session_max_timeout:
                    self._worker_mgr.kill_all("session timeout")
                    self.store.update_session_status(
                        self.session_id,
                        SessionStatus.ABORTED,
                        abort_reason=f"Session timeout exceeded ({self._config.session_max_timeout}s)",
                        completed_at=datetime.now(timezone.utc),
                    )
                    self._stop_event.set()

    def _parse_progress(self, worker: ManagedWorker, lines: list[str]) -> None:
        for line in lines:
            if PROGRESS_PATTERN not in line:
                continue
            _, _, payload = line.partition(PROGRESS_PATTERN)
            parts = [part.strip() for part in payload.split("|")]
            if len(parts) < 2:
                continue

            task_id = parts[0]
            try:
                if "Phase:" in parts[1]:
                    phase_name = parts[1].split("Phase:", 1)[1].strip()
                    phase_num = None
                    phase_total = None
                    if len(parts) >= 3 and "/" in parts[2]:
                        num_str, total_str = parts[2].split("/", 1)
                        phase_num = int(num_str.strip())
                        phase_total = int(total_str.strip())
                    self.store.update_task_status(
                        self.session_id,
                        task_id,
                        TaskStatus.ACTIVE,
                        phase=phase_name,
                        phase_num=phase_num,
                        phase_total=phase_total,
                    )
                elif "Detail:" in parts[1]:
                    detail = parts[1].split("Detail:", 1)[1].strip()
                    self.store.update_task_status(
                        self.session_id,
                        task_id,
                        TaskStatus.ACTIVE,
                        detail=detail,
                    )
                    self._broadcast_message(
                        {
                            "type": "progress_detail",
                            "data": {
                                "session_id": self.session_id,
                                "worker_slot": worker.slot_number,
                                "task_id": task_id,
                                "detail": detail,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        }
                    )
            except (IndexError, ValueError):
                logger.debug("Failed to parse progress line: %s", line)

    def _complete_session(self) -> None:
        completed_at = datetime.now(timezone.utc)
        self.store.update_session_status(
            self.session_id,
            SessionStatus.COMPLETED,
            completed_at=completed_at,
        )
        self._add_event(
            EventType.SESSION_COMPLETED,
            message=f"Completed: {self._total_completed} done, {self._total_blocked} blocked",
        )
        if self._total_blocked == 0:
            self._trim_session_directory()

    def _trim_session_directory(self) -> None:
        base = session_dir(self.session_id)
        session = self.store.get_session(self.session_id)
        tasks = self.store.list_tasks(self.session_id)
        (base / "summary.json").write_text(
            json.dumps(
                {
                    "session_id": session.id,
                    "name": session.name,
                    "pack": session.pack_name,
                    "status": session.status.value,
                    "created_at": session.created_at.isoformat(),
                    "started_at": session.started_at.isoformat() if session.started_at else None,
                    "completed_at": session.completed_at.isoformat() if session.completed_at else None,
                    "total_tasks": len(tasks),
                    "completed": self._total_completed,
                    "blocked": self._total_blocked,
                    "tasks": [{"id": task.id, "title": task.title, "status": task.status.value} for task in tasks],
                },
                indent=2,
            )
        )

        removable_dirs = {"intake", "claimed", "staging", "review", "ready", "workers", "blocked"}
        for item in base.iterdir():
            if item.name in removable_dirs and item.is_dir():
                shutil.rmtree(item)

        logs_dir = base / "logs"
        if logs_dir.exists():
            for item in logs_dir.iterdir():
                if item.name == "session.log":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

    def _move_to_done(self, plan_file: Path, status_file: Path, slot_dir: Path) -> None:
        os.rename(str(plan_file), str(self._dirs["done"] / plan_file.name))
        os.rename(str(status_file), str(self._dirs["done"] / status_file.name))
        for log_file in slot_dir.glob("*.log"):
            shutil.move(str(log_file), str(self._dirs["done"] / log_file.name))

    def _add_event(
        self,
        event_type: EventType,
        task_id: Optional[str] = None,
        worker_slot: Optional[int] = None,
        message: str = "",
    ) -> None:
        self.store.add_event(
            Event(
                session_id=self.session_id,
                timestamp=datetime.now(timezone.utc),
                event_type=event_type,
                task_id=task_id,
                worker_slot=worker_slot,
                message=message,
            )
        )

    def _broadcast_message(self, payload: dict[str, Any]) -> None:
        if self._ws_broadcast is None or self._event_loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._ws_broadcast(payload), self._event_loop)
        except Exception:
            logger.debug("Failed to broadcast websocket payload", exc_info=True)

    def _broadcast_state(self) -> None:
        try:
            session = self.store.get_session(self.session_id)
            counts = self.store.pipeline_counts(self.session_id)
            workers = self.store.get_worker_slots(self.session_id)
            state = {
                "type": "state_update",
                "data": {
                    "session_id": self.session_id,
                    "session": {
                        "status": session.status.value,
                        "elapsed": (
                            datetime.now(timezone.utc) - session.started_at
                        ).total_seconds()
                        if session.started_at
                        else 0,
                    },
                    "pipeline": counts,
                    "workers": [
                        {
                            "slot": worker.slot_number,
                            "status": worker.status.value,
                            "task_id": worker.current_task_id,
                        }
                        for worker in workers
                    ],
                },
            }
        except Exception:
            logger.debug("Failed to broadcast state update", exc_info=True)
            return
        self._broadcast_message(state)

    @staticmethod
    def _extract_title_from_plan(plan_path: Path) -> str:
        try:
            in_frontmatter = False
            for raw_line in plan_path.read_text().splitlines():
                line = raw_line.strip()
                if line == "---":
                    in_frontmatter = not in_frontmatter
                    continue
                if in_frontmatter:
                    continue
                if line.startswith("# "):
                    title = line[2:].strip()
                    if title.lower().startswith("plan"):
                        parts = title.split(":", 1)
                        if len(parts) > 1:
                            return parts[1].strip()
                    return title
        except Exception:
            logger.debug("Unable to extract plan title from %s", plan_path, exc_info=True)
        return plan_path.stem
