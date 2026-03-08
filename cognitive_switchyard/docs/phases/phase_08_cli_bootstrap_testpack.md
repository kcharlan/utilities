# Phase 08: CLI Entry Point, Self-Bootstrapping, and Test-Echo Pack

**Design doc:** `docs/cognitive_switchyard_design.md` (Sections 7.2, 4.5, 8 Phase 1)

## Spec

Build the self-bootstrapping CLI entry point, pack distribution system, and the test-echo pack. After this phase, `./switchyard start --pack test-echo --session my-run` works end-to-end from a cold start (no pre-existing venv).

### Files to create

- `switchyard` (executable entry point at project root — no extension)
- `switchyard/cli.py` — Argument parsing and command dispatch
- `packs/test-echo/` — Built-in test-echo pack directory

### Self-bootstrapping (`switchyard` entry point)

Single-file script at project root. Contains a `bootstrap()` function:

1. Check if dependencies are importable (`fastapi`, `uvicorn`, `aiosqlite`). If yes, continue.
2. If not, create venv at `~/.switchyard_venv/`, install dependencies via pip, re-exec with `os.execv()` using the venv's Python.
3. Print brief progress messages during first-time setup.
4. After bootstrap, import `switchyard.cli` and call `main()`.

The entry point must have a shebang (`#!/usr/bin/env python3`) and the executable bit set.

### CLI arguments (`cli.py`)

`main()` uses `argparse` with subcommands:

- `switchyard start --pack <name> --session <name> [--workers N] [--planners N] [--poll-interval N]` — Create a session and start orchestration. If the session already exists (idempotent restart), resume it.
- `switchyard list-packs` — List available packs with name and description.
- `switchyard validate-pack <name>` — Run pack validation (pack.yaml schema + executable-bit check). Print results.
- `switchyard reset-pack <name>` — Restore a single built-in pack to factory default (copy from `packs/` in source to `~/.switchyard/packs/`). Must ask for confirmation if the target already exists.
- `switchyard reset-all-packs` — Restore all built-in packs. Confirmation required.
- `switchyard serve [--port PORT]` — Start the web UI server (implemented in Phase 09, this phase just registers the subcommand with a stub).

### Pack distribution

On first run (via `ensure_dirs()` or a `distribute_builtin_packs()` function):

- Scan the `packs/` directory in the source tree for subdirectories.
- For each, copy to `~/.switchyard/packs/<name>/` if not already present.
- If the pack directory already exists locally, do NOT overwrite (user may have customized).
- `--reset-pack <name>`: Delete the local copy and re-copy from source. Requires `--force` or interactive confirmation.
- `--reset-all-packs`: Same for all built-in packs.

The source `packs/` directory path is determined relative to the `switchyard` entry point script.

### Test-echo pack

A minimal pack that proves the engine works without any LLM or external tool dependency.

```
packs/test-echo/
  pack.yaml
  scripts/
    execute.sh       # Reads task file, echoes content, writes status sidecar
    preflight.sh     # Always passes (checks nothing)
  templates/
    intake.md        # Simple template: "# Task Title\nDescription"
```

**pack.yaml:**
```yaml
name: test-echo
description: "Minimal test pack that echoes task content. For testing the orchestrator."
version: "1.0.0"

phases:
  planning:
    enabled: false
  resolution:
    enabled: false
  execution:
    enabled: true
    executor: shell
    command: scripts/execute.sh
    max_workers: 4
  verification:
    enabled: false

auto_fix:
  enabled: false

isolation:
  type: none

prerequisites:
  - name: "bash"
    check: "which bash"

timeouts:
  task_idle: 30
  task_max: 60
  session_max: 300
```

**execute.sh:** Reads `$1` (task file path), prints content to stdout, writes a `.status` sidecar file adjacent to the task file with `STATUS: done`.

**preflight.sh:** Checks `which bash`, exits 0 if found.

## Acceptance tests

```python
# tests/test_phase08_cli_bootstrap_testpack.py
import os
import shutil
import stat
import subprocess
import sys
import yaml
import pytest
from pathlib import Path

from switchyard.config import ensure_dirs, PACKS_DIR, SWITCHYARD_HOME


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    home = tmp_path / ".switchyard"
    monkeypatch.setattr("switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("switchyard.config.DB_PATH", home / "switchyard.db")
    monkeypatch.setattr("switchyard.config.CONFIG_PATH", home / "config.yaml")
    monkeypatch.setattr("switchyard.config.PACKS_DIR", home / "packs")
    monkeypatch.setattr("switchyard.config.SESSIONS_DIR", home / "sessions")
    ensure_dirs()


# --- Test-echo pack structure ---

def test_test_echo_pack_exists():
    """The test-echo pack must exist in the source packs directory."""
    source_packs = Path(__file__).parent.parent / "packs"
    pack_dir = source_packs / "test-echo"
    assert pack_dir.is_dir()
    assert (pack_dir / "pack.yaml").exists()


def test_test_echo_pack_yaml_valid():
    source_packs = Path(__file__).parent.parent / "packs"
    pack_dir = source_packs / "test-echo"
    config = yaml.safe_load((pack_dir / "pack.yaml").read_text())
    assert config["name"] == "test-echo"
    assert config["phases"]["execution"]["enabled"] is True
    assert config["phases"]["execution"]["executor"] == "shell"


def test_test_echo_scripts_executable():
    source_packs = Path(__file__).parent.parent / "packs"
    scripts_dir = source_packs / "test-echo" / "scripts"
    for script in scripts_dir.iterdir():
        assert os.access(script, os.X_OK), f"{script.name} is not executable"


def test_test_echo_execute_writes_sidecar(tmp_path):
    """The execute script must write a STATUS: done sidecar file."""
    source_packs = Path(__file__).parent.parent / "packs"
    execute = source_packs / "test-echo" / "scripts" / "execute.sh"
    task_file = tmp_path / "t1.plan.md"
    task_file.write_text("# Test Task\nDo the thing.")
    result = subprocess.run(
        [str(execute), str(task_file), str(tmp_path)],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert result.returncode == 0
    sidecar = tmp_path / "t1.status"
    assert sidecar.exists()
    content = sidecar.read_text()
    assert "STATUS: done" in content


# --- Pack distribution ---

def test_distribute_copies_builtin_packs(tmp_path, monkeypatch):
    from switchyard.cli import distribute_builtin_packs
    local_packs = tmp_path / ".switchyard" / "packs"
    monkeypatch.setattr("switchyard.cli.PACKS_DIR", local_packs)
    source_packs = Path(__file__).parent.parent / "packs"
    monkeypatch.setattr("switchyard.cli.BUILTIN_PACKS_DIR", source_packs)
    distribute_builtin_packs()
    assert (local_packs / "test-echo" / "pack.yaml").exists()


def test_distribute_does_not_overwrite_existing(tmp_path, monkeypatch):
    from switchyard.cli import distribute_builtin_packs
    local_packs = tmp_path / ".switchyard" / "packs"
    monkeypatch.setattr("switchyard.cli.PACKS_DIR", local_packs)
    source_packs = Path(__file__).parent.parent / "packs"
    monkeypatch.setattr("switchyard.cli.BUILTIN_PACKS_DIR", source_packs)

    # Pre-create with custom content
    (local_packs / "test-echo").mkdir(parents=True)
    (local_packs / "test-echo" / "pack.yaml").write_text("custom: true")

    distribute_builtin_packs()
    content = (local_packs / "test-echo" / "pack.yaml").read_text()
    assert "custom: true" in content  # NOT overwritten


def test_reset_pack_overwrites(tmp_path, monkeypatch):
    from switchyard.cli import distribute_builtin_packs, reset_pack
    local_packs = tmp_path / ".switchyard" / "packs"
    monkeypatch.setattr("switchyard.cli.PACKS_DIR", local_packs)
    source_packs = Path(__file__).parent.parent / "packs"
    monkeypatch.setattr("switchyard.cli.BUILTIN_PACKS_DIR", source_packs)

    # Pre-create with custom content
    (local_packs / "test-echo").mkdir(parents=True)
    (local_packs / "test-echo" / "pack.yaml").write_text("custom: true")

    reset_pack("test-echo")
    config = yaml.safe_load((local_packs / "test-echo" / "pack.yaml").read_text())
    assert config["name"] == "test-echo"  # factory default restored


# --- CLI argument parsing ---

def test_cli_list_packs(tmp_path, monkeypatch):
    from switchyard.cli import main
    local_packs = tmp_path / ".switchyard" / "packs"
    monkeypatch.setattr("switchyard.cli.PACKS_DIR", local_packs)
    source_packs = Path(__file__).parent.parent / "packs"
    monkeypatch.setattr("switchyard.cli.BUILTIN_PACKS_DIR", source_packs)
    from switchyard.cli import distribute_builtin_packs
    distribute_builtin_packs()

    monkeypatch.setattr("switchyard.pack_loader.PACKS_DIR", local_packs)
    monkeypatch.setattr("sys.argv", ["switchyard", "list-packs"])
    # Should not raise
    try:
        main()
    except SystemExit as e:
        assert e.code in (0, None)


# --- CLI help ---

def test_cli_help():
    from switchyard.cli import main
    import sys
    with pytest.raises(SystemExit) as exc_info:
        sys.argv = ["switchyard", "--help"]
        main()
    assert exc_info.value.code == 0


# --- Entry point is executable ---

def test_entry_point_exists_and_executable():
    entry = Path(__file__).parent.parent / "switchyard"
    assert entry.exists(), "Entry point 'switchyard' must exist at project root"
    assert os.access(entry, os.X_OK), "Entry point must be executable"
```
