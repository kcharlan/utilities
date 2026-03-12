from __future__ import annotations

import time
from pathlib import Path
from textwrap import dedent

import pytest

from cognitive_switchyard.pack_loader import load_pack_manifest, resolve_pack_hook_path
from cognitive_switchyard.worker_manager import (
    WorkerManager,
    WorkerStatusSidecarError,
)


def _write_pack(
    tmp_path: Path,
    *,
    name: str,
    execute_script: Path,
    progress_format: str = "##PROGRESS##",
    sidecar_format: str = "key-value",
) -> Path:
    pack_root = tmp_path / name
    scripts_dir = pack_root / "scripts"
    scripts_dir.mkdir(parents=True)
    execute_target = scripts_dir / execute_script.name
    execute_target.write_text(execute_script.read_text(encoding="utf-8"), encoding="utf-8")
    execute_target.chmod(execute_script.stat().st_mode | 0o111)
    (pack_root / "pack.yaml").write_text(
        dedent(
            f"""
            name: {name}
            description: Worker manager test pack.
            version: 1.2.3

            timeouts:
              task_idle: 5
              task_max: 0

            status:
              progress_format: {progress_format!r}
              sidecar_format: {sidecar_format}

            phases:
              execution:
                enabled: true
                executor: shell
                command: scripts/{execute_script.name}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return pack_root


def _write_task_plan(task_dir: Path, task_id: str = "039") -> Path:
    task_dir.mkdir(parents=True, exist_ok=True)
    task_path = task_dir / f"{task_id}_example.plan.md"
    task_path.write_text(
        dedent(
            f"""
            ---
            PLAN_ID: {task_id}
            DEPENDS_ON: none
            EXEC_ORDER: 1
            FULL_TEST_AFTER: no
            ---

            # Plan: Worker fixture task
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return task_path


def _status_path_for(task_path: Path) -> Path:
    return task_path.with_name(task_path.name.removesuffix(".plan.md") + ".status")


def _poll_until_finished(manager: WorkerManager, slot_number: int, *, deadline_seconds: float = 5.0):
    deadline = time.monotonic() + deadline_seconds
    snapshot = manager.poll(slot_number)
    while not snapshot.is_finished:
        if time.monotonic() >= deadline:
            raise AssertionError(f"worker slot {slot_number} did not finish before deadline")
        time.sleep(0.02)
        snapshot = manager.poll(slot_number)
    return snapshot


def test_dispatch_shell_worker_writes_worker_log_and_collects_status_sidecar(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    execute_script = repo_root / "tests" / "fixtures" / "workers" / "normal_worker.py"
    pack_root = _write_pack(tmp_path, name="normal-pack", execute_script=execute_script)
    manifest = load_pack_manifest(pack_root)
    task_path = _write_task_plan(tmp_path / "session" / "workers" / "0")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    log_path = tmp_path / "logs" / "workers" / "0.log"

    manager = WorkerManager()
    manager.dispatch(
        slot_number=0,
        pack_manifest=manifest,
        task_plan_path=task_path,
        workspace_path=workspace,
        log_path=log_path,
    )

    final_snapshot = _poll_until_finished(manager, 0)
    result = manager.collect(0)

    assert final_snapshot.exit_code == 0
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.status.status == "done"
    assert result.status.commits == ("abc1234",)
    assert result.status.tests_ran == "targeted"
    assert result.status.test_result == "pass"
    assert result.status_path == _status_path_for(task_path)
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "worker starting",
        "##PROGRESS## 039_example | Phase: implementing | 3/5",
        "worker completed",
    ]


def test_worker_progress_markers_update_latest_progress_without_hiding_raw_output(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    execute_script = repo_root / "tests" / "fixtures" / "workers" / "progress_worker.py"
    pack_root = _write_pack(tmp_path, name="progress-pack", execute_script=execute_script)
    manifest = load_pack_manifest(pack_root)
    task_path = _write_task_plan(tmp_path / "session" / "workers" / "1")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    log_path = tmp_path / "logs" / "workers" / "1.log"

    manager = WorkerManager()
    manager.dispatch(
        slot_number=1,
        pack_manifest=manifest,
        task_plan_path=task_path,
        workspace_path=workspace,
        log_path=log_path,
    )

    seen_lines: list[str] = []
    snapshot = manager.poll(1)
    while not snapshot.is_finished:
        seen_lines.extend(snapshot.new_output_lines)
        time.sleep(0.02)
        snapshot = manager.poll(1)
    seen_lines.extend(snapshot.new_output_lines)
    result = manager.collect(1)

    assert result.progress.phase_name == "implementing"
    assert result.progress.phase_index == 3
    assert result.progress.phase_total == 5
    assert result.progress.detail_message == "Processing chunk 3/9"
    assert seen_lines == [
        "raw before markers",
        "##PROGRESS## 039_example | Phase: implementing | 3/5",
        "##PROGRESS## 039_example | Detail: Processing chunk 3/9",
        "raw after markers",
    ]
    assert log_path.read_text(encoding="utf-8").splitlines() == seen_lines


def test_worker_progress_markers_ignore_other_task_ids(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    execute_script = repo_root / "tests" / "fixtures" / "workers" / "mismatched_progress_worker.py"
    pack_root = _write_pack(tmp_path, name="mismatched-progress-pack", execute_script=execute_script)
    manifest = load_pack_manifest(pack_root)
    task_path = _write_task_plan(tmp_path / "session" / "workers" / "6")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    log_path = tmp_path / "logs" / "workers" / "6.log"

    manager = WorkerManager()
    manager.dispatch(
        slot_number=6,
        pack_manifest=manifest,
        task_plan_path=task_path,
        workspace_path=workspace,
        log_path=log_path,
    )

    _poll_until_finished(manager, 6)
    result = manager.collect(6)

    assert result.progress.task_id == "039_example"
    assert result.progress.phase_name == "implementing"
    assert result.progress.phase_index == 3
    assert result.progress.phase_total == 5
    assert result.progress.detail_message == "canonical detail"
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "##PROGRESS## wrong-task | Phase: reading | 1/5",
        "##PROGRESS## 039_example | Phase: implementing | 3/5",
        "##PROGRESS## wrong-task | Detail: should be ignored",
        "##PROGRESS## 039_example | Detail: canonical detail",
    ]


def test_worker_manager_honors_custom_progress_and_json_sidecar_formats(
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "custom-pack"
    scripts_dir = pack_root / "scripts"
    scripts_dir.mkdir(parents=True)
    execute_target = scripts_dir / "execute.py"
    execute_target.write_text(
        dedent(
            """
            #!/usr/bin/env python3
            import json
            import sys
            from pathlib import Path

            task_path = Path(sys.argv[1])
            task_id = task_path.name.removesuffix('.plan.md')
            print(f"@@PROG@@ {task_id} | Phase: validating | 2/3", flush=True)
            status_path = task_path.with_name(task_id + '.status')
            status_path.write_text(
                json.dumps(
                    {
                        "status": "done",
                        "commits": "abc1234",
                        "tests_ran": "targeted",
                        "test_result": "pass",
                    }
                ),
                encoding="utf-8",
            )
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    execute_target.chmod(execute_target.stat().st_mode | 0o111)
    (pack_root / "pack.yaml").write_text(
        dedent(
            """
            name: custom-pack
            description: Worker manager test pack.
            version: 1.2.3

            status:
              progress_format: '@@PROG@@'
              sidecar_format: json

            timeouts:
              task_idle: 5
              task_max: 0

            phases:
              execution:
                enabled: true
                executor: shell
                command: scripts/execute.py
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    manifest = load_pack_manifest(pack_root)
    task_path = _write_task_plan(tmp_path / "session" / "workers" / "7")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    log_path = tmp_path / "logs" / "workers" / "7.log"

    manager = WorkerManager()
    manager.dispatch(
        slot_number=7,
        pack_manifest=manifest,
        task_plan_path=task_path,
        workspace_path=workspace,
        log_path=log_path,
    )

    _poll_until_finished(manager, 7)
    result = manager.collect(7)

    assert result.progress.phase_name == "validating"
    assert result.progress.phase_index == 2
    assert result.progress.phase_total == 3
    assert result.status is not None
    assert result.status.status == "done"
    assert result.status.tests_ran == "targeted"


def test_idle_timeout_terminates_worker_and_reports_timeout_result(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    execute_script = repo_root / "tests" / "fixtures" / "workers" / "silent_worker.py"
    pack_root = _write_pack(tmp_path, name="idle-pack", execute_script=execute_script)
    manifest = load_pack_manifest(pack_root)
    task_path = _write_task_plan(tmp_path / "session" / "workers" / "2")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    log_path = tmp_path / "logs" / "workers" / "2.log"

    manager = WorkerManager(default_task_idle=0.2, kill_grace_period=0.1)
    manager.dispatch(
        slot_number=2,
        pack_manifest=manifest,
        task_plan_path=task_path,
        workspace_path=workspace,
        log_path=log_path,
    )

    final_snapshot = _poll_until_finished(manager, 2, deadline_seconds=3.0)
    result = manager.collect(2)

    assert final_snapshot.timed_out is True
    assert result.timed_out is True
    assert result.timeout_kind == "idle"
    assert result.status is None
    assert "no output" in result.failure_reason
    assert log_path.read_text(encoding="utf-8") == ""


def test_task_max_timeout_terminates_long_running_worker_after_grace_period(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    execute_script = repo_root / "tests" / "fixtures" / "workers" / "ignore_term_worker.py"
    pack_root = _write_pack(tmp_path, name="hard-timeout-pack", execute_script=execute_script)
    manifest = load_pack_manifest(pack_root)
    task_path = _write_task_plan(tmp_path / "session" / "workers" / "3")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    log_path = tmp_path / "logs" / "workers" / "3.log"

    # Leave enough headroom for Python startup so the fixture reliably installs
    # its SIGTERM handler before the manager enforces the task-max timeout.
    manager = WorkerManager(default_task_idle=0, default_task_max=0.5, kill_grace_period=0.1)
    manager.dispatch(
        slot_number=3,
        pack_manifest=manifest,
        task_plan_path=task_path,
        workspace_path=workspace,
        log_path=log_path,
    )

    final_snapshot = _poll_until_finished(manager, 3, deadline_seconds=4.0)
    result = manager.collect(3)

    assert final_snapshot.timed_out is True
    assert result.timed_out is True
    assert result.timeout_kind == "task_max"
    assert result.kill_escalated is True
    assert "exceeded max task time" in result.failure_reason
    assert "ignoring SIGTERM" in log_path.read_text(encoding="utf-8")


def test_collect_rejects_missing_or_malformed_status_sidecar_with_typed_error(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = WorkerManager()

    missing_pack_root = _write_pack(
        tmp_path,
        name="missing-sidecar-pack",
        execute_script=repo_root / "tests" / "fixtures" / "workers" / "missing_sidecar_worker.py",
    )
    missing_manifest = load_pack_manifest(missing_pack_root)
    missing_task_path = _write_task_plan(tmp_path / "session" / "workers" / "4")
    manager.dispatch(
        slot_number=4,
        pack_manifest=missing_manifest,
        task_plan_path=missing_task_path,
        workspace_path=workspace,
        log_path=tmp_path / "logs" / "workers" / "4.log",
    )
    _poll_until_finished(manager, 4)
    with pytest.raises(WorkerStatusSidecarError, match="missing status sidecar"):
        manager.collect(4)

    malformed_pack_root = _write_pack(
        tmp_path,
        name="malformed-sidecar-pack",
        execute_script=repo_root / "tests" / "fixtures" / "workers" / "malformed_sidecar_worker.py",
    )
    malformed_manifest = load_pack_manifest(malformed_pack_root)
    malformed_task_path = _write_task_plan(tmp_path / "session" / "workers" / "5")
    manager.dispatch(
        slot_number=5,
        pack_manifest=malformed_manifest,
        task_plan_path=malformed_task_path,
        workspace_path=workspace,
        log_path=tmp_path / "logs" / "workers" / "5.log",
    )
    _poll_until_finished(manager, 5)
    with pytest.raises(WorkerStatusSidecarError, match="invalid status sidecar"):
        manager.collect(5)


def test_packet_04_execution_hook_resolution_regression_still_passes(repo_root: Path) -> None:
    pack_root = repo_root / "tests" / "fixtures" / "packs" / "valid_shell_pack"
    manifest = load_pack_manifest(pack_root)

    execute_path = resolve_pack_hook_path(manifest, "execute")

    assert execute_path == pack_root / "scripts" / "execute"


# --- Regression tests for code-audit fixes ---


def test_f3_collect_raises_worker_status_sidecar_error_when_file_deleted_after_exists_check(
    tmp_path: Path, repo_root: Path
) -> None:
    """F-3 regression: collect() must raise WorkerStatusSidecarError when status file is
    deleted between the is_file() check and read_text() (TOCTOU race)."""
    import unittest.mock
    from cognitive_switchyard.worker_manager import WorkerManager, WorkerStatusSidecarError

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    # Script that exits immediately with a status sidecar
    script = scripts_dir / "execute"
    script.write_text(
        "#!/bin/sh\n"
        'task_id=$(basename "$1" .plan.md)\n'
        'printf "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: none\\nTEST_RESULT: skip\\n" '
        '> "$(dirname "$1")/${task_id}.status"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | 0o111)

    pack_root = tmp_path / "testpack"
    (pack_root / "scripts").mkdir(parents=True)
    (pack_root / "scripts" / "execute").write_bytes(script.read_bytes())
    (pack_root / "scripts" / "execute").chmod(script.stat().st_mode | 0o111)
    (pack_root / "pack.yaml").write_text(
        "name: testpack\ndescription: T\nversion: 1.0.0\n"
        "timeouts:\n  task_idle: 0\n  task_max: 0\n"
        "status:\n  progress_format: '##PROGRESS##'\n  sidecar_format: key-value\n"
        "phases:\n  execution:\n    enabled: true\n    executor: shell\n    command: scripts/execute\n",
        encoding="utf-8",
    )
    from cognitive_switchyard.pack_loader import load_pack_manifest
    manifest = load_pack_manifest(pack_root)

    plan_path = tmp_path / "workers" / "0" / "task1.plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\nPLAN_ID: task1\n---\n# task\n", encoding="utf-8")

    manager = WorkerManager()
    manager.dispatch(
        slot_number=0,
        pack_manifest=manifest,
        task_plan_path=plan_path,
        workspace_path=plan_path.parent,
        log_path=tmp_path / "worker.log",
    )
    # Wait for worker to finish
    import time
    for _ in range(50):
        snapshot = manager.poll(0)
        if snapshot.is_finished:
            break
        time.sleep(0.1)

    # Monkeypatch read_text on the status file to raise FileNotFoundError
    from pathlib import Path as _Path
    original_read_text = _Path.read_text

    def _raise_fnf(self: _Path, *args, **kwargs) -> str:
        if self.suffix == ".status":
            raise FileNotFoundError(f"Simulated deletion: {self}")
        return original_read_text(self, *args, **kwargs)

    import unittest.mock
    with unittest.mock.patch.object(_Path, "read_text", _raise_fnf):
        with pytest.raises(WorkerStatusSidecarError):
            manager.collect(0)


def test_f8_active_slot_numbers_excludes_collected_worker(
    tmp_path: Path,
) -> None:
    """F-8 regression: active_slot_numbers must not include workers with collected=True."""
    from cognitive_switchyard.worker_manager import WorkerManager

    scripts_dir = tmp_path / "pack" / "scripts"
    scripts_dir.mkdir(parents=True)
    script = scripts_dir / "execute"
    script.write_text(
        "#!/bin/sh\n"
        'task_id=$(basename "$1" .plan.md)\n'
        'printf "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: none\\nTEST_RESULT: skip\\n" '
        '> "$(dirname "$1")/${task_id}.status"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | 0o111)
    (tmp_path / "pack" / "pack.yaml").write_text(
        "name: p\ndescription: T\nversion: 1.0.0\n"
        "timeouts:\n  task_idle: 0\n  task_max: 0\n"
        "status:\n  progress_format: '##PROGRESS##'\n  sidecar_format: key-value\n"
        "phases:\n  execution:\n    enabled: true\n    executor: shell\n    command: scripts/execute\n",
        encoding="utf-8",
    )
    from cognitive_switchyard.pack_loader import load_pack_manifest
    manifest = load_pack_manifest(tmp_path / "pack")

    plan_path = tmp_path / "workers" / "0" / "task1.plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\nPLAN_ID: task1\n---\n# task\n", encoding="utf-8")

    manager = WorkerManager()
    manager.dispatch(
        slot_number=0,
        pack_manifest=manifest,
        task_plan_path=plan_path,
        workspace_path=plan_path.parent,
        log_path=tmp_path / "worker.log",
    )

    import time
    for _ in range(50):
        snapshot = manager.poll(0)
        if snapshot.is_finished:
            break
        time.sleep(0.1)

    assert 0 in manager.active_slot_numbers()
    manager.collect(0)
    assert 0 not in manager.active_slot_numbers()
