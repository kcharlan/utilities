# Phase 8: Web UI (Embedded React SPA)

## Spec

Build the single-file embedded React 18 SPA that serves as the web UI. All React/JSX, CSS, and Tailwind config are embedded in one HTML string returned by `GET /`. The UI communicates with the backend via REST (`/api/*`) and WebSocket (`/ws`).

### Dependencies from prior phases

- `switchyard/server.py` — All REST endpoints and WebSocket handler from Phase 7. Replace the placeholder `GET /` response with the real SPA.

### Files to create/modify

**`switchyard/html_template.py`** — A single Python file containing `def get_html() -> str:` that returns the complete HTML document as a string.

### CDN dependencies (pinned versions, UMD builds)

Load in `<head>` via `<script>` tags:
- React 18.2.0 (`react.production.min.js`)
- ReactDOM 18.2.0 (`react-dom.production.min.js`)
- Babel Standalone 7.23.9 (`babel.min.js`)
- Tailwind CSS 3.4.1 (`cdn.tailwindcss.com`)
- Lucide React 0.263.1 (UMD)
- React Flow 11.10.1 (UMD)

Google Fonts: Space Grotesk (400,500,600,700), JetBrains Mono (400,500,600), DM Sans (400,500,600,700).

### Design tokens

All CSS custom properties from design doc section 6.3.0 must be defined on `:root`. Every component references tokens — no hardcoded colors, fonts, or sizes. The full token list is in the design doc.

### Background and animations

- Body background: `--bg-base` with subtle radial gradients and SVG noise texture overlay (CSS-only, no image files).
- Define all keyframe animations from the design doc: `pulse-active`, `pulse-error`, `breathe`, `log-slide-in`, `count-bump`, `fade-in-up`, `segment-fill`.
- Page load: staggered `fade-in-up` animation (top bar → pipeline strip → worker cards → task feed).

### Views (React components)

The SPA uses client-side routing (hash-based: `#/monitor`, `#/setup`, `#/history`, `#/settings`, `#/task/:id`, `#/dag`). No React Router library — implement with `window.location.hash` and `useState`.

**`App`** — Root component. Manages routing, WebSocket connection, global state.
- Connects to `ws://<host>/ws` on mount. Handles reconnection on disconnect (retry every 3s).
- Stores session state, pipeline counts, worker states, task list in React state.
- Dispatches WebSocket messages to update state.

**`TopBar`** — Fixed top bar (48px height):
- Left: "COGNITIVE SWITCHYARD" wordmark (Space Grotesk, 700, uppercase, letter-spacing 0.08em).
- Center: Session name + status (or "No active session").
- Right: Nav links (Monitor, Setup, History) + gear icon for Settings. Pause/Resume/Abort controls when session active.

**`PipelineStrip`** — Pipeline flow visualization (44px height):
- Horizontal flow: `Intake(N) → Planning(N) → Staged(N) → Ready(N) → Active(N) → Done(N) | Blocked(N)`.
- Each stage is a badge with count. Count changes trigger `count-bump` animation.
- Blocked badge pulses red when count > 0 (`pulse-error`).
- DAG icon at right end → navigates to `#/dag`.

**`WorkerCard`** — Individual worker slot card:
- Header: slot label, task ID + title, status badge.
- Segmented progress bar (N segments for N phases, current segment animating).
- Detail line: latest freeform progress text.
- Elapsed time counter.
- Log tail: last 5 lines, monospace, `--bg-log` background. New lines animate with `log-slide-in`.
- States: idle (dimmed, `breathe` animation), active (`pulse-active`), problem (`pulse-error` + warning icon).
- Click navigates to `#/task/<task_id>`.

**`MonitorView`** — Main view (`#/monitor`):
- Pipeline strip, worker card grid (2-col for ≤4 workers, 3-col for 5-6), task feed below.
- Task feed: compact list sorted by status priority (blocked → active → ready → done). Each row shows task ID, title, status badge, constraint icons, time.

**`TaskDetailView`** — Full-page task view (`#/task/:id`):
- Left panel (40%): Task metadata, constraints with dependency status dots, plan content (rendered markdown).
- Right panel (60%): Full streaming log (`--bg-log`), progress lines highlighted, error lines in red. Search bar at top. Auto-scroll with "Jump to latest" button when user scrolls up.
- Back button returns to `#/monitor`.

**`DAGView`** — Full-page dependency graph (`#/dag`):
- Uses React Flow v11 to render interactive node graph.
- Custom node component with task ID, title, status badge, status-colored border.
- DEPENDS_ON edges: solid, animated, with arrow markers.
- ANTI_AFFINITY edges: dashed, purple, no markers.
- Anti-affinity group backgrounds as React Flow group nodes.
- Grid pattern background via CSS.
- Back button to `#/monitor`.

**`SetupView`** — Session creation (`#/setup`):
- Centered card (max-width 640px).
- Pack selector dropdown, session name input, worker/planner count steppers.
- Preflight checklist (two-stage: executable bits, then pack prerequisites).
- Intake file list with reveal buttons (calls `/api/sessions/{id}/reveal-file`).
- "Open Folder" button (calls `/api/sessions/{id}/open-intake`).
- Start button (full-width, green, disabled until intake files exist + preflight passes).
- Post-start: intake list becomes read-only with "Session locked" banner.
- Advanced section (collapsible): timeouts, auto-fix toggle, env vars.

**`HistoryView`** — Past sessions (`#/history`):
- Session cards with name, pack badge, stats (done/blocked counts), date/duration.
- Purge controls: trash icon per session (with confirmation), "Purge All" button.
- Empty state: centered "No sessions yet" with Inbox icon.

**`SettingsView`** — Global settings (`#/settings`):
- Retention days, default planner count, default worker count, default pack.
- Save button calls `PUT /api/settings`.

### Markdown rendering

For plan content in TaskDetailView, use a simple inline markdown renderer (parse headers, bold, italic, code blocks, lists). No external markdown library — implement a basic `renderMarkdown(text)` function that converts to React elements.

## Acceptance tests

```python
"""tests/test_phase08_web_ui.py"""
import pytest


def test_html_template_returns_string():
    from switchyard.html_template import get_html
    html = get_html()
    assert isinstance(html, str)
    assert len(html) > 1000  # Non-trivial content


def test_html_contains_react():
    from switchyard.html_template import get_html
    html = get_html()
    assert "react" in html.lower()
    assert "ReactDOM" in html or "react-dom" in html.lower()


def test_html_contains_design_tokens():
    from switchyard.html_template import get_html
    html = get_html()
    assert "--bg-base" in html
    assert "--bg-surface" in html
    assert "--status-done" in html
    assert "--status-blocked" in html
    assert "--font-display" in html
    assert "--font-mono" in html


def test_html_contains_fonts():
    from switchyard.html_template import get_html
    html = get_html()
    assert "Space+Grotesk" in html or "Space Grotesk" in html
    assert "JetBrains+Mono" in html or "JetBrains Mono" in html
    assert "DM+Sans" in html or "DM Sans" in html


def test_html_contains_animations():
    from switchyard.html_template import get_html
    html = get_html()
    assert "pulse-active" in html
    assert "pulse-error" in html
    assert "fade-in-up" in html
    assert "log-slide-in" in html


def test_html_contains_all_views():
    from switchyard.html_template import get_html
    html = get_html()
    # Check for view component names or route markers
    assert "MonitorView" in html or "monitor" in html.lower()
    assert "SetupView" in html or "setup" in html.lower()
    assert "HistoryView" in html or "history" in html.lower()
    assert "SettingsView" in html or "settings" in html.lower()
    assert "TaskDetail" in html or "task-detail" in html.lower()
    assert "DAGView" in html or "dag" in html.lower()


def test_html_contains_websocket_connection():
    from switchyard.html_template import get_html
    html = get_html()
    assert "WebSocket" in html or "websocket" in html.lower()
    assert "/ws" in html


def test_html_contains_cognitive_switchyard_branding():
    from switchyard.html_template import get_html
    html = get_html()
    assert "COGNITIVE SWITCHYARD" in html or "Cognitive Switchyard" in html


def test_html_contains_background_texture():
    from switchyard.html_template import get_html
    html = get_html()
    assert "feTurbulence" in html or "fractalNoise" in html


def test_html_contains_pipeline_stages():
    from switchyard.html_template import get_html
    html = get_html()
    for stage in ["Intake", "Planning", "Ready", "Active", "Done", "Blocked"]:
        assert stage in html or stage.lower() in html.lower()


def test_html_pinned_cdn_versions():
    """CDN URLs should use pinned versions, not @latest."""
    from switchyard.html_template import get_html
    html = get_html()
    assert "@latest" not in html


def test_html_is_valid_document():
    from switchyard.html_template import get_html
    html = get_html()
    assert html.strip().startswith("<!DOCTYPE html>") or html.strip().startswith("<html")
    assert "</html>" in html


def test_server_serves_html(tmp_path, monkeypatch):
    """GET / should return the SPA HTML."""
    import shutil
    from pathlib import Path
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

    src = Path(__file__).parent.parent / "switchyard" / "builtin_packs" / "test-echo"
    if src.exists():
        shutil.copytree(str(src), str(home / "packs" / "test-echo"))

    from switchyard.server import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    client = TestClient(app)

    r = client.get("/")
    assert r.status_code == 200
    assert "COGNITIVE SWITCHYARD" in r.text or "Cognitive Switchyard" in r.text
```
