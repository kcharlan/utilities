# usage-monthly-csv

Standalone Zsh utility that runs `ccusage_csv` and `cusage_csv` for the appropriate month and writes `MMYY`-suffixed CSV files to Downloads by default.

## What It Does

- Detects the current month and runs both upstream CSV commands with `--since YYYYMM01`.
- Writes output files to `~/Downloads` by default as:
  - `ccusage-MMYY.csv`
  - `cusage-MMYY.csv`
- Normalizes the CSV `date` column to ISO `YYYY-MM-DD` when upstream tools emit display-formatted dates.
- Automatically includes both the current month and the prior month during the first 2 days of a new month.
- Supports an explicit prior-month mode for manual backfills after the boundary window.
- Accepts `--date` in either `YYYY-MM-DD` or `YYYYMMDD`, normalizes internally, and still passes `YYYYMMDD`-style values to the upstream commands.
- Falls back to `zsh -ic` when the report generators are defined as shell functions in `~/.zshrc` instead of standalone executables.

## Requirements

- macOS with `zsh` and BSD `date`.
- `ccusage_csv` and `cusage_csv` available either:
  - directly on `PATH`, or
  - as functions/aliases loaded by interactive Zsh startup files such as `~/.zshrc`

## Installation

Copy or symlink the executable into `~/Library/Scripts` if you want to run it from your personal scripts directory:

```bash
chmod +x /Users/kevinharlan/source/utilities/usage-monthly-csv/usage-monthly-csv
ln -sf /Users/kevinharlan/source/utilities/usage-monthly-csv/usage-monthly-csv ~/Library/Scripts/usage-monthly-csv
```

If `~/Library/Scripts` is not already on your shell `PATH`, add it in `~/.zshrc`:

```bash
export PATH="$PATH:$HOME/Library/Scripts"
```

## Usage

```bash
usage-monthly-csv
usage-monthly-csv --prior-month
usage-monthly-csv --output-dir ~/Downloads
usage-monthly-csv --date 2026-01-02
usage-monthly-csv --boundary-days 3
```

Run `usage-monthly-csv --help` for the full switch reference.

### Defaults

- Output directory: `~/Downloads`
- Boundary window: first `2` days of the month
- Standard run: current month only
- Boundary run: current month plus prior month
- Prior month override: `--prior-month` runs only the prior month

## Validation

Repo-local regression harness:

```bash
zsh /Users/kevinharlan/source/utilities/usage-monthly-csv/tests/test_usage_monthly_csv.zsh
```

Safe shell-utility validation:

```bash
/Users/kevinharlan/source/utilities/usage-monthly-csv/usage-monthly-csv --help
```
