from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

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
    execute_script_name: str = "execute.py",
    execute_script_body: str,
) -> Path:
    pack_root = tmp_path / name
    scripts_dir = pack_root / "scripts"
    scripts_dir.mkdir(parents=True)

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
            "  execution:",
            "    enabled: true",
            "    executor: shell",
            f"    command: scripts/{execute_script_name}",
            f"    max_workers: {max_workers}",
            "",
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
) -> None:
    plan = TaskPlan(
        task_id=task_id,
        title=f"Task {task_id}",
        depends_on=depends_on,
        anti_affinity=anti_affinity,
        exec_order=exec_order,
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
            FULL_TEST_AFTER: no
            ---

            # Plan: Task {task_id}
            """
        ).lstrip(),
        created_at="2026-03-09T10:00:00Z",
    )


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
