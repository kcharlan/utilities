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
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <style>
      :root {
        --bg: #f6f0e6;
        --ink: #172121;
        --accent: #b24c2d;
        --accent-soft: #ffd8b8;
      }
      body {
        margin: 0;
        font-family: "Space Grotesk", sans-serif;
        background:
          radial-gradient(circle at top left, rgba(178, 76, 45, 0.18), transparent 32%),
          radial-gradient(circle at bottom right, rgba(32, 94, 77, 0.16), transparent 28%),
          var(--bg);
        color: var(--ink);
      }
      .mono { font-family: "IBM Plex Mono", monospace; }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script type="text/babel">
      const { useEffect, useState } = React;

      function TopBar({ currentView, setCurrentView }) {
        const views = ["setup", "monitor", "history", "settings"];
        return (
          <header className="border-b border-black/10 bg-white/70 backdrop-blur px-6 py-4 sticky top-0">
            <div className="max-w-6xl mx-auto flex items-center justify-between gap-4">
              <div>
                <div className="text-xs uppercase tracking-[0.3em] mono text-black/50">COGNITIVE SWITCHYARD</div>
                <div className="text-2xl font-bold">Local Orchestration Console</div>
              </div>
              <nav className="flex gap-2">
                {views.map((view) => (
                  <button
                    key={view}
                    onClick={() => setCurrentView(view)}
                    className={`px-3 py-2 rounded-full text-sm capitalize border ${currentView === view ? "bg-black text-white border-black" : "bg-white/80 border-black/10"}`}
                  >
                    {view}
                  </button>
                ))}
              </nav>
            </div>
          </header>
        );
      }

      function SetupView({ packs }) {
        return (
          <section className="grid md:grid-cols-[2fr,1fr] gap-6">
            <div className="bg-white/75 rounded-3xl p-6 border border-black/10 shadow-sm">
              <div className="mono text-xs uppercase tracking-[0.3em] text-black/50 mb-2">Setup</div>
              <h2 className="text-3xl font-bold mb-3">Create and launch sessions</h2>
              <p className="text-black/70 mb-6">Use the API-backed views to create sessions, stage intake, and launch orchestrators.</p>
              <div className="grid sm:grid-cols-2 gap-4">
                <div className="rounded-2xl bg-[var(--accent-soft)] p-4">
                  <div className="font-semibold mb-1">Installed Packs</div>
                  <div className="text-sm text-black/70">{packs.length} available</div>
                </div>
                <div className="rounded-2xl bg-black text-white p-4">
                  <div className="font-semibold mb-1">Transport</div>
                  <div className="text-sm text-white/70">REST + WebSocket</div>
                </div>
              </div>
            </div>
            <div className="bg-white/75 rounded-3xl p-6 border border-black/10 shadow-sm">
              <div className="mono text-xs uppercase tracking-[0.3em] text-black/50 mb-3">Packs</div>
              <ul className="space-y-3">
                {packs.map((pack) => (
                  <li key={pack.name} className="rounded-2xl border border-black/10 px-4 py-3">
                    <div className="font-semibold">{pack.name}</div>
                    <div className="text-sm text-black/60">{pack.description}</div>
                  </li>
                ))}
              </ul>
            </div>
          </section>
        );
      }

      function PlaceholderView({ label, title, detail }) {
        return (
          <section className="bg-white/75 rounded-3xl p-6 border border-black/10 shadow-sm">
            <div className="mono text-xs uppercase tracking-[0.3em] text-black/50 mb-2">{label}</div>
            <h2 className="text-3xl font-bold mb-3">{title}</h2>
            <p className="text-black/70">{detail}</p>
          </section>
        );
      }

      function App() {
        const [currentView, setCurrentView] = useState("setup");
        const [packs, setPacks] = useState([]);

        useEffect(() => {
          fetch("/api/packs").then((r) => r.json()).then(setPacks).catch(() => setPacks([]));
        }, []);

        let content = <SetupView packs={packs} />;
        if (currentView === "monitor") {
          content = <PlaceholderView label="Monitor" title="Session monitoring" detail="Live worker telemetry, task feeds, and retry controls are served from the REST and WebSocket APIs." />;
        } else if (currentView === "history") {
          content = <PlaceholderView label="History" title="Session archive" detail="Completed and aborted sessions can be listed and purged through the API." />;
        } else if (currentView === "settings") {
          content = <PlaceholderView label="Settings" title="Global defaults" detail="Retention, default pack, and worker counts are stored in the API settings endpoint." />;
        }

        return (
          <div>
            <TopBar currentView={currentView} setCurrentView={setCurrentView} />
            <main className="max-w-6xl mx-auto px-6 py-8">{content}</main>
          </div>
        );
      }

      ReactDOM.createRoot(document.getElementById("root")).render(<App />);
    </script>
  </body>
</html>"""
