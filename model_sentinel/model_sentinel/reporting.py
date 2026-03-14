from __future__ import annotations

import html as html_module
import json
from collections import OrderedDict, defaultdict
from dataclasses import asdict
from typing import Any

from .models import FieldChange, HistoryEvent, ModelDelta, ProviderScanResult
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
    if format_name == "html":
        return _render_scan_html(generated_at=generated_at, command=command, provider_results=provider_results)
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


def render_changes_report(
    *,
    format_name: str,
    provider_id: str | None,
    since: str | None,
    until: str | None,
    changes: tuple[dict[str, Any], ...],
    provider_pricing: dict[str, tuple[int, int]] | None = None,
) -> str:
    if format_name == "json":
        return json.dumps(
            {
                "provider_id": provider_id,
                "since": since,
                "until": until,
                "changes": list(changes),
            },
            indent=2,
            sort_keys=True,
        )

    if not changes:
        period_parts = []
        if since:
            period_parts.append(f"since {since}")
        if until:
            period_parts.append(f"until {until}")
        period = " ".join(period_parts) if period_parts else "in recorded history"
        scope = f"provider {provider_id}" if provider_id else "all providers"
        return f"No changes found for {scope} {period}."

    # Group by detected_at date, then provider, then model
    by_date: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = OrderedDict()
    for change in changes:
        date_str = to_local_human(change["detected_at"]).split(" ")[0] if change["detected_at"] else "unknown"
        provider = change["provider_label"]
        model = change["provider_model_id"]
        by_date.setdefault(date_str, OrderedDict()).setdefault(provider, OrderedDict()).setdefault(model, []).append(change)

    if format_name == "html":
        return _render_changes_html(
            by_date=by_date,
            provider_id=provider_id,
            since=since,
            until=until,
            total_changes=len(changes),
            provider_pricing=provider_pricing,
        )

    lines = ["Model Sentinel \u2014 Change Log", ""]
    scope_parts = []
    if provider_id:
        scope_parts.append(f"Provider: {provider_id}")
    if since:
        scope_parts.append(f"Since: {since}")
    if until:
        scope_parts.append(f"Until: {until}")
    if scope_parts:
        lines.append("  ".join(scope_parts))
        lines.append("")

    total_changes = len(changes)
    lines.append(f"{total_changes} change{'s' if total_changes != 1 else ''} across {len(by_date)} date{'s' if len(by_date) != 1 else ''}")
    lines.append("=" * 60)
    lines.append("")

    for date_str, providers in by_date.items():
        lines.append(f"  {date_str}")
        lines.append(f"  {'-' * 40}")
        for provider_label, models in providers.items():
            lines.append(f"    {provider_label}")
            for model_id, model_changes in models.items():
                display_name = model_changes[0].get("display_name", model_id)
                kind = model_changes[0]["change_kind"]
                if kind == "added":
                    lines.append(f"      + {model_id} ({display_name})")
                elif kind == "removed":
                    lines.append(f"      - {model_id} ({display_name})")
                else:
                    lines.append(f"      * {model_id} ({display_name})")
                    for change in model_changes:
                        fn = change.get("field_name")
                        if fn:
                            fc = FieldChange(fn, change["old_value"], change["new_value"])
                            pm, pd = 1, 1
                            if provider_pricing:
                                pid = change.get("provider_id", "")
                                pm, pd = provider_pricing.get(pid, (1, 1))
                            lines.append(f"          {_render_smart_change_text(fc, pm, pd)}")
        lines.append("")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Smart field-change formatting (shared by text and HTML renderers)
# ---------------------------------------------------------------------------

_CATEGORY_ORDER = ["Pricing", "Context & Limits", "Parameters", "Capabilities", "Other"]


def _classify_field(field_name: str) -> str:
    lower = field_name.lower()
    if any(p in lower for p in ("pricing.", "price", "cost", "_rate")):
        return "Pricing"
    if any(p in lower for p in ("context_length", "context_window", "max_completion", "max_tokens", "max_output")):
        return "Context & Limits"
    if "supported_parameters" in lower or lower == "parameters":
        return "Parameters"
    if any(p in lower for p in ("vision", "audio", "image", "tool", "reasoning", "structured", "modality")):
        return "Capabilities"
    return "Other"


def _group_field_changes(field_changes: tuple[FieldChange, ...]) -> list[tuple[str, list[FieldChange]]]:
    grouped: dict[str, list[FieldChange]] = defaultdict(list)
    for fc in field_changes:
        grouped[_classify_field(fc.field_name)].append(fc)
    return [(cat, grouped[cat]) for cat in _CATEGORY_ORDER if cat in grouped]


def _both_numeric(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    try:
        float(a)
        float(b)
        return True
    except (TypeError, ValueError):
        return False


def _fmt_int(value: float) -> str:
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _pct_change(old: float, new: float) -> str:
    if old == 0:
        return ""
    pct = ((new - old) / abs(old)) * 100
    arrow = "\u2191" if pct > 0 else "\u2193"
    return f"{arrow} {abs(pct):.1f}%"


def _fmt_price_per_m(value: float) -> str:
    if value == 0:
        return "free"
    abs_val = abs(value)
    if abs_val >= 1:
        formatted = f"{value:.2f}"
    elif abs_val >= 0.01:
        formatted = f"{value:.4f}"
    else:
        formatted = f"{value:.6f}"
    # Strip trailing zeros but keep at least 2 decimal places
    parts = formatted.split(".")
    decimals = parts[1].rstrip("0")
    if len(decimals) < 2:
        decimals = decimals.ljust(2, "0")
    return f"${parts[0]}.{decimals}"


def _normalize_price(raw_value: float, multiplier: int, divisor: int) -> float:
    return (raw_value * multiplier) / divisor


def _render_smart_change_text(fc: FieldChange, price_multiplier: int = 1, price_divisor: int = 1) -> str:
    category = _classify_field(fc.field_name)

    # List diff (supported_parameters)
    if isinstance(fc.old_value, list) and isinstance(fc.new_value, list):
        return _render_list_diff_text(fc)

    # Numeric fields with delta and percentage
    if _both_numeric(fc.old_value, fc.new_value):
        old_f = float(fc.old_value)
        new_f = float(fc.new_value)
        delta = new_f - old_f

        if category == "Pricing":
            norm_old = _normalize_price(old_f, price_multiplier, price_divisor)
            norm_new = _normalize_price(new_f, price_multiplier, price_divisor)
            pct = _pct_change(old_f, new_f)
            price_hint = f"{_fmt_price_per_m(norm_old)} \u2192 {_fmt_price_per_m(norm_new)} / 1M"
            parts = [f"{fc.field_name}: {fc.old_value} \u2192 {fc.new_value} ({price_hint}"]
            if pct:
                parts[0] += f", {pct}"
            parts[0] += ")"
            return parts[0]

        # Context and other integers: show formatted with delta
        pct = _pct_change(old_f, new_f)
        sign = "+" if delta > 0 else ""  # negative sign is automatic
        delta_str = f"{sign}{_fmt_int(delta)}"
        return f"{fc.field_name}: {_fmt_int(old_f)} \u2192 {_fmt_int(new_f)} ({delta_str}, {pct})" if pct else \
            f"{fc.field_name}: {_fmt_int(old_f)} \u2192 {_fmt_int(new_f)} ({delta_str})"

    # Boolean toggle
    if isinstance(fc.old_value, bool) and isinstance(fc.new_value, bool):
        old_sym = "\u2713" if fc.old_value else "\u2717"
        new_sym = "\u2713" if fc.new_value else "\u2717"
        return f"{fc.field_name}: {old_sym} \u2192 {new_sym}"

    # Generic fallback
    return f"{fc.field_name}: {_render_value(fc.old_value)} \u2192 {_render_value(fc.new_value)}"


def _render_list_diff_text(fc: FieldChange) -> str:
    old_set = set(str(x) for x in fc.old_value) if isinstance(fc.old_value, list) else set()
    new_set = set(str(x) for x in fc.new_value) if isinstance(fc.new_value, list) else set()
    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)
    old_count = len(fc.old_value) if isinstance(fc.old_value, list) else 0
    new_count = len(fc.new_value) if isinstance(fc.new_value, list) else 0
    parts = []
    if added:
        parts.append(", ".join(f"+{item}" for item in added))
    if removed:
        parts.append(", ".join(f"-{item}" for item in removed))
    count_str = f"({old_count} \u2192 {new_count})"
    if parts:
        return f"{fc.field_name}: {'; '.join(parts)} {count_str}"
    return f"{fc.field_name}: {count_str}"


# ---------------------------------------------------------------------------
# Text scan report (enhanced)
# ---------------------------------------------------------------------------


def _render_scan_text(*, generated_at: str, command: str, provider_results: list[ProviderScanResult]) -> str:
    lines = [
        "Model Sentinel report",
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
            if not delta.field_changes:
                continue
            grouped = _group_field_changes(delta.field_changes)
            pm, pd = result.price_multiplier, result.price_divisor
            if len(grouped) == 1 and len(grouped[0][1]) == 1:
                # Single change — no category header needed
                lines.append(f"      {_render_smart_change_text(grouped[0][1][0], pm, pd)}")
            else:
                for category, changes in grouped:
                    lines.append(f"      [{category}]")
                    for fc in changes:
                        lines.append(f"        {_render_smart_change_text(fc, pm, pd)}")
        lines.append("")

    # Summary table when there are changes across providers
    total_added = sum(len(r.added) for r in provider_results)
    total_removed = sum(len(r.removed) for r in provider_results)
    total_changed = sum(len(r.changed) for r in provider_results)
    if total_added or total_removed or total_changed:
        lines.append("Summary")
        lines.append("-" * 60)
        for result in provider_results:
            if result.change_count == 0:
                lines.append(f"  {result.provider_label}: no changes")
            else:
                parts = []
                if result.added:
                    parts.append(f"{len(result.added)} added")
                if result.removed:
                    parts.append(f"{len(result.removed)} removed")
                if result.changed:
                    parts.append(f"{len(result.changed)} changed")
                lines.append(f"  {result.provider_label}: {', '.join(parts)}")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Markdown scan report
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Unified HTML rendering
# ---------------------------------------------------------------------------

_HTML_CSS = """\
:root {
  --bg: #0f1419;
  --bg-card: #1a1f2e;
  --bg-card-hover: #1e2536;
  --bg-table-row: #151a24;
  --bg-table-alt: #1a2030;
  --border: #2a3040;
  --border-accent: #3a4050;
  --text: #c5cdd8;
  --text-dim: #6b7a8d;
  --text-bright: #e8edf4;
  --accent-green: #34d399;
  --accent-green-dim: rgba(52, 211, 153, 0.12);
  --accent-red: #f87171;
  --accent-red-dim: rgba(248, 113, 113, 0.12);
  --accent-amber: #fbbf24;
  --accent-amber-dim: rgba(251, 191, 36, 0.12);
  --accent-blue: #60a5fa;
  --font-mono: "SF Mono", "Cascadia Code", "Fira Code", "JetBrains Mono", "Consolas", monospace;
  --font-body: "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-body);
  font-size: 14px;
  line-height: 1.6;
  padding: 2rem;
  max-width: 1100px;
  margin: 0 auto;
}
header {
  border-bottom: 1px solid var(--border);
  padding-bottom: 1.5rem;
  margin-bottom: 2rem;
}
header h1 {
  font-family: var(--font-mono);
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-bright);
  letter-spacing: -0.02em;
}
header h1 .count {
  color: var(--accent-amber);
  font-weight: 400;
}
.meta {
  color: var(--text-dim);
  font-size: 0.85rem;
  margin-top: 0.4rem;
  font-family: var(--font-mono);
}
.provider-cards {
  display: flex;
  gap: 1rem;
  margin-bottom: 2rem;
  flex-wrap: wrap;
}
.provider-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  min-width: 200px;
  flex: 1;
  border-left: 3px solid var(--border);
}
.provider-card.status-clean { border-left-color: var(--accent-green); }
.provider-card.status-changed { border-left-color: var(--accent-amber); }
.provider-card.status-error { border-left-color: var(--accent-red); }
.provider-name {
  font-weight: 600;
  color: var(--text-bright);
  font-size: 1rem;
}
.provider-stats {
  color: var(--text-dim);
  font-size: 0.8rem;
  font-family: var(--font-mono);
  margin-top: 0.2rem;
}
.provider-badge {
  margin-top: 0.5rem;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.status-clean .provider-badge { color: var(--accent-green); }
.status-changed .provider-badge { color: var(--accent-amber); }
.status-error .provider-badge { color: var(--accent-red); }
.date-heading {
  font-family: var(--font-mono);
  font-size: 1.15rem;
  color: var(--text-bright);
  margin: 1.5rem 0 0.75rem 0;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border);
}
.provider-section {
  margin-bottom: 2.5rem;
}
.provider-section h2 {
  font-family: var(--font-mono);
  font-size: 1.15rem;
  color: var(--text-bright);
  margin-bottom: 0.75rem;
  font-weight: 600;
}
.provider-id {
  color: var(--text-dim);
  font-weight: 400;
  font-size: 0.9rem;
}
.baseline-info {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.8rem;
  margin-bottom: 1rem;
}
.error-msg {
  background: var(--accent-red-dim);
  color: var(--accent-red);
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  margin-bottom: 1rem;
}
h3 {
  font-size: 0.9rem;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin: 1.25rem 0 0.5rem 0;
  font-weight: 600;
}
.model-list {
  list-style: none;
  padding-left: 0;
}
.model-list li {
  padding: 0.35rem 0.5rem;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  margin-bottom: 0.2rem;
}
.added-list li {
  background: var(--accent-green-dim);
  color: var(--accent-green);
}
.removed-list li {
  background: var(--accent-red-dim);
  color: var(--accent-red);
}
.model-list .display-name {
  color: var(--text-dim);
  font-family: var(--font-body);
}
.model-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 1rem;
  overflow: hidden;
}
.model-card-header {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--bg-card-hover);
}
.model-card-header code {
  font-family: var(--font-mono);
  font-size: 0.9rem;
  color: var(--accent-amber);
  font-weight: 600;
}
.model-card-header .display-name {
  color: var(--text-dim);
  font-size: 0.85rem;
  margin-left: 0.5rem;
}
.change-category {
  padding: 0.5rem 1rem;
  border-bottom: 1px solid var(--border);
}
.change-category:last-child {
  border-bottom: none;
}
.category-label {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 0.4rem;
  font-weight: 600;
}
.change-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.change-table th {
  text-align: left;
  color: var(--text-dim);
  font-weight: 500;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.3rem 0.5rem;
  border-bottom: 1px solid var(--border);
}
.change-table td {
  padding: 0.4rem 0.5rem;
  font-family: var(--font-mono);
  font-size: 0.82rem;
  vertical-align: top;
}
.change-table tr:nth-child(even) td {
  background: var(--bg-table-alt);
}
.field-name { color: var(--text); }
td.old-val { color: var(--text-dim); }
td.new-val { color: var(--text-bright); }
td.change-delta { font-weight: 600; }
td.delta-decrease { color: var(--accent-red); }
td.delta-increase { color: var(--accent-green); }
td.delta-neutral { color: var(--accent-amber); }
.list-diff {
  font-family: var(--font-mono);
  font-size: 0.82rem;
  padding: 0.35rem 0;
}
.list-added { color: var(--accent-green); }
.list-removed { color: var(--accent-red); }
.list-count { color: var(--text-dim); font-size: 0.8rem; }
.summary-section {
  margin-top: 2.5rem;
  border-top: 1px solid var(--border);
  padding-top: 1.5rem;
}
.summary-section h2 {
  font-family: var(--font-mono);
  font-size: 1.1rem;
  color: var(--text-bright);
  margin-bottom: 1rem;
}
.summary-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.summary-table th {
  text-align: left;
  color: var(--text-dim);
  font-weight: 600;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.5rem 0.75rem;
  border-bottom: 2px solid var(--border-accent);
  background: var(--bg-card);
}
.summary-table td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 0.82rem;
}
.summary-table tr:nth-child(even) td {
  background: var(--bg-table-alt);
}
footer {
  margin-top: 3rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 0.75rem;
  font-family: var(--font-mono);
}"""


def _render_html_page(*, title: str, header_html: str, body_html: str, summary_html: str) -> str:
    h = html_module.escape
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{h(title)}</title>
<style>
{_HTML_CSS}
</style>
</head>
<body>
{header_html}
{body_html}
{summary_html}
<footer>Generated by Model Sentinel</footer>
</body>
</html>"""


def _build_html_summary_table(
    entries: list[tuple[str, str, str, str, str]],
) -> str:
    """Build the Change Summary HTML from (category, provider, model_id, field, detail) tuples."""
    if not entries:
        return ""
    h = html_module.escape
    rows = []
    for category, provider, model_id, field, detail in entries:
        if field:
            rows.append(
                f'<tr>'
                f'<td>{h(category)}</td>'
                f'<td>{h(provider)}</td>'
                f'<td><code>{h(model_id)}</code></td>'
                f'<td>{h(field)}</td>'
                f'<td>{h(detail)}</td>'
                f'</tr>'
            )
        else:
            rows.append(
                f'<tr><td>{h(category)}</td><td>{h(provider)}</td>'
                f'<td><code>{h(model_id)}</code></td>'
                f'<td colspan="2">{h(detail)}</td></tr>'
            )
    return (
        '<section class="summary-section">'
        '<h2>Change Summary</h2>'
        '<table class="summary-table">'
        '<thead><tr><th>Category</th><th>Provider</th><th>Model</th><th>Field</th><th>Change</th></tr></thead>'
        '<tbody>' + "\n".join(rows) + '</tbody>'
        '</table></section>'
    )


def _build_summary_entries_from_fc(
    *,
    provider_label: str,
    model_id: str,
    display_name: str,
    field_changes: list[FieldChange],
    price_multiplier: int,
    price_divisor: int,
) -> list[tuple[str, str, str, str, str]]:
    """Build summary entry tuples for field-changed models."""
    entries = []
    for fc in field_changes:
        category = _classify_field(fc.field_name)
        change_desc = _render_smart_change_text(fc, price_multiplier, price_divisor).split(": ", 1)
        field_part = change_desc[0] if len(change_desc) > 1 else fc.field_name
        detail_part = change_desc[1] if len(change_desc) > 1 else change_desc[0]
        entries.append((category, provider_label, model_id, field_part, detail_part))
    return entries


def _render_html_model_changes(delta: ModelDelta, price_multiplier: int = 1, price_divisor: int = 1) -> str:
    h = html_module.escape
    parts = [
        '<div class="model-card">',
        f'<div class="model-card-header"><code>{h(delta.provider_model_id)}</code>'
        f'<span class="display-name">{h(delta.display_name)}</span></div>',
    ]

    grouped = _group_field_changes(delta.field_changes)
    for category, changes in grouped:
        parts.append(f'<div class="change-category"><div class="category-label">{h(category)}</div>')
        _append_html_field_changes(parts, changes, price_multiplier, price_divisor)
        parts.append('</div>')

    parts.append('</div>')
    return "\n".join(parts)


def _append_html_field_changes(
    parts: list[str],
    field_changes: list[FieldChange],
    price_multiplier: int,
    price_divisor: int,
) -> None:
    """Append HTML for a group of field changes (table rows + list diffs) to parts."""
    list_changes = [fc for fc in field_changes if isinstance(fc.old_value, list) and isinstance(fc.new_value, list)]
    table_changes = [fc for fc in field_changes if fc not in list_changes]

    if table_changes:
        parts.append(
            '<table class="change-table"><thead><tr>'
            '<th>Field</th><th>Old</th><th>New</th><th>Change</th>'
            '</tr></thead><tbody>'
        )
        for fc in table_changes:
            parts.append(_render_html_table_row(fc, price_multiplier, price_divisor))
        parts.append('</tbody></table>')

    for fc in list_changes:
        parts.append(_render_html_list_diff(fc))


# ---------------------------------------------------------------------------
# HTML scan report
# ---------------------------------------------------------------------------


def _render_scan_html(*, generated_at: str, command: str, provider_results: list[ProviderScanResult]) -> str:
    h = html_module.escape
    timestamp = h(to_local_human(generated_at))
    total_changes = sum(r.change_count for r in provider_results)

    # Provider status cards
    provider_cards = []
    for result in provider_results:
        if result.status == "error":
            status_cls = "status-error"
            badge = "ERROR"
        elif result.change_count > 0:
            status_cls = "status-changed"
            badge = f"{result.change_count} change{'s' if result.change_count != 1 else ''}"
        else:
            status_cls = "status-clean"
            badge = "No changes"
        provider_cards.append(
            f'<div class="provider-card {status_cls}">'
            f'<div class="provider-name">{h(result.provider_label)}</div>'
            f'<div class="provider-stats">{result.current_count} models</div>'
            f'<div class="provider-badge">{badge}</div>'
            f'</div>'
        )

    # Change detail sections
    change_sections = []
    for result in provider_results:
        if result.change_count == 0 and result.status != "error":
            continue
        section_parts = [f'<h2>{h(result.provider_label)} <span class="provider-id">({h(result.provider_id)})</span></h2>']
        if result.baseline:
            section_parts.append(
                f'<div class="baseline-info">Baseline: scrape {result.baseline.scrape_id} '
                f'at {h(to_local_human(result.baseline.completed_at))}</div>'
            )
        if result.error_message:
            section_parts.append(f'<div class="error-msg">{h(result.error_message)}</div>')
        if result.added:
            section_parts.append('<h3>Added</h3><ul class="model-list added-list">')
            for delta in result.added:
                section_parts.append(f'<li><code>{h(delta.provider_model_id)}</code> <span class="display-name">{h(delta.display_name)}</span></li>')
            section_parts.append('</ul>')
        if result.removed:
            section_parts.append('<h3>Removed</h3><ul class="model-list removed-list">')
            for delta in result.removed:
                section_parts.append(f'<li><code>{h(delta.provider_model_id)}</code> <span class="display-name">{h(delta.display_name)}</span></li>')
            section_parts.append('</ul>')
        if result.changed:
            section_parts.append('<h3>Changed</h3>')
            for delta in result.changed:
                section_parts.append(_render_html_model_changes(delta, result.price_multiplier, result.price_divisor))
        change_sections.append('<section class="provider-section">' + "\n".join(section_parts) + '</section>')

    # Summary entries
    summary_entries: list[tuple[str, str, str, str, str]] = []
    for result in provider_results:
        prov = result.provider_label
        pm, pd = result.price_multiplier, result.price_divisor
        for delta in result.changed:
            summary_entries.extend(_build_summary_entries_from_fc(
                provider_label=prov, model_id=delta.provider_model_id,
                display_name=delta.display_name, field_changes=list(delta.field_changes),
                price_multiplier=pm, price_divisor=pd,
            ))
        for delta in result.added:
            summary_entries.append(("Added", prov, delta.provider_model_id, "", delta.display_name))
        for delta in result.removed:
            summary_entries.append(("Removed", prov, delta.provider_model_id, "", delta.display_name))

    suffix = "s" if total_changes != 1 else ""
    count_span = f'<span class="count">\u2014 {total_changes} change{suffix}</span>' if total_changes else ""
    header_html = (
        f'<header>\n'
        f'  <h1>Model Sentinel {count_span}</h1>\n'
        f'  <div class="meta">{timestamp} &middot; {h(command)}</div>\n'
        f'</header>'
    )
    body_html = (
        f'<div class="provider-cards">\n  {"".join(provider_cards)}\n</div>\n\n'
        + "".join(change_sections)
    )

    return _render_html_page(
        title=f"Model Sentinel \u2014 {to_local_human(generated_at)}",
        header_html=header_html,
        body_html=body_html,
        summary_html=_build_html_summary_table(summary_entries),
    )


# ---------------------------------------------------------------------------
# HTML changes report
# ---------------------------------------------------------------------------


def _render_changes_html(
    *,
    by_date: dict[str, dict[str, dict[str, list[dict[str, Any]]]]],
    provider_id: str | None,
    since: str | None,
    until: str | None,
    total_changes: int,
    provider_pricing: dict[str, tuple[int, int]] | None = None,
) -> str:
    h = html_module.escape

    scope_parts = []
    if provider_id:
        scope_parts.append(f"Provider: {provider_id}")
    if since:
        scope_parts.append(f"Since: {since}")
    if until:
        scope_parts.append(f"Until: {until}")
    meta_line = " &middot; ".join(h(p) for p in scope_parts) if scope_parts else "All providers"

    date_sections = []
    summary_entries: list[tuple[str, str, str, str, str]] = []

    for date_str, providers in by_date.items():
        parts = [f'<h2 class="date-heading">{h(date_str)}</h2>']
        for provider_label, models in providers.items():
            parts.append(f'<h3>{h(provider_label)}</h3>')
            added_models = []
            removed_models = []
            changed_models = []
            for model_id, model_changes in models.items():
                display_name = model_changes[0].get("display_name", model_id)
                kind = model_changes[0]["change_kind"]
                if kind == "added":
                    added_models.append((model_id, display_name))
                    summary_entries.append(("Added", provider_label, model_id, "", display_name))
                elif kind == "removed":
                    removed_models.append((model_id, display_name))
                    summary_entries.append(("Removed", provider_label, model_id, "", display_name))
                else:
                    changed_models.append((model_id, display_name, model_changes))

            if added_models:
                parts.append('<ul class="model-list added-list">')
                for mid, dname in added_models:
                    parts.append(f'<li><code>{h(mid)}</code> <span class="display-name">{h(dname)}</span></li>')
                parts.append('</ul>')
            if removed_models:
                parts.append('<ul class="model-list removed-list">')
                for mid, dname in removed_models:
                    parts.append(f'<li><code>{h(mid)}</code> <span class="display-name">{h(dname)}</span></li>')
                parts.append('</ul>')

            for model_id, display_name, model_changes in changed_models:
                field_changes = []
                for change in model_changes:
                    fn = change.get("field_name")
                    if fn:
                        field_changes.append(FieldChange(fn, change["old_value"], change["new_value"]))
                if not field_changes:
                    continue
                pm, pd = 1, 1
                if provider_pricing:
                    pid = model_changes[0].get("provider_id", "")
                    pm, pd = provider_pricing.get(pid, (1, 1))

                # Model change card
                parts.append('<div class="model-card">')
                parts.append(
                    f'<div class="model-card-header"><code>{h(model_id)}</code>'
                    f'<span class="display-name">{h(display_name)}</span></div>'
                )
                grouped = _group_field_changes(tuple(field_changes))
                for category, fcs in grouped:
                    parts.append(f'<div class="change-category"><div class="category-label">{h(category)}</div>')
                    _append_html_field_changes(parts, fcs, pm, pd)
                    parts.append('</div>')
                parts.append('</div>')

                # Summary entries
                summary_entries.extend(_build_summary_entries_from_fc(
                    provider_label=provider_label, model_id=model_id,
                    display_name=display_name, field_changes=field_changes,
                    price_multiplier=pm, price_divisor=pd,
                ))

        date_sections.append('<section class="provider-section">' + "\n".join(parts) + '</section>')

    header_html = (
        f'<header>\n'
        f'  <h1>Model Sentinel <span class="count">\u2014 Change Log</span></h1>\n'
        f'  <div class="meta">{meta_line} &middot; {total_changes} change{"s" if total_changes != 1 else ""}'
        f' across {len(by_date)} date{"s" if len(by_date) != 1 else ""}</div>\n'
        f'</header>'
    )

    return _render_html_page(
        title="Model Sentinel \u2014 Change Log",
        header_html=header_html,
        body_html="".join(date_sections),
        summary_html=_build_html_summary_table(summary_entries),
    )


# ---------------------------------------------------------------------------
# HTML component helpers
# ---------------------------------------------------------------------------


def _render_html_table_row(fc: FieldChange, price_multiplier: int = 1, price_divisor: int = 1) -> str:
    h = html_module.escape

    if _both_numeric(fc.old_value, fc.new_value):
        old_f = float(fc.old_value)
        new_f = float(fc.new_value)
        category = _classify_field(fc.field_name)

        pct = _pct_change(old_f, new_f)
        if old_f != 0:
            delta_cls = "delta-decrease" if new_f < old_f else "delta-increase"
        else:
            delta_cls = "delta-neutral"

        if category == "Pricing":
            norm_old = _normalize_price(old_f, price_multiplier, price_divisor)
            norm_new = _normalize_price(new_f, price_multiplier, price_divisor)
            old_str = h(f"{fc.old_value} ({_fmt_price_per_m(norm_old)} / 1M)")
            new_str = h(f"{fc.new_value} ({_fmt_price_per_m(norm_new)} / 1M)")
        else:
            old_str = h(_fmt_int(old_f))
            new_str = h(_fmt_int(new_f))

        return (
            f'<tr><td class="field-name">{h(fc.field_name)}</td>'
            f'<td class="old-val">{old_str}</td>'
            f'<td class="new-val">{new_str}</td>'
            f'<td class="change-delta {delta_cls}">{h(pct)}</td></tr>'
        )

    if isinstance(fc.old_value, bool) and isinstance(fc.new_value, bool):
        old_sym = "\u2713" if fc.old_value else "\u2717"
        new_sym = "\u2713" if fc.new_value else "\u2717"
        delta_cls = "delta-increase" if fc.new_value else "delta-decrease"
        return (
            f'<tr><td class="field-name">{h(fc.field_name)}</td>'
            f'<td class="old-val">{old_sym}</td>'
            f'<td class="new-val">{new_sym}</td>'
            f'<td class="change-delta {delta_cls}">{"\u2713" if fc.new_value else "\u2717"}</td></tr>'
        )

    return (
        f'<tr><td class="field-name">{h(fc.field_name)}</td>'
        f'<td class="old-val">{h(_render_value(fc.old_value))}</td>'
        f'<td class="new-val">{h(_render_value(fc.new_value))}</td>'
        f'<td class="change-delta delta-neutral">\u2014</td></tr>'
    )


def _render_html_list_diff(fc: FieldChange) -> str:
    h = html_module.escape
    old_set = set(str(x) for x in fc.old_value) if isinstance(fc.old_value, list) else set()
    new_set = set(str(x) for x in fc.new_value) if isinstance(fc.new_value, list) else set()
    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)
    old_count = len(fc.old_value) if isinstance(fc.old_value, list) else 0
    new_count = len(fc.new_value) if isinstance(fc.new_value, list) else 0

    parts = [f'<div class="list-diff">']
    parts.append(f'<span class="field-name">{h(fc.field_name)}</span> ')
    parts.append(f'<span class="list-count">({old_count} \u2192 {new_count})</span>')
    if added:
        parts.append('<div class="list-added">')
        for item in added:
            parts.append(f'&nbsp;&nbsp;+ {h(item)}')
        parts.append('</div>')
    if removed:
        parts.append('<div class="list-removed">')
        for item in removed:
            parts.append(f'&nbsp;&nbsp;\u2212 {h(item)}')
        parts.append('</div>')
    parts.append('</div>')
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Shared utility helpers
# ---------------------------------------------------------------------------


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
    input_price = _format_price_value(row.get("input_price"))
    output_price = _format_price_value(row.get("output_price"))
    if not input_price and not output_price:
        return "n/a"
    return f"{input_price or '?'} / {output_price or '?'}"


def _format_cache_prices(row: dict[str, Any]) -> str:
    read_price = _format_price_value(row.get("cache_read_price"))
    write_price = _format_price_value(row.get("cache_write_price"))
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


def _format_price_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    return format(numeric, "g")
