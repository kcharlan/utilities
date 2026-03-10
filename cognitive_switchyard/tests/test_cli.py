from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

import pytest

from cognitive_switchyard import BOOTSTRAP_VENV, RUNTIME_HOME
from cognitive_switchyard.bootstrap import (
    BootstrapRequired,
    BootstrapSettings,
    bootstrap_if_needed,
)
from cognitive_switchyard.cli import main
from cognitive_switchyard.config import build_runtime_paths
from cognitive_switchyard.pack_loader import load_pack_manifest
from cognitive_switchyard.state import StateStore, initialize_state_store


def _build_store(tmp_path: Path) -> tuple[StateStore, object]:
    runtime_paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(runtime_paths)
    return store, runtime_paths


def _write_builtin_pack(root: Path, *, name: str, body: str = "factory\n") -> Path:
    pack_root = root / name
    scripts_dir = pack_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (pack_root / "prompts").mkdir(parents=True, exist_ok=True)
    (pack_root / "README.md").write_text(body, encoding="utf-8")
    execute_path = scripts_dir / "execute"
    execute_path.write_text(
        dedent(
            """
            #!/usr/bin/env python3
            import sys
            from pathlib import Path

            task_path = Path(sys.argv[1])
            task_id = task_path.name.removesuffix(".plan.md")
            print(f"##PROGRESS## {task_id} | Phase: Execute | 1/1")
            status_path = task_path.with_name(task_id + ".status")
            status_path.write_text(
                "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
                encoding="utf-8",
            )
            """
        ).lstrip(),
        encoding="utf-8",
    )
    execute_path.chmod(execute_path.stat().st_mode | 0o111)
    (pack_root / "pack.yaml").write_text(
        dedent(
            f"""
            name: {name}
            description: Built-in pack fixture.
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
    return pack_root


def _write_intake_plan(path: Path, task_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        dedent(
            f"""
            ---
            PLAN_ID: {task_id}
            PRIORITY: normal
            ESTIMATED_SCOPE: src/{task_id}.py
            DEPENDS_ON: none
            FULL_TEST_AFTER: no
            ---

            # Plan: Task {task_id}

            Execute the built-in pack fixture.
            """
        ).lstrip(),
        encoding="utf-8",
    )


def test_bootstrap_creates_runtime_home_default_config_and_builtin_packs_when_dependencies_are_available(
    tmp_path: Path,
) -> None:
    builtin_root = tmp_path / "builtin-source"
    _write_builtin_pack(builtin_root, name="claude-code")

    exit_code = main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "packs",
        ]
    )

    runtime_paths = build_runtime_paths(home=tmp_path)
    synced_pack = runtime_paths.packs / "claude-code"

    assert exit_code == 0
    assert runtime_paths.home.is_dir()
    assert runtime_paths.packs.is_dir()
    assert runtime_paths.sessions.is_dir()
    assert runtime_paths.config.read_text(encoding="utf-8") == (
        "retention_days: 30\n"
        "default_planners: 3\n"
        "default_workers: 3\n"
        "default_pack: claude-code\n"
    )
    assert synced_pack.is_dir()
    assert synced_pack.joinpath("pack.yaml").is_file()
    assert os.access(synced_pack / "scripts" / "execute", os.X_OK)
    assert load_pack_manifest(synced_pack).name == "claude-code"


def test_sync_builtin_packs_is_non_destructive_for_existing_runtime_customizations(
    tmp_path: Path,
) -> None:
    builtin_root = tmp_path / "builtin-source"
    _write_builtin_pack(builtin_root, name="claude-code", body="factory copy\n")
    runtime_paths = build_runtime_paths(home=tmp_path)
    customized_readme = runtime_paths.packs / "claude-code" / "README.md"
    customized_readme.parent.mkdir(parents=True, exist_ok=True)
    customized_readme.write_text("customized copy\n", encoding="utf-8")

    exit_code = main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "sync-packs",
        ]
    )

    assert exit_code == 0
    assert customized_readme.read_text(encoding="utf-8") == "customized copy\n"


def test_reset_pack_restores_factory_copy_for_one_builtin_pack(tmp_path: Path) -> None:
    builtin_root = tmp_path / "builtin-source"
    _write_builtin_pack(builtin_root, name="claude-code", body="factory copy\n")

    main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "packs",
        ]
    )
    runtime_paths = build_runtime_paths(home=tmp_path)
    readme_path = runtime_paths.packs / "claude-code" / "README.md"
    readme_path.write_text("customized copy\n", encoding="utf-8")

    exit_code = main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "reset-pack",
            "claude-code",
        ]
    )

    assert exit_code == 0
    assert readme_path.read_text(encoding="utf-8") == "factory copy\n"


def test_reset_all_packs_restores_all_builtin_packs_but_keeps_custom_only_runtime_packs(
    tmp_path: Path,
) -> None:
    builtin_root = tmp_path / "builtin-source"
    _write_builtin_pack(builtin_root, name="claude-code", body="claude factory\n")
    _write_builtin_pack(builtin_root, name="starter", body="starter factory\n")

    main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "packs",
        ]
    )
    runtime_paths = build_runtime_paths(home=tmp_path)
    (runtime_paths.packs / "claude-code" / "README.md").write_text(
        "custom claude\n",
        encoding="utf-8",
    )
    (runtime_paths.packs / "starter" / "README.md").write_text(
        "custom starter\n",
        encoding="utf-8",
    )
    custom_only = runtime_paths.packs / "my-custom-pack"
    custom_only.mkdir(parents=True, exist_ok=True)
    (custom_only / "README.md").write_text("keep me\n", encoding="utf-8")

    exit_code = main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "reset-all-packs",
        ]
    )

    assert exit_code == 0
    assert (runtime_paths.packs / "claude-code" / "README.md").read_text(
        encoding="utf-8"
    ) == "claude factory\n"
    assert (runtime_paths.packs / "starter" / "README.md").read_text(
        encoding="utf-8"
    ) == "starter factory\n"
    assert (custom_only / "README.md").read_text(encoding="utf-8") == "keep me\n"


def test_start_command_creates_or_resumes_session_and_invokes_existing_orchestrator_pipeline(
    tmp_path: Path,
) -> None:
    builtin_root = tmp_path / "builtin-source"
    _write_builtin_pack(builtin_root, name="claude-code")
    runtime_paths = build_runtime_paths(home=tmp_path)

    _write_intake_plan(
        runtime_paths.session_paths("session-10-cli").intake / "001.plan.md",
        "001",
    )

    exit_code = main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "start",
            "--pack",
            "claude-code",
            "--session",
            "session-10-cli",
        ]
    )

    store = initialize_state_store(runtime_paths)
    session = store.get_session("session-10-cli")
    done_task = store.get_task("session-10-cli", "001")

    assert exit_code == 0
    assert session.status == "completed"
    assert done_task.status == "done"
    assert runtime_paths.session_paths("session-10-cli").done.joinpath("001.plan.md").is_file()


def test_serve_command_is_available_in_help_output(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "serve" in captured.out


def test_bootstrap_reexecs_into_private_venv_when_dependency_probe_fails(tmp_path: Path) -> None:
    calls: list[tuple[str, object]] = []

    def dependency_probe(module_name: str) -> bool:
        calls.append(("probe", module_name))
        return False

    def create_venv(path: Path) -> None:
        calls.append(("create_venv", path))
        path.mkdir(parents=True, exist_ok=True)

    def install_requirements(python_executable: Path) -> None:
        calls.append(("install", python_executable))

    def reexec(python_executable: Path, argv: list[str]) -> None:
        calls.append(("reexec", python_executable, tuple(argv)))
        raise BootstrapRequired(python_executable=python_executable, argv=tuple(argv))

    settings = BootstrapSettings(
        repo_root=Path(__file__).resolve().parents[1],
        runtime_paths=build_runtime_paths(home=tmp_path),
        dependency_modules=("yaml",),
    )

    with pytest.raises(BootstrapRequired) as exc_info:
        bootstrap_if_needed(
            ["start", "--session", "demo"],
            settings=settings,
            dependency_probe=dependency_probe,
            create_venv=create_venv,
            install_requirements=install_requirements,
            reexec=reexec,
        )

    expected_python = settings.runtime_paths.bootstrap_venv / "bin" / "python"
    assert exc_info.value.python_executable == expected_python
    assert exc_info.value.argv == ("start", "--session", "demo")
    assert calls == [
        ("probe", "yaml"),
        ("create_venv", settings.runtime_paths.bootstrap_venv),
        ("install", expected_python),
        ("reexec", expected_python, ("start", "--session", "demo")),
    ]
    assert str(settings.runtime_paths.home).endswith(RUNTIME_HOME.replace("~/", ""))
    assert str(settings.runtime_paths.bootstrap_venv).endswith(
        BOOTSTRAP_VENV.replace("~/", "")
    )
