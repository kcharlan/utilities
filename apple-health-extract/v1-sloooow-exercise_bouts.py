import xml.etree.ElementTree as ET
import pandas as pd
from datetime import datetime, timedelta
import csv
from tqdm import tqdm

# -------- CONFIGURATION --------
XML_PATH = "export.xml"
WORKOUT_CSV = "workout_summary.csv"
OUTPUT_CSV = "exercise_bouts.csv"

# Types of interest
HEART_RATE_TYPE = "HKQuantityTypeIdentifierHeartRate"
STEP_TYPE = "HKQuantityTypeIdentifierStepCount"
DISTANCE_TYPE = "HKQuantityTypeIdentifierDistanceWalkingRunning"
CALORIES_TYPE = "HKQuantityTypeIdentifierActiveEnergyBurned"
EXERCISE_TYPE = "HKQuantityTypeIdentifierAppleExerciseTime"

# --------- ESTIMATE XML FILE SIZE ---------
print("Counting lines for progress estimation...")
with open(XML_PATH, "r", encoding="utf-8", errors="ignore") as f:
    num_lines = sum(1 for _ in f)

# --------- EXTRACT EXERCISE + OTHER DATA ---------
print("Parsing export.xml for exercise, heart rate, steps, distance, calories...")
exercise_rows, heart_rate_rows, step_rows, distance_rows, calories_rows = [], [], [], [], []

with open(XML_PATH, "r", encoding="utf-8", errors="ignore") as file:
    # tqdm for progress
    for event, elem in tqdm(ET.iterparse(file, events=("start",)), total=num_lines, desc="Parsing XML"):
        t = elem.attrib.get("type")
        if elem.tag == "Record":
            if t == EXERCISE_TYPE:
                exercise_rows.append({
                    "startDate": elem.attrib.get("startDate"),
                    "endDate": elem.attrib.get("endDate"),
                    "value": float(elem.attrib.get("value", "0")),
                    "unit": elem.attrib.get("unit"),
                    "sourceName": elem.attrib.get("sourceName"),
                    "sourceVersion": elem.attrib.get("sourceVersion"),
                    "device": elem.attrib.get("device")
                })
            elif t == HEART_RATE_TYPE:
                heart_rate_rows.append({
                    "startDate": elem.attrib.get("startDate"),
                    "value": float(elem.attrib.get("value", "0"))
                })
            elif t == STEP_TYPE:
                step_rows.append({
                    "startDate": elem.attrib.get("startDate"),
                    "value": float(elem.attrib.get("value", "0"))
                })
            elif t == DISTANCE_TYPE:
                distance_rows.append({
                    "startDate": elem.attrib.get("startDate"),
                    "value": float(elem.attrib.get("value", "0"))
                })
            elif t == CALORIES_TYPE:
                calories_rows.append({
                    "startDate": elem.attrib.get("startDate"),
                    "value": float(elem.attrib.get("value", "0"))
                })
        elem.clear()

exercise_df = pd.DataFrame(exercise_rows)
heart_rate_df = pd.DataFrame(heart_rate_rows)
step_df = pd.DataFrame(step_rows)
distance_df = pd.DataFrame(distance_rows)
calories_df = pd.DataFrame(calories_rows)

if exercise_df.empty:
    raise ValueError("No Apple Exercise Time records found!")

exercise_df["start_dt"] = pd.to_datetime(exercise_df["startDate"])
exercise_df["end_dt"] = pd.to_datetime(exercise_df["endDate"])
exercise_df = exercise_df.sort_values("start_dt")

# --------- GROUP INTO BOUTS ---------
print("Grouping exercise minutes into bouts...")
bouts = []
current_bout = None

for idx, row in exercise_df.iterrows():
    this_start = row['start_dt']
    this_end = row['end_dt']
    if current_bout is None:
        current_bout = {
            "start_dt": this_start,
            "end_dt": this_end,
            "rows": [row],
        }
    else:
        last_end_dt = pd.to_datetime(current_bout["rows"][-1]["endDate"])
        if (this_start - last_end_dt) <= timedelta(seconds=90):
            current_bout["end_dt"] = this_end
            current_bout["rows"].append(row)
        else:
            bouts.append(current_bout)
            current_bout = {
                "start_dt": this_start,
                "end_dt": this_end,
                "rows": [row],
            }
if current_bout:
    bouts.append(current_bout)

# --------- LOAD WORKOUTS ---------
print("Loading workout time windows...")
workouts_df = pd.read_csv(WORKOUT_CSV)
workouts_df["start_dt"] = pd.to_datetime(workouts_df["start"]).dt.tz_localize("US/Eastern")
workouts_df["end_dt"] = pd.to_datetime(workouts_df["end"]).dt.tz_localize("US/Eastern")

def label_bout(bout_start, bout_end):
    for _, w in workouts_df.iterrows():
        if (bout_start < w["end_dt"]) and (bout_end > w["start_dt"]):
            return ("Workout", w["type"])
    return ("Incidental", None)

def summarize_data_in_bout(df, start, end, how="mean"):
    if df.empty: return None
    times = pd.to_datetime(df["startDate"])
    mask = (times >= start) & (times <= end)
    values = df.loc[mask, "value"]
    if values.empty: return None
    if how == "mean":
        return values.mean()
    elif how == "sum":
        return values.sum()
    else:
        return values.tolist()

# --------- SUMMARIZE PER-BOUT ---------
print("Summarizing heart rate, steps, calories, distance for each bout...")
bout_rows = []
for bout in tqdm(bouts, desc="Summarizing bouts"):
    # Ensure tz-aware for comparison
    bout_start = bout["start_dt"].tz_localize("US/Eastern") if bout["start_dt"].tzinfo is None else bout["start_dt"]
    bout_end = bout["end_dt"].tz_localize("US/Eastern") if bout["end_dt"].tzinfo is None else bout["end_dt"]
    bout_type, workout_type = label_bout(bout_start, bout_end)

    avg_hr = summarize_data_in_bout(heart_rate_df, bout_start, bout_end, "mean")
    total_steps = summarize_data_in_bout(step_df, bout_start, bout_end, "sum")
    total_cal = summarize_data_in_bout(calories_df, bout_start, bout_end, "sum")
    total_dist = summarize_data_in_bout(distance_df, bout_start, bout_end, "sum")

    bout_rows.append({
        "bout_start": bout_start,
        "bout_end": bout_end,
        "duration_min": len(bout["rows"]),
        "type": bout_type,
        "workout_type": workout_type,
        "avg_heart_rate": avg_hr,
        "steps": total_steps,
        "calories": total_cal,
        "distance_km": total_dist,
        "sourceName": bout["rows"][0]["sourceName"],
        "device": bout["rows"][0]["device"],
        "first_min_start": bout["rows"][0]["startDate"],
        "last_min_end": bout["rows"][-1]["endDate"],
    })

# --------- EXPORT TO CSV ---------
print(f"Exporting {len(bout_rows)} bouts to {OUTPUT_CSV}...")
with open(OUTPUT_CSV, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=bout_rows[0].keys())
    writer.writeheader()
    for row in bout_rows:
        writer.writerow(row)

print("Done! Your exercise bouts with metrics are ready for analysis.")
