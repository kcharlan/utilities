# prep_ledger

`prep_ledger` is a Python CLI utility designed to clean and reformat Fidelity "Accounts History" CSV exports. It automates the preparation of these files for import into personal finance software or spreadsheets by normalizing dates, cleaning number formats, and stripping unnecessary headers and footers.

## Features

- **Header Detection:** Automatically skips leading metadata to locate the actual column headers.
- **Date Formatting:** Converts dates from `MM/DD/YYYY` (e.g., `01/07/2026`) to a more compact `M/D/YY` (e.g., `1/7/26`) format.
- **Number Cleanup:** Removes unnecessary precision from quantity fields (e.g., converts `0.000` to `0`).
- **Footer Removal:** Strips legal disclaimers and empty lines from the end of the file.
- **Robustness:** Handles standard Fidelity CSV exports including those with metadata "Run Date" rows.

## Installation

1.  **Download/Copy the script:**
    Ensure you have the `prep_ledger` file.

2.  **Make it executable:**
    ```bash
    chmod +x prep_ledger
    ```

3.  **Move to your PATH:**
    To use it from anywhere, move it to a directory in your system PATH, such as `~/Library/Scripts` or `/usr/local/bin`.
    ```bash
    mv prep_ledger ~/Library/Scripts/
    ```

## Usage

Run the script from your terminal.

```bash
prep_ledger [options]
```

### Options

| Option | Description | Default |
| :--- | :--- | :--- |
| `-h`, `--help` | Show the help message and exit. | |
| `-i`, `--input` | Path to the source CSV file. | `Accounts_History.csv` |
| `-o`, `--output` | Path for the cleaned output CSV file. | `Accounts_History_cooked.csv` |
| `-v`, `--verbose` | Enable detailed output during processing. | `False` |

### Examples

**Standard Usage (defaults):**
Process `Accounts_History.csv` in the current directory and output `Accounts_History_cooked.csv`.
```bash
prep_ledger
```

**Custom Files:**
```bash
prep_ledger -i "Downloads/MyPortfolio.csv" -o "Documents/Finance/2026_Clean.csv"
```

**Verbose Mode:**
See exactly what the script is doing.
```bash
prep_ledger -v
```

## Requirements

- Python 3.6 or higher (standard on macOS).
