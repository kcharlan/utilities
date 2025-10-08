from __future__ import annotations
from dataclasses import dataclass
from datetime import date

@dataclass
class QIFConfig:
    payee: str = "Estimated Taxes Withholding"
    federal_expense: str = "Tax:Federal Income Tax Estimated Paid"
    federal_transfer: str = "[Federal Income Taxes]"
    state_expense: str = "Tax:State Income Tax Estimated Paid"
    state_transfer: str = "[GA State Income Taxes]"

def _fmt_date(d: date) -> str:
    return d.strftime("%m/%d/%y")

def _memo(d: date, label: str) -> str:
    return f"{label} - {d.strftime('%m/%d/%Y')}"

def build_qif_entries(tx_date: date, federal_tax: float, state_tax: float, cfg: QIFConfig | None = None) -> str:
    cfg = cfg or QIFConfig()
    lines = ["!Type:Bank"]
    # Federal expense (negative outflow)
    lines += [
        f"D{_fmt_date(tx_date)}",
        f"T{-abs(federal_tax):.2f}",
        f"P{cfg.payee}",
        f"M{_memo(tx_date, 'Estimated Federal taxes')}",
        f"L{cfg.federal_expense}",
        "^",
    ]
    # Federal transfer (positive inflow to transfer account)
    lines += [
        f"D{_fmt_date(tx_date)}",
        f"T{abs(federal_tax):.2f}",
        f"P{cfg.payee}",
        f"M{_memo(tx_date, 'Estimated Federal taxes')}",
        f"L{cfg.federal_transfer}",
        "^",
    ]
    # State expense
    lines += [
        f"D{_fmt_date(tx_date)}",
        f"T{-abs(state_tax):.2f}",
        f"P{cfg.payee}",
        f"M{_memo(tx_date, 'Estimated State taxes')}",
        f"L{cfg.state_expense}",
        "^",
    ]
    # State transfer
    lines += [
        f"D{_fmt_date(tx_date)}",
        f"T{abs(state_tax):.2f}",
        f"P{cfg.payee}",
        f"M{_memo(tx_date, 'Estimated State taxes')}",
        f"L{cfg.state_transfer}",
        "^",
    ]
    return "\n".join(lines)
