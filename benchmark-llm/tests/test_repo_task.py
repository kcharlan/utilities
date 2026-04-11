import io
import json
import os
import subprocess
from pathlib import Path

from benchmark_llm.cli import main


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Benchmark Tests",
            "-c",
            "user.email=bench-tests@example.com",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _git_output(args: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Benchmark Tests",
            "-c",
            "user.email=bench-tests@example.com",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_repo_task_run_preserves_workspace_and_records_command_provenance(
    tmp_path: Path,
) -> None:
    source_repo = tmp_path / "policy-engine-source"
    source_repo.mkdir()
    _git(["init", "-b", "main"], cwd=source_repo)
    _write_text(source_repo / "app.txt", "seed\n")
    _git(["add", "app.txt"], cwd=source_repo)
    _git(["commit", "-m", "seed"], cwd=source_repo)

    benchmark_dir = tmp_path / "policy-engine"
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                "id: policy-engine",
                "workspace:",
                "  kind: git_worktree",
                "  source_repo: ${BENCH_SOURCE_REPO}",
                "  keep_workspace: true",
                "  commit_outputs: true",
                "visibility:",
                "  expose:",
                "    - task-visible/**",
                "    - prompt.txt",
                "  hide:",
                "    - evaluator-only/**",
                "executor:",
                "  kind: cli",
                "  command: ./scripts/invoke_model.sh",
                "steps:",
                "  - name: prepare_visible",
                "    run: ./scripts/prepare.sh",
                "  - name: execute",
                "    use_executor: true",
                "  - name: judge_hidden",
                "    run: python ./scripts/judge.py",
                "scoring:",
                "  output: score.json",
            ]
        )
        + "\n",
    )
    _write_text(benchmark_dir / "prompt.txt", "Solve the repo task.\n")
    _write_text(benchmark_dir / "task-visible" / "visible-note.txt", "visible artifact\n")
    _write_text(benchmark_dir / "evaluator-only" / "expected.txt", "secret\n")
    _write_text(
        benchmark_dir / "scripts" / "prepare.sh",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "test -f \"$BENCH_BENCHMARK_DIR/prompt.txt\"",
                "test -f \"$BENCH_WORKSPACE/visible-note.txt\"",
                "test ! -e \"$BENCH_WORKSPACE/evaluator-only/expected.txt\"",
                "mkdir -p \"$BENCH_WORKSPACE/output\"",
                "printf 'prepared\\n' > \"$BENCH_WORKSPACE/output/prepare.txt\"",
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "invoke_model.sh",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "test -n \"$MODEL_ID\"",
                "test -n \"$WORKSPACE_ROOT\"",
                "test -n \"$TASK_PROMPT_PATH\"",
                "[[ -z ${BENCH_MODEL+x} ]]",
                "[[ -z ${BENCH_BENCHMARK_DIR+x} ]]",
                "[[ -z ${BENCH_WORKSPACE+x} ]]",
                "[[ -z ${PYTEST_CURRENT_TEST+x} ]]",
                "python - <<'PY'",
                "import json, os",
                "from pathlib import Path",
                "Path(os.environ['TASK_METRICS_PATH']).write_text(json.dumps({",
                "    'cost_usd': 0.33,",
                "    'input_tokens': 120,",
                "    'output_tokens': 45,",
                "    'provider_latency_ms': 987,",
                "}), encoding='utf-8')",
                "PY",
                "printf 'model=%s\\n' \"$MODEL_ID\" > \"$WORKSPACE_ROOT/output/result.txt\"",
                "cat \"$TASK_PROMPT_PATH\" >> \"$WORKSPACE_ROOT/output/result.txt\"",
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "judge.py",
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "",
                "workspace = Path(os.environ['BENCH_WORKSPACE'])",
                "run_dir = Path(os.environ['BENCH_RUN_DIR'])",
                "hidden_dir = Path(os.environ['BENCH_HIDDEN_DIR'])",
                "",
                "assert (workspace / 'visible-note.txt').read_text(encoding='utf-8').strip() == 'visible artifact'",
                "assert not (workspace / 'evaluator-only' / 'expected.txt').exists()",
                "assert (hidden_dir / 'expected.txt').read_text(encoding='utf-8').strip() == 'secret'",
                "command_rows = [json.loads(line) for line in (run_dir / 'commands.jsonl').read_text(encoding='utf-8').splitlines()]",
                "assert [row['phase'] for row in command_rows] == ['prepare_visible', 'execute']",
                "result_text = (workspace / 'output' / 'result.txt').read_text(encoding='utf-8')",
                "assert 'demo-model' in result_text",
                "score = {",
                "    'summary': {'passed': 3, 'total': 3, 'score_percent': 100.0},",
                "    'checks': [",
                "        {'name': 'visible copy', 'passed': True},",
                "        {'name': 'hidden isolation', 'passed': True},",
                "        {'name': 'executor output', 'passed': True},",
                "    ],",
                "}",
                "with (run_dir / 'score.json').open('w', encoding='utf-8') as handle:",
                "    json.dump(score, handle, indent=2)",
            ]
        )
        + "\n",
    )
    os.chmod(benchmark_dir / "scripts" / "prepare.sh", 0o755)
    os.chmod(benchmark_dir / "scripts" / "invoke_model.sh", 0o755)

    runtime_home = tmp_path / "runtime-home"
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["run", str(benchmark_dir), "-m", "demo-model"],
        environ={
            "BENCH_RUNTIME_HOME": str(runtime_home),
            "BENCH_SOURCE_REPO": str(source_repo),
        },
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0, stderr.getvalue()
    run_dirs = sorted((runtime_home / "runs").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["benchmark"]["mode"] == "repo_task"
    assert manifest["timing"]["elapsed_ms"] >= 0
    assert manifest["metrics"]["cost_usd"] == 0.33
    assert manifest["metrics"]["input_tokens"] == 120
    assert manifest["metrics"]["output_tokens"] == 45
    assert manifest["metrics"]["total_tokens"] == 165
    workspace_path = Path(manifest["workspace"]["path"])
    assert workspace_path.exists()
    assert (workspace_path / "visible-note.txt").exists()
    assert not (workspace_path / "evaluator-only" / "expected.txt").exists()
    assert manifest["workspace"]["commit_after_run"]

    command_rows = [
        json.loads(line)
        for line in (run_dir / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["phase"] for row in command_rows] == [
        "prepare_visible",
        "execute",
        "judge_hidden",
    ]
    assert command_rows[1]["command"] == "./scripts/invoke_model.sh"
    assert all(row["exit_code"] == 0 for row in command_rows)
    assert all(row["elapsed_ms"] >= 0 for row in command_rows)
    assert command_rows[1]["metrics"]["cost_usd"] == 0.33

    score = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
    assert score["summary"]["score_percent"] == 100.0


def test_repo_task_string_steps_still_honor_executor_command(tmp_path: Path) -> None:
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    _git(["init", "-b", "main"], cwd=source_repo)
    _write_text(source_repo / "seed.txt", "seed\n")
    _git(["add", "seed.txt"], cwd=source_repo)
    _git(["commit", "-m", "seed"], cwd=source_repo)

    benchmark_dir = tmp_path / "bench"
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                "workspace:",
                "  kind: git_worktree",
                f"  source_repo: {source_repo}",
                "executor:",
                "  kind: cli",
                "  command: ./scripts/invoke_model.sh",
                "steps:",
                "  - ./scripts/prepare.sh",
                "  - ./scripts/invoke_model.sh",
                "  - python ./scripts/judge.py",
                "scoring:",
                "  output: score.json",
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "prepare.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nmkdir -p \"$BENCH_WORKSPACE/output\"\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "invoke_model.sh",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "test -n \"$WORKSPACE_ROOT\"",
                "[[ -z ${BENCH_WORKSPACE+x} ]]",
                "[[ -z ${PYTEST_CURRENT_TEST+x} ]]",
                "printf 'from executor\\n' > \"$WORKSPACE_ROOT/output/result.txt\"",
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "judge.py",
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "run_dir = Path(os.environ['BENCH_RUN_DIR'])",
                "workspace = Path(os.environ['BENCH_WORKSPACE'])",
                "assert (workspace / 'output' / 'result.txt').read_text(encoding='utf-8').strip() == 'from executor'",
                "with (run_dir / 'score.json').open('w', encoding='utf-8') as handle:",
                "    json.dump({'summary': {'passed': 1, 'total': 1, 'score_percent': 100.0}, 'checks': [{'name': 'ok', 'passed': True}]}, handle)",
            ]
        )
        + "\n",
    )
    os.chmod(benchmark_dir / "scripts" / "prepare.sh", 0o755)
    os.chmod(benchmark_dir / "scripts" / "invoke_model.sh", 0o755)

    runtime_home = tmp_path / "runtime-home"
    exit_code = main(
        ["run", str(benchmark_dir), "-m", "demo-model"],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    run_dir = next((runtime_home / "runs").iterdir())
    command_rows = [
        json.loads(line)
        for line in (run_dir / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["phase"] for row in command_rows] == ["step_1", "execute", "step_3"]


def test_repo_task_failure_cleans_up_run_dir_and_worktree(tmp_path: Path) -> None:
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    _git(["init", "-b", "main"], cwd=source_repo)
    _write_text(source_repo / "seed.txt", "seed\n")
    _git(["add", "seed.txt"], cwd=source_repo)
    _git(["commit", "-m", "seed"], cwd=source_repo)

    benchmark_dir = tmp_path / "bench"
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                "id: cleanup-check",
                "workspace:",
                "  kind: git_worktree",
                f"  source_repo: {source_repo}",
                "  keep_workspace: true",
                "executor:",
                "  kind: cli",
                "  command: ./scripts/invoke_model.sh",
                "steps:",
                "  - name: execute",
                "    use_executor: true",
                "  - name: fail",
                "    run: ./scripts/fail.sh",
                "scoring:",
                "  output: score.json",
            ]
        )
        + "\n",
    )
    _write_text(benchmark_dir / "prompt.txt", "Do work.\n")
    _write_text(
        benchmark_dir / "scripts" / "invoke_model.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf 'ok\\n' > \"$WORKSPACE_ROOT/result.txt\"\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "fail.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\necho 'expected failure' >&2\nexit 2\n",
    )
    os.chmod(benchmark_dir / "scripts" / "invoke_model.sh", 0o755)
    os.chmod(benchmark_dir / "scripts" / "fail.sh", 0o755)

    runtime_home = tmp_path / "runtime-home"

    try:
        main(
            ["run", str(benchmark_dir), "-m", "demo-model"],
            environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    except RuntimeError as exc:
        assert "expected failure" in str(exc)
    else:
        raise AssertionError("Expected repo-task failure to raise RuntimeError")

    runs_dir = runtime_home / "runs"
    assert list(runs_dir.iterdir()) == []

    worktree_root = runtime_home / "worktrees" / "cleanup-check" / "demo-model"
    assert not any(worktree_root.iterdir()) if worktree_root.exists() else True

    assert "bench/cleanup-check/demo-model" not in _git_output(["branch", "--list"], cwd=source_repo)
    worktree_list = _git_output(["worktree", "list", "--porcelain"], cwd=source_repo)
    assert str(runtime_home / "worktrees") not in worktree_list
