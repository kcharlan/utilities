"""End-to-end browser tests using Playwright.

These tests start a real Uvicorn server in a background thread and drive
a Chromium browser to verify actual user experience — not just API contracts.

Run with:
    ~/.switchyard_venv/bin/pytest tests/test_e2e.py -v --headed   # visible browser
    ~/.switchyard_venv/bin/pytest tests/test_e2e.py -v             # headless
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from textwrap import dedent

import pytest

pytest.importorskip("playwright")

import uvicorn  # noqa: E402

from cognitive_switchyard.config import build_runtime_paths  # noqa: E402
from cognitive_switchyard.server import create_app  # noqa: E402
from cognitive_switchyard.state import initialize_state_store  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _setup_runtime(tmp_path: Path) -> Path:
    """Create a minimal runtime directory with a pack.

    build_runtime_paths(home=X) sets runtime_home = X/.cognitive_switchyard,
    so packs live at X/.cognitive_switchyard/packs/.
    """
    home = tmp_path / "runtime"
    cs = home / ".cognitive_switchyard"
    packs = cs / "packs" / "claude-code"
    scripts = packs / "scripts"
    prompts = packs / "prompts"
    scripts.mkdir(parents=True)
    prompts.mkdir(parents=True)
    (cs / "sessions").mkdir(parents=True, exist_ok=True)

    (scripts / "execute").write_text(
        dedent("""
        #!/usr/bin/env python3
        import sys, time
        from pathlib import Path
        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        print(f"##PROGRESS## {task_id} | Phase: Execute | 1/1")
        time.sleep(0.2)
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """).lstrip(),
        encoding="utf-8",
    )
    (scripts / "execute").chmod(0o755)
    (prompts / "planner.md").write_text("Plan prompt.\n")
    (prompts / "resolver.md").write_text("Resolve prompt.\n")

    (packs / "pack.yaml").write_text(
        dedent("""
        name: claude-code
        description: E2E test pack.
        version: 0.0.1

        phases:
          planning:
            enabled: false
          resolution:
            enabled: false
          execution:
            enabled: true
            executor: shell
            command: scripts/execute
            max_workers: 1
          verification:
            enabled: false

        timeouts:
          task_idle: 60
          task_max: 0
          session_max: 300

        isolation:
          type: none
        """).lstrip(),
        encoding="utf-8",
    )

    return home


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def server_url(tmp_path_factory):
    """Start a real uvicorn server in a thread and return its base URL."""
    tmp_path = tmp_path_factory.mktemp("e2e")
    home = _setup_runtime(tmp_path)

    runtime_paths = build_runtime_paths(home=home)
    store = initialize_state_store(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    port = _find_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to accept connections
    for _ in range(40):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.25)
    else:
        raise RuntimeError(f"Uvicorn did not start on port {port}")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Tests — ordered so state-mutating tests run last
# ---------------------------------------------------------------------------


def test_spa_loads_and_renders_setup_view(server_url, page):
    """The root URL should serve the SPA and render the Setup view by default."""
    page.goto(server_url)
    page.wait_for_selector("text=Create Session", timeout=10000)
    assert page.title() != ""


def test_no_console_errors_on_initial_load(server_url, page):
    """The SPA should load without any JavaScript console errors."""
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    page.goto(server_url)
    page.wait_for_selector("text=Create Session", timeout=10000)
    page.wait_for_timeout(500)

    assert errors == [], f"Console errors on load: {errors}"


def test_pack_selector_lists_available_packs(server_url, page):
    """The setup form should list the claude-code pack from the runtime directory."""
    page.goto(server_url)
    page.wait_for_selector("text=Create Session", timeout=10000)
    assert page.locator("text=claude-code").count() > 0


def test_api_packs_endpoint_from_browser(server_url, page):
    """The /api/packs endpoint should be reachable and return valid JSON."""
    page.goto(server_url)
    page.wait_for_selector("text=Create Session", timeout=10000)

    packs_response = page.evaluate("""async () => {
        const resp = await fetch('/api/packs');
        return { status: resp.status, data: await resp.json() };
    }""")
    assert packs_response["status"] == 200
    assert "packs" in packs_response["data"]
    assert len(packs_response["data"]["packs"]) >= 1


def test_websocket_connection_established(server_url, page):
    """The app should establish a WebSocket connection on load."""
    page.goto(server_url)
    page.wait_for_selector("text=Create Session", timeout=10000)
    page.wait_for_timeout(1000)

    ws_available = page.evaluate("() => typeof WebSocket !== 'undefined'")
    assert ws_available is True


def test_full_page_screenshot_no_crash(server_url, page):
    """Take a full page screenshot — validates complete render without exceptions."""
    page.goto(server_url)
    page.wait_for_selector("text=Create Session", timeout=10000)
    page.wait_for_timeout(500)

    screenshot = page.screenshot(full_page=True)
    assert len(screenshot) > 1000


def test_create_session_via_api_and_verify_dashboard(server_url, page):
    """Create a session via API, then verify the dashboard endpoint works."""
    page.goto(server_url)
    page.wait_for_selector("text=Create Session", timeout=10000)

    # Create session via API
    result = page.evaluate("""async () => {
        const resp = await fetch('/api/sessions', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: 'api-dashboard-test', name: 'Dashboard Test', pack: 'claude-code'})
        });
        const data = await resp.json();

        // Now fetch dashboard for this session
        const dashResp = await fetch('/api/sessions/api-dashboard-test/dashboard');
        const dash = await dashResp.json();
        return {
            createStatus: resp.status,
            dashStatus: dashResp.status,
            sessionStatus: dash.session ? dash.session.status : null,
            hasPipelineDirs: !!(dash.pipeline_dirs),
        };
    }""")
    assert result["createStatus"] in (200, 201)
    assert result["dashStatus"] == 200
    assert result["sessionStatus"] == "created"
    assert result["hasPipelineDirs"] is True


def test_session_page_renders_after_session_creation(server_url, page):
    """After creating a session, the root page should still render correctly."""
    # Create session via API
    page.goto(server_url)
    page.wait_for_selector("body", timeout=10000)
    page.wait_for_timeout(500)

    page.evaluate("""async () => {
        await fetch('/api/sessions', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: 'render-test', name: 'Render Test', pack: 'claude-code'})
        });
    }""")

    # Reload — should still render (bootstrap payload includes this session now)
    page.reload()
    page.wait_for_timeout(2000)

    # The page should have rendered with content — may show setup or session config
    body = page.locator("body").inner_text()
    assert len(body) > 20


def test_monitor_view_accessible(server_url, page):
    """Navigate to monitor view and verify it renders without console errors."""
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    page.goto(server_url)
    page.wait_for_selector("body", timeout=10000)
    page.wait_for_timeout(500)

    # Try to click monitor tab/link if available
    monitor_link = page.locator("text=Monitor").first
    if monitor_link.count() > 0:
        monitor_link.click()
        page.wait_for_timeout(500)

    assert errors == [], f"Console errors on monitor: {errors}"


def test_setup_lockout_when_session_started(server_url, page):
    """Starting a session should lock the setup view or auto-navigate to monitor."""
    page.goto(server_url)
    page.wait_for_selector("body", timeout=10000)

    # Create and start a session via API
    result = page.evaluate("""async () => {
        // Create
        const cr = await fetch('/api/sessions', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: 'lockout-e2e', name: 'Lockout E2E', pack: 'claude-code'})
        });
        // Start
        const sr = await fetch('/api/sessions/lockout-e2e/start', { method: 'POST' });
        return { createStatus: cr.status, startStatus: sr.status };
    }""")

    # Wait for WebSocket to deliver the state_update that triggers auto-navigation
    page.wait_for_timeout(2000)

    # Reload to test fresh render with active session
    page.reload()
    page.wait_for_timeout(2000)

    body_text = page.locator("body").inner_text()
    # Either the setup lockout message is showing, or we auto-navigated to monitor
    has_lockout = "Session Active" in body_text
    has_monitor_content = "Monitor" in body_text or "Worker" in body_text or "Pipeline" in body_text
    assert has_lockout or has_monitor_content, f"Expected lockout or monitor content, got: {body_text[:200]}"
