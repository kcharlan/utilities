You are adjudicating a coding benchmark run for the `policy-engine` task.

Use the structured evidence below to produce a strict JSON object only. Do not include markdown fences.

Scoring rules:
- visible_correctness: 25
- hidden_generalization: 25
- hidden_robustness: 10
- code_quality: 15
- cli_output_usability: 10
- tests_docs: 10
- run_behavior_efficiency: 5

Requirements:
- Base findings on the evidence provided, not speculation.
- Mention command provenance when it materially affects the score.
- Keep findings concise and factual.
- Report pass/fail values as `Pass`, `Fail`, or `Partial`.
- Emit numeric `score_percent` as a number from 0 to 100.

Return JSON with this shape:
{
  "model": "...",
  "provider": "...",
  "date": "YYYY-MM-DD",
  "time_started": "HH:MM",
  "time_ended": "HH:MM",
  "elapsed_minutes": 0,
  "cost": "unknown",
  "turns": 0,
  "interventions": 0,
  "visible_pass_fail": "Pass|Fail|Partial",
  "hidden_c_pass_fail": "Pass|Fail|Partial",
  "hidden_d_pass_fail": "Pass|Fail|Partial",
  "mutation_result": "Pass|Fail|Partial",
  "final_score": "92/100",
  "score_percent": 92.0,
  "notes": "...",
  "findings": ["...", "...", "..."],
  "score_breakdown": {
    "visible": "25/25",
    "hidden_generalization": "25/25",
    "hidden_robustness": "10/10",
    "code_quality": "12/15",
    "cli_output_usability": "9/10",
    "tests_docs": "7/10",
    "run_behavior_efficiency": "4/5"
  }
}
