from __future__ import annotations


def get_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Cognitive Switchyard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script>
      tailwind = {
        config: {
          theme: {
            extend: {
              boxShadow: {
                panel: "0 20px 60px rgba(0, 0, 0, 0.32)",
              },
            },
          },
        },
      };
    </script>
    <script src="https://cdn.tailwindcss.com"></script>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <script src="https://unpkg.com/reactflow@11/dist/umd/index.js"></script>
    <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
    <style>
      :root {
        --bg-base: #0f1117;
        --bg-surface: #161922;
        --bg-surface-raised: #1c1f2e;
        --bg-surface-hover: #232738;
        --bg-input: #0c0e14;
        --bg-log: #0a0c10;
        --text-primary: #e8eaed;
        --text-secondary: #8b8fa3;
        --text-muted: #4a4e63;
        --text-inverse: #0f1117;
        --status-done: #34d399;
        --status-active: #f59e0b;
        --status-ready: #3b82f6;
        --status-blocked: #ef4444;
        --status-staged: #a78bfa;
        --status-idle: #374151;
        --status-review: #f97316;
        --glow-done: rgba(52, 211, 153, 0.15);
        --glow-active: rgba(245, 158, 11, 0.15);
        --glow-blocked: rgba(239, 68, 68, 0.25);
        --glow-ready: rgba(59, 130, 246, 0.1);
        --border-subtle: #1e2231;
        --border-medium: #2a2f42;
        --border-focus: #3b82f6;
        --font-display: "Space Grotesk", "DM Sans", sans-serif;
        --font-mono: "JetBrains Mono", "IBM Plex Mono", monospace;
        --font-body: "DM Sans", "Space Grotesk", sans-serif;
        --text-xs: 0.6875rem;
        --text-sm: 0.75rem;
        --text-base: 0.8125rem;
        --text-md: 0.875rem;
        --text-lg: 1rem;
        --text-xl: 1.25rem;
        --text-2xl: 1.5rem;
        --space-1: 4px;
        --space-2: 8px;
        --space-3: 12px;
        --space-4: 16px;
        --space-5: 20px;
        --space-6: 24px;
        --space-8: 32px;
        --radius-sm: 4px;
        --radius-md: 6px;
        --radius-lg: 8px;
        --radius-xl: 12px;
        --transition-fast: 150ms ease;
        --transition-base: 250ms ease;
        --transition-slow: 400ms ease;
        --z-sticky: 20;
        --topbar-height: 48px;
        --pipeline-strip-height: 44px;
        --worker-card-min-height: 220px;
        --sidebar-width: 280px;
      }
      * { box-sizing: border-box; }
      html, body, #root { min-height: 100%; }
      body {
        margin: 0;
        background-color: var(--bg-base);
        background-image:
          radial-gradient(ellipse at 20% 50%, rgba(59, 130, 246, 0.03) 0%, transparent 50%),
          radial-gradient(ellipse at 80% 20%, rgba(245, 158, 11, 0.025) 0%, transparent 40%);
        color: var(--text-primary);
        font-family: var(--font-body);
      }
      body::before {
        content: "";
        position: fixed;
        inset: 0;
        opacity: 0.025;
        background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
        pointer-events: none;
        z-index: -1;
      }
      .font-display { font-family: var(--font-display); }
      .font-mono { font-family: var(--font-mono); }
      .panel {
        background: linear-gradient(180deg, rgba(28, 31, 46, 0.98), rgba(18, 20, 30, 0.98));
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-xl);
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.32);
      }
      .surface {
        background: var(--bg-surface);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-lg);
      }
      .input {
        width: 100%;
        background: var(--bg-input);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-md);
        color: var(--text-primary);
        font-family: var(--font-mono);
        font-size: var(--text-base);
        padding: 10px 12px;
        outline: none;
      }
      .input:focus {
        border-color: var(--border-focus);
        box-shadow: 0 0 0 1px var(--border-focus);
      }
      .btn {
        border-radius: var(--radius-md);
        border: 1px solid transparent;
        font-family: var(--font-display);
        font-size: var(--text-sm);
        font-weight: 700;
        letter-spacing: 0.04em;
        padding: 10px 14px;
        transition: var(--transition-fast);
        text-transform: uppercase;
      }
      .btn:hover { filter: brightness(1.08); }
      .btn:disabled { opacity: 0.35; cursor: not-allowed; filter: none; }
      .btn-primary { background: var(--status-done); color: var(--text-inverse); }
      .btn-secondary { background: transparent; border-color: var(--border-medium); color: var(--text-primary); }
      .btn-danger { background: transparent; border-color: var(--status-blocked); color: var(--status-blocked); }
      .btn-danger:hover { background: var(--status-blocked); color: white; }
      .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        border-radius: 999px;
        padding: 2px 8px;
        font-family: var(--font-mono);
        font-size: var(--text-xs);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
      }
      .fade-up {
        opacity: 0;
        animation: fade-in-up 400ms ease forwards;
      }
      .grid-bg {
        background-image:
          linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
        background-size: 40px 40px;
      }
      @keyframes pulse-active {
        0%, 100% { box-shadow: 0 0 0 1px var(--status-active), 0 0 8px var(--glow-active); }
        50% { box-shadow: 0 0 0 1px var(--status-active), 0 0 16px var(--glow-active); }
      }
      @keyframes pulse-error {
        0%, 100% { box-shadow: 0 0 0 2px var(--status-blocked), 0 0 12px var(--glow-blocked); }
        50% { box-shadow: 0 0 0 2px var(--status-blocked), 0 0 24px var(--glow-blocked); }
      }
      @keyframes breathe {
        0%, 100% { opacity: 0.4; }
        50% { opacity: 0.6; }
      }
      @keyframes log-slide-in {
        from { opacity: 0; transform: translateY(4px); }
        to { opacity: 1; transform: translateY(0); }
      }
      @keyframes fade-in-up {
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
      }
      .log-line {
        animation: log-slide-in 200ms ease;
      }
      .worker-idle {
        opacity: 0.6;
        animation: breathe 4s ease-in-out infinite;
      }
      .worker-active {
        animation: pulse-active 3s ease-in-out infinite;
      }
      .worker-problem {
        animation: pulse-error 1.5s ease-in-out infinite;
      }
      .markdown h1, .markdown h2, .markdown h3 {
        font-family: var(--font-display);
        margin: 1rem 0 0.5rem;
      }
      .markdown p, .markdown li {
        color: var(--text-secondary);
        line-height: 1.6;
        font-size: var(--text-base);
      }
      .markdown pre, .markdown code {
        font-family: var(--font-mono);
      }
      .scrollbar-thin::-webkit-scrollbar { width: 8px; height: 8px; }
      .scrollbar-thin::-webkit-scrollbar-thumb {
        background: var(--border-medium);
        border-radius: 999px;
      }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script type="text/babel">
      const { useEffect, useRef, useState } = React;

      const STATUS_COLORS = {
        created: "var(--status-idle)",
        planning: "var(--status-staged)",
        staged: "var(--status-staged)",
        review: "var(--status-review)",
        ready: "var(--status-ready)",
        active: "var(--status-active)",
        running: "var(--status-active)",
        verifying: "var(--status-active)",
        done: "var(--status-done)",
        completed: "var(--status-done)",
        blocked: "var(--status-blocked)",
        aborted: "var(--status-blocked)",
        paused: "var(--status-review)",
        idle: "var(--status-idle)",
      };

      function api(path, options = {}) {
        return fetch(path, {
          headers: { "Content-Type": "application/json", ...(options.headers || {}) },
          ...options,
        }).then(async (response) => {
          if (!response.ok) {
            const detail = await response.text();
            throw new Error(detail || `Request failed: ${response.status}`);
          }
          if (response.status === 204) {
            return null;
          }
          const contentType = response.headers.get("content-type") || "";
          return contentType.includes("application/json") ? response.json() : response.text();
        });
      }

      function formatDuration(seconds) {
        const total = Math.max(0, Math.floor(seconds || 0));
        const hrs = Math.floor(total / 3600);
        const mins = Math.floor((total % 3600) / 60);
        const secs = total % 60;
        if (hrs > 0) return `${hrs}h ${mins}m`;
        if (mins > 0) return `${mins}m ${secs}s`;
        return `${secs}s`;
      }

      function formatTimestamp(value) {
        if (!value) return "n/a";
        try {
          return new Date(value).toLocaleString();
        } catch (err) {
          return value;
        }
      }

      function statusColor(status) {
        return STATUS_COLORS[status] || "var(--text-secondary)";
      }

      function sortTasks(tasks) {
        const rank = { blocked: 0, active: 1, ready: 2, planning: 3, staged: 4, review: 5, done: 6 };
        return [...tasks].sort((a, b) => {
          const rankDiff = (rank[a.status] ?? 99) - (rank[b.status] ?? 99);
          if (rankDiff !== 0) return rankDiff;
          return a.id.localeCompare(b.id);
        });
      }

      function StatusPill({ status, children }) {
        const color = statusColor(status);
        return (
          <span
            className="status-pill"
            style={{ background: `${color}22`, color, border: `1px solid ${color}33` }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: 999,
                background: color,
                display: "inline-block",
              }}
            />
            {children || status}
          </span>
        );
      }

      function Icon({ path, size = 16, stroke = "currentColor" }) {
        return (
          <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            {path.map((d, index) => <path key={index} d={d} />)}
          </svg>
        );
      }

      const ICONS = {
        folder: ["M3 6h5l2 2h11v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z", "M3 6a2 2 0 0 1 2-2h3l2 2"],
        branch: ["M6 3v12", "M18 9V3", "M6 15a3 3 0 1 0 0 6a3 3 0 0 0 0-6z", "M18 3a3 3 0 1 0 0 6a3 3 0 0 0 0-6z", "M9 18h6a3 3 0 0 0 3-3V9"],
        arrowLeft: ["M19 12H5", "M12 19l-7-7l7-7"],
        trash: ["M3 6h18", "M8 6V4h8v2", "M19 6l-1 14H6L5 6", "M10 11v6", "M14 11v6"],
        pause: ["M8 5v14", "M16 5v14"],
        play: ["M8 5l11 7l-11 7z"],
        alert: ["M12 9v4", "M12 17h.01", "M10.29 3.86l-8.09 14a2 2 0 0 0 1.71 3h16.18a2 2 0 0 0 1.71-3l-8.09-14a2 2 0 0 0-3.42 0z"],
      };

      function TopBar({ currentView, setCurrentView, activeSession, dashboard, onPause, onResume, onAbort, wsState }) {
        const sessionLabel = activeSession ? activeSession.name : "No active session";
        const sessionStatus = activeSession ? activeSession.status : "idle";
        const workers = dashboard?.workers || [];
        const activeWorkers = workers.filter((worker) => worker.status === "active").length;
        const nav = [
          { id: "setup", label: "Setup" },
          { id: "monitor", label: "Monitor" },
          { id: "history", label: "History" },
          { id: "settings", label: "Settings" },
        ];
        return (
          <header
            className="border-b"
            style={{
              height: "var(--topbar-height)",
              position: "sticky",
              top: 0,
              zIndex: "var(--z-sticky)",
              background: "rgba(22, 25, 34, 0.92)",
              backdropFilter: "blur(12px)",
              borderColor: "var(--border-subtle)",
            }}
          >
            <div className="mx-auto flex h-full max-w-7xl items-center justify-between gap-4 px-4">
              <div className="flex items-center gap-4">
                <div>
                  <div className="font-display text-sm font-bold uppercase tracking-[0.32em] text-[var(--text-primary)]">COGNITIVE SWITCHYARD</div>
                </div>
                <div className="hidden md:block font-mono text-xs text-[var(--text-secondary)]">
                  {sessionLabel} · <span style={{ color: statusColor(sessionStatus) }}>{sessionStatus}</span>
                  {dashboard?.session?.started_at ? ` · ${formatDuration(dashboard.session.elapsed || 0)}` : ""}
                </div>
              </div>
              <nav className="hidden items-center gap-2 md:flex">
                {nav.map((item) => (
                  <button
                    key={item.id}
                    className="btn btn-secondary"
                    style={{
                      background: currentView === item.id ? "var(--bg-surface-hover)" : "transparent",
                      color: currentView === item.id ? "var(--text-primary)" : "var(--text-secondary)",
                    }}
                    onClick={() => setCurrentView(item.id)}
                  >
                    {item.label}
                  </button>
                ))}
              </nav>
              <div className="flex items-center gap-2">
                <div className="hidden lg:block font-mono text-xs text-[var(--text-secondary)]">
                  {activeSession ? `${activeWorkers}/${workers.length || activeSession.config?.num_workers || 0} active` : "ws"} · {wsState}
                </div>
                {activeSession && activeSession.status === "running" && (
                  <button className="btn btn-secondary" style={{ borderColor: "var(--status-active)", color: "var(--status-active)" }} onClick={onPause}>
                    <Icon path={ICONS.pause} size={14} />
                  </button>
                )}
                {activeSession && activeSession.status === "paused" && (
                  <button className="btn btn-primary" onClick={onResume}>
                    <Icon path={ICONS.play} size={14} />
                  </button>
                )}
                {activeSession && !["completed", "aborted"].includes(activeSession.status) && (
                  <button className="btn btn-danger" onClick={onAbort}>Abort</button>
                )}
              </div>
            </div>
          </header>
        );
      }

      function PipelineStrip({ pipeline, onOpenDag }) {
        const stages = [
          ["intake", "Intake"],
          ["planning", "Planning"],
          ["staged", "Staged"],
          ["review", "Review"],
          ["ready", "Ready"],
          ["active", "Active"],
          ["done", "Done"],
          ["blocked", "Blocked"],
        ];
        return (
          <div
            className="surface fade-up flex items-center justify-between px-4"
            style={{ height: "var(--pipeline-strip-height)", animationDelay: "80ms" }}
          >
            <div className="flex flex-wrap items-center gap-2">
              {stages.map(([key, label], index) => (
                <React.Fragment key={key}>
                  <span
                    className="status-pill"
                    style={{
                      background: `${statusColor(key)}22`,
                      color: statusColor(key),
                      border: `1px solid ${statusColor(key)}22`,
                      animation: key === "blocked" && (pipeline?.[key] || 0) > 0 ? "pulse-error 2s ease-in-out infinite" : "none",
                    }}
                  >
                    {label}({pipeline?.[key] || 0})
                  </span>
                  {index < stages.length - 1 && <span className="font-mono text-[11px] text-[var(--text-muted)]">→</span>}
                </React.Fragment>
              ))}
            </div>
            <button className="btn btn-secondary flex items-center gap-2" onClick={onOpenDag}>
              <Icon path={ICONS.branch} size={16} />
              DAG
            </button>
          </div>
        );
      }

      function WorkerCard({ worker, onSelect, logLines, delayMs = 0 }) {
        const active = worker.status === "active";
        const cardClass = worker.status === "problem" ? "worker-problem" : active ? "worker-active" : "worker-idle";
        const segments = Math.max(worker.phase_total || 0, 1);
        const completed = Math.max(0, (worker.phase_num || 1) - 1);
        return (
          <button
            className={`surface fade-up ${cardClass} text-left p-4 transition-colors hover:bg-[var(--bg-surface-hover)]`}
            style={{
              minHeight: "var(--worker-card-min-height)",
              animationDelay: `${delayMs}ms`,
              cursor: worker.task_id ? "pointer" : "default",
            }}
            disabled={!worker.task_id}
            onClick={() => worker.task_id && onSelect(worker.task_id)}
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <div className="font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--text-muted)]">Slot {worker.slot}</div>
                <div className="mt-1 font-mono text-sm font-semibold text-[var(--text-primary)]">{worker.task_id || "idle"}</div>
                <div className="mt-1 text-sm text-[var(--text-secondary)]">{worker.task_title || "Waiting for task..."}</div>
              </div>
              <StatusPill status={worker.status}>{worker.status}</StatusPill>
            </div>
            <div className="mb-3 flex gap-1">
              {Array.from({ length: segments }).map((_, index) => {
                const isDone = index < completed;
                const isCurrent = index === completed && active;
                return (
                  <div key={index} className="h-1.5 flex-1 rounded-full" style={{ background: "var(--bg-input)", overflow: "hidden" }}>
                    <div
                      style={{
                        width: isDone || isCurrent ? "100%" : "0%",
                        height: "100%",
                        background: isDone ? "var(--status-done)" : "var(--status-active)",
                        transition: "width 250ms ease",
                      }}
                    />
                  </div>
                );
              })}
            </div>
            <div className="mb-2 font-mono text-xs text-[var(--text-secondary)]">
              {worker.detail || (worker.phase ? `${worker.phase} ${worker.phase_num || ""}/${worker.phase_total || ""}` : "No progress detail yet")}
            </div>
            <div className="mb-4 font-mono text-[11px] text-[var(--text-muted)]">
              {worker.task_id ? `elapsed ${formatDuration(worker.elapsed)}` : "worker idle"}
            </div>
            <div
              className="scrollbar-thin rounded-md p-3 font-mono text-[11px] leading-5 text-[var(--text-secondary)]"
              style={{ background: "var(--bg-log)", minHeight: 96 }}
            >
              {logLines.length ? (
                logLines.slice(-5).map((line, index) => (
                  <div key={`${worker.slot}-${index}-${line}`} className="log-line">{line}</div>
                ))
              ) : (
                <div className="text-[var(--text-muted)]">{worker.task_id ? "Log stream waiting..." : "Waiting for task..."}</div>
              )}
            </div>
          </button>
        );
      }

      function TaskFeed({ tasks, onSelect }) {
        return (
          <div className="surface fade-up overflow-hidden" style={{ animationDelay: "320ms" }}>
            <div className="border-b px-4 py-3 font-display text-sm font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]" style={{ borderColor: "var(--border-subtle)" }}>
              Task Feed
            </div>
            <div className="max-h-[360px] overflow-y-auto scrollbar-thin">
              {tasks.length === 0 ? (
                <div className="p-6 text-sm text-[var(--text-muted)]">No tasks for this session yet.</div>
              ) : (
                sortTasks(tasks).map((task) => (
                  <button
                    key={task.id}
                    onClick={() => onSelect(task.id)}
                    className="flex h-11 w-full items-center gap-3 border-b px-4 text-left transition-colors hover:bg-[var(--bg-surface-hover)]"
                    style={{
                      borderColor: "var(--border-subtle)",
                      background: task.status === "blocked" ? "rgba(239, 68, 68, 0.08)" : "transparent",
                      boxShadow: task.status === "blocked" ? "inset 3px 0 0 var(--status-blocked)" : task.status === "active" ? "inset 3px 0 0 var(--status-active)" : "none",
                    }}
                  >
                    <div className="w-14 font-mono text-xs text-[var(--text-primary)]">{task.id}</div>
                    <div className="flex-1 truncate text-sm text-[var(--text-secondary)]">{task.title}</div>
                    <div className="hidden items-center gap-2 md:flex text-[var(--text-muted)]">
                      {task.depends_on?.length > 0 && <span className="font-mono text-[11px]">deps:{task.depends_on.length}</span>}
                      {task.anti_affinity?.length > 0 && <span className="font-mono text-[11px]">lock:{task.anti_affinity.length}</span>}
                    </div>
                    <StatusPill status={task.status}>{task.status}</StatusPill>
                  </button>
                ))
              )}
            </div>
          </div>
        );
      }

      function SetupView({
        packs,
        selectedPack,
        setSelectedPack,
        draftSession,
        setDraftSession,
        intakeFiles,
        setCurrentView,
        refreshAll,
        refreshSession,
      }) {
        const [form, setForm] = useState({
          name: "",
          num_workers: 2,
          num_planners: 1,
          verification_interval: 4,
          auto_fix_enabled: false,
          auto_fix_max_attempts: 2,
          poll_interval: 5,
        });
        const [advanced, setAdvanced] = useState(false);
        const [preflight, setPreflight] = useState({ checks: [], ok: true });
        const pack = packs.find((item) => item.name === selectedPack) || packs[0] || null;

        useEffect(() => {
          if (!pack) return;
          api(`/api/packs/${pack.name}/preflight`).then(setPreflight).catch(() => setPreflight({ checks: [], ok: false }));
          setForm((current) => ({
            ...current,
            num_workers: pack.phases.execution.max_workers || current.num_workers,
            verification_interval: pack.phases.verification.interval || current.verification_interval,
          }));
        }, [pack?.name]);

        async function createDraftSession() {
          if (!pack) return;
          const response = await api("/api/sessions", {
            method: "POST",
            body: JSON.stringify({
              pack_name: pack.name,
              name: form.name || `${pack.name}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}`,
              num_workers: Number(form.num_workers),
              num_planners: Number(form.num_planners),
              verification_interval: Number(form.verification_interval),
              auto_fix_enabled: Boolean(form.auto_fix_enabled),
              auto_fix_max_attempts: Number(form.auto_fix_max_attempts),
              poll_interval: Number(form.poll_interval),
            }),
          });
          setDraftSession(response.session);
          await refreshAll();
          await refreshSession(response.session.id);
        }

        async function startDraftSession() {
          if (!draftSession) return;
          await api(`/api/sessions/${draftSession.id}/start`, { method: "POST" });
          await refreshAll();
          await refreshSession(draftSession.id);
          setCurrentView("monitor");
        }

        async function openIntake() {
          if (!draftSession) return;
          await api(`/api/sessions/${draftSession.id}/open-intake`);
        }

        async function revealFile(relativePath) {
          if (!draftSession) return;
          const query = new URLSearchParams({ path: relativePath });
          await api(`/api/sessions/${draftSession.id}/reveal-file?${query.toString()}`);
        }

        return (
          <div className="mx-auto max-w-6xl px-4 py-8">
            <div className="grid gap-6 xl:grid-cols-[1.45fr,1fr]">
              <section className="panel p-8">
                <div className="mb-6">
                  <div className="font-mono text-xs uppercase tracking-[0.32em] text-[var(--text-secondary)]">Setup</div>
                  <h1 className="mt-3 font-display text-3xl font-bold text-[var(--text-primary)]">New Session</h1>
                  <p className="mt-2 max-w-2xl text-sm text-[var(--text-secondary)]">
                    Create a session, stage intake files, then launch the orchestrator into the live monitor.
                  </p>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <label>
                    <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-[var(--text-muted)]">Pack</div>
                    <select className="input" value={selectedPack || ""} onChange={(event) => setSelectedPack(event.target.value)}>
                      {packs.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
                    </select>
                  </label>
                  <label>
                    <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-[var(--text-muted)]">Session Name</div>
                    <input className="input" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="claude-code-2026-03-07" />
                  </label>
                  <label>
                    <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-[var(--text-muted)]">Workers</div>
                    <input className="input" type="number" min="1" value={form.num_workers} onChange={(event) => setForm({ ...form, num_workers: event.target.value })} />
                  </label>
                  {pack?.phases?.planning?.enabled && (
                    <label>
                      <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-[var(--text-muted)]">Planners</div>
                      <input className="input" type="number" min="1" value={form.num_planners} onChange={(event) => setForm({ ...form, num_planners: event.target.value })} />
                    </label>
                  )}
                </div>
                <button className="mt-4 text-xs text-[var(--text-secondary)]" onClick={() => setAdvanced((value) => !value)}>
                  {advanced ? "Hide" : "Show"} advanced session settings
                </button>
                {advanced && (
                  <div className="mt-4 grid gap-4 md:grid-cols-3">
                    <label>
                      <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-[var(--text-muted)]">Verify Interval</div>
                      <input className="input" type="number" min="1" value={form.verification_interval} onChange={(event) => setForm({ ...form, verification_interval: event.target.value })} />
                    </label>
                    <label>
                      <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-[var(--text-muted)]">Poll Interval</div>
                      <input className="input" type="number" min="1" value={form.poll_interval} onChange={(event) => setForm({ ...form, poll_interval: event.target.value })} />
                    </label>
                    <label>
                      <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-[var(--text-muted)]">Auto-Fix Attempts</div>
                      <input className="input" type="number" min="1" value={form.auto_fix_max_attempts} onChange={(event) => setForm({ ...form, auto_fix_max_attempts: event.target.value })} />
                    </label>
                    <label className="md:col-span-3 flex items-center gap-3 rounded-lg border px-4 py-3" style={{ borderColor: "var(--border-subtle)", background: "rgba(12, 14, 20, 0.7)" }}>
                      <input type="checkbox" checked={form.auto_fix_enabled} onChange={(event) => setForm({ ...form, auto_fix_enabled: event.target.checked })} />
                      <span className="text-sm text-[var(--text-secondary)]">Enable auto-fix for verification and task failures</span>
                    </label>
                  </div>
                )}
                <div className="mt-6 flex flex-wrap gap-3">
                  <button className="btn btn-primary" onClick={createDraftSession} disabled={!pack}>Create Session Directory</button>
                  <button className="btn btn-secondary" onClick={refreshAll}>Refresh</button>
                </div>
              </section>
              <section className="panel p-6">
                <div className="mb-4">
                  <div className="font-mono text-xs uppercase tracking-[0.32em] text-[var(--text-secondary)]">Pack Brief</div>
                  <h2 className="mt-2 font-display text-2xl font-semibold">{pack?.name || "No packs installed"}</h2>
                  <p className="mt-2 text-sm text-[var(--text-secondary)]">{pack?.description || "Install or bootstrap packs to begin."}</p>
                </div>
                <div className="space-y-3">
                  {(preflight.checks.length ? preflight.checks : [{ name: "No checks defined", passed: true, detail: "", kind: "info" }]).map((check) => (
                    <div key={`${check.kind}-${check.name}`} className="surface px-4 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm text-[var(--text-primary)]">{check.name}</div>
                        <StatusPill status={check.passed ? "done" : "blocked"}>{check.passed ? "pass" : "fail"}</StatusPill>
                      </div>
                      {check.detail && <div className="mt-2 font-mono text-[11px] text-[var(--text-secondary)]">{check.detail}</div>}
                    </div>
                  ))}
                </div>
              </section>
            </div>

            <section className="panel mt-6 p-6">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <div className="font-display text-xl font-semibold">Intake</div>
                  <div className="mt-1 font-mono text-xs text-[var(--text-secondary)]">
                    {draftSession ? draftSession.id : "Create a session first"} · {draftSession ? `Drop .md files in ${draftSession.id}/intake` : "Session path pending"}
                  </div>
                </div>
                <div className="flex flex-wrap gap-3">
                  <button className="btn btn-secondary flex items-center gap-2" onClick={openIntake} disabled={!draftSession}>
                    <Icon path={ICONS.folder} size={14} />
                    Open Intake
                  </button>
                  <button className="btn btn-primary" onClick={startDraftSession} disabled={!draftSession || intakeFiles.length === 0 || !preflight.ok}>
                    Start Session
                  </button>
                </div>
              </div>
              <div className="mt-4 rounded-lg border p-3" style={{ borderColor: "var(--border-subtle)", background: "var(--bg-log)" }}>
                {draftSession && draftSession.status !== "created" && (
                  <div className="mb-3 rounded-md border px-3 py-2 text-sm text-[var(--status-review)]" style={{ borderColor: "rgba(249, 115, 22, 0.35)" }}>
                    Session locked. Intake is now read-only.
                  </div>
                )}
                <div className="max-h-64 overflow-y-auto scrollbar-thin">
                  {intakeFiles.length === 0 ? (
                    <div className="px-2 py-4 text-sm text-[var(--text-muted)]">No intake files detected yet.</div>
                  ) : (
                    intakeFiles.map((file) => (
                      <div key={file.relative_path} className="flex items-center justify-between gap-3 border-b px-2 py-3 last:border-b-0" style={{ borderColor: "rgba(255,255,255,0.04)" }}>
                        <div>
                          <div className="font-mono text-sm text-[var(--text-primary)]">{file.name}</div>
                          <div className="font-mono text-[11px] text-[var(--text-muted)]">{file.size} bytes · {formatTimestamp(file.modified_at)}</div>
                        </div>
                        {!file.locked && (
                          <button className="btn btn-secondary" onClick={() => revealFile(file.relative_path)}>Reveal</button>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>
            </section>
          </div>
        );
      }

      function MonitorView({ dashboard, tasks, workerLogs, onSelectTask, onOpenDag }) {
        const workers = dashboard?.workers || [];
        return (
          <div className="mx-auto max-w-7xl px-4 py-6">
            <PipelineStrip pipeline={dashboard?.pipeline || {}} onOpenDag={onOpenDag} />
            <div className={`mt-6 grid gap-4 ${workers.length >= 5 ? "lg:grid-cols-3" : "lg:grid-cols-2"}`}>
              {workers.map((worker, index) => (
                <WorkerCard
                  key={worker.slot}
                  worker={worker}
                  onSelect={onSelectTask}
                  logLines={workerLogs[worker.slot] || []}
                  delayMs={160 + index * 60}
                />
              ))}
              {workers.length === 0 && (
                <div className="panel p-6 text-sm text-[var(--text-muted)]">No worker slots configured yet.</div>
              )}
            </div>
            <div className="mt-6">
              <TaskFeed tasks={tasks} onSelect={onSelectTask} />
            </div>
          </div>
        );
      }

      function MetadataRow({ label, value }) {
        return (
          <div>
            <div className="text-[11px] uppercase tracking-[0.08em] text-[var(--text-muted)]">{label}</div>
            <div className="mt-1 font-mono text-sm text-[var(--text-primary)]">{value || "n/a"}</div>
          </div>
        );
      }

      function TaskDetailView({ task, logContent, onBack }) {
        return (
          <div className="min-h-screen">
            <div className="mx-auto max-w-7xl px-4 py-6">
              <button className="btn btn-secondary mb-4 flex items-center gap-2" onClick={onBack}>
                <Icon path={ICONS.arrowLeft} size={14} />
                Back to Monitor
              </button>
              <div className="grid gap-6 xl:grid-cols-[1fr,1.35fr]">
                <section className="panel h-[calc(100vh-140px)] overflow-y-auto scrollbar-thin p-6">
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="font-mono text-2xl font-semibold">{task?.id}</div>
                    <StatusPill status={task?.status || "idle"}>{task?.status}</StatusPill>
                  </div>
                  <div className="mt-2 text-lg text-[var(--text-secondary)]">{task?.title}</div>
                  <div className="mt-6 grid gap-4 sm:grid-cols-2">
                    <MetadataRow label="Worker Slot" value={task?.worker_slot ?? "idle"} />
                    <MetadataRow label="Phase" value={task?.phase || "n/a"} />
                    <MetadataRow label="Created" value={formatTimestamp(task?.created_at)} />
                    <MetadataRow label="Completed" value={formatTimestamp(task?.completed_at)} />
                    <MetadataRow label="Depends On" value={(task?.depends_on || []).join(", ") || "none"} />
                    <MetadataRow label="Anti-Affinity" value={(task?.anti_affinity || []).join(", ") || "none"} />
                  </div>
                  <div className="mt-6 surface p-4">
                    <div className="mb-3 font-display text-sm font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Status Sidecar</div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {Object.entries(task?.status_sidecar || {}).map(([key, value]) => (
                        <MetadataRow key={key} label={key.replaceAll("_", " ")} value={value} />
                      ))}
                    </div>
                  </div>
                  <div className="markdown mt-6 rounded-lg border p-5" style={{ borderColor: "var(--border-subtle)", background: "rgba(12, 14, 20, 0.7)" }}>
                    <pre className="whitespace-pre-wrap text-sm text-[var(--text-secondary)]">{task?.plan_content || "No plan content found."}</pre>
                  </div>
                </section>
                <section className="panel flex h-[calc(100vh-140px)] flex-col overflow-hidden">
                  <div className="border-b px-5 py-4" style={{ borderColor: "var(--border-subtle)" }}>
                    <div className="font-display text-lg font-semibold">Live Log</div>
                  </div>
                  <div className="scrollbar-thin flex-1 overflow-y-auto p-5 font-mono text-xs leading-6 text-[var(--text-secondary)]" style={{ background: "var(--bg-log)" }}>
                    {logContent ? (
                      logContent.split("\\n").map((line, index) => (
                        <div
                          key={`${index}-${line}`}
                          style={{
                            color: /ERROR|FAIL/i.test(line) ? "var(--status-blocked)" : "var(--text-secondary)",
                            background: line.includes("##PROGRESS##") ? "rgba(245, 158, 11, 0.08)" : "transparent",
                            borderLeft: line.includes("##PROGRESS##") ? "2px solid var(--status-active)" : "2px solid transparent",
                            paddingLeft: line.includes("##PROGRESS##") ? 10 : 0,
                          }}
                        >
                          {line || " "}
                        </div>
                      ))
                    ) : (
                      <div className="text-[var(--text-muted)]">No log output available.</div>
                    )}
                  </div>
                </section>
              </div>
            </div>
          </div>
        );
      }

      function DAGView({ tasks, dag, onBack, onSelectTask }) {
        const width = 1100;
        const height = Math.max(460, tasks.length * 120);
        const nodePositions = {};
        tasks.forEach((task, index) => {
          const column = Math.floor(index / 6);
          const row = index % 6;
          nodePositions[task.id] = { x: 120 + column * 240, y: 90 + row * 110 };
        });
        return (
          <div className="min-h-screen grid-bg">
            <div className="mx-auto max-w-7xl px-4 py-6">
              <button className="btn btn-secondary mb-4 flex items-center gap-2" onClick={onBack}>
                <Icon path={ICONS.arrowLeft} size={14} />
                Back to Monitor
              </button>
              <div className="panel overflow-auto p-4">
                <svg width={width} height={height} className="min-w-full">
                  <defs>
                    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                      <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--text-muted)" />
                    </marker>
                  </defs>
                  {(dag?.tasks || []).flatMap((entry) => (entry.depends_on || []).map((depId) => {
                    const from = nodePositions[depId];
                    const to = nodePositions[entry.task_id];
                    if (!from || !to) return null;
                    return (
                      <line key={`${depId}-${entry.task_id}`} x1={from.x + 180} y1={from.y + 30} x2={to.x} y2={to.y + 30} stroke="var(--text-muted)" strokeWidth="2" markerEnd="url(#arrow)" />
                    );
                  }))}
                  {tasks.map((task) => {
                    const point = nodePositions[task.id];
                    return (
                      <g key={task.id} transform={`translate(${point.x}, ${point.y})`} onDoubleClick={() => onSelectTask(task.id)} style={{ cursor: "pointer" }}>
                        <rect width="180" height="64" rx="10" fill="var(--bg-surface)" stroke={statusColor(task.status)} strokeWidth="2" />
                        <text x="12" y="24" fill={statusColor(task.status)} fontFamily="JetBrains Mono" fontSize="13" fontWeight="600">{task.id}</text>
                        <text x="12" y="42" fill="var(--text-secondary)" fontFamily="DM Sans" fontSize="11">{task.title.slice(0, 22)}</text>
                        <text x="12" y="56" fill={statusColor(task.status)} fontFamily="JetBrains Mono" fontSize="10">{task.status}</text>
                      </g>
                    );
                  })}
                </svg>
              </div>
            </div>
          </div>
        );
      }

      function HistoryView({ sessions, refreshAll, setCurrentSessionId, setCurrentView }) {
        async function purgeSession(sessionId) {
          if (!confirm(`Delete session ${sessionId} and its artifacts?`)) return;
          await api(`/api/sessions/${sessionId}`, { method: "DELETE" });
          await refreshAll();
        }

        async function purgeAll() {
          if (!confirm("Purge all completed or aborted sessions?")) return;
          await api("/api/sessions", { method: "DELETE" });
          await refreshAll();
        }

        return (
          <div className="mx-auto max-w-7xl px-4 py-8">
            <div className="mb-6 flex items-center justify-between gap-4">
              <div>
                <div className="font-display text-2xl font-semibold">Session History</div>
                <div className="mt-1 text-sm text-[var(--text-secondary)]">Completed and aborted sessions remain here until purged or retention expiry.</div>
              </div>
              <button className="btn btn-danger" onClick={purgeAll}>Purge All</button>
            </div>
            <div className="space-y-3">
              {sessions.length === 0 ? (
                <div className="panel p-10 text-center text-[var(--text-muted)]">No sessions yet.</div>
              ) : (
                sessions.map((entry) => (
                  <div key={entry.session.id} className="panel p-5">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <div className="flex flex-wrap items-center gap-3">
                          <div className="font-display text-lg font-semibold">{entry.session.name}</div>
                          <StatusPill status={entry.session.status}>{entry.session.status}</StatusPill>
                          <span className="rounded-full px-2 py-1 font-mono text-[11px]" style={{ background: "var(--bg-surface-raised)", color: "var(--text-secondary)" }}>{entry.session.pack_name}</span>
                        </div>
                        <div className="mt-2 font-mono text-xs text-[var(--text-secondary)]">
                          created {formatTimestamp(entry.session.created_at)} · done {entry.pipeline.done || 0} · blocked {entry.pipeline.blocked || 0}
                        </div>
                      </div>
                      <div className="flex gap-3">
                        <button
                          className="btn btn-secondary"
                          onClick={() => {
                            setCurrentSessionId(entry.session.id);
                            setCurrentView("monitor");
                          }}
                        >
                          Open
                        </button>
                        <button className="btn btn-danger flex items-center gap-2" onClick={() => purgeSession(entry.session.id)}>
                          <Icon path={ICONS.trash} size={14} />
                          Delete
                        </button>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        );
      }

      function SettingsView({ settings, setSettings, refreshAll }) {
        const [local, setLocal] = useState(settings);
        useEffect(() => setLocal(settings), [settings]);

        async function save() {
          const saved = await api("/api/settings", {
            method: "PUT",
            body: JSON.stringify({
              retention_days: Number(local.retention_days || 0),
              default_planners: Number(local.default_planners || 1),
              default_workers: Number(local.default_workers || 1),
              default_pack: local.default_pack || "",
            }),
          });
          setSettings(saved);
          await refreshAll();
        }

        return (
          <div className="mx-auto max-w-4xl px-4 py-8">
            <section className="panel p-8">
              <div className="mb-6">
                <div className="font-display text-2xl font-semibold">Settings</div>
                <div className="mt-2 text-sm text-[var(--text-secondary)]">Global defaults stored in config.yaml.</div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <label>
                  <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-[var(--text-muted)]">Retention Days</div>
                  <input className="input" type="number" min="0" value={local.retention_days || 0} onChange={(event) => setLocal({ ...local, retention_days: event.target.value })} />
                </label>
                <label>
                  <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-[var(--text-muted)]">Default Pack</div>
                  <input className="input" value={local.default_pack || ""} onChange={(event) => setLocal({ ...local, default_pack: event.target.value })} />
                </label>
                <label>
                  <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-[var(--text-muted)]">Default Planners</div>
                  <input className="input" type="number" min="1" value={local.default_planners || 1} onChange={(event) => setLocal({ ...local, default_planners: event.target.value })} />
                </label>
                <label>
                  <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-[var(--text-muted)]">Default Workers</div>
                  <input className="input" type="number" min="1" value={local.default_workers || 1} onChange={(event) => setLocal({ ...local, default_workers: event.target.value })} />
                </label>
              </div>
              <div className="mt-6 flex gap-3">
                <button className="btn btn-primary" onClick={save}>Save Settings</button>
              </div>
            </section>
          </div>
        );
      }

      function App() {
        const [packs, setPacks] = useState([]);
        const [sessions, setSessions] = useState([]);
        const [settings, setSettings] = useState({});
        const [selectedPack, setSelectedPack] = useState("");
        const [currentView, setCurrentView] = useState("setup");
        const [currentSessionId, setCurrentSessionId] = useState(null);
        const [sessionPayload, setSessionPayload] = useState(null);
        const [dashboard, setDashboard] = useState(null);
        const [tasks, setTasks] = useState([]);
        const [dag, setDag] = useState({ tasks: [], groups: [], conflicts: [], notes: "" });
        const [selectedTaskId, setSelectedTaskId] = useState(null);
        const [selectedTask, setSelectedTask] = useState(null);
        const [taskLog, setTaskLog] = useState("");
        const [draftSession, setDraftSession] = useState(null);
        const [intakeFiles, setIntakeFiles] = useState([]);
        const [workerLogs, setWorkerLogs] = useState({});
        const [wsState, setWsState] = useState("connecting");
        const wsRef = useRef(null);

        async function refreshAll() {
          const [packData, sessionData, settingsData] = await Promise.all([
            api("/api/packs"),
            api("/api/sessions"),
            api("/api/settings"),
          ]);
          setPacks(packData || []);
          setSessions(sessionData || []);
          setSettings(settingsData || {});
          if (!selectedPack && packData?.length) {
            setSelectedPack(settingsData?.default_pack || packData[0].name);
          }
          if (!currentSessionId) {
            const candidate = (sessionData || []).find((entry) => !["completed", "aborted"].includes(entry.session.status));
            if (candidate) {
              setCurrentSessionId(candidate.session.id);
              setDraftSession(candidate.session.status === "created" ? candidate.session : null);
            }
          }
        }

        async function refreshSession(sessionId = currentSessionId) {
          if (!sessionId) return;
          const [sessionData, tasksData, dashboardData, dagData] = await Promise.all([
            api(`/api/sessions/${sessionId}`),
            api(`/api/sessions/${sessionId}/tasks`),
            api(`/api/sessions/${sessionId}/dashboard`),
            api(`/api/sessions/${sessionId}/dag`),
          ]);
          setSessionPayload(sessionData);
          setDashboard(dashboardData);
          setTasks(tasksData || []);
          setDag(dagData || { tasks: [], groups: [], conflicts: [], notes: "" });
          if (sessionData?.session?.status === "created") {
            setDraftSession(sessionData.session);
          }
        }

        async function refreshIntake(sessionId = currentSessionId || draftSession?.id) {
          if (!sessionId) {
            setIntakeFiles([]);
            return;
          }
          const files = await api(`/api/sessions/${sessionId}/intake`);
          setIntakeFiles(files || []);
        }

        useEffect(() => {
          refreshAll().catch((error) => console.error(error));
        }, []);

        useEffect(() => {
          if (!currentSessionId) return;
          refreshSession(currentSessionId).catch((error) => console.error(error));
          refreshIntake(currentSessionId).catch((error) => console.error(error));
          const timer = setInterval(() => {
            refreshSession(currentSessionId).catch(() => {});
            refreshIntake(currentSessionId).catch(() => {});
          }, 3000);
          return () => clearInterval(timer);
        }, [currentSessionId]);

        useEffect(() => {
          const sessionId = currentSessionId || draftSession?.id;
          if (!sessionId) return;
          const timer = setInterval(() => {
            refreshIntake(sessionId).catch(() => {});
          }, 2500);
          return () => clearInterval(timer);
        }, [currentSessionId, draftSession?.id]);

        useEffect(() => {
          const ws = new WebSocket(`ws://${location.host}/ws`);
          wsRef.current = ws;
          ws.onopen = () => setWsState("live");
          ws.onclose = () => setWsState("offline");
          ws.onerror = () => setWsState("error");
          ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            const data = message.data || {};
            if (currentSessionId && data.session_id && data.session_id !== currentSessionId) {
              return;
            }
            if (message.type === "state_update") {
              setDashboard((current) => ({ ...current, ...data }));
            } else if (message.type === "log_line") {
              setWorkerLogs((current) => {
                const next = { ...current };
                const lines = [...(next[data.worker_slot] || []), data.line];
                next[data.worker_slot] = lines.slice(-10);
                return next;
              });
            } else if (message.type === "progress_detail") {
              setDashboard((current) => {
                if (!current?.workers) return current;
                return {
                  ...current,
                  workers: current.workers.map((worker) =>
                    worker.slot === data.worker_slot ? { ...worker, detail: data.detail } : worker
                  ),
                };
              });
            } else if (message.type === "task_status_change") {
              refreshSession(currentSessionId).catch(() => {});
            }
          };
          return () => ws.close();
        }, [currentSessionId]);

        useEffect(() => {
          if (!selectedTaskId || !currentSessionId) return;
          const load = async () => {
            const [taskData, logData] = await Promise.all([
              api(`/api/sessions/${currentSessionId}/tasks/${selectedTaskId}`),
              api(`/api/sessions/${currentSessionId}/tasks/${selectedTaskId}/log`),
            ]);
            setSelectedTask(taskData);
            setTaskLog(logData?.content || "");
          };
          load().catch((error) => console.error(error));
          const timer = setInterval(() => load().catch(() => {}), 2000);
          return () => clearInterval(timer);
        }, [selectedTaskId, currentSessionId]);

        const activeSession = sessionPayload?.session || draftSession || null;

        async function pauseSession() {
          if (!currentSessionId) return;
          await api(`/api/sessions/${currentSessionId}/pause`, { method: "POST" });
          await refreshSession(currentSessionId);
          await refreshAll();
        }

        async function resumeSession() {
          if (!currentSessionId) return;
          await api(`/api/sessions/${currentSessionId}/resume`, { method: "POST" });
          await refreshSession(currentSessionId);
          await refreshAll();
        }

        async function abortSession() {
          if (!currentSessionId) return;
          if (!confirm("Abort the current session?")) return;
          await api(`/api/sessions/${currentSessionId}/abort`, { method: "POST" });
          await refreshSession(currentSessionId);
          await refreshAll();
        }

        function openTask(taskId) {
          setSelectedTaskId(taskId);
          setCurrentView("taskDetail");
        }

        let content = (
          <SetupView
            packs={packs}
            selectedPack={selectedPack}
            setSelectedPack={setSelectedPack}
            draftSession={draftSession}
            setDraftSession={setDraftSession}
            intakeFiles={intakeFiles}
            setCurrentView={(view) => {
              if (view === "monitor" && draftSession?.id) {
                setCurrentSessionId(draftSession.id);
              }
              setCurrentView(view);
            }}
            refreshAll={refreshAll}
            refreshSession={async (sessionId) => {
              setCurrentSessionId(sessionId);
              await refreshSession(sessionId);
              await refreshIntake(sessionId);
            }}
          />
        );

        if (currentView === "monitor") {
          content = (
            <MonitorView
              dashboard={dashboard}
              tasks={tasks}
              workerLogs={workerLogs}
              onSelectTask={openTask}
              onOpenDag={() => setCurrentView("dag")}
            />
          );
        } else if (currentView === "taskDetail") {
          content = <TaskDetailView task={selectedTask} logContent={taskLog} onBack={() => setCurrentView("monitor")} />;
        } else if (currentView === "dag") {
          content = <DAGView tasks={tasks} dag={dag} onBack={() => setCurrentView("monitor")} onSelectTask={openTask} />;
        } else if (currentView === "history") {
          content = (
            <HistoryView
              sessions={sessions}
              refreshAll={refreshAll}
              setCurrentSessionId={async (sessionId) => {
                setCurrentSessionId(sessionId);
                await refreshSession(sessionId);
              }}
              setCurrentView={setCurrentView}
            />
          );
        } else if (currentView === "settings") {
          content = <SettingsView settings={settings} setSettings={setSettings} refreshAll={refreshAll} />;
        }

        return (
          <div>
            <TopBar
              currentView={currentView}
              setCurrentView={setCurrentView}
              activeSession={activeSession}
              dashboard={dashboard}
              onPause={pauseSession}
              onResume={resumeSession}
              onAbort={abortSession}
              wsState={wsState}
            />
            {content}
          </div>
        );
      }

      ReactDOM.createRoot(document.getElementById("root")).render(<App />);
    </script>
  </body>
</html>"""
