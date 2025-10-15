#!/usr/bin/env python3
"""
Roll up snapshot JSON files into a daily CSV summary.

This script scans for `snapshot_*.json` files in the same directory, uses the
timestamp embedded in each filename to determine the UTC date, and aggregates
the `totals` payload into `snapshots.csv`. After a snapshot is successfully
rolled up, it is renamed with a `.bak` suffix so it will not be processed
again.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

BASE_DIR = Path(__file__).resolve().parent
CSV_FILENAME = "snapshots.csv"
SNAPSHOT_GLOB = "snapshot_*.json"


def _load_existing(csv_path: Path) -> Tuple[Dict[str, Dict[str, int]], List[str]]:
    """Load existing CSV content, returning per-date totals and column order."""
    if not csv_path.exists():
        return {}, []

    data: Dict[str, Dict[str, int]] = {}
    with csv_path.open(newline="") as fp:
        reader = csv.DictReader(fp)
        if reader.fieldnames is None:
            return {}, []

        columns = [col for col in reader.fieldnames if col != "date"]
        for row in reader:
            date_key = row.get("date")
            if not date_key:
                continue
            totals: Dict[str, int] = {}
            for col in columns:
                raw = (row.get(col) or "").strip()
                if raw:
                    try:
                        totals[col] = int(raw)
                    except ValueError:
                        raise ValueError(f"Non-numeric value for column '{col}' on {date_key!r}")
            data[date_key] = totals

        return data, columns


def _timestamp_to_date(timestamp_ms: str) -> str:
    """Convert a millisecond epoch string to an ISO date (UTC)."""
    try:
        ts = int(timestamp_ms)
    except ValueError as exc:
        raise ValueError(f"Invalid timestamp in snapshot filename: {timestamp_ms!r}") from exc

    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    return dt.date().isoformat()


def _rollup_snapshot(path: Path) -> Tuple[str, Dict[str, int]]:
    """Return the date string and totals found in a snapshot JSON file."""
    stem = path.stem  # e.g. "snapshot_1760327682560"
    if not stem.startswith("snapshot_"):
        raise ValueError(f"Unexpected snapshot filename: {path.name}")
    timestamp_ms = stem.split("_", 1)[1]
    day = _timestamp_to_date(timestamp_ms)

    with path.open() as fp:
        payload = json.load(fp)

    totals = payload.get("totals")
    if not isinstance(totals, dict):
        raise ValueError(f"Snapshot {path.name} missing 'totals' dict")

    parsed: Dict[str, int] = {}
    for key, value in totals.items():
        try:
            parsed[key] = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid total for '{key}' in {path.name}: {value!r}") from exc

    return day, parsed


def _write_csv(csv_path: Path, data: Dict[str, Dict[str, int]], columns: List[str]) -> None:
    """Persist the aggregated data back to CSV."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["date"] + columns

    with csv_path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for day in sorted(data.keys()):
            row = {"date": day}
            totals = data.get(day, {})
            for col in columns:
                row[col] = totals.get(col, 0)
            writer.writerow(row)


def main() -> int:
    csv_path = BASE_DIR / CSV_FILENAME
    snapshots = sorted(BASE_DIR.glob(SNAPSHOT_GLOB))
    if not snapshots and not csv_path.exists():
        # Ensure the CSV file is present even if there is nothing to process.
        _write_csv(csv_path, {}, [])
        print("No snapshot files found. Created empty snapshots.csv.")
        return 0

    aggregated, column_order = _load_existing(csv_path)
    seen_columns = set(column_order)
    processed: List[Path] = []

    for snapshot in snapshots:
        try:
            day, totals = _rollup_snapshot(snapshot)
        except ValueError as exc:
            print(f"Skipping {snapshot.name}: {exc}", file=sys.stderr)
            continue

        day_totals = aggregated.setdefault(day, {})
        for key, value in totals.items():
            day_totals[key] = day_totals.get(key, 0) + value
            if key not in seen_columns:
                seen_columns.add(key)
                column_order.append(key)

        processed.append(snapshot)

    if processed:
        _write_csv(csv_path, aggregated, column_order)

        for snapshot in processed:
            bak_path = snapshot.with_name(snapshot.name + ".bak")
            snapshot.replace(bak_path)
        print(f"Rolled up {len(processed)} snapshot(s) into {csv_path.name}.")
    else:
        if not csv_path.exists():
            _write_csv(csv_path, aggregated, column_order)
        print("No new snapshots to process.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

