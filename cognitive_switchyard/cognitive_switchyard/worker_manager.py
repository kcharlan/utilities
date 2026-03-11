from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, TextIO

from .models import PackManifest, WorkerAlert, WorkerProgressState, WorkerResult, WorkerSnapshot
from .pack_loader import resolve_pack_hook_path
from .parsers import ArtifactParseError, parse_progress_line, parse_status_sidecar


class WorkerManagerError(RuntimeError):
    pass


class WorkerResultError(WorkerManagerError):
    pass


class WorkerStatusSidecarError(WorkerResultError):
    pass


@dataclass
class _ActiveWorker:
    slot_number: int
    task_id: str
    task_plan_path: Path
    workspace_path: Path
    log_path: Path
    process: subprocess.Popen[str]
    log_handle: TextIO
    started_at: float
    last_output_at: float
    task_idle: float
    task_max: float
    progress_format: str
    sidecar_format: str
    progress: WorkerProgressState = field(default_factory=WorkerProgressState)
    pending_lines: list[str] = field(default_factory=list)
    pending_alerts: list[WorkerAlert] = field(default_factory=list)
    timed_out: bool = False
    timeout_kind: str | None = None
    failure_reason: str | None = None
    terminate_sent_at: float | None = None
    kill_escalated: bool = False
    finalized: bool = False
    collected: bool = False
    idle_warning_emitted: bool = False
    task_max_warning_emitted: bool = False
    readers: list[threading.Thread] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


class WorkerManager:
    def __init__(
        self,
        *,
        default_task_idle: float | None = None,
        default_task_max: float | None = None,
        kill_grace_period: float = 5.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._default_task_idle = default_task_idle
        self._default_task_max = default_task_max
        self._kill_grace_period = kill_grace_period
        self._clock = clock or time.monotonic
        self._workers: dict[int, _ActiveWorker] = {}

    def dispatch(
        self,
        *,
        slot_number: int,
        pack_manifest: PackManifest,
        task_plan_path: Path,
        workspace_path: Path,
        log_path: Path,
        env: Mapping[str, str] | None = None,
    ) -> int:
        if slot_number in self._workers and not self._workers[slot_number].collected:
            raise WorkerManagerError(f"worker slot {slot_number} is already active")

        command_path = resolve_pack_hook_path(pack_manifest, "execute")
        if command_path is None:
            raise WorkerManagerError(f"pack {pack_manifest.name!r} does not define an execute hook")

        task_plan_path = task_plan_path.resolve()
        workspace_path = workspace_path.resolve()
        log_path = log_path.resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        started_at = self._clock()
        # Strip CLAUDECODE so child Claude CLI sessions don't refuse to launch
        # when the orchestrator itself is running inside Claude Code.
        command_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        if env is not None:
            command_env.update(env)
        process = subprocess.Popen(
            [str(command_path), str(task_plan_path), str(workspace_path)],
            cwd=workspace_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=command_env,
            text=True,
            bufsize=1,
        )
        log_handle = log_path.open("a", encoding="utf-8")
        worker = _ActiveWorker(
            slot_number=slot_number,
            task_id=_task_id_from_path(task_plan_path),
            task_plan_path=task_plan_path,
            workspace_path=workspace_path,
            log_path=log_path,
            process=process,
            log_handle=log_handle,
            started_at=started_at,
            last_output_at=started_at,
            task_idle=(
                pack_manifest.timeouts.task_idle
                if self._default_task_idle is None
                else self._default_task_idle
            ),
            task_max=(
                pack_manifest.timeouts.task_max
                if self._default_task_max is None
                else self._default_task_max
            ),
            progress_format=pack_manifest.status.progress_format,
            sidecar_format=pack_manifest.status.sidecar_format,
        )
        self._workers[slot_number] = worker
        self._start_reader_threads(worker)
        return process.pid

    def poll(self, slot_number: int) -> WorkerSnapshot:
        worker = self._get_worker(slot_number)
        self._refresh_worker(worker)
        with worker.lock:
            new_output_lines = tuple(worker.pending_lines)
            worker.pending_lines.clear()
            progress = worker.progress
            alerts = tuple(worker.pending_alerts)
            worker.pending_alerts.clear()
        exit_code = worker.process.poll()
        return WorkerSnapshot(
            slot_number=worker.slot_number,
            task_id=worker.task_id,
            pid=worker.process.pid,
            workspace_path=worker.workspace_path,
            log_path=worker.log_path,
            new_output_lines=new_output_lines,
            progress=progress,
            is_finished=worker.finalized,
            exit_code=exit_code,
            timed_out=worker.timed_out,
            alerts=alerts,
        )

    def collect(self, slot_number: int) -> WorkerResult:
        worker = self._get_worker(slot_number)
        self._refresh_worker(worker)
        if not worker.finalized:
            raise WorkerResultError(f"worker slot {slot_number} has not finished")
        if worker.collected:
            raise WorkerResultError(f"worker slot {slot_number} was already collected")

        worker.collected = True
        worker.process.wait(timeout=0)
        try:
            exit_code = worker.process.returncode
            assert exit_code is not None
            result = WorkerResult(
                slot_number=worker.slot_number,
                task_id=worker.task_id,
                pid=worker.process.pid,
                workspace_path=worker.workspace_path,
                log_path=worker.log_path,
                exit_code=exit_code,
                timed_out=worker.timed_out,
                timeout_kind=worker.timeout_kind,
                failure_reason=worker.failure_reason,
                kill_escalated=worker.kill_escalated,
                progress=worker.progress,
            )
            if worker.timed_out:
                return result

            status_path = _status_sidecar_path_from_plan(worker.task_plan_path)
            if not status_path.is_file():
                raise WorkerStatusSidecarError(f"missing status sidecar: {status_path}")
            try:
                status = parse_status_sidecar(
                    status_path.read_text(encoding="utf-8"),
                    source=status_path,
                    sidecar_format=worker.sidecar_format,
                )
            except ArtifactParseError as exc:
                raise WorkerStatusSidecarError(
                    f"invalid status sidecar: {status_path}: {exc}"
                ) from exc
            return WorkerResult(
                slot_number=result.slot_number,
                task_id=result.task_id,
                pid=result.pid,
                workspace_path=result.workspace_path,
                log_path=result.log_path,
                exit_code=result.exit_code,
                timed_out=result.timed_out,
                timeout_kind=result.timeout_kind,
                failure_reason=result.failure_reason,
                kill_escalated=result.kill_escalated,
                progress=result.progress,
                status_path=status_path,
                status=status,
            )
        finally:
            self._workers.pop(slot_number, None)

    def active_slot_numbers(self) -> tuple[int, ...]:
        return tuple(
            slot_number
            for slot_number, worker in sorted(self._workers.items())
            if not worker.collected
        )

    def terminate(
        self,
        slot_number: int,
        *,
        reason: str,
        timeout_kind: str = "session_max",
    ) -> None:
        worker = self._get_worker(slot_number)
        now = self._clock()
        if worker.finalized:
            return
        if worker.process.poll() is not None:
            self._refresh_worker(worker)
            return
        self._terminate_worker(
            worker,
            timeout_kind=timeout_kind,
            reason=reason,
            now=now,
        )

    def _refresh_worker(self, worker: _ActiveWorker) -> None:
        with worker.lock:
            if worker.finalized:
                return

        now = self._clock()
        exit_code = worker.process.poll()
        if exit_code is None:
            self._enforce_timeouts(worker, now)
            exit_code = worker.process.poll()

        if exit_code is not None:
            self._finalize_worker(worker)

    def _enforce_timeouts(self, worker: _ActiveWorker, now: float) -> None:
        if worker.terminate_sent_at is not None:
            if now - worker.terminate_sent_at >= self._kill_grace_period:
                worker.process.kill()
                worker.kill_escalated = True
            return

        self._emit_warning_alerts(worker, now)

        if worker.task_idle > 0 and now - worker.last_output_at >= worker.task_idle:
            self._terminate_worker(
                worker,
                timeout_kind="idle",
                reason=f"Killed: no output for {int(worker.task_idle)}s",
                now=now,
            )
            return

        if worker.task_max > 0 and now - worker.started_at >= worker.task_max:
            self._terminate_worker(
                worker,
                timeout_kind="task_max",
                reason=f"Killed: exceeded max task time {worker.task_max:g}s",
                now=now,
            )

    def _emit_warning_alerts(self, worker: _ActiveWorker, now: float) -> None:
        idle_elapsed = now - worker.last_output_at
        if (
            worker.task_idle > 0
            and not worker.idle_warning_emitted
            and idle_elapsed >= worker.task_idle * 0.8
        ):
            worker.idle_warning_emitted = True
            self._queue_alert(
                worker,
                severity="warning",
                message=(
                    f"No output for {_format_seconds(idle_elapsed)} "
                    f"(timeout at {_format_seconds(worker.task_idle)})"
                ),
            )

        task_elapsed = now - worker.started_at
        if (
            worker.task_max > 0
            and not worker.task_max_warning_emitted
            and task_elapsed >= worker.task_max * 0.8
        ):
            worker.task_max_warning_emitted = True
            self._queue_alert(
                worker,
                severity="warning",
                message=(
                    f"Task runtime {_format_seconds(task_elapsed)} is nearing "
                    f"the max limit {_format_seconds(worker.task_max)}"
                ),
            )

    def _queue_alert(self, worker: _ActiveWorker, *, severity: str, message: str) -> None:
        with worker.lock:
            worker.pending_alerts.append(
                WorkerAlert(
                    severity=severity,
                    task_id=worker.task_id,
                    worker_slot=worker.slot_number,
                    message=message,
                )
            )

    def _terminate_worker(
        self,
        worker: _ActiveWorker,
        *,
        timeout_kind: str,
        reason: str,
        now: float,
    ) -> None:
        worker.timed_out = True
        worker.timeout_kind = timeout_kind
        worker.failure_reason = reason
        worker.terminate_sent_at = now
        worker.process.terminate()

    def _finalize_worker(self, worker: _ActiveWorker) -> None:
        for reader in worker.readers:
            reader.join(timeout=1.0)
        worker.log_handle.flush()
        worker.log_handle.close()
        worker.finalized = True

    def _start_reader_threads(self, worker: _ActiveWorker) -> None:
        assert worker.process.stdout is not None
        assert worker.process.stderr is not None
        for stream in (worker.process.stdout, worker.process.stderr):
            reader = threading.Thread(target=self._read_stream, args=(worker, stream), daemon=True)
            reader.start()
            worker.readers.append(reader)

    def _read_stream(self, worker: _ActiveWorker, stream: TextIO) -> None:
        for raw_line in iter(stream.readline, ""):
            line = raw_line.rstrip("\r\n")
            now = self._clock()
            with worker.lock:
                worker.last_output_at = now
                worker.pending_lines.append(line)
                worker.log_handle.write(raw_line)
                worker.log_handle.flush()
                worker.progress = _updated_progress_state(
                    worker.progress,
                    line,
                    worker.task_id,
                    worker.progress_format,
                )
        stream.close()

    def _get_worker(self, slot_number: int) -> _ActiveWorker:
        try:
            return self._workers[slot_number]
        except KeyError as exc:
            raise WorkerManagerError(f"unknown worker slot {slot_number}") from exc


def _task_id_from_path(task_plan_path: Path) -> str:
    return task_plan_path.name.removesuffix(".plan.md")


def _status_sidecar_path_from_plan(task_plan_path: Path) -> Path:
    plan_name = task_plan_path.name
    if plan_name.endswith(".plan.md"):
        return task_plan_path.with_name(plan_name.removesuffix(".plan.md") + ".status")
    return task_plan_path.with_suffix(".status")


def _updated_progress_state(
    progress: WorkerProgressState,
    line: str,
    expected_task_id: str,
    progress_format: str,
) -> WorkerProgressState:
    try:
        update = parse_progress_line(line, progress_format=progress_format)
    except ArtifactParseError:
        return progress
    if update.task_id != expected_task_id:
        return progress

    if update.kind == "phase":
        return WorkerProgressState(
            task_id=update.task_id,
            phase_name=update.phase_name,
            phase_index=update.phase_index,
            phase_total=update.phase_total,
            detail_message=progress.detail_message,
        )
    return WorkerProgressState(
        task_id=update.task_id,
        phase_name=progress.phase_name,
        phase_index=progress.phase_index,
        phase_total=progress.phase_total,
        detail_message=update.detail_message,
    )


def _format_seconds(value: float) -> str:
    if value >= 10 or value.is_integer():
        return f"{int(round(value))}s"
    return f"{value:.1f}s"
