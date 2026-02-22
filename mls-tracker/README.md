# MLS Tracker
Streamlit dashboard and supporting scripts for tracking MLS Eastern Conference playoff races. Pulls live standings from the ESPN public API, applies custom team branding, and computes playoff scenarios against the 9th-place bubble team.

## Components

- `mls_playoff_tracker.py` – Streamlit app with per-team theming, playoff scenario analysis, and standings comparison.
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

- Sidebar pickers for season year, favorite club, games per season, and API timeout.
- Automatic color theming for 14 Eastern Conference teams (Atlanta United, Inter Miami, LAFC, NYCFC, Toronto, Philadelphia, Orlando, NY Red Bulls, Nashville, CF Montreal, D.C. United, Columbus, Charlotte, Chicago Fire).
- Pulls Eastern Conference standings via the ESPN endpoint with 5-minute `st.cache_data` caching.
- Custom CSS removes Streamlit boilerplate (headers, collapse buttons) for a cleaner kiosk presentation.
- Status banner showing whether the selected team is eliminated, needs help, is in contention, or has clinched.
- Metric cards for current points, points to safety, minimum wins needed, and required PPG.
- Standings snapshot comparing the selected team against the 9th-place team.
- Best-case and worst-case playoff scenario breakdowns (wins, ties, losses, final points).
- "Need help" analysis showing what 9th place must do for the selected team to qualify.

## CLI Standings Snapshot

```bash
python gemini-espn-api.py
```

The script hits the same ESPN endpoint, normalizes stats into integers, sorts by rank, and prints east/west tables, making it suitable for quick daily summaries or Gemini prompts.

## Extending

- Add additional teams or tweak branding in `TEAM_CONFIGS` (uppercase hex colors, search keywords).
- Export standings by saving the pandas DataFrames created inside the Streamlit app.
