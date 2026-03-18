from __future__ import annotations

import copy
import importlib.util
from datetime import datetime
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("router_log_analyze.py")
MODULE_SPEC = importlib.util.spec_from_file_location("router_log_analyze", MODULE_PATH)
assert MODULE_SPEC is not None
assert MODULE_SPEC.loader is not None
analyzer = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(analyzer)


def seed_epoch(store: analyzer.StateStore) -> int:
    store.conn.execute(
        """
        INSERT INTO baseline_epochs(created_at, source_path, source_hash, label, is_active)
        VALUES(?, ?, ?, ?, 1)
        """,
        ("2026-03-01T00:00:00Z", None, None, "test"),
    )
    store.conn.commit()
    row = store.get_active_epoch()
    assert row is not None
    return int(row["id"])


def insert_history_day(
    store: analyzer.StateStore,
    epoch_id: int,
    file_hash: str,
    observed_date: str,
    mac: str,
    event_key: str,
    event_family: str,
    timestamps: list[str],
) -> None:
    run_id = store.insert_run(
        epoch_id=epoch_id,
        policy_profile_id=None,
        file_hash=file_hash,
        source_path=Path(f"/tmp/{file_hash}.log"),
        parse_stats=analyzer.ParseStats(parsed_events=len(timestamps)),
        observation_start=timestamps[0],
        observation_end=timestamps[-1],
        observed_dates=[observed_date],
        risk_score=0,
        status="Clean",
        is_partial=False,
    )
    device_stat = analyzer.DeviceDayAggregate(observed_date=observed_date, mac=mac)
    event_stat = analyzer.EventDayAggregate(
        observed_date=observed_date,
        mac=mac,
        event_key=event_key,
        event_family=event_family,
    )
    for timestamp_iso in timestamps:
        event = analyzer.Event(
            timestamp=datetime.fromisoformat(timestamp_iso),
            mac=mac,
            event_family=event_family,
            event_key=event_key,
            ip=None,
            raw_label=event_key,
            raw_line="",
            source="test",
        )
        device_stat.add_event(event)
        event_stat.add_event(event)
    store.insert_device_daily_stat(run_id, epoch_id, device_stat, True, None)
    store.insert_device_event_daily_stat(run_id, epoch_id, event_stat, True, None)
    store.conn.commit()


def make_current_stat(
    observed_date: str,
    mac: str,
    event_key: str,
    event_family: str,
    timestamps: list[str],
) -> analyzer.EventDayAggregate:
    stat = analyzer.EventDayAggregate(
        observed_date=observed_date,
        mac=mac,
        event_key=event_key,
        event_family=event_family,
    )
    for timestamp_iso in timestamps:
        stat.add_event(
            analyzer.Event(
                timestamp=datetime.fromisoformat(timestamp_iso),
                mac=mac,
                event_family=event_family,
                event_key=event_key,
                ip=None,
                raw_label=event_key,
                raw_line="",
                source="test",
            )
        )
    return stat


def test_weekday_drift_is_suppressed_without_enough_history(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "48:5F:2D:FF:49:7B"
        event_key = "WLAN_ACCESS_ALLOWED"
        event_family = "WLAN_ALLOWED"
        insert_history_day(
            store,
            epoch_id,
            "history-1",
            "2026-03-16",
            mac,
            event_key,
            event_family,
            ["2026-03-16T03:58:31"],
        )
        current_stat = make_current_stat(
            "2026-03-17",
            mac,
            event_key,
            event_family,
            ["2026-03-17T03:58:31"],
        )
        aggregate = {"event_day_stats": {("2026-03-17", mac, event_key): current_stat}}
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_event_behavior_anomalies(aggregate, store, epoch_id, policy)

        assert findings == []
    finally:
        store.close()


def test_weekday_drift_appears_after_minimum_history(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "48:5F:2D:FF:49:7B"
        event_key = "WLAN_ACCESS_ALLOWED"
        event_family = "WLAN_ALLOWED"
        history_dates = ["2026-02-16", "2026-02-23", "2026-03-02", "2026-03-09"]
        for index, history_date in enumerate(history_dates, start=1):
            insert_history_day(
                store,
                epoch_id,
                f"history-{index}",
                history_date,
                mac,
                event_key,
                event_family,
                [f"{history_date}T03:58:31"],
            )
        current_stat = make_current_stat(
            "2026-03-17",
            mac,
            event_key,
            event_family,
            ["2026-03-17T03:58:31"],
        )
        aggregate = {"event_day_stats": {("2026-03-17", mac, event_key): current_stat}}
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_event_behavior_anomalies(aggregate, store, epoch_id, policy)

        assert len(findings) == 1
        assert findings[0].metadata["reasons"] == ["weekday drift"]
        assert findings[0].metadata["history_count"] == 4
        assert findings[0].metadata["dominant_weekdays"] == [0]
        assert findings[0].metadata["current_weekday"] == 1
    finally:
        store.close()


def test_timing_detail_lines_show_observed_and_expected_hours() -> None:
    lines = analyzer.finding_detail_lines(
        {
            "kind": "timing_anomaly",
            "rendered_message": "Timing drift for MacBook Pro on 2026-03-17: 1.0 hour(s) outside the expected window.",
            "metadata": {
                "day": "2026-03-17",
                "hours": ["2026-03-17T10:43:39"],
                "expected_active_hours": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 20, 21, 22, 23],
            },
        }
    )

    assert "Observed: 10:43:39 AM" in lines
    assert "Expected active hours: 12:00 AM-9:59 AM, 8:00 PM-11:59 PM" in lines


def test_event_behavior_detail_lines_show_observed_and_learned_times() -> None:
    lines = analyzer.finding_detail_lines(
        {
            "kind": "event_behavior_anomaly",
            "rendered_message": "WLAN Access Allowed behavior for Kevin iPhone 17 Pro Max on 2026-03-17 changed: time shift 2.0h.",
            "metadata": {
                "reasons": ["time shift 2.0h", "weekday drift"],
                "observed_timestamps": ["2026-03-17T11:22:50"],
                "typical_hour": 9.0,
                "history_count": 4,
                "dominant_weekdays": [0],
                "current_weekday": 1,
            },
        }
    )

    assert "Observed weekday: Tuesday" in lines
    assert "Learned weekday pattern: Monday from 4 prior day(s)" in lines
    assert "Observed times: 11:22:50 AM" in lines
    assert "Learned typical time: around 9:00 AM from 4 prior day(s)" in lines
