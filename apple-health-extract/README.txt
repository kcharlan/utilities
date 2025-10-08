
To run this, you need to:
1. Export your Apple Health data.
2. Extract the zip file, and pull out the export.xml file and drop it here.
3. Activate the virtual environment (source venv/bin/activate). If you need to rebuild the environment, see the setup.sh.
4. Run the extract_workout_stats.py first. This extracts workout_summary.csv (needed for the next step) and workout_heart_rate_detail.csv.
5. After 4 is complete, run exercise_bouts.py to extract the non-affiliated exercise minutes and data. It outputs exercise_bouts.csv
