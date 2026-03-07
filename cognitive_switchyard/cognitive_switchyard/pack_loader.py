from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

import cognitive_switchyard.config as config

logger = logging.getLogger(__name__)


@dataclass
class PackConfig:
    """Parsed pack.yaml."""

    name: str
    description: str = ""
    version: str = "0.1.0"
    planning_enabled: bool = False
    planning_executor: str = "agent"
    planning_model: str = "opus"
    planning_prompt: str = ""
    planning_script: str = ""
    planning_max_instances: int = 1
    resolution_enabled: bool = True
    resolution_executor: str = "agent"
    resolution_model: str = "opus"
    resolution_prompt: str = ""
    resolution_script: str = ""
    execution_executor: str = "shell"
    execution_model: str = "sonnet"
    execution_prompt: str = ""
    execution_command: str = ""
    execution_max_workers: int = 2
    verification_enabled: bool = False
    verification_command: str = ""
    verification_interval: int = 4
    auto_fix_enabled: bool = False
    auto_fix_max_attempts: int = 2
    auto_fix_model: str = "opus"
    auto_fix_prompt: str = ""
    auto_fix_script: str = ""
    isolation_type: str = "none"
    isolation_setup: str = ""
    isolation_teardown: str = ""
    prerequisites: list[dict] = field(default_factory=list)
    task_idle_timeout: int = 300
    task_max_timeout: int = 0
    session_max_timeout: int = 14400
    progress_format: str = "##PROGRESS##"
    sidecar_format: str = "key-value"


def bootstrap_packs() -> None:
    if not config.BUILTIN_PACKS_DIR.exists():
        logger.warning("No built-in packs directory found at %s", config.BUILTIN_PACKS_DIR)
        return

    config.PACKS_DIR.mkdir(parents=True, exist_ok=True)
    for pack_source in config.BUILTIN_PACKS_DIR.iterdir():
        if not pack_source.is_dir():
            continue
        destination = config.PACKS_DIR / pack_source.name
        if destination.exists():
            continue
        shutil.copytree(pack_source, destination)


def reset_pack(name: str) -> bool:
    source = config.BUILTIN_PACKS_DIR / name
    destination = config.PACKS_DIR / name
    if not source.exists():
        logger.error("No built-in pack named '%s'", name)
        return False
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return True


def list_packs() -> list[PackConfig]:
    if not config.PACKS_DIR.exists():
        return []

    packs: list[PackConfig] = []
    for pack_path in sorted(config.PACKS_DIR.iterdir()):
        if not pack_path.is_dir():
            continue
        if not (pack_path / "pack.yaml").exists():
            continue
        try:
            packs.append(load_pack(pack_path.name))
        except Exception as exc:
            logger.warning("Skipping invalid pack '%s': %s", pack_path.name, exc)
    return packs


def load_pack(name: str) -> PackConfig:
    yaml_path = pack_dir(name) / "pack.yaml"
    if not yaml_path.exists():
        raise ValueError(f"Pack '{name}' not found (no pack.yaml at {yaml_path})")

    with yaml_path.open() as handle:
        data = yaml.safe_load(handle) or {}
    if not data.get("name"):
        raise ValueError(f"Pack '{name}': pack.yaml missing required 'name' field")

    phases = data.get("phases", {})
    planning = phases.get("planning", {})
    resolution = phases.get("resolution", {})
    execution = phases.get("execution", {})
    verification = phases.get("verification", {})
    auto_fix = data.get("auto_fix", {})
    isolation = data.get("isolation", {})
    timeouts = data.get("timeouts", {})
    status = data.get("status", {})

    return PackConfig(
        name=data["name"],
        description=data.get("description", ""),
        version=data.get("version", "0.1.0"),
        planning_enabled=planning.get("enabled", False),
        planning_executor=planning.get("executor", "agent"),
        planning_model=planning.get("model", "opus"),
        planning_prompt=planning.get("prompt", ""),
        planning_script=planning.get("script", ""),
        planning_max_instances=planning.get("max_instances", 1),
        resolution_enabled=resolution.get("enabled", True),
        resolution_executor=resolution.get("executor", "agent"),
        resolution_model=resolution.get("model", "opus"),
        resolution_prompt=resolution.get("prompt", ""),
        resolution_script=resolution.get("script", ""),
        execution_executor=execution.get("executor", "shell"),
        execution_model=execution.get("model", "sonnet"),
        execution_prompt=execution.get("prompt", ""),
        execution_command=execution.get("command", ""),
        execution_max_workers=execution.get("max_workers", 2),
        verification_enabled=verification.get("enabled", False),
        verification_command=verification.get("command", ""),
        verification_interval=verification.get("interval", 4),
        auto_fix_enabled=auto_fix.get("enabled", False),
        auto_fix_max_attempts=auto_fix.get("max_attempts", 2),
        auto_fix_model=auto_fix.get("model", "opus"),
        auto_fix_prompt=auto_fix.get("prompt", ""),
        auto_fix_script=auto_fix.get("script", ""),
        isolation_type=isolation.get("type", "none"),
        isolation_setup=isolation.get("setup", ""),
        isolation_teardown=isolation.get("teardown", ""),
        prerequisites=data.get("prerequisites", []),
        task_idle_timeout=timeouts.get("task_idle", 300),
        task_max_timeout=timeouts.get("task_max", 0),
        session_max_timeout=timeouts.get("session_max", 14400),
        progress_format=status.get("progress_format", "##PROGRESS##"),
        sidecar_format=status.get("sidecar_format", "key-value"),
    )


def pack_dir(name: str) -> Path:
    return config.PACKS_DIR / name


def check_scripts_executable(name: str) -> list[tuple[str, str]]:
    scripts_dir = pack_dir(name) / "scripts"
    if not scripts_dir.exists():
        return []

    failures: list[tuple[str, str]] = []
    for script in sorted(scripts_dir.iterdir()):
        if script.is_file() and not os.access(script, os.X_OK):
            failures.append(
                (
                    str(script.relative_to(pack_dir(name))),
                    f"chmod +x {script}",
                )
            )
    return failures


def run_preflight(name: str) -> list[tuple[str, bool, str]]:
    pack = load_pack(name)
    results: list[tuple[str, bool, str]] = []
    for prereq in pack.prerequisites:
        check_name = prereq.get("name", "unnamed")
        check_cmd = prereq.get("check", "")
        if not check_cmd:
            results.append((check_name, False, "No check command specified"))
            continue
        try:
            completed = subprocess.run(
                check_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            passed = completed.returncode == 0
            detail = (completed.stdout if passed else completed.stderr).strip()
            if not detail:
                detail = completed.stdout.strip() or completed.stderr.strip()
            results.append((check_name, passed, detail))
        except subprocess.TimeoutExpired:
            results.append((check_name, False, "Check timed out (30s)"))
        except Exception as exc:
            results.append((check_name, False, str(exc)))
    return results


def invoke_hook(
    pack_name: str,
    script_relative_path: str,
    args: Optional[list[str]] = None,
    cwd: Optional[str | Path] = None,
    capture_output: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    script_path = pack_dir(pack_name) / script_relative_path
    if not script_path.exists():
        raise FileNotFoundError(f"Hook script not found: {script_path}")
    if not os.access(script_path, os.X_OK):
        raise PermissionError(f"Hook script not executable: {script_path}")

    return subprocess.run(
        [str(script_path), *(args or [])],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=capture_output,
        text=True,
        timeout=timeout,
    )
