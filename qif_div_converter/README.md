# qif_div_converter

A command-line utility for converting Fidelity dividend CSVs into Moneydance-compatible QIF files.

## Overview

`qif_div_converter` is designed to streamline the process of importing dividend transactions from Fidelity's `Accounts_History.csv` files into Moneydance. It extracts only dividend transactions, formats them according to the QIF standard, and ensures compatibility with Moneydance's investment account type. The utility is configuration-driven, allowing users to define accounts and fund mappings via a JSON file.

## Features

- **Fidelity CSV to Moneydance QIF:** Specifically designed to process Fidelity `Accounts_History.csv` files and generate QIF files for Moneydance.
- **Dividend Transactions Only:** Filters out all transactions except "DIVIDEND RECEIVED", excluding "REINVESTMENT" transactions.
- **Configuration-Driven:** Uses `qif_div_converter.json` for flexible configuration of accounts, fund mappings, and transaction categories.
- **Deterministic & Scriptable:** A command-line tool suitable for automated workflows.
- **Warning System:** Provides detailed warnings for malformed, skipped, or excluded records, ensuring no data is silently ignored.
- **Summary Output:** Generates a reconciliation summary table to `stdout` after processing.
- **Shell Wildcard Support:** Accepts multiple CSV files via shell expansion.
- **Current Directory Operation:** All input and output operations occur within the current working directory, avoiding fixed paths.

## Goals

- Provide a deterministic, scriptable CLI tool for transforming Fidelity dividend data into Moneydance QIF format.
- Allow configuration-driven filtering (accounts, funds) without changing utility code.
- Validate output and warn on malformed or skipped records.
- Produce a summary table for reconciliation.

## Non-Goals

- No GUI or interactive prompts.
- No automatic detection of fund mappings.
- No support for reinvestments or complex corporate actions.

## Configuration (`qif_div_converter.json`)

The utility relies on a `qif_div_converter.json` file, which must be located in the same directory as the utility executable/script. This file defines the rules for processing.

### Example Configuration

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

### Configuration Details

-   `accounts`: An array of strings representing the Fidelity account names to include.
-   `fund_mappings`: An object where keys are stock/fund symbols (tickers) and values are the corresponding full names to be used in Moneydance.
-   `category`: The Moneydance category to assign to dividend transactions (e.g., "Investment:Dividends").

New accounts and fund mappings can be added by simply extending their respective sections in the JSON file. The utility will gracefully handle unknown tickers by skipping them with a warning.

## CLI Specification

The utility is executed from the command line with one or more Fidelity CSV files as arguments.

```bash
qif_div_converter <input_csv> [another_input.csv ...]
```

### Requirements

-   The utility accepts relative or absolute paths to CSV files.
-   Shell wildcards (e.g., `*.csv`) are supported for processing multiple files.
-   If multiple files are provided, the utility processes them sequentially, generating one QIF file per input CSV.

## Transaction Inclusion Rules

A transaction row from the Fidelity CSV is processed only if all of the following conditions are met:

1.  **Account Match:** The `Account` field matches one of the configured accounts in `qif_div_converter.json`.
2.  **Symbol Mapping:** The `Symbol` field exists as a key in the `fund_mappings` dictionary in `qif_div_converter.json`.
3.  **Dividend Type:** The transaction type is explicitly "DIVIDEND RECEIVED".
4.  **Not Reinvestment:** The transaction type is *not* "REINVESTMENT".
5.  **Positive Amount:** The `Amount` field is a positive number.

If any of these conditions are not met, the row is skipped, and a warning is emitted to `stderr` explaining the reason for exclusion, including the line number, cause, and relevant field values.

## QIF Output Specification

### File Header

Each generated QIF file will start with:

```
!Type:Invst
```

### Per-Transaction QIF Block

Each dividend transaction will be formatted as a block:

```
D<M/D'YY>
NMiscInc
Y<Mapped Fund Name>
T<Amount rounded to 2 decimals>
MDividend <TICKER>
L<Category from config.json>
^
```

### Formatting Requirements

-   **Date (`D`):** Must be rendered in `M/D'YY` format with an ASCII apostrophe.
-   **Action (`N`):** Always `MiscInc` for dividend income.
-   **Security (`Y`):** The mapped fund name from `fund_mappings`.
-   **Amount (`T`):** The dividend amount, rounded to two decimal places.
-   **Memo (`M`):** "Dividend <TICKER>".
-   **Category (`L`):** The category specified in `qif_div_converter.json`.

## Output Behavior

### Naming Convention

Generated QIF files follow this naming convention:

```
dividends_by_fund_<startYYYYMMDD>_<endYYYYMMDD>.qif
```

These files are created in the current working directory where the utility is executed.

### Validation

Before writing the QIF file, the utility performs validation:

-   Ensures the file begins with `!Type:Invst`.
-   Verifies that there is at least one transaction.
-   Confirms all dates are in the correct apostrophe format.
-   Checks that all amounts are valid decimal numbers with two places.

If validation fails, file generation is aborted, warnings are emitted, and the utility exits with a non-zero status code.

## Summary Output

Upon successful QIF file generation, a summary table is printed to `stdout` for reconciliation:

| Ticker | Count | Total Amount |
| :----- | :---- | :----------- |
|        |       |              |

The totals in this table match the entries in the generated QIF file.

## Error Handling & Warnings

The utility prioritizes transparency and will **never silently skip data**. Warnings are emitted for:

-   Unknown tickers (not found in `fund_mappings`).
-   Missing required CSV fields.
-   Invalid numeric amounts.
-   Invalid or unparsable dates.
-   Rows excluded due to configuration filters.

Warnings will specify the line number, the cause of the exclusion, and relevant field values to aid in troubleshooting.

## Functional Flow

1.  Resolve utility directory and load `qif_div_converter.json`.
2.  Accept CSV path argument(s) (with shell wildcard expansion).
3.  For each input CSV:
    -   Parse rows, validating required fields.
    -   Apply filtering rules (account, ticker, amount, transaction type).
    -   Log warnings for all exclusions.
    -   Generate QIF entries for qualifying rows.
    -   Accumulate statistics for the summary.
4.  Determine date range from transactions and construct the final QIF filename.
5.  Validate the generated QIF content.
6.  Write the QIF file to the current working directory.
7.  Print the summary table to `stdout`.

## Edge Cases

-   **Empty result set:** If no valid transactions are found, an error is printed, and the utility exits non-zero.
-   **CSV with no valid account or symbol column:** This results in a fatal error.
-   **Malformed CSV:** Leads to a fatal error with diagnostic output.
-   **Large files:** The utility is designed for streaming processing, avoiding the need to load entire files into memory.
