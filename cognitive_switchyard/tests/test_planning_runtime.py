from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from cognitive_switchyard.config import build_runtime_paths
from cognitive_switchyard.pack_loader import load_pack_manifest
from cognitive_switchyard.parsers import (
    parse_resolution_json,
    parse_staged_task_plan,
    parse_task_plan,
)
from cognitive_switchyard.planning_runtime import (
    prepare_session_for_execution,
    run_planning_phase,
    run_resolution_phase,
)
from cognitive_switchyard.state import StateStore, initialize_state_store


def _build_store(tmp_path: Path) -> tuple[StateStore, object]:
    runtime_paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(runtime_paths)
    return store, runtime_paths


def _write_script(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(contents).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)


def _write_pack(
    tmp_path: Path,
    *,
    name: str,
    planning_enabled: bool = False,
    resolution_executor: str = "passthrough",
    resolve_script_body: str | None = None,
    execute_script_body: str = """
    #!/usr/bin/env python3
    raise SystemExit(0)
    """,
) -> Path:
    pack_root = tmp_path / name
    scripts_dir = pack_root / "scripts"
    prompts_dir = pack_root / "prompts"
    scripts_dir.mkdir(parents=True)
    prompts_dir.mkdir(parents=True)

    manifest_lines = [
        f"name: {name}",
        "description: Planning runtime test pack.",
        "version: 1.2.3",
        "",
        "phases:",
    ]
    if planning_enabled:
        (prompts_dir / "planner.md").write_text("planner prompt\n", encoding="utf-8")
        manifest_lines.extend(
            [
                "  planning:",
                "    enabled: true",
                "    executor: agent",
                "    model: test-planner",
                "    prompt: prompts/planner.md",
            ]
        )
    if resolution_executor == "agent":
        (prompts_dir / "resolver.md").write_text("resolver prompt\n", encoding="utf-8")
        manifest_lines.extend(
            [
                "  resolution:",
                "    enabled: true",
                "    executor: agent",
                "    model: test-resolver",
                "    prompt: prompts/resolver.md",
            ]
        )
    elif resolution_executor == "script":
        _write_script(scripts_dir / "resolve", resolve_script_body or "")
        manifest_lines.extend(
            [
                "  resolution:",
                "    enabled: true",
                "    executor: script",
                "    script: scripts/resolve",
            ]
        )
    else:
        manifest_lines.extend(
            [
                "  resolution:",
                "    enabled: true",
                "    executor: passthrough",
            ]
        )
    _write_script(scripts_dir / "execute", execute_script_body)
    manifest_lines.extend(
        [
            "  execution:",
            "    enabled: true",
            "    executor: shell",
            "    command: scripts/execute",
        ]
    )
    (pack_root / "pack.yaml").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    return pack_root


def _write_intake(path: Path, name: str, contents: str) -> Path:
    target = path / name
    target.write_text(dedent(contents).lstrip(), encoding="utf-8")
    return target


def _staged_plan_text(
    task_id: str,
    *,
    depends_on: str = "none",
    full_test_after: str = "no",
    body_extra: str = "",
) -> str:
    return dedent(
        f"""
        ---
        PLAN_ID: {task_id}
        PRIORITY: normal
        ESTIMATED_SCOPE: src/{task_id}.py
        DEPENDS_ON: {depends_on}
        FULL_TEST_AFTER: {full_test_after}
        ---

        # Plan: Task {task_id}

        Implement task {task_id}.
        {body_extra}
        """
    ).lstrip()


def _write_staging_plan(session_root: Path, task_id: str, *, depends_on: str = "none") -> Path:
    path = session_root / "staging" / f"{task_id}.plan.md"
    path.write_text(_staged_plan_text(task_id, depends_on=depends_on), encoding="utf-8")
    return path


def test_planner_claims_oldest_intake_item_and_writes_staged_plan(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-08-plan-oldest",
        name="Packet 08 planning oldest",
        pack="planning-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="planning-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)
    _write_intake(session_paths.intake, "001_first.md", "# First intake\n")
    _write_intake(session_paths.intake, "002_second.md", "# Second intake\n")

    seen: list[str] = []

    def planner_agent(*, intake_path: Path, **_: object) -> str:
        seen.append(intake_path.name)
        task_id = intake_path.name.split("_", 1)[0]
        return _staged_plan_text(task_id)

    result = run_planning_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
    )

    assert seen == ["001_first.md", "002_second.md"]
    assert result.staged_task_ids == ("001", "002")
    assert result.review_task_ids == ()
    assert sorted(path.name for path in session_paths.staging.glob("*.plan.md")) == [
        "001.plan.md",
        "002.plan.md",
    ]
    assert not any(session_paths.claimed.iterdir())
    assert not any(session_paths.intake.iterdir())


def test_planner_output_with_questions_goes_to_review_and_halts_before_resolution(
    tmp_path: Path,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-08-review-halt",
        name="Packet 08 review halt",
        pack="review-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="review-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)
    _write_intake(session_paths.intake, "010_review.md", "# Needs review\n")

    def planner_agent(**_: object) -> str:
        return _staged_plan_text(
            "010",
            body_extra="""

            ## Questions for Review

            1. Which branch should this target?
            """,
        )

    result = prepare_session_for_execution(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
    )

    assert result.review_task_ids == ("010",)
    assert result.ready_task_ids == ()
    assert result.resolution_conflicts == ()
    assert (session_paths.review / "010.plan.md").is_file()
    assert not session_paths.resolution.exists()
    assert not any(session_paths.ready.iterdir())
    assert store.list_ready_tasks(session.id) == ()


def test_planning_disabled_session_promotes_valid_intake_plan_files_to_staging(
    tmp_path: Path,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-08-no-planner",
        name="Packet 08 planning disabled",
        pack="no-planner-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="no-planner-pack", planning_enabled=False)
    session_paths = runtime_paths.session_paths(session.id)
    intake_plan = session_paths.intake / "021.plan.md"
    intake_plan.write_text(_staged_plan_text("021"), encoding="utf-8")

    result = run_planning_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    assert result.staged_task_ids == ("021",)
    assert result.review_task_ids == ()
    assert not intake_plan.exists()
    staged_path = session_paths.staging / "021.plan.md"
    assert staged_path.is_file()
    assert parse_staged_task_plan(
        staged_path.read_text(encoding="utf-8"),
        source=staged_path,
    ).task_id == "021"


def test_passthrough_resolution_writes_resolution_json_and_moves_plans_to_ready(
    tmp_path: Path,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-08-passthrough",
        name="Packet 08 passthrough",
        pack="passthrough-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="passthrough-pack", resolution_executor="passthrough")
    session_paths = runtime_paths.session_paths(session.id)
    _write_staging_plan(session_paths.root, "031")
    _write_staging_plan(session_paths.root, "032", depends_on="031")

    result = run_resolution_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    resolution = parse_resolution_json(
        session_paths.resolution.read_text(encoding="utf-8"),
        source=session_paths.resolution,
    )
    assert result.ready_task_ids == ("031", "032")
    assert result.conflicts == ()
    assert [task.task_id for task in resolution.tasks] == ["031", "032"]
    assert resolution.tasks[0].anti_affinity == ()
    assert resolution.tasks[0].exec_order == 1
    assert resolution.tasks[1].depends_on == ("031",)
    assert resolution.tasks[1].exec_order == 2
    ready_text = (session_paths.ready / "032.plan.md").read_text(encoding="utf-8")
    assert "ANTI_AFFINITY: none" in ready_text
    assert "EXEC_ORDER: 2" in ready_text
    assert [task.task_id for task in store.list_ready_tasks(session.id)] == ["031", "032"]


def test_resolution_rerun_with_conflicts_clears_stale_ready_outputs_before_halting(
    tmp_path: Path,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-08-rerun-conflict",
        name="Packet 08 rerun conflict",
        pack="rerun-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="rerun-pack", resolution_executor="passthrough")
    session_paths = runtime_paths.session_paths(session.id)
    _write_staging_plan(session_paths.root, "035")

    first = run_resolution_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    assert first.ready_task_ids == ("035",)
    assert [task.task_id for task in store.list_ready_tasks(session.id)] == ["035"]

    _write_staging_plan(session_paths.root, "036", depends_on="999")

    second = run_resolution_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    assert second.ready_task_ids == ()
    assert second.conflicts == ("unknown dependency 999 referenced by 036",)
    assert sorted(path.name for path in session_paths.staging.glob("*.plan.md")) == [
        "035.plan.md",
        "036.plan.md",
    ]
    assert not any(session_paths.ready.glob("*.plan.md"))
    assert store.list_ready_tasks(session.id) == ()


@pytest.mark.parametrize("mode", ["script", "agent"])
def test_script_or_agent_resolution_rewrites_plan_headers_and_registers_ready_tasks(
    tmp_path: Path,
    mode: str,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id=f"session-08-{mode}",
        name=f"Packet 08 {mode}",
        pack=f"{mode}-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    if mode == "script":
        pack_root = _write_pack(
            tmp_path,
            name="script-pack",
            resolution_executor="script",
            resolve_script_body="""
            #!/usr/bin/env python3
            import json
            import sys
            from pathlib import Path

            session_root = Path(sys.argv[1])
            resolution_path = session_root / "resolution.json"
            resolution_path.write_text(json.dumps({
                "resolved_at": "2026-03-09T11:00:00Z",
                "tasks": [
                    {
                        "task_id": "041",
                        "depends_on": [],
                        "anti_affinity": ["042"],
                        "exec_order": 5,
                    },
                    {
                        "task_id": "042",
                        "depends_on": ["041"],
                        "anti_affinity": [],
                        "exec_order": 6,
                    },
                ],
                "groups": [],
                "conflicts": [],
                "notes": "script resolution"
            }) + "\\n", encoding="utf-8")
            """,
        )
        resolver_agent = None
    else:
        pack_root = _write_pack(tmp_path, name="agent-pack", resolution_executor="agent")

        def resolver_agent(*, model: str, prompt_path: Path, session_root: Path, **_: object) -> str:
            assert model == "test-resolver"
            assert prompt_path.name == "resolver.md"
            assert session_root.name == session.id
            return dedent(
                """
                {
                  "resolved_at": "2026-03-09T11:00:00Z",
                  "tasks": [
                    {
                      "task_id": "041",
                      "depends_on": [],
                      "anti_affinity": ["042"],
                      "exec_order": 5
                    },
                    {
                      "task_id": "042",
                      "depends_on": ["041"],
                      "anti_affinity": [],
                      "exec_order": 6
                    }
                  ],
                  "groups": [],
                  "conflicts": [],
                  "notes": "agent resolution"
                }
                """
            ).strip()

    session_paths = runtime_paths.session_paths(session.id)
    _write_staging_plan(session_paths.root, "041")
    _write_staging_plan(session_paths.root, "042")

    result = run_resolution_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        resolver_agent=resolver_agent,
    )

    assert result.ready_task_ids == ("041", "042")
    ready_plan = parse_task_plan(
        (session_paths.ready / "041.plan.md").read_text(encoding="utf-8"),
        source=session_paths.ready / "041.plan.md",
    )
    assert ready_plan.anti_affinity == ("042",)
    assert ready_plan.exec_order == 5
    persisted = store.get_task(session.id, "042")
    assert persisted.depends_on == ("041",)
    assert persisted.exec_order == 6
