from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from .hook_runner import HookNotFoundError, run_pack_hook, run_pack_preflight
from .models import (
    OrchestratorResult,
    OrchestratorStartupFailure,
    PackManifest,
    PersistedTask,
)
from .planning_runtime import prepare_session_for_execution
from .recovery import recover_execution_session
from .scheduler import select_next_task
from .state import StateStore
from .worker_manager import (
    WorkerManager,
    WorkerStatusSidecarError,
)


def execute_session(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    env: Mapping[str, str] | None = None,
    poll_interval: float = 0.1,
    kill_grace_period: float = 5.0,
    skip_preflight: bool = False,
) -> OrchestratorResult:
    session = store.get_session(session_id)
    if session.status not in {"created", "running", "paused"}:
        raise ValueError(
            "Execution supports only 'created', 'running', or 'paused' sessions, "
            f"got {session.status!r}"
        )

    initial_status = session.status
    if initial_status in {"running", "paused"}:
        if session.started_at is None:
            session = store.update_session_status(
                session_id,
                status=initial_status,
                started_at=_timestamp(),
            )
        recover_execution_session(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            env=env,
            kill_grace_period=kill_grace_period,
        )
        if initial_status == "paused":
            return OrchestratorResult(
                session_id=session_id,
                started=True,
                session_status="paused",
            )
    else:
        session = store.get_session(session_id)

    if not skip_preflight:
        preflight_result = _run_startup_preflight(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            env=env,
            started=(initial_status != "created"),
        )
        if preflight_result is not None:
            return preflight_result

    if initial_status == "created":
        started_at = _timestamp()
        store.update_session_status(session_id, status="running", started_at=started_at)
        store.append_event(
            session_id,
            timestamp=started_at,
            event_type="session.running",
            message="Execution started.",
        )
        session = store.get_session(session_id)

    manager = WorkerManager(kill_grace_period=kill_grace_period)
    session_paths = store.runtime_paths.session_paths(session_id)
    session_started_at = session.started_at

    while True:
        if (
            pack_manifest.timeouts.session_max > 0
            and _elapsed_since_timestamp(session_started_at) >= pack_manifest.timeouts.session_max
        ):
            return _abort_session_for_timeout(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                manager=manager,
                poll_interval=poll_interval,
                session_timeout=pack_manifest.timeouts.session_max,
            )

        _collect_finished_workers(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            manager=manager,
        )

        ready_tasks = list(store.list_ready_tasks(session_id))
        active_tasks = store.list_active_tasks(session_id)
        blocked_tasks = store.list_blocked_tasks(session_id)
        done_tasks = store.list_done_tasks(session_id)

        if not ready_tasks and not active_tasks:
            if blocked_tasks:
                return OrchestratorResult(
                    session_id=session_id,
                    started=True,
                    session_status=store.get_session(session_id).status,
                    blocked_tasks=tuple(task.task_id for task in blocked_tasks),
                )
            completed_at = _timestamp()
            store.update_session_status(
                session_id,
                status="completed",
                completed_at=completed_at,
            )
            store.append_event(
                session_id,
                timestamp=completed_at,
                event_type="session.completed",
                message="All tasks completed successfully.",
            )
            return OrchestratorResult(
                session_id=session_id,
                started=True,
                session_status="completed",
            )

        active_ids = {task.task_id for task in active_tasks}
        done_ids = {task.task_id for task in done_tasks}
        available_slots = _available_slots(pack_manifest.phases.execution.max_workers, active_tasks)

        for slot_number in available_slots:
            next_task = select_next_task(
                ready_tasks,
                completed_task_ids=done_ids,
                active_task_ids=active_ids,
            )
            if next_task is None:
                break
            ready_tasks = [task for task in ready_tasks if task.task_id != next_task.task_id]
            workspace_path = _prepare_workspace(
                pack_manifest=pack_manifest,
                session_paths=session_paths,
                slot_number=slot_number,
                task=next_task,
                env=env,
            )
            if workspace_path is None:
                blocked_task = store.project_task(
                    session_id,
                    next_task.task_id,
                    status="blocked",
                    timestamp=_timestamp(),
                )
                active_ids.discard(blocked_task.task_id)
                store.append_event(
                    session_id,
                    timestamp=_timestamp(),
                    event_type="task.blocked",
                    task_id=blocked_task.task_id,
                    message="Isolation setup failed.",
                )
                continue

            started_at = _timestamp()
            active_task = store.project_task(
                session_id,
                next_task.task_id,
                status="active",
                worker_slot=slot_number,
                timestamp=started_at,
            )
            pid = manager.dispatch(
                slot_number=slot_number,
                pack_manifest=pack_manifest,
                task_plan_path=active_task.plan_path,
                workspace_path=workspace_path,
                log_path=session_paths.worker_log(slot_number),
                env=env,
            )
            store.write_worker_recovery_metadata(
                session_id,
                slot_number=slot_number,
                task_id=active_task.task_id,
                workspace_path=workspace_path,
                pid=pid,
            )
            active_ids.add(active_task.task_id)
            store.append_event(
                session_id,
                timestamp=started_at,
                event_type="task.dispatched",
                task_id=active_task.task_id,
                message=f"Dispatched to worker slot {slot_number}.",
            )

        time.sleep(poll_interval)


def start_session(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    planner_agent=None,
    resolver_agent=None,
    env: Mapping[str, str] | None = None,
    poll_interval: float = 0.1,
    kill_grace_period: float = 5.0,
) -> OrchestratorResult:
    session = store.get_session(session_id)
    if session.status in {"running", "paused"}:
        return execute_session(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            env=env,
            poll_interval=poll_interval,
            kill_grace_period=kill_grace_period,
        )
    if session.status not in {"created", "planning", "resolving"}:
        raise ValueError(
            "Start supports only 'created', 'planning', 'resolving', 'running', or 'paused' sessions, "
            f"got {session.status!r}"
        )

    preflight_result = _run_startup_preflight(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        env=env,
        started=False,
    )
    if preflight_result is not None:
        return preflight_result

    preparation = prepare_session_for_execution(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        planner_agent=planner_agent,
        resolver_agent=resolver_agent,
        env=dict(env) if env is not None else None,
    )
    if preparation.review_task_ids or preparation.resolution_conflicts:
        return OrchestratorResult(
            session_id=session_id,
            started=False,
            session_status=store.get_session(session_id).status,
            review_tasks=preparation.review_task_ids,
            resolution_conflicts=preparation.resolution_conflicts,
        )
    return execute_session(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        env=env,
        poll_interval=poll_interval,
        kill_grace_period=kill_grace_period,
        skip_preflight=True,
    )


def _collect_finished_workers(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    manager: WorkerManager,
) -> None:
    for slot_number in manager.active_slot_numbers():
        snapshot = manager.poll(slot_number)
        if not snapshot.is_finished:
            continue
        active_task = store.get_task(session_id, snapshot.task_id)
        try:
            result = manager.collect(slot_number)
        except WorkerStatusSidecarError as exc:
            _finalize_blocked_task(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                active_task=active_task,
                slot_number=slot_number,
                workspace_path=snapshot.workspace_path,
                reason=str(exc),
            )
            continue

        if result.timed_out:
            _finalize_blocked_task(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                active_task=active_task,
                slot_number=slot_number,
                workspace_path=result.workspace_path,
                reason=result.failure_reason or "Task timed out.",
            )
            continue

        if result.status is None or result.status.status != "done":
            blocked_reason = (
                result.status.blocked_reason
                if result.status is not None and result.status.blocked_reason
                else f"Worker exited with status {result.exit_code}."
            )
            _finalize_blocked_task(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                active_task=active_task,
                slot_number=slot_number,
                workspace_path=result.workspace_path,
                reason=blocked_reason,
            )
            continue

        if not _run_isolate_end(
            pack_manifest=pack_manifest,
            slot_number=slot_number,
            task_id=active_task.task_id,
            workspace_path=result.workspace_path,
            final_status="done",
        ):
            _finalize_blocked_task(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                active_task=active_task,
                slot_number=slot_number,
                workspace_path=result.workspace_path,
                reason="Isolation teardown failed.",
            )
            continue

        completed_at = _timestamp()
        store.project_task(
            session_id,
            active_task.task_id,
            status="done",
            timestamp=completed_at,
        )
        store.clear_worker_recovery_metadata(session_id, slot_number=slot_number)
        store.append_event(
            session_id,
            timestamp=completed_at,
            event_type="task.completed",
            task_id=active_task.task_id,
            message="Task completed successfully.",
        )


def _finalize_blocked_task(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    active_task: PersistedTask,
    slot_number: int,
    workspace_path: Path,
    reason: str,
) -> None:
    _run_isolate_end(
        pack_manifest=pack_manifest,
        slot_number=slot_number,
        task_id=active_task.task_id,
        workspace_path=workspace_path,
        final_status="blocked",
    )
    blocked_at = _timestamp()
    store.project_task(
        session_id,
        active_task.task_id,
        status="blocked",
        timestamp=blocked_at,
    )
    store.clear_worker_recovery_metadata(session_id, slot_number=slot_number)
    store.append_event(
        session_id,
        timestamp=blocked_at,
        event_type="task.blocked",
        task_id=active_task.task_id,
        message=reason,
    )


def _abort_session_for_timeout(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    manager: WorkerManager,
    poll_interval: float,
    session_timeout: int,
) -> OrchestratorResult:
    reason = f"Session max timeout exceeded ({session_timeout}s)."
    store.append_event(
        session_id,
        timestamp=_timestamp(),
        event_type="session.timeout",
        message=reason,
    )
    for slot_number in manager.active_slot_numbers():
        manager.terminate(
            slot_number,
            reason=f"Killed: {reason}",
            timeout_kind="session_max",
        )

    while manager.active_slot_numbers():
        for slot_number in manager.active_slot_numbers():
            snapshot = manager.poll(slot_number)
            if not snapshot.is_finished:
                continue
            result = manager.collect(slot_number)
            _finalize_blocked_task(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                active_task=store.get_task(session_id, result.task_id),
                slot_number=result.slot_number,
                workspace_path=result.workspace_path,
                reason=result.failure_reason or f"Killed: {reason}",
            )
        if manager.active_slot_numbers():
            time.sleep(poll_interval)

    aborted_at = _timestamp()
    store.update_session_status(session_id, status="aborted", completed_at=aborted_at)
    store.append_event(
        session_id,
        timestamp=aborted_at,
        event_type="session.aborted",
        message=reason,
    )
    return OrchestratorResult(
        session_id=session_id,
        started=True,
        session_status="aborted",
        blocked_tasks=tuple(task.task_id for task in store.list_blocked_tasks(session_id)),
    )


def _prepare_workspace(
    *,
    pack_manifest: PackManifest,
    session_paths,
    slot_number: int,
    task: PersistedTask,
    env: Mapping[str, str] | None,
) -> Path | None:
    if pack_manifest.isolation.type == "none":
        return session_paths.root

    # Minimum safe assumption for packet 06: a non-none isolation mode without a
    # working isolate_start hook is treated as a task-blocking setup failure.
    try:
        result = run_pack_hook(
            pack_manifest,
            "isolate_start",
            args=[str(slot_number), task.task_id, str(session_paths.root)],
            cwd=session_paths.root,
            env=env,
        )
    except HookNotFoundError:
        return None
    if not result.ok:
        return None
    workspace = result.stdout.strip()
    if not workspace:
        return None
    return Path(workspace)


def _run_isolate_end(
    *,
    pack_manifest: PackManifest,
    slot_number: int,
    task_id: str,
    workspace_path: Path,
    final_status: str,
) -> bool:
    if pack_manifest.isolation.type == "none":
        return True
    try:
        result = run_pack_hook(
            pack_manifest,
            "isolate_end",
            args=[
                str(slot_number),
                task_id,
                str(workspace_path),
                final_status,
            ],
            cwd=workspace_path,
        )
    except HookNotFoundError:
        return False
    return result.ok


def _available_slots(max_workers: int, active_tasks: tuple[PersistedTask, ...]) -> list[int]:
    active_slots = {
        task.worker_slot
        for task in active_tasks
        if task.worker_slot is not None
    }
    return [slot for slot in range(max_workers) if slot not in active_slots]


def _preflight_failure_message(preflight) -> str:
    if not preflight.permission_report.ok:
        return "Pack script permissions failed preflight."
    if not preflight.prerequisite_results.ok:
        failed = [result.name for result in preflight.prerequisite_results.results if not result.ok]
        return "Preflight prerequisites failed: " + ", ".join(failed)
    if preflight.preflight_result is not None and not preflight.preflight_result.ok:
        return f"Preflight hook failed with exit code {preflight.preflight_result.exit_code}."
    return "Preflight failed."


def _run_startup_preflight(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    env: Mapping[str, str] | None,
    started: bool,
) -> OrchestratorResult | None:
    preflight = run_pack_preflight(pack_manifest, runtime_paths=store.runtime_paths, env=env)
    if preflight.ok:
        return None
    message = _preflight_failure_message(preflight)
    store.append_event(
        session_id,
        timestamp=_timestamp(),
        event_type="session.preflight_failed",
        message=message,
    )
    return OrchestratorResult(
        session_id=session_id,
        started=started,
        session_status=store.get_session(session_id).status,
        startup_failure=OrchestratorStartupFailure(
            reason="preflight_failed",
            message=message,
        ),
    )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _elapsed_since_timestamp(timestamp: str | None) -> float:
    if not timestamp:
        return 0.0
    return (datetime.now(UTC) - _parse_timestamp(timestamp)).total_seconds()


def _parse_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(UTC)
