from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent
from datetime import UTC, datetime, timedelta

from cognitive_switchyard.config import build_runtime_paths
from cognitive_switchyard.models import TaskPlan
from cognitive_switchyard.pack_loader import load_pack_manifest
from cognitive_switchyard.state import StateStore, initialize_state_store


def _build_store(tmp_path: Path) -> tuple[StateStore, object]:
    runtime_paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(runtime_paths)
    return store, runtime_paths


def _write_script(path: Path, contents: str, *, executable: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(contents).lstrip(), encoding="utf-8")
    mode = path.stat().st_mode
    if executable:
        path.chmod(mode | 0o111)
    else:
        path.chmod(mode & ~0o111)


def _write_pack(
    tmp_path: Path,
    *,
    name: str,
    max_workers: int = 2,
    task_idle: int = 5,
    task_max: int = 0,
    session_max: int = 60,
    isolation_type: str = "none",
    prerequisites: str = "",
    preflight: str | None = None,
    isolate_start: str | None = None,
    isolate_end: str | None = None,
    planning_enabled: bool = False,
    resolution_executor: str | None = None,
    resolve_script_name: str = "resolve",
    resolve_script_body: str | None = None,
    verification_enabled: bool = False,
    verification_interval: int = 4,
    verification_command: str | None = None,
    auto_fix_enabled: bool = False,
    execute_script_name: str = "execute.py",
    execute_script_body: str,
) -> Path:
    pack_root = tmp_path / name
    scripts_dir = pack_root / "scripts"
    scripts_dir.mkdir(parents=True)
    prompts_dir = pack_root / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    isolation_block = f"isolation:\n  type: {isolation_type}\n"
    if isolate_start is not None:
        _write_script(scripts_dir / "isolate_start.py", isolate_start)
        isolation_block += "  setup: scripts/isolate_start.py\n"
    if isolate_end is not None:
        _write_script(scripts_dir / "isolate_end.py", isolate_end)
        isolation_block += "  teardown: scripts/isolate_end.py\n"
    if preflight is not None:
        _write_script(scripts_dir / "preflight", preflight)

    _write_script(scripts_dir / execute_script_name, execute_script_body)

    manifest_lines = [
        f"name: {name}",
        "description: Orchestrator test pack.",
        "version: 1.2.3",
        "",
    ]
    if prerequisites.strip():
        manifest_lines.extend(dedent(prerequisites).strip().splitlines())
        manifest_lines.append("")
    manifest_lines.extend(
        [
            "phases:",
        ]
    )
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
        _write_script(scripts_dir / resolve_script_name, resolve_script_body or "")
        manifest_lines.extend(
            [
                "  resolution:",
                "    enabled: true",
                "    executor: script",
                f"    script: scripts/{resolve_script_name}",
            ]
        )
    elif resolution_executor == "passthrough":
        manifest_lines.extend(
            [
                "  resolution:",
                "    enabled: true",
                "    executor: passthrough",
            ]
        )
    manifest_lines.extend(
        [
            "  execution:",
            "    enabled: true",
            "    executor: shell",
            f"    command: scripts/{execute_script_name}",
            f"    max_workers: {max_workers}",
        ]
    )
    if verification_enabled:
        assert verification_command is not None
        manifest_lines.extend(
            [
                "  verification:",
                "    enabled: true",
                "    command: >-",
                f"      {verification_command}",
                f"    interval: {verification_interval}",
            ]
        )
    manifest_lines.append("")
    if auto_fix_enabled:
        (prompts_dir / "fixer.md").write_text("fixer prompt\n", encoding="utf-8")
        manifest_lines.extend(
            [
                "auto_fix:",
                "  enabled: true",
                "  max_attempts: 2",
                "  model: test-fixer",
                "  prompt: prompts/fixer.md",
                "",
            ]
        )
    manifest_lines.extend(
        [
            "timeouts:",
            f"  task_idle: {task_idle}",
            f"  task_max: {task_max}",
            f"  session_max: {session_max}",
            "",
        ]
    )
    manifest_lines.extend(isolation_block.strip().splitlines())
    (pack_root / "pack.yaml").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    return pack_root


def _register_task(
    store: StateStore,
    *,
    session_id: str,
    task_id: str,
    depends_on: tuple[str, ...] = (),
    anti_affinity: tuple[str, ...] = (),
    exec_order: int = 1,
    full_test_after: bool = False,
) -> None:
    plan = TaskPlan(
        task_id=task_id,
        title=f"Task {task_id}",
        depends_on=depends_on,
        anti_affinity=anti_affinity,
        exec_order=exec_order,
        full_test_after=full_test_after,
    )
    store.register_task_plan(
        session_id=session_id,
        plan=plan,
        plan_text=dedent(
            f"""
            ---
            PLAN_ID: {task_id}
            DEPENDS_ON: {", ".join(depends_on) if depends_on else "none"}
            ANTI_AFFINITY: {", ".join(anti_affinity) if anti_affinity else "none"}
            EXEC_ORDER: {exec_order}
            FULL_TEST_AFTER: {"yes" if full_test_after else "no"}
            ---

            # Plan: Task {task_id}
            """
        ).lstrip(),
        created_at="2026-03-09T10:00:00Z",
    )


def _timestamp_offset(*, seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def test_start_execution_runs_preflight_before_marking_session_running(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-06-preflight",
        name="Packet 06 preflight",
        pack="preflight-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001")

    pack_root = _write_pack(
        tmp_path,
        name="preflight-pack",
        prerequisites="""
        prerequisites:
          - name: Missing dependency
            check: exit 7
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        raise SystemExit(0)
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    assert result.started is False
    assert result.session_status == "created"
    assert result.startup_failure is not None
    assert result.startup_failure.reason == "preflight_failed"
    assert store.get_session(session.id).status == "created"
    assert store.list_events(session.id)[0].event_type == "session.preflight_failed"


def test_running_session_recovers_before_preflight_failure_returns_stranded_work_to_ready(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-running-preflight-failure",
        name="Packet 07 running preflight failure",
        pack="running-preflight-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="090")
    active_task = store.project_task(
        session.id,
        "090",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at=_timestamp_offset(seconds=-5),
    )

    pack_root = _write_pack(
        tmp_path,
        name="running-preflight-pack",
        prerequisites="""
        prerequisites:
          - name: Broken dependency
            check: exit 9
        """,
        isolation_type="temp-directory",
        isolate_end="""
        #!/usr/bin/env python3
        raise SystemExit(0)
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        raise SystemExit(0)
        """,
    )
    workspace_path = runtime_paths.session_paths(session.id).root / "workspace" / "090"
    workspace_path.mkdir(parents=True, exist_ok=True)
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="090",
        workspace_path=workspace_path,
        pid=None,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    assert result.started is True
    assert result.session_status == "running"
    assert result.startup_failure is not None
    assert store.get_task(session.id, "090").status == "ready"
    assert store.get_task(session.id, "090").plan_path == runtime_paths.session_paths(session.id).ready / "090.plan.md"
    assert not runtime_paths.session_paths(session.id).worker_recovery_path(0).exists()


def test_paused_session_recovers_without_dispatch_even_if_preflight_would_fail(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-paused-preflight-failure",
        name="Packet 07 paused preflight failure",
        pack="paused-preflight-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="091")
    store.project_task(
        session.id,
        "091",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.update_session_status(
        session.id,
        status="paused",
        started_at=_timestamp_offset(seconds=-5),
    )

    pack_root = _write_pack(
        tmp_path,
        name="paused-preflight-pack",
        prerequisites="""
        prerequisites:
          - name: Broken dependency
            check: exit 9
        """,
        isolation_type="temp-directory",
        isolate_end="""
        #!/usr/bin/env python3
        raise SystemExit(0)
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        raise SystemExit(0)
        """,
    )
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="091",
        workspace_path=runtime_paths.session_paths(session.id).root / "workspace" / "091",
        pid=None,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    assert result.started is True
    assert result.session_status == "paused"
    assert result.startup_failure is None
    assert store.get_session(session.id).status == "paused"
    assert store.get_task(session.id, "091").status == "ready"


def test_dispatch_respects_dependencies_anti_affinity_and_max_workers(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-06-dispatch",
        name="Packet 06 dispatch",
        pack="dispatch-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001", exec_order=1)
    _register_task(store, session_id=session.id, task_id="002", anti_affinity=("003",), exec_order=1)
    _register_task(store, session_id=session.id, task_id="003", anti_affinity=("002",), exec_order=1)
    _register_task(store, session_id=session.id, task_id="004", depends_on=("001",), exec_order=1)

    pack_root = _write_pack(
        tmp_path,
        name="dispatch-pack",
        max_workers=2,
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        import time
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.split('.', 1)[0]
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        trace_path = Path(os.environ['ORCH_TRACE'])
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with trace_path.open('a', encoding='utf-8') as handle:
            handle.write(f"start:{task_id}\\n")
        time.sleep(0.25 if task_id == "002" else 0.12)
        status_path.write_text("STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n", encoding='utf-8')
        with trace_path.open('a', encoding='utf-8') as handle:
            handle.write(f"end:{task_id}\\n")
        """,
    )
    trace_path = tmp_path / "dispatch-trace.log"

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"ORCH_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    dispatch_events = [
        event.task_id
        for event in store.list_events(session.id)
        if event.event_type == "task.dispatched"
    ]
    trace_lines = trace_path.read_text(encoding="utf-8").splitlines()

    assert result.session_status == "completed"
    assert dispatch_events == ["001", "002", "004", "003"]
    assert set(trace_lines[:2]) == {"start:001", "start:002"}
    assert trace_lines.index("start:004") > trace_lines.index("end:001")
    assert trace_lines.index("start:003") > trace_lines.index("end:002")
    assert trace_lines.index("start:004") < trace_lines.index("start:003")


def test_successful_task_runs_isolation_worker_collection_and_done_projection(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-06-success",
        name="Packet 06 success",
        pack="isolation-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="010")

    marker_path = tmp_path / "isolation.log"
    pack_root = _write_pack(
        tmp_path,
        name="isolation-pack",
        isolation_type="temp-directory",
        isolate_start=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        slot, task_id, session_root = sys.argv[1:4]
        workspace = Path(session_root) / "isolated" / task_id
        workspace.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"start|{{slot}}|{{task_id}}|{{session_root}}\\n", encoding='utf-8')
        print(workspace)
        """,
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        slot, task_id, workspace, status = sys.argv[1:5]
        with marker.open('a', encoding='utf-8') as handle:
            handle.write(f"end|{{slot}}|{{task_id}}|{{workspace}}|{{status}}\\n")
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        status_path.write_text("STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n", encoding='utf-8')
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    task = store.get_task(session.id, "010")
    marker_lines = marker_path.read_text(encoding="utf-8").splitlines()
    expected_workspace = runtime_paths.session_paths(session.id).root / "isolated" / "010"

    assert result.session_status == "completed"
    assert task.status == "done"
    assert task.plan_path == runtime_paths.session_paths(session.id).done / "010.plan.md"
    assert marker_lines[0].startswith("start|0|010|")
    assert marker_lines[1] == f"end|0|010|{expected_workspace}|done"


def test_failed_or_timed_out_task_moves_to_blocked_and_calls_isolate_end_with_blocked_status(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-06-blocked",
        name="Packet 06 blocked",
        pack="blocked-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="011")

    marker_path = tmp_path / "blocked-isolation.log"
    pack_root = _write_pack(
        tmp_path,
        name="blocked-pack",
        task_idle=1,
        isolation_type="temp-directory",
        isolate_start="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        workspace = Path(sys.argv[3]) / "workspace" / sys.argv[2]
        workspace.mkdir(parents=True, exist_ok=True)
        print(workspace)
        """,
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        import time

        time.sleep(2)
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    task = store.get_task(session.id, "011")
    blocked_events = [event for event in store.list_events(session.id) if event.event_type == "task.blocked"]
    expected_workspace = runtime_paths.session_paths(session.id).root / "workspace" / "011"

    assert result.session_status == "running"
    assert result.blocked_tasks == ("011",)
    assert task.status == "blocked"
    assert task.plan_path == runtime_paths.session_paths(session.id).blocked / "011.plan.md"
    assert marker_path.read_text(encoding="utf-8").strip() == f"0|011|{expected_workspace}|blocked"
    assert "no output" in blocked_events[0].message


def test_invalid_status_sidecar_moves_task_to_blocked_and_calls_isolate_end_with_workspace(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-06-invalid-sidecar",
        name="Packet 06 invalid sidecar",
        pack="invalid-sidecar-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="012")

    marker_path = tmp_path / "invalid-sidecar-isolation.log"
    pack_root = _write_pack(
        tmp_path,
        name="invalid-sidecar-pack",
        isolation_type="temp-directory",
        isolate_start="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        workspace = Path(sys.argv[3]) / "workspace" / sys.argv[2]
        workspace.mkdir(parents=True, exist_ok=True)
        print(workspace)
        """,
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        status_path.write_text("STATUS: blocked\\nCOMMITS: none\\nTEST_RESULT: skip\\n", encoding='utf-8')
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    task = store.get_task(session.id, "012")
    blocked_events = [event for event in store.list_events(session.id) if event.event_type == "task.blocked"]
    expected_workspace = runtime_paths.session_paths(session.id).root / "workspace" / "012"

    assert result.session_status == "running"
    assert result.blocked_tasks == ("012",)
    assert task.status == "blocked"
    assert marker_path.read_text(encoding="utf-8").strip() == f"0|012|{expected_workspace}|blocked"
    assert "invalid status sidecar" in blocked_events[0].message


def test_session_max_timeout_aborts_active_workers_and_marks_session_aborted(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-06-session-timeout",
        name="Packet 06 session timeout",
        pack="session-timeout-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="020")

    marker_path = tmp_path / "session-timeout-isolation.log"
    pack_root = _write_pack(
        tmp_path,
        name="session-timeout-pack",
        task_idle=0,
        session_max=1,
        isolation_type="temp-directory",
        isolate_start="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        workspace = Path(sys.argv[3]) / "workspace" / sys.argv[2]
        workspace.mkdir(parents=True, exist_ok=True)
        print(workspace)
        """,
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        import signal
        import time

        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True:
            print("still running", flush=True)
            time.sleep(0.2)
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
        kill_grace_period=0.05,
    )

    task = store.get_task(session.id, "020")
    events = store.list_events(session.id)
    expected_workspace = runtime_paths.session_paths(session.id).root / "workspace" / "020"

    assert result.session_status == "aborted"
    assert store.get_session(session.id).status == "aborted"
    assert task.status == "blocked"
    assert marker_path.read_text(encoding="utf-8").strip() == f"0|020|{expected_workspace}|blocked"
    assert any(event.event_type == "session.aborted" for event in events)
    assert any(event.event_type == "task.blocked" and event.task_id == "020" for event in events)


def test_restart_honors_original_session_max_budget(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-session-max-restart",
        name="Packet 07 restart session max",
        pack="restart-session-max-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="021")
    store.update_session_status(
        session.id,
        status="running",
        started_at=_timestamp_offset(seconds=-2),
    )

    pack_root = _write_pack(
        tmp_path,
        name="restart-session-max-pack",
        session_max=1,
        execute_script_body="""
        #!/usr/bin/env python3
        from pathlib import Path
        import sys

        task_path = Path(sys.argv[1])
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        status_path.write_text("STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n", encoding='utf-8')
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    assert result.session_status == "aborted"
    assert store.get_session(session.id).status == "aborted"
    assert store.list_done_tasks(session.id) == ()


def test_all_done_session_marks_completed_and_records_ordered_events(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-06-complete",
        name="Packet 06 complete",
        pack="complete-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="030")
    _register_task(store, session_id=session.id, task_id="031")

    pack_root = _write_pack(
        tmp_path,
        name="complete-pack",
        max_workers=1,
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        status_path.write_text("STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n", encoding='utf-8')
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    events = store.list_events(session.id)

    assert result.session_status == "completed"
    assert [event.event_type for event in events] == [
        "session.running",
        "task.dispatched",
        "task.completed",
        "task.dispatched",
        "task.completed",
        "session.completed",
    ]


def test_execute_session_resumes_running_session_after_recovery_pass(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-running-resume",
        name="Packet 07 running resume",
        pack="resume-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="040")
    _register_task(store, session_id=session.id, task_id="041")
    stranded = store.project_task(
        session.id,
        "040",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.update_session_status(session.id, status="running")

    marker_path = tmp_path / "resume-isolation.log"
    trace_path = tmp_path / "resume-trace.log"
    pack_root = _write_pack(
        tmp_path,
        name="resume-pack",
        isolation_type="temp-directory",
        isolate_start="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        workspace = Path(sys.argv[3]) / "workspace" / sys.argv[2]
        workspace.mkdir(parents=True, exist_ok=True)
        print(workspace)
        """,
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix('.plan.md')
        trace_path = Path(os.environ['ORCH_TRACE'])
        with trace_path.open('a', encoding='utf-8') as handle:
            handle.write(f"dispatch:{task_id}\\n")
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        status_path.write_text("STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n", encoding='utf-8')
        """,
    )
    _status_path = stranded.plan_path.with_name("040.status")
    _status_path.write_text(
        "STATUS: done\nCOMMITS: abc1234\nTESTS_RAN: targeted\nTEST_RESULT: pass\n",
        encoding="utf-8",
    )
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="040",
        workspace_path=runtime_paths.session_paths(session.id).root / "workspace" / "040",
        pid=None,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"ORCH_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    assert result.session_status == "completed"
    assert store.get_task(session.id, "040").status == "done"
    assert store.get_task(session.id, "041").status == "done"
    assert trace_path.read_text(encoding="utf-8").splitlines() == ["dispatch:041"]
    assert marker_path.read_text(encoding="utf-8").splitlines()[0].endswith("|040|" + str(runtime_paths.session_paths(session.id).root / "workspace" / "040") + "|done")


def test_execute_session_recovers_paused_session_without_dispatching_new_work(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-paused-resume",
        name="Packet 07 paused recovery",
        pack="paused-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="050")
    _register_task(store, session_id=session.id, task_id="051")
    store.project_task(
        session.id,
        "050",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.update_session_status(session.id, status="paused")

    marker_path = tmp_path / "paused-isolation.log"
    trace_path = tmp_path / "paused-trace.log"
    pack_root = _write_pack(
        tmp_path,
        name="paused-pack",
        isolation_type="temp-directory",
        isolate_start="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        workspace = Path(sys.argv[3]) / "workspace" / sys.argv[2]
        workspace.mkdir(parents=True, exist_ok=True)
        print(workspace)
        """,
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        from pathlib import Path

        Path(os.environ['ORCH_TRACE']).write_text('unexpected dispatch\\n', encoding='utf-8')
        """,
    )
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="050",
        workspace_path=runtime_paths.session_paths(session.id).root / "workspace" / "050",
        pid=None,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"ORCH_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    assert result.started is True
    assert result.session_status == "paused"
    assert store.get_session(session.id).status == "paused"
    assert store.get_task(session.id, "050").status == "ready"
    assert store.get_task(session.id, "051").status == "ready"
    assert marker_path.read_text(encoding="utf-8").strip() == (
        f"0|050|{runtime_paths.session_paths(session.id).root / 'workspace' / '050'}|blocked"
    )
    assert not trace_path.exists()


def test_start_session_runs_planning_resolution_then_hands_off_to_execution_when_no_review_items_exist(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import start_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-08-start",
        name="Packet 08 start session",
        pack="start-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    (session_paths.intake / "051_feature.md").write_text("# Feature request\n", encoding="utf-8")

    pack_root = _write_pack(
        tmp_path,
        name="start-pack",
        planning_enabled=True,
        resolution_executor="passthrough",
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_plan_path = Path(sys.argv[1])
        task_id = task_plan_path.name.removesuffix(".plan.md")
        print(f"##PROGRESS## {task_id} | Phase: Execute | 1/1")
        status_path = task_plan_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    def planner_agent(*, model: str, prompt_path: Path, intake_path: Path, **_: object) -> str:
        assert model == "test-planner"
        assert prompt_path.name == "planner.md"
        assert intake_path.name == "051_feature.md"
        return dedent(
            """
            ---
            PLAN_ID: 051
            PRIORITY: normal
            ESTIMATED_SCOPE: src/feature.py
            DEPENDS_ON: none
            FULL_TEST_AFTER: no
            ---

            # Plan: Task 051

            Implement the feature.
            """
        ).lstrip()

    result = start_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        poll_interval=0.01,
    )

    assert result.started is True
    assert result.session_status == "completed"
    assert result.review_tasks == ()
    assert result.resolution_conflicts == ()
    assert (session_paths.done / "051.plan.md").is_file()
    assert store.list_done_tasks(session.id)[0].task_id == "051"


def test_task_failure_with_auto_fix_success_reclassifies_task_done_and_resumes_dispatch(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.models import FixerAttemptResult
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-09-task-auto-fix",
        name="Packet 09 task auto-fix",
        pack="task-auto-fix-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001")
    _register_task(store, session_id=session.id, task_id="002", depends_on=("001",))

    trace_path = tmp_path / "task-auto-fix-trace.log"
    verify_flag_path = runtime_paths.session_paths(session.id).root / "verify.ok"
    pack_root = _write_pack(
        tmp_path,
        name="task-auto-fix-pack",
        max_workers=1,
        verification_enabled=True,
        verification_interval=99,
        verification_command=(
            "python3 -c \"from pathlib import Path; import os, sys; "
            "flag = Path(os.environ['VERIFY_FLAG']); "
            "print('verification-pass' if flag.exists() else 'verification-fail'); "
            "raise SystemExit(0 if flag.exists() else 1)\""
        ),
        auto_fix_enabled=True,
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        trace_path = Path(os.environ["ORCH_TRACE"])
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"start:{task_id}\\n")
        status_path = task_path.with_name(task_id + ".status")
        if task_id == "001":
            status_path.write_text(
                "STATUS: blocked\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: fail\\nBLOCKED_REASON: worker failed\\n",
                encoding="utf-8",
            )
            raise SystemExit(1)
        status_path.write_text(
            "STATUS: done\\nCOMMITS: def5678\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"end:{task_id}\\n")
        """,
    )
    fixer_calls: list[tuple[str | None, int]] = []

    def fixer_executor(context):
        fixer_calls.append((context.task_id, context.attempt))
        verify_flag_path.write_text("ok\n", encoding="utf-8")
        return FixerAttemptResult(success=True, summary="Created verify flag.")

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={
            "ORCH_TRACE": str(trace_path),
            "PATH": os.environ["PATH"],
            "VERIFY_FLAG": str(verify_flag_path),
        },
        poll_interval=0.01,
        fixer_executor=fixer_executor,
    )

    assert result.session_status == "completed"
    assert store.get_task(session.id, "001").status == "done"
    assert store.get_task(session.id, "002").status == "done"
    assert fixer_calls == [("001", 1)]
    assert trace_path.read_text(encoding="utf-8").splitlines() == [
        "start:001",
        "start:002",
        "end:002",
    ]


def test_verification_failure_without_auto_fix_pauses_session_with_ready_frontier_preserved(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-09-verification-paused",
        name="Packet 09 verification paused",
        pack="verification-paused-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001")
    _register_task(store, session_id=session.id, task_id="002", depends_on=("001",))

    pack_root = _write_pack(
        tmp_path,
        name="verification-paused-pack",
        max_workers=1,
        verification_enabled=True,
        verification_interval=1,
        verification_command="python3 -c \"print('verification failed'); raise SystemExit(1)\"",
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    events = store.list_events(session.id)

    assert result.session_status == "paused"
    assert store.get_session(session.id).status == "paused"
    assert store.get_task(session.id, "001").status == "done"
    assert store.get_task(session.id, "002").status == "ready"
    assert any(event.event_type == "session.verification_failed" for event in events)
