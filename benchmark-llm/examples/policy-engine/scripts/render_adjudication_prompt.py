from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


def main() -> int:
    benchmark_dir = Path(sys.argv[1])
    run_dir = Path(sys.argv[2])
    model = sys.argv[3]

    prompt_header = (benchmark_dir / "hidden" / "adjudicator_prompt.md").read_text(encoding="utf-8")
    report_template = (benchmark_dir / "report_template.md").read_text(encoding="utf-8")
    rubric = yaml.safe_load((benchmark_dir / "hidden" / "rubric.yaml").read_text(encoding="utf-8"))
    validation_summary = json.loads((run_dir / "validation_summary.json").read_text(encoding="utf-8"))
    benchmark_commands = (run_dir / "commands.jsonl").read_text(encoding="utf-8")

    prompt = "\n\n".join(
        [
            prompt_header,
            f"Model under evaluation: {model}",
            f"Provider: {rubric['provider']}",
            "Report template:",
            report_template,
            "Validation summary JSON:",
            json.dumps(validation_summary, indent=2),
            "Top-level benchmark command log:",
            benchmark_commands,
        ]
    )
    sys.stdout.write(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
