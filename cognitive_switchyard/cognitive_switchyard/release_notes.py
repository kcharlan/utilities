from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CompletedPlanRecord:
    plan_id: str
    title: str
    commits: str
    test_result: str
    notes: str
    operator_actions: str
    overview: str


def generate_release_notes(done_dir: Path, output_path: Path, plan_files: Iterable[Path] | None = None) -> bool:
    plans = sorted(plan_files or done_dir.glob("*.plan.md"))
    records = [_build_record(plan_path) for plan_path in plans if plan_path.exists()]
    if not records:
        return False

    lines = [
        f"# Release Notes - {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "> Auto-generated from completed plans in `done/`.",
        "",
        "## Operator Action Items",
        "",
    ]

    categorized = {
        "Infrastructure": [],
        "Data Migration": [],
        "Configuration": [],
        "Breaking Changes": [],
        "Rollback Notes": [],
    }
    has_actions = False
    for record in records:
        actions = _extract_operator_action_categories(record.operator_actions)
        if any(actions.values()):
            has_actions = True
        for category, items in actions.items():
            if not items:
                continue
            categorized[category].append(f"**From {record.plan_id} - {record.title}:**")
            categorized[category].extend(items)
            categorized[category].append("")

    if not has_actions:
        lines.extend(
            [
                "_No operator actions required - all plans are standard deployments._",
                "",
            ]
        )
    else:
        for category, items in categorized.items():
            if not items:
                continue
            lines.append(f"### {category}")
            lines.extend(items)

    lines.extend(
        [
            "## Plans Included",
            "",
            "| Plan | Title | Commits | Tests |",
            "|------|-------|---------|-------|",
        ]
    )
    for record in records:
        lines.append(f"| {record.plan_id} | {record.title} | `{record.commits}` | {record.test_result} |")

    lines.extend(["", "## Detailed Changes", ""])
    for record in records:
        lines.append(f"### {record.plan_id} - {record.title}")
        lines.append("")
        lines.append(record.overview or "_No overview provided._")
        lines.append("")
        if record.notes:
            lines.append(f"_Worker notes: {record.notes}_")
            lines.append("")

    output_path.write_text("\n".join(lines).rstrip() + "\n")
    return True


def _build_record(plan_path: Path) -> CompletedPlanRecord:
    status_path = plan_path.with_suffix("").with_suffix(".status")
    if not status_path.exists():
        alternate = plan_path.with_name(f"{plan_path.name}.status")
        status_path = alternate if alternate.exists() else status_path
    status_fields = _parse_status_fields(status_path)
    return CompletedPlanRecord(
        plan_id=_extract_frontmatter_field(plan_path, "PLAN_ID") or plan_path.name.split("_", 1)[0],
        title=_extract_title(plan_path),
        commits=status_fields.get("COMMITS", "-"),
        test_result=status_fields.get("TEST_RESULT", "-"),
        notes=status_fields.get("NOTES", ""),
        operator_actions=_extract_section(plan_path, "Operator Actions"),
        overview=_extract_section(plan_path, "Overview"),
    )


def _extract_title(plan_path: Path) -> str:
    for line in plan_path.read_text().splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return plan_path.name


def _extract_frontmatter_field(plan_path: Path, field: str) -> str:
    in_frontmatter = False
    prefix = f"{field}:"
    for line in plan_path.read_text().splitlines():
        if line.strip() == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter and line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def _extract_section(plan_path: Path, heading: str) -> str:
    target = f"## {heading}"
    lines: list[str] = []
    found = False
    for line in plan_path.read_text().splitlines():
        if line == target:
            found = True
            continue
        if found and line.startswith("## "):
            break
        if found:
            lines.append(line)
    return "\n".join(lines).strip()


def _extract_operator_action_categories(body: str) -> dict[str, list[str]]:
    categories = {
        "Infrastructure": [],
        "Data Migration": [],
        "Configuration": [],
        "Breaking Changes": [],
        "Rollback Notes": [],
    }
    if not body or body.lower().startswith("none"):
        return categories

    current: str | None = None
    for line in body.splitlines():
        if line.startswith("### "):
            current = line[4:].strip()
            continue
        if current in categories and line.strip():
            categories[current].append(line.rstrip())
    return categories


def _parse_status_fields(status_path: Path) -> dict[str, str]:
    if not status_path.exists():
        return {}
    fields: dict[str, str] = {}
    for line in status_path.read_text().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip().upper()] = value.strip()
    return fields
