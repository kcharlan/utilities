# Phase 6: CLI Entry Point, Self-Bootstrapping, and Test-Echo Pack

## Spec

Build the CLI entry point with self-bootstrapping (auto-venv creation), the test-echo pack for integration testing, and pack distribution (copying built-in packs to `~/.switchyard/packs/`).

### Dependencies from prior phases

- `switchyard/config.py` — `VENV_DIR`, `PACKS_DIR`, `SWITCHYARD_HOME`, `ensure_directories()`, `load_config()`.
- `switchyard/state.py` — `StateStore`, `create_session_dirs()`.
- `switchyard/pack_loader.py` — `load_pack()`, `check_executable_bits()`, `run_preflight()`.
- `switchyard/orchestrator.py` — `Orchestrator`.

### Files to create

**`switchyard/cli.py`** — Entry point and CLI argument parsing:

**`bootstrap()`:**
- Check if running inside the switchyard venv (`sys.prefix` matches `VENV_DIR`).
- If not: create venv at `VENV_DIR` if it doesn't exist (`python3 -m venv`). Install deps: `fastapi`, `uvicorn`, `aiosqlite`, `pyyaml`, `watchfiles`. Re-exec with venv Python via `os.execv()`. Print progress messages during first-time setup.
- If yes: proceed to `main()`.

**`distribute_packs()`:**
- Scans `switchyard/builtin_packs/` (shipped with source) for pack directories.
- For each, copies to `PACKS_DIR/<pack_name>/` if it doesn't already exist there.
- Never overwrites existing user packs.

**`main()`:**
- Calls `ensure_directories()` and `distribute_packs()`.
- Parses CLI arguments with `argparse`:
  - `switchyard start --pack <name> --session <name> [--workers N] [--planners N]` — Create and run a session.
  - `switchyard resume --session <name>` — Resume an existing session (crash recovery + run).
  - `switchyard list-packs` — List available packs.
  - `switchyard validate-pack <path>` — Validate a pack directory (check YAML, executable bits, referenced files exist).
  - `switchyard reset-pack <name>` — Restore a built-in pack to factory default.
  - `switchyard reset-all-packs` — Restore all built-in packs.
  - `switchyard serve [--port N]` — Start the web UI server only (Phase 7).

- **`start` command flow:**
  1. Load pack via `load_pack()`.
  2. Run executable-bit check. If failures, print diagnostic and exit.
  3. Run preflight checks. If failures, print diagnostic and exit.
  4. Generate session ID (UUID4 short form: first 8 chars).
  5. Create session in state store.
  6. Create session directories.
  7. Print intake directory path. Wait for user to populate it (prompt: "Press Enter when intake files are ready").
  8. Scan intake directory, create Task records for each `.md` file.
  9. If pack has planning enabled, run planning phase (future — for now, skip planning, move intake directly to `ready/`).
  10. If pack has resolution enabled, run resolution phase (future — for now, skip resolution, move from `staging/` or `intake/` directly to `ready/`).
  11. Create Orchestrator, call `run()`.

- **`resume` command flow:**
  1. Look up session by name in state store.
  2. Load pack.
  3. Create Orchestrator, call `recover()`, then `run()`.

**`switchyard/builtin_packs/test-echo/`** — Test echo pack:

**`pack.yaml`:**
```yaml
name: test-echo
description: Test pack that echoes task content. For integration testing.
version: "0.1.0"

phases:
  planning:
    enabled: false
  resolution:
    enabled: false
  execution:
    enabled: true
    executor: shell
    command: scripts/execute
    max_workers: 4
  verification:
    enabled: false

auto_fix:
  enabled: false

isolation:
  type: temp-directory
  setup: scripts/isolate_start
  teardown: scripts/isolate_end

prerequisites: []

timeouts:
  task_idle: 30
  task_max: 60
  session_max: 300
```

**`scripts/isolate_start`:**
- Creates a temp directory under `$3/workers/$1/`.
- Prints the path to stdout.

**`scripts/isolate_end`:**
- No-op (exit 0). For temp-directory isolation, nothing to merge.

**`scripts/execute`:**
- Reads the task plan file (`$1`), echoes its content.
- Emits progress: `##PROGRESS## <task_id> | Phase: echoing | 1/1`.
- Writes a status sidecar (`.status` file next to the plan) with `STATUS: done`.
- Sleeps 0.5s to simulate work.

### CLI output format

All CLI output uses plain text, no colors (colors are a future enhancement). Preflight results show as:
```
Preflight checks:
  [PASS] Pack scripts executable
  [PASS] echo test
  [FAIL] missing-tool -- command not found
```

## Acceptance tests

```python
"""tests/test_phase06_cli_bootstrap_testpack.py"""
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def sw_env(tmp_path, monkeypatch):
    """Set up isolated switchyard environment."""
    from switchyard import config
    home = tmp_path / ".switchyard"
    home.mkdir()
    monkeypatch.setattr(config, "SWITCHYARD_HOME", str(home))
    monkeypatch.setattr(config, "PACKS_DIR", str(home / "packs"))
    monkeypatch.setattr(config, "SESSIONS_DIR", str(home / "sessions"))
    monkeypatch.setattr(config, "DB_PATH", str(home / "test.db"))
    monkeypatch.setattr(config, "CONFIG_PATH", str(home / "config.yaml"))
    (home / "packs").mkdir()
    (home / "sessions").mkdir()
    return home


# --- Test-echo pack structure ---

def test_test_echo_pack_exists():
    pack_dir = Path(__file__).parent.parent / "switchyard" / "builtin_packs" / "test-echo"
    assert (pack_dir / "pack.yaml").exists()
    assert (pack_dir / "scripts" / "execute").exists()
    assert (pack_dir / "scripts" / "isolate_start").exists()
    assert (pack_dir / "scripts" / "isolate_end").exists()


def test_test_echo_scripts_are_executable():
    pack_dir = Path(__file__).parent.parent / "switchyard" / "builtin_packs" / "test-echo"
    for script in (pack_dir / "scripts").iterdir():
        assert os.access(str(script), os.X_OK), f"{script.name} is not executable"


def test_test_echo_pack_loads(sw_env):
    """Copy test-echo to packs dir and verify it loads."""
    import shutil
    src = Path(__file__).parent.parent / "switchyard" / "builtin_packs" / "test-echo"
    dst = sw_env / "packs" / "test-echo"
    shutil.copytree(str(src), str(dst))
    from switchyard.pack_loader import load_pack
    pack = load_pack("test-echo")
    assert pack.name == "test-echo"
    assert pack.phases["execution"]["enabled"] is True
    assert pack.timeouts["task_idle"] == 30


# --- Pack distribution ---

def test_distribute_packs_copies_builtin(sw_env):
    from switchyard.cli import distribute_packs
    distribute_packs()
    assert (sw_env / "packs" / "test-echo" / "pack.yaml").exists()


def test_distribute_packs_does_not_overwrite(sw_env):
    from switchyard.cli import distribute_packs
    distribute_packs()
    # Modify the distributed pack
    marker = sw_env / "packs" / "test-echo" / "CUSTOM_MARKER"
    marker.write_text("user customization")
    # Re-distribute
    distribute_packs()
    # User's customization must survive
    assert marker.exists()


# --- Reset pack ---

def test_reset_pack_restores_builtin(sw_env):
    from switchyard.cli import distribute_packs, reset_pack
    distribute_packs()
    # Modify the distributed pack
    yaml_path = sw_env / "packs" / "test-echo" / "pack.yaml"
    yaml_path.write_text("corrupted content")
    # Reset
    reset_pack("test-echo")
    content = yaml_path.read_text()
    assert "test-echo" in content
    assert "corrupted" not in content


# --- Execute script end-to-end ---

def test_echo_execute_script_writes_sidecar(sw_env):
    """Run the execute script directly and verify it writes a status sidecar."""
    import shutil
    src = Path(__file__).parent.parent / "switchyard" / "builtin_packs" / "test-echo"
    dst = sw_env / "packs" / "test-echo"
    shutil.copytree(str(src), str(dst))

    # Create workspace with a task file
    workspace = sw_env / "workspace"
    workspace.mkdir()
    plan = workspace / "001.plan.md"
    plan.write_text("# Task 001\nEcho this content\n")

    execute = dst / "scripts" / "execute"
    result = subprocess.run(
        [str(execute), str(plan), str(workspace)],
        cwd=str(workspace), capture_output=True, text=True, timeout=10)

    assert result.returncode == 0
    assert "##PROGRESS##" in result.stdout

    sidecar = workspace / "001.status"
    assert sidecar.exists()
    content = sidecar.read_text()
    assert "STATUS: done" in content


# --- CLI argument parsing ---

def test_cli_list_packs(sw_env):
    from switchyard.cli import distribute_packs, main
    distribute_packs()
    # We can't easily test the full main() with argparse without subprocess,
    # but we can test the list_packs output function
    from switchyard.pack_loader import list_packs
    packs = list_packs()
    names = [p.name for p in packs]
    assert "test-echo" in names


# --- Validate pack ---

def test_validate_pack_catches_missing_yaml(sw_env):
    bad_dir = sw_env / "packs" / "bad-pack"
    bad_dir.mkdir()
    from switchyard.pack_loader import load_pack, PackLoadError
    with pytest.raises(PackLoadError):
        load_pack("bad-pack")


# --- Integration: start flow (minimal, no interactive prompt) ---

def test_start_creates_session_and_tasks(sw_env):
    """Test the session creation part of the start flow."""
    from switchyard.cli import distribute_packs
    from switchyard.state import StateStore, create_session_dirs
    from switchyard.pack_loader import load_pack
    from switchyard.models import Session, Task

    distribute_packs()
    store = StateStore(str(sw_env / "test.db"))
    try:
        pack = load_pack("test-echo")
        session = Session(id="s1", name="test-run", pack="test-echo",
                          status="created", config={},
                          created_at="2026-01-01T00:00:00Z")
        store.create_session(session)
        session_dir = create_session_dirs("s1")

        # Add intake files
        (session_dir / "intake" / "001.md").write_text("# Task 1\nDo thing 1\n")
        (session_dir / "intake" / "002.md").write_text("# Task 2\nDo thing 2\n")

        # Scan intake and create tasks (this is what the start command does)
        intake_files = sorted((session_dir / "intake").glob("*.md"))
        assert len(intake_files) == 2
    finally:
        store.close()
```
