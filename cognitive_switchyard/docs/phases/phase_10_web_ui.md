# Phase 10: Embedded React SPA

**Design doc:** `docs/cognitive_switchyard_design.md` (Sections 6.1–6.4)

## Spec

Build the single-file embedded React 18 SPA served by the FastAPI backend. All HTML, CSS, and JSX are in one Python string returned by `get_html()`. The SPA communicates with the backend via `fetch()` to `/api/*` and WebSocket to `/ws`.

### Files to create

- `switchyard/html_template.py` — Contains `get_html() -> str` returning the complete HTML document.

### Dependencies from prior phases

- `switchyard/server.py` — `GET /` calls `get_html()` and returns it as `text/html`. All `/api/*` and `/ws` endpoints are already implemented.

### Technology stack (all CDN-loaded, no npm)

- React 18, ReactDOM 18 (UMD from unpkg, pinned versions)
- Babel Standalone (for JSX transform in browser)
- Tailwind CSS (CDN)
- Lucide Icons (UMD from unpkg)
- React Flow v11 (UMD from unpkg, pinned — NOT v12 which requires React 19)
- Google Fonts: Space Grotesk, JetBrains Mono, DM Sans

### Design tokens

All CSS custom properties from design doc Section 6.3.0 must be defined on `:root`. These include background colors (`--bg-base` through `--bg-log`), text colors, status colors, status glows, borders, typography (font families, sizes), spacing, border-radius, transitions, z-index layers, and layout constants.

### Background texture

Apply the radial gradients and SVG noise texture from Section 6.3.0.2 to `body`.

### Animation keyframes

Define all keyframes from Section 6.3.0.3: `pulse-active`, `pulse-error`, `breathe`, `log-slide-in`, `count-bump`, `fade-in-up`, `segment-fill`.

### React components (5 views)

The SPA uses client-side routing (hash-based: `#/`, `#/monitor`, `#/task/:id`, `#/dag`, `#/history`, `#/settings`).

1. **TopBar** — Fixed top bar with logo "COGNITIVE SWITCHYARD", session info, nav links (Monitor, Setup, History, Settings gear icon), and session controls (Pause/Resume/Abort).

2. **SetupView** (`#/` when no active session) — Pack selector dropdown, session name input, worker/planner count steppers, preflight checklist, intake file list with live-updating entries, Start button (disabled until intake has files and preflight passes), Advanced collapsible section for config overrides.

3. **MonitorView** (`#/monitor`) — Three zones:
   - Pipeline flow strip showing stage counts with animated transitions
   - Worker cards grid (2-col for 2-4 workers, 3-col for 5-6) with slot label, task info, progress bar, detail line, elapsed time, log tail (5 lines)
   - Task feed below: compact row list sorted blocked→active→ready→done

4. **TaskDetailView** (`#/task/:id`) — Two-column layout: left (40%) shows task metadata, constraints, plan content; right (60%) shows full streaming log with search bar and auto-scroll.

5. **DAGView** (`#/dag`) — React Flow v11 interactive graph. Nodes colored by status, edges for DEPENDS_ON (solid arrow) and ANTI_AFFINITY (dashed). Anti-affinity groups as background regions.

6. **HistoryView** (`#/history`) — Past session cards with name, pack, date, duration, task stats. Purge controls per session and purge-all.

7. **SettingsView** (`#/settings`) — Retention days, default planners, default workers, default pack.

### WebSocket integration

On mount, connect to `ws://localhost:${location.port}/ws`. Handle message types: `state_update`, `log_line`, `task_status_change`, `progress_detail`, `alert`. Send `subscribe_logs`/`unsubscribe_logs` when entering/leaving task detail or monitor view.

### Component specifications

Follow the exact pixel specs from design doc Section 6.3.0.4: TopBar (48px height), Pipeline Flow Strip (44px), Worker Card (220px min-height, specific card header/progress bar/log tail specs), Task Feed Row (36px height), etc.

### Page load animation

Staggered `fade-in-up` animation on MonitorView load: TopBar 0ms, Pipeline strip 80ms, Worker cards 160ms+60ms stagger, Task feed 320ms.

## Acceptance tests

```python
# tests/test_phase10_web_ui.py
import pytest

from switchyard.html_template import get_html


@pytest.fixture
def html():
    return get_html()


# --- HTML structure ---

def test_html_is_valid_document(html):
    assert html.startswith("<!DOCTYPE html>") or html.startswith("<!doctype html>")
    assert "</html>" in html


def test_html_contains_react_root(html):
    assert 'id="root"' in html


# --- CDN dependencies ---

def test_cdn_react_18_loaded(html):
    assert "react@18" in html or "react/18" in html
    assert "react-dom@18" in html or "react-dom/18" in html


def test_cdn_babel_standalone(html):
    assert "babel-standalone" in html or "babel/standalone" in html


def test_cdn_react_flow_v11(html):
    """Must use React Flow v11 (NOT v12 which requires React 19)."""
    assert "reactflow" in html.lower() or "react-flow" in html.lower()
    # Must NOT reference v12+
    assert "@12" not in html or "reactflow@12" not in html


def test_cdn_lucide_icons(html):
    assert "lucide" in html.lower()


# --- Google Fonts ---

def test_google_fonts_loaded(html):
    assert "fonts.googleapis.com" in html
    assert "Space+Grotesk" in html or "Space Grotesk" in html
    assert "JetBrains+Mono" in html or "JetBrains Mono" in html
    assert "DM+Sans" in html or "DM Sans" in html


# --- Design tokens (CSS custom properties) ---

def test_design_tokens_defined(html):
    required_tokens = [
        "--bg-base", "--bg-surface", "--bg-surface-raised", "--bg-log",
        "--text-primary", "--text-secondary", "--text-muted",
        "--status-done", "--status-active", "--status-ready", "--status-blocked",
        "--font-display", "--font-mono", "--font-body",
        "--topbar-height", "--pipeline-strip-height",
    ]
    for token in required_tokens:
        assert token in html, f"Missing design token: {token}"


# --- Background texture ---

def test_background_noise_texture(html):
    assert "feTurbulence" in html  # SVG noise filter


# --- Animation keyframes ---

def test_animation_keyframes_defined(html):
    required_keyframes = [
        "pulse-active", "pulse-error", "breathe",
        "log-slide-in", "count-bump", "fade-in-up",
    ]
    for kf in required_keyframes:
        assert kf in html, f"Missing keyframe: {kf}"


# --- React components ---

def test_components_exist(html):
    """Each major view component must be defined."""
    required_components = [
        "TopBar", "SetupView", "MonitorView", "TaskDetailView",
        "DAGView", "HistoryView", "SettingsView",
    ]
    for comp in required_components:
        assert comp in html, f"Missing component: {comp}"


# --- WebSocket integration ---

def test_websocket_connection_code(html):
    assert "/ws" in html
    assert "subscribe_logs" in html
    assert "unsubscribe_logs" in html


# --- API integration ---

def test_api_endpoint_references(html):
    """The SPA must reference the API endpoints it needs."""
    required_paths = [
        "/api/packs", "/api/sessions", "/api/settings",
    ]
    for path in required_paths:
        assert path in html, f"Missing API reference: {path}"


# --- Navigation ---

def test_hash_routing(html):
    """SPA uses hash-based routing."""
    assert "#/monitor" in html or "monitor" in html
    assert "#/history" in html or "history" in html
    assert "#/settings" in html or "settings" in html


# --- Branding ---

def test_logo_text(html):
    assert "COGNITIVE SWITCHYARD" in html


# --- Worker card specs ---

def test_worker_card_log_tail_reference(html):
    """Worker cards must show log tail output."""
    assert "log-slide-in" in html  # animation for new log lines
    assert "--log-tail-lines" in html  # design token for visible lines


# --- Pipeline strip ---

def test_pipeline_stage_names(html):
    """Pipeline strip must show all stage names."""
    stages = ["Intake", "Planning", "Staged", "Ready", "Active", "Done", "Blocked"]
    # At least the key stages should be referenced
    found = sum(1 for s in stages if s in html or s.lower() in html)
    assert found >= 5, f"Only found {found}/7 pipeline stages in HTML"
```
