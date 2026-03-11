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


def _write_script(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(contents).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)


def _write_pack(
    tmp_path: Path,
    *,
    name: str,
    max_workers: int = 1,
    verification_interval: int = 4,
    verification_command: str,
    execute_script_body: str,
) -> Path:
    pack_root = tmp_path / name
    scripts_dir = pack_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    _write_script(scripts_dir / "execute.py", execute_script_body)
    (pack_root / "pack.yaml").write_text(
        "\n".join(
            [
                f"name: {name}",
                "description: Verification runtime test pack.",
                "version: 1.2.3",
                "",
                "phases:",
                "  execution:",
                "    enabled: true",
                "    executor: shell",
                "    command: scripts/execute.py",
                f"    max_workers: {max_workers}",
                "  verification:",
                "    enabled: true",
                "    command: >-",
                f"      {verification_command}",
                f"    interval: {verification_interval}",
                "",
                "timeouts:",
                "  task_idle: 5",
                "  task_max: 0",
                "  session_max: 60",
                "",
                "isolation:",
                "  type: none",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return pack_root


def _register_task(
    store: StateStore,
    *,
    session_id: str,
    task_id: str,
    depends_on: tuple[str, ...] = (),
    full_test_after: bool = False,
) -> None:
    store.register_task_plan(
        session_id=session_id,
        plan=TaskPlan(
            task_id=task_id,
            title=f"Task {task_id}",
            depends_on=depends_on,
            full_test_after=full_test_after,
        ),
        plan_text=dedent(
            f"""
            ---
            PLAN_ID: {task_id}
            DEPENDS_ON: {", ".join(depends_on) if depends_on else "none"}
            ANTI_AFFINITY: none
            EXEC_ORDER: 1
            FULL_TEST_AFTER: {"yes" if full_test_after else "no"}
            ---

            # Plan: Task {task_id}
            """
        ).lstrip(),
        created_at="2026-03-09T10:00:00Z",
    )


def test_interval_verification_waits_for_active_workers_and_writes_verify_log(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-09-verify-interval",
        name="Packet 09 interval verification",
        pack="interval-verification-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001")
    _register_task(store, session_id=session.id, task_id="002")

    trace_path = tmp_path / "verify-interval-trace.log"
    pack_root = _write_pack(
        tmp_path,
        name="interval-verification-pack",
        max_workers=2,
        verification_interval=1,
        verification_command=(
            "python3 -c \"from pathlib import Path; import os; "
            "trace = Path(os.environ['VERIFY_TRACE']); "
            "handle = trace.open('a', encoding='utf-8'); handle.write('verify\\n'); handle.close(); "
            "print('verification ok')\""
        ),
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        import time
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        trace_path = Path(os.environ["VERIFY_TRACE"])
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"start:{task_id}\\n")
        time.sleep(0.05 if task_id == "001" else 0.15)
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"end:{task_id}\\n")
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"VERIFY_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    lines = trace_path.read_text(encoding="utf-8").splitlines()

    assert result.session_status == "idle"
    assert set(lines[:2]) == {"start:001", "start:002"}
    assert lines.index("end:001") < lines.index("end:002")
    assert lines[-1:] == ["verify"]
    session_paths = runtime_paths.session_paths(session.id)
    assert not session_paths.summary.is_file()
    # verify_log still exists at idle (trimming deferred to explicit end_session)
    assert session_paths.verify_log.exists() is True
    assert session_paths.session_log.is_file()


def test_full_test_after_flag_forces_verification_before_more_dispatch(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-09-full-test-after",
        name="Packet 09 full-test-after",
        pack="full-test-after-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001", full_test_after=True)
    _register_task(store, session_id=session.id, task_id="002")
    _register_task(store, session_id=session.id, task_id="003")

    trace_path = tmp_path / "full-test-after-trace.log"
    pack_root = _write_pack(
        tmp_path,
        name="full-test-after-pack",
        max_workers=1,
        verification_interval=99,
        verification_command=(
            "python3 -c \"from pathlib import Path; import os; "
            "trace = Path(os.environ['VERIFY_TRACE']); "
            "handle = trace.open('a', encoding='utf-8'); handle.write('verify\\n'); handle.close(); "
            "print('verification ok')\""
        ),
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        trace_path = Path(os.environ["VERIFY_TRACE"])
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"start:{task_id}\\n")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"end:{task_id}\\n")
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"VERIFY_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    assert result.session_status == "idle"
    assert trace_path.read_text(encoding="utf-8").splitlines() == [
        "start:001",
        "end:001",
        "verify",
        "start:002",
        "end:002",
        "start:003",
        "end:003",
        "verify",
    ]
