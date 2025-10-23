# HYSA vs CD Excel Generator
Creates a multi-tab Excel workbook that compares a high-yield savings account (HYSA) against a set of certificate of deposit (CD) maturities. All configuration lives in `inputs.csv`, and the generated workbook mirrors the original template you reconciled against.

## Files

- `hysa_vs_cd_model.py` – Core script that builds the workbook with `xlsxwriter`.
- `inputs.csv` – Parameter sheet read into the Inputs tab (rates, durations, sensitivities).
- `CD_vs_HYSA_Model_TEMPLATE_MATCH.xlsx` – The main output file, overwritten each run.
- `output.xlsx` – A leftover file from a previous version, can be removed.
- `setup.sh` – Bootstraps a virtual environment with the required packages.

## Environment

```bash
./setup.sh          # creates venv/ and installs pandas + xlsxwriter
source venv/bin/activate
```

`xlsxwriter` handles all formatting; Excel or Numbers can open the resulting file.

## Running the Generator

1. Edit `inputs.csv` to reflect the scenarios you want to compare. Every row contains a `Parameter` name and a `Value`. Rates expressed as percentages should use decimal form (e.g., `0.045` for 4.5%).
2. Execute:
   ```bash
   python hysa_vs_cd_model.py
   ```
3. Open `CD_vs_HYSA_Model_TEMPLATE_MATCH.xlsx` to inspect the results. Tabs created:
   - **Inputs** – Mirrors `inputs.csv` with number formatting applied.
   - **Monthly Balances** – Month-by-month HYSA and CD ladder balances with dynamic rates.
   - **Simple** – Placeholder sheet for manual annotations or ad-hoc formulas.
   - **Output** – Summary table comparing final balances across strategies with highlighting for the best performer.

## Implementation Notes

- Rate steps are clamped at zero, so negative rate drifts will floor at 0%.
- CD rates inherit the HYSA rate change cadence and optionally scale by the `CD Sensitivity` parameter to widen or narrow spreads.
- Monthly balance computations compound monthly interest; change the formulas in `hysa_vs_cd_model.py` if you need different compounding.

## Extending

- Add more CD tenors by appending to the `cd_terms` list. The script dynamically builds headers and formulas.
- Swap the `output_headers` list to add new summary metrics (e.g., average balance, total interest).
- For scenario analysis, duplicate `inputs.csv` into multiple files and generate separate workbooks per scenario.
