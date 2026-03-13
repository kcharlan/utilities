from pathlib import Path

from argparse import Namespace
import os

import model_sentinel.cli as cli
from model_sentinel.config import ProviderConfig
from model_sentinel.models import BaselineInfo
from model_sentinel.storage import Store
from model_sentinel.time_utils import to_local_human


def _write_config_files(root: Path) -> Path:
    runtime_home = root / ".model_sentinel"
    runtime_home.mkdir(parents=True, exist_ok=True)
    (runtime_home / "providers.env").write_text(
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_ENABLED=1\n"
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_LABEL=OpenRouter\n"
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_KIND=openrouter\n"
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1\n"
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_MODELS_PATH=/models\n"
        "MODEL_SENTINEL_PROVIDER_OPENROUTER_API_KEY_ENV=OPENROUTER_AI_CREDS\n",
        encoding="utf-8",
    )
    (runtime_home / "settings.env").write_text(
        "MODEL_SENTINEL_LOG_MAX_BYTES=10485760\n"
        "MODEL_SENTINEL_LOG_KEEP_FILES=3\n"
        "MODEL_SENTINEL_REPORT_DIR=reports\n"
        "MODEL_SENTINEL_NOTIFY_DEFAULT=0\n"
        "MODEL_SENTINEL_NOTIFY_ON=never\n"
        "MODEL_SENTINEL_NOTIFY_OPEN_TARGET=file\n",
        encoding="utf-8",
    )
    return runtime_home


def test_default_scan_without_baseline_explains_next_step(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("OPENROUTER_AI_CREDS", "token")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    exit_code = cli.main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No saved baseline exists for provider 'openrouter'" in captured.out
    assert "model_sentinel scan --save" in captured.out


def test_save_mode_allows_initial_baseline_without_prior_snapshot(tmp_path: Path) -> None:
    store = Store(tmp_path / ".model_sentinel" / "sentinel.db")
    store.initialize()
    args = Namespace(save=True, baseline="previous", baseline_date=None)
    assert cli._resolve_baseline(store, "openrouter", args) is None


def test_initial_saved_scan_reports_all_models_as_added(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("OPENROUTER_AI_CREDS", "token")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    provider = ProviderConfig(
        provider_id="openrouter",
        label="OpenRouter",
        kind="openrouter",
        base_url="https://openrouter.ai/api/v1",
        models_path="/models",
        credential_env_var="OPENROUTER_AI_CREDS",
        enabled=True,
    )

    monkeypatch.setattr(cli, "validate_selected_providers", lambda providers, provider_id=None: (provider,))
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda project_root: type(
            "Loaded",
            (),
            {
                "project_root": tmp_path,
                "runtime_paths": type(
                    "Paths",
                    (),
                    {
                        "database_path": runtime_home / "model_sentinel.db",
                        "runtime_home": runtime_home,
                        "providers_env": runtime_home / "providers.env",
                        "settings_env": runtime_home / "settings.env",
                        "logs_dir": runtime_home / "logs",
                        "log_file": runtime_home / "logs" / "model_sentinel.log",
                        "debug_dir": runtime_home / "debug",
                        "report_dir": runtime_home / "reports",
                        "ensure_directories": lambda self=None: (
                            (runtime_home / "logs").mkdir(parents=True, exist_ok=True),
                            (runtime_home / "debug").mkdir(parents=True, exist_ok=True),
                            (runtime_home / "reports").mkdir(parents=True, exist_ok=True),
                        ),
                    },
                )(),
                "settings": type(
                    "Settings",
                    (),
                    {
                        "notify_default": False,
                        "notify_on": "never",
                        "notify_open_target": "file",
                        "report_dir": runtime_home / "reports",
                        "log_max_bytes": 10485760,
                        "log_keep_files": 3,
                        "runtime_home": runtime_home,
                    },
                )(),
                "providers": (provider,),
            },
        )(),
    )
    monkeypatch.setattr(
        cli,
        "fetch_raw_models",
        lambda provider, api_key: [{"id": "alpha", "name": "Alpha"}, {"id": "beta", "name": "Beta"}],
    )

    exit_code = cli.main(["scan", "--save"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "added: 2" in captured.out
    assert "+ alpha (Alpha)" in captured.out
    assert "+ beta (Beta)" in captured.out


def test_history_model_list_lists_known_models(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))
    store = Store(runtime_home / "model_sentinel.db")
    store.initialize()
    scrape_id = store.create_scrape(
        provider_id="openrouter",
        started_at="2026-03-13T12:00:00-04:00",
        completed_at="2026-03-13T12:00:01-04:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=None,
        saved_snapshot=True,
        model_count=2,
        error_message=None,
    )
    from model_sentinel.models import NormalizedModel, canonical_json

    store.save_snapshot_models(
        scrape_id=scrape_id,
        provider_id="openrouter",
        models=[
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="alpha",
                display_name="Alpha",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=None,
                output_price=None,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "alpha", "name": "Alpha"}),
            ),
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="beta",
                display_name="Beta",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=None,
                output_price=None,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "beta", "name": "Beta"}),
            ),
        ],
    )

    exit_code = cli.main(["history", "--provider", "openrouter", "--model", "list"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Known models for openrouter" in captured.out
    assert "- alpha" in captured.out
    assert "- beta" in captured.out
    assert f"first: {to_local_human('2026-03-13T16:00:01+00:00')}" in captured.out


def test_history_model_list_groups_prefixed_models(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))
    store = Store(runtime_home / "model_sentinel.db")
    store.initialize()
    scrape_id = store.create_scrape(
        provider_id="openrouter",
        started_at="2026-03-13T12:53:40-04:00",
        completed_at="2026-03-13T12:53:41-04:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=None,
        saved_snapshot=True,
        model_count=3,
        error_message=None,
    )
    from model_sentinel.models import NormalizedModel, canonical_json

    store.save_snapshot_models(
        scrape_id=scrape_id,
        provider_id="openrouter",
        models=[
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="zai-org/glm-4.5",
                display_name="zai-org/glm-4.5",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=None,
                output_price=None,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "zai-org/glm-4.5"}),
            ),
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="zai-org/glm-4.6",
                display_name="zai-org/glm-4.6",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=None,
                output_price=None,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "zai-org/glm-4.6"}),
            ),
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="route-llm",
                display_name="route-llm",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=None,
                output_price=None,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "route-llm"}),
            ),
        ],
    )

    exit_code = cli.main(["history", "--provider", "openrouter", "--model", "list"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "zai-org/" in captured.out
    assert "  - glm-4.5" in captured.out
    assert "  - glm-4.6" in captured.out
    assert "- route-llm" in captured.out


def test_history_model_list_supports_partial_filter(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))
    store = Store(runtime_home / "model_sentinel.db")
    store.initialize()
    scrape_id = store.create_scrape(
        provider_id="openrouter",
        started_at="2026-03-13T12:53:40-04:00",
        completed_at="2026-03-13T12:53:41-04:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=None,
        saved_snapshot=True,
        model_count=3,
        error_message=None,
    )
    from model_sentinel.models import NormalizedModel, canonical_json

    store.save_snapshot_models(
        scrape_id=scrape_id,
        provider_id="openrouter",
        models=[
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="openai/chatgpt-5.2",
                display_name="ChatGPT 5.2",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=None,
                output_price=None,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "openai/chatgpt-5.2", "name": "ChatGPT 5.2"}),
            ),
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="openai/gpt-4.1",
                display_name="GPT-4.1",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=None,
                output_price=None,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "openai/gpt-4.1", "name": "GPT-4.1"}),
            ),
            NormalizedModel(
                provider_id="openrouter",
                provider_label="OpenRouter",
                provider_model_id="anthropic/claude-sonnet-4.5",
                display_name="Claude Sonnet 4.5",
                description=None,
                model_family=None,
                created_at_provider=None,
                context_window=None,
                max_output_tokens=None,
                input_price=None,
                output_price=None,
                cache_read_price=None,
                cache_write_price=None,
                reasoning_supported=None,
                tool_calling_supported=None,
                vision_supported=None,
                audio_supported=None,
                image_supported=None,
                structured_output_supported=None,
                deprecated=None,
                status=None,
                metadata_json=canonical_json({"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5"}),
            ),
        ],
    )

    exit_code = cli.main(["history", "--provider", "openrouter", "--model", "list", "chatgpt"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "chatgpt-5.2" in captured.out.casefold()
    assert "gpt-4.1" not in captured.out.casefold()
    assert "claude-sonnet-4.5" not in captured.out.casefold()


def test_history_pattern_without_model_list_exits_cleanly(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    try:
        cli.main(["history", "--provider", "openrouter", "--model", "chatgpt-5.2", "chatgpt"])
    except SystemExit as exc:
        assert exc.code == 2
    captured = capsys.readouterr()
    assert "only supported with `--model list`" in captured.err


def test_history_with_unknown_provider_exits_cleanly(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_home = _write_config_files(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(runtime_home))

    try:
        cli.main(["history", "--provider", "abacusai", "--model", "list"])
    except SystemExit as exc:
        assert exc.code == 2
    captured = capsys.readouterr()
    assert "Unknown provider 'abacusai'" in captured.err
