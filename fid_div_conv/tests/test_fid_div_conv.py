import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "fid_div_conv"


def install_tool(tmp_path, legacy_config=None):
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    tool_path = install_dir / "fid_div_conv"
    shutil.copy2(SCRIPT_PATH, tool_path)
    os.chmod(tool_path, 0o755)
    if legacy_config is not None:
        (install_dir / "fid_div_conv.json").write_text(
            json.dumps(legacy_config, indent=2) + "\n",
            encoding="utf-8",
        )
    return tool_path


def run_tool(tmp_path, csv_name, csv_text, legacy_config=None):
    tool_path = install_tool(tmp_path, legacy_config=legacy_config)
    input_path = tmp_path / csv_name
    input_path.write_text(textwrap.dedent(csv_text).lstrip(), encoding="utf-8")
    runtime_home = tmp_path / "runtime_home"
    env = os.environ.copy()
    env["FID_DIV_CONV_HOME"] = str(runtime_home)
    result = subprocess.run(
        [sys.executable, str(tool_path), str(input_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    return result, input_path, runtime_home


def test_help_does_not_create_runtime_state(tmp_path):
    tool_path = install_tool(tmp_path)
    runtime_home = tmp_path / "runtime_home"
    env = os.environ.copy()
    env["FID_DIV_CONV_HOME"] = str(runtime_home)
    result = subprocess.run(
        [sys.executable, str(tool_path), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert "usage: fid_div_conv" in result.stdout
    assert not runtime_home.exists()


def test_first_run_bootstraps_runtime_home_and_generates_outputs(tmp_path):
    result, _, runtime_home = run_tool(
        tmp_path,
        "Accounts_History.csv",
        """
        Account History Export

        Run Date,Account,Action,Symbol,Amount ($),Quantity
        01/07/2026,Individual - TOD,DIVIDEND RECEIVED,ITWO,358.57,0.000
        01/08/2026,Individual - TOD,REINVESTMENT,ITWO,10.00,1.000
        01/09/2026,Other Account,DIVIDEND RECEIVED,ITWO,20.00,0.000
        01/10/2026,Individual - TOD,DIVIDEND RECEIVED,SPAXX,$5.00,2.000
        01/11/2026,Individual - TOD,DIVIDEND RECEIVED,XDTE,7.00,1.000
        Important Information,See disclosure,,,, 
        """,
    )

    assert result.returncode == 0, result.stderr

    cooked_path = tmp_path / "Accounts_History_cooked.csv"
    qif_path = tmp_path / "dividends_by_fund_20260107_20260111.qif"
    config_path = runtime_home / "config.json"
    bootstrap_path = runtime_home / "bootstrap_state.json"
    venv_python = runtime_home / "venv" / "bin" / "python"

    assert cooked_path.exists()
    assert qif_path.exists()
    assert config_path.exists()
    assert bootstrap_path.exists()
    assert venv_python.exists()

    cooked_text = cooked_path.read_text(encoding="utf-8")
    qif_text = qif_path.read_text(encoding="utf-8")
    runtime_config = json.loads(config_path.read_text(encoding="utf-8"))

    assert "1/7/26" in cooked_text
    assert "1/10/26" in cooked_text
    assert "1/11/26" in cooked_text
    assert ",0\n" in cooked_text
    assert ",2\n" in cooked_text
    assert "Important Information" not in cooked_text

    assert qif_text.startswith("!Type:Invst\n")
    assert "D1/7'26" in qif_text
    assert "D1/10'26" in qif_text
    assert "D1/11'26" in qif_text
    assert "YITWO - PROSHARES TR RUSSELL 2000 HIG" in qif_text
    assert "YFIDELITY GOVERNMENT MONEY MARKET" in qif_text
    assert "YXDTE ROUNDHILL ETF TRUST S&P 500 0DTE COVERED CALL STRATEGY ETF" in qif_text
    assert "T358.57" in qif_text
    assert "T5.00" in qif_text
    assert "T7.00" in qif_text
    assert "Dividend ITWO" in qif_text
    assert "Dividend SPAXX" in qif_text
    assert "Dividend XDTE" in qif_text
    assert "REINVESTMENT" not in qif_text
    assert runtime_config["accounts"] == ["Individual - TOD"]
    assert runtime_config["fund_mappings"]["ITWO"] == "ITWO - PROSHARES TR RUSSELL 2000 HIG"
    assert runtime_config["fund_mappings"]["JEPI"] == "JEPI"
    assert runtime_config["fund_mappings"]["SDIV"] == "SDIV - Global X SuperDividend Etf"
    assert runtime_config["fund_mappings"]["SPYI"] == "SPYI - NEOS ETF TRUST NEOS S&P 500 HI"
    assert runtime_config["fund_mappings"]["ULTY"] == "ULTY - TIDAL TRUST II YIELDMAX ULTRA OPTION INCM STRATEGY ETF"
    assert runtime_config["fund_mappings"]["XDTE"] == "XDTE ROUNDHILL ETF TRUST S&P 500 0DTE COVERED CALL STRATEGY ETF"

    assert "Generated CSV: Accounts_History_cooked.csv" in result.stdout
    assert "Generated QIF: dividends_by_fund_20260107_20260111.qif" in result.stdout
    assert "ITWO" in result.stdout
    assert "SPAXX" in result.stdout
    assert "XDTE" in result.stdout
    assert "[fid_div_conv] Preparing private runtime" in result.stderr
    assert "[fid_div_conv] Wrote default runtime config" in result.stderr
    assert "Skipped Action 'REINVESTMENT' (is Reinvestment)" in result.stderr
    assert "Skipped Account 'Other Account' (not in config)" in result.stderr


def test_runtime_config_is_seeded_once_from_legacy_adjacent_file_and_then_persists(tmp_path):
    legacy_config = {
        "accounts": ["Brokerage"],
        "fund_mappings": {
            "ABC": "ABC - CUSTOM FUND",
        },
        "category": "Investment:Custom",
    }
    result, _, runtime_home = run_tool(
        tmp_path,
        "legacy.csv",
        """
        Fidelity Export
        Run Date,Account,Action,Symbol,Amount ($),Quantity
        01/07/2026,Brokerage,DIVIDEND RECEIVED,ABC,12.34,0.000
        Footer,See disclosure,,,, 
        """,
        legacy_config=legacy_config,
    )

    assert result.returncode == 0, result.stderr
    runtime_config_path = runtime_home / "config.json"
    assert runtime_config_path.exists()
    runtime_config = json.loads(runtime_config_path.read_text(encoding="utf-8"))
    assert runtime_config["accounts"] == legacy_config["accounts"]
    assert runtime_config["category"] == legacy_config["category"]
    assert runtime_config["fund_mappings"]["ABC"] == "ABC - CUSTOM FUND"
    assert runtime_config["fund_mappings"]["JEPI"] == "JEPI"
    assert runtime_config["fund_mappings"]["SPYI"] == "SPYI - NEOS ETF TRUST NEOS S&P 500 HI"
    assert runtime_config["fund_mappings"]["XDTE"] == "XDTE ROUNDHILL ETF TRUST S&P 500 0DTE COVERED CALL STRATEGY ETF"
    assert "[fid_div_conv] Seeded runtime config from legacy file" in result.stderr

    (tmp_path / "install" / "fid_div_conv.json").unlink()
    second_input = tmp_path / "second.csv"
    second_input.write_text(
        textwrap.dedent(
            """
            Fidelity Export
            Run Date,Account,Action,Symbol,Amount ($),Quantity
            01/08/2026,Brokerage,DIVIDEND RECEIVED,ABC,1.00,1.000
            Footer,See disclosure,,,,
            """
        ).lstrip(),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["FID_DIV_CONV_HOME"] = str(runtime_home)
    second = subprocess.run(
        [sys.executable, str(tmp_path / "install" / "fid_div_conv"), str(second_input)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )

    assert second.returncode == 0, second.stderr
    assert "Generated QIF: dividends_by_fund_20260108_20260108.qif" in second.stdout
    assert "[fid_div_conv] Seeded runtime config from legacy file" not in second.stderr


def test_existing_runtime_config_is_backfilled_with_missing_builtin_mappings(tmp_path):
    tool_path = install_tool(tmp_path)
    runtime_home = tmp_path / "runtime_home"
    runtime_home.mkdir()
    (runtime_home / "config.json").write_text(
        json.dumps(
            {
                "accounts": ["Individual - TOD"],
                "fund_mappings": {
                    "ITWO": "ITWO - PROSHARES TR RUSSELL 2000 HIG",
                    "SPAXX": "FIDELITY GOVERNMENT MONEY MARKET",
                },
                "category": "Investment:Dividends",
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    input_path = tmp_path / "backfill.csv"
    input_path.write_text(
        textwrap.dedent(
            """
            Fidelity Export
            Run Date,Account,Action,Symbol,Amount ($),Quantity
            01/07/2026,Individual - TOD,DIVIDEND RECEIVED,JEPI,4.56,1.000
            Footer,See disclosure,,,,
            """
        ).lstrip(),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["FID_DIV_CONV_HOME"] = str(runtime_home)
    result = subprocess.run(
        [sys.executable, str(tool_path), str(input_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "Added missing built-in fund mappings" in result.stderr
    config = json.loads((runtime_home / "config.json").read_text(encoding="utf-8"))
    assert config["fund_mappings"]["JEPI"] == "JEPI"
    assert config["fund_mappings"]["SPYI"] == "SPYI - NEOS ETF TRUST NEOS S&P 500 HI"
    assert config["fund_mappings"]["ULTY"] == "ULTY - TIDAL TRUST II YIELDMAX ULTRA OPTION INCM STRATEGY ETF"
    assert config["fund_mappings"]["XDTE"] == "XDTE ROUNDHILL ETF TRUST S&P 500 0DTE COVERED CALL STRATEGY ETF"
    assert "Generated QIF: dividends_by_fund_20260107_20260107.qif" in result.stdout
