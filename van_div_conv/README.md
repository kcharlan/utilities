# van_div_conv

`van_div_conv` takes a Vanguard CSV export, keeps the transaction activity table,
and writes two import files in the current working directory:

- `<input_stem>_cooked.csv` for Actual Budget
- `vanguard_activity_<startYYYYMMDD>_<endYYYYMMDD>.qif` for Moneydance

The command mirrors the `fid_div_conv` workflow: it is a single executable with
runtime state under `~/.van_div_conv/`.

## Behavior

- Skips leading position/holding sections and trailing activity sections.
- Keeps only `Dividend` and `Withdrawal` transaction rows in the cooked CSV.
- Ignores rows such as `Reinvestment` and `Sweep out`.
- Writes dividend QIF entries as investment `MiscInc` transactions.
- Writes withdrawal QIF entries as investment `XOut` transfers to
  `[TD Bank - Checking]`.

## Runtime Config

On first run, the tool writes `~/.van_div_conv/config.json`:

```json
{
  "account_name": "Vanguard",
  "dividend_category": "Investment:Dividends",
  "transfer_account": "TD Bank - Checking",
  "cash_security": "Vanguard Cash",
  "fund_mappings": {
    "VMFXX": "VANGUARD FEDERAL MONEY MARKET INVESTOR CL"
  }
}
```

Edit this file if the Moneydance transfer account, Vanguard account name, or
fund display names need to change.

## Usage

```bash
van_div_conv OfxDownload.csv
```

The output files are written to the directory where the command is run.

## Validation

From `~/source/utilities`, activate the project venv and run:

```bash
source .venv/bin/activate
python -m pytest van_div_conv/tests -v
```
