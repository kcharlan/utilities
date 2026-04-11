# Evaluation Sheet

| Field | Value |
| --- | --- |
| Model | {{ model }} |
| Provider | {{ provider }} |
| Date | {{ date }} |
| Time started | {{ time_started }} |
| Time ended | {{ time_ended }} |
| Elapsed minutes | {{ elapsed_minutes }} |
| Cost | {{ cost }} |
| Turns/prompts | {{ turns }} |
| Human interventions | {{ interventions }} |
| Visible set pass/fail | {{ visible_pass_fail }} |
| Hidden C pass/fail | {{ hidden_c_pass_fail }} |
| Hidden D pass/fail | {{ hidden_d_pass_fail }} |
| Mutation test result | {{ mutation_result }} |
| Final score | {{ final_score }} |
| Notes | {{ notes }} |

## Findings

- {{ finding_1 }}
- {{ finding_2 }}
- {{ finding_3 }}

## Score Breakdown

- Visible correctness: {{ score_visible }}
- Hidden generalization: {{ score_hidden_generalization }}
- Hidden robustness: {{ score_hidden_robustness }}
- Code quality: {{ score_code_quality }}
- CLI and output usability: {{ score_cli }}
- Tests and docs: {{ score_tests_docs }}
- Run behavior and efficiency: {{ score_run_behavior }}
