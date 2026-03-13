from pathlib import Path

from argparse import Namespace
import os

import model_sentinel.cli as cli
from model_sentinel.config import ProviderConfig
from model_sentinel.models import BaselineInfo
from model_sentinel.storage import Store


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
