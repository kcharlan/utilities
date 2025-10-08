from __future__ import annotations
import yaml
from .models import TaxRules, FilingStatus, Bracket, Credit

def load_rules(path: str) -> TaxRules:
    with open(path, 'r') as f:
        data = yaml.safe_load(f)

    # Convert keys for enums
    fs_list = [FilingStatus(x) for x in data['filing_statuses']]
    std_ded = {FilingStatus(k): float(v) for k, v in data['standard_deduction'].items()}
    brackets = {FilingStatus(k): [Bracket(**b) for b in v] for k, v in data['brackets'].items()}
    credits = [Credit(**c) for c in data.get('credits', [])]

    return TaxRules(
        year=int(data['year']),
        jurisdiction=str(data['jurisdiction']),
        filing_statuses=fs_list,
        standard_deduction=std_ded,
        brackets=brackets,
        credits=credits,
    )
