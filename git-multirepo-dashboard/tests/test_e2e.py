"""
End-to-end tests using Playwright.

These tests start the real git_dashboard server and exercise it in a real
Chromium browser. They catch rendering errors, broken CDN loads, dead buttons,
and layout issues that unit tests miss entirely.

Run E2E tests only:
    .venv/bin/python -m pytest tests/test_e2e.py -v

Run unit tests only (exclude E2E):
    .venv/bin/python -m pytest tests -v --ignore=tests/test_e2e.py

IMPORTANT: E2E tests must NOT run in the same pytest invocation as unit tests.
Playwright's event loop conflicts with asyncio.run() used by unit tests.

Requires:
    pip install playwright pytest-playwright
    playwright install chromium
"""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

# ── Check playwright is installed ────────────────────────────────────────────
try:
    from playwright.sync_api import expect  # noqa: F401
except ImportError:
    pytest.skip(
        "playwright not installed — run: .venv/bin/pip install playwright pytest-playwright "
        "&& .venv/bin/playwright install chromium",
        allow_module_level=True,
    )

pytestmark = pytest.mark.e2e

PROJECT_ROOT = Path(__file__).parent.parent
GIT_DASHBOARD = PROJECT_ROOT / "git_dashboard.py"


def _find_free_port():
    """Find a free port for the test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port, timeout=10):
    """Wait until the server is accepting connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


@pytest.fixture(scope="module")
def server():
    """Start git_dashboard server on a random port, yield the base URL, then shut down."""
    port = _find_free_port()
    env = dict(os.environ)
    env["GIT_DASHBOARD_NO_BROWSER"] = "1"

    proc = subprocess.Popen(
        [sys.executable, str(GIT_DASHBOARD), "--port", str(port), "--no-browser", "--yes"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if not _wait_for_server(port):
        proc.kill()
        stdout = proc.stdout.read().decode(errors="replace")
        stderr = proc.stderr.read().decode(errors="replace")
        pytest.fail(f"Server failed to start on port {port}.\nstdout: {stdout}\nstderr: {stderr}")

    yield f"http://localhost:{port}"

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ─────────────────────────────────────────────────────────────────────────────
# Basic page load
# ─────────────────────────────────────────────────────────────────────────────

def test_page_loads_without_errors(server, page):
    """Page loads with no JavaScript errors or failed network requests."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    failed_requests = []
    page.on("requestfailed", lambda req: failed_requests.append(
        f"{req.method} {req.url}: {req.failure}"
    ))

    page.goto(server)
    page.wait_for_load_state("networkidle")

    # Filter out expected missing tools (not CDN failures)
    cdn_failures = [r for r in failed_requests if "cdnjs" in r or "unpkg" in r or "fonts" in r]

    assert errors == [], f"JavaScript errors on page load: {errors}"
    assert cdn_failures == [], f"CDN resources failed to load: {cdn_failures}"


def test_react_app_mounts(server, page):
    """React app mounts successfully — the root div has content."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    root = page.locator("#root")
    assert root.inner_html() != "", "React app did not mount — #root is empty"


def test_no_recharts_reference_error(server, page):
    """Recharts loads correctly — no ReferenceError for Recharts global."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(server)
    page.wait_for_load_state("networkidle")

    recharts_errors = [e for e in errors if "Recharts" in e]
    assert recharts_errors == [], f"Recharts failed to load: {recharts_errors}"


# ─────────────────────────────────────────────────────────────────────────────
# Header and navigation
# ─────────────────────────────────────────────────────────────────────────────

def test_header_visible(server, page):
    """The fixed header is visible with the app title."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    header = page.locator("header")
    assert header.is_visible(), "Header is not visible"
    assert "Git Fleet" in header.inner_text()


def test_nav_tabs_visible(server, page):
    """Navigation tabs are visible and clickable."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    nav = page.locator("nav")
    assert nav.is_visible(), "Nav tabs are not visible"

    for tab_name in ["Fleet Overview", "Analytics", "Dependencies"]:
        tab = nav.locator(f"text={tab_name}")
        assert tab.is_visible(), f"Tab '{tab_name}' is not visible"


def test_nav_tab_switching(server, page):
    """Clicking a nav tab changes the hash route."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    analytics_tab = page.locator("nav >> text=Analytics")
    analytics_tab.click()
    page.wait_for_timeout(300)
    assert "#/analytics" in page.url

    fleet_tab = page.locator("nav >> text=Fleet Overview")
    fleet_tab.click()
    page.wait_for_timeout(300)
    assert "#/fleet" in page.url or "#/" == page.url.split(str(server))[-1]


# ─────────────────────────────────────────────────────────────────────────────
# Scan Dir button
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_dir_button_exists_and_clickable(server, page):
    """Scan Dir button is visible in the header and has a click handler."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    scan_dir = page.locator("header >> text=Scan Dir")
    assert scan_dir.is_visible(), "Scan Dir button is not visible"

    # The button should trigger a prompt dialog
    page.on("dialog", lambda dialog: dialog.dismiss())
    scan_dir.click()
    # If we get here without error, the button is wired up


def test_scan_dir_registers_repos(server, page, tmp_path):
    """Scan Dir with a valid path containing git repos registers them."""
    # Create a git repo in tmp_path
    repo = tmp_path / "test_repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        check=True, capture_output=True,
    )

    page.goto(server)
    page.wait_for_load_state("networkidle")

    # Handle the prompt dialog — enter the tmp_path
    page.on("dialog", lambda dialog: dialog.accept(str(tmp_path)))

    scan_dir = page.locator("header >> text=Scan Dir")
    scan_dir.click()

    # Wait for the fleet to refresh and show the repo
    page.wait_for_timeout(1000)

    # The page should now show the registered repo
    body_text = page.locator("body").inner_text()
    assert "test_repo" in body_text, (
        f"Expected 'test_repo' in page after scanning {tmp_path}, got: {body_text[:500]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Full Scan button
# ─────────────────────────────────────────────────────────────────────────────

def test_full_scan_button_visible(server, page):
    """Full Scan button is visible in the header."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    full_scan = page.locator("header >> text=Full Scan")
    assert full_scan.is_visible(), "Full Scan button is not visible"


# ─────────────────────────────────────────────────────────────────────────────
# Tool status banner
# ─────────────────────────────────────────────────────────────────────────────

def test_tool_status_banner_visible_and_dismissible(server, page):
    """If tool status banner shows, it's visible below the nav and can be dismissed."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    # The banner may or may not appear depending on installed tools
    # Wait briefly for it to render
    page.wait_for_timeout(500)

    # Check if banner exists (it contains "not found" text for missing tools)
    banner_dismiss = page.locator("button[aria-label='Dismiss']")
    if banner_dismiss.count() > 0:
        # Banner exists — verify it's visible (not hidden behind header)
        assert banner_dismiss.is_visible(), (
            "Tool status banner dismiss button exists but is not visible — "
            "likely hidden behind the fixed header"
        )

        # Verify banner text is visible too
        banner_text = banner_dismiss.locator("..").locator("div").first
        bbox = banner_text.bounding_box()
        assert bbox is not None, "Banner text has no bounding box"
        # Banner should be below the fixed header+nav (100px)
        assert bbox["y"] >= 90, (
            f"Banner text is at y={bbox['y']}, should be >= 90 (below fixed header+nav)"
        )

        # Click dismiss
        banner_dismiss.click()
        page.wait_for_timeout(300)
        assert banner_dismiss.count() == 0 or not banner_dismiss.is_visible(), \
            "Banner dismiss button still visible after clicking"


# ─────────────────────────────────────────────────────────────────────────────
# Fleet Overview
# ─────────────────────────────────────────────────────────────────────────────

def test_fleet_overview_renders(server, page):
    """Fleet Overview tab renders content (KPI cards or empty state)."""
    page.goto(server)
    page.wait_for_load_state("networkidle")

    main = page.locator("main")
    assert main.is_visible(), "Main content area not visible"

    # Wait for the fleet API call to complete and content to render
    page.wait_for_timeout(2000)

    main_text = main.inner_text()

    # Should show either KPI cards, repo cards, or the empty state message
    has_content = (
        "Total Repos" in main_text
        or "Scan Dir" in main_text
        or "add repositories" in main_text.lower()
        or "No repositories registered" in main_text
        or "repos" in main_text.lower()
    )
    assert has_content, f"Fleet Overview has no recognizable content: {main_text[:500]}"


# ─────────────────────────────────────────────────────────────────────────────
# Analytics tab
# ─────────────────────────────────────────────────────────────────────────────

def test_analytics_tab_renders(server, page):
    """Analytics tab loads without JS errors and shows analytics components."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(server + "#/analytics")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    assert errors == [], f"JavaScript errors on Analytics tab: {errors}"

    main = page.locator("main")
    assert main.is_visible(), "Main content area not visible on Analytics tab"


# ─────────────────────────────────────────────────────────────────────────────
# Dependencies tab
# ─────────────────────────────────────────────────────────────────────────────

def test_dependencies_tab_renders(server, page):
    """Dependencies tab loads without JS errors."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(server + "#/deps")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    assert errors == [], f"JavaScript errors on Dependencies tab: {errors}"


# ─────────────────────────────────────────────────────────────────────────────
# API endpoints (via browser fetch)
# ─────────────────────────────────────────────────────────────────────────────

def test_api_status_returns_json(server, page):
    """/api/status returns valid JSON with tools and version."""
    page.goto(server)
    result = page.evaluate("""
        async () => {
            const r = await fetch('/api/status');
            return { status: r.status, body: await r.json() };
        }
    """)
    assert result["status"] == 200
    assert "tools" in result["body"]
    assert "version" in result["body"]


def test_api_fleet_returns_json(server, page):
    """/api/fleet returns valid JSON with repos and kpis."""
    page.goto(server)
    result = page.evaluate("""
        async () => {
            const r = await fetch('/api/fleet');
            return { status: r.status, body: await r.json() };
        }
    """)
    assert result["status"] == 200
    assert "repos" in result["body"]
    assert "kpis" in result["body"]
