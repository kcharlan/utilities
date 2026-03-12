from __future__ import annotations

from textwrap import dedent

from cognitive_switchyard.html_template import render_app_html


def test_render_app_html_pins_required_react18_tailwind_lucide_and_reactflow_cdns() -> None:
    html = render_app_html({"ok": True})

    assert "https://unpkg.com/react@18.3.1/umd/react.development.js" in html
    assert "https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js" in html
    assert "https://unpkg.com/@babel/standalone@7.28.4/babel.min.js" in html
    assert "https://unpkg.com/lucide@0.542.0/dist/umd/lucide.min.js" in html
    assert "https://unpkg.com/reactflow@11.11.4/dist/umd/index.js" in html
    assert "https://unpkg.com/reactflow@11.11.4/dist/style.css" in html


def test_render_app_html_includes_required_google_fonts_import_and_design_token_block() -> None:
    html = render_app_html({"ok": True})

    assert '<link rel="preconnect" href="https://fonts.googleapis.com">' in html
    assert '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>' in html
    assert (
        '<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">'
        in html
    )
    assert (
        dedent(
            """
            :root {
              /* === Background === */
              --bg-base: #0f1117;           /* Main page background - very dark blue-gray */
              --bg-surface: #161922;        /* Card/panel backgrounds */
              --bg-surface-raised: #1c1f2e; /* Elevated surfaces (modals, dropdowns) */
              --bg-surface-hover: #232738;  /* Hover state on interactive surfaces */
              --bg-input: #0c0e14;          /* Input field backgrounds */
              --bg-log: #0a0c10;            /* Log viewer background (darkest) */

              /* === Text === */
              --text-primary: #e8eaed;      /* Primary text - slightly warm white */
              --text-secondary: #8b8fa3;    /* Secondary/dimmed text */
              --text-muted: #4a4e63;        /* Very dimmed text (idle labels, timestamps) */
              --text-inverse: #0f1117;      /* Text on bright backgrounds */

              /* === Status Colors === */
              --status-done: #34d399;       /* Green - completed/healthy */
              --status-active: #f59e0b;     /* Amber - in progress */
              --status-ready: #3b82f6;      /* Blue - queued/ready */
              --status-blocked: #ef4444;    /* Red - error/blocked */
              --status-staged: #a78bfa;     /* Purple - staged/planning */
              --status-idle: #374151;       /* Dark gray - idle/inactive */
              --status-review: #f97316;     /* Orange - needs human review */

              /* === Status Glows (for box-shadow) === */
              --glow-done: rgba(52, 211, 153, 0.15);
              --glow-active: rgba(245, 158, 11, 0.15);
              --glow-blocked: rgba(239, 68, 68, 0.25);
              --glow-ready: rgba(59, 130, 246, 0.1);

              /* === Borders === */
              --border-subtle: #1e2231;     /* Default card/panel borders */
              --border-medium: #2a2f42;     /* Stronger separation */
              --border-focus: #3b82f6;      /* Focus ring color */

              /* === Typography === */
              --font-display: 'Space Grotesk', 'DM Sans', sans-serif;    /* Headers, labels */
              --font-mono: 'JetBrains Mono', 'IBM Plex Mono', monospace; /* Data, logs, IDs */
              --font-body: 'DM Sans', 'Space Grotesk', sans-serif;       /* Body text */

              /* === Font Sizes === */
              --text-xs: 0.6875rem;    /* 11px - timestamps, fine print */
              --text-sm: 0.75rem;      /* 12px - secondary labels */
              --text-base: 0.8125rem;  /* 13px - body text (dense UI) */
              --text-md: 0.875rem;     /* 14px - primary labels */
              --text-lg: 1rem;         /* 16px - section headers */
              --text-xl: 1.25rem;      /* 20px - page headers */
              --text-2xl: 1.5rem;      /* 24px - view titles */

              /* === Spacing === */
              --space-1: 4px;
              --space-2: 8px;
              --space-3: 12px;
              --space-4: 16px;
              --space-5: 20px;
              --space-6: 24px;
              --space-8: 32px;

              /* === Border Radius === */
              --radius-sm: 4px;
              --radius-md: 6px;
              --radius-lg: 8px;
              --radius-xl: 12px;

              /* === Transitions === */
              --transition-fast: 150ms ease;
              --transition-base: 250ms ease;
              --transition-slow: 400ms ease;

              /* === Z-index layers === */
              --z-base: 0;
              --z-cards: 10;
              --z-sticky: 20;
              --z-overlay: 30;
              --z-modal: 40;
              --z-tooltip: 50;

              /* === Layout === */
              --topbar-height: 48px;
              --pipeline-strip-height: 44px;
              --worker-card-min-height: 220px;
              --log-tail-lines: 5;          /* Number of visible lines in worker card log tail */
              --sidebar-width: 280px;       /* For views that use sidebar layout */
            }
            """
        ).strip()
        in html
    )


def test_render_app_html_escapes_bootstrap_json_for_inline_use() -> None:
    html = render_app_html(
        {
            "danger": "</script><script>alert('xss')</script>",
            "ampersand": "A&B",
        }
    )

    assert "</script><script>alert('xss')</script>" not in html
    assert "\\u003c/script\\u003e\\u003cscript\\u003ealert('xss')\\u003c/script\\u003e" in html
    assert "A\\u0026B" in html


def test_render_app_html_uses_valid_single_brace_css_and_react_syntax() -> None:
    html = render_app_html({"ok": True})

    assert "body {" in html
    assert "const { useEffect, useMemo, useRef, useState } = React;" in html
    assert "body {{" not in html
    assert "const {{ useEffect, useMemo, useRef, useState }} = React;" not in html
    assert "window.location.reload" not in html


def test_render_app_html_wires_setup_monitor_and_log_stream_contracts() -> None:
    html = render_app_html({"ok": True})

    assert 'type: "subscribe_logs"' in html
    assert 'type: "unsubscribe_logs"' in html
    assert "/api/sessions/${sessionId}/dashboard" in html
    assert "/api/sessions/${sessionId}/tasks" in html
    assert "/api/sessions/${sessionId}/intake" in html
    assert "/api/sessions/${sessionId}/preflight" in html
    assert "/api/sessions/${currentSession.id}/tasks/${taskId}/log?offset=0&limit=400" in html
    assert "/api/sessions/${currentSession.id}/open-intake" in html
    assert "/api/sessions/${currentSession.id}/reveal-file?path=${encodeURIComponent(path)}" in html
    assert "Create Session" in html
    assert "Run Preflight" in html
    assert "Start Session" in html
    assert "Pause" in html
    assert "Resume" in html
    assert "Abort" in html


def test_history_view_opens_trimmed_completed_session_without_requesting_live_task_log_streams() -> None:
    html = render_app_html({"ok": True})

    assert 'async function loadHistorySession(sessionId)' in html
    assert 'requestJson(`/api/sessions/${sessionId}`)' in html
    assert 'requestJson(`/api/sessions/${sessionId}/tasks`)' in html
    assert 'setView("history")' in html
    assert 'await loadHistorySession(session.id);' in html
    assert 'await loadSessionData(session.id, { includePreflight: session.status === "created" });' not in html
    assert 'const protocol = window.location.protocol === "https:" ? "wss" : "ws";' in html


def test_history_view_renders_release_notes_panel_for_completed_session_detail() -> None:
    html = render_app_html({"ok": True})

    assert "Release Notes" in html
    assert "selectedSession?.release_notes?.content" in html
    assert "selectedSession.release_notes.content" in html


def test_pause_button_visible_for_all_active_statuses_not_gated_on_running_only() -> None:
    """Regression: pause button must show during planning/resolving, not just running."""
    html = render_app_html({"ok": True})

    # The pause condition must include planning and resolving, not just running
    assert (
        '["planning", "resolving", "running", "verifying", "auto_fixing"].includes(currentSession?.status)'
        in html
    )
    # The old gating condition must NOT appear
    assert 'currentSession?.status === "running"' not in html
    # The resume button must be gated on paused only (not verifying/auto_fixing)
    assert 'currentSession?.status === "paused"' in html


def test_verification_card_reads_auto_fix_max_attempts_from_nested_path() -> None:
    """Regression: effectiveConfig.auto_fix_max_attempts (flat) was undefined; must use nested path."""
    html = render_app_html({"ok": True})

    # Must use the nested read that matches to_dict()'s "auto_fix.max_attempts" structure
    assert "effectiveConfig.auto_fix?.max_attempts" in html
    # Must NOT use the flat key that evaluates to undefined
    assert "effectiveConfig.auto_fix_max_attempts" not in html


def test_task_detail_view_contains_timing_field_labels_and_elapsed_field_component() -> None:
    html = render_app_html({"ok": True})

    # Static labels rendered as JSX literals
    assert 'field-label">Started' in html
    assert 'field-label">Completed' in html
    # ElapsedField renders label dynamically; verify the string literals exist in the component
    assert '"Elapsed"' in html
    assert '"Duration"' in html
    # The ElapsedField component definition is present
    assert "function ElapsedField" in html


def test_task_row_renders_fta_badge_for_full_test_after_tasks() -> None:
    """Regression: task rows must display FTA badge when full_test_after is true."""
    html = render_app_html({"ok": True})

    # FTA badge text and its tooltip title attribute must appear in the task row rendering code
    assert ">FTA<" in html, "FTA badge text must be present in task row JSX"
    assert 'title="Full test after completion"' in html, (
        "FTA badge must have a descriptive title attribute for tooltip"
    )
    # Badge is conditional on task.full_test_after — the condition must be present
    assert "task.full_test_after" in html, (
        "FTA badge must be gated on task.full_test_after flag"
    )


def test_verification_countdown_uses_shared_reason_label_helper() -> None:
    """Regression: verification countdown must use verificationReasonLabel helper, not inline chain."""
    html = render_app_html({"ok": True})

    # The shared helper function must be defined
    assert "function verificationReasonLabel" in html, (
        "verificationReasonLabel helper must be defined as a standalone function"
    )
    # The countdown section must call it for the pending-state display
    assert "verificationReasonLabel(runtimeState.verification_reason)" in html, (
        "Countdown section must call verificationReasonLabel to show pending reason"
    )
    # The VerificationCard must also use it (no inline ternary chain left)
    assert "verificationReasonLabel(reason)" in html, (
        "VerificationCard must call verificationReasonLabel instead of inlining the ternary chain"
    )
