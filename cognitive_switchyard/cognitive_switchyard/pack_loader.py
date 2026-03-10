from __future__ import annotations

from pathlib import Path
import re
import shutil
from typing import Any

import yaml

from .models import (
    AutoFixConfig,
    ExecutionPhaseConfig,
    IsolationConfig,
    PackManifest,
    PhaseConfigSet,
    PlanningPhaseConfig,
    PrerequisiteCheck,
    ResolutionPhaseConfig,
    StatusConfig,
    TimeoutConfig,
    ValidationFinding,
    VerificationConfig,
)

_CONVENTIONAL_HOOKS = frozenset({"preflight", "isolate_start", "isolate_end", "resolve"})
_PACK_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class ManifestValidationError(ValueError):
    def __init__(self, findings: list[ValidationFinding]) -> None:
        self.findings = findings
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        lines = ["pack manifest validation failed:"]
        for finding in self.findings:
            lines.append(f"- {finding.path}: {finding.message}")
        return "\n".join(lines)


def load_pack_manifest(pack_root: Path) -> PackManifest:
    pack_root = pack_root.resolve()
    manifest_path = pack_root / "pack.yaml"
    findings: list[ValidationFinding] = []

    if not manifest_path.is_file():
        findings.append(ValidationFinding("pack.yaml", "manifest file is missing"))
        raise ManifestValidationError(findings)

    loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ManifestValidationError(
            [ValidationFinding("pack.yaml", "manifest must contain a YAML mapping")]
        )

    manifest = _build_manifest(pack_root, loaded, findings)
    if findings:
        raise ManifestValidationError(findings)
    return manifest


def iter_pack_script_files(pack_manifest: PackManifest) -> tuple[Path, ...]:
    scripts_dir = pack_manifest.root / "scripts"
    if not scripts_dir.is_dir():
        return ()
    return tuple(sorted(path for path in scripts_dir.rglob("*") if path.is_file()))


def resolve_pack_hook_path(pack_manifest: PackManifest, hook_name: str) -> Path | None:
    if hook_name == "preflight":
        return _find_conventional_hook(pack_manifest.root, hook_name)
    if hook_name == "isolate_start":
        return pack_manifest.isolation.setup or _find_conventional_hook(pack_manifest.root, hook_name)
    if hook_name == "isolate_end":
        return (
            pack_manifest.isolation.teardown
            or _find_conventional_hook(pack_manifest.root, hook_name)
        )
    if hook_name == "resolve":
        return (
            pack_manifest.phases.resolution.script
            or _find_conventional_hook(pack_manifest.root, hook_name)
        )
    if hook_name == "execute":
        return pack_manifest.phases.execution.command
    raise ValueError(f"Unsupported hook name: {hook_name}")


def list_runtime_pack_names(runtime_packs_dir: Path) -> tuple[str, ...]:
    if not runtime_packs_dir.is_dir():
        return ()
    return tuple(
        path.name
        for path in sorted(runtime_packs_dir.iterdir())
        if path.is_dir() and (path / "pack.yaml").is_file()
    )


def list_builtin_pack_names(builtin_packs_root: Path) -> tuple[str, ...]:
    if not builtin_packs_root.is_dir():
        return ()
    return tuple(
        path.name
        for path in sorted(builtin_packs_root.iterdir())
        if path.is_dir() and (path / "pack.yaml").is_file()
    )


def sync_builtin_packs(
    *,
    builtin_packs_root: Path,
    runtime_packs_dir: Path,
    reset_pack: str | None = None,
    reset_all: bool = False,
) -> tuple[str, ...]:
    builtin_names = list_builtin_pack_names(builtin_packs_root)
    runtime_packs_dir.mkdir(parents=True, exist_ok=True)

    if reset_pack is not None:
        if reset_pack not in builtin_names:
            raise KeyError(f"Unknown built-in pack: {reset_pack}")
        names_to_sync = (reset_pack,)
    elif reset_all:
        names_to_sync = builtin_names
    else:
        names_to_sync = builtin_names

    synced: list[str] = []
    for name in names_to_sync:
        source = builtin_packs_root / name
        target = runtime_packs_dir / name
        if reset_pack is None and not reset_all and target.exists():
            continue
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        synced.append(name)
    return tuple(synced)


def _build_manifest(
    pack_root: Path, data: dict[str, Any], findings: list[ValidationFinding]
) -> PackManifest:
    phases_data = _mapping(data.get("phases"), "phases", findings, default={})
    if "verification" in data:
        findings.append(
            ValidationFinding("verification", "must be nested under 'phases.verification'")
        )

    planning_data = _mapping(phases_data.get("planning"), "phases.planning", findings, default={})
    resolution_data = _mapping(
        phases_data.get("resolution"), "phases.resolution", findings, default={}
    )
    execution_data = _mapping(phases_data.get("execution"), "phases.execution", findings, default={})
    verification_data = _mapping(
        phases_data.get("verification"), "phases.verification", findings, default={}
    )

    planning = PlanningPhaseConfig(
        enabled=_bool(planning_data.get("enabled", False), "phases.planning.enabled", findings),
        executor=_string(planning_data.get("executor", "agent"), "phases.planning.executor", findings),
        model=_optional_string(planning_data.get("model"), "phases.planning.model", findings),
        prompt=_optional_pack_path(
            planning_data.get("prompt"), pack_root, "phases.planning.prompt", findings
        ),
        max_instances=_int(planning_data.get("max_instances", 1), "phases.planning.max_instances", findings),
    )
    if planning.enabled:
        if planning.executor != "agent":
            findings.append(
                ValidationFinding("phases.planning.executor", "must be 'agent' when planning is enabled")
            )
        if "model" not in planning_data:
            findings.append(
                ValidationFinding("phases.planning.model", "required when executor is 'agent'")
            )
        if "prompt" not in planning_data:
            findings.append(
                ValidationFinding("phases.planning.prompt", "required when executor is 'agent'")
            )

    resolution = ResolutionPhaseConfig(
        enabled=_bool(resolution_data.get("enabled", True), "phases.resolution.enabled", findings),
        executor=_string(
            resolution_data.get("executor", "agent"), "phases.resolution.executor", findings
        ),
        model=_optional_string(resolution_data.get("model"), "phases.resolution.model", findings),
        prompt=_optional_pack_path(
            resolution_data.get("prompt"), pack_root, "phases.resolution.prompt", findings
        ),
        script=_optional_pack_path(
            resolution_data.get("script"), pack_root, "phases.resolution.script", findings
        ),
    )
    if resolution.enabled:
        if resolution.executor == "agent":
            if resolution_data and "model" not in resolution_data:
                findings.append(
                    ValidationFinding("phases.resolution.model", "required when executor is 'agent'")
                )
            if resolution_data and "prompt" not in resolution_data:
                findings.append(
                    ValidationFinding("phases.resolution.prompt", "required when executor is 'agent'")
                )
        elif resolution.executor == "script":
            if "script" not in resolution_data:
                findings.append(
                    ValidationFinding("phases.resolution.script", "required when executor is 'script'")
                )
        elif resolution.executor != "passthrough":
            findings.append(
                ValidationFinding(
                    "phases.resolution.executor",
                    "must be one of 'agent', 'script', or 'passthrough'",
                )
            )

    execution = ExecutionPhaseConfig(
        enabled=_bool(execution_data.get("enabled", True), "phases.execution.enabled", findings),
        executor=_string(execution_data.get("executor", "shell"), "phases.execution.executor", findings),
        model=_optional_string(execution_data.get("model"), "phases.execution.model", findings),
        prompt=_optional_pack_path(
            execution_data.get("prompt"), pack_root, "phases.execution.prompt", findings
        ),
        command=_optional_pack_path(
            execution_data.get("command"), pack_root, "phases.execution.command", findings
        ),
        max_workers=_int(execution_data.get("max_workers", 2), "phases.execution.max_workers", findings),
    )
    if execution.enabled:
        if execution.executor == "agent":
            if "model" not in execution_data:
                findings.append(
                    ValidationFinding("phases.execution.model", "required when executor is 'agent'")
                )
            if "prompt" not in execution_data:
                findings.append(
                    ValidationFinding("phases.execution.prompt", "required when executor is 'agent'")
                )
        elif execution.executor == "shell":
            if "command" not in execution_data:
                findings.append(
                    ValidationFinding("phases.execution.command", "required when executor is 'shell'")
                )
        else:
            findings.append(
                ValidationFinding("phases.execution.executor", "must be one of 'agent' or 'shell'")
            )
    if execution.enabled is not True:
        findings.append(ValidationFinding("phases.execution.enabled", "must be true"))

    verification = VerificationConfig(
        enabled=_bool(
            verification_data.get("enabled", False), "phases.verification.enabled", findings
        ),
        command=_optional_string(
            verification_data.get("command"), "phases.verification.command", findings
        ),
        interval=_int(
            verification_data.get("interval", 4), "phases.verification.interval", findings
        ),
    )
    if verification.enabled and "command" not in verification_data:
        findings.append(
            ValidationFinding(
                "phases.verification.command", "required when verification is enabled"
            )
        )

    auto_fix_data = _mapping(data.get("auto_fix"), "auto_fix", findings, default={})
    auto_fix = AutoFixConfig(
        enabled=_bool(auto_fix_data.get("enabled", False), "auto_fix.enabled", findings),
        max_attempts=_int(auto_fix_data.get("max_attempts", 2), "auto_fix.max_attempts", findings),
        model=_optional_string(auto_fix_data.get("model"), "auto_fix.model", findings),
        prompt=_optional_pack_path(auto_fix_data.get("prompt"), pack_root, "auto_fix.prompt", findings),
    )
    if auto_fix.enabled:
        if "model" not in auto_fix_data:
            findings.append(ValidationFinding("auto_fix.model", "required when auto_fix is enabled"))
        if "prompt" not in auto_fix_data:
            findings.append(
                ValidationFinding("auto_fix.prompt", "required when auto_fix is enabled")
            )

    isolation_data = _mapping(data.get("isolation"), "isolation", findings, default={})
    isolation = IsolationConfig(
        type=_string(isolation_data.get("type", "none"), "isolation.type", findings),
        setup=_optional_pack_path(isolation_data.get("setup"), pack_root, "isolation.setup", findings),
        teardown=_optional_pack_path(
            isolation_data.get("teardown"), pack_root, "isolation.teardown", findings
        ),
    )
    _one_of(
        isolation.type,
        "isolation.type",
        findings,
        ("git-worktree", "temp-directory", "none"),
    )

    prerequisites_data = data.get("prerequisites", [])
    prerequisites = _prerequisites(prerequisites_data, findings)

    timeouts_data = _mapping(data.get("timeouts"), "timeouts", findings, default={})
    timeouts = TimeoutConfig(
        task_idle=_int(timeouts_data.get("task_idle", 300), "timeouts.task_idle", findings),
        task_max=_int(timeouts_data.get("task_max", 0), "timeouts.task_max", findings),
        session_max=_int(timeouts_data.get("session_max", 14400), "timeouts.session_max", findings),
    )

    status_data = _mapping(data.get("status"), "status", findings, default={})
    status = StatusConfig(
        progress_format=_string(
            status_data.get("progress_format", "##PROGRESS##"), "status.progress_format", findings
        ),
        sidecar_format=_string(
            status_data.get("sidecar_format", "key-value"), "status.sidecar_format", findings
        ),
    )
    _one_of(
        status.sidecar_format,
        "status.sidecar_format",
        findings,
        ("key-value", "json", "yaml"),
    )
    try:
        re.compile(status.progress_format)
    except re.error as exc:
        findings.append(
            ValidationFinding(
                "status.progress_format",
                f"must be a valid regex: {exc.msg}",
            )
        )

    return PackManifest(
        root=pack_root,
        name=_kebab_case_string(data.get("name"), "name", findings),
        description=_string(data.get("description"), "description", findings),
        version=_semver_string(data.get("version"), "version", findings),
        phases=PhaseConfigSet(planning=planning, resolution=resolution, execution=execution),
        verification=verification,
        auto_fix=auto_fix,
        isolation=isolation,
        prerequisites=prerequisites,
        timeouts=timeouts,
        status=status,
    )


def _find_conventional_hook(pack_root: Path, hook_name: str) -> Path | None:
    if hook_name not in _CONVENTIONAL_HOOKS:
        raise ValueError(f"Unsupported conventional hook name: {hook_name}")
    scripts_dir = pack_root / "scripts"
    if not scripts_dir.is_dir():
        return None

    exact_match = scripts_dir / hook_name
    if exact_match.is_file():
        return _validated_conventional_hook_path(exact_match, pack_root, hook_name)

    stem_matches = sorted(
        _validated_conventional_hook_path(path, pack_root, hook_name)
        for path in scripts_dir.iterdir()
        if path.is_file() and path.stem == hook_name
    )
    if len(stem_matches) > 1:
        raise ValueError(
            f"Multiple conventional hook scripts matched {hook_name!r}: "
            + ", ".join(path.name for path in stem_matches)
        )
    if stem_matches:
        return stem_matches[0]
    return None


def _validated_conventional_hook_path(path: Path, pack_root: Path, hook_name: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(pack_root)
    except ValueError as exc:
        relative_path = path.relative_to(pack_root).as_posix()
        raise ValueError(
            f"Conventional hook {hook_name!r} resolves outside the pack root: {relative_path}"
        ) from exc
    return path


def _mapping(
    value: Any, path: str, findings: list[ValidationFinding], default: dict[str, Any]
) -> dict[str, Any]:
    if value is None:
        return default
    if isinstance(value, dict):
        return value
    findings.append(ValidationFinding(path, "must be a mapping"))
    return default


def _string(value: Any, path: str, findings: list[ValidationFinding]) -> str:
    if isinstance(value, str) and value.strip():
        return value
    findings.append(ValidationFinding(path, "must be a non-empty string"))
    return ""


def _kebab_case_string(value: Any, path: str, findings: list[ValidationFinding]) -> str:
    parsed = _string(value, path, findings)
    if parsed and not _PACK_NAME_RE.fullmatch(parsed):
        findings.append(ValidationFinding(path, "must be a kebab-case identifier"))
    return parsed


def _semver_string(value: Any, path: str, findings: list[ValidationFinding]) -> str:
    parsed = _string(value, path, findings)
    if parsed and not _SEMVER_RE.fullmatch(parsed):
        findings.append(ValidationFinding(path, "must be a semver string"))
    return parsed


def _optional_string(value: Any, path: str, findings: list[ValidationFinding]) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    findings.append(ValidationFinding(path, "must be a non-empty string"))
    return None


def _bool(value: Any, path: str, findings: list[ValidationFinding]) -> bool:
    if isinstance(value, bool):
        return value
    findings.append(ValidationFinding(path, "must be a boolean"))
    return False


def _int(value: Any, path: str, findings: list[ValidationFinding]) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    findings.append(ValidationFinding(path, "must be an integer"))
    return 0


def _one_of(
    value: str, path: str, findings: list[ValidationFinding], allowed: tuple[str, ...]
) -> str:
    if value not in allowed:
        quoted = ", ".join(f"'{item}'" for item in allowed[:-1])
        findings.append(
            ValidationFinding(path, f"must be one of {quoted}, or '{allowed[-1]}'")
        )
    return value


def _optional_pack_path(
    value: Any, pack_root: Path, path: str, findings: list[ValidationFinding]
) -> Path | None:
    relative_path = _optional_string(value, path, findings)
    if relative_path is None:
        return None
    resolved = (pack_root / relative_path).resolve()
    try:
        resolved.relative_to(pack_root)
    except ValueError:
        findings.append(ValidationFinding(path, "must stay within the pack root"))
        return None
    if not resolved.exists():
        findings.append(ValidationFinding(path, "referenced file does not exist"))
        return None
    return resolved


def _prerequisites(value: Any, findings: list[ValidationFinding]) -> list[PrerequisiteCheck]:
    if value is None:
        return []
    if not isinstance(value, list):
        findings.append(ValidationFinding("prerequisites", "must be a list"))
        return []

    checks: list[PrerequisiteCheck] = []
    for index, item in enumerate(value):
        path = f"prerequisites[{index}]"
        if not isinstance(item, dict):
            findings.append(ValidationFinding(path, "must be a mapping"))
            continue
        checks.append(
            PrerequisiteCheck(
                name=_string(item.get("name"), f"{path}.name", findings),
                check=_string(item.get("check"), f"{path}.check", findings),
            )
        )
    return checks
