from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .models import HistoryEvent, ProviderScanResult
from .time_utils import to_local_human, to_local_iso


def render_scan_report(
    *,
    generated_at: str,
    command: str,
    format_name: str,
    provider_results: list[ProviderScanResult],
) -> str:
    if format_name == "json":
        return json.dumps(
            {
                "generated_at": to_local_iso(generated_at),
                "command": command,
                "providers": [_provider_result_json(result) for result in provider_results],
            },
            indent=2,
            sort_keys=True,
        )
    if format_name == "markdown":
        return _render_scan_markdown(generated_at=generated_at, command=command, provider_results=provider_results)
    return _render_scan_text(generated_at=generated_at, command=command, provider_results=provider_results)


def render_history_report(
    *,
    provider_id: str,
    model_id: str,
    format_name: str,
    first_seen: str | None,
    last_seen: str | None,
    events: tuple[HistoryEvent, ...],
    latest_model: dict[str, Any] | None = None,
) -> str:
    if format_name == "json":
        return json.dumps(
            {
                "provider_id": provider_id,
                "model_id": model_id,
                "first_seen": to_local_iso(first_seen),
                "last_seen": to_local_iso(last_seen),
                "latest_model": _normalize_latest_model_json(latest_model),
                "events": [
                    {
                        **asdict(event),
                        "detected_at": to_local_iso(event.detected_at),
                    }
                    for event in events
                ],
            },
            indent=2,
            sort_keys=True,
        )
    if format_name == "markdown":
        lines = [
            f"# History: {provider_id} / {model_id}",
            "",
            f"- First seen: {to_local_human(first_seen)}",
            f"- Last seen: {to_local_human(last_seen)}",
        ]
        if latest_model:
            lines.append(f"- Display name: {latest_model.get('display_name') or model_id}")
            lines.append(f"- Latest price in/out: {_format_price_pair(latest_model)}")
            cache_summary = _format_cache_prices(latest_model)
            if cache_summary:
                lines.append(f"- Latest cache pricing: {cache_summary}")
        lines.append("")
        if not events:
            lines.append("No saved change events matched the requested range.")
            return "\n".join(lines)
        lines.append("| Detected At | Kind | Field | Old | New |")
        lines.append("|---|---|---|---|---|")
        for event in events:
            lines.append(
                f"| {to_local_human(event.detected_at)} | {event.change_kind} | {event.field_name or ''} | "
                f"{_render_value(event.old_value)} | {_render_value(event.new_value)} |"
            )
        return "\n".join(lines)
    lines = [
        f"History for {provider_id} / {model_id}",
        f"First seen: {to_local_human(first_seen)}",
        f"Last seen: {to_local_human(last_seen)}",
    ]
    if latest_model:
        lines.append(f"Display name: {latest_model.get('display_name') or model_id}")
        lines.append(f"Latest price in/out: {_format_price_pair(latest_model)}")
        cache_summary = _format_cache_prices(latest_model)
        if cache_summary:
            lines.append(f"Latest cache pricing: {cache_summary}")
    lines.append("")
    if not events:
        lines.append("No saved change events matched the requested range.")
        return "\n".join(lines)
    for event in events:
        lines.append(
            f"- {to_local_human(event.detected_at)} [{event.change_kind}] "
            f"{event.field_name or ''} {_render_value(event.old_value)} -> {_render_value(event.new_value)}"
        )
    return "\n".join(lines)


def render_model_list_report(
    *,
    provider_id: str,
    format_name: str,
    models: tuple[dict[str, Any], ...],
) -> str:
    if format_name == "json":
        return json.dumps(
            {
                "provider_id": provider_id,
                "models": [
                    {
                        **row,
                        "first_seen": to_local_iso(row["first_seen"]),
                        "last_seen": to_local_iso(row["last_seen"]),
                    }
                    for row in models
                ],
            },
            indent=2,
            sort_keys=True,
        )
    if format_name == "markdown":
        lines = [
            f"# Models for {provider_id}",
            "",
            "| Model ID | Display Name | In Price | Out Price | First Seen | Last Seen |",
            "|---|---|---|---|---|---|",
        ]
        if not models:
            lines.append("| _none_ |  |  |  |  |  |")
            return "\n".join(lines)
        for row in models:
            lines.append(
                f"| {row['provider_model_id']} | {row['display_name'] or ''} | "
                f"{_format_number(row.get('input_price'))} | {_format_number(row.get('output_price'))} | "
                f"{to_local_human(row['first_seen']) if row['first_seen'] else ''} | "
                f"{to_local_human(row['last_seen']) if row['last_seen'] else ''} |"
            )
        return "\n".join(lines)
    lines = [f"Known models for {provider_id}", ""]
    if not models:
        lines.append("No saved models found for this provider.")
        return "\n".join(lines)
    grouped = _group_models_by_prefix(models)
    for prefix, rows in grouped:
        if prefix is None:
            for row in rows:
                lines.extend(_render_inline_model_row(row))
            continue
        if len(rows) == 1:
            lines.extend(_render_inline_model_row(rows[0]))
            continue
        lines.append(f"{prefix}/")
        for row in rows:
            suffix = row["provider_model_id"][len(prefix) + 1:]
            lines.append(f"  - {suffix}")
            price_summary = _format_price_pair(row)
            if price_summary != "n/a":
                lines.append(f"    price: {price_summary}")
            lines.append(f"    first: { _short_ts(row['first_seen']) }")
            lines.append(f"    last:  { _short_ts(row['last_seen']) }")
        lines.append("")
    return "\n".join(lines)


def render_providers_report(
    *,
    format_name: str,
    provider_rows: list[dict[str, Any]],
) -> str:
    if format_name == "json":
        normalized_rows = [
            {
                **row,
                "last_successful_scan": to_local_iso(row["last_successful_scan"]),
            }
            for row in provider_rows
        ]
        return json.dumps(normalized_rows, indent=2, sort_keys=True)
    if format_name == "markdown":
        lines = [
            "| Provider ID | Label | Kind | Enabled | Base URL | Models Path | Credential Env | Present | Last Successful Scan |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for row in provider_rows:
            lines.append(
                f"| {row['provider_id']} | {row['label']} | {row['kind']} | {row['enabled']} | "
                f"{row['base_url']} | {row['models_path']} | {row['credential_env_var']} | "
                f"{row['credential_present']} | {to_local_iso(row['last_successful_scan']) or 'none'} |"
            )
        return "\n".join(lines)
    lines = []
    for row in provider_rows:
        lines.extend(
            [
                f"{row['provider_id']} ({row['label']})",
                f"  kind: {row['kind']}",
                f"  enabled: {row['enabled']}",
                f"  base_url: {row['base_url']}",
                f"  models_path: {row['models_path']}",
                f"  credential_env_var: {row['credential_env_var']}",
                f"  credential_present: {row['credential_present']}",
                f"  last_successful_scan: {to_local_iso(row['last_successful_scan']) or 'none'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def render_healthcheck_report(*, format_name: str, checks: list[dict[str, Any]]) -> str:
    if format_name == "json":
        return json.dumps(checks, indent=2, sort_keys=True)
    if format_name == "markdown":
        lines = ["| Check | Status | Detail |", "|---|---|---|"]
        for check in checks:
            lines.append(f"| {check['check']} | {check['status']} | {check['detail']} |")
        return "\n".join(lines)
    return "\n".join(f"{check['status'].upper():7} {check['check']}: {check['detail']}" for check in checks)


def _provider_result_json(result: ProviderScanResult) -> dict[str, Any]:
    return {
        "provider_id": result.provider_id,
        "provider_label": result.provider_label,
        "status": result.status,
        "current_count": result.current_count,
        "saved": result.saved,
        "baseline": asdict(result.baseline) if result.baseline else None,
        "baseline_message": result.baseline_message,
        "scrape_id": result.scrape_id,
        "error_message": result.error_message,
        "added": [_delta_to_json(delta) for delta in result.added],
        "removed": [_delta_to_json(delta) for delta in result.removed],
        "changed": [_delta_to_json(delta) for delta in result.changed],
    }


def _delta_to_json(delta: Any) -> dict[str, Any]:
    return {
        "kind": delta.kind,
        "provider_model_id": delta.provider_model_id,
        "display_name": delta.display_name,
        "field_changes": [asdict(change) for change in delta.field_changes],
    }


def _render_scan_text(*, generated_at: str, command: str, provider_results: list[ProviderScanResult]) -> str:
    lines = [
        f"Model Sentinel report",
        f"Generated at: {to_local_human(generated_at)}",
        f"Command: {command}",
        "",
    ]
    for result in provider_results:
        lines.append(f"{result.provider_label} ({result.provider_id})")
        lines.append(f"  status: {result.status}")
        lines.append(f"  current_count: {result.current_count}")
        if result.baseline:
            lines.append(f"  baseline: scrape {result.baseline.scrape_id} at {to_local_human(result.baseline.completed_at)}")
        elif result.baseline_message:
            lines.append(f"  baseline: {result.baseline_message}")
        if result.error_message:
            lines.append(f"  error: {result.error_message}")
        lines.append(f"  added: {len(result.added)}")
        for delta in result.added:
            lines.append(f"    + {delta.provider_model_id} ({delta.display_name})")
        lines.append(f"  removed: {len(result.removed)}")
        for delta in result.removed:
            lines.append(f"    - {delta.provider_model_id} ({delta.display_name})")
        lines.append(f"  changed: {len(result.changed)}")
        for delta in result.changed:
            lines.append(f"    * {delta.provider_model_id} ({delta.display_name})")
            for field_change in delta.field_changes:
                lines.append(
                    f"      - {field_change.field_name}: "
                    f"{_render_value(field_change.old_value)} -> {_render_value(field_change.new_value)}"
                )
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_scan_markdown(*, generated_at: str, command: str, provider_results: list[ProviderScanResult]) -> str:
    lines = [
        "# Model Sentinel Report",
        "",
        f"- Generated at: {to_local_human(generated_at)}",
        f"- Command: {command}",
        "",
    ]
    for result in provider_results:
        lines.append(f"## {result.provider_label} (`{result.provider_id}`)")
        lines.append("")
        lines.append(f"- Status: `{result.status}`")
        lines.append(f"- Current models: `{result.current_count}`")
        if result.baseline:
            lines.append(f"- Baseline: scrape `{result.baseline.scrape_id}` at `{to_local_human(result.baseline.completed_at)}`")
        elif result.baseline_message:
            lines.append(f"- Baseline: {result.baseline_message}")
        if result.error_message:
            lines.append(f"- Error: `{result.error_message}`")
        lines.append("")
        lines.append(f"### Added ({len(result.added)})")
        lines.append("")
        if result.added:
            for delta in result.added:
                lines.append(f"- `{delta.provider_model_id}` - {delta.display_name}")
        else:
            lines.append("- None")
        lines.append("")
        lines.append(f"### Removed ({len(result.removed)})")
        lines.append("")
        if result.removed:
            for delta in result.removed:
                lines.append(f"- `{delta.provider_model_id}` - {delta.display_name}")
        else:
            lines.append("- None")
        lines.append("")
        lines.append(f"### Changed ({len(result.changed)})")
        lines.append("")
        if result.changed:
            for delta in result.changed:
                lines.append(f"- `{delta.provider_model_id}` - {delta.display_name}")
                for field_change in delta.field_changes:
                    lines.append(
                        f"  - `{field_change.field_name}`: "
                        f"`{_render_value(field_change.old_value)}` -> `{_render_value(field_change.new_value)}`"
                    )
        else:
            lines.append("- None")
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=True)
    return str(value)


def _group_models_by_prefix(models: tuple[dict[str, Any], ...]) -> list[tuple[str | None, list[dict[str, Any]]]]:
    grouped: dict[str | None, list[dict[str, Any]]] = {}
    order: list[str | None] = []
    for row in models:
        model_id = row["provider_model_id"]
        prefix = model_id.split("/", 1)[0] if "/" in model_id else None
        if prefix not in grouped:
            grouped[prefix] = []
            order.append(prefix)
        grouped[prefix].append(row)
    return [(prefix, grouped[prefix]) for prefix in order]


def _render_inline_model_row(row: dict[str, Any]) -> list[str]:
    model_id = row["provider_model_id"]
    display_name = row["display_name"] or model_id
    lines = [f"- {model_id}"]
    if display_name != model_id:
        lines.append(f"    name:  {display_name}")
    price_summary = _format_price_pair(row)
    if price_summary != "n/a":
        lines.append(f"    price: {price_summary}")
    cache_summary = _format_cache_prices(row)
    if cache_summary:
        lines.append(f"    cache: {cache_summary}")
    lines.append(f"    first: {_short_ts(row['first_seen'])}")
    lines.append(f"    last:  {_short_ts(row['last_seen'])}")
    lines.append("")
    return lines


def _short_ts(value: Any) -> str:
    return to_local_human(value)


def _format_number(value: Any) -> str:
    if value is None:
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    return format(numeric, "g")


def _format_price_pair(row: dict[str, Any]) -> str:
    input_price = _format_per_million(row.get("input_price"))
    output_price = _format_per_million(row.get("output_price"))
    if not input_price and not output_price:
        return "n/a"
    return f"{input_price or '?'} / {output_price or '?'}"


def _format_cache_prices(row: dict[str, Any]) -> str:
    read_price = _format_per_million(row.get("cache_read_price"))
    write_price = _format_per_million(row.get("cache_write_price"))
    if not read_price and not write_price:
        return ""
    return f"{read_price or '?'} / {write_price or '?'}"


def _normalize_latest_model_json(latest_model: dict[str, Any] | None) -> dict[str, Any] | None:
    if latest_model is None:
        return None
    return {
        **latest_model,
        "completed_at": to_local_iso(latest_model.get("completed_at")),
    }


def _format_per_million(value: Any) -> str:
    if value is None:
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    scaled = numeric * 1_000_000
    return format(scaled, "g")
