# Tax App (rules-based + QIF export)

Modernizes the original Streamlit tax calculator into a rules-driven engine with optional pre-generated tables and a **byte-compatible QIF export**. The project is organized so you can run ad-hoc Streamlit sessions, batch-generate tax tables, and export Quicken-ready transactions from the same codebase.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

`requirements.txt` covers Streamlit plus the engine dependencies (`pydantic`, `typer`, `numpy`, etc.). Install `pyarrow` if you plan to export Parquet tables.

## Features

- **Rules Engine** – Parse YAML rules describing brackets, deductions, and credits for both federal and state systems. Supports tiered rates, phase outs, and standard deduction logic.
- **Table Lookup** – Load precomputed CSV/Parquet tables to bypass runtime calculations or to cross-check the rules engine for regressions.
- **QIF Export** – Emit four-transaction bundles (federal expense/transfer, state expense/transfer) that import cleanly into Quicken or Moneydance.
- **Consistency Check** – UI mode that compares live rule calculations to table lookup values and flags drift.

## Project Layout

```
app/                # Streamlit UI (streamlit_app.py)
taxkit/             # Core library (engine, rules loader, table generation, QIF writer)
rules/              # Sample YAML rulesets (federal + GA state for 2025)
tables/             # Output location for generated tables
cli.py              # Typer CLI to run table generation jobs
generate_tables.sh  # Example script chaining CLI + merge
merge_tables.py     # Helper to combine federal + state tables into one CSV
tests/              # Placeholder for unit/property tests
```

### Key Modules in `taxkit`

- `engine.py` – Evaluates income against rules to compute per-period tax owed.
- `rules_loader.py` – Validates and parses YAML into typed models (`models.py`).
- `tablegen.py` – Sweeps an income grid and records monthly/annual obligations.
- `qif.py` – Builds transaction text blocks with consistent memo/ledger structure.

## Running the Streamlit App

```bash
streamlit run app/streamlit_app.py
```

Modes available from the sidebar:

1. **Rules Compute** – Select a federal + state ruleset, filing status, and income to compute monthly obligations on the fly.
2. **Table Lookup** – Load `tables/combined_2025.csv` (or any file with `MonthlyIncome`, `FederalMonthlyTax`, `StateMonthlyTax`) and inspect values.
3. **Cross-Check** – Run both engines simultaneously and view deltas.
4. **QIF Export** – Choose income, number of months, and target ledger names to download a `.zip` containing per-month QIF entries.

## Generating Tables from Rules

```bash
python cli.py tablegen \
  --rules rules/federal/2025.yaml \
  --filing-status single \
  --inc-max 500000 \
  --step 50 \
  --out tables/federal_2025.parquet

python cli.py tablegen \
  --rules rules/states/GA/2025.yaml \
  --filing-status single \
  --inc-max 500000 \
  --step 50 \
  --out tables/ga_2025.parquet
```

Combine the outputs if you want a single lookup file:

```python
import pandas as pd

fed = pd.read_parquet("tables/federal_2025.parquet") \
        .rename(columns={"MonthlyTax": "FederalMonthlyTax"})
ga = pd.read_parquet("tables/ga_2025.parquet") \
        .rename(columns={"MonthlyTax": "StateMonthlyTax"})

combined = (pd.merge(fed, ga, on="MonthlyIncome", how="outer")
              .sort_values("MonthlyIncome"))
combined.to_csv("tables/combined_2025.csv", index=False)
```

`generate_tables.sh` automates the sequence above and calls `merge_tables.py` to produce `tables/combined_2025.csv`.

## Table Format Expectations

- Combined table: `MonthlyIncome`, `FederalMonthlyTax`, `StateMonthlyTax`.
- Individual tables: `MonthlyIncome`, `MonthlyTax` (federal) and the same for state.
- All amounts are monthly; annual values are derived in the UI when needed.

## QIF Output

- Each payment cycle generates four transactions:
  1. Expense: `Tax:Federal Income Tax Estimated Paid`
  2. Transfer: `[Federal Income Taxes]`
  3. Expense: `Tax:State Income Tax Estimated Paid`
  4. Transfer: `[GA State Income Taxes]` (customizable in the UI)
- Dates follow `MM/DD/YY` format inside QIF while memo lines keep `MM/DD/YYYY`.
- Output is byte-compatible with the earlier `md-autotax` tooling.

## Testing

Basic scaffolding lives in `tests/`. Add property tests that sweep random incomes against known tables or snapshot tests for QIF output when you expand coverage.

## Extending

- Add new states by dropping YAML files under `rules/states/{STATE}/{YEAR}.yaml`.
- Introduce additional credit/phase-out models by expanding `taxkit.models` and updating the engine dispatcher.
- To support other export formats, create new writers alongside `taxkit.qif` and wire them into the Streamlit download options.
