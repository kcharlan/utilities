"""
Shared fixtures for launchmaster tests.

Test categories:
    Unit tests:  pytest tests/ -v --ignore=tests/test_e2e.py
    E2E tests:   pytest tests/test_e2e.py -v
    All:         Run separately (Playwright event loop conflicts with asyncio)
"""

import importlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

import pytest

# ── Enforce UTILITIES_TESTING so browser-opening code is always suppressed ────
# Set it if not already set, so test runs never steal focus.
os.environ["UTILITIES_TESTING"] = "1"

PROJECT_ROOT = Path(__file__).parent.parent
LAUNCHMASTER_SCRIPT = PROJECT_ROOT / "launchmaster"


# ── Import the launchmaster module (extensionless script) ─────────────────────

def _import_launchmaster():
    """Import the launchmaster script as a module for unit testing.

    Must be called AFTER bootstrap has run (i.e., from inside the venv),
    otherwise third-party imports will fail.
    """
    spec = importlib.util.spec_from_file_location("launchmaster", LAUNCHMASTER_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Server fixture for integration/E2E tests ─────────────────────────────────

def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port, timeout=15):
    """Wait until the server responds to /api/health."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            import urllib.request
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2)
            if resp.status == 200:
                return True
        except Exception:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="session")
def server_url():
    """Start launchmaster on a random port with browser suppressed.

    Yields the base URL (e.g., 'http://127.0.0.1:12345').
    Server is killed after the test session.
    """
    port = _find_free_port()

    env = dict(os.environ)
    env["UTILITIES_TESTING"] = "1"

    proc = subprocess.Popen(
        [sys.executable, str(LAUNCHMASTER_SCRIPT), "--port", str(port), "--no-browser"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if not _wait_for_server(port):
        proc.kill()
        stdout = proc.stdout.read().decode(errors="replace")
        stderr = proc.stderr.read().decode(errors="replace")
        pytest.fail(
            f"launchmaster failed to start on port {port}.\n"
            f"stdout: {stdout[:2000]}\nstderr: {stderr[:2000]}"
        )

    yield f"http://127.0.0.1:{port}"

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def api_jobs(server_url) -> list:
    """Fetch all jobs (including Apple) from the running server."""
    import urllib.request
    resp = urllib.request.urlopen(f"{server_url}/api/jobs?include_apple=true")
    return json.loads(resp.read().decode())


@pytest.fixture(scope="session")
def api_jobs_no_apple(server_url) -> list:
    """Fetch non-Apple jobs from the running server."""
    import urllib.request
    resp = urllib.request.urlopen(f"{server_url}/api/jobs?include_apple=false")
    return json.loads(resp.read().decode())


@pytest.fixture(scope="session")
def launchctl_state() -> Dict[str, Dict[str, Any]]:
    """Get the real launchctl list state for comparison."""
    result = subprocess.run(
        ["launchctl", "list"], capture_output=True, text=True, timeout=10
    )
    state = {}
    for line in result.stdout.splitlines()[1:]:  # skip header
        parts = line.split("\t")
        if len(parts) == 3:
            pid_str, status_str, label = parts
            pid = int(pid_str) if pid_str != "-" else None
            last_exit = int(status_str) if status_str != "-" else None
            state[label] = {"pid": pid, "last_exit": last_exit}
    return state


@pytest.fixture(scope="session")
def disabled_labels() -> set:
    """Get the set of explicitly disabled job labels from launchctl."""
    uid = os.getuid()
    disabled = set()
    try:
        result = subprocess.run(
            ["launchctl", "print-disabled", f"gui/{uid}"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if "=>" in line:
                label_part, state_part = line.split("=>", 1)
                label = label_part.strip().strip('"')
                if "disabled" in state_part.lower():
                    disabled.add(label)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return disabled
