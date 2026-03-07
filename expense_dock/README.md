# Expense Dock

Expense Dock is a self-bootstrapping local web utility for a OneDrive-based expense workflow:

- Upload a receipt file into `Business Expenses/YYYY/YYYY-MM/`
- Create the year/month folders if they do not exist
- Create an anonymous read-only share link for the uploaded receipt
- Download the Excel workbook from OneDrive, append a new expense row, and upload the workbook back
- Queue a retry if the receipt upload succeeds but the workbook write fails

## Quick Start

Run the entrypoint directly:

```zsh
./expense_dock
```

Or symlink it into your `PATH`:

```zsh
ln -s "$(pwd)/expense_dock" /usr/local/bin/expense_dock
expense_dock
```

On first run, Expense Dock creates a private virtual environment at `~/.expense_dock_venv` and installs its dependencies automatically.

Runtime state lives under `~/.expense_dock/`:

- `config.json` - saved app config and UI defaults
- `token_cache.json` - Microsoft auth token cache
- `pending/*.json` - queued retry records for workbook append failures
- `last_port` - most recent port used

## Microsoft Setup

Create a Microsoft Entra app registration for a public client:

1. Supported account types: `Personal Microsoft accounts only`
2. Platform: `Mobile and desktop applications`
3. Redirect URI: `http://localhost`

Then paste the app's client ID into the Expense Dock setup panel.

The app uses delegated Microsoft Graph scopes:

- `Files.ReadWrite.All`
- `offline_access`

## Current Workbook Assumptions

This project is currently wired to the provided workbook shape:

- Workbook file at the shared root: `Kevin-Expense_Tracker.xlsx`
- Expense worksheet: `Expense Log`
- Lookup worksheet: `Categories`
- Header row on row 1 with these columns:

```text
ID, Date, Vendor, Amount, Category, Business Purpose, Paid By, Payment Method,
Reimbursable?, Reimb. Status, Receipt Link, Receipt Filename, Notes
```

The `Categories` sheet is expected to expose four lookup columns:

- Column A: Categories
- Column B: Payment Methods
- Column C: Paid By
- Column D: Reimbursement Status

## Notes

- Receipt filenames are normalized to `YYYY-MM-DD-vendor-amount-short purpose.ext`
- If the normalized receipt filename already exists in the target month folder, Expense Dock reuses it instead of uploading again
- If the workbook already contains the same receipt link or receipt filename, Expense Dock treats the submission as already logged and avoids a duplicate row
- Large files use a resumable upload session; small files use a direct upload

## Validation

Smallest relevant checks for this project:

```zsh
./expense_dock --help
./expense_dock --no-browser --port 8420
```
