from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from cognitive_switchyard.state import StateStore


def parse_plan_frontmatter(plan_path: Path) -> dict[str, Any]:
    """Parse YAML front matter from a plan file."""
    lines = plan_path.read_text().splitlines()
    in_frontmatter = False
    yaml_lines: list[str] = []
    for line in lines:
        if line.strip() == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter:
            yaml_lines.append(line)
    if not yaml_lines:
        return {}
    return yaml.load("\n".join(yaml_lines), Loader=yaml.BaseLoader) or {}


def parse_list_field(value: Any) -> list[str]:
    """Normalize frontmatter list fields from string/list form."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text or text.lower() == "none":
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def resolve_passthrough(staging_dir: Path, ready_dir: Path, resolution_path: Path) -> dict[str, Any]:
    """Read constraints from plan frontmatter, write resolution.json, move plans to ready."""
    tasks: list[dict[str, Any]] = []
    for plan_file in sorted(staging_dir.glob("*.plan.md")):
        metadata = parse_plan_frontmatter(plan_file)
        task_id = str(
            metadata.get("PLAN_ID")
            or StateStore._extract_task_id_from_filename(plan_file.name)
            or plan_file.stem
        )
        depends_on = parse_list_field(metadata.get("DEPENDS_ON", "none"))
        anti_affinity = parse_list_field(metadata.get("ANTI_AFFINITY", "none"))
        exec_order = int(metadata.get("EXEC_ORDER", 1))
        tasks.append(
            {
                "task_id": task_id,
                "depends_on": depends_on,
                "anti_affinity": anti_affinity,
                "exec_order": exec_order,
            }
        )
        os.rename(str(plan_file), str(ready_dir / plan_file.name))

    resolution = {
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "tasks": tasks,
        "groups": [],
        "conflicts": [],
        "notes": "Passthrough resolution (user-declared constraints only)",
    }
    resolution_path.write_text(json.dumps(resolution, indent=2))
    return resolution
