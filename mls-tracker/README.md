# MLS Tracker

Self-bootstrapping dashboard for tracking MLS playoff races across both conferences. Pulls live standings from the ESPN public API, dynamically applies team branding (colors, logos), and computes playoff scenarios against a configurable cutoff position.

## Running

```bash
./mls_tracker
```

Zero setup required. On first run the script creates a runtime home at `~/.mls_tracker/`, a private venv at `~/.mls_tracker/venv/`, and a `bootstrap_state.json` refresh marker. A browser tab opens automatically to `http://127.0.0.1:8501`.

### Options

```
--port PORT, -p PORT    Port to serve on (default: 8501)
--no-browser            Don't open browser automatically
```

## Features

- **Both conferences**: Eastern and Western Conference standings with full team rosters.
- **Dynamic team theming**: Colors and logos fetched from ESPN's teams API — no hardcoded team configs.
- **Configurable playoff cutoff**: Analyze scenarios against any position (default: 9th).
- **Clinch/elimination logic**: Clinched if target points exceed cutoff's maximum possible points; eliminated if max possible target points fall below cutoff's current points.
- **Playoff scenarios**: Worst Case (wins only) and Easiest Path (maximum ties) breakdowns.
- **Need help analysis**: When needing help from other results, shows what the cutoff team must do.
- **Dark mode**: Toggle or auto-detect from system preference, persisted in localStorage.
- **5-minute data cache** with manual refresh button.

## Architecture

Single-file FastAPI + embedded React SPA (no Node.js build tooling required).

- **Backend**: FastAPI + uvicorn serving JSON API endpoints and an HTML template.
- **Frontend**: React 18 + Tailwind CSS + Lucide Icons, all loaded via CDN with in-browser Babel JSX transpilation.
- **Data sources**:
  - Standings: `https://site.api.espn.com/apis/v2/sports/soccer/usa.1/standings?season={year}`
  - Teams: `https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/teams`

## API Endpoints

```
GET  /                              → React SPA
GET  /api/data?season={year}        → Conference standings + team metadata
GET  /api/scenarios?season=&team=&cutoff=  → Playoff scenarios for a team
POST /api/refresh                   → Invalidate data cache
```
