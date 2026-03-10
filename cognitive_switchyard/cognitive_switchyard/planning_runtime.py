from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from .hook_runner import run_pack_hook
from .models import (
    PackManifest,
    PlanningPhaseResult,
    ResolutionGraph,
    ResolutionPhaseResult,
    ResolutionTask,
    SessionPreparationResult,
    StagedTaskPlan,
    build_effective_planner_count,
)
from .parsers import (
    ArtifactParseError,
    parse_resolution_json,
    parse_staged_task_plan,
    parse_task_plan,
)
from .state import StateStore

PlannerAgent = Callable[..., str]
ResolverAgent = Callable[..., str]


def prepare_session_for_execution(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    planner_agent: PlannerAgent | None = None,
    resolver_agent: ResolverAgent | None = None,
    effective_planner_count: int | None = None,
    env: dict[str, str] | None = None,
) -> SessionPreparationResult:
    session = store.get_session(session_id)
    if session.status not in {"created", "planning", "resolving"}:
        raise ValueError(
            "Planning/resolution supports only 'created', 'planning', or 'resolving' sessions, "
            f"got {session.status!r}"
        )

    session_paths = store.runtime_paths.session_paths(session_id)
    _recover_claimed_items(session_paths)
    if any(session_paths.review.glob("*.plan.md")):
        store.update_session_status(session_id, status="created")
        return SessionPreparationResult(
            session_id=session_id,
            review_task_ids=_task_ids_from_paths(session_paths.review.glob("*.plan.md")),
        )

    store.update_session_status(session_id, status="planning")
    planning = run_planning_phase(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        planner_agent=planner_agent,
        effective_planner_count=effective_planner_count,
    )
    if planning.review_task_ids:
        store.update_session_status(session_id, status="created")
        return SessionPreparationResult(
            session_id=session_id,
            review_task_ids=planning.review_task_ids,
        )

    store.update_session_status(session_id, status="resolving")
    resolution = run_resolution_phase(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        resolver_agent=resolver_agent,
        env=env,
    )
    if resolution.conflicts:
        store.update_session_status(session_id, status="created")
        return SessionPreparationResult(
            session_id=session_id,
            resolution_conflicts=resolution.conflicts,
        )

    store.update_session_status(session_id, status="created")
    return SessionPreparationResult(
        session_id=session_id,
        ready_task_ids=resolution.ready_task_ids,
    )


def run_planning_phase(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    planner_agent: PlannerAgent | None = None,
    effective_planner_count: int | None = None,
) -> PlanningPhaseResult:
    session_paths = store.runtime_paths.session_paths(session_id)
    session = store.get_session(session_id)
    _recover_claimed_items(session_paths)
    staged_task_ids: list[str] = []
    review_task_ids: list[str] = []

    intake_paths = sorted(
        (p for p in session_paths.intake.iterdir() if p.suffix == ".md"),
        key=_claim_sort_key,
    )
    if pack_manifest.phases.planning.enabled:
        if planner_agent is None:
            raise ValueError("planner_agent is required when planning is enabled")
        planner_count = effective_planner_count
        if planner_count is None:
            planner_count = build_effective_planner_count(
                session=session,
                pack_manifest=pack_manifest,
            )
        planner_count = max(1, planner_count or 1)
        lock = threading.Lock()
        stop_event = threading.Event()
        first_error: Exception | None = None

        def claim_next_intake_path() -> Path | None:
            with lock:
                if stop_event.is_set():
                    return None
                for intake_path in sorted(
                    (p for p in session_paths.intake.iterdir() if p.suffix == ".md"),
                    key=_claim_sort_key,
                ):
                    claimed_path = session_paths.claimed / intake_path.name
                    try:
                        intake_path.replace(claimed_path)
                    except FileNotFoundError:
                        continue
                    return claimed_path
                return None

        def planner_worker() -> None:
            nonlocal first_error
            while not stop_event.is_set():
                claimed_path = claim_next_intake_path()
                if claimed_path is None:
                    return
                try:
                    plan_text = planner_agent(
                        model=pack_manifest.phases.planning.model,
                        prompt_path=pack_manifest.phases.planning.prompt,
                        intake_path=claimed_path,
                        intake_text=claimed_path.read_text(encoding="utf-8"),
                        session_root=session_paths.root,
                        pack_manifest=pack_manifest,
                    )
                    staged_plan = parse_staged_task_plan(plan_text, source=claimed_path)
                    target_dir = (
                        session_paths.review if _needs_review(staged_plan.body) else session_paths.staging
                    )
                    target_path = target_dir / f"{staged_plan.task_id}.plan.md"
                    _atomic_write_text(target_path, plan_text)
                    claimed_path.unlink(missing_ok=True)
                    with lock:
                        if target_dir == session_paths.review:
                            review_task_ids.append(staged_plan.task_id)
                        else:
                            staged_task_ids.append(staged_plan.task_id)
                except Exception as exc:
                    if claimed_path.exists():
                        claimed_path.replace(session_paths.intake / claimed_path.name)
                    with lock:
                        if first_error is None:
                            first_error = exc
                    stop_event.set()
                    return

        with ThreadPoolExecutor(max_workers=planner_count) as executor:
            futures = {executor.submit(planner_worker) for _ in range(planner_count)}
            while futures:
                done, futures = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    future.result()
                if first_error is not None:
                    stop_event.set()
                    for future in futures:
                        future.result()
                    _recover_claimed_items(session_paths)
                    raise first_error
    else:
        invalid_inputs = [path.name for path in intake_paths if path.suffixes[-2:] != [".plan", ".md"]]
        if invalid_inputs:
            raise ValueError(
                "planning-disabled packs only accept intake .plan.md files: "
                + ", ".join(sorted(invalid_inputs))
            )
        for intake_path in intake_paths:
            plan_text = intake_path.read_text(encoding="utf-8")
            staged_plan = parse_staged_task_plan(plan_text, source=intake_path)
            target_path = session_paths.staging / f"{staged_plan.task_id}.plan.md"
            intake_path.replace(target_path)
            staged_task_ids.append(staged_plan.task_id)

    return PlanningPhaseResult(
        session_id=session_id,
        staged_task_ids=tuple(sorted(staged_task_ids)),
        review_task_ids=tuple(sorted(review_task_ids)),
    )


def run_resolution_phase(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    resolver_agent: ResolverAgent | None = None,
    env: dict[str, str] | None = None,
) -> ResolutionPhaseResult:
    session_paths = store.runtime_paths.session_paths(session_id)
    _recover_resolution_inputs(store=store, session_id=session_id)
    input_paths = _resolution_input_paths(session_paths)
    staged_plans = {
        path.name.removesuffix(".plan.md"): parse_staged_task_plan(
            path.read_text(encoding="utf-8"),
            source=path,
        )
        for path in input_paths
    }
    if not staged_plans:
        session_paths.resolution.unlink(missing_ok=True)
        return ResolutionPhaseResult(session_id=session_id)

    if pack_manifest.phases.resolution.executor == "passthrough":
        resolution = _build_passthrough_resolution(staged_plans)
        _atomic_write_text(session_paths.resolution, _serialize_resolution_graph(resolution))
    elif pack_manifest.phases.resolution.executor == "script":
        result = run_pack_hook(
            pack_manifest,
            "resolve",
            args=(str(session_paths.root),),
            cwd=session_paths.root,
            env=env,
        )
        if not result.ok:
            raise RuntimeError(f"resolve hook failed: {result.stderr or result.stdout}".strip())
        if not session_paths.resolution.is_file():
            raise RuntimeError("resolve hook did not write resolution.json")
        resolution = parse_resolution_json(
            session_paths.resolution.read_text(encoding="utf-8"),
            source=session_paths.resolution,
        )
        _atomic_write_text(session_paths.resolution, _serialize_resolution_graph(resolution))
    elif pack_manifest.phases.resolution.executor == "agent":
        if resolver_agent is None:
            raise ValueError("resolver_agent is required when agent resolution is enabled")
        resolution_text = resolver_agent(
            model=pack_manifest.phases.resolution.model,
            prompt_path=pack_manifest.phases.resolution.prompt,
            session_root=session_paths.root,
            staged_plans=tuple(staged_plans.values()),
            plan_paths=input_paths,
            pack_manifest=pack_manifest,
        )
        _atomic_write_text(session_paths.resolution, resolution_text)
        resolution = parse_resolution_json(
            session_paths.resolution.read_text(encoding="utf-8"),
            source=session_paths.resolution,
        )
        _atomic_write_text(session_paths.resolution, _serialize_resolution_graph(resolution))
    else:
        raise ValueError(
            f"Unsupported resolution executor: {pack_manifest.phases.resolution.executor!r}"
        )

    conflicts = list(resolution.conflicts)
    resolved_by_id = {task.task_id: task for task in resolution.tasks}
    missing = sorted(task_id for task_id in staged_plans if task_id not in resolved_by_id)
    if missing:
        conflicts.append("unresolved plans: " + ", ".join(missing))

    if conflicts:
        return ResolutionPhaseResult(
            session_id=session_id,
            conflicts=tuple(conflicts),
        )

    ready_task_ids: list[str] = []
    for task_id, resolution_task in sorted(
        resolved_by_id.items(),
        key=lambda item: (item[1].exec_order, item[0]),
    ):
        staged_plan = staged_plans.get(task_id)
        if staged_plan is None:
            continue
        ready_text = rewrite_staged_plan_as_ready(
            staged_plan,
            depends_on=resolution_task.depends_on,
            anti_affinity=resolution_task.anti_affinity,
            exec_order=resolution_task.exec_order,
        )
        ready_path = session_paths.ready / f"{task_id}.plan.md"
        _atomic_write_text(ready_path, ready_text)
        source_path = _find_existing_plan_path(session_paths, task_id)
        if source_path is not None and source_path != ready_path:
            source_path.unlink(missing_ok=True)
        plan = parse_task_plan(ready_text, source=ready_path)
        store.upsert_ready_task_plan(
            session_id=session_id,
            plan=plan,
            plan_text=ready_text,
            created_at=_timestamp(),
        )
        ready_task_ids.append(task_id)

    for staged_path in session_paths.staging.glob("*.plan.md"):
        if staged_path.name.removesuffix(".plan.md") in ready_task_ids:
            staged_path.unlink(missing_ok=True)

    return ResolutionPhaseResult(
        session_id=session_id,
        ready_task_ids=tuple(ready_task_ids),
    )


def rewrite_staged_plan_as_ready(
    staged_plan: StagedTaskPlan,
    *,
    depends_on: tuple[str, ...],
    anti_affinity: tuple[str, ...],
    exec_order: int,
) -> str:
    metadata = dict(staged_plan.metadata)
    metadata["PLAN_ID"] = staged_plan.task_id
    metadata["DEPENDS_ON"] = ", ".join(depends_on) if depends_on else "none"
    metadata["ANTI_AFFINITY"] = ", ".join(anti_affinity) if anti_affinity else "none"
    metadata["EXEC_ORDER"] = str(exec_order)
    metadata["FULL_TEST_AFTER"] = "yes" if staged_plan.full_test_after else "no"

    ordered_keys = [
        "PLAN_ID",
        *[
            key
            for key in metadata
            if key not in {"PLAN_ID", "DEPENDS_ON", "ANTI_AFFINITY", "EXEC_ORDER", "FULL_TEST_AFTER"}
        ],
        "DEPENDS_ON",
        "ANTI_AFFINITY",
        "EXEC_ORDER",
        "FULL_TEST_AFTER",
    ]
    front_matter_lines = ["---"]
    for key in ordered_keys:
        front_matter_lines.append(f"{key}: {metadata[key]}")
    front_matter_lines.append("---")
    return "\n".join(front_matter_lines) + "\n\n" + staged_plan.body.strip() + "\n"


def _build_passthrough_resolution(
    staged_plans: dict[str, StagedTaskPlan],
) -> ResolutionGraph:
    conflicts: list[str] = []
    visiting: set[str] = set()
    depth_cache: dict[str, int] = {}

    def depth(task_id: str) -> int:
        if task_id in depth_cache:
            return depth_cache[task_id]
        if task_id in visiting:
            conflicts.append(f"circular dependency detected at {task_id}")
            return 1
        visiting.add(task_id)
        staged_plan = staged_plans[task_id]
        depths = []
        for dependency_id in staged_plan.declared_depends_on:
            if dependency_id not in staged_plans:
                conflicts.append(f"unknown dependency {dependency_id} referenced by {task_id}")
                continue
            depths.append(depth(dependency_id))
        visiting.remove(task_id)
        value = (max(depths) if depths else 0) + 1
        depth_cache[task_id] = value
        return value

    tasks = []
    for task_id in sorted(staged_plans):
        staged_plan = staged_plans[task_id]
        tasks.append(
            ResolutionTask(
                task_id=task_id,
                depends_on=staged_plan.declared_depends_on,
                anti_affinity=(),
                exec_order=depth(task_id),
            )
        )
    return ResolutionGraph(
        resolved_at=_timestamp(),
        tasks=tuple(tasks),
        groups=(),
        conflicts=tuple(dict.fromkeys(conflicts)),
        notes="passthrough resolution",
    )


def _recover_claimed_items(session_paths) -> None:
    for claimed_path in sorted(session_paths.claimed.iterdir(), key=_claim_sort_key):
        target_path = session_paths.intake / claimed_path.name
        claimed_path.replace(target_path)


def _recover_resolution_inputs(*, store: StateStore, session_id: str) -> None:
    session_paths = store.runtime_paths.session_paths(session_id)
    session_paths.resolution.unlink(missing_ok=True)
    for ready_path in sorted(session_paths.ready.glob("*.plan.md")):
        task_id = ready_path.name.removesuffix(".plan.md")
        staged_path = session_paths.staging / ready_path.name
        if not staged_path.exists():
            ready_path.replace(staged_path)
        else:
            ready_path.unlink(missing_ok=True)
        store.delete_task(session_id, task_id)


def _resolution_input_paths(session_paths) -> tuple[Path, ...]:
    staging_paths = tuple(sorted(session_paths.staging.glob("*.plan.md")))
    ready_paths = tuple(sorted(session_paths.ready.glob("*.plan.md")))
    return staging_paths + ready_paths


def _claim_sort_key(path: Path) -> tuple[int, str]:
    prefix = path.name.split("_", 1)[0].split(".", 1)[0]
    try:
        return int(prefix), path.name
    except ValueError:
        return 10_000_000, path.name


def _needs_review(body: str) -> bool:
    return "## Questions for Review" in body


def _task_ids_from_paths(paths) -> tuple[str, ...]:
    return tuple(
        sorted(path.name.removesuffix(".plan.md") for path in paths if path.is_file())
    )


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _serialize_resolution_graph(graph: ResolutionGraph) -> str:
    payload = {
        "resolved_at": graph.resolved_at,
        "tasks": [
            {
                "task_id": task.task_id,
                "depends_on": list(task.depends_on),
                "anti_affinity": list(task.anti_affinity),
                "exec_order": task.exec_order,
            }
            for task in graph.tasks
        ],
        "groups": [
            {
                "name": group.name,
                "type": group.type,
                "members": list(group.members),
                "shared_resources": list(group.shared_resources),
            }
            for group in graph.groups
        ],
        "conflicts": list(graph.conflicts),
        "notes": graph.notes,
    }
    return json.dumps(payload, indent=2) + "\n"


def _find_existing_plan_path(session_paths, task_id: str) -> Path | None:
    for directory in (session_paths.ready, session_paths.staging):
        candidate = directory / f"{task_id}.plan.md"
        if candidate.exists():
            return candidate
    return None


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
