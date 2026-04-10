from __future__ import annotations

import copy
import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest


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


def make_aggregate(
    mac_to_name: dict[str, str] | None = None,
    devices_snapshot: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "mac_to_name": mac_to_name or {},
        "devices_snapshot": devices_snapshot or {},
        "events_by_mac": {},
        "observation_range": {"start": None, "end": None},
        "events_per_hour": {},
    }


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
            "rendered_message": "Timing drift for MacBook Pro on 2026-03-17: 1 hour outside the expected window.",
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
            "rendered_message": "WLAN Access Allowed behavior for Kevin iPhone 17 Pro Max on 2026-03-17 changed: time shift 2 hours.",
            "metadata": {
                "reasons": ["time shift 2 hours", "weekday drift"],
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


def test_render_finding_message_formats_small_timing_drift_as_minutes() -> None:
    finding = analyzer.Finding(
        kind="timing_anomaly",
        severity="low",
        mac="A4:7E:FA:26:2D:0A",
        message="",
        metadata={
            "day": "2026-03-18",
            "distance_hours": 0.05,
        },
    )

    rendered = analyzer.render_finding_message(
        finding,
        {"mac_to_name": {"A4:7E:FA:26:2D:0A": "Withings Scale"}},
    )

    assert rendered == (
        "Timing drift for Withings Scale (A4:7E:FA:26:2D:0A) on 2026-03-18: "
        "3 minutes outside the expected window."
    )


def test_format_duration_hours_normalizes_subhour_and_mixed_durations() -> None:
    assert analyzer.format_duration_hours(0.05) == "3 minutes"
    assert analyzer.format_duration_hours(1.0) == "1 hour"
    assert analyzer.format_duration_hours(2.5) == "2 hours 30 minutes"


def test_help_examples_use_invoked_program_name(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(analyzer.sys, "argv", ["/tmp/custom-router-tool"])

    with pytest.raises(SystemExit):
        analyzer.parse_args(["--help"])

    output = capsys.readouterr().out
    assert "custom-router-tool router-log.pdf" in output
    assert "./router_log_analyze.py" not in output


def test_ensure_private_venv_rebuilds_when_existing_python_fails_health_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime-home"
    venv_dir = home / "venv"
    venv_python = venv_dir / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    home.mkdir(exist_ok=True)
    bootstrap_state = home / analyzer.CONFIG_FILENAME
    bootstrap_state.write_text(
        json.dumps(analyzer.desired_bootstrap_state()),
        encoding="utf-8",
    )
    paths = analyzer.RuntimePaths(
        home=home,
        venv=venv_dir,
        venv_python=venv_python,
        bootstrap_state=bootstrap_state,
        db=home / analyzer.DB_FILENAME,
    )
    refresh_events: list[tuple[str, Path]] = []

    class FakeEnvBuilder:
        def __init__(self, *, with_pip: bool) -> None:
            assert with_pip is True

        def create(self, target: Path) -> None:
            refresh_events.append(("create", target))
            (target / "bin").mkdir(parents=True, exist_ok=True)
            (target / "bin" / "python").write_text("", encoding="utf-8")

    def fake_install_runtime_dependencies(runtime_paths: analyzer.RuntimePaths) -> None:
        refresh_events.append(("install", runtime_paths.venv))

    def fake_write_bootstrap_state(runtime_paths: analyzer.RuntimePaths) -> None:
        refresh_events.append(("write_state", runtime_paths.bootstrap_state))

    def fake_execv(executable: str, argv: list[str]) -> None:
        refresh_events.append(("execv", Path(executable)))
        raise RuntimeError("stop after execv")

    monkeypatch.setattr(analyzer.sys, "prefix", str(tmp_path / "outside-venv"))
    monkeypatch.setattr(analyzer.subprocess, "run", lambda *args, **kwargs: type("Result", (), {"returncode": 134})())
    monkeypatch.setattr(analyzer.venv, "EnvBuilder", FakeEnvBuilder)
    monkeypatch.setattr(analyzer, "install_runtime_dependencies", fake_install_runtime_dependencies)
    monkeypatch.setattr(analyzer, "write_bootstrap_state", fake_write_bootstrap_state)
    monkeypatch.setattr(analyzer.os, "execv", fake_execv)

    with pytest.raises(RuntimeError, match="stop after execv"):
        analyzer.ensure_private_venv(paths)

    assert ("create", venv_dir) in refresh_events
    assert ("install", venv_dir) in refresh_events
    assert ("write_state", bootstrap_state) in refresh_events
    assert ("execv", venv_python) in refresh_events


def test_parse_log_text_scrapes_unknown_event_labels_without_whitelist() -> None:
    events, stats = analyzer.parse_log_text(
        "[vpn handshake retry] from source 192.168.1.25, Saturday, March 21, 2026 08:32:33",
        source="test",
    )

    assert stats.parsed_events == 1
    assert events[0].event_key == "VPN_HANDSHAKE_RETRY"
    assert events[0].event_family == "OTHER"
    assert events[0].mac == analyzer.SYSTEM_ACTOR
    assert events[0].ip == "192.168.1.25"


def test_parse_log_text_reconstructs_wrapped_access_rejection_timestamp() -> None:
    events, stats = analyzer.parse_log_text(
        "\n".join(
            [
                "[WLAN access rejected: incorrect security] from MAC address 5C:AD:BA:2D:73:1B, Wednesday, March 25, 2026",
                "13:11:47",
            ]
        ),
        source="test",
    )

    assert stats.parsed_events == 1
    assert stats.malformed_lines == 0
    assert events[0].event_key == "WLAN_ACCESS_REJECTED"
    assert events[0].event_family == "WLAN_REJECTED"
    assert events[0].mac == "5C:AD:BA:2D:73:1B"
    assert events[0].timestamp == datetime(2026, 3, 25, 13, 11, 47)


def test_parse_log_text_ignores_wrapped_access_control_status_line() -> None:
    events, stats = analyzer.parse_log_text(
        "\n".join(
            [
                "[Access Control] Device RokuUltra with MAC Address d8:31:34:5c:ce:8c is allowed to access the, Thursday, April",
                "02, 2026 04:18:12",
            ]
        ),
        source="test",
    )

    assert events == []
    assert stats.parsed_events == 0
    assert stats.malformed_lines == 0
    assert stats.ignored_lines == 1
    assert stats.malformed_samples == []


def test_parse_log_text_ignores_truncated_wrapped_access_control_status_line() -> None:
    events, stats = analyzer.parse_log_text(
        "\n".join(
            [
                "[Access Control] Device Etekcity-Outlet with MAC Address 2c:3a:e8:20:82:b8 is allowed to acce, Thursday, April 02,",
                "2026 04:18:12",
            ]
        ),
        source="test",
    )

    assert events == []
    assert stats.parsed_events == 0
    assert stats.malformed_lines == 0
    assert stats.ignored_lines == 1


def test_parse_log_text_ignores_severely_truncated_access_control_status_line() -> None:
    events, stats = analyzer.parse_log_text(
        "[Access Control] Device android-a7a560af9888aea8 with MAC Address 54:78:c9:92:92:12 is allowe, Thursday, April 02, 2026 04:18:12",
        source="test",
    )

    assert events == []
    assert stats.parsed_events == 0
    assert stats.malformed_lines == 0
    assert stats.ignored_lines == 1


def test_aggregate_events_attributes_ip_only_events_to_known_dhcp_mac() -> None:
    events, stats = analyzer.parse_log_text(
        "\n".join(
            [
                "[DHCP IP: (192.168.1.25)] to MAC address 92:ef:df:17:9a:49, Saturday, March 21, 2026 08:07:26",
                "[admin login] from source 192.168.1.25, Saturday, March 21, 2026 08:32:33",
            ]
        ),
        source="test",
    )

    assert stats.parsed_events == 2

    aggregate = analyzer.aggregate_events(
        events,
        {"devices": {"92:EF:DF:17:9A:49": {"name": "MacBook Pro"}}},
        {"92:EF:DF:17:9A:49": {"name": "MacBook Pro"}},
    )
    by_key = {event.event_key: event for event in aggregate["events"]}
    summary = {item["mac"]: item for item in analyzer.summarize_devices(aggregate)}

    assert by_key["ADMIN_LOGIN"].mac == "92:EF:DF:17:9A:49"
    assert summary["92:EF:DF:17:9A:49"]["total_events"] == 2
    assert "ADMIN_LOGIN" in summary["92:EF:DF:17:9A:49"]["event_types"]
    assert "__SYSTEM__" not in summary


def test_new_event_type_is_reported_when_device_has_history_but_event_is_new(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "92:EF:DF:17:9A:49"
        for index, history_date in enumerate(["2026-03-17", "2026-03-18", "2026-03-19"], start=1):
            insert_history_day(
                store,
                epoch_id,
                f"history-{index}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                [f"{history_date}T08:07:26"],
            )
        current_stat = make_current_stat(
            "2026-03-21",
            mac,
            "ADMIN_LOGIN",
            "OTHER",
            ["2026-03-21T08:32:33"],
        )
        aggregate = {"event_day_stats": {("2026-03-21", mac, "ADMIN_LOGIN"): current_stat}}
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_new_event_types(aggregate, store, epoch_id, policy)

        assert len(findings) == 1
        assert findings[0].kind == "new_event_type"
        assert findings[0].severity == "medium"
        assert findings[0].metadata["event_key"] == "ADMIN_LOGIN"
        assert findings[0].metadata["history_count"] == 3
    finally:
        store.close()


def test_new_event_type_single_wlan_access_allowed_for_configured_device_is_low(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "92:EF:DF:17:9A:49"
        for index, history_date in enumerate(["2026-03-17", "2026-03-18", "2026-03-19"], start=1):
            insert_history_day(
                store,
                epoch_id,
                f"history-{index}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                [f"{history_date}T08:07:26"],
            )
        current_stat = make_current_stat(
            "2026-03-21",
            mac,
            "WLAN_ACCESS_ALLOWED",
            "WLAN_ALLOWED",
            ["2026-03-21T08:32:33"],
        )
        aggregate = {
            "event_day_stats": {("2026-03-21", mac, "WLAN_ACCESS_ALLOWED"): current_stat},
            "devices_snapshot": {
                mac: {
                    "status": "allowed",
                    "source": "config_import",
                }
            },
        }
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_new_event_types(aggregate, store, epoch_id, policy)

        assert len(findings) == 1
        assert findings[0].kind == "new_event_type"
        assert findings[0].severity == "low"
    finally:
        store.close()


def test_new_event_type_repeated_wlan_access_allowed_for_configured_device_stays_medium(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "92:EF:DF:17:9A:49"
        for index, history_date in enumerate(["2026-03-17", "2026-03-18", "2026-03-19"], start=1):
            insert_history_day(
                store,
                epoch_id,
                f"history-{index}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                [f"{history_date}T08:07:26"],
            )
        current_stat = make_current_stat(
            "2026-03-21",
            mac,
            "WLAN_ACCESS_ALLOWED",
            "WLAN_ALLOWED",
            ["2026-03-21T08:32:33", "2026-03-21T08:33:00"],
        )
        aggregate = {
            "event_day_stats": {("2026-03-21", mac, "WLAN_ACCESS_ALLOWED"): current_stat},
            "devices_snapshot": {
                mac: {
                    "status": "allowed",
                    "source": "config_import",
                }
            },
        }
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_new_event_types(aggregate, store, epoch_id, policy)

        assert len(findings) == 1
        assert findings[0].kind == "new_event_type"
        assert findings[0].severity == "medium"
    finally:
        store.close()


def test_new_event_type_detail_lines_show_observed_times_and_history() -> None:
    lines = analyzer.finding_detail_lines(
        {
            "kind": "new_event_type",
            "rendered_message": "Admin Login was first observed for MacBook Pro on 2026-03-21.",
            "metadata": {
                "history_count": 3,
                "observed_timestamps": ["2026-03-21T08:32:33"],
            },
        }
    )

    assert "Observed times: 8:32:33 AM" in lines
    assert "No prior occurrences in 3 learned day(s) for this device" in lines


def test_single_wlan_access_allowed_behavior_for_configured_device_is_capped_to_low(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "48:5F:2D:FF:49:7B"
        insert_history_day(
            store,
            epoch_id,
            "history-1",
            "2026-03-16",
            mac,
            "WLAN_ACCESS_ALLOWED",
            "WLAN_ALLOWED",
            ["2026-03-16T08:00:00"],
        )
        current_stat = make_current_stat(
            "2026-03-17",
            mac,
            "WLAN_ACCESS_ALLOWED",
            "WLAN_ALLOWED",
            ["2026-03-17T13:00:00"],
        )
        aggregate = {
            "event_day_stats": {("2026-03-17", mac, "WLAN_ACCESS_ALLOWED"): current_stat},
            "mac_to_name": {mac: "Kindle Paperwhite"},
            "devices_snapshot": {
                mac: {
                    "status": "allowed",
                    "source": "config_import",
                }
            },
        }
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_event_behavior_anomalies(aggregate, store, epoch_id, policy)

        assert len(findings) == 1
        assert findings[0].kind == "event_behavior_anomaly"
        assert findings[0].severity == "low"
        assert findings[0].metadata["reasons"] == ["time shift 5 hours"]
    finally:
        store.close()


def test_compute_risk_score_deduplicates_correlated_event_findings() -> None:
    findings = {
        "all": [
            analyzer.Finding(
                kind="new_event_type",
                severity="medium",
                mac="5C:AD:BA:2D:73:1B",
                message="",
                metadata={
                    "day": "2026-03-25",
                    "event_key": "WLAN_ACCESS_REJECTED",
                    "event_family": "WLAN_REJECTED",
                },
            ),
            analyzer.Finding(
                kind="event_behavior_anomaly",
                severity="low",
                mac="5C:AD:BA:2D:73:1B",
                message="",
                metadata={
                    "day": "2026-03-25",
                    "event_key": "WLAN_ACCESS_REJECTED",
                    "event_family": "WLAN_REJECTED",
                    "reasons": ["time shift 5 minutes"],
                },
            ),
            analyzer.Finding(
                kind="dhcp_anomaly",
                severity="low",
                mac="5C:AD:BA:2D:73:1B",
                message="",
                metadata={"day": "2026-03-25"},
            ),
        ]
    }
    policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

    score, status, breakdown = analyzer.compute_risk_score(findings, policy)

    assert score == 12
    assert status == "Clean"
    assert breakdown == {"new_event_type": 10, "dhcp_anomaly": 2}


def test_compute_risk_score_deduplicates_same_day_cluster_findings() -> None:
    findings = {
        "all": [
            analyzer.Finding(
                kind="cluster_anomaly",
                severity="medium",
                mac=None,
                message="cluster anomaly 1",
                metadata={
                    "cluster": "Etekcity_Outlets",
                    "day": "2026-03-25",
                    "occurrence_index": 0,
                    "start": "2026-03-25T16:06:21",
                },
            ),
            analyzer.Finding(
                kind="cluster_anomaly",
                severity="medium",
                mac=None,
                message="cluster anomaly 2",
                metadata={
                    "cluster": "Etekcity_Outlets",
                    "day": "2026-03-25",
                    "occurrence_index": 1,
                    "start": "2026-03-25T23:15:26",
                },
            ),
        ]
    }
    policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

    score, status, breakdown = analyzer.compute_risk_score(findings, policy)

    assert score == 12
    assert status == "Clean"
    assert breakdown == {"cluster_anomaly": 12}


def test_enforce_policy_severity_supports_maximum_and_suppress() -> None:
    policy = copy.deepcopy(analyzer.DEFAULT_POLICY)
    policy["event_overrides"]["WLAN_ACCESS_REJECTED"] = {"maximum_severity": "low"}
    policy["device_overrides"]["5C:AD:BA:2D:73:1B"] = {"suppress": True}

    assert (
        analyzer.enforce_policy_severity(
            "medium",
            policy,
            event_key="WLAN_ACCESS_REJECTED",
            event_family="WLAN_REJECTED",
        )
        == "low"
    )
    assert (
        analyzer.enforce_policy_severity(
            "critical",
            policy,
            mac="5C:AD:BA:2D:73:1B",
            event_key="WLAN_ACCESS_REJECTED",
            event_family="WLAN_REJECTED",
        )
        == "normal"
    )


def test_enforce_policy_severity_supports_finding_specific_device_and_cluster_caps() -> None:
    policy = copy.deepcopy(analyzer.DEFAULT_POLICY)
    policy["device_overrides"]["5C:AD:BA:2D:73:1B"] = {
        "finding_overrides": {
            "event_volume_anomaly": {"maximum_severity": "low"}
        }
    }
    policy["device_name_overrides"]["Kevin iPhone 17 Pro Max"] = {
        "finding_overrides": {
            "event_volume_anomaly": {"maximum_severity": "low"}
        }
    }
    policy["cluster_overrides"]["Etekcity_Outlets"] = {
        "finding_overrides": {
            "cluster_anomaly": {"maximum_severity": "low"}
        }
    }

    assert (
        analyzer.enforce_policy_severity(
            "medium",
            policy,
            mac="5C:AD:BA:2D:73:1B",
            finding_kind="event_volume_anomaly",
        )
        == "low"
    )
    assert (
        analyzer.enforce_policy_severity(
            "medium",
            policy,
            device_name="Kevin iPhone 17 Pro Max",
            finding_kind="event_volume_anomaly",
        )
        == "low"
    )
    assert (
        analyzer.enforce_policy_severity(
            "medium",
            policy,
            mac="5C:AD:BA:2D:73:1B",
            finding_kind="new_event_type",
        )
        == "medium"
    )
    assert (
        analyzer.enforce_policy_severity(
            "medium",
            policy,
            event_key="DHCP_IP",
            event_family="DHCP",
            finding_kind="cluster_anomaly",
            cluster_name="Etekcity_Outlets",
        )
        == "low"
    )


def test_detect_unknown_devices_respects_device_suppression() -> None:
    mac = "AA:BB:CC:DD:EE:FF"
    aggregate = {
        "events_by_mac": {
            mac: [
                analyzer.Event(
                    timestamp=datetime(2026, 3, 25, 13, 11, 47),
                    mac=mac,
                    event_family="OTHER",
                    event_key="ADMIN_LOGIN",
                    ip=None,
                    raw_label="admin login",
                    raw_line="",
                    source="test",
                )
            ]
        },
        "cluster_profiles": {},
    }
    policy = copy.deepcopy(analyzer.DEFAULT_POLICY)
    policy["device_overrides"][mac] = {"suppress": True}

    findings = analyzer.detect_unknown_devices(aggregate, {"devices": {}}, {}, policy)

    assert findings == []


def test_detect_device_metric_anomalies_respects_event_volume_cap(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "5C:AD:BA:2D:73:1B"
        for index, history_date in enumerate(["2026-03-17", "2026-03-18", "2026-03-19"], start=1):
            insert_history_day(
                store,
                epoch_id,
                f"history-{index}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                [f"{history_date}T08:07:26", f"{history_date}T08:10:00", f"{history_date}T08:12:00"],
            )
        current_device_stat = analyzer.DeviceDayAggregate(observed_date="2026-03-25", mac=mac)
        for minute in range(10):
            current_device_stat.add_event(
                analyzer.Event(
                    timestamp=datetime(2026, 3, 25, 13, minute, 0),
                    mac=mac,
                    event_family="DHCP",
                    event_key="DHCP_IP",
                    ip=f"192.168.1.{minute + 10}",
                    raw_label="DHCP IP",
                    raw_line="",
                    source="test",
                )
            )
        aggregate = {
            "device_day_stats": {("2026-03-25", mac): current_device_stat},
            "mac_to_name": {mac: "Kevin iPhone 17 Pro Max"},
        }
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)
        policy["device_overrides"][mac] = {
            "finding_overrides": {"event_volume_anomaly": {"maximum_severity": "low"}}
        }

        findings = analyzer.detect_device_metric_anomalies(aggregate, {"devices": {}}, store, epoch_id, policy)
        event_volume = next(finding for finding in findings if finding.kind == "event_volume_anomaly")

        assert event_volume.severity == "low"
    finally:
        store.close()


def test_detect_device_metric_anomalies_respects_device_name_event_volume_cap(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "4A:1E:F3:D6:C8:F9"
        device_name = "Kevin iPhone 17 Pro Max"
        for index, history_date in enumerate(["2026-03-17", "2026-03-18", "2026-03-19"], start=1):
            insert_history_day(
                store,
                epoch_id,
                f"name-history-{index}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                [f"{history_date}T08:07:26", f"{history_date}T08:10:00", f"{history_date}T08:12:00"],
            )
        current_device_stat = analyzer.DeviceDayAggregate(observed_date="2026-03-25", mac=mac)
        for minute in range(10):
            current_device_stat.add_event(
                analyzer.Event(
                    timestamp=datetime(2026, 3, 25, 13, minute, 0),
                    mac=mac,
                    event_family="DHCP",
                    event_key="DHCP_IP",
                    ip=f"192.168.1.{minute + 30}",
                    raw_label="DHCP IP",
                    raw_line="",
                    source="test",
                )
            )
        aggregate = {
            "device_day_stats": {("2026-03-25", mac): current_device_stat},
            "mac_to_name": {mac: device_name},
        }
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)
        policy["device_name_overrides"][device_name] = {
            "finding_overrides": {"event_volume_anomaly": {"maximum_severity": "low"}}
        }

        findings = analyzer.detect_device_metric_anomalies(aggregate, {"devices": {}}, store, epoch_id, policy)
        event_volume = next(finding for finding in findings if finding.kind == "event_volume_anomaly")

        assert event_volume.severity == "low"
    finally:
        store.close()


def test_detect_cluster_anomalies_respects_cluster_cap(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        stat = analyzer.SubjectBehaviorDayAggregate(
            observed_date="2026-03-25",
            subject_key="Etekcity_Outlets",
            subject_type="group",
            behavior_key="DHCP_IP",
            behavior_family="DHCP",
        )
        stat.add_occurrence(
            start=datetime(2026, 3, 25, 16, 6, 21),
            end=datetime(2026, 3, 25, 16, 8, 28),
            size=4,
            context={
                "member_macs": [
                    "2C:3A:E8:20:9F:4F",
                    "2C:3A:E8:23:00:44",
                    "60:01:94:45:A5:85",
                    "2C:3A:E8:20:82:B8",
                ],
                "member_events": [
                    {"name": "Etekcity-Outlet", "mac": "2C:3A:E8:20:9F:4F", "timestamp": "2026-03-25T16:06:21"},
                    {"name": "Etekcity-Outlet", "mac": "2C:3A:E8:23:00:44", "timestamp": "2026-03-25T16:07:23"},
                ],
            },
        )
        aggregate = {
            "subject_behavior_day_stats": {
                ("2026-03-25", "Etekcity_Outlets", "group", "DHCP_IP"): stat
            },
            "cluster_profiles": {
                "Etekcity_Outlets": {
                    "cluster_size": 4,
                    "expected_windows": [{"start_hour": 1.75, "end_hour": 2.0}],
                }
            },
            "mac_to_name": {
                "2C:3A:E8:20:9F:4F": "Etekcity-Outlet",
                "2C:3A:E8:23:00:44": "Etekcity-Outlet",
            },
        }
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)
        policy["cluster_overrides"]["Etekcity_Outlets"] = {
            "finding_overrides": {"cluster_anomaly": {"maximum_severity": "low"}}
        }

        findings = analyzer.detect_cluster_anomalies(aggregate, store, epoch_id, policy)

        assert findings
        assert all(finding.severity == "low" for finding in findings)
    finally:
        store.close()


def test_build_priority_findings_surfaces_security_events_first() -> None:
    mac = "5C:AD:BA:2D:73:1B"
    findings = {
        "critical": [],
        "observations": [
            analyzer.Finding(
                kind="event_volume_anomaly",
                severity="low",
                mac=mac,
                message="",
                metadata={
                    "day": "2026-03-25",
                    "expected_range": [1.0, 3.0],
                    "direction": "above",
                    "learned_mean": 2.0,
                    "trend": "flat",
                },
            )
        ],
        "anomalies": [
            analyzer.Finding(
                kind="cluster_anomaly",
                severity="medium",
                mac=None,
                message="",
                metadata={
                    "cluster": "Etekcity_Outlets",
                    "day": "2026-03-25",
                    "distance_minutes": 581,
                    "member_events": [
                        {"name": "Etekcity-Outlet", "mac": "2C:3A:E8:23:00:44", "timestamp": "2026-03-25T16:07:23"}
                    ],
                },
            ),
            analyzer.Finding(
                kind="new_event_type",
                severity="medium",
                mac=mac,
                message="",
                metadata={
                    "day": "2026-03-25",
                    "event_key": "WLAN_ACCESS_REJECTED",
                    "event_family": "WLAN_REJECTED",
                    "history_count": 8,
                    "observed_timestamps": ["2026-03-25T13:11:47"],
                },
            ),
        ],
        "all": [],
    }
    findings["all"] = findings["observations"] + findings["anomalies"]
    aggregate = make_aggregate({mac: "Kevin iPhone 17 Pro Max"})

    findings_dict = analyzer.findings_to_dict(findings, aggregate)
    priority = analyzer.build_priority_findings(findings_dict)

    assert priority[0]["kind"] == "new_event_type"
    assert "WLAN Access Rejected" in priority[0]["rendered_message"]


def test_cluster_partial_visibility_detail_lines_do_not_report_zero_minutes() -> None:
    lines = analyzer.finding_detail_lines(
        {
            "kind": "cluster_anomaly",
            "severity": "low",
            "event_count": 1,
            "rendered_message": "",
            "metadata": {
                "cluster": "Etekcity_Outlets",
                "day": "2026-03-25",
                "expected_size": 4,
                "min_cluster_size": 2,
                "member_events": [
                    {"name": "Etekcity-Outlet", "mac": "2C:3A:E8:23:00:44", "timestamp": "2026-03-25T23:15:26"}
                ],
            },
        }
    )

    assert lines[0] == "Etekcity_Outlets on 2026-03-25: observed 1 of expected 4 device(s)."
    assert all("0 minutes outside expected timing" not in line for line in lines)


def test_render_text_report_places_priority_findings_before_observations() -> None:
    report = {
        "parse_stats": {
            "parsed_events": 1,
            "malformed_lines": 0,
            "duplicate_events": 0,
            "spam_filtered": 0,
            "export_noise_lines": 0,
            "malformed_samples": [],
        },
        "observation_range": {"start": "2026-03-25T13:11:47", "end": "2026-03-25T13:11:47"},
        "state": {"deduplicated": False},
        "inputs": {"db": "/tmp/network.db"},
        "risk_score": 10,
        "status": "Clean",
        "risk_breakdown": {"new_event_type": 10},
        "priority_findings": [
            {
                "kind": "new_event_type",
                "severity": "medium",
                "rendered_message": "WLAN Access Rejected was first observed for Kevin iPhone 17 Pro Max on 2026-03-25.",
                "metadata": {
                    "history_count": 8,
                    "observed_timestamps": ["2026-03-25T13:11:47"],
                },
            }
        ],
        "findings": {
            "critical": [],
            "anomalies": [],
            "observations": [
                {
                    "kind": "event_volume_anomaly",
                    "severity": "low",
                    "rendered_message": "Daily event count for Kevin iPhone 17 Pro Max on 2026-03-25 was slightly above expected range.",
                    "metadata": {},
                }
            ],
        },
        "device_summary": [],
    }

    rendered = analyzer.render_text_report(report)

    assert rendered.index("Priority Findings") < rendered.index("Behavioral Observations (Low)")
    assert "WLAN Access Rejected was first observed" in rendered


def test_rare_event_activity_is_reported_for_repeat_sparse_other_event(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "92:EF:DF:17:9A:49"
        insert_history_day(
            store,
            epoch_id,
            "admin-login-history",
            "2026-03-17",
            mac,
            "ADMIN_LOGIN",
            "OTHER",
            ["2026-03-17T08:32:33"],
        )
        for index, history_date in enumerate(["2026-03-16", "2026-03-18", "2026-03-19", "2026-03-20"], start=1):
            insert_history_day(
                store,
                epoch_id,
                f"dhcp-history-{index}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                [f"{history_date}T08:07:26"],
            )
        current_stat = make_current_stat(
            "2026-03-21",
            mac,
            "ADMIN_LOGIN",
            "OTHER",
            ["2026-03-21T08:45:00"],
        )
        aggregate = {"event_day_stats": {("2026-03-21", mac, "ADMIN_LOGIN"): current_stat}}
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_rare_event_activity(aggregate, store, epoch_id, policy)

        assert len(findings) == 1
        assert findings[0].kind == "rare_event_activity"
        assert findings[0].severity == "medium"
        assert findings[0].metadata["history_count"] == 1
        assert findings[0].metadata["observed_device_days"] == 5
        assert findings[0].metadata["learned_presence_rate"] == 0.2
    finally:
        store.close()


def test_rare_event_activity_detail_lines_show_rarity_context() -> None:
    lines = analyzer.finding_detail_lines(
        {
            "kind": "rare_event_activity",
            "rendered_message": "Admin Login remains rare for MacBook Pro on 2026-03-21.",
            "metadata": {
                "history_count": 1,
                "observed_device_days": 5,
                "learned_presence_rate": 0.2,
                "observed_timestamps": ["2026-03-21T08:32:33"],
            },
        }
    )

    assert "Observed times: 8:32:33 AM" in lines
    assert "Learned rarity: 1 prior occurrence day(s) across 5 learned day(s) (20% presence)" in lines
