# Apple Health Workout Extractor
Utilities for turning an Apple Health export (`export.xml`) into structured CSV datasets covering workouts, heart-rate detail, and incidental exercise bouts.

## What You Get

- `workout_summary.csv` – One row per recorded workout with start/end timestamps, duration, device, heart-rate aggregates, steps, distance, and calorie totals.
- `workout_heart_rate_detail.csv` – Timestamped heart-rate samples keyed to the workout that produced them.
- `exercise_bouts.csv` – Groups of non-workout Apple Exercise Time minutes, annotated with average heart rate, steps, calories, and overlapping workout labels (Workout vs Incidental).

## Environment

1. (Optional) `./setup.sh` creates `venv/` using the system Python.
2. Activate the virtual environment: `source venv/bin/activate`.
3. Install dependencies:
   ```bash
   pip install pandas tqdm
   ```

The scripts use only the standard library plus `pandas` and `tqdm`, so no compiled extensions are required.

## Required Inputs

1. From the Health app, export your data (⚙︎ → Export All Health Data) which produces a ZIP file.
2. Extract `export.xml` and place it in this directory.

## Typical Workflow

1. **Generate workout summaries and heart-rate detail**
   ```bash
   python extract_workout_stats.py
   ```
   - Scans every `<Workout>` entry to build a baseline table.
   - Streams the XML once more to capture heart rate, steps, distance, and active calories for the workout window.
   - Writes `workout_summary.csv` and `workout_heart_rate_detail.csv`.

2. **Build incidental exercise bouts**
   ```bash
   python exercise_bouts.py
   ```
   - Consumes `workout_summary.csv` to label bouts that overlap an official workout.
   - Groups contiguous Apple Exercise Time records within 90 seconds into a single bout.
   - Aggregates complementary metrics (heart rate, steps, calories, distance) and writes `exercise_bouts.csv`.

3. (Optional) `backup-exercise_bouts.py` and `v1-sloooow-exercise_bouts.py` retain earlier experimentation. Only `exercise_bouts.py` is needed for production runs.

## Performance Notes

- `extract_workout_stats.py` streams the XML via `iterparse` and clears elements immediately to keep memory stable even for multi-gigabyte exports.
- `exercise_bouts.py` pre-counts the XML lines to show a progress bar sized correctly for large files.
- Expect multi-minute runtimes for multi-year exports; run from SSD storage when possible.

## Troubleshooting

- Ensure `export.xml` is UTF-8 encoded. The scripts open the file in text mode with `errors="ignore"` to survive odd characters, but a corrupt XML file will still fail.
- If you have only a small subset of data, confirm that the export actually contains Apple Exercise Time records—otherwise `exercise_bouts.py` raises a descriptive error.
- If the default virtual environment path in `run.sh` is stale, regenerate the venv and update the script or call the Python files directly.
