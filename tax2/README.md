# Tax App (rules-based + QIF export)

Modernizes the original Streamlit tax calculator into a rules-driven engine with optional pre-generated tables and a **byte-compatible QIF export**. The project is organized so you can run ad-hoc Streamlit sessions, batch-generate tax tables, and export Quicken-ready transactions from the same codebase.

## Quick Start

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the application
streamlit run app/streamlit_app.py
```

`requirements.txt` covers Streamlit plus the engine dependencies (`pydantic`, `typer`, `numpy`, `pyarrow`, etc.).

## Features

- **Rules Engine** – Parse YAML rules describing brackets, deductions, and credits for both federal and state systems. Supports tiered rates, phase outs, and standard deduction logic.
- **Dynamic Year Selection** – Automatically defaults to the current tax year. Allows manual selection of other available years and falls back to the latest rules if the current year's rules are missing.
- **Table Lookup** – Load precomputed CSV/Parquet tables to bypass runtime calculations or to cross-check the rules engine for regressions.
- **QIF Export** – Emit four-transaction bundles (federal expense/transfer, state expense/transfer) that import cleanly into Quicken or Moneydance.
- **Consistency Check** – UI mode that compares live rule calculations to table lookup values and flags drift.

## Project Layout

```
app/                # Streamlit UI (streamlit_app.py)
taxkit/             # Core library (engine, rules loader, table generation, QIF writer, utils)
rules/              # YAML rulesets (federal + state, e.g., rules/federal/2026.yaml)
tables/             # Output location for generated tables (e.g., combined_2025.csv)
cli.py              # Typer CLI to run table generation jobs
generate_tables.sh  # Example script chaining CLI + merge
merge_tables.py     # Helper to combine federal + state tables into one CSV
run.sh              # Convenience wrapper to launch the Streamlit app
tests/              # Placeholder for unit/property tests
```

### Key Modules in `taxkit`

- `engine.py` – Evaluates income against rules to compute per-period tax owed.
- `rules_loader.py` – Validates and parses YAML into typed models (`models.py`).
- `tablegen.py` – Sweeps an income grid and records monthly/annual obligations.
- `qif.py` – Builds transaction text blocks with consistent memo/ledger structure.
- `utils.py` – Handles year selection and rule path resolution logic.

## Running the Streamlit App

```bash
# Ensure venv is active and dependencies are installed first
./run.sh
```

Modes available from the sidebar:

1. **Rules Compute** – Select a tax year (defaults to current), federal + state ruleset, filing status, and income to compute monthly obligations on the fly.
2. **Table Lookup** – Load `tables/combined_2025.csv` (or any file with `MonthlyIncome`, `FederalMonthlyTax`, `StateMonthlyTax`) and inspect values.
3. **Cross-Check** – Run both engines simultaneously and view deltas.
4. **QIF Export** – Choose income, number of months, and target ledger names to download a `.zip` containing per-month QIF entries.

## Generating Tables from Rules

```bash
# Generate tables for a specific year (defaults to current year if omitted)
python cli.py --year 2026 --out tables/federal_2026.parquet
```

The `generate_tables.sh` script automates the process of generating tables for a default year. You can modify it or run the CLI directly to target different years.



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
