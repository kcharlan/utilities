from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .execution import run_command
from .metrics import aggregate_metrics
from .reporting import write_report
from .storage import record_run, write_json, write_jsonl
from .util import (
    build_model_command_env,
    elapsed_milliseconds,
    expand_env_string,
    iso_timestamp,
    merge_environ,
    run_timestamp_slug,
    safe_slug,
    unique_child_name,
    utc_now,
)


@dataclass
class RepoTaskStep:
    phase: str
    command: str
    model_visible: bool = False


def _git(source_repo: Path, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=benchmark-llm",
            "-c",
            "user.email=benchmark-llm@example.com",
            *args,
        ],
        cwd=cwd or source_repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _git_try(source_repo: Path, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=benchmark-llm",
            "-c",
            "user.email=benchmark-llm@example.com",
            *args,
        ],
        cwd=cwd or source_repo,
        check=False,
        capture_output=True,
        text=True,
    )


def _pattern_strip_root(pattern: str) -> Path:
    parts = Path(pattern).parts
    prefix_parts: list[str] = []
    wildcard_found = False
    for part in parts:
        if any(marker in part for marker in ("*", "?", "[")):
            wildcard_found = True
            break
        prefix_parts.append(part)
    if not wildcard_found and prefix_parts:
        prefix_parts = prefix_parts[:-1]
    return Path(*prefix_parts) if prefix_parts else Path(".")


def _copy_pattern_matches(
    benchmark_dir: Path,
    destination_root: Path,
    patterns: list[str],
    require_match: bool = False,
) -> list[Path]:
    copied: list[Path] = []
    for pattern in patterns:
        strip_root = _pattern_strip_root(pattern)
        source_base = benchmark_dir if strip_root == Path(".") else benchmark_dir / strip_root
        for match in benchmark_dir.glob(pattern):
            if not match.is_file():
                continue
            relative = match.relative_to(source_base)
            destination = destination_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(match, destination)
            copied.append(destination)
    if require_match and not copied:
        raise FileNotFoundError(f"No files matched configured patterns: {patterns}")
    return copied


def _resolve_repo_steps(config: dict[str, Any]) -> list[RepoTaskStep]:
    raw_steps = config.get("steps", [])
    executor_config = config.get("executor", {}) or {}
    executor_command = executor_config.get("command")
    resolved: list[RepoTaskStep] = []
    executor_used = False

    for index, raw_step in enumerate(raw_steps, start=1):
        if isinstance(raw_step, str):
            phase = "execute" if executor_command and raw_step == executor_command else f"step_{index}"
            command = executor_command if phase == "execute" else raw_step
            executor_used = executor_used or phase == "execute"
            resolved.append(
                RepoTaskStep(
                    phase=phase,
                    command=str(command),
                    model_visible=phase == "execute",
                )
            )
            continue

        if not isinstance(raw_step, dict):
            raise TypeError(f"Unsupported repo-task step type: {type(raw_step)!r}")

        phase = str(raw_step.get("name") or f"step_{index}")
        use_executor = bool(raw_step.get("use_executor", False))
        run_command_value = raw_step.get("run")

        if use_executor:
            if run_command_value is not None:
                raise ValueError(f"Step {phase!r} cannot set both run and use_executor.")
            if not executor_command:
                raise ValueError(f"Step {phase!r} requested use_executor but executor.command is missing.")
            resolved.append(
                RepoTaskStep(
                    phase=phase,
                    command=str(executor_command),
                    model_visible=True,
                )
            )
            executor_used = True
            continue

        if run_command_value is None:
            if phase == "execute" and executor_command:
                resolved.append(
                    RepoTaskStep(
                        phase=phase,
                        command=str(executor_command),
                        model_visible=True,
                    )
                )
                executor_used = True
                continue
            raise ValueError(f"Step {phase!r} must define run or use_executor.")

        resolved.append(
            RepoTaskStep(
                phase=phase,
                command=str(run_command_value),
                model_visible=bool(executor_command) and run_command_value == executor_command,
            )
        )
        executor_used = executor_used or (bool(executor_command) and run_command_value == executor_command)

    if executor_command and not executor_used:
        raise ValueError(
            "executor.command is configured but no step uses it. "
            "Add a string step with the same command or a named step with use_executor: true."
        )

    return resolved
    for pattern in patterns:
        for match in benchmark_dir.glob(pattern):
            if not match.is_file():
                continue
            relative = match.relative_to(benchmark_dir)
            if relative.parts and relative.parts[0] == "visible":
                relative = Path(*relative.parts[1:])
            destination = workspace / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(match, destination)
def _commit_workspace(workspace: Path, message: str) -> str:
    status = _git(workspace, ["status", "--porcelain"], cwd=workspace).stdout.strip()
    if not status:
        return _git(workspace, ["rev-parse", "HEAD"], cwd=workspace).stdout.strip()
    _git(workspace, ["add", "-A"], cwd=workspace)
    _git(workspace, ["commit", "-m", message], cwd=workspace)
    return _git(workspace, ["rev-parse", "HEAD"], cwd=workspace).stdout.strip()


def _cleanup_failed_repo_task(source_repo: Path, workspace: Path, branch_name: str, run_dir: Path) -> None:
    if workspace.exists():
        _git_try(source_repo, ["worktree", "remove", "--force", str(workspace)])
        shutil.rmtree(workspace, ignore_errors=True)

    branch_result = _git_try(source_repo, ["branch", "--list", branch_name])
    if branch_result.stdout.strip():
        _git_try(source_repo, ["branch", "-D", branch_name])

    shutil.rmtree(run_dir, ignore_errors=True)


def run_repo_task(
    benchmark_dir: Path,
    runtime_home: Path,
    model: str,
    environ: dict[str, str],
) -> Path:
    config = yaml.safe_load((benchmark_dir / "bench.yaml").read_text(encoding="utf-8"))
    bench_id = safe_slug(str(config.get("id", benchmark_dir.name)))
    started = utc_now()
    timestamp_slug = run_timestamp_slug(started)
    base_run_id = f"{timestamp_slug}__{bench_id}__{safe_slug(model)}"
    run_id = unique_child_name(runtime_home / "runs", base_run_id)
    run_dir = runtime_home / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    workspace_config = config["workspace"]
    if workspace_config["kind"] != "git_worktree":
        raise ValueError("Only git_worktree repo tasks are currently supported.")
    source_repo = Path(
        expand_env_string(str(workspace_config["source_repo"]), environ)
    ).expanduser().resolve()
    run_suffix = run_id[len(base_run_id) :]
    worktree_leaf = f"{started.strftime('%Y%m%dT%H%M%S%fZ')}{run_suffix}"
    branch_name = f"bench/{bench_id}/{safe_slug(model)}/{worktree_leaf}"
    workspace = runtime_home / "worktrees" / bench_id / safe_slug(model) / worktree_leaf
    workspace.parent.mkdir(parents=True, exist_ok=True)
    try:
        _git(source_repo, ["worktree", "add", "-b", branch_name, str(workspace), "HEAD"])

        visibility = config.get("visibility", {})
        _copy_pattern_matches(benchmark_dir, workspace, visibility.get("expose", []))
        hidden_stage_dir = run_dir / "hidden"
        hidden_patterns = visibility.get("hide", [])
        if hidden_patterns:
            hidden_stage_dir.mkdir(parents=True, exist_ok=True)
            _copy_pattern_matches(
                benchmark_dir,
                hidden_stage_dir,
                hidden_patterns,
                require_match=True,
            )
        else:
            hidden_stage_dir.mkdir(parents=True, exist_ok=True)

        command_rows: list[dict[str, Any]] = []
        for index, step in enumerate(_resolve_repo_steps(config), start=1):
            metrics_path = run_dir / "command-metrics" / f"{index:02d}__{safe_slug(step.phase)}.json"
            if step.model_visible:
                env = build_model_command_env(
                    environ,
                    {
                        "MODEL_ID": model,
                        "WORKSPACE_ROOT": str(workspace),
                        "TASK_PROMPT_PATH": str(workspace / "prompt.txt"),
                        "TASK_METRICS_PATH": str(metrics_path),
                    },
                )
            else:
                env = merge_environ(
                    environ,
                    {
                        "BENCH_MODEL": model,
                        "BENCH_RUN_DIR": str(run_dir),
                        "BENCH_BENCHMARK_DIR": str(benchmark_dir),
                        "BENCH_WORKSPACE": str(workspace),
                        "BENCH_HIDDEN_DIR": str(hidden_stage_dir),
                        "BENCH_COMMAND_METRICS_PATH": str(metrics_path),
                    },
                )
            record = run_command(
                step.command,
                cwd=benchmark_dir,
                env=env,
                phase=step.phase,
                metrics_path=metrics_path,
            )
            command_rows.append(record)
            write_jsonl(run_dir / "commands.jsonl", command_rows)
            if record["exit_code"] != 0:
                raise RuntimeError(record["stderr"] or record["stdout"] or f"Step failed: {step.command}")

        commit_after_run = ""
        if workspace_config.get("commit_outputs", False):
            commit_after_run = _commit_workspace(workspace, f"bench: capture outputs for {run_id}")

        score_path = run_dir / str(config.get("scoring", {}).get("output", "score.json"))
        score = json.loads(score_path.read_text(encoding="utf-8"))
        ended = utc_now()
        run_metrics = aggregate_metrics(command_rows)
        manifest = {
            "run_id": run_id,
            "benchmark": {
                "id": bench_id,
                "mode": "repo_task",
                "path": str(benchmark_dir),
            },
            "model": model,
            "started_at": iso_timestamp(started),
            "ended_at": iso_timestamp(ended),
            "timing": {
                "elapsed_ms": elapsed_milliseconds(started, ended),
            },
            "metrics": run_metrics,
            "workspace": {
                "kind": "git_worktree",
                "source_repo": str(source_repo),
                "branch": branch_name,
                "path": str(workspace),
                "keep_workspace": bool(workspace_config.get("keep_workspace", True)),
                "commit_after_run": commit_after_run,
            },
            "artifacts": {
                "commands": str(run_dir / "commands.jsonl"),
                "score": str(score_path),
                "report": str(run_dir / "report.md"),
            },
        }

        write_json(run_dir / "manifest.json", manifest)
        report_path = write_report(run_dir, manifest, score)
        record_run(
            runtime_home,
            {
                "run_id": run_id,
                "benchmark_id": bench_id,
                "benchmark_mode": "repo_task",
                "model": model,
                "started_at": manifest["started_at"],
                "ended_at": manifest["ended_at"],
                "elapsed_ms": manifest["timing"]["elapsed_ms"],
                "cost_usd": manifest["metrics"].get("cost_usd"),
                "input_tokens": manifest["metrics"].get("input_tokens"),
                "output_tokens": manifest["metrics"].get("output_tokens"),
                "total_tokens": manifest["metrics"].get("total_tokens"),
                "score_percent": float(score["summary"]["score_percent"]),
                "run_dir": str(run_dir),
                "report_path": str(report_path),
                "manifest_path": str(run_dir / "manifest.json"),
            },
        )
        return run_dir
    except Exception:
        _cleanup_failed_repo_task(source_repo, workspace, branch_name, run_dir)
        raise
