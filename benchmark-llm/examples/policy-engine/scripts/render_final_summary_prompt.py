from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


_TABLE_ROW_RE = re.compile(r"^\|\s*(?P<field>[^|]+?)\s*\|\s*(?P<value>[^|]+?)\s*\|$")


def _extract_topline_fields(report_text: str) -> dict[str, str]:
    extracted: dict[str, str] = {}
    for line in report_text.splitlines():
        match = _TABLE_ROW_RE.match(line.strip())
        if not match:
            continue
        field = match.group("field").strip().lower()
        value = match.group("value").strip()
        if field in {"field", "---"}:
            continue
        extracted[field] = value
    return extracted


def build_prompt(benchmark_dir: Path, summary_input_path: Path) -> str:
    summary_payload = json.loads(summary_input_path.read_text(encoding="utf-8"))
    benchmark_name = benchmark_dir.name

    sections = [
        f"You are writing the final synthesized benchmark summary for the `{benchmark_name}` benchmark.",
        "Return markdown only.",
        "",
        "Required output structure:",
        "1. A summary table of the topline results from each report.md.",
        "2. A synthesized detail narrative that compares the runs as a set.",
        "3. A per-model commentary section with supporting quotes or evidence from the specific report.md for that model.",
        "",
        "Use short quotes from report.md only when they directly support a claim. Do not invent evidence.",
        "If multiple runs use the same model, keep them as separate rows and separate commentary subsections.",
        "",
        "Required headings:",
        "# Benchmark Summary",
        "## Topline Results",
        "## Synthesized Narrative",
        "## Model Commentary",
    ]

    for run in summary_payload.get("runs", []):
        report_path = Path(run["report_path"])
        report_text = report_path.read_text(encoding="utf-8")
        sections.extend(
            [
                "",
                f"Run ID: {run['run_id']}",
                f"Model: {run['model']}",
                f"Score percent: {run.get('score_percent', '')}",
                "Extracted topline fields from report.md:",
                json.dumps(_extract_topline_fields(report_text), indent=2, sort_keys=True),
                "Full report.md:",
                report_text,
            ]
        )

    return "\n".join(sections) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    benchmark_dir = Path(argv[0])
    summary_input_path = Path(argv[1])
    sys.stdout.write(build_prompt(benchmark_dir, summary_input_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
