# MD AutoTax
Streamlit + CLI utilities for generating Quicken Interchange Format (QIF) files that record estimated state and federal tax payments. Built around a flexible CSV tax table and a YAML-based rules engine shared with the `tax2` project.

## Components

- `app.py` – Streamlit UI for browsing a tax table, previewing payments, and exporting monthly QIF files in a zipped bundle.
- `tax_qif_generator_grouped.py` – Command-line helper that emits a single `.qif` file for a chosen income/date pair.
- `Tax-table.csv` – Sample combined table containing columns for monthly income, federal tax, and state tax.
- `setup.sh` – Recreates the `venv/` directory and installs the minimal dependencies (`pandas`). Install `streamlit` as well when running the UI.
- `ui.sh` – Convenience script to activate the venv and run the Streamlit app.

## Environment

```bash
./setup.sh
source venv/bin/activate
pip install streamlit pandas  # whisper/openai optional unless you extend the UI
```

## Using the Streamlit UI

```bash
streamlit run app.py
```

1. Point the “Tax Table CSV Path” input at your `Tax-table.csv`, or upload a CSV directly.
2. Select your monthly gross income from the formatted selector; the app shows federal/state taxes and total.
3. Choose a payment schedule, applicable months, and output directory.
4. Click **Generate QIF Files** to download a zip with four transactions per month (expense + transfer for both jurisdictions).

### Notable Features

- Aggressive input validation: the app re-parses currency strings, strips symbols, and reports missing columns.
- Session state keeps your selections sticky across reruns.
- Uses atomic writes when persisting generated bundles to avoid partial files.
- Optional theming/polish to match other internal Streamlit tooling.

## Command-Line Generation

```bash
python tax_qif_generator_grouped.py \
  --income 13000 \
  --date 06/04/2025 \
  --tax-table Tax-table.csv \
  --output-dir ./exports
```

This writes `exports/tax_entries_2025-06-04.qif` containing four transactions (federal expense/transfer, state expense/transfer) with your memo format.

## Customizing the Tax Table

- Keep the exact header names (or adjust the parsing logic in `app.py`) if you modify column labels.
- Additional jurisdictions can be added by extending the QIF generation helper; the Streamlit app already separates federal and state so you can piggyback third entries.

## Troubleshooting

- If the UI rejects your CSV, confirm the headers include phrases similar to “Monthly Gross Income”, “Federal Monthly Tax”, and “State Monthly Tax”; the loader performs fuzzy matching but still requires those tokens.
- Streamlit runs need a writable temp directory because uploaded files are staged before parsing.
- For QIF files intended for Quicken, keep amounts as monthly totals; the app uses two-step transactions (expense + transfer) that import cleanly.
