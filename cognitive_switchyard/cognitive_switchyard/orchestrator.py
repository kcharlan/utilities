from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Mapping

from .hook_runner import HookNotFoundError, run_pack_hook, run_pack_preflight
from .models import BackendRuntimeEvent
from .models import (
    FixerAttemptResult,
    OrchestratorResult,
    OrchestratorStartupFailure,
    PackManifest,
    PersistedTask,
)
from .parsers import ArtifactParseError, parse_progress_line
from .planning_runtime import prepare_session_for_execution
from .recovery import recover_execution_session
from .scheduler import select_next_task
from .state import StateStore
from .verification_runtime import (
    build_task_failure_context,
    build_verification_failure_context,
    run_verification_command,
)
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
    fixer_executor: Callable[..., FixerAttemptResult] | None = None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
) -> OrchestratorResult:
    session = store.get_session(session_id)
    if session.status not in {"created", "running", "paused", "verifying", "auto_fixing"}:
        raise ValueError(
            "Execution supports only 'created', 'running', 'paused', 'verifying', or 'auto_fixing' sessions, "
            f"got {session.status!r}"
        )

    initial_status = session.status
    if initial_status in {"running", "paused", "verifying", "auto_fixing"}:
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
        if initial_status in {"verifying", "auto_fixing"}:
            store.write_session_runtime_state(
                session_id,
                verification_pending=True,
                verification_reason=(
                    "recovery_replay"
                    if session.runtime_state.verification_reason is None
                    else session.runtime_state.verification_reason
                ),
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
                runtime_event_sink=runtime_event_sink,
            )

        _collect_finished_workers(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            manager=manager,
            env=env,
            fixer_executor=fixer_executor,
            runtime_event_sink=runtime_event_sink,
        )

        current_session = store.get_session(session_id)
        active_tasks = store.list_active_tasks(session_id)
        if current_session.status == "aborted":
            return _abort_session(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                manager=manager,
                poll_interval=poll_interval,
                reason="Session aborted by operator.",
            )
        if current_session.status == "paused":
            if active_tasks:
                time.sleep(poll_interval)
                continue
            return OrchestratorResult(
                session_id=session_id,
                started=True,
                session_status="paused",
                blocked_tasks=tuple(task.task_id for task in store.list_blocked_tasks(session_id)),
            )

        ready_tasks = list(store.list_ready_tasks(session_id))
        blocked_tasks = store.list_blocked_tasks(session_id)
        done_tasks = store.list_done_tasks(session_id)

        if pack_manifest.verification.enabled:
            pending_runtime_state = store.get_session(session_id).runtime_state
            if (
                not pending_runtime_state.verification_pending
                and pack_manifest.verification.interval > 0
                and pending_runtime_state.completed_since_verification >= pack_manifest.verification.interval
            ):
                store.write_session_runtime_state(
                    session_id,
                    verification_pending=True,
                    verification_reason="interval",
                )
                pending_runtime_state = store.get_session(session_id).runtime_state

            if pending_runtime_state.verification_pending:
                if active_tasks:
                    time.sleep(poll_interval)
                    continue
                verification_result = _run_pending_verification(
                    store=store,
                    session_id=session_id,
                    pack_manifest=pack_manifest,
                    env=env,
                    fixer_executor=fixer_executor,
                    runtime_event_sink=runtime_event_sink,
                )
                if verification_result is not None:
                    return verification_result
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
            _publish_state_update(runtime_event_sink, session_id)
            return OrchestratorResult(
                session_id=session_id,
                started=True,
                session_status="completed",
            )

        active_ids = {task.task_id for task in active_tasks}
        done_ids = {task.task_id for task in done_tasks}
        available_slots = _available_slots(pack_manifest.phases.execution.max_workers, active_tasks)

        for slot_number in available_slots:
            _publish_worker_runtime_events(
                runtime_event_sink=runtime_event_sink,
                session_id=session_id,
                pack_manifest=pack_manifest,
                snapshot=None,
            )
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
                _publish_task_status_change(
                    runtime_event_sink,
                    session_id=session_id,
                    task_id=blocked_task.task_id,
                    old_status=next_task.status,
                    new_status="blocked",
                    worker_slot=None,
                    notes="Isolation setup failed.",
                )
                _publish_state_update(runtime_event_sink, session_id)
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
            _publish_task_status_change(
                runtime_event_sink,
                session_id=session_id,
                task_id=active_task.task_id,
                old_status=next_task.status,
                new_status="active",
                worker_slot=slot_number,
                notes=f"Dispatched to worker slot {slot_number}.",
            )
            _publish_state_update(runtime_event_sink, session_id)

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
    fixer_executor: Callable[..., FixerAttemptResult] | None = None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
) -> OrchestratorResult:
    session = store.get_session(session_id)
    if session.status in {"running", "paused", "verifying", "auto_fixing"}:
        return execute_session(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            env=env,
            poll_interval=poll_interval,
            kill_grace_period=kill_grace_period,
            fixer_executor=fixer_executor,
            runtime_event_sink=runtime_event_sink,
        )
    if session.status not in {"created", "planning", "resolving"}:
        raise ValueError(
            "Start supports only 'created', 'planning', 'resolving', 'running', 'paused', "
            "'verifying', or 'auto_fixing' sessions, "
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
        fixer_executor=fixer_executor,
        runtime_event_sink=runtime_event_sink,
    )


def _collect_finished_workers(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    manager: WorkerManager,
    env: Mapping[str, str] | None,
    fixer_executor: Callable[..., FixerAttemptResult] | None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
) -> None:
    for slot_number in manager.active_slot_numbers():
        snapshot = manager.poll(slot_number)
        _publish_worker_runtime_events(
            runtime_event_sink=runtime_event_sink,
            session_id=session_id,
            pack_manifest=pack_manifest,
            snapshot=snapshot,
        )
        if not snapshot.is_finished:
            continue
        active_task = store.get_task(session_id, snapshot.task_id)
        try:
            result = manager.collect(slot_number)
        except WorkerStatusSidecarError as exc:
            _handle_failed_task(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                active_task=active_task,
                slot_number=slot_number,
                workspace_path=snapshot.workspace_path,
                reason=str(exc),
                log_path=snapshot.log_path,
                status_path=None,
                env=env,
                fixer_executor=fixer_executor,
                runtime_event_sink=runtime_event_sink,
            )
            continue

        if result.timed_out:
            _handle_failed_task(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                active_task=active_task,
                slot_number=slot_number,
                workspace_path=result.workspace_path,
                reason=result.failure_reason or "Task timed out.",
                log_path=result.log_path,
                status_path=result.status_path,
                env=env,
                fixer_executor=fixer_executor,
                runtime_event_sink=runtime_event_sink,
            )
            continue

        if result.status is None or result.status.status != "done":
            blocked_reason = (
                result.status.blocked_reason
                if result.status is not None and result.status.blocked_reason
                else f"Worker exited with status {result.exit_code}."
            )
            _handle_failed_task(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                active_task=active_task,
                slot_number=slot_number,
                workspace_path=result.workspace_path,
                reason=blocked_reason,
                log_path=result.log_path,
                status_path=result.status_path,
                env=env,
                fixer_executor=fixer_executor,
                runtime_event_sink=runtime_event_sink,
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
                runtime_event_sink=runtime_event_sink,
            )
            continue

        completed_at = _timestamp()
        previous_status = active_task.status
        store.project_task(
            session_id,
            active_task.task_id,
            status="done",
            timestamp=completed_at,
        )
        store.clear_worker_recovery_metadata(session_id, slot_number=slot_number)
        if pack_manifest.verification.enabled:
            current_runtime_state = store.get_session(session_id).runtime_state
            store.write_session_runtime_state(
                session_id,
                completed_since_verification=current_runtime_state.completed_since_verification + 1,
                verification_pending=(
                    active_task.full_test_after or current_runtime_state.verification_pending
                ),
                verification_reason=(
                    "full_test_after"
                    if active_task.full_test_after
                    else current_runtime_state.verification_reason
                ),
            )
        store.append_event(
            session_id,
            timestamp=completed_at,
            event_type="task.completed",
            task_id=active_task.task_id,
            message="Task completed successfully.",
        )
        _publish_task_status_change(
            runtime_event_sink,
            session_id=session_id,
            task_id=active_task.task_id,
            old_status=previous_status,
            new_status="done",
            worker_slot=slot_number,
            notes="Task completed successfully.",
        )
        _publish_state_update(runtime_event_sink, session_id)


def _handle_failed_task(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    active_task: PersistedTask,
    slot_number: int,
    workspace_path: Path,
    reason: str,
    log_path: Path | None,
    status_path: Path | None,
    env: Mapping[str, str] | None,
    fixer_executor: Callable[..., FixerAttemptResult] | None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
) -> None:
    if (
        pack_manifest.auto_fix.enabled
        and fixer_executor is not None
        and pack_manifest.verification.enabled
        and pack_manifest.verification.command
    ):
        _run_isolate_end(
            pack_manifest=pack_manifest,
            slot_number=slot_number,
            task_id=active_task.task_id,
            workspace_path=workspace_path,
            final_status="blocked",
        )
        restored_task = store.project_task(session_id, active_task.task_id, status="ready")
        store.clear_worker_recovery_metadata(session_id, slot_number=slot_number)
        if _attempt_task_auto_fix(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            task=restored_task,
            log_path=log_path,
            status_path=status_path,
            env=env,
            fixer_executor=fixer_executor,
            runtime_event_sink=runtime_event_sink,
        ):
            return
        _finalize_blocked_task(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            active_task=restored_task,
            slot_number=slot_number,
            workspace_path=workspace_path,
            reason=reason,
            run_isolation_end=False,
            runtime_event_sink=runtime_event_sink,
        )
        return
    _finalize_blocked_task(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        active_task=active_task,
        slot_number=slot_number,
        workspace_path=workspace_path,
        reason=reason,
        runtime_event_sink=runtime_event_sink,
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
    run_isolation_end: bool = True,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
) -> None:
    previous_status = active_task.status
    if run_isolation_end:
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
    _publish_task_status_change(
        runtime_event_sink,
        session_id=session_id,
        task_id=active_task.task_id,
        old_status=previous_status,
        new_status="blocked",
        worker_slot=slot_number,
        notes=reason,
    )
    _publish_state_update(runtime_event_sink, session_id)


def _attempt_task_auto_fix(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    task: PersistedTask,
    log_path: Path | None,
    status_path: Path | None,
    env: Mapping[str, str] | None,
    fixer_executor: Callable[..., FixerAttemptResult],
    start_attempt: int = 1,
    previous_summary: str | None = None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
) -> bool:
    session_paths = store.runtime_paths.session_paths(session_id)
    for attempt in range(start_attempt, pack_manifest.auto_fix.max_attempts + 1):
        store.update_session_status(session_id, status="auto_fixing")
        store.write_session_runtime_state(
            session_id,
            verification_pending=True,
            verification_reason="task_auto_fix",
            auto_fix_context="task_failure",
            auto_fix_task_id=task.task_id,
            auto_fix_attempt=attempt,
            last_fix_summary=previous_summary,
        )
        context = build_task_failure_context(
            session_id=session_id,
            task_id=task.task_id,
            attempt=attempt,
            plan_path=task.plan_path,
            status_path=status_path,
            worker_log_path=log_path,
            verify_log_path=session_paths.verify_log,
            previous_attempt_summary=previous_summary,
        )
        fix_result = fixer_executor(context)
        previous_summary = fix_result.summary or previous_summary
        store.write_session_runtime_state(
            session_id,
            last_fix_summary=previous_summary,
            auto_fix_attempt=attempt,
        )
        if not fix_result.success:
            continue
        verification = run_verification_command(
            session_root=session_paths.root,
            verify_log_path=session_paths.verify_log,
            command=pack_manifest.verification.command or "",
            env=env,
        )
        if verification.ok:
            completed_at = _timestamp()
            previous_status = store.get_task(session_id, task.task_id).status
            store.project_task(session_id, task.task_id, status="done", timestamp=completed_at)
            store.append_event(
                session_id,
                timestamp=completed_at,
                event_type="task.completed",
                task_id=task.task_id,
                message="Task completed after auto-fix and verification pass.",
            )
            store.update_session_status(session_id, status="running")
            store.write_session_runtime_state(
                session_id,
                completed_since_verification=0,
                verification_pending=False,
                verification_reason=None,
                auto_fix_context=None,
                auto_fix_task_id=None,
                auto_fix_attempt=0,
                last_fix_summary=previous_summary,
            )
            _publish_task_status_change(
                runtime_event_sink,
                session_id=session_id,
                task_id=task.task_id,
                old_status=previous_status,
                new_status="done",
                worker_slot=task.worker_slot,
                notes="Task completed after auto-fix and verification pass.",
            )
            _publish_state_update(runtime_event_sink, session_id)
            return True
        store.append_event(
            session_id,
            timestamp=_timestamp(),
            event_type="session.verification_failed",
            task_id=task.task_id,
            message="Verification failed after task auto-fix attempt.",
        )
    store.update_session_status(session_id, status="running")
    store.write_session_runtime_state(
        session_id,
        verification_pending=False,
        verification_reason=None,
        auto_fix_context=None,
        auto_fix_task_id=None,
        auto_fix_attempt=0,
        last_fix_summary=previous_summary,
    )
    return False


def _complete_task_after_auto_fix_verification(
    *,
    store: StateStore,
    session_id: str,
    task_id: str,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
) -> None:
    task = store.get_task(session_id, task_id)
    if task.status != "done":
        completed_at = _timestamp()
        store.project_task(session_id, task_id, status="done", timestamp=completed_at)
        store.append_event(
            session_id,
            timestamp=completed_at,
            event_type="task.completed",
            task_id=task_id,
            message="Task completed after auto-fix and verification pass.",
        )
        _publish_task_status_change(
            runtime_event_sink,
            session_id=session_id,
            task_id=task_id,
            old_status=task.status,
            new_status="done",
            worker_slot=task.worker_slot,
            notes="Task completed after auto-fix and verification pass.",
        )
        _publish_state_update(runtime_event_sink, session_id)


def _resume_recovered_task_auto_fix(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    env: Mapping[str, str] | None,
    fixer_executor: Callable[..., FixerAttemptResult],
    runtime_state,
    session_root: Path,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
) -> None:
    task = store.get_task(session_id, runtime_state.auto_fix_task_id)
    if _attempt_task_auto_fix(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        task=task,
        log_path=None,
        status_path=None,
        env=env,
        fixer_executor=fixer_executor,
        start_attempt=runtime_state.auto_fix_attempt + 1,
        previous_summary=runtime_state.last_fix_summary,
        runtime_event_sink=runtime_event_sink,
    ):
        return
    _finalize_blocked_task(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        active_task=store.get_task(session_id, runtime_state.auto_fix_task_id),
        slot_number=0,
        workspace_path=session_root,
        reason="Auto-fix retry budget exhausted after recovery.",
        run_isolation_end=False,
        runtime_event_sink=runtime_event_sink,
    )


def _run_pending_verification(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    env: Mapping[str, str] | None,
    fixer_executor: Callable[..., FixerAttemptResult] | None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
) -> OrchestratorResult | None:
    session_paths = store.runtime_paths.session_paths(session_id)
    runtime_state = store.get_session(session_id).runtime_state
    verification_started_at = _timestamp()
    store.update_session_status(session_id, status="verifying")
    store.append_event(
        session_id,
        timestamp=verification_started_at,
        event_type="session.verification_started",
        message="Verification started.",
    )
    _publish_state_update(runtime_event_sink, session_id)
    verification = run_verification_command(
        session_root=session_paths.root,
        verify_log_path=session_paths.verify_log,
        command=pack_manifest.verification.command or "",
        env=env,
    )
    if verification.ok:
        if runtime_state.auto_fix_context == "task_failure" and runtime_state.auto_fix_task_id is not None:
            _complete_task_after_auto_fix_verification(
                store=store,
                session_id=session_id,
                task_id=runtime_state.auto_fix_task_id,
                runtime_event_sink=runtime_event_sink,
            )
        verified_at = _timestamp()
        store.update_session_status(session_id, status="running")
        store.write_session_runtime_state(
            session_id,
            completed_since_verification=0,
            verification_pending=False,
            verification_reason=None,
            auto_fix_context=None,
            auto_fix_task_id=None,
            auto_fix_attempt=0,
        )
        store.append_event(
            session_id,
            timestamp=verified_at,
            event_type="session.verification_passed",
            message="Verification passed.",
        )
        _publish_state_update(runtime_event_sink, session_id)
        return None

    failed_at = _timestamp()
    store.append_event(
        session_id,
        timestamp=failed_at,
        event_type="session.verification_failed",
        message="Verification failed.",
    )
    if (
        runtime_state.auto_fix_context == "task_failure"
        and runtime_state.auto_fix_task_id is not None
        and pack_manifest.auto_fix.enabled
        and fixer_executor is not None
    ):
        _resume_recovered_task_auto_fix(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            env=env,
            fixer_executor=fixer_executor,
            runtime_state=runtime_state,
            session_root=session_paths.root,
            runtime_event_sink=runtime_event_sink,
        )
        return None
    if not pack_manifest.auto_fix.enabled or fixer_executor is None:
        store.update_session_status(session_id, status="paused")
        _publish_state_update(runtime_event_sink, session_id)
        return OrchestratorResult(
            session_id=session_id,
            started=True,
            session_status="paused",
            blocked_tasks=tuple(task.task_id for task in store.list_blocked_tasks(session_id)),
        )

    previous_summary: str | None = store.get_session(session_id).runtime_state.last_fix_summary
    for attempt in range(1, pack_manifest.auto_fix.max_attempts + 1):
        store.update_session_status(session_id, status="auto_fixing")
        store.write_session_runtime_state(
            session_id,
            verification_pending=True,
            verification_reason="verification_failure",
            auto_fix_context="verification_failure",
            auto_fix_task_id=None,
            auto_fix_attempt=attempt,
            last_fix_summary=previous_summary,
        )
        context = build_verification_failure_context(
            session_id=session_id,
            attempt=attempt,
            verify_log_path=session_paths.verify_log,
            previous_attempt_summary=previous_summary,
        )
        fix_result = fixer_executor(context)
        previous_summary = fix_result.summary or previous_summary
        store.write_session_runtime_state(
            session_id,
            last_fix_summary=previous_summary,
            auto_fix_attempt=attempt,
        )
        if not fix_result.success:
            continue
        store.update_session_status(session_id, status="verifying")
        verification = run_verification_command(
            session_root=session_paths.root,
            verify_log_path=session_paths.verify_log,
            command=pack_manifest.verification.command or "",
            env=env,
        )
        if verification.ok:
            verified_at = _timestamp()
            store.update_session_status(session_id, status="running")
            store.write_session_runtime_state(
                session_id,
                completed_since_verification=0,
                verification_pending=False,
                verification_reason=None,
                auto_fix_context=None,
                auto_fix_task_id=None,
                auto_fix_attempt=0,
                last_fix_summary=previous_summary,
            )
            store.append_event(
                session_id,
                timestamp=verified_at,
                event_type="session.verification_passed",
                message="Verification passed.",
            )
            _publish_state_update(runtime_event_sink, session_id)
            return None
        store.append_event(
            session_id,
            timestamp=_timestamp(),
            event_type="session.verification_failed",
            message="Verification failed after auto-fix attempt.",
        )

    store.update_session_status(session_id, status="paused")
    _publish_state_update(runtime_event_sink, session_id)
    return OrchestratorResult(
        session_id=session_id,
        started=True,
        session_status="paused",
        blocked_tasks=tuple(task.task_id for task in store.list_blocked_tasks(session_id)),
    )


def _abort_session_for_timeout(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    manager: WorkerManager,
    poll_interval: float,
    session_timeout: int,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
) -> OrchestratorResult:
    reason = f"Session max timeout exceeded ({session_timeout}s)."
    store.append_event(
        session_id,
        timestamp=_timestamp(),
        event_type="session.timeout",
        message=reason,
    )
    _publish_alert(
        runtime_event_sink,
        session_id=session_id,
        severity="error",
        task_id=None,
        worker_slot=None,
        message=reason,
    )
    return _abort_session(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        manager=manager,
        poll_interval=poll_interval,
        reason=reason,
        timeout_kind="session_max",
        runtime_event_sink=runtime_event_sink,
    )


def _abort_session(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    manager: WorkerManager,
    poll_interval: float,
    reason: str,
    timeout_kind: str = "abort",
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
) -> OrchestratorResult:
    for slot_number in manager.active_slot_numbers():
        manager.terminate(
            slot_number,
            reason=f"Killed: {reason}",
            timeout_kind=timeout_kind,
        )

    while manager.active_slot_numbers():
        for slot_number in manager.active_slot_numbers():
            snapshot = manager.poll(slot_number)
            _publish_worker_runtime_events(
                runtime_event_sink=runtime_event_sink,
                session_id=session_id,
                pack_manifest=pack_manifest,
                snapshot=snapshot,
            )
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
                runtime_event_sink=runtime_event_sink,
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
    _publish_state_update(runtime_event_sink, session_id)
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


def _publish_state_update(
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
    session_id: str,
) -> None:
    _publish_runtime_event(runtime_event_sink, "state_update", session_id=session_id)


def _publish_task_status_change(
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
    *,
    session_id: str,
    task_id: str,
    old_status: str,
    new_status: str,
    worker_slot: int | None,
    notes: str,
) -> None:
    _publish_runtime_event(
        runtime_event_sink,
        "task_status_change",
        session_id=session_id,
        data={
            "task_id": task_id,
            "old_status": old_status,
            "new_status": new_status,
            "worker_slot": worker_slot,
            "notes": notes,
        },
    )


def _publish_alert(
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
    *,
    session_id: str,
    severity: str,
    task_id: str | None,
    worker_slot: int | None,
    message: str,
) -> None:
    payload = {"severity": severity, "message": message}
    if task_id is not None:
        payload["task_id"] = task_id
    if worker_slot is not None:
        payload["worker_slot"] = worker_slot
    _publish_runtime_event(
        runtime_event_sink,
        "alert",
        session_id=session_id,
        data=payload,
    )


def _publish_worker_runtime_events(
    *,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
    session_id: str,
    pack_manifest: PackManifest,
    snapshot,
) -> None:
    if runtime_event_sink is None or snapshot is None:
        return
    for alert in snapshot.alerts:
        _publish_runtime_event(
            runtime_event_sink,
            "alert",
            session_id=session_id,
            data={
                "severity": alert.severity,
                "task_id": alert.task_id,
                "worker_slot": alert.worker_slot,
                "message": alert.message,
            },
        )
    for line in snapshot.new_output_lines:
        timestamp = _timestamp()
        _publish_runtime_event(
            runtime_event_sink,
            "log_line",
            session_id=session_id,
            data={
                "worker_slot": snapshot.slot_number,
                "task_id": snapshot.task_id,
                "line": line,
                "timestamp": timestamp,
            },
        )
        try:
            update = parse_progress_line(line, progress_format=pack_manifest.status.progress_format)
        except ArtifactParseError:
            continue
        if update.task_id != snapshot.task_id or update.kind != "detail":
            continue
        _publish_runtime_event(
            runtime_event_sink,
            "progress_detail",
            session_id=session_id,
            data={
                "worker_slot": snapshot.slot_number,
                "task_id": snapshot.task_id,
                "detail": update.detail_message,
                "timestamp": timestamp,
            },
        )


def _publish_runtime_event(
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
    message_type: str,
    *,
    session_id: str,
    data: dict | None = None,
) -> None:
    if runtime_event_sink is None:
        return
    runtime_event_sink(
        BackendRuntimeEvent(
            message_type=message_type,
            session_id=session_id,
            data={} if data is None else data,
        )
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
