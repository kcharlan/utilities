# Phase 02: Pack Loader

**Design doc:** `docs/cognitive_switchyard_design.md`

## Spec

Build the pack discovery, validation, and hook invocation system. A pack is a directory in `~/.switchyard/packs/` containing `pack.yaml` and supporting files (prompts, scripts, templates).

### Files to create

- `switchyard/pack_loader.py`

### Dependencies from prior phases

- `switchyard/config.py` — `PACKS_DIR` path constant
- `switchyard/models.py` — dataclasses (not directly used but establishes conventions)

### Pack discovery

- `list_packs() -> list[dict]` — Scan `PACKS_DIR` for directories containing `pack.yaml`. Return list of `{"name": str, "description": str, "version": str, "path": Path}`.
- `load_pack(name: str) -> dict` — Read and parse `pack.yaml` from the named pack directory. Returns the full parsed YAML as a dict.

### Pack validation

- `validate_pack(pack_config: dict, pack_path: Path) -> list[str]` — Validate a parsed pack.yaml. Returns a list of error strings (empty = valid). Must check:
  - Required top-level fields: `name` (str, kebab-case), `description` (str), `version` (str).
  - `phases.execution.enabled` must be `true` (always required).
  - If `phases.planning.enabled`, then `phases.planning.executor` must be `"agent"`, and `phases.planning.prompt` must reference an existing file relative to pack_path.
  - If `phases.resolution.enabled`, then `phases.resolution.executor` must be one of `"agent"`, `"script"`, `"passthrough"`. If `"agent"`, `prompt` must reference an existing file. If `"script"`, `script` must reference an existing file.
  - If `phases.execution.executor` is `"agent"`, `prompt` must exist. If `"shell"`, `command` must exist.
  - If `phases.verification.enabled`, `command` must be a non-empty string.
  - If `auto_fix.enabled`, `prompt` must reference an existing file.
  - If `isolation.setup` or `isolation.teardown` is set, the referenced file must exist.
  - All referenced paths are relative to the pack directory.

### Executable-bit preflight

- `check_executable_bits(pack_path: Path) -> list[dict]` — Scan `pack_path/scripts/` for all files. Return a list of `{"file": str, "fix_command": str}` for any file missing the executable bit. Empty list = all OK. The fix_command is the exact `chmod +x <full_path>` string.

This check runs unconditionally for every pack at every session start, before the pack's own preflight hook.

### Hook invocation

- `run_hook(pack_path: Path, script_rel_path: str, args: list[str], cwd: Path = None, capture: bool = True, timeout: int = None) -> subprocess.CompletedProcess` — Run a pack script via `subprocess.run()`. The script is resolved as `pack_path / script_rel_path`. Arguments are passed positionally. If `cwd` is provided, set the working directory. Capture stdout/stderr if `capture=True`. Raise `FileNotFoundError` if the script doesn't exist. Raise `PermissionError` if the script isn't executable (check before invoking — don't let subprocess produce a confusing error). Pass `timeout` to subprocess if set.

- `run_hook_async(pack_path: Path, script_rel_path: str, args: list[str], cwd: Path = None) -> subprocess.Popen` — Start a long-running hook (like `execute`) as a subprocess via `Popen`. Return the Popen object for the caller to manage. Stdout and stderr are set to `subprocess.PIPE`. Same pre-invocation checks as `run_hook`.

### Preflight execution

- `run_preflight(pack_config: dict, pack_path: Path) -> list[dict]` — Run the pack's `prerequisites` list. Each prerequisite has `name` (str) and `check` (shell command string). Execute each check via `subprocess.run(shell=True)`. Return list of `{"name": str, "passed": bool, "output": str}`.

## Acceptance tests

```python
# tests/test_phase02_pack_loader.py
import os
import stat
import subprocess
import yaml
import pytest
from pathlib import Path

from switchyard.config import PACKS_DIR
from switchyard.pack_loader import (
    list_packs, load_pack, validate_pack,
    check_executable_bits, run_hook, run_hook_async, run_preflight,
)


@pytest.fixture
def packs_dir(tmp_path, monkeypatch):
    d = tmp_path / "packs"
    d.mkdir()
    monkeypatch.setattr("switchyard.pack_loader.PACKS_DIR", d)
    return d


def _write_pack(packs_dir, name, config, scripts=None, prompts=None):
    """Helper: create a minimal pack directory."""
    pack_dir = packs_dir / name
    pack_dir.mkdir()
    (pack_dir / "pack.yaml").write_text(yaml.dump(config))
    if scripts:
        (pack_dir / "scripts").mkdir()
        for sname, content in scripts.items():
            p = pack_dir / "scripts" / sname
            p.write_text(content)
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
    if prompts:
        (pack_dir / "prompts").mkdir()
        for pname, content in prompts.items():
            (pack_dir / "prompts" / pname).write_text(content)
    return pack_dir


MINIMAL_VALID = {
    "name": "test-pack",
    "description": "A test pack",
    "version": "1.0.0",
    "phases": {"execution": {"enabled": True, "executor": "shell", "command": "scripts/run.sh"}},
}


# --- Discovery ---

def test_list_packs_finds_valid(packs_dir):
    _write_pack(packs_dir, "alpha", {**MINIMAL_VALID, "name": "alpha"}, scripts={"run.sh": "#!/bin/bash\necho ok"})
    _write_pack(packs_dir, "beta", {**MINIMAL_VALID, "name": "beta"}, scripts={"run.sh": "#!/bin/bash\necho ok"})
    packs = list_packs()
    names = {p["name"] for p in packs}
    assert names == {"alpha", "beta"}


def test_list_packs_ignores_dirs_without_yaml(packs_dir):
    (packs_dir / "not-a-pack").mkdir()
    assert list_packs() == []


# --- Validation ---

def test_validate_valid_pack(packs_dir):
    pack_dir = _write_pack(packs_dir, "good", MINIMAL_VALID, scripts={"run.sh": "#!/bin/bash\necho ok"})
    config = yaml.safe_load((pack_dir / "pack.yaml").read_text())
    errors = validate_pack(config, pack_dir)
    assert errors == []


def test_validate_missing_name(packs_dir):
    bad = {k: v for k, v in MINIMAL_VALID.items() if k != "name"}
    pack_dir = _write_pack(packs_dir, "bad", bad)
    errors = validate_pack(bad, pack_dir)
    assert any("name" in e.lower() for e in errors)


def test_validate_execution_must_be_enabled(packs_dir):
    bad = {**MINIMAL_VALID, "phases": {"execution": {"enabled": False}}}
    pack_dir = _write_pack(packs_dir, "bad", bad)
    errors = validate_pack(bad, pack_dir)
    assert any("execution" in e.lower() for e in errors)


def test_validate_missing_prompt_file(packs_dir):
    config = {
        **MINIMAL_VALID,
        "phases": {
            "execution": {"enabled": True, "executor": "agent", "prompt": "prompts/worker.md"},
        },
    }
    pack_dir = _write_pack(packs_dir, "bad", config)  # no prompts dir
    errors = validate_pack(config, pack_dir)
    assert any("worker.md" in e or "prompt" in e.lower() for e in errors)


# --- Executable-bit preflight ---

def test_executable_bits_all_ok(packs_dir):
    pack_dir = _write_pack(packs_dir, "good", MINIMAL_VALID, scripts={"run.sh": "#!/bin/bash\necho ok"})
    result = check_executable_bits(pack_dir)
    assert result == []


def test_executable_bits_detects_missing(packs_dir):
    pack_dir = _write_pack(packs_dir, "bad", MINIMAL_VALID, scripts={"run.sh": "#!/bin/bash\necho ok"})
    script = pack_dir / "scripts" / "run.sh"
    script.chmod(0o644)  # remove executable bit
    result = check_executable_bits(pack_dir)
    assert len(result) == 1
    assert "chmod +x" in result[0]["fix_command"]
    assert "run.sh" in result[0]["fix_command"]


# --- Hook invocation ---

def test_run_hook_captures_output(packs_dir):
    pack_dir = _write_pack(packs_dir, "test", MINIMAL_VALID, scripts={"echo.sh": "#!/bin/bash\necho hello"})
    result = run_hook(pack_dir, "scripts/echo.sh", [])
    assert result.stdout.strip() == "hello"
    assert result.returncode == 0


def test_run_hook_passes_args(packs_dir):
    pack_dir = _write_pack(packs_dir, "test", MINIMAL_VALID, scripts={"args.sh": "#!/bin/bash\necho $1 $2"})
    result = run_hook(pack_dir, "scripts/args.sh", ["foo", "bar"])
    assert "foo bar" in result.stdout


def test_run_hook_raises_on_missing_script(packs_dir):
    pack_dir = _write_pack(packs_dir, "test", MINIMAL_VALID)
    with pytest.raises(FileNotFoundError):
        run_hook(pack_dir, "scripts/nonexistent.sh", [])


def test_run_hook_raises_on_not_executable(packs_dir):
    pack_dir = _write_pack(packs_dir, "test", MINIMAL_VALID, scripts={"noexec.sh": "#!/bin/bash\necho hi"})
    (pack_dir / "scripts" / "noexec.sh").chmod(0o644)
    with pytest.raises(PermissionError):
        run_hook(pack_dir, "scripts/noexec.sh", [])


def test_run_hook_async_returns_popen(packs_dir):
    pack_dir = _write_pack(packs_dir, "test", MINIMAL_VALID,
                           scripts={"slow.sh": "#!/bin/bash\nsleep 0.1\necho done"})
    proc = run_hook_async(pack_dir, "scripts/slow.sh", [])
    assert isinstance(proc, subprocess.Popen)
    stdout, _ = proc.communicate(timeout=5)
    assert proc.returncode == 0
    assert "done" in stdout.decode()


# --- Preflight ---

def test_preflight_passes(packs_dir):
    config = {**MINIMAL_VALID, "prerequisites": [{"name": "echo check", "check": "echo ok"}]}
    results = run_preflight(config, packs_dir / "test")
    assert results[0]["passed"] is True


def test_preflight_detects_failure(packs_dir):
    config = {**MINIMAL_VALID, "prerequisites": [{"name": "bad check", "check": "exit 1"}]}
    results = run_preflight(config, packs_dir / "test")
    assert results[0]["passed"] is False
```
