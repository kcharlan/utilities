# fid_div_conv

`fid_div_conv` merges the old `prep_ledger` and `qif_div_converter` workflows into one command. It takes a raw Fidelity `Accounts History` CSV export, writes a cleaned CSV for Actual Budget import, and writes a Moneydance-compatible dividend QIF in the same run.

The tool is now self-contained for copied or symlinked installs:

- first run creates a runtime home at `~/.fid_div_conv/`
- first run creates a private bootstrap venv at `~/.fid_div_conv/venv/`
- runtime config lives at `~/.fid_div_conv/config.json`
- no colocated config file is required next to the script

## What It Does

- Detects and preserves the real Fidelity header row while skipping leading metadata.
- Writes a cleaned CSV with:
  - dates normalized from `MM/DD/YYYY` to `M/D/YY`
  - integer quantities collapsed from values like `0.000` to `0`
  - footer/disclaimer rows removed
- Filters dividend transactions using a colocated JSON config.
- Writes a QIF file for Moneydance using the configured account and fund mappings.
- Emits warnings for every skipped dividend row instead of silently ignoring them.

## Runtime Home

`fid_div_conv` keeps its runtime state under:

```text
~/.fid_div_conv/
  config.json
  bootstrap_state.json
  venv/
```

If `config.json` does not exist, the tool writes a default config on first run.

If a legacy `fid_div_conv.json` exists next to the script, first run will import that file into `~/.fid_div_conv/config.json` once so existing mappings can carry forward.

## Configuration

The runtime config file is `~/.fid_div_conv/config.json`.

Example:

```json
{
  "accounts": [
    "Individual - TOD"
  ],
  "fund_mappings": {
    "ITWO": "ITWO - PROSHARES TR RUSSELL 2000 HIG",
    "SPAXX": "FIDELITY GOVERNMENT MONEY MARKET"
  },
  "category": "Investment:Dividends"
}
```

## Usage

```bash
fid_div_conv <input_csv> [another_input.csv ...]
```

The CLI follows the old `qif_div_converter` style: input files are positional, so there is no required `-i`, and default output filenames are generated automatically.

Optional flags:

- `-h`, `--help` show the help text
- `-v`, `--verbose` print additional footer-detection information

## Output Files

For each input file, `fid_div_conv` writes both outputs into the current working directory:

- Cleaned CSV: `<input_stem>_cooked.csv`
- Dividend QIF: `dividends_by_fund_<startYYYYMMDD>_<endYYYYMMDD>.qif`

Example:

```bash
fid_div_conv Accounts_History.csv
```

Produces:

- `Accounts_History_cooked.csv`
- `dividends_by_fund_20260107_20260131.qif`

If the ledger cleanup succeeds but the file contains no qualifying dividend transactions, the cooked CSV is still written and the command exits non-zero after reporting the QIF failure.

## Validation

Run the project tests with:

```bash
pytest tests -v
```
