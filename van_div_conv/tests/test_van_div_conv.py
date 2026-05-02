import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "van_div_conv"


def install_tool(tmp_path):
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    tool_path = install_dir / "van_div_conv"
    shutil.copy2(SCRIPT_PATH, tool_path)
    os.chmod(tool_path, 0o755)
    return tool_path


def run_tool(tmp_path, csv_name, csv_text):
    tool_path = install_tool(tmp_path)
    input_path = tmp_path / csv_name
    input_path.write_text(textwrap.dedent(csv_text).lstrip(), encoding="utf-8")
    runtime_home = tmp_path / "runtime_home"
    env = os.environ.copy()
    env["VAN_DIV_CONV_HOME"] = str(runtime_home)
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
    env["VAN_DIV_CONV_HOME"] = str(runtime_home)
    result = subprocess.run(
        [sys.executable, str(tool_path), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert "usage: van_div_conv" in result.stdout
    assert not runtime_home.exists()


def test_generates_actual_csv_and_moneydance_qif_from_vanguard_export(tmp_path):
    result, _, runtime_home = run_tool(
        tmp_path,
        "OfxDownload.csv",
        """
        Account Number,Investment Name,Symbol,Shares,Share Price,Total Value,
        57821940,VANGUARD FEDERAL MONEY MARKET INVESTOR CL,VMFXX,515000,1,515000,



        Account Number,Trade Date,Settlement Date,Transaction Type,Transaction Description,Investment Name,Symbol,Shares,Share Price,Principal Amount,Commissions and Fees,Net Amount,Accrued Interest,Account Type,
        57821940,2026-04-30,2026-04-30,Dividend,Dividend Received,VANGUARD FEDERAL MONEY MARKET INVESTOR CL,VMFXX,0.00000,0.0,1492.03,0.0,1492.03,0.0,CASH,
        57821940,2026-04-30,2026-04-30,Reinvestment,Dividend Reinvestment,VANGUARD FEDERAL MONEY MARKET INVESTOR CL,VMFXX,0.00000,0.0,-1492.03,0.0,-1492.03,0.0,CASH,
        57821940,2026-05-01,2026-05-01,Sweep out,Sweep Out Of Settlement Fund,VANGUARD FEDERAL MONEY MARKET INVESTOR CL,VMFXX,0.00000,1.0,1492.03,0.0,1492.03,0.0,CASH,
        57821940,2026-05-01,2026-05-01,Withdrawal,Withdrawal via Electronic Bank Transfer,CASH,,0.00000,0.0,-1492.03,0.0,-1492.03,0.0,CASH,


        Account Number,Trade Date,Run Date,Transaction Activity,Transaction Description,Investment Name,Share Price,Transaction Shares,Dollar Amount,
        """,
    )

    assert result.returncode == 0, result.stderr

    cooked_path = tmp_path / "OfxDownload_cooked.csv"
    qif_path = tmp_path / "vanguard_activity_20260430_20260501.qif"

    assert cooked_path.exists()
    assert qif_path.exists()
    assert (runtime_home / "config.json").exists()
    assert (runtime_home / "bootstrap_state.json").exists()
    assert (runtime_home / "venv" / "bin" / "python").exists()

    cooked_text = cooked_path.read_text(encoding="utf-8")
    qif_text = qif_path.read_text(encoding="utf-8")

    assert cooked_text.startswith(
        "Account Number,Trade Date,Settlement Date,Transaction Type,"
    )
    assert "Dividend,Dividend Received" in cooked_text
    assert "Withdrawal,Withdrawal via Electronic Bank Transfer" in cooked_text
    assert "Reinvestment" not in cooked_text
    assert "Sweep out" not in cooked_text
    assert "Account Number,Investment Name" not in cooked_text
    assert "Transaction Activity" not in cooked_text

    assert qif_text.startswith("!Account\nNVanguard\nTInvst\n^\n!Type:Invst\n")
    assert "D4/30'26\nNMiscInc\nYVANGUARD FEDERAL MONEY MARKET INVESTOR CL" in qif_text
    assert "T1492.03" in qif_text
    assert "MDividend VMFXX" in qif_text
    assert "LInvestment:Dividends" in qif_text
    assert "D5/1'26\nNXOut\nYVanguard Cash" in qif_text
    assert "T1492.03" in qif_text
    assert "MWithdrawal via Electronic Bank Transfer" in qif_text
    assert "L[TD Bank - Checking]" in qif_text
    assert "Reinvestment" not in qif_text
    assert "Sweep Out" not in qif_text

    assert "Generated CSV: OfxDownload_cooked.csv" in result.stdout
    assert "Generated QIF: vanguard_activity_20260430_20260501.qif" in result.stdout
    assert "Dividend" in result.stdout
    assert "Withdrawal" in result.stdout
    assert "Skipped Transaction Type 'Reinvestment'" in result.stderr
    assert "Skipped Transaction Type 'Sweep out'" in result.stderr


def test_exits_nonzero_when_no_supported_transactions(tmp_path):
    result, _, _ = run_tool(
        tmp_path,
        "empty.csv",
        """
        Account Number,Trade Date,Settlement Date,Transaction Type,Transaction Description,Investment Name,Symbol,Shares,Share Price,Principal Amount,Commissions and Fees,Net Amount,Accrued Interest,Account Type,
        57821940,2026-04-30,2026-04-30,Reinvestment,Dividend Reinvestment,VANGUARD FEDERAL MONEY MARKET INVESTOR CL,VMFXX,0.00000,0.0,-1492.03,0.0,-1492.03,0.0,CASH,
        """,
    )

    assert result.returncode == 1
    assert (tmp_path / "empty_cooked.csv").exists()
    assert "No valid Vanguard transactions found" in result.stderr
