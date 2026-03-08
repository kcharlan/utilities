# Phase 2: Pack Loader

## Spec

Build the pack discovery, validation, and hook invocation system. This is the interface between the orchestrator and workload-specific behavior.

### Dependencies from Phase 1

- `switchyard/config.py` — uses `PACKS_DIR` for pack discovery path.

### Files to create

**`switchyard/pack_loader.py`** — Pack discovery, validation, and hook invocation:

**`PackConfig` dataclass:**
```
PackConfig(
    name: str,
    description: str,
    version: str,
    phases: dict,         # Raw phases config from pack.yaml
    auto_fix: dict,       # Raw auto_fix config
    isolation: dict,      # Raw isolation config
    prerequisites: list,  # List of {name: str, check: str}
    timeouts: dict,       # {task_idle, task_max, session_max}
    status: dict,         # {progress_format, sidecar_format}
    pack_dir: Path        # Absolute path to this pack's directory
)
```

**`load_pack(pack_name: str) -> PackConfig`:**
- Resolves `PACKS_DIR / pack_name / pack.yaml`.
- Parses YAML. Validates required fields: `name`, `phases.execution.enabled` must be truthy.
- Applies defaults: `phases.resolution.enabled` → `True`, `phases.planning.enabled` → `False`, `phases.verification.enabled` → `False`, `auto_fix.enabled` → `False`, `auto_fix.max_attempts` → `2`, `timeouts.task_idle` → `300`, `timeouts.task_max` → `0`, `timeouts.session_max` → `14400`, `status.progress_format` → `"##PROGRESS##"`, `status.sidecar_format` → `"key-value"`, `phases.execution.max_workers` → `2`.
- Raises `PackLoadError(message)` on missing pack dir, missing/invalid YAML, or missing required fields.

**`list_packs() -> list[PackConfig]`:**
- Scans `PACKS_DIR` for directories containing `pack.yaml`. Returns loaded configs. Skips dirs without `pack.yaml` (logs warning, does not error).

**`check_executable_bits(pack: PackConfig) -> list[dict]`:**
- Scans `pack.pack_dir / "scripts/"` for all files.
- Returns a list of `{"file": relative_path, "fix": "chmod +x <absolute_path>"}` for each file that lacks the executable bit.
- Returns empty list if all scripts are executable or if `scripts/` doesn't exist.

**`run_preflight(pack: PackConfig) -> list[dict]`:**
- Runs each entry in `pack.prerequisites` by executing the `check` string as a shell command.
- Returns list of `{"name": str, "passed": bool, "output": str}`.
- Each check runs with a 10-second timeout. Timeout = failure.

**`run_hook(pack: PackConfig, hook_name: str, args: list[str], cwd: Optional[str] = None, capture: bool = True) -> subprocess.CompletedProcess`:**
- Resolves the script path from pack config. For hooks the mapping is:
  - `"isolate_start"` → `pack.isolation.get("setup")` or `"scripts/isolate_start"`
  - `"isolate_end"` → `pack.isolation.get("teardown")` or `"scripts/isolate_end"`
  - `"execute"` → `pack.phases["execution"].get("command")` or `"scripts/execute"`
  - `"verify"` → `pack.phases["verification"].get("command")`
  - `"preflight"` → `"scripts/preflight"`
- Constructs the full path: `pack.pack_dir / script_path`.
- Raises `PackLoadError` if the resolved script doesn't exist.
- Calls `subprocess.run([str(script_path)] + args, cwd=cwd, capture_output=capture, text=True)`.
- Does NOT wrap in `bash -c`. Scripts must have shebangs.

**`parse_status_sidecar(path: str) -> dict`:**
- Reads a key-value status sidecar file. Lines are `KEY: value`. Returns dict with uppercase keys.
- Expected keys: `STATUS`, `COMMITS`, `TESTS_RAN`, `TEST_RESULT`, `BLOCKED_REASON`, `NOTES`.
- Unknown keys are preserved. Missing keys get `None`. Malformed lines are skipped.

**`parse_progress_line(line: str, format: str = "##PROGRESS##") -> Optional[dict]`:**
- If `line` contains the progress format string, parses it.
- Phase progress: `##PROGRESS## <task_id> | Phase: <name> | <N>/<total>` → `{"task_id": str, "type": "phase", "phase": str, "current": int, "total": int}`.
- Detail progress: `##PROGRESS## <task_id> | Detail: <message>` → `{"task_id": str, "type": "detail", "detail": str}`.
- Returns `None` if line doesn't match.

**Exception class:** `PackLoadError(Exception)` — raised for any pack loading/validation failure.

## Acceptance tests

```python
"""tests/test_phase02_pack_loader.py"""
import os
import stat
import subprocess
from pathlib import Path

import pytest


def _make_pack(tmp_path, name="test-pack", yaml_content=None, scripts=None):
    """Helper: create a minimal pack directory."""
    pack_dir = tmp_path / "packs" / name
    pack_dir.mkdir(parents=True)
    if yaml_content is None:
        yaml_content = (
            f"name: {name}\ndescription: A test pack\nversion: '0.1.0'\n"
            "phases:\n  execution:\n    enabled: true\n    executor: shell\n"
            "    command: scripts/execute\n    max_workers: 2\n"
        )
    (pack_dir / "pack.yaml").write_text(yaml_content)
    if scripts:
        (pack_dir / "scripts").mkdir(exist_ok=True)
        for sname, content in scripts.items():
            p = pack_dir / "scripts" / sname
            p.write_text(content)
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return pack_dir


@pytest.fixture
def packs_dir(tmp_path, monkeypatch):
    d = tmp_path / "packs"
    d.mkdir()
    from switchyard import config
    monkeypatch.setattr(config, "PACKS_DIR", str(d))
    return d


# --- load_pack ---

def test_load_pack_valid(packs_dir, tmp_path):
    _make_pack(tmp_path, "echo")
    from switchyard.pack_loader import load_pack
    pack = load_pack("echo")
    assert pack.name == "echo"
    assert pack.phases["execution"]["enabled"] is True


def test_load_pack_applies_defaults(packs_dir, tmp_path):
    _make_pack(tmp_path, "echo")
    from switchyard.pack_loader import load_pack
    pack = load_pack("echo")
    assert pack.timeouts["task_idle"] == 300
    assert pack.timeouts["session_max"] == 14400
    assert pack.auto_fix["enabled"] is False


def test_load_pack_missing_dir(packs_dir):
    from switchyard.pack_loader import load_pack, PackLoadError
    with pytest.raises(PackLoadError):
        load_pack("nonexistent")


def test_load_pack_missing_execution(packs_dir, tmp_path):
    _make_pack(tmp_path, "bad", yaml_content="name: bad\nversion: '1'\nphases:\n  planning:\n    enabled: true\n")
    from switchyard.pack_loader import load_pack, PackLoadError
    with pytest.raises(PackLoadError):
        load_pack("bad")


# --- list_packs ---

def test_list_packs_skips_non_pack_dirs(packs_dir, tmp_path):
    _make_pack(tmp_path, "real")
    (packs_dir / "not-a-pack").mkdir()  # no pack.yaml
    from switchyard.pack_loader import list_packs
    packs = list_packs()
    assert len(packs) == 1
    assert packs[0].name == "real"


# --- executable bit check ---

def test_check_executable_bits_all_ok(packs_dir, tmp_path):
    _make_pack(tmp_path, "good", scripts={"run": "#!/bin/bash\necho hi"})
    from switchyard.pack_loader import load_pack, check_executable_bits
    failures = check_executable_bits(load_pack("good"))
    assert failures == []


def test_check_executable_bits_detects_missing(packs_dir, tmp_path):
    pack_dir = _make_pack(tmp_path, "bad", scripts={"run": "#!/bin/bash\necho"})
    # Remove executable bit from one script
    bad_script = pack_dir / "scripts" / "run"
    bad_script.chmod(stat.S_IRUSR | stat.S_IWUSR)
    from switchyard.pack_loader import load_pack, check_executable_bits
    failures = check_executable_bits(load_pack("bad"))
    assert len(failures) == 1
    assert "chmod +x" in failures[0]["fix"]


def test_check_executable_bits_no_scripts_dir(packs_dir, tmp_path):
    _make_pack(tmp_path, "noscripts")
    from switchyard.pack_loader import load_pack, check_executable_bits
    assert check_executable_bits(load_pack("noscripts")) == []


# --- preflight ---

def test_run_preflight_passes(packs_dir, tmp_path):
    yaml = (
        "name: pf\ndescription: test\nversion: '1'\n"
        "phases:\n  execution:\n    enabled: true\n"
        "prerequisites:\n  - name: echo test\n    check: echo hello\n"
    )
    _make_pack(tmp_path, "pf", yaml_content=yaml)
    from switchyard.pack_loader import load_pack, run_preflight
    results = run_preflight(load_pack("pf"))
    assert results[0]["passed"] is True


def test_run_preflight_fails(packs_dir, tmp_path):
    yaml = (
        "name: pf\ndescription: test\nversion: '1'\n"
        "phases:\n  execution:\n    enabled: true\n"
        "prerequisites:\n  - name: bad check\n    check: 'false'\n"
    )
    _make_pack(tmp_path, "pf", yaml_content=yaml)
    from switchyard.pack_loader import load_pack, run_preflight
    results = run_preflight(load_pack("pf"))
    assert results[0]["passed"] is False


# --- run_hook ---

def test_run_hook_captures_output(packs_dir, tmp_path):
    scripts = {"execute": "#!/bin/bash\necho \"hello from hook\""}
    _make_pack(tmp_path, "hooktest", scripts=scripts)
    from switchyard.pack_loader import load_pack, run_hook
    result = run_hook(load_pack("hooktest"), "execute", [])
    assert "hello from hook" in result.stdout


def test_run_hook_missing_script_raises(packs_dir, tmp_path):
    _make_pack(tmp_path, "nohook")
    from switchyard.pack_loader import load_pack, run_hook, PackLoadError
    with pytest.raises(PackLoadError):
        run_hook(load_pack("nohook"), "verify", [])


# --- status sidecar parsing ---

def test_parse_status_sidecar(tmp_path):
    sidecar = tmp_path / "task.status"
    sidecar.write_text(
        "STATUS: done\n"
        "COMMITS: abc123,def456\n"
        "TESTS_RAN: targeted\n"
        "TEST_RESULT: pass\n"
        "NOTES: All good\n"
    )
    from switchyard.pack_loader import parse_status_sidecar
    d = parse_status_sidecar(str(sidecar))
    assert d["STATUS"] == "done"
    assert d["COMMITS"] == "abc123,def456"
    assert d["NOTES"] == "All good"


def test_parse_status_sidecar_malformed_lines(tmp_path):
    sidecar = tmp_path / "task.status"
    sidecar.write_text("STATUS: blocked\ngarbage line\nBLOCKED_REASON: something broke\n")
    from switchyard.pack_loader import parse_status_sidecar
    d = parse_status_sidecar(str(sidecar))
    assert d["STATUS"] == "blocked"
    assert d["BLOCKED_REASON"] == "something broke"


# --- progress line parsing ---

def test_parse_progress_phase():
    from switchyard.pack_loader import parse_progress_line
    r = parse_progress_line("##PROGRESS## 023 | Phase: implementing | 3/5")
    assert r["task_id"] == "023"
    assert r["type"] == "phase"
    assert r["phase"] == "implementing"
    assert r["current"] == 3
    assert r["total"] == 5


def test_parse_progress_detail():
    from switchyard.pack_loader import parse_progress_line
    r = parse_progress_line("##PROGRESS## 023 | Detail: Processing chunk 3/9")
    assert r["type"] == "detail"
    assert r["detail"] == "Processing chunk 3/9"


def test_parse_progress_no_match():
    from switchyard.pack_loader import parse_progress_line
    assert parse_progress_line("just a normal log line") is None
```
