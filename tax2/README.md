# Tax App (rules-based + QIF export)

A rules-driven tax calculator with optional pre-generated tables and **byte-compatible QIF export**. Uses a self-bootstrapping FastAPI backend with an embedded React SPA (no Streamlit, no Node.js tooling). You can run the web UI, batch-generate tax tables via CLI, and export Quicken-ready transactions from the same codebase.

## Quick Start

```bash
# No setup required - just run
./tax2

# Or with custom port
./tax2 --port 9000

# Don't auto-open browser
./tax2 --no-browser

# Optional custom rules directory
./tax2 /path/to/rules

# CLI mode for table generation (uses same venv)
./.tax2_venv/bin/python cli.py generate-combined --year 2026
```

On first run, the `tax2` script will automatically:
- Create a private virtual environment at `.tax2_venv`
- Install all required dependencies (FastAPI, uvicorn, pandas, pyyaml, etc.)
- Start the web server on port 8000
- Open your browser

Subsequent runs start instantly.

## Features

- **Rules Engine** – Parse YAML rules describing brackets, deductions, and credits for both federal and state systems. Supports tiered rates, phase outs, and standard deduction logic.
- **Dynamic Year Selection** – Automatically defaults to the current tax year. Allows manual selection of other available years and falls back to the latest rules if the current year's rules are missing.
- **Table Lookup** – Load precomputed CSV/Parquet tables to bypass runtime calculations or to cross-check the rules engine for regressions.
- **QIF Export** – Emit four-transaction bundles (federal expense/transfer, state expense/transfer) that import cleanly into Quicken or Moneydance.
- **Consistency Check** – UI mode that compares live rule calculations to table lookup values and flags drift.

## Project Layout

```
tax2                # Self-bootstrapping entry point (FastAPI server + embedded React SPA)
cli.py              # Typer CLI for table generation (tablegen, generate-combined)
taxkit/             # Core library (engine, rules loader, table generation, QIF writer, utils)
rules/              # YAML rulesets
  federal/          #   Federal brackets (2025.yaml, 2026.yaml)
  states/GA/        #   Georgia state rules (2025.yaml, 2026.yaml)
tables/             # Output location for generated tables (Parquet + CSV)
tests/              # Placeholder for unit/property tests
docs/               # Design docs (Tech_migration.md, UI_Design_Reference.html, Usage.md)
archive/            # Previous Streamlit version (archive/streamlit_version/)
```

### Key Modules in `taxkit`

- `engine.py` – Evaluates income against rules to compute per-period tax owed.
- `rules_loader.py` – Validates and parses YAML into typed models (`models.py`).
- `tablegen.py` – Sweeps an income grid and records monthly/annual obligations.
- `qif.py` – Builds transaction text blocks with consistent memo/ledger structure.
- `utils.py` – Handles year selection and rule path resolution logic.

## Running the Web UI

```bash
./tax2
```

The embedded React SPA communicates with the FastAPI backend via `/api/*` JSON endpoints. Available modes:

1. **Rules Compute** – Select a tax year (defaults to current), federal + state ruleset, filing status, and income to compute monthly obligations on the fly.
2. **Table Lookup** – Load a pre-generated combined CSV table and inspect values.
3. **Cross-Check** – Run both engines simultaneously and view deltas.
4. **QIF Export** – Choose income, number of months, and target ledger names to download QIF entries.

## Generating Tables from Rules

To generate both Federal and State tables and merge them into a single CSV (replaces the old `generate_tables.sh` script):

```bash
# Generate for the current year
python3 cli.py generate-combined

# Generate for a specific year
python3 cli.py generate-combined --year 2026
```

This will produce:
- `tables/federal_YYYY.parquet`
- `tables/ga_YYYY.parquet`
- `tables/combined_YYYY.csv`



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
- To support other export formats, create new writers alongside `taxkit.qif` and wire them into the UI download options.
