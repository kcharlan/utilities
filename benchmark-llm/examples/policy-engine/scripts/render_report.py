from __future__ import annotations

import json
import sys
from pathlib import Path

from eval_helpers import render_template


def main() -> int:
    run_dir = Path(sys.argv[1])
    template_path = Path(sys.argv[2])
    adjudication = json.loads((run_dir / "adjudication.json").read_text(encoding="utf-8"))

    normalized = {
        "summary": {
            "passed": sum(
                1
                for key in (
                    "visible_pass_fail",
                    "hidden_c_pass_fail",
                    "hidden_d_pass_fail",
                    "mutation_result",
                )
                if adjudication.get(key) == "Pass"
            ),
            "total": 4,
            "score_percent": float(adjudication["score_percent"]),
        },
        "checks": [
            {"name": "Visible set pass/fail", "passed": adjudication.get("visible_pass_fail") == "Pass"},
            {"name": "Hidden C pass/fail", "passed": adjudication.get("hidden_c_pass_fail") == "Pass"},
            {"name": "Hidden D pass/fail", "passed": adjudication.get("hidden_d_pass_fail") == "Pass"},
            {"name": "Mutation test result", "passed": adjudication.get("mutation_result") == "Pass"},
        ],
        "adjudication": adjudication,
    }
    (run_dir / "score.json").write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")

    template_text = template_path.read_text(encoding="utf-8")
    report_text = render_template(
        template_text,
        {
            "model": adjudication.get("model", ""),
            "provider": adjudication.get("provider", ""),
            "date": adjudication.get("date", ""),
            "time_started": adjudication.get("time_started", ""),
            "time_ended": adjudication.get("time_ended", ""),
            "elapsed_minutes": adjudication.get("elapsed_minutes", ""),
            "cost": adjudication.get("cost", "unknown"),
            "turns": adjudication.get("turns", ""),
            "interventions": adjudication.get("interventions", ""),
            "visible_pass_fail": adjudication.get("visible_pass_fail", ""),
            "hidden_c_pass_fail": adjudication.get("hidden_c_pass_fail", ""),
            "hidden_d_pass_fail": adjudication.get("hidden_d_pass_fail", ""),
            "mutation_result": adjudication.get("mutation_result", ""),
            "final_score": adjudication.get("final_score", ""),
            "notes": adjudication.get("notes", ""),
            "finding_1": (adjudication.get("findings") or [""])[0],
            "finding_2": (adjudication.get("findings") or ["", ""])[1],
            "finding_3": (adjudication.get("findings") or ["", "", ""])[2],
            "score_visible": adjudication.get("score_breakdown", {}).get("visible", ""),
            "score_hidden_generalization": adjudication.get("score_breakdown", {}).get(
                "hidden_generalization", ""
            ),
            "score_hidden_robustness": adjudication.get("score_breakdown", {}).get(
                "hidden_robustness", ""
            ),
            "score_code_quality": adjudication.get("score_breakdown", {}).get("code_quality", ""),
            "score_cli": adjudication.get("score_breakdown", {}).get("cli_output_usability", ""),
            "score_tests_docs": adjudication.get("score_breakdown", {}).get("tests_docs", ""),
            "score_run_behavior": adjudication.get("score_breakdown", {}).get(
                "run_behavior_efficiency", ""
            ),
        },
    )
    (run_dir / "report.md").write_text(report_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
