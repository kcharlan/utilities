# MLS Tracker
Streamlit dashboard and supporting scripts for tracking MLS playoff races. Pulls live standings from the ESPN public API, applies custom team branding, and highlights upcoming opponents and form.

## Components

- `mls_playoff_tracker.py` – Streamlit app with per-team theming, opponent breakdowns, and playoff clinch metrics.
- `gemini-espn-api.py` – Standalone script that prints sorted conference tables to the terminal.
- `run.sh` – Convenience wrapper to activate the virtual environment and launch Streamlit.
- `setup.sh` – Rebuilds the `venv/` folder with `streamlit`, `pandas`, and `requests`.

## Setup

```bash
./setup.sh
source venv/bin/activate
```

The Streamlit app requires internet access to call ESPN’s API at runtime.

## Running the Dashboard

```bash
./run.sh
# or
streamlit run mls_playoff_tracker.py
```

Features:

- Sidebar pickers for your favorite club, with automatic color theming.
- Pulls standings, results, and schedules via the ESPN endpoint.
- Custom CSS removes Streamlit boilerplate (headers, collapse buttons) for a cleaner kiosk presentation.
- Metric cards and opponent breakdowns highlight clinch scenarios at a glance.

## CLI Standings Snapshot

```bash
python gemini-espn-api.py
```

The script hits the same ESPN endpoint, normalizes stats into integers, sorts by rank, and prints east/west tables, making it suitable for quick daily summaries or Gemini prompts.

## Extending

- Add additional teams or tweak branding in `TEAM_CONFIGS` (uppercase hex colors, search keywords).
- Layer in caching by wrapping the API calls with `st.cache_data` if you expect heavy usage.
- Export standings or schedules by saving the pandas DataFrames created inside the Streamlit app.
