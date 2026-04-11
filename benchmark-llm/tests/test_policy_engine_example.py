import json
import importlib.util
from pathlib import Path

import yaml


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_policy_engine_example_includes_adjudication_step_and_assets() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bench_yaml = yaml.safe_load(
        (repo_root / "examples" / "policy-engine" / "bench.yaml").read_text(encoding="utf-8")
    )
    steps = bench_yaml["steps"]
    step_names = [step["name"] if isinstance(step, dict) else step for step in steps]
    assert "adjudicate" in step_names

    assert (repo_root / "examples" / "policy-engine" / "scripts" / "adjudicate.sh").exists()
    assert (repo_root / "examples" / "policy-engine" / "hidden" / "data" / "benefits-hidden-c.yaml").exists()
    assert (
        repo_root
        / "examples"
        / "policy-engine"
        / "hidden"
        / "policies"
        / "professional-risk-only-extended.yaml"
    ).exists()
    assert (
        repo_root / "examples" / "policy-engine" / "visible" / "data" / "benefits-sample-a.json"
    ).exists()


def test_policy_engine_adjudication_defaults_to_cx_wrapper() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script_text = (repo_root / "examples" / "policy-engine" / "scripts" / "adjudicate.sh").read_text(
        encoding="utf-8"
    )
    readme_text = (repo_root / "examples" / "policy-engine" / "README.md").read_text(encoding="utf-8")

    assert 'ADJUDICATOR_BIN="${BENCH_POLICY_ENGINE_ADJUDICATOR_BIN:-cx}"' in script_text
    assert "active default remains `cx exec`" in readme_text


def test_policy_engine_eval_helpers_compare_rows_and_render_template() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    module = _load_module(
        repo_root / "examples" / "policy-engine" / "scripts" / "eval_helpers.py"
    )

    payload = {
        "results": [
            {
                "original_service_category": "PCP Visit",
                "canonical_service_category": "Primary Care Visit",
                "risk_holder": "professional",
                "system_configuration_action": "PAY",
                "match_status": "matched",
            }
        ]
    }
    rows = module.extract_output_rows(payload)
    assert len(rows) == 1

    expected_rows = [
        {
            "original_service_category": "PCP Visit",
            "canonical_service_category": "Primary Care Visit",
            "risk_holder": "professional",
            "system_configuration_action": "PAY",
            "match_status": "matched",
        }
    ]
    comparison = module.compare_expected_rows(rows, expected_rows)
    assert comparison["passed"] is True

    rendered = module.render_template(
        "Model: {{ model }}\nScore: {{ final_score }}\n",
        {"model": "GLM-5.1", "final_score": "92/100"},
    )
    assert "GLM-5.1" in rendered
    assert "92/100" in rendered


def test_policy_engine_harness_metrics_extracts_opencode_and_codex_shapes(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    module = _load_module(
        repo_root / "examples" / "policy-engine" / "scripts" / "harness_metrics.py"
    )

    opencode_events = tmp_path / "opencode-events.jsonl"
    opencode_events.write_text(
        "\n".join(
            [
                json.dumps({"type": "step_start", "sessionID": "ses_abc123XYZ"}),
                json.dumps(
                    {
                        "type": "step_finish",
                        "sessionID": "ses_abc123XYZ",
                        "part": {
                            "type": "step-finish",
                            "tokens": {"total": 24533, "input": 24512, "output": 7, "reasoning": 14},
                            "cost": 0.00800735,
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    opencode_export = tmp_path / "opencode-export.json"
    opencode_export.write_text(
        json.dumps(
            {
                "info": {
                    "id": "ses_abc123XYZ",
                    "time": {"created": 1775927614760, "completed": 1775927615509},
                },
                "messages": [
                    {
                        "info": {
                            "cost": 0.42,
                            "tokens": {"input": 100, "output": 20, "total": 120},
                        }
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert module.extract_opencode_session_id(module._read_jsonl(opencode_events)) == "ses_abc123XYZ"
    event_metrics = module.extract_metrics_from_payload(module._read_jsonl(opencode_events))
    assert event_metrics["cost_usd"] == 0.008007
    assert event_metrics["input_tokens"] == 24512
    assert event_metrics["output_tokens"] == 7
    assert event_metrics["total_tokens"] == 24533

    metrics = module.extract_metrics_from_payload(module._read_json(opencode_export))
    assert metrics["cost_usd"] == 0.42
    assert metrics["provider_latency_ms"] == 749
    assert metrics["total_tokens"] == 120

    codex_events = tmp_path / "codex-events.jsonl"
    codex_events.write_text(
        "\n".join(
            [
                json.dumps({"type": "turn.completed", "usage": {"prompt_tokens": 210, "completion_tokens": 45}}),
                json.dumps({"type": "response.completed", "total_cost_usd": 0.031}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    codex_metrics = module.extract_metrics_from_payload(module._read_jsonl(codex_events))
    assert codex_metrics["input_tokens"] == 210
    assert codex_metrics["output_tokens"] == 45
    assert codex_metrics["total_tokens"] == 255
    assert codex_metrics["cost_usd"] == 0.031


def test_policy_engine_model_visible_assets_do_not_signal_evaluation_context() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompt_text = (repo_root / "examples" / "policy-engine" / "prompt.txt").read_text(
        encoding="utf-8"
    )
    visible_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((repo_root / "examples" / "policy-engine" / "visible").rglob("*"))
        if path.is_file()
    )
    combined = f"{prompt_text}\n{visible_text}".lower()

    for forbidden in [
        "benchmark",
        "evaluation",
        "adjudication",
        "evaluator",
        "hidden asset",
        "hidden assets",
        "test",
        "tests",
    ]:
        assert forbidden not in combined
