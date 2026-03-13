from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

from cognitive_switchyard import BOOTSTRAP_VENV, PACKAGE_NAME, RUNTIME_HOME


LEGACY_RUNTIME_MARKERS = ("~/.switchyard", "~/.switchyard_venv")


def run_command(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=repo_root,
        text=True,
        capture_output=True,
    )


def _write_non_executable_builtin_pack(root: Path) -> None:
    scripts_dir = root / "claude-code" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (root / "claude-code" / "pack.yaml").write_text(
        dedent(
            """
            name: claude-code
            description: Failing built-in pack fixture.
            version: 1.2.3

            phases:
              resolution:
                enabled: true
                executor: passthrough
              execution:
                enabled: true
                executor: shell
                command: scripts/execute
                max_workers: 1

            timeouts:
              task_idle: 5
              task_max: 0
              session_max: 60

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )
    execute_path = scripts_dir / "execute"
    execute_path.write_text("#!/usr/bin/env python3\nprint('fail preflight')\n", encoding="utf-8")
    execute_path.chmod(0o644)


def _write_intake_plan(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        dedent(
            """
            ---
            PLAN_ID: 001
            PRIORITY: normal
            ESTIMATED_SCOPE: src/001.py
            DEPENDS_ON: none
            FULL_TEST_AFTER: no
            ---

            # Plan: Task 001
            """
        ).lstrip(),
        encoding="utf-8",
    )


def test_import_cognitive_switchyard() -> None:
    module = importlib.import_module("cognitive_switchyard")

    assert module.__name__ == "cognitive_switchyard"
    assert PACKAGE_NAME == "cognitive_switchyard"
    assert RUNTIME_HOME == "~/.cognitive_switchyard"
    assert BOOTSTRAP_VENV == "~/.cognitive_switchyard_venv"


def test_python_module_help_succeeds(repo_root: Path) -> None:
    result = run_command(repo_root, sys.executable, "-m", "cognitive_switchyard", "--help")

    assert result.returncode == 0
    assert "cognitive_switchyard" in result.stdout
    assert "runtime home" in result.stdout
    assert "~/.cognitive_switchyard" in result.stdout
    assert "~/.cognitive_switchyard_venv" in result.stdout
    for legacy_marker in LEGACY_RUNTIME_MARKERS:
        assert legacy_marker not in result.stdout
    assert result.stderr == ""


def test_switchyard_help_succeeds(repo_root: Path) -> None:
    launcher = repo_root / "switchyard"
    result = run_command(repo_root, str(launcher), "--help")

    assert result.returncode == 0
    assert "cognitive_switchyard" in result.stdout
    assert "~/.cognitive_switchyard" in result.stdout
    assert "~/.cognitive_switchyard_venv" in result.stdout
    for legacy_marker in LEGACY_RUNTIME_MARKERS:
        assert legacy_marker not in result.stdout
    assert result.stderr == ""


def test_module_main_preserves_none_argv_for_bootstrap(monkeypatch) -> None:
    from cognitive_switchyard import __main__ as module_main

    observed: dict[str, object] = {}

    def fake_cli_main(argv=None):
        observed["argv"] = argv
        return 0

    monkeypatch.setattr("cognitive_switchyard.cli.main", fake_cli_main)

    assert module_main.main() == 0
    assert observed["argv"] is None


def test_paths_subcommand_reports_canonical_contracts(repo_root: Path) -> None:
    launcher = repo_root / "switchyard"
    result = run_command(repo_root, str(launcher), "paths")

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "package: cognitive_switchyard",
        "runtime home: ~/.cognitive_switchyard",
        "bootstrap venv: ~/.cognitive_switchyard_venv",
    ]
    assert result.stderr == ""


def test_help_and_paths_continue_to_report_canonical_cognitive_switchyard_contracts(
    repo_root: Path,
) -> None:
    launcher = repo_root / "switchyard"
    help_result = run_command(repo_root, str(launcher), "--help")
    paths_result = run_command(repo_root, str(launcher), "paths")

    assert help_result.returncode == 0
    assert "cognitive_switchyard" in help_result.stdout
    assert "~/.cognitive_switchyard" in help_result.stdout
    assert "~/.cognitive_switchyard_venv" in help_result.stdout
    assert paths_result.returncode == 0
    assert "runtime home: ~/.cognitive_switchyard" in paths_result.stdout
    assert "bootstrap venv: ~/.cognitive_switchyard_venv" in paths_result.stdout


def test_switchyard_propagates_nonzero_exit_codes_from_start_failures(
    repo_root: Path, tmp_path: Path
) -> None:
    launcher = repo_root / "switchyard"
    builtin_root = tmp_path / "builtin"
    runtime_root = tmp_path / "runtime"
    _write_non_executable_builtin_pack(builtin_root)
    _write_intake_plan(
        runtime_root / ".cognitive_switchyard" / "sessions" / "demo" / "intake" / "001.plan.md"
    )

    result = run_command(
        repo_root,
        str(launcher),
        "--runtime-root",
        str(runtime_root),
        "--builtin-packs-root",
        str(builtin_root),
        "start",
        "--pack",
        "claude-code",
        "--session",
        "demo",
    )

    assert result.returncode == 1
