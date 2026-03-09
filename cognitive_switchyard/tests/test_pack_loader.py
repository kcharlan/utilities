from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from cognitive_switchyard.pack_loader import (
    ManifestValidationError,
    load_pack_manifest,
    resolve_pack_hook_path,
)


def _write_pack_fixture(tmp_path: Path, manifest: str) -> Path:
    pack_root = tmp_path / "pack-under-test"
    (pack_root / "scripts").mkdir(parents=True)
    (pack_root / "prompts").mkdir(parents=True)
    (pack_root / "scripts" / "execute").write_text("#!/bin/sh\necho execute\n", encoding="utf-8")
    (pack_root / "prompts" / "fixer.md").write_text("fixer prompt\n", encoding="utf-8")
    (pack_root / "pack.yaml").write_text(dedent(manifest).strip() + "\n", encoding="utf-8")
    return pack_root


def test_load_pack_manifest_applies_documented_defaults(repo_root: Path) -> None:
    pack_root = repo_root / "tests" / "fixtures" / "packs" / "valid_shell_pack"

    manifest = load_pack_manifest(pack_root)

    assert manifest.name == "valid-shell-pack"
    assert manifest.phases.planning.enabled is False
    assert manifest.phases.planning.max_instances == 1
    assert manifest.phases.resolution.enabled is True
    assert manifest.phases.resolution.executor == "passthrough"
    assert manifest.phases.execution.enabled is True
    assert manifest.phases.execution.executor == "shell"
    assert manifest.phases.execution.max_workers == 2
    assert manifest.phases.execution.command == pack_root / "scripts" / "execute"
    assert manifest.verification.enabled is False
    assert manifest.verification.interval == 4
    assert manifest.auto_fix.enabled is False
    assert manifest.auto_fix.max_attempts == 2
    assert manifest.isolation.type == "none"
    assert manifest.timeouts.task_idle == 300
    assert manifest.timeouts.task_max == 0
    assert manifest.timeouts.session_max == 14400
    assert manifest.status.progress_format == "##PROGRESS##"
    assert manifest.status.sidecar_format == "key-value"
    assert manifest.prerequisites == []


def test_invalid_manifest_reports_structured_readable_error(repo_root: Path) -> None:
    pack_root = repo_root / "tests" / "fixtures" / "packs" / "invalid_shell_pack"

    with pytest.raises(ManifestValidationError) as excinfo:
        load_pack_manifest(pack_root)

    error = excinfo.value
    assert len(error.findings) == 1
    finding = error.findings[0]
    assert finding.path == "phases.execution.command"
    assert "required when executor is 'shell'" == finding.message
    assert "phases.execution.command" in str(error)


def test_manifest_reference_paths_cannot_escape_pack_root(repo_root: Path) -> None:
    pack_root = repo_root / "tests" / "fixtures" / "packs" / "escape_prompt_pack"

    with pytest.raises(ManifestValidationError) as excinfo:
        load_pack_manifest(pack_root)

    error = excinfo.value
    assert len(error.findings) == 1
    finding = error.findings[0]
    assert finding.path == "phases.planning.prompt"
    assert "must stay within the pack root" == finding.message


def test_load_pack_manifest_reads_verification_from_phases_mapping(tmp_path: Path) -> None:
    pack_root = _write_pack_fixture(
        tmp_path,
        """
        name: verification-pack
        description: Verification config is nested under phases.
        version: 1.2.3

        phases:
          verification:
            enabled: true
            command: pytest -q
            interval: 7
          execution:
            enabled: true
            executor: shell
            command: scripts/execute
        """,
    )

    manifest = load_pack_manifest(pack_root)

    assert manifest.verification.enabled is True
    assert manifest.verification.command == "pytest -q"
    assert manifest.verification.interval == 7


def test_invalid_manifest_reports_contract_level_schema_errors(tmp_path: Path) -> None:
    pack_root = _write_pack_fixture(
        tmp_path,
        """
        name: Invalid Pack
        description: Invalid schema values for packet 01 validation.
        version: one.two.three

        verification:
          enabled: true
          command: pytest -q

        phases:
          execution:
            enabled: true
            executor: shell
            command: scripts/execute

        auto_fix:
          enabled: true

        isolation:
          type: sandbox

        status:
          sidecar_format: toml
        """,
    )

    with pytest.raises(ManifestValidationError) as excinfo:
        load_pack_manifest(pack_root)

    findings = {(finding.path, finding.message) for finding in excinfo.value.findings}
    assert findings == {
        ("name", "must be a kebab-case identifier"),
        ("version", "must be a semver string"),
        ("verification", "must be nested under 'phases.verification'"),
        ("auto_fix.model", "required when auto_fix is enabled"),
        ("auto_fix.prompt", "required when auto_fix is enabled"),
        ("isolation.type", "must be one of 'git-worktree', 'temp-directory', or 'none'"),
        ("status.sidecar_format", "must be one of 'key-value', 'json', or 'yaml'"),
    }


def test_packet_01_manifest_parsing_regressions_still_pass(repo_root: Path) -> None:
    pack_root = repo_root / "tests" / "fixtures" / "packs" / "valid_shell_pack"

    manifest = load_pack_manifest(pack_root)

    assert manifest.name == "valid-shell-pack"
    assert manifest.phases.execution.command == pack_root / "scripts" / "execute"
    assert manifest.prerequisites == []


def test_conventional_hook_resolution_rejects_paths_that_escape_pack_root(
    tmp_path: Path,
) -> None:
    pack_root = _write_pack_fixture(
        tmp_path,
        """
        name: escaping-hook-pack
        description: Conventional hooks must stay inside the pack.
        version: 1.2.3

        phases:
          execution:
            enabled: true
            executor: shell
            command: scripts/execute
        """,
    )
    outside_script = tmp_path / "outside-preflight"
    outside_script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (pack_root / "scripts" / "preflight").symlink_to(outside_script)

    manifest = load_pack_manifest(pack_root)

    with pytest.raises(ValueError) as excinfo:
        resolve_pack_hook_path(manifest, "preflight")

    assert "resolves outside the pack root" in str(excinfo.value)
