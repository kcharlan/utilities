from __future__ import annotations
import pandas as pd
from .engine import compute_tax
from .rules_loader import load_rules
from .models import TaxInput, FilingStatus

def generate_table(rules_path: str, filing_status: str = "single",
                   inc_min: int = 0, inc_max: int = 500000, step: int = 50,
                   period: str = "monthly") -> pd.DataFrame:
    rules = load_rules(rules_path)
    fs = FilingStatus(filing_status)
    rows = []
    for mi in range(inc_min, inc_max + 1, step):
        annual = mi * 12 if period == "monthly" else mi
        tin = TaxInput(annual_income=annual, filing_status=fs)
        tax_annual = compute_tax(tin, rules)
        tax_monthly = round(tax_annual / 12.0, 2)
        rows.append({"MonthlyIncome": mi, "MonthlyTax": tax_monthly})
    return pd.DataFrame(rows)
